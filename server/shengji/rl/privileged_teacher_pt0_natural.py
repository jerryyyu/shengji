"""Bounded, outcome-blind PT0 state capture on real engine rounds.

This module is intentionally a source core.  Importing it does not construct
an engine, select a policy, or open a writer; the only entry point which does
any of those things is :func:`run_natural_packet`.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import math
import os
import random
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Mapping, Sequence

from .privileged_teacher_pt0 import (
    PrivilegedTeacherPT0Error,
    canonical_json_bytes,
    evaluate_named_baseline,
    information_set_target,
    pt0_public_state_sha256,
    run_pt0_miniature,
)


NATURAL_PT0_SCHEMA = "privileged-teacher-pt0-natural-packet-v1"
NATURAL_PT0_RECORD_SCHEMA = "privileged-teacher-pt0-natural-state-v1"
ROLE_BUCKETS = ("banker-team", "attacker-team")
REMAINING_HAND_THRESHOLDS = (2, 3)
BASELINE_POLICIES = ("heuristic", "smart", "mc-s0-report-lcb")
SAMPLER_ESTIMAND = (
    "production-mcbot-constraint-sampler-algorithmic-distribution-v1")
BOOTSTRAP_UNIT = "capture-round-cluster-v1"


class NaturalPT0Error(PrivilegedTeacherPT0Error):
    """A natural-state PT0 packet cannot be constructed safely."""


def _check_nonnegative_int(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or (value <= 0 if positive else value < 0):
        raise NaturalPT0Error(f"{name} must be an integer")
    return value


@dataclass(frozen=True)
class NaturalPT0Design:
    """Immutable, explicit knobs for one natural PT0 packet.

    ``role_buckets`` and ``remaining_hand_thresholds`` are deliberately
    tuples, rather than flags hidden in the runner.  The packet therefore
    cannot silently change its estimand by omitting a role or threshold.
    """

    capture_secret_sha256: str
    trump_ranks: tuple[str, ...]
    production_policy: str = "mc-s0-report-lcb"
    banker_seats: tuple[int, ...] = (0, 1)
    role_buckets: tuple[str, ...] = ROLE_BUCKETS
    remaining_hand_thresholds: tuple[int, ...] = REMAINING_HAND_THRESHOLDS
    capture_attempts_per_cell: int = 64
    unique_worlds_per_state: int = 2
    proposal_worlds_per_state: int | None = None
    evaluation_worlds_per_state: int | None = None
    max_sampler_attempts: int = 64
    max_exact_nodes: int = 250_000
    baseline_policies: tuple[str, ...] = BASELINE_POLICIES
    baseline_seeds_per_state: int = 4
    bootstrap_replicates: int = 5_000
    gameplay_authorized: bool = False
    strength_claim_authorized: bool = False
    deployment_authorized: bool = False
    training_authorized: bool = False

    def __post_init__(self) -> None:
        from ..engine.cards import RANKS  # explicit design validation only

        ranks = tuple(self.trump_ranks)
        object.__setattr__(self, "trump_ranks", ranks)
        if (type(self.capture_secret_sha256) is not str
                or len(self.capture_secret_sha256) != 64
                or any(char not in "0123456789abcdef"
                       for char in self.capture_secret_sha256)):
            raise NaturalPT0Error("capture_secret_sha256 must be a SHA-256")
        if not ranks or any(type(x) is not str or x not in RANKS for x in ranks):
            raise NaturalPT0Error("trump_ranks must contain engine ranks")
        if tuple(sorted(set(ranks), key=RANKS.index)) != ranks:
            raise NaturalPT0Error("trump_ranks must be unique in engine order")
        bankers = tuple(self.banker_seats)
        object.__setattr__(self, "banker_seats", bankers)
        if (not bankers or len(set(bankers)) != len(bankers)
                or any(isinstance(seat, bool) or seat not in range(4)
                       for seat in bankers)):
            raise NaturalPT0Error(
                "banker_seats must be unique seats in [0, 3]")
        if tuple(self.role_buckets) != ROLE_BUCKETS:
            raise NaturalPT0Error("PT0 requires both declared role buckets")
        if tuple(self.remaining_hand_thresholds) != REMAINING_HAND_THRESHOLDS:
            raise NaturalPT0Error("PT0 requires exact remaining-hand thresholds 2 and 3")
        if type(self.production_policy) is not str or not self.production_policy:
            raise NaturalPT0Error("production_policy must be a named policy")
        for value, name in ((self.unique_worlds_per_state, "unique_worlds_per_state"),
                            (self.capture_attempts_per_cell,
                             "capture_attempts_per_cell"),
                            (self.max_sampler_attempts, "max_sampler_attempts"),
                            (self.max_exact_nodes, "max_exact_nodes"),
                            (self.baseline_seeds_per_state,
                             "baseline_seeds_per_state"),
                            (self.bootstrap_replicates,
                             "bootstrap_replicates")):
            _check_nonnegative_int(value, name, positive=True)
        if self.unique_worlds_per_state < 2:
            raise NaturalPT0Error("unique_worlds_per_state must be at least two")
        for value, name in ((self.proposal_worlds_per_state,
                             "proposal_worlds_per_state"),
                            (self.evaluation_worlds_per_state,
                             "evaluation_worlds_per_state")):
            if value is not None:
                _check_nonnegative_int(value, name, positive=True)
                if value < 2:
                    raise NaturalPT0Error(f"{name} must be at least two")
        if self.proposal_worlds_per_state is None:
            object.__setattr__(self, "proposal_worlds_per_state",
                               self.unique_worlds_per_state)
        if self.evaluation_worlds_per_state is None:
            object.__setattr__(self, "evaluation_worlds_per_state",
                               self.unique_worlds_per_state)
        policies = tuple(self.baseline_policies)
        object.__setattr__(self, "baseline_policies", policies)
        if not set(BASELINE_POLICIES).issubset(policies):
            raise NaturalPT0Error("baseline_policies must include the frozen PT0 baselines")
        if any(type(x) is not str or not x for x in policies):
            raise NaturalPT0Error("baseline_policies must be named policies")
        for flag in (self.gameplay_authorized, self.strength_claim_authorized,
                     self.deployment_authorized, self.training_authorized):
            if flag is not False:
                raise NaturalPT0Error("natural PT0 authority is always false")

    @property
    def bucket_keys(self) -> tuple[tuple[str, int, str, int], ...]:
        return tuple((rank, banker, role, threshold)
                     for rank in self.trump_ranks
                     for banker in self.banker_seats
                     for threshold in self.remaining_hand_thresholds
                     for role in self.role_buckets)

    def payload(self) -> dict[str, object]:
        """Return the closed design identity used by packet evidence."""
        return {
            "capture_secret_sha256": self.capture_secret_sha256,
            "trump_ranks": list(self.trump_ranks),
            "production_policy": self.production_policy,
            "banker_seats": list(self.banker_seats),
            "role_buckets": list(self.role_buckets),
            "remaining_hand_thresholds": list(
                self.remaining_hand_thresholds),
            "capture_attempts_per_cell": self.capture_attempts_per_cell,
            "proposal_worlds_per_state": self.proposal_worlds_per_state,
            "evaluation_worlds_per_state": self.evaluation_worlds_per_state,
            "max_sampler_attempts": self.max_sampler_attempts,
            "max_exact_nodes": self.max_exact_nodes,
            "baseline_policies": list(self.baseline_policies),
            "baseline_seeds_per_state": self.baseline_seeds_per_state,
            "bootstrap_replicates": self.bootstrap_replicates,
            "sampler_estimand": SAMPLER_ESTIMAND,
            "bootstrap_unit": BOOTSTRAP_UNIT,
            "authority": self.authority(),
        }

    def authority(self) -> dict[str, bool]:
        return {"gameplay_authorized": False,
                "strength_claim_authorized": False,
                "deployment_authorized": False,
                "training_authorized": False}


def _seed(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256(canonical_json_bytes(list(parts))).digest()[:8],
                          "big")


def _capture_round_seed(capture_secret: bytes, trump_rank: str,
                        banker: int, attempt: int) -> int:
    """Domain-separate deals so rank/banker cells do not reuse one deal."""
    message = canonical_json_bytes([
        NATURAL_PT0_SCHEMA, "capture-round", trump_rank, banker, attempt])
    return int.from_bytes(
        hmac.new(capture_secret, message, hashlib.sha256).digest()[:8], "big")


def _check_capture_secret(design: NaturalPT0Design,
                          capture_secret: bytes) -> bytes:
    if type(capture_secret) is not bytes or len(capture_secret) != 32:
        raise NaturalPT0Error("capture secret must be exactly 32 bytes")
    if hashlib.sha256(capture_secret).hexdigest() \
            != design.capture_secret_sha256:
        raise NaturalPT0Error("capture secret commitment drift")
    return capture_secret


def _role(rnd: object, seat: int) -> str:
    return "banker-team" if seat % 2 == rnd.banker % 2 else "attacker-team"


def _world_hash(rnd: object, *, actor: int, buried: Sequence[str]) -> str:
    # This underlying-world identity is used only to count repeated sampler
    # draws.  It is never included in a safe state record or used to choose an
    # action.
    payload = {"hands": [sorted(hand) for hand in rnd.hands],
               "buried": sorted(buried), "actor": actor}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _clone_world(rnd: object, hands: list[list[str]], buried: Sequence[str]):
    clone = copy.copy(rnd)
    clone.hands = [list(hand) for hand in hands]
    clone.buried = list(buried)
    clone.history = list(rnd.history)
    clone.trick = copy.deepcopy(rnd.trick)
    clone.last_trick = copy.deepcopy(rnd.last_trick)
    clone.message = None
    clone.__dict__.pop("_trusted_rollout", None)
    clone.__dict__.pop("_determinized_world", None)
    return clone


def _capture_round(design: NaturalPT0Design, round_seed: int,
                   trump_rank: str, banker: int) \
        -> dict[tuple[str, int], object]:
    """Play one actual Round and return the first chronological bucket hits."""
    from ..ai.registry import make_bot
    from ..ai.endgame import exhaustive_legal_actions
    from ..engine.round import Round

    rnd = Round(trump_rank, banker=banker, rng=random.Random(round_seed))
    bots = [make_bot(
        design.production_policy,
        seed=_seed(round_seed, trump_rank, banker, s))
            for s in range(4)]
    # Deal and declaration are genuine engine transitions.  A declaration is
    # accepted only when the named bot returns a legal option.
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        declaration = bots[seat].decide_declare(rnd, seat)
        if declaration is not None:
            rnd.declare(seat, declaration)
    for seat in range(4):
        declaration = bots[seat].decide_declare(rnd, seat, final=True)
        if declaration is not None:
            rnd.declare(seat, declaration)
        else:
            rnd.pass_declare(seat)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))

    hits: dict[tuple[str, int], object] = {}
    while rnd.phase == "play":
        seat = rnd.turn
        assert seat is not None
        maximum = max(len(hand) for hand in rnd.hands)
        if maximum in design.remaining_hand_thresholds:
            actions = exhaustive_legal_actions(rnd, seat, max_hand_cards=maximum)
            key = (_role(rnd, seat), maximum)
            # This is the sole selection predicate.  It reads no exact value,
            # baseline decision, hidden-card strength, or round outcome.
            if key not in hits and len(actions) >= 2:
                captured = copy.deepcopy(rnd)
                captured._natural_round_seed = round_seed
                captured._natural_trump_rank = trump_rank
                hits[key] = captured
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
        if len(hits) == len(ROLE_BUCKETS) * len(REMAINING_HAND_THRESHOLDS):
            break
    return hits


def _capture_cell(
        design: NaturalPT0Design, capture_secret: bytes, *,
        rank: str, banker: int, deadline: float | None,
        monotonic: Callable[[], float]) \
        -> tuple[dict[tuple[str, int, str, int], object], bool]:
    captured: dict[tuple[str, int, str, int], object] = {}
    seen_seeds = set()
    wanted = {key for key in design.bucket_keys
              if key[0] == rank and key[1] == banker}
    for attempt in range(design.capture_attempts_per_cell):
        if deadline is not None and monotonic() >= deadline:
            return captured, True
        seed = _capture_round_seed(capture_secret, rank, banker, attempt)
        if seed in seen_seeds:
            raise NaturalPT0Error("natural PT0 derived capture seed collision")
        seen_seeds.add(seed)
        hits = _capture_round(design, seed, rank, banker)
        for bucket, state in sorted(hits.items()):
            key = (rank, banker, bucket[0], bucket[1])
            if key not in captured:
                state._natural_capture_attempt = attempt
                captured[key] = state
        if wanted.issubset(captured):
            return captured, False
    missing = sorted(wanted - set(captured))
    raise NaturalPT0Error(
        f"natural PT0 bucket completeness refusal: missing {missing}")


def capture_natural_states(
        design: NaturalPT0Design, *, capture_secret: bytes) \
        -> dict[tuple[str, int, str, int], object]:
    """Capture one state per requested rank/role/threshold."""
    if type(design) is not NaturalPT0Design:
        raise NaturalPT0Error("capture requires NaturalPT0Design")
    secret = _check_capture_secret(design, capture_secret)
    captured: dict[tuple[str, int, str, int], object] = {}
    for rank in design.trump_ranks:
        for banker in design.banker_seats:
            cell, expired = _capture_cell(
                design, secret, rank=rank, banker=banker,
                deadline=None, monotonic=time.monotonic)
            assert not expired
            captured.update(cell)
    return captured


def _fraction_payload(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _dispersion(target: Mapping[str, object]) -> dict[str, dict[str, int]]:
    rows = target["actions"]
    return {"max_signed_level_variance": max(
        (row["signed_level_variance"] for row in rows),
        key=lambda v: Fraction(v["numerator"], v["denominator"])),
        "argmax_count": {"numerator": len(target["information_set_argmax"]),
                         "denominator": 1}}


def _sample_worlds(design: NaturalPT0Design, state: object, *, role: str,
                   threshold: int, round_seed: int, trump_rank: str,
                   cohort: str, count: int):
    from ..ai.mcbot import MCBot, DeterminizationContractError
    from ..ai.memory import Memory

    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise NaturalPT0Error("natural PT0 requires SHENGJI_REQUIRE_VOIDS=1")
    seat = state.turn
    public = pt0_public_state_sha256(state, perspective_seat=seat)
    sampler = MCBot(seed=_seed(
        "natural-sampler", cohort, round_seed, trump_rank, state.banker,
        seat, role, threshold, public))
    memory = Memory(state, seat, own_kitty=True)
    draws: list[tuple[str, object]] = []
    underlying_world_sha256s: list[str] = []
    for _ in range(design.max_sampler_attempts):
        sampled = sampler._sample_hands(state, seat, memory)
        if sampled is None:
            continue
        hands, buried = sampled
        try:
            complete = sampler._complete_determinized_hands(
                state, seat, hands, buried=buried)
        except DeterminizationContractError as exc:
            raise NaturalPT0Error("MCBot sampled world failed exact completion") from exc
        world = _clone_world(state, complete, buried)
        underlying_identity = _world_hash(
            world, actor=seat, buried=buried)
        draw_identity = hashlib.sha256(canonical_json_bytes([
            NATURAL_PT0_SCHEMA, "constraint-sampler-draw", public, cohort,
            len(draws), underlying_identity,
        ])).hexdigest()
        draws.append((draw_identity, world))
        underlying_world_sha256s.append(underlying_identity)
        if len(draws) == count:
            break
    if len(draws) != count:
        raise NaturalPT0Error(
            "natural PT0 sampler attempt cap underfilled constraint-consistent draws")
    ordered = sorted(draws)
    if len({identity for identity, _ in ordered}) != count:
        raise NaturalPT0Error("natural PT0 sampler draw identity collision")
    if any(pt0_public_state_sha256(world, perspective_seat=seat) != public
           for _, world in ordered):
        raise NaturalPT0Error("natural PT0 compatible world public fingerprint drift")
    return ordered, public, frozenset(underlying_world_sha256s)


def _make_record(design: NaturalPT0Design, state: object, *, role: str,
                 threshold: int, round_seed: int, trump_rank: str) -> dict[str, object]:
    seat = state.turn
    proposal_worlds, public, proposal_underlying = _sample_worlds(
        design, state, role=role, threshold=threshold, round_seed=round_seed,
        trump_rank=trump_rank, cohort="proposal",
        count=design.proposal_worlds_per_state)
    evaluation_worlds, evaluation_public, evaluation_underlying = _sample_worlds(
        design, state, role=role, threshold=threshold, round_seed=round_seed,
        trump_rank=trump_rank, cohort="evaluation",
        count=design.evaluation_worlds_per_state)
    if public != evaluation_public:
        raise NaturalPT0Error("natural PT0 cohort public fingerprint drift")
    proposal_draw_ids = {identity for identity, _ in proposal_worlds}
    evaluation_draw_ids = {identity for identity, _ in evaluation_worlds}
    if proposal_draw_ids & evaluation_draw_ids:
        raise NaturalPT0Error("natural PT0 proposal/evaluation draw identity overlap")
    try:
        result = run_pt0_miniature(
            public, proposal_worlds, perspective_seat=seat,
            max_hand_cards=threshold, max_nodes=design.max_exact_nodes)
    except PrivilegedTeacherPT0Error as exc:
        raise NaturalPT0Error(
            f"natural PT0 proposal evaluation refused: {exc}") from exc
    if result.status != "COMPLETE" or result.target is None:
        raise NaturalPT0Error("natural PT0 exact world population did not complete")
    target = result.target
    try:
        evaluation_result = run_pt0_miniature(
            public, evaluation_worlds, perspective_seat=seat,
            max_hand_cards=threshold, max_nodes=design.max_exact_nodes)
    except PrivilegedTeacherPT0Error as exc:
        raise NaturalPT0Error(
            f"natural PT0 held-out evaluation refused: {exc}") from exc
    if evaluation_result.status != "COMPLETE" or evaluation_result.target is None:
        raise NaturalPT0Error("natural PT0 evaluation world population did not complete")
    proposal_action = tuple(target["information_set_argmax"][0])
    eval_rows = {tuple(row["cards"]): row for row in evaluation_result.target["actions"]}
    eval_values = {
        cards: Fraction(row["mean_signed_level_utility"]["numerator"],
                        row["mean_signed_level_utility"]["denominator"])
        for cards, row in eval_rows.items()}
    proposal_population = {
        tuple(row["cards"]) for row in target["actions"]}
    if set(eval_values) != proposal_population:
        raise NaturalPT0Error(
            "natural PT0 proposal/evaluation legal-action drift")
    eval_order = sorted(eval_values, key=lambda cards: (-eval_values[cards], cards))
    baselines = []
    for policy in design.baseline_policies:
        for seed_index in range(design.baseline_seeds_per_state):
            baseline = evaluate_named_baseline(
                state, target, policy=policy,
                seed=_seed("natural-baseline", round_seed, trump_rank,
                           state.banker, role, threshold, policy, seed_index))
            baseline_cards = tuple(baseline.selected_cards)
            if baseline_cards not in eval_values:
                raise NaturalPT0Error(
                    "baseline selected action outside evaluation ballot")
            baselines.append({
                "policy": policy,
                "seed_index": seed_index,
                "selected_cards": list(baseline.selected_cards),
                "evaluation_delta_pt0_minus_baseline": _fraction_payload(
                    eval_values[proposal_action] - eval_values[baseline_cards]),
            })
    capture_id = hashlib.sha256(canonical_json_bytes([
        NATURAL_PT0_RECORD_SCHEMA, trump_rank, state.banker, role, threshold,
        public])).hexdigest()
    # The capture round is an inference cluster: one natural round may supply
    # several role/horizon records.  Hash the secret-derived round seed into an
    # opaque grouping token so the terminal can preserve that dependence
    # without publishing a replayable seed or hidden deal identity.
    capture_round_cluster = hashlib.sha256(canonical_json_bytes([
        NATURAL_PT0_RECORD_SCHEMA, "capture-round-cluster", round_seed,
    ])).hexdigest()
    record = {
        "schema": NATURAL_PT0_RECORD_SCHEMA,
        "capture_id_sha256": capture_id,
        "capture_round_cluster_sha256": capture_round_cluster,
        "trump_rank": trump_rank,
        "banker": state.banker,
        "role": role,
        "remaining_hand_threshold": threshold,
        "public_state_sha256": public,
        "proposal_world_population_sha256": target["world_population_sha256"],
        "proposal_world_count": target["world_count"],
        "proposal_unique_underlying_world_count": len(proposal_underlying),
        "evaluation_world_population_sha256": evaluation_result.target["world_population_sha256"],
        "evaluation_world_count": evaluation_result.target["world_count"],
        "evaluation_unique_underlying_world_count": len(evaluation_underlying),
        "cross_cohort_underlying_world_overlap_count": len(
            proposal_underlying & evaluation_underlying),
        # Compatibility aliases make the fixed proposal population explicit
        # to consumers that do not need the independent evaluation cohort.
        "world_population_sha256": target["world_population_sha256"],
        "world_count": target["world_count"],
        "target_sha256": hashlib.sha256(canonical_json_bytes(target)).hexdigest(),
        "target_argmax": target["information_set_argmax"],
        "proposal_action": list(proposal_action),
        "evaluation_argmax": evaluation_result.target["information_set_argmax"],
        "proposal_action_rank": 0,
        "proposal_action_rank_in_evaluation": eval_order.index(proposal_action),
        "target_dispersion": _dispersion(target),
        "baselines": baselines,
        "work": {
            "proposal": result.receipt["work"],
            "evaluation": evaluation_result.receipt["work"],
        },
        "authority": design.authority(),
    }
    canonical_json_bytes(record)
    return record


def _mean(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise NaturalPT0Error("natural PT0 cannot average an empty population")
    return sum(values, Fraction()) / len(values)


def _percentile(values: Sequence[Fraction], numerator: int,
                denominator: int) -> Fraction:
    if not values:
        raise NaturalPT0Error("natural PT0 percentile population is empty")
    ordered = sorted(values)
    # Nearest-rank with an explicit zero-based lower index.  This convention
    # is simple, deterministic and frozen in the packet metadata.
    index = max(0, min(len(ordered) - 1,
                       (len(ordered) * numerator) // denominator))
    return ordered[index]


def _capture_round_bootstrap(
        state_rows: Sequence[tuple[Mapping[str, object], Fraction]], *,
        replicates: int, rng: random.Random) -> tuple[list[Fraction], int]:
    """Bootstrap opaque capture-round clusters, retaining all member states."""
    clusters: dict[str, list[Fraction]] = {}
    for record, state_mean in state_rows:
        cluster = record.get("capture_round_cluster_sha256")
        if (type(cluster) is not str or len(cluster) != 64
                or any(char not in "0123456789abcdef" for char in cluster)):
            raise NaturalPT0Error("natural PT0 capture round cluster drift")
        clusters.setdefault(cluster, []).append(state_mean)
    cluster_ids = tuple(sorted(clusters))
    if not cluster_ids:
        raise NaturalPT0Error("natural PT0 capture round population is empty")
    bootstrap = []
    for _ in range(replicates):
        sampled_states = []
        for _ in cluster_ids:
            selected = cluster_ids[rng.randrange(len(cluster_ids))]
            sampled_states.extend(clusters[selected])
        bootstrap.append(_mean(sampled_states))
    return bootstrap, len(cluster_ids)


def summarize_natural_records(
        design: NaturalPT0Design, records: Sequence[Mapping[str, object]], *,
        complete: bool) -> dict[str, object]:
    """Reduce state-safe records without opening any hidden world."""
    if not records:
        return {
            "record_count": 0,
            "complete_grid_inference": False,
            "policy_summaries": [],
        }
    policy_summaries = []
    for policy in design.baseline_policies:
        state_means: list[Fraction] = []
        state_rows: list[tuple[Mapping[str, object], Fraction]] = []
        positive = zero = negative = 0
        flip_count = comparison_count = 0
        for record in records:
            rows = [row for row in record["baselines"]
                    if row["policy"] == policy]
            if len(rows) != design.baseline_seeds_per_state:
                raise NaturalPT0Error(
                    "natural PT0 baseline seed population drift")
            deltas = [Fraction(
                row["evaluation_delta_pt0_minus_baseline"]["numerator"],
                row["evaluation_delta_pt0_minus_baseline"]["denominator"])
                for row in rows]
            state_mean = _mean(deltas)
            state_means.append(state_mean)
            state_rows.append((record, state_mean))
            positive += state_mean > 0
            zero += state_mean == 0
            negative += state_mean < 0
            proposal_action = tuple(record["proposal_action"])
            flip_count += sum(
                tuple(row["selected_cards"]) != proposal_action for row in rows)
            comparison_count += len(rows)

        summary: dict[str, object] = {
            "policy": policy,
            "state_count": len(state_means),
            "capture_round_cluster_count": len({
                record["capture_round_cluster_sha256"] for record, _ in state_rows
            }),
            "mean_held_out_delta": _fraction_payload(_mean(state_means)),
            "positive_state_count": positive,
            "zero_state_count": zero,
            "negative_state_count": negative,
            "decision_flip_count": flip_count,
            "decision_comparison_count": comparison_count,
            "decision_flip_fraction": _fraction_payload(
                Fraction(flip_count, comparison_count)),
            "bootstrap_interval": None,
        }
        if complete:
            rng = random.Random(_seed(
                "natural-pt0-capture-round-bootstrap", policy,
                hashlib.sha256(canonical_json_bytes(
                    [record["capture_id_sha256"]
                     for record in records])).hexdigest()))
            bootstrap, cluster_count = _capture_round_bootstrap(
                state_rows, replicates=design.bootstrap_replicates, rng=rng)
            if cluster_count != summary["capture_round_cluster_count"]:
                raise NaturalPT0Error(
                    "natural PT0 capture round cluster reconstruction drift")
            summary["bootstrap_interval"] = {
                "schema": "fixed-capture-round-cluster-bootstrap-percentile-v1",
                "replicates": design.bootstrap_replicates,
                "cluster_count": cluster_count,
                "lower_2_5_percent": _fraction_payload(
                    _percentile(bootstrap, 25, 1_000)),
                "upper_97_5_percent": _fraction_payload(
                    _percentile(bootstrap, 975, 1_000)),
            }
        slices = []
        for dimension in ("trump_rank", "banker", "role",
                          "remaining_hand_threshold"):
            values = sorted({record[dimension] for record, _ in state_rows},
                            key=lambda value: (str(type(value)), str(value)))
            for value in values:
                selected = [state_mean for record, state_mean in state_rows
                            if record[dimension] == value]
                slices.append({
                    "dimension": dimension,
                    "value": value,
                    "state_count": len(selected),
                    "mean_held_out_delta": _fraction_payload(_mean(selected)),
                    "positive_state_count": sum(item > 0 for item in selected),
                    "zero_state_count": sum(item == 0 for item in selected),
                    "negative_state_count": sum(item < 0 for item in selected),
                })
        summary["descriptive_slices"] = slices
        policy_summaries.append(summary)
    return {
        "record_count": len(records),
        "complete_grid_inference": complete,
        "policy_summaries": policy_summaries,
    }


def run_natural_packet(
        design: NaturalPT0Design, *, capture_secret: bytes,
        progress_sink: Callable[[int, int, int], object] | None = None,
        record_sink: Callable[[int, bytes], object] | None = None,
        deadline_exempt_prefix: int = 0,
        deadline: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        state_capture: Callable[[NaturalPT0Design],
                                dict[tuple[str, int, str, int], object]] |
        None = None) -> dict[str, object]:
    """Capture/evaluate a deterministic packet entirely in memory."""
    if progress_sink is not None and not callable(progress_sink):
        raise NaturalPT0Error("progress_sink must be callable")
    if record_sink is not None and not callable(record_sink):
        raise NaturalPT0Error("record_sink must be callable")
    if not callable(monotonic):
        raise NaturalPT0Error("monotonic must be callable")
    if deadline is not None and (isinstance(deadline, bool)
                                 or not isinstance(deadline, (int, float))
                                 or not math.isfinite(deadline)):
        raise NaturalPT0Error("deadline must be a monotonic number")
    secret = _check_capture_secret(design, capture_secret)
    captured = state_capture(design) if state_capture is not None else None
    if captured is not None:
        if set(captured) != set(design.bucket_keys):
            raise NaturalPT0Error(
                "natural PT0 bucket completeness refusal: "
                f"expected {sorted(design.bucket_keys)}, "
                f"got {sorted(captured)}")
    total = len(design.bucket_keys)
    if (isinstance(deadline_exempt_prefix, bool)
            or not isinstance(deadline_exempt_prefix, int)
            or deadline_exempt_prefix < 0
            or deadline_exempt_prefix > total):
        raise NaturalPT0Error("deadline-exempt prefix is outside the grid")
    records = []
    # A state capture callback is intentionally state-only; provenance values
    # are fixed by the design and bucket.  No hidden identity can enter here.
    cell_key = None
    cell_states: dict[tuple[str, int, str, int], object] = {}
    for key in sorted(design.bucket_keys):
        replaying_prefix = len(records) < deadline_exempt_prefix
        active_deadline = None if replaying_prefix else deadline
        if active_deadline is not None and monotonic() >= active_deadline:
            break
        rank, banker, role, threshold = key
        if captured is None and cell_key != (rank, banker):
            cell_states, expired = _capture_cell(
                design, secret, rank=rank, banker=banker,
                deadline=active_deadline, monotonic=monotonic)
            if expired:
                break
            cell_key = (rank, banker)
        state = captured[key] if captured is not None else cell_states[key]
        if state.banker != banker:
            raise NaturalPT0Error("natural PT0 captured banker drift")
        round_seed = getattr(state, "_natural_round_seed", None)
        state_rank = getattr(state, "_natural_trump_rank", None)
        capture_attempt = getattr(state, "_natural_capture_attempt", None)
        if (isinstance(round_seed, bool) or not isinstance(round_seed, int)
                or round_seed < 0 or state_rank != rank
                or isinstance(capture_attempt, bool)
                or not isinstance(capture_attempt, int)
                or capture_attempt not in range(design.capture_attempts_per_cell)
                or round_seed != _capture_round_seed(
                    secret, rank, banker, capture_attempt)):
            raise NaturalPT0Error("natural PT0 capture provenance drift")
        record = _make_record(
            design, state, role=role, threshold=threshold,
            round_seed=round_seed, trump_rank=state_rank)
        records.append(record)
        if record_sink is not None:
            record_sink(len(records) - 1, canonical_json_bytes(record))
        if progress_sink is not None:
            progress_sink(
                len(records), total, (len(records) * 10_000) // total)
    records.sort(key=lambda row: (row["trump_rank"], row["banker"], row["role"],
                                 row["remaining_hand_threshold"],
                                 row["public_state_sha256"]))
    design_sha256 = hashlib.sha256(
        canonical_json_bytes(design.payload())).hexdigest()
    complete = len(records) == total
    packet = {
        "schema": NATURAL_PT0_SCHEMA,
        "design_sha256": design_sha256,
        "records": records,
        "record_count": len(records),
        "total_record_count": total,
        "status": "COMPLETE" if complete else "TRUNCATED",
        "truncated_by_deadline": not complete,
        "progress": {
            "completed_units": len(records),
            "total_units": total,
            "percent_basis_points": (len(records) * 10_000) // total,
        },
        "summary": summarize_natural_records(
            design, records, complete=complete),
        "authority": design.authority(),
    }
    packet["packet_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
    canonical_json_bytes(packet)
    return packet


__all__ = ["BASELINE_POLICIES", "NaturalPT0Design", "NaturalPT0Error",
           "NATURAL_PT0_RECORD_SCHEMA", "NATURAL_PT0_SCHEMA",
           "capture_natural_states", "run_natural_packet",
           "summarize_natural_records"]
