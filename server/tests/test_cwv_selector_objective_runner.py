"""Failing-direction checks for the selector diagnostic's control and readout."""
import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).parents[1] / "scripts/cwv_selector_objective_audit.py"
    spec = importlib.util.spec_from_file_location("objective_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def control_record():
    return {"candidates": [["SK"], ["SQ"]], "played": ["SQ"], "played_index": 1,
            "reason": "report_lcb_override", "report_candidate_index": 1,
            "raw_winner_index": 1, "n_by_candidate": [30, 30], "worlds": 30,
            "work": {"selection_rollouts": 60, "report_rollouts": 600}, "report_seed": 17,
            "means": [42.0, 48.0], "paired_se": [0, 1.0],
            "report_fold": {"gap": 4.0, "se": 1.0, "statistic": 2.3, "critical": 1.7, "min_gain": 0.0}}


@pytest.mark.parametrize("field", ["played", "means", "work", "report"])
def test_control_must_reproduce_actual_record_not_only_played_action(runner, field):
    saved = control_record()
    replay = copy.deepcopy(saved)
    runner.verify_control(saved, replay)
    if field == "played":
        replay["played"] = ["SK"]
    elif field == "means":
        replay["means"][1] += 0.1
    elif field == "work":
        replay["work"]["report_rollouts"] -= 2
    else:
        replay["report_fold"]["statistic"] = -2.3
    with pytest.raises(ValueError, match="^control (consumer|report) mismatch:"):
        runner.verify_control(saved, replay)


def test_no_search_does_not_masquerade_as_valid_contested_control(runner):
    runner.verify_control(None, None)
    with pytest.raises(ValueError, match="^control search/no-search mismatch$"):
        runner.verify_control(control_record(), None)


def test_validation_root_is_refused_before_reconstruction(runner, monkeypatch):
    monkeypatch.setattr(runner, "_round_from_snapshot", lambda *a: pytest.fail("must not reconstruct validation"))
    with pytest.raises(ValueError, match="^objective diagnostic accepts only FIT positions$"):
        runner.run_case({"provenance": {"split": "validation"}}, {}, {}, {})


def test_summary_pairs_objectives_and_uses_deals_not_row_count(runner):
    def row(deal, level, changed):
        return {"deal_key": deal, "all_point_controls_reproduced": True,
                "native_rollouts_executed": 30, "wall_seconds": 0.1,
                "arms": {"v1/finished/points": {"played": ["SK"], "final_lift_vs_incumbent": 0},
                         "v1/finished/levels": {"played": ["SQ"] if changed else ["SK"],
                                                  "final_lift_vs_incumbent": level}}}
    rows = [row("a", 1, True), row("a", 1, True), row("b", -1, False)]
    result = runner.summarize(rows)
    assert result["states"] == 3 and result["deals"] == 2
    assert result["native_rollouts_executed"] == 90
    assert result["contrasts"]["v1/finished/levels"]["level_minus_point"] == 0
    assert result["contrasts"]["v1/finished/levels"]["changed_submitted_moves"] == 2
    rows[0]["all_point_controls_reproduced"] = False
    assert not runner.summarize(rows)["all_point_controls_reproduced"]
