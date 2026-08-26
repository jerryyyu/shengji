"""Disposable, non-scientific population for the BELIEF V2 DAG rehearsal.

This module deliberately does not alter the production V2 protocol.  It
defines a separate domain-separated population whose only purpose is to prove
that the reviewed worker/controller/artifact wiring can traverse every stage
before a multi-day production admission is consumed.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..engine.cards import RANKS
from ..ai.heuristic import HeuristicBot
from ..engine.round import Round, actual_play_after
from .belief_contract import canonical_json_bytes
from .belief_corpus import SPLIT_SCHEMA, split_for_round_seed
from .belief_v2_protocol import (
    MAX_SEED,
    V1_B2_SEED_END,
    V1_B2_SEED_START,
    V2_CAPTURE_LANES,
    V2_REFERENCE_WORLD_COUNT,
    V2_RANKS,
    V2RoundCoordinate,
    v2_round_coordinates,
)
from .belief_v2_progress import PROGRESS_SCHEMA


REHEARSAL_SCHEMA = "belief-v1-v2-full-dag-rehearsal-v1"
REHEARSAL_RECEIPT_SCHEMA = "belief-v1-v2-full-dag-rehearsal-receipt-v1"
REHEARSAL_SEED_NAMESPACE = "belief-v1-v2-full-dag-rehearsal-104-v1"
REHEARSAL_ROUNDS_PER_RANK = 8
REHEARSAL_ROUND_COUNT = len(V2_RANKS) * REHEARSAL_ROUNDS_PER_RANK
REHEARSAL_SPLIT_COUNTS_PER_RANK = (
    ("train", 6), ("calibration", 1), ("test", 1))
REHEARSAL_SPLIT_COUNTS = (
    ("train", 6 * len(V2_RANKS) - 3),
    ("calibration", len(V2_RANKS) + 3),
    ("test", len(V2_RANKS)),
)
REHEARSAL_HUMAN_SOURCE_COUNT = 30
REHEARSAL_HUMAN_SPLIT_COUNTS = (
    ("train", 24), ("calibration", 3), ("test", 3))
REHEARSAL_MINIMUM_COMPLETED_EPOCHS = 1
REHEARSAL_TRAIN_BATCH_DECISION_CAP = 128
REHEARSAL_STAGE_ORDER = (
    "synthetic-capture", "human-capture", "training-input-index",
    "training-tensor-cache", "device-qualification", "references",
    "training", "calibration", "single-test-opening",
    "terminal-verification",
)
REHEARSAL_PROGRESS_STAGES = (
    "capture", "human-capture", "training-input-index",
    "training-tensor-cache", "device-qualification", "reference",
    "human-reference", "training", "calibration", "terminal",
    "terminal-verification",
)
_PROGRESS_ROW_KEYS = {
    "schema", "stage", "worker", "phase", "completed_units",
    "total_units", "percent_basis_points", "elapsed_nanoseconds",
    "estimated_remaining_nanoseconds", "status", "outcome_blind",
    "evidence_artifact", "strength_claim_authorized",
    "deployment_authorized",
}


class BeliefV2RehearsalError(ValueError):
    """The disposable rehearsal identity or population drifted."""


def _is_hex(value: Any, length: int) -> bool:
    return (type(value) is str and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _progress_token(value: Any) -> bool:
    return type(value) is str and bool(value) and value.isascii() \
        and all(char.isalnum() or char in "-_." for char in value)


def _validate_receipt_progress(
        progress: Any, *, eligible: bool) -> None:
    if type(progress) is not dict or set(progress) != {
            "row_count", "worker_count", "phase_count",
            "population_sha256", "rows"} \
            or any(type(progress[field]) is not int or progress[field] < 0
                   for field in ("row_count", "worker_count", "phase_count")) \
            or type(progress["rows"]) is not list \
            or progress["row_count"] != len(progress["rows"]) \
            or not _is_hex(progress["population_sha256"], 64) \
            or hashlib.sha256(canonical_json_bytes(
                progress["rows"])).hexdigest() \
            != progress["population_sha256"]:
        raise BeliefV2RehearsalError("V2 rehearsal progress identity drift")
    phases: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    workers: dict[tuple[str, str], list[dict[str, Any]]] = {}
    phase_started_elapsed: dict[tuple[str, str, str], int] = {}
    for row in progress["rows"]:
        completed = row.get("completed_units") if type(row) is dict else None
        total = row.get("total_units") if type(row) is dict else None
        elapsed = row.get("elapsed_nanoseconds") if type(row) is dict else None
        phase_key = ((row.get("stage"), row.get("worker"), row.get("phase"))
                     if type(row) is dict else (None, None, None))
        if type(elapsed) is int and elapsed >= 0 \
                and all(type(value) is str for value in phase_key):
            phase_started = phase_started_elapsed.setdefault(phase_key, elapsed)
            phase_elapsed = elapsed - phase_started
        else:
            phase_elapsed = None
        phase_first = phase_key not in phases
        remaining = (None if completed == 0
                     or phase_first and completed < total else
                     phase_elapsed * (total - completed) // completed) \
            if type(completed) is int and type(total) is int \
            and type(phase_elapsed) is int and phase_elapsed >= 0 \
            and completed >= 0 and total > 0 \
            else object()
        if type(row) is not dict or set(row) != _PROGRESS_ROW_KEYS \
                or row.get("schema") != PROGRESS_SCHEMA \
                or row.get("stage") not in REHEARSAL_PROGRESS_STAGES \
                or not _progress_token(row.get("worker")) \
                or not _progress_token(row.get("phase")) \
                or type(completed) is not int or type(total) is not int \
                or total <= 0 or not 0 <= completed <= total \
                or type(elapsed) is not int or elapsed < 0 \
                or row.get("percent_basis_points") \
                != completed * 10_000 // total \
                or row.get("estimated_remaining_nanoseconds") != remaining \
                or row.get("status") \
                != ("complete" if completed == total else "running") \
                or row.get("outcome_blind") is not True \
                or row.get("evidence_artifact") is not False \
                or row.get("strength_claim_authorized") is not False \
                or row.get("deployment_authorized") is not False:
            raise BeliefV2RehearsalError(
                "V2 rehearsal progress row drift")
        phase_key = (row["stage"], row["worker"], row["phase"])
        worker_key = (row["stage"], row["worker"])
        phases.setdefault(phase_key, []).append(row)
        workers.setdefault(worker_key, []).append(row)
    if progress["worker_count"] != len(workers) \
            or progress["phase_count"] != len(phases) \
            or any(len({row["total_units"] for row in rows}) != 1
                   or [row["completed_units"] for row in rows]
                   != sorted(row["completed_units"] for row in rows)
                   or [row["elapsed_nanoseconds"] for row in rows]
                   != sorted(row["elapsed_nanoseconds"] for row in rows)
                   for rows in phases.values()):
        raise BeliefV2RehearsalError("V2 rehearsal progress identity drift")
    if eligible and (
            set(row["stage"] for row in progress["rows"])
            != set(REHEARSAL_PROGRESS_STAGES)
            or not workers
            or any(rows[-1]["status"] != "complete"
                   for rows in workers.values())):
        raise BeliefV2RehearsalError(
            "V2 rehearsal progress coverage drift")


@dataclass(frozen=True)
class V2RehearsalCoordinateV1:
    trump_rank: str
    rank_index: int
    rank_ordinal: int
    round_seed: int
    split: str
    lane: int


def _human_event(round_number: int, kind: str, **fields: Any) \
        -> dict[str, Any]:
    return {"round": round_number, "e": kind, **fields}


@lru_cache(maxsize=REHEARSAL_HUMAN_SOURCE_COUNT)
def rehearsal_human_source_bytes(source_index: int) -> bytes:
    """Create one complete, identity-disjoint fixture source group."""
    if type(source_index) is not int \
            or source_index not in range(REHEARSAL_HUMAN_SOURCE_COUNT):
        raise BeliefV2RehearsalError(
            "V2 rehearsal human source index drift")
    rank = V2_RANKS[source_index % len(V2_RANKS)]
    round_number = source_index + 1
    rnd = Round(rank, 0, random.Random(_derive_seed(
        f"human-fixture|source-{source_index:02d}")))
    events = [_human_event(
        round_number, "round_start", deck=list(rnd.deck), banker=rnd.banker,
        trump_rank=rnd.trump_rank, levels=[rank] * 4,
        players=[
            {"seat": 0, "name": f"Rehearsal Human {source_index:02d}",
             "is_bot": False},
            *({"seat": seat,
               "name": f"Rehearsal Bot {source_index:02d}-{seat}",
               "is_bot": True} for seat in range(1, 4)),
        ])]
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    events.append(_human_event(
        round_number, "trump", suit=rnd.trump_suit, rank=rnd.trump_rank,
        banker=rnd.banker, declared=False))
    bot = HeuristicBot()
    buried = bot.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, buried)
    events.append(_human_event(
        round_number, "bury", seat=rnd.banker, cards=buried, bot=False))
    first = True
    while rnd.phase == "play":
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        actual = actual_play_after(rnd, seat, previous_last)
        events.append(_human_event(
            round_number, "play", seat=seat, cards=actual,
            bot=not first))
        first = False
    events.append(_human_event(
        round_number, "round_end", attacker_points=rnd.attacker_points,
        kitty=list(rnd.buried), kitty_points=rnd.kitty_bonus,
        winner_team="attackers", level_change=1,
        new_levels=[rank] * 4, next_banker=0, game_over=False))
    return b"".join(json.dumps(
        event, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
        for event in events)


def _derive_seed(label: str) -> int:
    if type(label) is not str or not label:
        raise BeliefV2RehearsalError("V2 rehearsal seed label is invalid")
    return int.from_bytes(hashlib.sha256(
        f"{REHEARSAL_SCHEMA}|{REHEARSAL_SEED_NAMESPACE}|{label}".encode(
            "ascii")).digest()[:8], "big") & MAX_SEED


def _order_key(label: str) -> bytes:
    return hashlib.sha256(
        f"{REHEARSAL_SCHEMA}|order|{label}".encode("ascii")).digest()


def _production_seed_population() -> frozenset[int]:
    return frozenset(row.round_seed for row in v2_round_coordinates())


def _rank_rows(trump_rank: str, rank_index: int) \
        -> tuple[tuple[int, str], ...]:
    quotas = dict(REHEARSAL_SPLIT_COUNTS_PER_RANK)
    if trump_rank in _extra_calibration_ranks():
        quotas["train"] -= 1
        quotas["calibration"] += 1
    selected: dict[str, list[int]] = {split: [] for split in quotas}
    production = _production_seed_population()
    seen: set[int] = set()
    candidate_index = 0
    while any(len(selected[split]) < quota
              for split, quota in quotas.items()):
        seed = _derive_seed(
            f"round|rank-{trump_rank}|candidate-{candidate_index}")
        candidate_index += 1
        if seed in seen or seed in production \
                or V1_B2_SEED_START <= seed <= V1_B2_SEED_END:
            continue
        seen.add(seed)
        split = split_for_round_seed(seed)
        if len(selected[split]) < quotas[split]:
            selected[split].append(seed)
    rows = tuple((seed, split) for split, values in selected.items()
                 for seed in values)
    if len(rows) != REHEARSAL_ROUNDS_PER_RANK \
            or len({row[0] for row in rows}) != len(rows):
        raise BeliefV2RehearsalError(
            "V2 rehearsal rank population drift")
    return tuple(sorted(rows, key=lambda row: (
        _order_key(f"rank-{rank_index}|seed-{row[0]}"), row[0])))


@lru_cache(maxsize=1)
def _extra_calibration_ranks() -> tuple[str, str, str]:
    """Choose the three extra calibration ranks without hand selection."""
    selected = tuple(sorted(
        V2_RANKS,
        key=lambda rank: (_order_key(f"extra-calibration|{rank}"), rank))[:3])
    return selected  # type: ignore[return-value]


def _rank_split_counts(trump_rank: str) -> dict[str, int]:
    result = dict(REHEARSAL_SPLIT_COUNTS_PER_RANK)
    if trump_rank in _extra_calibration_ranks():
        result["train"] -= 1
        result["calibration"] += 1
    return result


@lru_cache(maxsize=1)
def rehearsal_round_coordinates() -> tuple[V2RehearsalCoordinateV1, ...]:
    """Return 104 distinct rounds with every lane carrying evaluation work."""
    pending: list[tuple[str, int, int, int, str]] = []
    seen: set[int] = set()
    for rank_index, trump_rank in enumerate(V2_RANKS):
        for rank_ordinal, (seed, split) in enumerate(
                _rank_rows(trump_rank, rank_index)):
            if seed in seen:
                raise BeliefV2RehearsalError(
                    "V2 rehearsal cross-rank seed collision")
            seen.add(seed)
            pending.append((
                trump_rank, rank_index, rank_ordinal, seed, split))

    # Give every production-shaped worker lane at least one calibration/test
    # coordinate so the real reference-lane path cannot be skipped.  Fill the
    # remainder by the currently smallest lane for an even 6/7-round load.
    calibration = [row for row in pending if row[4] == "calibration"]
    disposable_test = [row for row in pending if row[4] == "test"]
    training = [row for row in pending if row[4] == "train"]
    calibration.sort(key=lambda row: (
        _order_key(f"calibration|{row[3]}"), row[3]))
    disposable_test.sort(key=lambda row: (
        _order_key(f"test|{row[3]}"), row[3]))
    training.sort(key=lambda row: (
        _order_key(f"training|{row[3]}"), row[3]))
    lane_rows: list[list[tuple[str, int, int, int, str]]] = [
        [] for _ in range(V2_CAPTURE_LANES)]
    for lane, row in enumerate(calibration):
        lane_rows[lane].append(row)
    for row in disposable_test:
        lane = min(range(V2_CAPTURE_LANES),
                   key=lambda value: (len(lane_rows[value]), value))
        lane_rows[lane].append(row)
    for row in training:
        lane = min(range(V2_CAPTURE_LANES),
                   key=lambda value: (len(lane_rows[value]), value))
        lane_rows[lane].append(row)

    result = tuple(V2RehearsalCoordinateV1(
        trump_rank=row[0], rank_index=row[1], rank_ordinal=row[2],
        round_seed=row[3], split=row[4], lane=lane)
        for lane, rows in enumerate(lane_rows)
        for row in sorted(rows, key=lambda value: (
            value[1], value[2], value[3])))
    validate_rehearsal_coordinates(result)
    return result


def validate_rehearsal_coordinates(
        rows: tuple[V2RehearsalCoordinateV1, ...]) -> None:
    if type(rows) is not tuple or len(rows) != REHEARSAL_ROUND_COUNT \
            or any(type(row) is not V2RehearsalCoordinateV1 for row in rows) \
            or len({row.round_seed for row in rows}) != len(rows) \
            or any(row.trump_rank not in RANKS
                   or row.rank_index != V2_RANKS.index(row.trump_rank)
                   or not 0 <= row.rank_ordinal < REHEARSAL_ROUNDS_PER_RANK
                   or row.split != split_for_round_seed(row.round_seed)
                   or row.lane not in range(V2_CAPTURE_LANES)
                   for row in rows):
        raise BeliefV2RehearsalError("V2 rehearsal coordinate drift")
    if any(sum(row.trump_rank == rank for row in rows)
           != REHEARSAL_ROUNDS_PER_RANK for rank in V2_RANKS) \
            or any(sum(row.trump_rank == rank and row.split == split
                       for row in rows) != expected
                   for rank in V2_RANKS
                   for split, expected in _rank_split_counts(rank).items()) \
            or any(not any(row.lane == lane and row.split == "calibration"
                           for row in rows)
                   for lane in range(V2_CAPTURE_LANES)) \
            or any(not 6 <= sum(row.lane == lane for row in rows) <= 7
                   for lane in range(V2_CAPTURE_LANES)):
        raise BeliefV2RehearsalError("V2 rehearsal population drift")
    production = _production_seed_population()
    if any(row.round_seed in production
           or V1_B2_SEED_START <= row.round_seed <= V1_B2_SEED_END
           for row in rows):
        raise BeliefV2RehearsalError("V2 rehearsal seed overlap")


def rehearsal_lane_coordinates(
        lane: int) -> tuple[V2RehearsalCoordinateV1, ...]:
    if type(lane) is not int or lane not in range(V2_CAPTURE_LANES):
        raise BeliefV2RehearsalError("V2 rehearsal lane is invalid")
    rows = tuple(row for row in rehearsal_round_coordinates()
                 if row.lane == lane)
    if not rows or not any(row.split != "train" for row in rows):
        raise BeliefV2RehearsalError("V2 rehearsal lane population drift")
    return rows


@lru_cache(maxsize=1)
def rehearsal_v2_coordinates() -> tuple[V2RoundCoordinate, ...]:
    """Return rehearsal rows in the production controller's coordinate type."""
    return tuple(V2RoundCoordinate(
        trump_rank=row.trump_rank, rank_index=row.rank_index,
        rank_ordinal=row.rank_ordinal, round_seed=row.round_seed,
        split=row.split, lane=row.lane)
        for row in rehearsal_round_coordinates())


def rehearsal_v2_round_coordinate(
        trump_rank: str, rank_ordinal: int) -> V2RoundCoordinate:
    matches = tuple(row for row in rehearsal_v2_coordinates()
                    if row.trump_rank == trump_rank
                    and row.rank_ordinal == rank_ordinal)
    if len(matches) != 1:
        raise BeliefV2RehearsalError(
            "V2 rehearsal coordinate lookup drift")
    return matches[0]


def rehearsal_v2_lane_coordinates(
        lane: int) -> tuple[V2RoundCoordinate, ...]:
    rehearsal_lane_coordinates(lane)
    return tuple(row for row in rehearsal_v2_coordinates()
                 if row.lane == lane)


def rehearsal_policy_seeds(
        coordinate: V2RehearsalCoordinateV1) -> tuple[int, int, int, int]:
    if type(coordinate) is not V2RehearsalCoordinateV1 \
            or coordinate not in rehearsal_round_coordinates():
        raise BeliefV2RehearsalError(
            "V2 rehearsal policy coordinate drift")
    seeds = tuple(_derive_seed(
        f"champion-policy|round-{coordinate.round_seed}|seat-{seat}")
        for seat in range(4))
    if len(set(seeds)) != 4 or coordinate.round_seed in seeds:
        raise BeliefV2RehearsalError("V2 rehearsal policy seed collision")
    return seeds  # type: ignore[return-value]


def rehearsal_v2_policy_seeds(
        coordinate: V2RoundCoordinate) -> tuple[int, int, int, int]:
    if type(coordinate) is not V2RoundCoordinate:
        raise BeliefV2RehearsalError(
            "V2 rehearsal policy coordinate drift")
    row = rehearsal_v2_round_coordinate(
        coordinate.trump_rank, coordinate.rank_ordinal)
    if coordinate != row:
        raise BeliefV2RehearsalError(
            "V2 rehearsal policy coordinate drift")
    rehearsal = next(value for value in rehearsal_round_coordinates()
                     if value.round_seed == coordinate.round_seed)
    return rehearsal_policy_seeds(rehearsal)


def rehearsal_profile_dict() -> dict[str, Any]:
    rows = rehearsal_round_coordinates()
    return {
        "schema": REHEARSAL_SCHEMA,
        "smoke_only": True,
        "scientific_evidence": False,
        "seed_namespace": REHEARSAL_SEED_NAMESPACE,
        "synthetic_population": {
            "round_count": REHEARSAL_ROUND_COUNT,
            "trump_ranks": list(V2_RANKS),
            "rounds_per_rank": REHEARSAL_ROUNDS_PER_RANK,
            "capture_lanes": V2_CAPTURE_LANES,
            "split_schema": SPLIT_SCHEMA,
            "split_counts_by_rank": {
                rank: _rank_split_counts(rank) for rank in V2_RANKS},
            "split_counts": dict(REHEARSAL_SPLIT_COUNTS),
            "all_lanes_have_calibration_work": True,
        },
        "human_fixture_population": {
            "source_count": REHEARSAL_HUMAN_SOURCE_COUNT,
            "split_counts": dict(REHEARSAL_HUMAN_SPLIT_COUNTS),
            "private_human_data_opened": False,
        },
        "reference_world_count": V2_REFERENCE_WORLD_COUNT,
        "minimum_completed_epochs_per_cohort": (
            REHEARSAL_MINIMUM_COMPLETED_EPOCHS),
        "training_batch_decision_cap": REHEARSAL_TRAIN_BATCH_DECISION_CAP,
        "statistical_smoke_overrides": {
            "rank_calibration_minimum_rounds": 1,
            "reference_stability_is_observed_not_enforced": True,
        },
        "coordinate_sha256": hashlib.sha256(canonical_json_bytes([
            {
                "lane": row.lane,
                "rank_index": row.rank_index,
                "rank_ordinal": row.rank_ordinal,
                "round_seed": row.round_seed,
                "split": row.split,
                "trump_rank": row.trump_rank,
            } for row in rows])).hexdigest(),
        "retry_count": 0,
        "drop_count": 0,
        "authority": {
            "scientific_evidence": False,
            "sampler_implementation": False,
            "gameplay_screen": False,
            "strength_claim": False,
            "promotion": False,
            "deployment": False,
        },
    }


def rehearsal_profile_bytes() -> bytes:
    return canonical_json_bytes(rehearsal_profile_dict())


def rehearsal_profile_sha256() -> str:
    return hashlib.sha256(rehearsal_profile_bytes()).hexdigest()


def validate_rehearsal_receipt(value: dict[str, Any]) -> None:
    """Validate the non-scientific rehearsal receipt and its authority wall."""
    expected = {
        "schema", "smoke_only", "scientific_evidence", "profile_sha256",
        "freeze_sha256", "admission_sha256", "source_identity",
        "runtime_identity", "device_identity", "synthetic_round_count",
        "human_fixture_source_count", "reference_world_count",
        "cohort_epoch_counts", "stage_order", "progress", "artifact_count",
        "artifact_population_sha256", "terminal_manifest_sha256",
        "stability_observations", "development_resume_used",
        "production_freeze_review_eligible", "retry_count", "drop_count",
        "authority",
    }
    if type(value) is not dict or set(value) != expected \
            or value["schema"] != REHEARSAL_RECEIPT_SCHEMA \
            or value["smoke_only"] is not True \
            or value["scientific_evidence"] is not False \
            or value["profile_sha256"] != rehearsal_profile_sha256() \
            or value["synthetic_round_count"] != REHEARSAL_ROUND_COUNT \
            or value["human_fixture_source_count"] \
            != REHEARSAL_HUMAN_SOURCE_COUNT \
            or value["reference_world_count"] != V2_REFERENCE_WORLD_COUNT \
            or value["stage_order"] != list(REHEARSAL_STAGE_ORDER) \
            or type(value["development_resume_used"]) is not bool \
            or type(value["production_freeze_review_eligible"]) is not bool \
            or value["retry_count"] != 0 or value["drop_count"] != 0 \
            or value["authority"] != rehearsal_profile_dict()["authority"]:
        raise BeliefV2RehearsalError("V2 rehearsal receipt identity drift")
    sha_fields = (
        "freeze_sha256", "admission_sha256",
        "artifact_population_sha256", "terminal_manifest_sha256",
    )
    if any(not _is_hex(value[field], 64)
           for field in sha_fields):
        raise BeliefV2RehearsalError("V2 rehearsal receipt digest drift")
    source = value["source_identity"]
    runtime = value["runtime_identity"]
    device = value["device_identity"]
    progress = value["progress"]
    if type(source) is not dict or set(source) != {
            "execution_git", "checkout_clean", "source_manifest_sha256"} \
            or not _is_hex(source["execution_git"], 40) \
            or type(source["checkout_clean"]) is not bool \
            or (source["source_manifest_sha256"] is not None and (
                not _is_hex(source["source_manifest_sha256"], 64))) \
            or source["checkout_clean"] \
            != (source["source_manifest_sha256"] is not None):
        raise BeliefV2RehearsalError("V2 rehearsal source identity drift")
    if type(runtime) is not dict or set(runtime) != {
            "profile", "profile_sha256"} \
            or type(runtime["profile"]) is not dict \
            or not _is_hex(runtime["profile_sha256"], 64) \
            or hashlib.sha256(canonical_json_bytes(runtime["profile"])).hexdigest() \
            != runtime["profile_sha256"]:
        raise BeliefV2RehearsalError("V2 rehearsal runtime identity drift")
    if type(device) is not dict or set(device) != {
            "training_device", "qualification_plan_sha256",
            "qualification_result_sha256"} \
            or type(device["training_device"]) is not str \
            or any(not _is_hex(device[field], 64)
                   for field in (
                       "qualification_plan_sha256",
                       "qualification_result_sha256")):
        raise BeliefV2RehearsalError("V2 rehearsal device identity drift")
    epochs = value["cohort_epoch_counts"]
    if type(epochs) is not dict or len(epochs) != 4 \
            or any(type(count) is not int
                   or count < REHEARSAL_MINIMUM_COMPLETED_EPOCHS
                   for count in epochs.values()) \
            or type(value["artifact_count"]) is not int \
            or value["artifact_count"] <= 0 \
            or type(value["stability_observations"]) is not list:
        raise BeliefV2RehearsalError("V2 rehearsal evidence population drift")
    eligible = value["production_freeze_review_eligible"]
    _validate_receipt_progress(progress, eligible=eligible)
    if eligible and (value["development_resume_used"]
                     or not source["checkout_clean"]):
        raise BeliefV2RehearsalError(
            "V2 rehearsal production-review eligibility drift")
