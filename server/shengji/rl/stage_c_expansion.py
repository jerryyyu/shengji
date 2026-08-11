"""Deterministic selection for the first larger Stage-C Teacher dataset.

The original capture retained substantially more score-free states than the
2,048-state first tranche.  This module turns those retained reservoirs into a
larger learning-curve asset without dealing new games or touching a label:

* DESIGN grows to 5,632 states (5,120 play / 512 bury);
* CALIB grows to 1,408 states (1,280 play / 128 bury); and
* REPORT is a third untouched 512-state tranche (480 play / 32 bury), disjoint
  from both the original and already-spent replacement REPORT populations.

Cell allocations preserve the original quota weights.  Scarce cells saturate
and their residual allocation is deterministically redistributed across cells
with remaining supply.  The selected DESIGN/CALIB set contains every original
training row, so its reviewed labels can be reused; only the 5,504 new
DESIGN/CALIB rows require Teacher work.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from typing import Mapping, Sequence


SCHEMA = "teacher-stage-c-expanded-state-selection-v1"
SPLIT_ORDER = ("DESIGN", "CALIB", "REPORT")
SURFACES = ("play", "bury")
TARGET_SURFACES = {
    "DESIGN": {"play": 5_120, "bury": 512},
    "CALIB": {"play": 1_280, "bury": 128},
    "REPORT": {"play": 480, "bury": 32},
}
TARGET_SPLITS = {
    split: sum(surfaces.values())
    for split, surfaces in TARGET_SURFACES.items()
}
TARGET_STATES = sum(TARGET_SPLITS.values())
REUSED_TRAINING_STATES = 1_536
NEW_LABEL_STATES = (
    TARGET_SPLITS["DESIGN"] + TARGET_SPLITS["CALIB"]
    - REUSED_TRAINING_STATES
)
SEALED_REPORT_STATES = TARGET_SPLITS["REPORT"]


class ExpansionError(RuntimeError):
    """A retained reservoir or expanded split contract drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def manifest_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _forbidden_label_material(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"label_action", "raw_attacker_points",
                       "signed_level_utility", "row_sha256"}:
                return True
            if _forbidden_label_material(child):
                return True
    elif isinstance(value, list):
        return any(_forbidden_label_material(child) for child in value)
    return False


def weighted_capacity_allocation(
    cells: Sequence[Mapping[str, object]], capacities: Mapping[str, int],
    target: int,
) -> dict[str, int]:
    """Allocate an integer target proportionally, saturating scarce cells."""
    if isinstance(target, bool) or not isinstance(target, int) or target < 0:
        raise ExpansionError("expanded allocation target drift")
    weights = {}
    for cell in cells:
        cell_id = str(cell.get("cell_id"))
        weight = cell.get("quota")
        capacity = capacities.get(cell_id)
        if (not cell_id or cell_id in weights or isinstance(weight, bool)
                or not isinstance(weight, int) or weight <= 0
                or isinstance(capacity, bool) or not isinstance(capacity, int)
                or capacity < 0):
            raise ExpansionError("expanded allocation cell/capacity drift")
        weights[cell_id] = weight
    if sum(capacities[cell_id] for cell_id in weights) < target:
        raise ExpansionError("expanded allocation supply underfilled")
    allocated = {cell_id: 0 for cell_id in weights}
    for _ in range(target):
        available = [cell_id for cell_id in weights
                     if allocated[cell_id] < capacities[cell_id]]
        if not available:
            raise ExpansionError("expanded allocation exhausted early")
        selected = min(
            available,
            key=lambda cell_id: (
                Fraction(allocated[cell_id], weights[cell_id]), cell_id),
        )
        allocated[selected] += 1
    if sum(allocated.values()) != target:
        raise ExpansionError("expanded allocation total drift")
    return allocated


def _state_identity(state: Mapping[str, object]) -> tuple[str, int]:
    state_id = state.get("state_id")
    seed = state.get("seed")
    if (not isinstance(state_id, str) or not state_id
            or isinstance(seed, bool) or not isinstance(seed, int)):
        raise ExpansionError("expanded state identity drift")
    return state_id, seed


def _selection_identity(state: Mapping[str, object]) -> tuple[str, int]:
    state_id, seed = _state_identity(state)
    priority = state.get("selection_priority")
    split = state.get("split")
    cell_id = state.get("cell_id")
    surface = state.get("surface_type")
    if (not isinstance(priority, str) or not priority
            or split not in SPLIT_ORDER or not isinstance(cell_id, str)
            or not cell_id or surface not in SURFACES):
        raise ExpansionError("expanded state selection identity drift")
    return state_id, seed


def select_expanded_states(
    *, capture_packet: Mapping[str, object],
    retained_states: Sequence[Mapping[str, object]],
    original_states: Sequence[Mapping[str, object]],
    current_fresh_report_states: Sequence[Mapping[str, object]],
) -> dict:
    """Select the larger DESIGN/CALIB set and a third sealed REPORT tranche."""
    cells_by_split = capture_packet.get("schedule", {}).get("quota_cells")
    if (not isinstance(cells_by_split, dict)
            or set(cells_by_split) != set(SPLIT_ORDER)):
        raise ExpansionError("expanded capture quota cells missing")
    original_ids = set()
    original_seeds = set()
    original_training_ids = set()
    for state in original_states:
        state_id, seed = _selection_identity(state)
        if (state_id in original_ids or seed in original_seeds
                or _forbidden_label_material(state)):
            raise ExpansionError("original Stage-C identity collision")
        original_ids.add(state_id)
        original_seeds.add(seed)
        if state.get("split") in {"DESIGN", "CALIB"}:
            original_training_ids.add(state_id)
    if (len(original_ids) != 2_048
            or len(original_training_ids) != REUSED_TRAINING_STATES):
        raise ExpansionError("original Stage-C population drift")

    fresh_ids = set()
    fresh_seeds = set()
    for state in current_fresh_report_states:
        state_id, seed = _selection_identity(state)
        if (state.get("split") != "REPORT" or state_id in fresh_ids
                or seed in fresh_seeds or state_id in original_ids
                or seed in original_seeds
                or _forbidden_label_material(state)):
            raise ExpansionError("current fresh REPORT identity drift")
        fresh_ids.add(state_id)
        fresh_seeds.add(seed)
    if len(fresh_ids) != 512:
        raise ExpansionError("current fresh REPORT population drift")

    pools: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    retained_ids = set()
    retained_seeds = set()
    for state in retained_states:
        state_id, seed = _selection_identity(state)
        split = state.get("split")
        cell_id = state.get("cell_id")
        if (state_id in retained_ids or seed in retained_seeds
                or _forbidden_label_material(state)):
            raise ExpansionError("retained Stage-C state drift")
        retained_ids.add(state_id)
        retained_seeds.add(seed)
        pools[(str(split), cell_id)].append(state)
    for pool in pools.values():
        pool.sort(key=lambda state: (
            state["selection_priority"], state["state_id"]))

    selected = []
    cell_manifest = []
    for split in SPLIT_ORDER:
        raw_cells = cells_by_split[split]
        if not isinstance(raw_cells, list):
            raise ExpansionError("expanded split cell list drift")
        cells = {str(cell.get("cell_id")): cell for cell in raw_cells}
        if len(cells) != len(raw_cells):
            raise ExpansionError("expanded cell identity collision")
        for surface in SURFACES:
            surface_cells = [cell for cell in raw_cells
                             if cell.get("surface_type") == surface]
            eligible_pools = {}
            capacities = {}
            for cell in surface_cells:
                cell_id = str(cell["cell_id"])
                pool = pools.get((split, cell_id), [])
                if split == "REPORT":
                    pool = [state for state in pool
                            if str(state["state_id"])
                            not in original_ids | fresh_ids
                            and int(state["seed"])
                            not in original_seeds | fresh_seeds]
                eligible_pools[cell_id] = pool
                capacities[cell_id] = len(pool)
            allocation = weighted_capacity_allocation(
                surface_cells, capacities, TARGET_SURFACES[split][surface])
            for cell in sorted(surface_cells,
                               key=lambda value: str(value["cell_id"])):
                cell_id = str(cell["cell_id"])
                count = allocation[cell_id]
                pool = eligible_pools[cell_id]
                chosen = pool[:count]
                for rank, state in enumerate(chosen, 1):
                    value = copy.deepcopy(state)
                    value["expansion_selection"] = {
                        "schema": SCHEMA,
                        "base_quota": int(cell["quota"]),
                        "cell_capacity_after_exclusions": len(pool),
                        "expanded_cell_allocation": count,
                        "rank": rank,
                        "selection_uses_labels_or_outcomes": False,
                    }
                    selected.append(value)
                cell_manifest.append({
                    "split": split,
                    "surface_type": surface,
                    "cell_id": cell_id,
                    "base_quota": int(cell["quota"]),
                    "retained_supply": len(pools.get((split, cell_id), [])),
                    "eligible_supply_after_exclusions": len(pool),
                    "allocation": count,
                    "selected_state_ids_sha256": manifest_hash(
                        [state["state_id"] for state in chosen]),
                })

    selected.sort(key=lambda state: (
        SPLIT_ORDER.index(str(state["split"])), str(state["cell_id"]),
        state["selection_priority"], state["state_id"]))
    selected_ids = [str(state["state_id"]) for state in selected]
    selected_seeds = [int(state["seed"]) for state in selected]
    split_counts = Counter(str(state["split"]) for state in selected)
    surface_counts = Counter(
        (str(state["split"]), str(state["surface_type"]))
        for state in selected)
    selected_training_ids = {
        str(state["state_id"]) for state in selected
        if state["split"] in {"DESIGN", "CALIB"}}
    report_ids = {str(state["state_id"]) for state in selected
                  if state["split"] == "REPORT"}
    report_seeds = {int(state["seed"]) for state in selected
                    if state["split"] == "REPORT"}
    original_overlap = set(selected_ids) & original_ids
    if (len(selected) != TARGET_STATES
            or len(set(selected_ids)) != TARGET_STATES
            or len(set(selected_seeds)) != TARGET_STATES
            or dict(split_counts) != TARGET_SPLITS
            or any(surface_counts[(split, surface)]
                   != TARGET_SURFACES[split][surface]
                   for split in SPLIT_ORDER for surface in SURFACES)
            or not original_training_ids.issubset(selected_training_ids)
            or len(selected_training_ids - original_training_ids)
            != NEW_LABEL_STATES
            or original_overlap != original_training_ids
            or report_ids & (original_ids | fresh_ids)
            or report_seeds & (original_seeds | fresh_seeds)
            or _forbidden_label_material(selected)):
        raise ExpansionError("expanded selected population contract drift")

    new_label_ids = sorted(selected_training_ids - original_training_ids)
    reused_ids = sorted(original_training_ids)
    sealed_report_ids = sorted(report_ids)
    result = {
        "schema": SCHEMA,
        "selection_rule": (
            "within each split/surface, allocate the frozen target in "
            "proportion to original quota weights; saturate scarce cells and "
            "deterministically redistribute residual work; within each cell "
            "take the first (selection_priority,state_id) rows, excluding "
            "both earlier REPORT tranches from the third REPORT"
        ),
        "states": selected,
        "states_sha256": manifest_hash(selected),
        "state_count": len(selected),
        "split_counts": dict(split_counts),
        "surface_counts": {
            split: {surface: surface_counts[(split, surface)]
                    for surface in SURFACES}
            for split in SPLIT_ORDER
        },
        "cell_manifest": cell_manifest,
        "cell_manifest_sha256": manifest_hash(cell_manifest),
        "reused_training_state_ids": reused_ids,
        "reused_training_state_ids_sha256": manifest_hash(reused_ids),
        "new_label_state_ids": new_label_ids,
        "new_label_state_ids_sha256": manifest_hash(new_label_ids),
        "sealed_report_state_ids": sealed_report_ids,
        "sealed_report_state_ids_sha256": manifest_hash(sealed_report_ids),
        "original_state_overlap": len(original_overlap),
        "current_fresh_report_overlap": len(report_ids & fresh_ids),
        "labels_or_outcomes_opened": False,
        "report_labels_opened": False,
    }
    result["selection_sha256"] = manifest_hash(result)
    return result
