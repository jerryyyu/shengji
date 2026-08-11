"""Deterministic fresh-population scanner for the mid/late state screen.

Each deal seed is assigned to exactly one phase/role cell.  Candidate replay
and protected decision folds may decide whether the state is a valid trigger;
the independent evaluation fold remains unopened.  The scanner stops only
after 64 triggers in each of four cells or the predeclared finite seed supply
is exhausted.

This is population mechanics, not execution authority.  A controller must pin
the seed range, forbidden-deal manifest, actor/capture source and selector
artifacts before any scan can parent evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Callable, Mapping, Sequence

from . import stage_c_state_screen as SCREEN


SCHEMA = "teacher-stage-c-midlate-trigger-population-v1"
ENTRY_SCHEMA = "teacher-stage-c-midlate-trigger-entry-v1"


class StageCStateCaptureError(RuntimeError):
    """A seed assignment, candidate, selection or population drifted."""


Candidate = Callable[[int, str, str], tuple[Mapping[str, object] | None, str]]
Selector = Callable[[Mapping[str, object]], Mapping[str, object]]
Progress = Callable[[int, Mapping[str, int]], None]


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return hashlib.sha256(_canonical_json({
        key: item for key, item in value.items() if key != field
    })).hexdigest()


def assigned_cell(offset: int) -> tuple[str, str]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise StageCStateCaptureError("capture seed offset drift")
    cell = SCREEN.CELL_KEYS[offset % len(SCREEN.CELL_KEYS)]
    phase, role = cell.split(":", 1)
    return phase, role


def _validate_entry(entry: Mapping[str, object]) -> None:
    state = entry.get("state")
    selection = entry.get("selection")
    if (entry.get("schema") != ENTRY_SCHEMA
            or entry.get("entry_sha256") != _self_hash(entry, "entry_sha256")
            or not isinstance(state, Mapping)
            or not isinstance(selection, Mapping)
            or entry.get("evaluation_opened") is not False):
        raise StageCStateCaptureError("capture entry identity drift")
    try:
        SCREEN._state_identity(state)
        SCREEN._validate_selection(selection)
    except SCREEN.StageCStateScreenError as exc:
        raise StageCStateCaptureError(
            f"capture entry screen contract drift: {exc}") from exc
    if (selection.get("state_id") != state.get("state_id")
            or selection.get("deal_seed") != state.get("seed")
            or selection.get("seat") != state.get("seat")
            or selection.get("trick") != state.get("trick")
            or selection.get("phase") != state.get("phase")
            or selection.get("role") != state.get("role")):
        raise StageCStateCaptureError("capture entry state/selection drift")


def scan_population(
    *, seed0: int, scan_deals: int, forbidden_deal_seeds: Sequence[int],
    candidate: Candidate, selector: Selector,
    progress: Progress | None = None,
) -> dict:
    """Scan a finite deal range and freeze decision-only trigger entries."""
    if (isinstance(seed0, bool) or not isinstance(seed0, int) or seed0 < 0
            or isinstance(scan_deals, bool) or not isinstance(scan_deals, int)
            or scan_deals < SCREEN.TARGET_STATES
            or not isinstance(forbidden_deal_seeds, (list, tuple))
            or any(isinstance(seed, bool) or not isinstance(seed, int)
                   for seed in forbidden_deal_seeds)
            or not callable(candidate) or not callable(selector)
            or (progress is not None and not callable(progress))):
        raise StageCStateCaptureError("capture population input drift")
    forbidden = set(forbidden_deal_seeds)
    entries = []
    counts: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    scanned = 0
    selection_attempts = 0
    for offset in range(scan_deals):
        if all(counts[cell] == SCREEN.TARGET_PER_CELL
               for cell in SCREEN.CELL_KEYS):
            break
        seed = seed0 + offset
        phase, role = assigned_cell(offset)
        cell = f"{phase}:{role}"
        scanned += 1
        if counts[cell] >= SCREEN.TARGET_PER_CELL:
            dispositions[f"{cell}:quota_full"] += 1
            continue
        if seed in forbidden:
            dispositions[f"{cell}:forbidden_deal"] += 1
            continue
        state, reason = candidate(seed, phase, role)
        if state is None:
            if not isinstance(reason, str) or not reason:
                raise StageCStateCaptureError(
                    "candidate refusal lacks a disposition")
            dispositions[f"{cell}:{reason}"] += 1
            continue
        if (state.get("seed") != seed or state.get("phase") != phase
                or state.get("role") != role):
            raise StageCStateCaptureError(
                "candidate differs from assigned deal/cell")
        try:
            selection_attempts += 1
            selection = selector(state)
        except SCREEN.StageCStateIneligible as exc:
            dispositions[f"{cell}:not_triggered:{exc}"] += 1
            continue
        except SCREEN.StageCStateScreenError as exc:
            raise StageCStateCaptureError(
                f"protected selection failed: {exc}") from exc
        entry = {
            "schema": ENTRY_SCHEMA,
            "state": copy.deepcopy(state),
            "selection": copy.deepcopy(selection),
            "evaluation_opened": False,
        }
        entry["entry_sha256"] = _self_hash(entry, "entry_sha256")
        _validate_entry(entry)
        entries.append(entry)
        counts[cell] += 1
        dispositions[f"{cell}:selected"] += 1
        if progress is not None:
            progress(scanned, {key: counts[key] for key in SCREEN.CELL_KEYS})

    complete = (len(entries) == SCREEN.TARGET_STATES
                and all(counts[cell] == SCREEN.TARGET_PER_CELL
                        for cell in SCREEN.CELL_KEYS))
    state_ids = [entry["state"]["state_id"] for entry in entries]
    deal_seeds = [entry["state"]["seed"] for entry in entries]
    position_counts = Counter(
        str(entry["selection"]["position"]) for entry in entries)
    if (len(state_ids) != len(set(state_ids))
            or len(deal_seeds) != len(set(deal_seeds))
            or set(deal_seeds) & forbidden):
        raise StageCStateCaptureError(
            "captured trigger population is not fresh/unique")
    result = {
        "schema": SCHEMA,
        "seed0": seed0,
        "scan_deals": scan_deals,
        "deals_scanned": scanned,
        "target_states": SCREEN.TARGET_STATES,
        "target_per_cell": SCREEN.TARGET_PER_CELL,
        "selected_states": len(entries),
        "cell_counts": {cell: counts[cell] for cell in SCREEN.CELL_KEYS},
        "position_counts": {
            position: position_counts[position]
            for position in ("lead", "follow")
        },
        "dispositions": dict(sorted(dispositions.items())),
        "forbidden_deal_count": len(forbidden),
        "forbidden_deal_overlap": 0,
        "one_state_per_deal": True,
        "selection_states_attempted": selection_attempts,
        "evaluation_folds_opened": 0,
        "entries": entries,
        "complete": complete,
        "decision": (
            "READY_FOR_EVALUATION_REVIEW" if complete
            else "INSUFFICIENT_TRIGGER_SUPPLY"),
        "evaluation_launch_authorized": False,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["population_sha256"] = _self_hash(result, "population_sha256")
    return result


def validate_population(value: Mapping[str, object], *,
                        forbidden_deal_seeds: Sequence[int]) -> None:
    entries = value.get("entries")
    seed0 = value.get("seed0")
    scan_deals = value.get("scan_deals")
    deals_scanned = value.get("deals_scanned")
    selection_attempts = value.get("selection_states_attempted")
    dispositions = value.get("dispositions")
    if (value.get("schema") != SCHEMA
            or value.get("population_sha256")
            != _self_hash(value, "population_sha256")
            or not isinstance(entries, list)
            or value.get("target_states") != SCREEN.TARGET_STATES
            or value.get("target_per_cell") != SCREEN.TARGET_PER_CELL
            or isinstance(seed0, bool) or not isinstance(seed0, int)
            or seed0 < 0
            or isinstance(scan_deals, bool) or not isinstance(scan_deals, int)
            or scan_deals < SCREEN.TARGET_STATES
            or isinstance(deals_scanned, bool)
            or not isinstance(deals_scanned, int)
            or not 0 <= deals_scanned <= scan_deals
            or isinstance(selection_attempts, bool)
            or not isinstance(selection_attempts, int)
            or not 0 <= selection_attempts <= deals_scanned
            or not isinstance(dispositions, dict)
            or any(not isinstance(key, str) or not key
                   or isinstance(count, bool) or not isinstance(count, int)
                   or count <= 0
                   for key, count in dispositions.items())
            or value.get("evaluation_folds_opened") != 0
            or value.get("evaluation_launch_authorized") is not False
            or value.get("whole_game_launch_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False):
        raise StageCStateCaptureError("capture population identity drift")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise StageCStateCaptureError("capture population entry drift")
        _validate_entry(entry)
    seeds = [entry["state"]["seed"] for entry in entries]
    ids = [entry["state"]["state_id"] for entry in entries]
    counts = Counter(entry["selection"]["cell"] for entry in entries)
    positions = Counter(
        entry["selection"]["position"] for entry in entries)
    forbidden = set(forbidden_deal_seeds)
    complete = len(entries) == SCREEN.TARGET_STATES
    selected_dispositions = sum(
        count for key, count in dispositions.items()
        if key.endswith(":selected"))
    ineligible_dispositions = sum(
        count for key, count in dispositions.items()
        if ":not_triggered:" in key)
    valid_prefixes = tuple(f"{cell}:" for cell in SCREEN.CELL_KEYS)
    if (len(seeds) != len(set(seeds)) or len(ids) != len(set(ids))
            or set(seeds) & forbidden
            or seeds != sorted(seeds)
            or any(not seed0 <= seed < seed0 + deals_scanned
                   for seed in seeds)
            or any(entry["selection"]["cell"] != ":".join(
                assigned_cell(entry["state"]["seed"] - seed0))
                   for entry in entries)
            or any(not key.startswith(valid_prefixes)
                   for key in dispositions)
            or sum(dispositions.values()) != deals_scanned
            or selected_dispositions != len(entries)
            or selected_dispositions + ineligible_dispositions
            != selection_attempts
            or value.get("forbidden_deal_count") != len(forbidden)
            or value.get("forbidden_deal_overlap") != 0
            or value.get("one_state_per_deal") is not True
            or value.get("selected_states") != len(entries)
            or selection_attempts < len(entries)
            or value.get("cell_counts")
            != {cell: counts[cell] for cell in SCREEN.CELL_KEYS}
            or value.get("position_counts") != {
                position: positions[position]
                for position in ("lead", "follow")}
            or value.get("complete") is not complete
            or (not complete and deals_scanned != scan_deals)
            or value.get("decision") != (
                "READY_FOR_EVALUATION_REVIEW" if complete
                else "INSUFFICIENT_TRIGGER_SUPPLY")):
        raise StageCStateCaptureError(
            "capture population freshness/quota drift")
    if complete and any(counts[cell] != SCREEN.TARGET_PER_CELL
                        for cell in SCREEN.CELL_KEYS):
        raise StageCStateCaptureError("complete capture cell quota drift")
