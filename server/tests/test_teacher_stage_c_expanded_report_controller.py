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


def test_packet_is_score_free_and_schedules_only_selected_bury(
        monkeypatch, tmp_path):
    states = [
        {"state_id": f"bury-{index:03d}", "surface_type": "bury",
         "split": "REPORT", "candidates": [0, 1]}
        for index in range(32)
    ] + [
        {"state_id": f"play-{index:03d}", "surface_type": "play",
         "split": "REPORT", "candidates": [0, 1]}
        for index in range(480)
    ]
    selection = {
        "states": states,
        "sealed_report_state_ids_sha256": CTRL._manifest_hash(sorted(
            state["state_id"] for state in states)),
    }
    sealed = {
        "state_ids_sha256": selection["sealed_report_state_ids_sha256"],
        "state_material_sha256": CTRL._manifest_hash(states),
        "states": 512,
        "surface_counts": {"play": 480, "bury": 32},
        "state_material_published": False,
        "labels_or_predictions_computed": False,
    }
    dataset = {
        "dataset_sha256": "d" * 64,
        "sealed_report_selection": sealed,
        "examples": {"DESIGN": {"bury": [{"unused": True}]}},
    }
    aggregate, _receipt, _final = terminal_parents()
    manifest = [{"seed": seed, "checkpoint_sha256": f"{index:064x}"}
                for index, seed in enumerate(CTRL.MODEL.TRAINING_SEEDS, 1)]
    training_review = tmp_path / "training-review.md"
    state_review = tmp_path / "state-review.md"
    fresh_review = tmp_path / "fresh-review.md"
    for path in (training_review, state_review, fresh_review):
        path.write_text("review\n")
    monkeypatch.setattr(CTRL, "_source_sha256s", lambda: {"source": "1"})
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: {"host": "mini"})
    monkeypatch.setattr(CTRL, "_candidate_world_ceiling", lambda _state: 9)
    monkeypatch.setattr(
        CTRL.TRAIN, "state_balanced_prior", lambda _examples: [0.125] * 8)
    packet = CTRL.build_packet(
        git="f" * 40, evidence_repo=tmp_path,
        training_result_review_record=training_review,
        capture_evidence_repo=tmp_path,
        state_set_review_record=state_review,
        fresh_report_review_record=fresh_review,
        training_packet={"packet_sha256": "a" * 64}, dataset=dataset,
        aggregate=aggregate, manifest=manifest, selection=selection,
        report_states=states)
    assert packet["selected_capability"]["surface"] == "bury"
    assert packet["protected_policy"] is None
    assert packet["report_schedule"]["states"] == 32
    assert packet["report_schedule"]["candidate_world_ceiling"] == 32 * 9
    assert packet["commands"]["run_shards"][0][1] == \
        CTRL.RUNTIME_SCRIPT_PATH
    assert packet["authority"] == {
        "fresh_report_capture_shards_revalidated": 8,
        "fresh_report_state_material_published": False,
        "teacher_labels_computed": 0,
        "model_predictions_computed": 0,
        "report_utility_opened": False,
        "one_report_execution_authorized": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert packet["packet_sha256"] == CTRL.self_hash(
        packet, "packet_sha256")


def test_packet_refuses_sealed_report_material_drift(monkeypatch, tmp_path):
    states = [
        {"state_id": f"bury-{index:03d}", "surface_type": "bury",
         "split": "REPORT", "candidates": [0, 1]}
        for index in range(32)
    ] + [
        {"state_id": f"play-{index:03d}", "surface_type": "play",
         "split": "REPORT", "candidates": [0, 1]}
        for index in range(480)
    ]
    selection = {
        "states": states,
        "sealed_report_state_ids_sha256": "a" * 64,
    }
    dataset = {
        "dataset_sha256": "d" * 64,
        "sealed_report_selection": {
            "state_ids_sha256": "a" * 64,
            "state_material_sha256": "wrong",
            "states": 512,
            "surface_counts": {"play": 480, "bury": 32},
            "state_material_published": False,
            "labels_or_predictions_computed": False,
        },
        "examples": {"DESIGN": {"bury": []}},
    }
    review = tmp_path / "review.md"
    review.write_text("review\n")
    aggregate, _receipt, _final = terminal_parents()
    monkeypatch.setattr(CTRL, "_source_sha256s", lambda: {})
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: {})
    monkeypatch.setattr(CTRL, "_candidate_world_ceiling", lambda _state: 1)
    with pytest.raises(CTRL.ReportControllerRefused, match="sealed REPORT"):
        CTRL.build_packet(
            git="f" * 40, evidence_repo=tmp_path,
            training_result_review_record=review,
            capture_evidence_repo=tmp_path,
            state_set_review_record=review,
            fresh_report_review_record=review,
            training_packet={"packet_sha256": "a" * 64}, dataset=dataset,
            aggregate=aggregate, manifest=[], selection=selection,
            report_states=states)


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
