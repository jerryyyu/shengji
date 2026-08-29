"""Full-play public-versus-true-world teacher diagnostic.

This module is deliberately DEV-only.  It measures whether the current
production policy can use a complete hidden world across an entire play phase;
it contains no learned policy and grants no gameplay or strength authority.
"""

from __future__ import annotations

import copy
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import random
import time
from typing import Callable, Mapping

from ..ai.registry import REGISTRY
from ..engine.cards import RANKS
from ..engine.round import Round
from .privileged_teacher_pt0 import canonical_json_bytes, signed_level_utility
from .privileged_teacher_pt1 import PRODUCTION_POLICY


SCHEMA = "privileged-teacher-full-play-ab-dev-v1"
RECORD_SCHEMA = "privileged-teacher-full-play-ab-record-v1"
DESIGN_SCHEMA = "privileged-teacher-full-play-ab-design-v1"
DEV_NAMESPACE = "privileged-teacher-full-play-ab-open-dev-v1"
BANKER_SEATS = (0, 1)
ROLES = ("banker-team", "attacker-team")
ARMS = ("A", "A0", "B")
MINI_HOSTNAME = "Jerrys-Mac-mini.local"
AUTHORITY = {
    "scientific_execution_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "merge_authorized": False,
}

_Production = REGISTRY[PRODUCTION_POLICY]


class PrivilegedTeacherFullABError(ValueError):
    """The DEV population, information boundary, or result drifted."""


def _sha(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _derive_seed(seed_secret: bytes, *parts: object) -> int:
    if type(seed_secret) is not bytes or len(seed_secret) != 32:
        raise PrivilegedTeacherFullABError("seed secret identity drift")
    return int.from_bytes(hashlib.sha256(
        seed_secret + canonical_json_bytes(
            [DEV_NAMESPACE, *parts])).digest()[:8], "big") & ((1 << 63) - 1)


def _root_sha256(rnd: Round) -> str:
    return _sha({
        "schema": "privileged-teacher-full-play-root-v1",
        "hands": [sorted(hand) for hand in rnd.hands],
        "buried": sorted(rnd.buried),
        "banker": rnd.banker,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "turn": rnd.turn,
    })


@dataclass(frozen=True)
class FullABDesign:
    seed_commitment_sha256: str
    execution_git: str
    native_sha256: str
    hostname: str
    replicates: int = 1
    production_policy: str = PRODUCTION_POLICY
    namespace: str = DEV_NAMESPACE

    def __post_init__(self) -> None:
        if (type(self.seed_commitment_sha256) is not str
                or len(self.seed_commitment_sha256) != 64
                or any(char not in "0123456789abcdef"
                       for char in self.seed_commitment_sha256)):
            raise PrivilegedTeacherFullABError("seed commitment drift")
        if (type(self.execution_git) is not str
                or len(self.execution_git) != 40
                or any(char not in "0123456789abcdef"
                       for char in self.execution_git)):
            raise PrivilegedTeacherFullABError("execution Git drift")
        if (type(self.native_sha256) is not str
                or len(self.native_sha256) != 64
                or any(char not in "0123456789abcdef"
                       for char in self.native_sha256)):
            raise PrivilegedTeacherFullABError("native identity drift")
        if self.hostname != MINI_HOSTNAME:
            raise PrivilegedTeacherFullABError("execution hostname drift")
        if self.replicates != 1:
            raise PrivilegedTeacherFullABError(
                "first DEV design requires exactly one replicate")
        if self.production_policy != PRODUCTION_POLICY:
            raise PrivilegedTeacherFullABError(
                "full-play A/B requires exact production policy")
        if self.namespace != DEV_NAMESPACE:
            raise PrivilegedTeacherFullABError(
                "full-play A/B namespace drift")

    @property
    def root_coordinates(self) -> tuple[tuple[str, int, int], ...]:
        return tuple((rank, banker, replicate)
                     for rank in RANKS
                     for banker in BANKER_SEATS
                     for replicate in range(self.replicates))

    def payload(self) -> dict[str, object]:
        return {
            "schema": DESIGN_SCHEMA,
            "namespace": self.namespace,
            "seed_commitment_sha256": self.seed_commitment_sha256,
            "execution_git": self.execution_git,
            "native_sha256": self.native_sha256,
            "hostname": self.hostname,
            "production_policy": self.production_policy,
            "trump_ranks": list(RANKS),
            "banker_seats": list(BANKER_SEATS),
            "roles": list(ROLES),
            "replicates": self.replicates,
            "root_count": len(self.root_coordinates),
            "comparison_record_count": len(self.root_coordinates) * len(ROLES),
            "played_round_count": len(self.root_coordinates) * 5,
            "authority": dict(AUTHORITY),
        }


class RepeatedPublicWorldBot(_Production):
    """Repeat one ordinary actor-visible sampled world within each decision."""

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        self._ptfull_repeated_world = None
        return super().decide_play(rnd, seat)

    def _sample_hands(self, rnd: Round, seat: int, memory):
        cached = getattr(self, "_ptfull_repeated_world", None)
        if cached is None:
            sampled = super()._sample_hands(rnd, seat, memory)
            if sampled is None:
                return None
            hands, buried = sampled
            cached = ({other: tuple(cards) for other, cards in hands.items()},
                      tuple(buried))
            self._ptfull_repeated_world = cached
        else:
            # Preserve the production sampler-call accounting even though the
            # control deliberately returns a cached public-compatible world.
            self.sample_attempts += 1
            self.accepted_worlds += 1
        hands, buried = cached
        return ({other: list(cards) for other, cards in hands.items()},
                list(buried))


class TrueWorldProductionBot(_Production):
    """Use the exact current world while preserving production search logic."""

    def _sample_hands(self, rnd: Round, seat: int, memory):
        if getattr(rnd, "_ptfull_true_world", False) is not True:
            raise PrivilegedTeacherFullABError(
                "true-world bot requires marked privileged round")
        self.sample_attempts += 1
        self.accepted_worlds += 1
        return ({other: list(rnd.hands[other])
                 for other in range(4) if other != seat},
                list(rnd.buried))


@dataclass(frozen=True)
class ArmOutcome:
    arm: str
    attacker_points: int
    signed_level_utility: int
    decision_count: int
    work: Mapping[str, int]

    def payload(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "attacker_points": self.attacker_points,
            "signed_level_utility": self.signed_level_utility,
            "decision_count": self.decision_count,
            "work": dict(self.work),
        }


def _policy_seed(seed_secret: bytes, rank: str, banker: int,
                 replicate: int, seat: int) -> int:
    return _derive_seed(seed_secret, "policy", rank, banker, replicate, seat)


def _setup_seed(seed_secret: bytes, rank: str, banker: int,
                replicate: int, seat: int) -> int:
    return _derive_seed(
        seed_secret, "setup-policy", rank, banker, replicate, seat)


def _build_root(design: FullABDesign, seed_secret: bytes, rank: str, banker: int,
                replicate: int) -> Round:
    if (rank, banker, replicate) not in design.root_coordinates:
        raise PrivilegedTeacherFullABError("root coordinate drift")
    rnd = Round(rank, banker=banker, rng=random.Random(
        _derive_seed(seed_secret, "deal", rank, banker, replicate)))
    setup = [_Production(seed=_setup_seed(
        seed_secret, rank, banker, replicate, seat))
             for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = setup[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = setup[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker != banker or rnd.trump_rank != rank:
        raise PrivilegedTeacherFullABError("post-declare root identity drift")
    rnd.bury(banker, setup[banker].decide_bury(rnd, banker))
    if (rnd.phase != "play"
            or rnd.turn != banker
            or len(rnd.buried) != 8
            or any(len(hand) != 25 for hand in rnd.hands)):
        raise PrivilegedTeacherFullABError("post-bury root mechanics drift")
    return rnd


def _bots(seed_secret: bytes, rank: str, banker: int, replicate: int, *, arm: str,
          treatment_team: int) -> list[object]:
    if arm not in ARMS or treatment_team not in (0, 1):
        raise PrivilegedTeacherFullABError("arm/treatment identity drift")
    bots = []
    for seat in range(4):
        cls = _Production
        if seat % 2 == treatment_team:
            if arm == "A0":
                cls = RepeatedPublicWorldBot
            elif arm == "B":
                cls = TrueWorldProductionBot
        bots.append(cls(seed=_policy_seed(
            seed_secret, rank, banker, replicate, seat)))
    return bots


_WORK_FIELDS = (
    "search_calls", "rollouts", "sample_attempts", "accepted_worlds",
    "rejected_worlds", "failed_worlds", "short_search_decisions",
    "zero_world_decisions", "exact_endgame_calls", "exact_endgame_nodes",
    "verified_rollouts",
)


def _work(bots: list[object]) -> dict[str, int]:
    result = {}
    for field in _WORK_FIELDS:
        values = ([0] if field == "verified_rollouts" else
                  [getattr(bot, field, 0) for bot in bots])
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value < 0 for value in values):
            raise PrivilegedTeacherFullABError("bot work counter drift")
        result[field] = sum(values)
    return result


def _verify_decision_work(bot: object) -> int:
    """Refuse any contested decision that did not spend exact production work."""
    record = getattr(bot, "last_decision_record", None)
    if record is None:
        return 0
    work = record.get("work")
    allocation = record.get("alloc")
    report = record.get("report_fold")
    sampler = record.get("sampler_counters", {}).get("delta")
    n_by = allocation.get("n_by_candidate") if type(allocation) is dict \
        else None
    candidate_count = len(n_by) if type(n_by) is list else 0
    expected_selection = 30 * candidate_count
    expected_report = 600
    expected_total = expected_selection + expected_report
    if (type(work) is not dict
            or type(allocation) is not dict
            or type(report) is not dict
            or type(sampler) is not dict
            or type(n_by) is not list
            or len(n_by) < 2
            or any(type(value) is not int or value != 30 for value in n_by)
            or set(sampler) != {
                "sample_attempts", "accepted_worlds", "failed_worlds",
                "rejected_worlds", "impossible_worlds"}
            or any(type(value) is not int or value < 0
                   for value in sampler.values())
            or record.get("n_determinizations") != 30
            or record.get("report_worlds_requested") != 300
            or allocation.get("mode") != "uniform"
            or allocation.get("worlds") != 30
            or allocation.get("short") is not False
            or work.get("selection_budget") != expected_selection
            or work.get("selection_rollouts") != expected_selection
            or work.get("report_budget") != expected_report
            or work.get("report_rollouts") != expected_report
            or work.get("total_budget") != expected_total
            or work.get("total_rollouts") != expected_total
            or work.get("complete") is not True
            or report.get("worlds") != 300
            or report.get("complete") is not True
            or sampler.get("sample_attempts") != (
                sampler.get("accepted_worlds", -1)
                + sampler.get("failed_worlds", -1))
            or sampler.get("accepted_worlds") != 330
            or sampler.get("rejected_worlds", -1) > sampler.get(
                "failed_worlds", -1)):
        raise PrivilegedTeacherFullABError(
            "contested decision exact work drift")
    return expected_total


def _play_arm(root: Round, *, rank: str, banker: int, replicate: int,
              arm: str, treatment_team: int, seed_secret: bytes) -> ArmOutcome:
    rnd = copy.deepcopy(root)
    if arm == "B":
        rnd._ptfull_true_world = True
    bots = _bots(seed_secret, rank, banker, replicate, arm=arm,
                 treatment_team=treatment_team)
    decisions = 0
    validated_searches = 0
    verified_rollouts = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None:
            raise PrivilegedTeacherFullABError("play round lost turn")
        cards = bots[seat].decide_play(rnd, seat)
        verified = _verify_decision_work(bots[seat])
        validated_searches += int(verified > 0)
        verified_rollouts += verified
        rnd.play(seat, cards)
        decisions += 1
    if rnd.phase != "round_end" or rnd.banker is None:
        raise PrivilegedTeacherFullABError("arm did not complete round")
    work = _work(bots)
    work["verified_rollouts"] = verified_rollouts
    if (validated_searches < 1
            or work["search_calls"] != validated_searches
            or work["short_search_decisions"] != 0
            or work["zero_world_decisions"] != 0
            or work["accepted_worlds"] != 330 * validated_searches
            or work["sample_attempts"] != (
                work["accepted_worlds"] + work["failed_worlds"])
            or work["rejected_worlds"] > work["failed_worlds"]
            or work["rollouts"] != verified_rollouts
            or work["rollouts"] < 660 * validated_searches):
        raise PrivilegedTeacherFullABError("arm exact work receipt drift")
    perspective = treatment_team
    return ArmOutcome(
        arm=arm,
        attacker_points=rnd.attacker_points,
        signed_level_utility=signed_level_utility(
            rnd.attacker_points, banker_seat=rnd.banker,
            perspective_seat=perspective),
        decision_count=decisions,
        work=work,
    )


def _record_payload(*, rank: str, banker: int, replicate: int, role: str,
                    root_sha256: str, a: ArmOutcome, a0: ArmOutcome,
                    b: ArmOutcome) -> dict[str, object]:
    if role not in ROLES or (a.arm, a0.arm, b.arm) != ARMS:
        raise PrivilegedTeacherFullABError("comparison record arm drift")
    banker_team = banker % 2
    treatment_team = banker_team if role == "banker-team" else 1 - banker_team
    a_utility = signed_level_utility(
        a.attacker_points, banker_seat=banker,
        perspective_seat=treatment_team)
    a_payload = {**a.payload(), "signed_level_utility": a_utility}
    body = {
        "schema": RECORD_SCHEMA,
        "trump_rank": rank,
        "banker": banker,
        "replicate": replicate,
        "role": role,
        "treatment_team": treatment_team,
        "root_sha256": root_sha256,
        "arms": {"A": a_payload, "A0": a0.payload(), "B": b.payload()},
        "contrasts": {
            "b_minus_a": b.signed_level_utility - a_utility,
            "b_minus_a0": (
                b.signed_level_utility - a0.signed_level_utility),
            "a0_minus_a": a0.signed_level_utility - a_utility,
        },
        "authority": dict(AUTHORITY),
    }
    return {**body, "record_sha256": _sha(body)}


def _run_root(design: FullABDesign, seed_secret: bytes,
              coordinate: tuple[str, int, int]
              ) -> tuple[dict[str, object], dict[str, object]]:
    rank, banker, replicate = coordinate
    root = _build_root(design, seed_secret, rank, banker, replicate)
    root_sha256 = _root_sha256(root)
    a = _play_arm(root, rank=rank, banker=banker, replicate=replicate,
                  arm="A", treatment_team=0, seed_secret=seed_secret)
    records = []
    for role in ROLES:
        banker_team = banker % 2
        treatment = banker_team if role == "banker-team" else 1 - banker_team
        a0 = _play_arm(
            root, rank=rank, banker=banker, replicate=replicate,
            arm="A0", treatment_team=treatment, seed_secret=seed_secret)
        b = _play_arm(
            root, rank=rank, banker=banker, replicate=replicate,
            arm="B", treatment_team=treatment, seed_secret=seed_secret)
        records.append(_record_payload(
            rank=rank, banker=banker, replicate=replicate, role=role,
            root_sha256=root_sha256, a=a, a0=a0, b=b))
    return records[0], records[1]


def _fraction(values: list[int]) -> dict[str, int]:
    if not values:
        raise PrivilegedTeacherFullABError("empty contrast population")
    value = Fraction(sum(values), len(values))
    return {"numerator": value.numerator, "denominator": value.denominator}


def _contrast_summary(records: list[dict[str, object]],
                      name: str) -> dict[str, object]:
    values = [record["contrasts"][name] for record in records]
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in values):
        raise PrivilegedTeacherFullABError("contrast value drift")
    return {
        "mean": _fraction(values),
        "positive_count": sum(value > 0 for value in values),
        "zero_count": sum(value == 0 for value in values),
        "negative_count": sum(value < 0 for value in values),
    }


def _summaries(records: list[dict[str, object]]) -> dict[str, object]:
    result = {
        name: _contrast_summary(records, name)
        for name in ("b_minus_a", "b_minus_a0", "a0_minus_a")
    }
    result["by_role"] = {
        role: {
            name: _contrast_summary(
                [record for record in records if record["role"] == role],
                name)
            for name in ("b_minus_a", "b_minus_a0", "a0_minus_a")
        } for role in ROLES
    }
    result["by_rank"] = {
        rank: {
            name: _contrast_summary(
                [record for record in records
                 if record["trump_rank"] == rank], name)
            for name in ("b_minus_a", "b_minus_a0", "a0_minus_a")
        } for rank in RANKS
    }
    return result


def run_dev(
        design: FullABDesign, *, seed_secret: bytes, workers: int = 1,
        progress_sink: Callable[[dict[str, object]], object] | None = None,
) -> dict[str, object]:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise PrivilegedTeacherFullABError("workers must be positive integer")
    if hashlib.sha256(seed_secret).hexdigest() != \
            design.seed_commitment_sha256:
        raise PrivilegedTeacherFullABError("seed secret commitment drift")
    started = time.monotonic()
    coordinates = design.root_coordinates
    completed: dict[tuple[str, int, int],
                    tuple[dict[str, object], dict[str, object]]] = {}

    def publish() -> None:
        done = len(completed)
        elapsed = time.monotonic() - started
        eta = (None if done == 0 else
               max(0.0, elapsed * (len(coordinates) - done) / done))
        if progress_sink is not None:
            progress_sink({
                "completed_roots": done,
                "total_roots": len(coordinates),
                "percent_basis_points": done * 10_000 // len(coordinates),
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
            })

    if workers == 1:
        for coordinate in coordinates:
            completed[coordinate] = _run_root(design, seed_secret, coordinate)
            publish()
    else:
        with ProcessPoolExecutor(max_workers=min(workers, len(coordinates))) as pool:
            futures = {
                pool.submit(_run_root, design, seed_secret, coordinate): coordinate
                for coordinate in coordinates
            }
            for future in as_completed(futures):
                coordinate = futures[future]
                completed[coordinate] = future.result()
                publish()

    records = [record for coordinate in coordinates
               for record in completed[coordinate]]
    body = {
        "schema": SCHEMA,
        "status": "COMPLETE",
        "design": design.payload(),
        "completed_roots": len(completed),
        "record_count": len(records),
        "played_round_count": len(coordinates) * 5,
        "records": records,
        "summaries": _summaries(records),
        "elapsed_seconds": time.monotonic() - started,
        "authority": dict(AUTHORITY),
    }
    return {**body, "report_sha256": _sha(body)}


def validate_report(report: dict[str, object], design: FullABDesign) -> None:
    if type(report) is not dict or set(report) != {
            "schema", "status", "design", "completed_roots", "record_count",
            "played_round_count", "records", "summaries", "elapsed_seconds",
            "authority", "report_sha256"}:
        raise PrivilegedTeacherFullABError("report schema drift")
    body = {key: value for key, value in report.items()
            if key != "report_sha256"}
    records = report["records"]
    elapsed = report["elapsed_seconds"]
    if (isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0):
        raise PrivilegedTeacherFullABError("report elapsed time drift")
    if (report["schema"] != SCHEMA
            or report["status"] != "COMPLETE"
            or report["design"] != design.payload()
            or report["completed_roots"] != len(design.root_coordinates)
            or report["record_count"] != len(design.root_coordinates) * 2
            or report["played_round_count"] != len(design.root_coordinates) * 5
            or type(records) is not list
            or report["summaries"] != _summaries(records)
            or report["authority"] != AUTHORITY
            or report["report_sha256"] != _sha(body)):
        raise PrivilegedTeacherFullABError("report identity drift")
    expected = {(rank, banker, replicate, role)
                for rank, banker, replicate in design.root_coordinates
                for role in ROLES}
    actual = set()
    root_identities: dict[tuple[str, int, int], str] = {}
    public_arm_receipts: dict[tuple[str, int, int], dict[str, object]] = {}
    for record in records:
        if type(record) is not dict or set(record) != {
                "schema", "trump_rank", "banker", "replicate", "role",
                "treatment_team", "root_sha256", "arms", "contrasts",
                "authority", "record_sha256"}:
            raise PrivilegedTeacherFullABError("record schema drift")
        record_body = {key: value for key, value in record.items()
                       if key != "record_sha256"}
        key = (record["trump_rank"], record["banker"],
               record["replicate"], record["role"])
        coordinate = key[:3]
        expected_treatment = (record["banker"] % 2 if record["role"] ==
                              "banker-team" else 1 - record["banker"] % 2)
        arms = record["arms"]
        if type(arms) is not dict or tuple(arms) != ARMS:
            raise PrivilegedTeacherFullABError("record arm population drift")
        utilities = {}
        for arm in ARMS:
            row = arms[arm]
            if (type(row) is not dict
                    or set(row) != {
                        "arm", "attacker_points", "signed_level_utility",
                        "decision_count", "work"}
                    or row["arm"] != arm
                    or isinstance(row["attacker_points"], bool)
                    or not isinstance(row["attacker_points"], int)
                    or row["attacker_points"] < 0
                    or isinstance(row["decision_count"], bool)
                    or not isinstance(row["decision_count"], int)
                    or row["decision_count"] < 1
                    or type(row["work"]) is not dict
                    or set(row["work"]) != set(_WORK_FIELDS)
                    or any(isinstance(value, bool)
                           or not isinstance(value, int) or value < 0
                           for value in row["work"].values())):
                raise PrivilegedTeacherFullABError("record arm receipt drift")
            work = row["work"]
            if (work["search_calls"] < 1
                    or work["short_search_decisions"] != 0
                    or work["zero_world_decisions"] != 0
                    or work["accepted_worlds"] != 330 * work["search_calls"]
                    or work["sample_attempts"] != (
                        work["accepted_worlds"] + work["failed_worlds"])
                    or work["rejected_worlds"] > work["failed_worlds"]
                    or work["rollouts"] != work["verified_rollouts"]
                    or work["rollouts"] < 660 * work["search_calls"]):
                raise PrivilegedTeacherFullABError(
                    "record exact work receipt drift")
            expected_utility = signed_level_utility(
                row["attacker_points"], banker_seat=record["banker"],
                perspective_seat=record["treatment_team"])
            if row["signed_level_utility"] != expected_utility:
                raise PrivilegedTeacherFullABError(
                    "record signed utility drift")
            utilities[arm] = expected_utility
        expected_contrasts = {
            "b_minus_a": utilities["B"] - utilities["A"],
            "b_minus_a0": utilities["B"] - utilities["A0"],
            "a0_minus_a": utilities["A0"] - utilities["A"],
        }
        if (key not in expected
                or key in actual
                or record["record_sha256"] != _sha(record_body)
                or record["authority"] != AUTHORITY
                or record["contrasts"] != expected_contrasts
                or record["treatment_team"] != expected_treatment
                or type(record["root_sha256"]) is not str
                or len(record["root_sha256"]) != 64
                or any(char not in "0123456789abcdef"
                       for char in record["root_sha256"])):
            raise PrivilegedTeacherFullABError("record identity drift")
        prior_root = root_identities.setdefault(
            coordinate, record["root_sha256"])
        if prior_root != record["root_sha256"]:
            raise PrivilegedTeacherFullABError("root role binding drift")
        public_receipt = {
            key: value for key, value in arms["A"].items()
            if key != "signed_level_utility"}
        prior_public = public_arm_receipts.setdefault(
            coordinate, public_receipt)
        if prior_public != public_receipt:
            raise PrivilegedTeacherFullABError("public arm role binding drift")
        actual.add(key)
    if actual != expected:
        raise PrivilegedTeacherFullABError("record population drift")


def report_bytes(report: dict[str, object],
                 design: FullABDesign) -> bytes:
    validate_report(report, design)
    return canonical_json_bytes(report)
