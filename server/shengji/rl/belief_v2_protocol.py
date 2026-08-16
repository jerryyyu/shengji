"""Canonical score-free BELIEF-V1 V2 population proposal.

This module freezes a balanced all-rank population and the deterministic
identities needed to review its future capture implementation.  It creates no
files, starts no workers, opens no corpus, trains no model, and authorizes no
execution.  Host/runtime identities, human source-log membership, resource
caps, and the V1 terminal routing receipt remain inputs to a later immutable
execution freeze.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..engine.cards import RANKS
from ..engine.round import Round
from .belief_contract import canonical_json_bytes
from .belief_corpus import SPLIT_SCHEMA, split_for_round_seed


V2_PROTOCOL_SCHEMA = "belief-v1-v2-diverse-population-proposal-v1"
V2_SEED_NAMESPACE = "belief-v1-v2-all-ranks-champion-human-v1"
V2_RANKS = tuple(RANKS)
V2_CAPTURE_LANES = 16
V2_ROUNDS_PER_RANK = 1_024
V2_ROUNDS_PER_LANE_RANK = 64
V2_ROUND_COUNT = 13_312
V2_SPLIT_COUNTS_PER_RANK = (
    ("train", 819), ("calibration", 102), ("test", 103))
V2_SPLIT_COUNTS = (
    ("train", 10_647), ("calibration", 1_326), ("test", 1_339))
V2_REFERENCE_WORLD_COUNT = 256
V2_CANDIDATE_MEMBER_COUNT = 8
V2_LABEL_CONTROL_MEMBER_COUNT = 8
MAX_SEED = 2**63 - 1

# Immutable V1 population: V2 must be disjoint even though collision is
# already cryptographically unlikely.  Other project populations are checked
# by the future source-independent registry scan at execution freeze.
V1_B2_SEED_START = 6_104_125_432_620_400_640
V1_B2_SEED_END = V1_B2_SEED_START + 4_096 - 1

HUMAN_V8_MANIFEST_SHA256 = (
    "b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553")
HUMAN_V8_SOURCE_FILE_COUNT = 30
HUMAN_V8_ROUNDS_SEEN = 129
HUMAN_V8_ROUNDS_REPLAYED = 122
HUMAN_V8_INCOMPLETE_ROUNDS = 7
HUMAN_V8_ACCEPTED_PLAYS = 2_830
HUMAN_V8_ACCEPTED_BURIES = 45


class BeliefV2ProtocolError(ValueError):
    """A V2 population coordinate or derived identity drifted."""


@dataclass(frozen=True)
class V2RoundCoordinate:
    """One rank-balanced synthetic round selected without opening its deal."""

    trump_rank: str
    rank_index: int
    rank_ordinal: int
    round_seed: int
    split: str
    lane: int


def _derive_seed(label: str) -> int:
    if type(label) is not str or not label:
        raise BeliefV2ProtocolError("V2 seed label is invalid")
    return int.from_bytes(hashlib.sha256(
        f"{V2_PROTOCOL_SCHEMA}|{V2_SEED_NAMESPACE}|{label}".encode(
            "ascii")).digest()[:8], "big") & MAX_SEED


def _order_key(label: str) -> bytes:
    if type(label) is not str or not label:
        raise BeliefV2ProtocolError("V2 ordering label is invalid")
    return hashlib.sha256(
        f"{V2_PROTOCOL_SCHEMA}|order|{label}".encode("ascii")).digest()


@lru_cache(maxsize=len(V2_RANKS))
def _rank_seed_population(trump_rank: str) -> tuple[int, ...]:
    """Select exact split quotas from a deal-blind deterministic seed stream."""
    if trump_rank not in V2_RANKS:
        raise BeliefV2ProtocolError("V2 trump rank is invalid")
    quotas = dict(V2_SPLIT_COUNTS_PER_RANK)
    selected: dict[str, list[int]] = {split: [] for split in quotas}
    seen: set[int] = set()
    candidate_index = 0
    while any(len(selected[split]) < quota
              for split, quota in quotas.items()):
        seed = _derive_seed(f"round|rank-{trump_rank}|candidate-{candidate_index}")
        candidate_index += 1
        if seed in seen or V1_B2_SEED_START <= seed <= V1_B2_SEED_END:
            continue
        seen.add(seed)
        split = split_for_round_seed(seed)
        if len(selected[split]) < quotas[split]:
            selected[split].append(seed)
    seeds = tuple(seed for values in selected.values() for seed in values)
    if len(seeds) != V2_ROUNDS_PER_RANK or len(set(seeds)) != len(seeds):
        raise BeliefV2ProtocolError("V2 rank seed population drift")
    return tuple(sorted(
        seeds,
        key=lambda seed: (_order_key(f"rank-{trump_rank}|seed-{seed}"), seed)))


@lru_cache(maxsize=1)
def v2_round_coordinates() -> tuple[V2RoundCoordinate, ...]:
    rows: list[V2RoundCoordinate] = []
    seen: set[int] = set()
    for rank_index, trump_rank in enumerate(V2_RANKS):
        seeds = _rank_seed_population(trump_rank)
        for rank_ordinal, seed in enumerate(seeds):
            if seed in seen:
                raise BeliefV2ProtocolError("V2 cross-rank seed collision")
            seen.add(seed)
            rows.append(V2RoundCoordinate(
                trump_rank=trump_rank,
                rank_index=rank_index,
                rank_ordinal=rank_ordinal,
                round_seed=seed,
                split=split_for_round_seed(seed),
                lane=rank_ordinal % V2_CAPTURE_LANES))
    result = tuple(rows)
    if len(result) != V2_ROUND_COUNT:
        raise BeliefV2ProtocolError("V2 round population drift")
    return result


def v2_round_coordinate(trump_rank: str, rank_ordinal: int) \
        -> V2RoundCoordinate:
    if trump_rank not in V2_RANKS or type(rank_ordinal) is not int \
            or not 0 <= rank_ordinal < V2_ROUNDS_PER_RANK:
        raise BeliefV2ProtocolError("V2 round coordinate is invalid")
    rank_index = V2_RANKS.index(trump_rank)
    return v2_round_coordinates()[
        rank_index * V2_ROUNDS_PER_RANK + rank_ordinal]


def v2_lane_coordinates(lane: int) -> tuple[V2RoundCoordinate, ...]:
    """Return one exact balanced 832-round production capture lane."""
    if type(lane) is not int or lane not in range(V2_CAPTURE_LANES):
        raise BeliefV2ProtocolError("V2 capture lane is invalid")
    result = tuple(row for row in v2_round_coordinates()
                   if row.lane == lane)
    if len(result) != V2_ROUND_COUNT // V2_CAPTURE_LANES \
            or any(sum(row.trump_rank == rank for row in result)
                   != V2_ROUNDS_PER_LANE_RANK for rank in V2_RANKS):
        raise BeliefV2ProtocolError("V2 capture lane population drift")
    return result


def v2_research_round(coordinate: V2RoundCoordinate) -> Round:
    """Construct the exact first-round state for a reviewed V2 coordinate."""
    if type(coordinate) is not V2RoundCoordinate \
            or coordinate != v2_round_coordinate(
                coordinate.trump_rank, coordinate.rank_ordinal):
        raise BeliefV2ProtocolError("V2 round coordinate derivation drift")
    return Round(coordinate.trump_rank, banker=None,
                 rng=random.Random(coordinate.round_seed))


def v2_policy_seeds(coordinate: V2RoundCoordinate) \
        -> tuple[int, int, int, int]:
    if type(coordinate) is not V2RoundCoordinate \
            or coordinate != v2_round_coordinate(
                coordinate.trump_rank, coordinate.rank_ordinal):
        raise BeliefV2ProtocolError("V2 policy coordinate derivation drift")
    seeds = tuple(_derive_seed(
        f"champion-policy|rank-{coordinate.trump_rank}|round-"
        f"{coordinate.round_seed}|seat-{seat}") for seat in range(4))
    if len(set(seeds)) != 4 or coordinate.round_seed in seeds:
        raise BeliefV2ProtocolError("V2 policy seed collision")
    return seeds  # type: ignore[return-value]


def schedule_dict() -> dict[str, Any]:
    return {
        "schema": "belief-v1-v2-synthetic-schedule-v1",
        "coordinates": [
            {
                "lane": row.lane,
                "rank_index": row.rank_index,
                "rank_ordinal": row.rank_ordinal,
                "round_seed": row.round_seed,
                "split": row.split,
                "trump_rank": row.trump_rank,
            }
            for row in v2_round_coordinates()
        ],
    }


def schedule_bytes() -> bytes:
    return canonical_json_bytes(schedule_dict())


def schedule_sha256() -> str:
    return hashlib.sha256(schedule_bytes()).hexdigest()


def protocol_dict() -> dict[str, Any]:
    rows = v2_round_coordinates()
    by_split = {split: sum(row.split == split for row in rows)
                for split, _ in V2_SPLIT_COUNTS}
    by_rank = {rank: sum(row.trump_rank == rank for row in rows)
               for rank in V2_RANKS}
    if tuple(by_split.items()) != V2_SPLIT_COUNTS \
            or set(by_rank.values()) != {V2_ROUNDS_PER_RANK}:
        raise BeliefV2ProtocolError("V2 population summary drift")
    return {
        "schema": V2_PROTOCOL_SCHEMA,
        "status": "source-design-proposal-not-execution-freeze",
        "seed_namespace": V2_SEED_NAMESPACE,
        "schedule_sha256": schedule_sha256(),
        "synthetic_population": {
            "round_count": V2_ROUND_COUNT,
            "trump_ranks": list(V2_RANKS),
            "rounds_per_rank": V2_ROUNDS_PER_RANK,
            "capture_lanes": V2_CAPTURE_LANES,
            "rounds_per_lane_rank": V2_ROUNDS_PER_LANE_RANK,
            "rounds_per_lane": V2_ROUND_COUNT // V2_CAPTURE_LANES,
            "split_schema": SPLIT_SCHEMA,
            "split_counts_per_rank": dict(V2_SPLIT_COUNTS_PER_RANK),
            "split_counts": by_split,
            "selection_rule": (
                "first-domain-separated-seeds-satisfying-frozen-split-quotas"),
            "lane_rule": "rank_ordinal%16-after-domain-separated-ordering",
            "banker_at_round_start": None,
            "retry_count": 0,
            "drop_count": 0,
        },
        "human_input": {
            "starting_asset_manifest_sha256": HUMAN_V8_MANIFEST_SHA256,
            "source_file_count": HUMAN_V8_SOURCE_FILE_COUNT,
            "rounds_seen": HUMAN_V8_ROUNDS_SEEN,
            "rounds_replayed": HUMAN_V8_ROUNDS_REPLAYED,
            "incomplete_rounds": HUMAN_V8_INCOMPLETE_ROUNDS,
            "accepted_human_plays": HUMAN_V8_ACCEPTED_PLAYS,
            "accepted_human_buries": HUMAN_V8_ACCEPTED_BURIES,
            "starting_asset_training_authorized": False,
            "v2_belief_training_authorized": False,
            "required_before_freeze": (
                "new-belief-specific-H0-inventory-builder-and-review"),
        },
        "parallel_after_capture": [
            "synthetic-only-training",
            "bounded-human-mixture-training",
            "ref-c-transcript-replay",
        ],
        "reference": {
            "accepted_worlds_per_decision": V2_REFERENCE_WORLD_COUNT,
            "training_dependency": False,
        },
        "training": {
            "candidate_member_count": V2_CANDIDATE_MEMBER_COUNT,
            "hard_geometry_permuted_label_member_count": (
                V2_LABEL_CONTROL_MEMBER_COUNT),
            "human_mixture_fraction": "freeze-after-H0-inventory-max-20-percent",
        },
        "freeze_inputs_missing": [
            "v1-b2-terminal-result-and-resource-receipts",
            "reviewed-ref-c-replay-successor",
            "reviewed-belief-specific-human-H0-inventory",
            "multi-rank-capacity-and-training-profile",
            "host-runtime-native-identities-and-caps",
        ],
        "authority": {
            "human_log_access_authorized": False,
            "population_capture_authorized": False,
            "reference_generation_authorized": False,
            "training_authorized": False,
            "test_split_open_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
        },
    }


def protocol_bytes() -> bytes:
    return canonical_json_bytes(protocol_dict())


def protocol_sha256() -> str:
    return hashlib.sha256(protocol_bytes()).hexdigest()
