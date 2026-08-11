from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_midlate_state_controller as CTRL  # noqa: E402


def _write_marker(path: Path, marker: str, claim: dict) -> None:
    path.write_text(marker + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n")


def test_source_review_requires_the_exact_raw_claim(tmp_path: Path) -> None:
    record = tmp_path / "review.md"
    _write_marker(
        record, CTRL.SOURCE_REVIEW_MARKER,
        CTRL.expected_source_review_claim())
    assert CTRL.validate_source_review(record) \
        == CTRL.expected_source_review_claim()

    forged = CTRL.expected_source_review_claim()
    forged["evidence_open_authorized"] = True
    _write_marker(tmp_path / "forged.md", CTRL.SOURCE_REVIEW_MARKER, forged)
    with pytest.raises(CTRL.MidlateStateControllerRefused,
                       match="authority drift"):
        CTRL.validate_source_review(tmp_path / "forged.md")


def test_forbidden_manifest_covers_all_capture_and_prior_screen_deals(
        monkeypatch) -> None:
    original = {"states": [{"seed": 10}, {"seed": 11}]}
    shards = [{"retained_states": [
        {"seed": 10}, {"seed": 11}, {"seed": 12},
    ]}]
    current = [{"seed": 12}]
    monkeypatch.setattr(
        CTRL.CAPABILITY.EXPANSION, "validate_evidence",
        lambda **_kwargs: ({}, original, {}, {}, shards, current))
    values = CTRL.forbidden_deal_seeds(
        capture_evidence_repo=Path("/capture"),
        state_set_review_record=Path("/state-review"),
        fresh_report_review_record=Path("/fresh-review"))
    assert {10, 11, 12} <= set(values)
    assert CTRL.PRIOR_STAGE_C_RANGES[0][0] in values
    assert CTRL.SEED0 not in values
    assert values == sorted(set(values))


def _complete_population() -> dict:
    return {
        "complete": True,
        "decision": "READY_FOR_EVALUATION_REVIEW",
        "selected_states": 256,
        "deals_scanned": 400,
        "cell_counts": {cell: 64 for cell in CTRL.SCREEN.CELL_KEYS},
        "position_counts": {"lead": 64, "follow": 192},
        "evaluation_folds_opened": 0,
        "forbidden_deal_overlap": 0,
        "population_sha256": "a" * 64,
    }


def test_selection_review_claim_refuses_underfill() -> None:
    packet = {"producer": {"git": "g"}}
    wrapper = {"population": _complete_population()}
    claim = CTRL.expected_selection_review_claim(
        packet, "b" * 64, wrapper, "c" * 64)
    assert claim["one_evaluation_execution_authorized"] is True
    assert claim["evaluation_folds_opened"] == 0

    short = copy.deepcopy(wrapper)
    short["population"]["selected_states"] = 255
    short["population"]["complete"] = False
    with pytest.raises(CTRL.MidlateStateControllerRefused,
                       match="does not meet"):
        CTRL.expected_selection_review_claim(
            packet, "b" * 64, short, "c" * 64)


def test_screen_contract_has_only_two_primary_strength_gates() -> None:
    contract = CTRL.screen_contract([1, 2, 3])
    assert contract["primary_gates"] == [
        "treatment-minus-live one-sided 95% LCB > 0",
        "treatment-minus-matched-null one-sided 95% LCB > 0",
    ]
    assert contract["matched-null-minus-live_is_diagnostic_only"] is True
    assert contract["evaluation_candidate_worlds"] == 256 * 3 * 300
    assert contract["retry_or_extension_authorized"] is False
