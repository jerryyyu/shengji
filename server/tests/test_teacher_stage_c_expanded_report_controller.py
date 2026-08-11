import os
import subprocess
import sys

import pytest

import teacher_stage_c_expanded_report_controller as CTRL


def capability():
    return {
        "action_improvement_positive_seeds": 8,
        "calibration_positive_seeds": 8,
        "eligible": True,
        "epoch": 32,
        "head": "ranking",
        "loss_recipe": "all_pairs_v1",
        "mean_teacher_regret": 0.1615142822265625,
        "median_action_improvement_vs_candidate0": 0.01641845703125,
        "median_outcome_nll_improvement": 0.02034193337756174,
        "outcome_calibration_required": False,
        "surface": "bury",
    }


def terminal_parents():
    aggregate = {
        "schedule_sha256": "a" * 64,
        "aggregate_sha256": CTRL.TRAINING_AGGREGATE_INTERNAL_SHA256,
        "selection": {
            "selected_capability": capability(),
            "selection_sha256": "b" * 64,
        },
    }
    receipt = {"receipt_sha256": "c" * 64}
    final = {"final_sha256": CTRL.TRAINING_SUPERVISOR_FINAL_INTERNAL_SHA256}
    return aggregate, receipt, final


def test_training_result_claim_binds_exact_selected_cohort():
    aggregate, receipt, final = terminal_parents()
    claim = CTRL.expected_training_result_review_claim(
        aggregate, receipt, final)
    assert claim["decision"] == \
        "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW"
    assert claim["selected_capability"] == {
        "loss_recipe": "all_pairs_v1",
        "surface": "bury",
        "head": "ranking",
        "epoch": 32,
        "action_improvement_positive_seeds": 8,
        "calibration_positive_seeds": 8,
        "median_action_improvement_vs_candidate0": 0.01641845703125,
        "mean_teacher_regret": 0.1615142822265625,
        "median_outcome_nll_improvement": 0.02034193337756174,
    }
    assert claim["one_expanded_report_controller_freeze_authorized"] is True
    assert claim["report_open_authorized"] is False
    assert claim["strength_claim"] is False


def test_training_result_claim_refuses_a_different_winner():
    aggregate, receipt, final = terminal_parents()
    aggregate["selection"]["selected_capability"]["surface"] = "play"
    with pytest.raises(CTRL.ReportControllerRefused):
        CTRL.expected_training_result_review_claim(aggregate, receipt, final)


def test_report_schedule_is_eight_equal_bury_shards(monkeypatch):
    states = [
        {"state_id": f"bury-{index:03d}", "surface_type": "bury",
         "candidates": [0, 1]}
        for index in range(32)
    ] + [
        {"state_id": f"play-{index:03d}", "surface_type": "play",
         "candidates": [0, 1]}
        for index in range(480)
    ]
    monkeypatch.setattr(CTRL, "_candidate_world_ceiling", lambda _state: 7)
    schedule = CTRL.build_report_schedule(states, surface="bury")
    assert schedule["states"] == 32
    assert [shard["state_count"] for shard in schedule["shards"]] == [4] * 8
    assert schedule["candidate_world_ceiling"] == 32 * 7
    assert schedule["schedule_sha256"] == CTRL._manifest_hash({
        key: value for key, value in schedule.items()
        if key != "schedule_sha256"
    })


def test_report_schedule_refuses_underfilled_bury_population(monkeypatch):
    monkeypatch.setattr(CTRL, "_candidate_world_ceiling", lambda _state: 1)
    with pytest.raises(CTRL.ReportControllerRefused):
        CTRL.build_report_schedule([
            {"state_id": f"bury-{index}", "surface_type": "bury"}
            for index in range(31)
        ], surface="bury")


def test_runtime_wrapper_selects_expanded_controller():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(("server", "server/scripts"))
    completed = subprocess.run(
        [sys.executable, "-c", (
            "import teacher_stage_c_expanded_report_runtime as wrapper; "
            "print(wrapper.BASE.CTRL.RUN_ID); "
            "print(wrapper.BASE.RECEIPT_SCHEMA)")],
        check=True, capture_output=True, text=True, env=env)
    assert completed.stdout.splitlines() == [
        CTRL.RUN_ID, CTRL.RUNTIME_RECEIPT_SCHEMA]


def test_supervisor_wrapper_selects_expanded_schemas():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(("server", "server/scripts"))
    completed = subprocess.run(
        [sys.executable, "-c", (
            "import teacher_stage_c_expanded_report_supervisor as wrapper; "
            "print(wrapper.BASE.CTRL.RUN_ID); "
            "print(wrapper.BASE.SCHEMA); "
            "print(wrapper.BASE.REVIEW_MARKER)")],
        check=True, capture_output=True, text=True, env=env)
    assert completed.stdout.splitlines() == [
        CTRL.RUN_ID, CTRL.SUPERVISOR_SCHEMA,
        CTRL.SUPERVISOR_REVIEW_MARKER]


@pytest.mark.parametrize("module", (
    "teacher_stage_c_report_runtime",
    "teacher_stage_c_report_supervisor",
))
def test_shared_report_entry_points_refuse_unknown_controller(module):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(("server", "server/scripts"))
    env["SHENGJI_STAGE_C_REPORT_CONTROLLER"] = "json"
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, text=True, env=env)
    assert completed.returncode != 0
    assert "unrecognized Stage-C REPORT controller module" \
        in completed.stderr
