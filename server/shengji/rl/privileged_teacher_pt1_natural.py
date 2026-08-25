"""Outcome-blind natural population capture for PT1.

This is a capture/provider boundary only.  It does not select A/B/C actions
or inspect exact values.  Each target cell is captured from its own
secret-derived engine round seed, so every retained state is its own inference
cluster (416 states, not 52 shared clusters).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import random
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .privileged_teacher_pt0 import (
    PrivilegedTeacherPT0Error,
    canonical_json_bytes,
    pt0_public_state_sha256,
)
from .privileged_teacher_pt1 import TrueWorld, seal_true_world

NATURAL_PT1_SCHEMA = "privileged-teacher-pt1-natural-population-v1"
NATURAL_PT1_STATE_SCHEMA = "privileged-teacher-pt1-natural-state-v1"
ROLE_BUCKETS = ("banker-team", "attacker-team")
REMAINING_HAND_THRESHOLDS = (3, 4)
BANKER_SEATS = (0, 1)
REPLICATES = 4
TARGET_STATE_COUNT = 416


class NaturalPT1Error(PrivilegedTeacherPT0Error):
    """The natural PT1 population failed closed."""


def _sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise NaturalPT1Error(f"{label} must be a lowercase SHA-256")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NaturalPT1Error(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class NaturalPT1Design:
    """The closed 13-rank × 2-seat × 2-role × 2-horizon × 4 grid."""

    capture_secret_sha256: str
    trump_ranks: tuple[str, ...] | None = None
    production_policy: str = "mc-s0-report-lcb"
    banker_seats: tuple[int, ...] = BANKER_SEATS
    role_buckets: tuple[str, ...] = ROLE_BUCKETS
    remaining_hand_thresholds: tuple[int, ...] = REMAINING_HAND_THRESHOLDS
    replicates: int = REPLICATES
    capture_attempts_per_state: int = 64
    gameplay_authorized: bool = False
    strength_claim_authorized: bool = False
    promotion_authorized: bool = False
    deployment_authorized: bool = False
    training_authorized: bool = False

    def __post_init__(self) -> None:
        from ..engine.cards import RANKS

        _sha(self.capture_secret_sha256, "capture_secret_sha256")
        ranks = tuple(RANKS if self.trump_ranks is None else self.trump_ranks)
        object.__setattr__(self, "trump_ranks", ranks)
        if ranks != tuple(RANKS):
            raise NaturalPT1Error("PT1 requires all 13 ranks in engine order")
        if tuple(self.banker_seats) != BANKER_SEATS:
            raise NaturalPT1Error("PT1 requires banker representatives (0, 1)")
        if tuple(self.role_buckets) != ROLE_BUCKETS:
            raise NaturalPT1Error("PT1 requires both actor roles")
        if tuple(self.remaining_hand_thresholds) != REMAINING_HAND_THRESHOLDS:
            raise NaturalPT1Error("PT1 requires remaining-hand thresholds (3, 4)")
        if self.replicates != REPLICATES:
            raise NaturalPT1Error("PT1 requires four independent replicates")
        _positive(self.capture_attempts_per_state, "capture_attempts_per_state")
        if self.production_policy != "mc-s0-report-lcb":
            raise NaturalPT1Error(
                "PT1 natural capture requires mc-s0-report-lcb production")
        for flag in (self.gameplay_authorized, self.strength_claim_authorized,
                     self.promotion_authorized, self.deployment_authorized,
                     self.training_authorized):
            if flag is not False:
                raise NaturalPT1Error("PT1 natural authority is always false")

    @property
    def cell_keys(self) -> tuple[tuple[str, int, str, int], ...]:
        return tuple((rank, banker, role, threshold)
                     for rank in self.trump_ranks
                     for banker in self.banker_seats
                     for role in self.role_buckets
                     for threshold in self.remaining_hand_thresholds)

    @property
    def state_keys(self) -> tuple[tuple[str, int, str, int, int], ...]:
        return tuple((*cell, replicate)
                     for cell in self.cell_keys
                     for replicate in range(self.replicates))

    def authority(self) -> dict[str, bool]:
        return {"gameplay_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False,
                "training_authorized": False}

    def payload(self) -> dict[str, object]:
        return {"schema": NATURAL_PT1_SCHEMA,
                "capture_secret_sha256": self.capture_secret_sha256,
                "trump_ranks": list(self.trump_ranks),
                "production_policy": self.production_policy,
                "banker_seats": list(self.banker_seats),
                "role_buckets": list(self.role_buckets),
                "remaining_hand_thresholds": list(self.remaining_hand_thresholds),
                "replicates": self.replicates,
                "capture_attempts_per_state": self.capture_attempts_per_state,
                "target_state_count": TARGET_STATE_COUNT,
                "authority": self.authority()}


@dataclass(frozen=True)
class NaturalPT1State:
    """One captured public/true-world pair; hidden state stays in ``true_world``."""

    rank: str
    banker: int
    role: str
    remaining_hand_threshold: int
    replicate: int
    round_seed: int
    capture_round_cluster_sha256: str
    capture_id_sha256: str
    public_state_sha256: str
    true_world_sha256: str
    public_round: object
    true_world: TrueWorld
    schema: str = NATURAL_PT1_STATE_SCHEMA

    def payload(self) -> dict[str, object]:
        return {"schema": self.schema,
                "capture_id_sha256": self.capture_id_sha256,
                "capture_round_cluster_sha256": self.capture_round_cluster_sha256,
                "trump_rank": self.rank, "banker": self.banker,
                "role": self.role,
                "remaining_hand_threshold": self.remaining_hand_threshold,
                "replicate": self.replicate,
                "public_state_sha256": self.public_state_sha256,
                "true_world_sha256": self.true_world_sha256,
                "authority": {"gameplay_authorized": False,
                               "strength_claim_authorized": False,
                               "promotion_authorized": False,
                               "deployment_authorized": False,
                               "training_authorized": False}}


def _capture_round_seed(secret: bytes, rank: str, banker: int, role: str,
                        threshold: int, replicate: int, attempt: int) -> int:
    message = canonical_json_bytes([
        NATURAL_PT1_SCHEMA, "capture-round", rank, banker, role,
        threshold, replicate, attempt])
    return int.from_bytes(hmac.new(secret, message, hashlib.sha256).digest()[:8],
                          "big")


def _check_secret(design: NaturalPT1Design, secret: bytes) -> bytes:
    if type(secret) is not bytes or len(secret) != 32 \
            or hashlib.sha256(secret).hexdigest() != design.capture_secret_sha256:
        raise NaturalPT1Error("capture secret commitment drift")
    return secret


def _world_sha256(rnd: object) -> str:
    payload = {"hands": [sorted(hand) for hand in rnd.hands],
               "buried": sorted(rnd.buried), "banker": rnd.banker,
               "trump_rank": rnd.trump_rank, "turn": rnd.turn}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _cluster_sha256(round_seed: int) -> str:
    return hashlib.sha256(canonical_json_bytes([
        NATURAL_PT1_SCHEMA, "capture-round-cluster", round_seed])).hexdigest()


def _capture_id_sha256(rank: str, banker: int, role: str, threshold: int,
                       replicate: int, public: str) -> str:
    return hashlib.sha256(canonical_json_bytes([
        NATURAL_PT1_STATE_SCHEMA, rank, banker, role, threshold, replicate,
        public])).hexdigest()


def _role(rnd: object, seat: int) -> str:
    return "banker-team" if seat % 2 == rnd.banker % 2 else "attacker-team"


def _capture_round(design: NaturalPT1Design, round_seed: int,
                   rank: str, banker: int):
    """Run ordinary production play and return first eligible hits only."""
    from ..ai.endgame import exhaustive_legal_actions
    from ..ai.registry import make_bot
    from ..engine.round import Round

    rnd = Round(rank, banker=banker, rng=random.Random(round_seed))
    bots = [make_bot(design.production_policy,
                     seed=int.from_bytes(hashlib.sha256(
                         canonical_json_bytes([NATURAL_PT1_SCHEMA, round_seed, s])
                     ).digest()[:8], "big")) for s in range(4)]
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
    hits = {}
    while rnd.phase == "play":
        seat = rnd.turn
        assert seat is not None
        threshold = max(len(hand) for hand in rnd.hands)
        key = (_role(rnd, seat), threshold)
        if threshold in design.remaining_hand_thresholds and key not in hits:
            actions = exhaustive_legal_actions(rnd, seat,
                                                max_hand_cards=threshold)
            if len(actions) >= 2:
                hits[key] = copy.deepcopy(rnd)
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
        if len(hits) == len(ROLE_BUCKETS) * len(REMAINING_HAND_THRESHOLDS):
            break
    return hits


def _first_eligible(state: object, *, role: str, threshold: int):
    """Capture predicate kept separate to make outcome blindness auditable."""
    from ..ai.endgame import exhaustive_legal_actions
    from ..engine.round import Round
    if type(state) is not Round or state.phase != "play" or state.turn is None:
        raise NaturalPT1Error("capture callback did not return active exact Round")
    seat = state.turn
    if _role(state, seat) != role or max(len(hand) for hand in state.hands) != threshold:
        return None
    if len(exhaustive_legal_actions(state, seat, max_hand_cards=threshold)) < 2:
        return None
    return copy.deepcopy(state)


def _state_from_round(design: NaturalPT1Design, state: object, *, rank: str,
                      banker: int, role: str, threshold: int, replicate: int,
                      round_seed: int) -> NaturalPT1State:
    from ..engine.round import Round
    if type(state) is not Round or state.banker != banker or state.trump_rank != rank:
        raise NaturalPT1Error("captured state rank/banker drift")
    if state.turn is None or _role(state, state.turn) != role \
            or max(len(hand) for hand in state.hands) != threshold:
        raise NaturalPT1Error("captured state cell drift")
    public = pt0_public_state_sha256(state, perspective_seat=state.turn)
    true_round = copy.deepcopy(state)
    true_world = seal_true_world(true_round)
    if pt0_public_state_sha256(true_round, perspective_seat=true_round.turn) != public:
        raise NaturalPT1Error("captured public-state fingerprint drift")
    world_hash = _world_sha256(true_round)
    cluster = _cluster_sha256(round_seed)
    capture_id = _capture_id_sha256(
        rank, banker, role, threshold, replicate, public)
    return NaturalPT1State(
        rank, banker, role, threshold, replicate, round_seed, cluster,
        capture_id, public, world_hash, copy.deepcopy(state), true_world)


def capture_natural_states(
        design: NaturalPT1Design, *, capture_secret: bytes,
        state_capture: Callable[..., object] | None = None) \
        -> dict[tuple[str, int, str, int, int], NaturalPT1State]:
    """Capture exactly one chronological first-eligible state per target key."""
    if type(design) is not NaturalPT1Design:
        raise NaturalPT1Error("capture requires NaturalPT1Design")
    secret = _check_secret(design, capture_secret)
    if state_capture is not None and not callable(state_capture):
        raise NaturalPT1Error("state_capture must be callable")
    captured = {}
    used_seeds = set()
    used_clusters = set()
    used_capture_ids = set()
    for rank, banker, role, threshold, replicate in design.state_keys:
        hit = None
        for attempt in range(design.capture_attempts_per_state):
            seed = _capture_round_seed(secret, rank, banker, role,
                                       threshold, replicate, attempt)
            if seed in used_seeds:
                raise NaturalPT1Error("capture round seed collision")
            used_seeds.add(seed)
            state = (state_capture(design, seed, rank, banker, role,
                                    threshold, replicate)
                     if state_capture is not None
                     else _capture_round(design, seed, rank, banker).get(
                         (role, threshold)))
            if state is None:
                continue
            if isinstance(state, Mapping):
                state = state.get((role, threshold))
            if state is None:
                continue
            eligible = _first_eligible(state, role=role, threshold=threshold)
            if eligible is None:
                continue
            candidate = _state_from_round(
                design, eligible, rank=rank, banker=banker, role=role,
                threshold=threshold, replicate=replicate, round_seed=seed)
            if candidate.capture_round_cluster_sha256 in used_clusters:
                raise NaturalPT1Error("duplicate capture round cluster")
            if candidate.capture_id_sha256 in used_capture_ids:
                raise NaturalPT1Error("duplicate natural PT1 state identity")
            used_clusters.add(candidate.capture_round_cluster_sha256)
            used_capture_ids.add(candidate.capture_id_sha256)
            captured[(rank, banker, role, threshold, replicate)] = candidate
            break
        if (rank, banker, role, threshold, replicate) not in captured:
            raise NaturalPT1Error(
                f"incomplete natural PT1 population cell: {(rank, banker, role, threshold, replicate)}")
    if len(captured) != TARGET_STATE_COUNT or len(used_clusters) != TARGET_STATE_COUNT:
        raise NaturalPT1Error("natural PT1 population coverage/cluster drift")
    return captured


def validate_population(
        design: NaturalPT1Design,
        states: Mapping[tuple[str, int, str, int, int], NaturalPT1State]):
    """Validate a captured population without opening result/action paths."""
    from ..engine.round import Round

    if type(design) is not NaturalPT1Design:
        raise NaturalPT1Error("validation requires NaturalPT1Design")
    if not isinstance(states, Mapping):
        raise NaturalPT1Error("natural PT1 population must be a mapping")
    if set(states) != set(design.state_keys):
        raise NaturalPT1Error("natural PT1 population cells incomplete or duplicated")
    clusters = set()
    capture_ids = set()
    round_seeds = set()
    for key, state in states.items():
        if (type(state) is not NaturalPT1State
                or type(state.rank) is not str
                or type(state.banker) is not int
                or isinstance(state.banker, bool)
                or type(state.role) is not str
                or type(state.remaining_hand_threshold) is not int
                or isinstance(state.remaining_hand_threshold, bool)
                or type(state.replicate) is not int
                or isinstance(state.replicate, bool)):
            raise NaturalPT1Error("natural PT1 state field type drift")
        if type(state) is not NaturalPT1State or key != (
                state.rank, state.banker, state.role,
                state.remaining_hand_threshold, state.replicate):
            raise NaturalPT1Error("natural PT1 state identity drift")
        if state.schema != NATURAL_PT1_STATE_SCHEMA:
            raise NaturalPT1Error("natural PT1 state schema drift")
        if (isinstance(state.round_seed, bool)
                or not isinstance(state.round_seed, int)
                or state.round_seed < 0):
            raise NaturalPT1Error("natural PT1 round seed drift")
        if state.round_seed in round_seeds:
            raise NaturalPT1Error("duplicate natural PT1 round seed")
        if type(state.public_round) is not Round:
            raise NaturalPT1Error("natural PT1 public round type drift")
        try:
            true_round = state.true_world.verify()
        except PrivilegedTeacherPT0Error as exc:
            raise NaturalPT1Error("natural PT1 true-world capability drift") from exc
        if type(true_round) is not Round:
            raise NaturalPT1Error("natural PT1 true-world round type drift")
        for rnd in (state.public_round, true_round):
            if (rnd.trump_rank != state.rank or rnd.banker != state.banker
                    or rnd.turn is None
                    or _role(rnd, rnd.turn) != state.role
                    or max(len(hand) for hand in rnd.hands)
                    != state.remaining_hand_threshold):
                raise NaturalPT1Error("natural PT1 state cell/round drift")
        if state.public_round.turn != true_round.turn:
            raise NaturalPT1Error("natural PT1 actor turn drift")
        actor = state.public_round.turn
        if list(state.public_round.hands[actor]) != list(true_round.hands[actor]):
            raise NaturalPT1Error("natural PT1 actor hand drift")
        _sha(state.public_state_sha256, "public_state_sha256")
        _sha(state.true_world_sha256, "true_world_sha256")
        _sha(state.capture_round_cluster_sha256,
             "capture_round_cluster_sha256")
        _sha(state.capture_id_sha256, "capture_id_sha256")
        if pt0_public_state_sha256(state.public_round,
                                   perspective_seat=actor) \
                != state.public_state_sha256:
            raise NaturalPT1Error("natural PT1 public-state fingerprint drift")
        if pt0_public_state_sha256(
                true_round, perspective_seat=actor) \
                != state.public_state_sha256:
            raise NaturalPT1Error("natural PT1 true-world public mismatch")
        if _world_sha256(true_round) != state.true_world_sha256:
            raise NaturalPT1Error("natural PT1 true-world fingerprint drift")
        if _cluster_sha256(state.round_seed) \
                != state.capture_round_cluster_sha256:
            raise NaturalPT1Error("natural PT1 capture cluster fingerprint drift")
        if _capture_id_sha256(
                state.rank, state.banker, state.role,
                state.remaining_hand_threshold, state.replicate,
                state.public_state_sha256) != state.capture_id_sha256:
            raise NaturalPT1Error("natural PT1 capture identity fingerprint drift")
        if state.capture_round_cluster_sha256 in clusters:
            raise NaturalPT1Error("duplicate capture round cluster")
        if state.capture_id_sha256 in capture_ids:
            raise NaturalPT1Error("duplicate natural PT1 state identity")
        round_seeds.add(state.round_seed)
        clusters.add(state.capture_round_cluster_sha256)
        capture_ids.add(state.capture_id_sha256)
    if len(clusters) != TARGET_STATE_COUNT:
        raise NaturalPT1Error("natural PT1 cluster population incomplete")


def run_natural_population(
        design: NaturalPT1Design, *, capture_secret: bytes,
        state_capture: Callable[..., object] | None = None) -> dict[str, object]:
    states = capture_natural_states(
        design, capture_secret=capture_secret, state_capture=state_capture)
    validate_population(design, states)
    records = [states[key].payload() for key in design.state_keys]
    packet = {"schema": NATURAL_PT1_SCHEMA,
              "design_sha256": hashlib.sha256(
                  canonical_json_bytes(design.payload())).hexdigest(),
              "records": records, "record_count": len(records),
              "total_record_count": TARGET_STATE_COUNT,
              "status": "COMPLETE", "truncated_by_deadline": False,
              "authority": design.authority()}
    packet["packet_sha256"] = hashlib.sha256(
        canonical_json_bytes(packet)).hexdigest()
    canonical_json_bytes(packet)
    return packet


capture_pt1_states = capture_natural_states
run_natural_packet = run_natural_population

__all__ = [
    "BANKER_SEATS", "NATURAL_PT1_SCHEMA", "NATURAL_PT1_STATE_SCHEMA",
    "NaturalPT1Design", "NaturalPT1Error", "NaturalPT1State",
    "REMAINING_HAND_THRESHOLDS", "REPLICATES", "ROLE_BUCKETS",
    "TARGET_STATE_COUNT", "capture_natural_states", "capture_pt1_states",
    "run_natural_packet", "run_natural_population", "validate_population",
]
