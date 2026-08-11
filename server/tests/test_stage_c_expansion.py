from __future__ import annotations

import copy

import pytest

from shengji.rl import stage_c_expansion as EXP


ORIGINAL_SURFACES = {
    "DESIGN": {"play": 960, "bury": 64},
    "CALIB": {"play": 480, "bury": 32},
    "REPORT": {"play": 480, "bury": 32},
}


def _state(*, split: str, surface: str, index: int) -> dict:
    split_number = EXP.SPLIT_ORDER.index(split) + 1
    surface_number = EXP.SURFACES.index(surface) + 1
    return {
        "state_id": f"{split}:{surface}:{index:05d}",
        "seed": split_number * 10_000_000 + surface_number * 1_000_000
        + index,
        "split": split,
        "cell_id": f"{split}:{surface}:only-cell",
        "surface_type": surface,
        "selection_priority": f"{index:064x}",
    }


def _parents() -> tuple[dict, list[dict], list[dict], list[dict]]:
    cells = {
        split: [{
            "cell_id": f"{split}:{surface}:only-cell",
            "surface_type": surface,
            "quota": ORIGINAL_SURFACES[split][surface],
        } for surface in EXP.SURFACES]
        for split in EXP.SPLIT_ORDER
    }
    capture = {"schedule": {"quota_cells": cells}}
    retained = []
    original = []
    current_fresh = []
    for split in EXP.SPLIT_ORDER:
        for surface in EXP.SURFACES:
            original_count = ORIGINAL_SURFACES[split][surface]
            if split == "REPORT":
                retained_count = 3 * original_count
            else:
                retained_count = EXP.TARGET_SURFACES[split][surface]
            pool = [_state(
                split=split, surface=surface, index=index,
            ) for index in range(retained_count)]
            retained.extend(pool)
            original.extend(copy.deepcopy(pool[:original_count]))
            if split == "REPORT":
                current_fresh.extend(copy.deepcopy(
                    pool[original_count:2 * original_count]))
    return capture, retained, original, current_fresh


def test_weighted_capacity_allocation_is_proportional() -> None:
    cells = [
        {"cell_id": "a", "quota": 2},
        {"cell_id": "b", "quota": 1},
    ]
    assert EXP.weighted_capacity_allocation(
        cells, {"a": 99, "b": 99}, 12,
    ) == {"a": 8, "b": 4}


def test_weighted_capacity_allocation_redistributes_saturated_work() -> None:
    cells = [
        {"cell_id": "a", "quota": 2},
        {"cell_id": "b", "quota": 1},
    ]
    assert EXP.weighted_capacity_allocation(
        cells, {"a": 1, "b": 5}, 6,
    ) == {"a": 1, "b": 5}


def test_expanded_selection_reuses_training_and_seals_third_report() -> None:
    capture, retained, original, current_fresh = _parents()
    result = EXP.select_expanded_states(
        capture_packet=capture,
        retained_states=retained,
        original_states=original,
        current_fresh_report_states=current_fresh,
    )

    assert result["state_count"] == 7_552
    assert result["split_counts"] == {
        "DESIGN": 5_632, "CALIB": 1_408, "REPORT": 512}
    assert result["surface_counts"] == EXP.TARGET_SURFACES
    assert len(result["reused_training_state_ids"]) == 1_536
    assert len(result["new_label_state_ids"]) == 5_504
    assert len(result["sealed_report_state_ids"]) == 512
    assert result["original_state_overlap"] == 1_536
    assert result["current_fresh_report_overlap"] == 0
    assert result["labels_or_outcomes_opened"] is False
    assert result["report_labels_opened"] is False

    selected = {state["state_id"]: state for state in result["states"]}
    assert set(result["reused_training_state_ids"]) == {
        state["state_id"] for state in original
        if state["split"] in {"DESIGN", "CALIB"}}
    assert not (set(result["sealed_report_state_ids"]) & {
        state["state_id"] for state in current_fresh})
    assert all(selected[state_id]["split"] == "REPORT"
               for state_id in result["sealed_report_state_ids"])


def test_expanded_selection_refuses_outcome_material_or_short_supply() \
        -> None:
    capture, retained, original, current_fresh = _parents()
    leaked = copy.deepcopy(retained)
    leaked[-1]["signed_level_utility"] = 1.0
    with pytest.raises(EXP.ExpansionError, match="retained Stage-C state drift"):
        EXP.select_expanded_states(
            capture_packet=capture,
            retained_states=leaked,
            original_states=original,
            current_fresh_report_states=current_fresh,
        )

    short = retained[:-1]
    with pytest.raises(EXP.ExpansionError, match="supply underfilled"):
        EXP.select_expanded_states(
            capture_packet=capture,
            retained_states=short,
            original_states=original,
            current_fresh_report_states=current_fresh,
        )
