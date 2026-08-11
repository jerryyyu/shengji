import json
import os
import subprocess
import sys

import pytest

import teacher_stage_c_expanded_report_controller as CTRL
import teacher_stage_c_report_runtime as RUNTIME


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


def test_recovery_review_grants_freeze_but_not_report_execution(
        monkeypatch, tmp_path):
    selection = {
        "schema": CTRL.EXP.SUCCESSOR_REPORT_SCHEMA,
        "states": [],
        "states_sha256": "1" * 64,
        "state_ids_sha256": "2" * 64,
        "state_count": 512,
        "surface_counts": {"play": 480, "bury": 32},
        "spent_report_populations": 3,
        "spent_report_states": 1_536,
        "spent_report_state_ids_sha256": "3" * 64,
        "spent_report_deal_seeds_sha256": "4" * 64,
        "spent_state_overlap": 0,
        "spent_deal_seed_overlap": 0,
        "remaining_report_supply_after_selection": {
            "play": 1_615, "bury": 128},
        "labels_or_outcomes_opened": False,
        "report_labels_opened": False,
    }
    selection["selection_sha256"] = CTRL._manifest_hash(selection)
    monkeypatch.setattr(CTRL, "_source_sha256s", lambda: {
        "server/scripts/teacher_stage_c_expanded_report_controller.py":
            "5" * 64,
        "server/shengji/rl/stage_c_expansion.py": "6" * 64,
    })
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "7" * 64)
    claim = CTRL.expected_recovery_review_claim(
        selection, git="f" * 40)
    assert claim["one_score_free_v2_packet_freeze_authorized"] is True
    assert claim["report_execution_authorized"] is False
    assert claim["retry_authorized"] is False

    review = tmp_path / "recovery-review.md"
    review.write_text(CTRL.RECOVERY_REVIEW_MARKER + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n")
    monkeypatch.setattr(CTRL, "_git", lambda *_args, **_kwargs: "f" * 40)
    assert CTRL.validate_recovery_review(review, selection) == claim

    claim["report_execution_authorized"] = True
    review.write_text(CTRL.RECOVERY_REVIEW_MARKER + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(CTRL.ReportControllerRefused, match="PASS marker"):
        CTRL.validate_recovery_review(review, selection)


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
    spent_states = [dict(state, state_id=f"spent-{state['state_id']}")
                    for state in states]
    spent_selection = {
        "states": spent_states,
        "sealed_report_state_ids_sha256": CTRL._manifest_hash(sorted(
            state["state_id"] for state in spent_states)),
    }
    selection = {
        "states": states,
        "states_sha256": CTRL._manifest_hash(states),
        "state_ids_sha256": CTRL._manifest_hash(sorted(
            state["state_id"] for state in states)),
        "state_count": 512,
        "surface_counts": {"play": 480, "bury": 32},
        "spent_report_populations": 3,
        "spent_report_state_ids_sha256": "1" * 64,
        "spent_report_deal_seeds_sha256": "2" * 64,
        "spent_state_overlap": 0,
        "spent_deal_seed_overlap": 0,
        "remaining_report_supply_after_selection": {
            "play": 1_615, "bury": 128},
        "labels_or_outcomes_opened": False,
        "report_labels_opened": False,
    }
    selection["selection_sha256"] = CTRL._manifest_hash(selection)
    sealed = {
        "state_ids_sha256": spent_selection[
            "sealed_report_state_ids_sha256"],
        "state_material_sha256": CTRL._manifest_hash(spent_states),
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
    recovery_review = tmp_path / "recovery-review.md"
    for path in (training_review, state_review, fresh_review):
        path.write_text("review\n")
    recovery_review.write_text(CTRL.RECOVERY_REVIEW_MARKER + "{}\n")
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
        recovery_review_record=recovery_review,
        training_packet={"packet_sha256": "a" * 64}, dataset=dataset,
        aggregate=aggregate, manifest=manifest,
        spent_selection=spent_selection, selection=selection,
        report_states=states)
    assert packet["selected_capability"]["surface"] == "bury"
    assert packet["protected_policy"] is None
    assert packet["report_schedule"]["states"] == 32
    assert packet["report_schedule"]["candidate_world_ceiling"] == 32 * 9
    assert packet["report_contract"]["report_population_ordinal"] == 4
    assert packet["report_contract"]["prior_report_populations_spent"] == 3
    assert packet["parents"]["fresh_report_selection"][
        "spent_state_overlap"] == 0
    assert packet["commands"]["run_shards"][0][1] == \
        CTRL.RUNTIME_SCRIPT_PATH
    runtime_commands = [
        packet["commands"]["admit"],
        *packet["commands"]["run_shards"],
        packet["commands"]["evaluate"],
    ]
    substitutions = {
        "{python}": sys.executable,
        "{git}": "f" * 40,
        "{packet_sha256}": "a" * 64,
        "{controller_review_record}": "controller-review.md",
        "{fresh_report_review_record}": "fresh-review.md",
        "{state_set_review_record}": "state-review.md",
        "{receipt_sha256}": "b" * 64,
    }
    for command in runtime_commands:
        assert command.count("--expected-git") == 1
        position = command.index("--expected-git")
        assert command[position + 1] == "{git}"
        expanded = [substitutions.get(token, token) for token in command]
        RUNTIME.parser().parse_args(expanded[2:])
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
    spent_selection = {
        "states": states,
        "sealed_report_state_ids_sha256": "a" * 64,
    }
    selection = {
        "state_count": 512,
        "surface_counts": {"play": 480, "bury": 32},
        "spent_report_populations": 3,
        "spent_state_overlap": 0,
        "spent_deal_seed_overlap": 0,
        "labels_or_outcomes_opened": False,
        "report_labels_opened": False,
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
            recovery_review_record=review,
            training_packet={"packet_sha256": "a" * 64}, dataset=dataset,
            aggregate=aggregate, manifest=[],
            spent_selection=spent_selection, selection=selection,
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
