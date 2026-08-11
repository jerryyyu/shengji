from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import teacher_stage_c_expanded_play_capability as CTRL


def _candidate() -> dict:
    return {
        **CTRL.EXPECTED_CAPABILITY,
        "eligible": True,
        "outcome_calibration_required": False,
    }


def test_play_capability_is_independent_eligible_candidate() -> None:
    aggregate = {"selection": {"candidates": [_candidate()]}}
    assert CTRL._play_capability(aggregate) == CTRL.EXPECTED_CAPABILITY

    changed = copy.deepcopy(aggregate)
    changed["selection"]["candidates"][0][
        "action_improvement_positive_seeds"] = 7
    with pytest.raises(
            CTRL.ExpandedPlayCapabilityRefused,
            match="not independently eligible"):
        CTRL._play_capability(changed)


def test_bury_terminal_review_must_match_exact_select_none(tmp_path: Path) \
        -> None:
    review = tmp_path / "review.md"
    review.write_text(
        CTRL.BURY_RESULT_REVIEW_MARKER
        + json.dumps(CTRL.EXPECTED_BURY_RESULT_REVIEW, sort_keys=True,
                     separators=(",", ":")) + "\n")
    assert CTRL._bury_result_review(review) \
        == CTRL.EXPECTED_BURY_RESULT_REVIEW

    changed = copy.deepcopy(CTRL.EXPECTED_BURY_RESULT_REVIEW)
    changed["decision"] = "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW"
    review.write_text(
        CTRL.BURY_RESULT_REVIEW_MARKER
        + json.dumps(changed, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(
            CTRL.ExpandedPlayCapabilityRefused,
            match="terminal review drift"):
        CTRL._bury_result_review(review)


def test_selection_summary_never_publishes_state_material() -> None:
    selection = {
        "schema": CTRL.EXP.PLAY_SUCCESSOR_REPORT_SCHEMA,
        "selection_rule": "frozen",
        "selection_sha256": "1" * 64,
        "states_sha256": "2" * 64,
        "state_ids_sha256": "3" * 64,
        "state_count": 480,
        "surface_counts": {"play": 480},
        "cell_manifest": [],
        "cell_manifest_sha256": "4" * 64,
        "spent_report_populations": 4,
        "spent_report_states": 2_048,
        "spent_report_state_ids_sha256": "5" * 64,
        "spent_report_deal_seeds_sha256": "6" * 64,
        "prior_fourth_report_selection_sha256": "7" * 64,
        "spent_state_overlap": 0,
        "spent_deal_seed_overlap": 0,
        "remaining_report_supply_after_selection": {
            "play": 1_135, "bury": 128},
        "states": [{"secret": "must not publish"}],
    }
    summary = CTRL._selection_summary(selection)
    assert "states" not in summary
    assert summary["state_material_published"] is False
    assert summary["surface_counts"] == {"play": 480}


def test_review_claim_authorizes_only_one_controller_freeze() -> None:
    diagnostic = {
        "states": 40,
        "proposal_triggers": 10,
        "teacher_improvement_vs_candidate0": {
            "mean": 0.1, "one_sided_95_lcb": 0.01},
    }
    packet = {
        "producer": {"git": "a" * 40},
        "packet_sha256": "b" * 64,
        "parents": {"bury_terminal_result_review": {
            "claim_sha256": "c" * 64}},
        "capability": dict(CTRL.EXPECTED_CAPABILITY),
        "checkpoint_manifest": [{}] * 8,
        "checkpoint_manifest_sha256": "d" * 64,
        "diagnostics": {"DESIGN": diagnostic, "CALIB": diagnostic},
        "diagnostics_sha256": "e" * 64,
        "fresh_play_selection": {
            "selection_sha256": "f" * 64,
            "state_ids_sha256": "0" * 64,
            "state_count": 480,
            "surface_counts": {"play": 480},
            "spent_report_populations": 4,
            "spent_report_states": 2_048,
            "spent_state_overlap": 0,
            "spent_deal_seed_overlap": 0,
            "remaining_report_supply_after_selection": {
                "play": 1_135, "bury": 128},
        },
    }
    claim = CTRL.expected_review_claim(packet, "9" * 64)
    assert claim["one_play_report_controller_freeze_authorized"] is True
    assert claim["report_open_authorized"] is False
    assert claim["report_execution_authorized"] is False
    assert claim["composition_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False
