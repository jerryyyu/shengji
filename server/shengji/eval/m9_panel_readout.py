"""Descriptive internal-consistency readout for a completed M9 panel.

This module consumes already-read synthetic/retained records only.  It does
not authenticate files, worlds, models, runtime seals, or fixture provenance,
and makes no served-choice or strategy claim.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .ballot_matrix import CARD_INDEX, _canonical_collection
from .ballot_full_pool import summarize_full_pool_matrix
from .ballot_points_selection import summarize_points_selection
from .m9_panel_plan import build_m9_panel_plan
from .m9_panel_worker import _validate_panel
from .m9_replay_binding import validate_m9_replay


_ARMS = ("control", "treatment")
_CAPTURE_SCHEMA = "fixed-tape-same-leaf-capture-v1"
_FRESH_SCHEMA = "fixed-tape-three-pass-panel-v1"
_PRIMED_SCHEMA = "fixed-tape-history-primed-panel-v1"


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a strict integer")
    return value


def _same(left: Any, right: Any) -> bool:
    """Recursive equality that never treats bool as an integer."""
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return (set(left) == set(right)
                and all(_same(left[key], right[key]) for key in left))
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right))
    return left == right


def _finite(value: Any, label: str) -> None:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite plain number")
    try:
        valid = math.isfinite(value)
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a finite plain number")


def _matrix(value: Any, rows: int, columns: int, label: str) -> list[list[Any]]:
    if type(value) is not list or len(value) != rows:
        raise ValueError(f"{label} must have {rows} rows")
    result = []
    for row_index, row in enumerate(value):
        if type(row) is not list or len(row) != columns:
            raise ValueError(f"{label}[{row_index}] has wrong column count")
        for column, number in enumerate(row):
            _finite(number, f"{label}[{row_index}][{column}]")
        result.append(row)
    return result


def _points(value: Any, rows: int, columns: int, label: str) -> list[list[int]]:
    if type(value) is not list or len(value) != rows:
        raise ValueError(f"{label} must have {rows} rows")
    for row_index, row in enumerate(value):
        if type(row) is not list or len(row) != columns:
            raise ValueError(f"{label}[{row_index}] has wrong column count")
        for column, number in enumerate(row):
            if type(number) is not int:
                raise ValueError(f"{label}[{row_index}][{column}] must be an int")
    return value


def _capture(capture: Any, actions: list[list[str]], label: str) -> dict[str, Any]:
    c = _object(capture, label)
    if c.get("schema") != _CAPTURE_SCHEMA:
        raise ValueError(f"{label} schema mismatch")
    if c.get("actions") != actions:
        raise ValueError(f"{label}.actions differ from planned order")
    if _strict_int(c.get("world_count"), f"{label}.world_count") != 64:
        raise ValueError(f"{label}.world_count must be 64")
    count = len(actions)
    matrix = _matrix(c.get("value_matrix"), 64, count,
                     f"{label}.value_matrix")
    points = _points(c.get("signed_trick_points"), 64, count,
                     f"{label}.signed_trick_points")
    means = c.get("serving_value_means")
    if type(means) is not list or len(means) != count:
        raise ValueError(f"{label}.serving_value_means has wrong length")
    for index, number in enumerate(means):
        _finite(number, f"{label}.serving_value_means[{index}]")
        try:
            total = 0.0
            for row in matrix:
                total += row[index]
            expected = total / 64
        except (OverflowError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"{label} sequential mean overflow") from exc
        _finite(expected, f"{label}.sequential_mean[{index}]")
        if number != expected:
            raise ValueError(f"{label}.serving_value_means drifted")
    return {"object": c, "matrix": matrix, "points": points,
            "means": means}


def _capture_batches(capture: Mapping[str, Any], count: int,
                     batch_size: int, label: str) -> None:
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("panel effective.batch_size must be positive")
    batches = _strict_int(capture.get("batches"), f"{label}.batches")
    expected = (64 * count + batch_size - 1) // batch_size
    if batches < 1 or batches != expected:
        raise ValueError(f"{label}.batches differs from expected count")


def _same_points(full: list[list[int]], ballot: list[list[int]],
                 indices: list[int], label: str) -> None:
    if len(ballot) != 64:
        raise ValueError(f"{label} point rows differ")
    for world, row in enumerate(ballot):
        if row != [full[world][index] for index in indices]:
            raise ValueError(f"{label} signed trick points differ")


def _read_panel(record: Mapping[str, Any], job: Mapping[str, Any],
                saved_analysis: Any) -> tuple[dict[str, Any], dict[str, list[float]] | None,
                                               dict[str, Any] | None]:
    panel = _validate_panel(record.get("panel"), job)
    tape = _object(panel.get("tape_receipt"), "panel.tape_receipt")
    if tape.get("schema") != "public-refusal-tape-v1":
        raise ValueError("panel tape receipt schema mismatch")
    if tape.get("mode") != job["mode"]:
        raise ValueError("panel tape receipt mode mismatch")
    if _strict_int(tape.get("seed"), "panel.tape_receipt.seed") != job["seed"]:
        raise ValueError("panel tape receipt seed mismatch")
    if _strict_int(tape.get("fill_seed"),
                   "panel.tape_receipt.fill_seed") != job["fill_seed"]:
        raise ValueError("panel tape receipt fill_seed mismatch")
    if _strict_int(tape.get("world_count"),
                   "panel.tape_receipt.world_count") != 64:
        raise ValueError("panel tape receipt world_count mismatch")
    if tape.get("checkpoint_sha256") != job["checkpoint_sha256"]:
        raise ValueError("panel tape receipt checkpoint mismatch")
    ledger = _object(tape.get("ledger_receipt"), "panel.tape_receipt.ledger_receipt")
    if ledger.get("mode") != job["mode"]:
        raise ValueError("panel ledger receipt mode mismatch")
    actions = panel.get("actions")
    canonical_actions = _canonical_collection(actions, "panel.actions")
    if len(canonical_actions) != job["expected_legal_count"]:
        raise ValueError("panel action pool count differs from planned legal count")
    if type(actions) is not list:
        raise ValueError("panel.actions must be a list")
    effective = _object(panel.get("effective"), "panel.effective")
    batch_size = _strict_int(effective.get("batch_size"),
                             "panel.effective.batch_size")
    if batch_size < 1:
        raise ValueError("panel effective.batch_size must be positive")
    worlds = panel.get("worlds")
    if type(worlds) is not list or len(worlds) != 64:
        raise ValueError("panel.worlds must contain exactly 64 worlds")
    for world in worlds:
        if type(world) not in (list, tuple) or len(world) != 2:
            raise ValueError("world must contain hands and buried cards")
        hands, buried = world
        if type(hands) is not list or len(hands) != 4:
            raise ValueError("world must contain four hands")
        for cards in [*hands, buried]:
            if type(cards) is not list or any(type(card) is not str or card not in CARD_INDEX
                                               for card in cards):
                raise ValueError("world cards must be known card strings")
    collection = _object(panel.get("collection"), "panel.collection")
    full_actions = actions
    full_capture_obj = None
    deltas = None
    replay = None
    if job["mode"] == "fresh-root":
        if collection.get("schema") != _FRESH_SCHEMA:
            raise ValueError("fresh panel collection schema mismatch")
        captures = _object(collection.get("captures"), "panel.collection.captures")
        if set(captures) != {"full_pool", "control", "treatment"}:
            raise ValueError("fresh collection captures are incomplete")
        full = _capture(captures["full_pool"], full_actions,
                        "full_pool capture")
        _capture_batches(full["object"], len(full_actions), batch_size,
                         "full_pool capture")
        ballot_info = {}
        full_canonical = _canonical_collection(full_actions, "panel.actions")
        indices_by_action = {action: index
                             for index, action in enumerate(full_canonical)}
        for arm in _ARMS:
            ballot_actions = job[f"{arm}_ballot"]
            ballot = _capture(captures[arm], ballot_actions,
                              f"{arm} capture")
            _capture_batches(ballot["object"], len(ballot_actions), batch_size,
                             f"{arm} capture")
            ballot_canonical = _canonical_collection(ballot_actions,
                                                     f"{arm} ballot")
            try:
                indices = [indices_by_action[action] for action in ballot_canonical]
            except KeyError as exc:
                raise ValueError(f"{arm} ballot action absent from full pool") from exc
            _same_points(full["points"], ballot["points"], indices,
                         f"{arm} capture")
            ballot_info[arm] = indices
        # Initialize after validating arm captures so the assignment above is
        # unambiguous and preserves the two independent ballot columns.
        deltas = {}
        ballot_replays = {}
        shared_replays = {}
        for arm in _ARMS:
            indices = ballot_info[arm]
            ballot = _object(captures[arm], f"{arm} capture")
            means = ballot["serving_value_means"]
            arm_deltas = []
            for i, j in enumerate(indices):
                try:
                    delta = means[i] - full["means"][j]
                except (OverflowError, ValueError) as exc:
                    raise ValueError(f"{arm} schedule delta overflow") from exc
                _finite(delta, f"{arm} schedule delta")
                arm_deltas.append(delta)
            deltas[arm] = arm_deltas
            ballot_replays[arm] = summarize_points_selection(
                job[f"{arm}_ballot"], means, ballot["signed_trick_points"])
            shared_replays[arm] = summarize_points_selection(
                job[f"{arm}_ballot"], [full["means"][j] for j in indices],
                [[row[j] for j in indices] for row in full["points"]])
        for field, expected in (
            ("ballot_schedule_points_replay", ballot_replays),
            ("shared_matrix_points_replay", shared_replays),
            ("ballot_minus_full_schedule_value_deltas", deltas),
        ):
            if not _same(collection.get(field), expected):
                raise ValueError(f"cached {field} differs")
        full_capture_obj = full
        replay = validate_m9_replay(panel, saved_analysis)
        if not _same(record.get("replay_consistency"), replay):
            raise ValueError("recorded replay consistency differs")
    else:
        if collection.get("schema") != _PRIMED_SCHEMA:
            raise ValueError("primed panel collection schema mismatch")
        if collection.get("union_is_projection") is not True:
            raise ValueError("primed union projection flag is required")
        if collection.get("saved_ballots_generated_under_this_sampler") is not False:
            raise ValueError("primed sampler ballot flag must be false")
        if record.get("replay_consistency") is not None:
            raise ValueError("primed records cannot carry replay consistency")
        full_capture_obj = _capture(collection.get("full_pool_capture"),
                                    full_actions, "full_pool capture")
        _capture_batches(full_capture_obj["object"], len(full_actions),
                         batch_size, "full_pool capture")
    recomputed = summarize_full_pool_matrix(
        full_actions, job["control_ballot"], job["treatment_ballot"],
        full_capture_obj["matrix"])
    if not _same(recomputed, collection.get("shared_matrix_summary")):
        raise ValueError("cached shared matrix summary differs")
    return recomputed, deltas, replay


def summarize_m9_panels(saved_analysis, records) -> dict[str, Any]:
    """Return a descriptive readout after strict panel internal checks."""
    plan = build_m9_panel_plan(saved_analysis)
    if type(records) is not list or len(records) != len(plan):
        raise ValueError("exactly 15 panel records are required")
    rows = []
    for index, (record_value, job) in enumerate(zip(records, plan)):
        record = _object(record_value, f"records[{index}]")
        if not _same(record.get("job"), job):
            raise ValueError(f"records[{index}] job differs or is out of order")
        if record.get("validation_status") != "passed":
            raise ValueError("all panel records must have passed validation")
        if "replay_failure" not in record:
            raise ValueError("record must explicitly contain replay_failure")
        if record["replay_failure"] is not None:
            raise ValueError("rejected replay record cannot be read out")
        expected_cadence = ("fresh-root" if job["mode"] == "fresh-root"
                            else "single-seat-actor-turns")
        if record.get("ledger_cadence") != expected_cadence:
            raise ValueError("panel ledger cadence differs from job mode")
        full_summary, deltas, _replay = _read_panel(record, job, saved_analysis)
        rows.append({
            "fixture_id": job["fixture_id"],
            "mode": job["mode"],
            "seed": job["seed"],
            "role": job["role"],
            "ledger_cadence": expected_cadence,
            "full_pool_summary": full_summary,
            "ballot_minus_full_schedule_value_deltas": deltas,
            "replay_consistency": _replay,
        })
    return {
        "schema": "m9-panel-readout-v1",
        "rows": rows,
        "panel_count": len(rows),
        "provenance_verified": False,
        "strategic_quality_assessed": False,
        "causal_mechanism_assessed": False,
    }


__all__ = ["summarize_m9_panels"]
