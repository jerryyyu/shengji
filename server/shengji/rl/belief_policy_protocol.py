"""Score-free population and RNG identities for the R4 policy diagnostic."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

from ..engine.cards import RANKS


POLICY_PROTOCOL_SCHEMA = "belief-r4-opened-dev-policy-diagnostic-v1"
POLICY_SEED_NAMESPACE = "belief-r4-policy-opened-dev-20260831-v1"
POLICY_RANKS = tuple(RANKS)
CANDIDATE_ROUNDS_PER_RANK = 32
SELECTED_ROUNDS_PER_RANK = 8
TARGET_ROUND_COUNT = len(POLICY_RANKS) * SELECTED_ROUNDS_PER_RANK
REFERENCE_WORLD_COUNT = 256
SELECTION_WORLD_COUNT = 30
REPORT_WORLD_COUNT = 300
CAPACITY_ROUND_COUNT = 16
MAX_SEED = 2**63 - 1
FOLD_LABELS = ("proposal-reference", "selection", "report")


class BeliefPolicyProtocolError(ValueError):
    """A policy diagnostic coordinate or derived RNG identity drifted."""


@dataclass(frozen=True)
class PolicyRoundCoordinateV1:
    trump_rank: str
    rank_index: int
    rank_ordinal: int
    round_seed: int


def _seed(label: str) -> int:
    if type(label) is not str or not label:
        raise BeliefPolicyProtocolError("policy diagnostic seed label drift")
    return int.from_bytes(hashlib.sha256(
        f"{POLICY_PROTOCOL_SCHEMA}|{POLICY_SEED_NAMESPACE}|{label}".encode(
            "ascii")).digest()[:8], "big") & MAX_SEED


@lru_cache(maxsize=1)
def policy_round_coordinates() -> tuple[PolicyRoundCoordinateV1, ...]:
    rows = tuple(
        PolicyRoundCoordinateV1(
            trump_rank=rank,
            rank_index=rank_index,
            rank_ordinal=ordinal,
            round_seed=_seed(f"round|rank-{rank}|ordinal-{ordinal}"),
        )
        for rank_index, rank in enumerate(POLICY_RANKS)
        for ordinal in range(CANDIDATE_ROUNDS_PER_RANK)
    )
    if len(rows) != len(POLICY_RANKS) * CANDIDATE_ROUNDS_PER_RANK \
            or len({row.round_seed for row in rows}) != len(rows):
        raise BeliefPolicyProtocolError(
            "policy diagnostic round population drift")
    return rows


def policy_rank_coordinates(
        trump_rank: str) -> tuple[PolicyRoundCoordinateV1, ...]:
    if trump_rank not in POLICY_RANKS:
        raise BeliefPolicyProtocolError(
            "policy diagnostic trump rank drift")
    rows = tuple(row for row in policy_round_coordinates()
                 if row.trump_rank == trump_rank)
    if len(rows) != CANDIDATE_ROUNDS_PER_RANK:
        raise BeliefPolicyProtocolError(
            "policy diagnostic rank population drift")
    return rows


@lru_cache(maxsize=1)
def policy_capacity_coordinates() -> tuple[PolicyRoundCoordinateV1, ...]:
    """Return a score-free namespace disjoint from scientific coordinates."""
    rows = tuple(PolicyRoundCoordinateV1(
        trump_rank=POLICY_RANKS[index % len(POLICY_RANKS)],
        rank_index=index % len(POLICY_RANKS),
        rank_ordinal=index,
        round_seed=_seed(f"capacity-round|index-{index}"),
    ) for index in range(CAPACITY_ROUND_COUNT))
    if len({row.round_seed for row in rows}) != CAPACITY_ROUND_COUNT \
            or {row.round_seed for row in rows} & {
                row.round_seed for row in policy_round_coordinates()}:
        raise BeliefPolicyProtocolError(
            "policy diagnostic capacity namespace drift")
    return rows


def _known_coordinate(coordinate: PolicyRoundCoordinateV1) -> bool:
    return coordinate in policy_round_coordinates() \
        or coordinate in policy_capacity_coordinates()


def policy_seat_seeds(
        coordinate: PolicyRoundCoordinateV1) -> tuple[int, int, int, int]:
    if type(coordinate) is not PolicyRoundCoordinateV1 \
            or not _known_coordinate(coordinate):
        raise BeliefPolicyProtocolError(
            "policy diagnostic coordinate derivation drift")
    seeds = tuple(_seed(
        f"seat-policy|round-{coordinate.round_seed}|seat-{seat}")
        for seat in range(4))
    if len(set(seeds)) != 4 or coordinate.round_seed in seeds:
        raise BeliefPolicyProtocolError(
            "policy diagnostic seat seed collision")
    return seeds  # type: ignore[return-value]


def policy_fold_seed(
        coordinate: PolicyRoundCoordinateV1, *,
        decision_index: int, actor_sha256: str, fold: str) -> int:
    if type(coordinate) is not PolicyRoundCoordinateV1 \
            or not _known_coordinate(coordinate) \
            or type(decision_index) is not int or decision_index < 0 \
            or type(actor_sha256) is not str or len(actor_sha256) != 64 \
            or any(char not in "0123456789abcdef" for char in actor_sha256) \
            or fold not in FOLD_LABELS:
        raise BeliefPolicyProtocolError(
            "policy diagnostic fold seed input drift")
    return _seed(
        f"world-fold|round-{coordinate.round_seed}|decision-{decision_index}|"
        f"actor-{actor_sha256}|fold-{fold}")


def policy_root_order_key(
        coordinate: PolicyRoundCoordinateV1, *,
        decision_index: int, actor_sha256: str) -> bytes:
    if type(coordinate) is not PolicyRoundCoordinateV1 \
            or not _known_coordinate(coordinate) \
            or type(decision_index) is not int or decision_index < 0 \
            or type(actor_sha256) is not str or len(actor_sha256) != 64 \
            or any(char not in "0123456789abcdef" for char in actor_sha256):
        raise BeliefPolicyProtocolError(
            "policy diagnostic root identity drift")
    return hashlib.sha256(
        f"{POLICY_PROTOCOL_SCHEMA}|root-order|round-{coordinate.round_seed}|"
        f"decision-{decision_index}|actor-{actor_sha256}".encode("ascii")
    ).digest()
