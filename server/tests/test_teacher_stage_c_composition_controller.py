from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_composition_controller as CTRL  # noqa: E402
from shengji.rl import stage_c_model as MODEL


def _capability():
    return {"surface": "play", "head": "ranking", "epoch": 8}


def _runtime_contract():
    return {
        "host": "mini", "python": "3.14", "numpy": "2.5",
        "python_executable": "/reviewed/python",
        "python_executable_resolved": "/resolved/reviewed/python",
        "python_executable_sha256": "e" * 64,
        "supervisor_heartbeat_seconds": 30,
        "supervisor_signal_contract": {
            "handled_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_shards_authorized": False,
        },
    }


def _report_packet():
    return {
        "producer": {"git": "a" * 40},
        "selected_capability": _capability(),
        "checkpoint_manifest": [{
            "seed": seed,
            "surface": "play",
            "head": "ranking",
            "epoch": 8,
            "checkpoint_path": f"models/{seed}.pt",
            "checkpoint_sha256": f"{seed + 1:064x}",
            "model_state_sha256": f"{seed + 101:064x}",
            "checkpoint_contract": {"seed": seed},
        } for seed in MODEL.TRAINING_SEEDS],
        "parents": {"fresh_report_selection": {
            "sealed_selection_sha256": "8" * 64,
            "fresh_report_states": 512,
        }},
        "report_schedule": {
            "schedule_sha256": "9" * 64,
            "candidate_world_ceiling": 10_000,
            "shards": [{
                "index": index,
                "state_ids_sha256": f"{index + 11:064x}",
            } for index in range(8)],
        },
        "report_contract": {"states": 2},
    }


def _report_result(packet):
    evaluation = {
        "schema": CTRL.REPORT.REPORT_SCHEMA,
        "surface": "play",
        "head": "ranking",
        "ensemble_seeds": list(MODEL.TRAINING_SEEDS),
        "states": 2,
        "proposal_triggers": 1,
        "teacher_improvement_vs_candidate0": {
            "one_sided_95_lcb": 0.1},
        "outcome_nll_improvement_vs_design_prior": {
            "one_sided_95_lcb": -0.1},
        "rows": [{"state_id": "s0"}, {"state_id": "s1"}],
        "decision": "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW",
        "composition_packet_review_authorized": True,
        "report_opened_once": True,
        "report_reuse_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    evaluation["result_sha256"] = CTRL.self_hash(
        evaluation, "result_sha256")
    result = {
        "schema": CTRL.REPORT_RUNTIME.RESULT_SCHEMA,
        "run_id": CTRL.REPORT_CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": "1" * 64,
        "report_receipt_sha256": "2" * 64,
        "report_open_admission_slot":
            CTRL.REPORT_RUNTIME.REPORT_OPEN_ADMISSION_PATH,
        "report_open_admission_slot_sha256": "3" * 64,
        "selected_capability": packet["selected_capability"],
        "checkpoint_manifest_sha256": CTRL.REPORT_CTRL._manifest_hash(
            packet["checkpoint_manifest"]),
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "opened_report_label_shards": [{
            "index": index,
            "logical_path": CTRL.REPORT_RUNTIME.SHARD_PATHS[index],
            "external_sha256": f"{index + 31:064x}",
            "internal_sha256": f"{index + 41:064x}",
            "state_ids_sha256": packet["report_schedule"]["shards"][
                index]["state_ids_sha256"],
            "row_sha256s_sha256": f"{index + 51:064x}",
            "status": "COMPLETE",
            "refused_rows": 0,
        } for index in range(8)],
        "report_label_shard_files_opened": 8,
        "fresh_report_states_reconstructed": 512,
        "selected_surface_rows_labeled": 2,
        "report_label_refusals": 0,
        "work": {
            "candidate_worlds_attempted": 9_000,
            "candidate_worlds_completed": 9_000,
        },
        "candidate_world_ceiling": 10_000,
        "candidate_world_ceiling_respected": True,
        "v11_checkpoint_loaded": False,
        "evaluation": evaluation,
        "decision": evaluation["decision"],
        "composition_packet_review_authorized": True,
        "report_reuse_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["result_sha256"] = CTRL.self_hash(result, "result_sha256")
    return result


def _report_supervisor_final(result):
    value = {
        "schema": CTRL.REPORT_SUPERVISOR.FINAL_SCHEMA,
        "run_id": CTRL.REPORT_CTRL.RUN_ID,
        "git": "a" * 40,
        "controller_packet_sha256": "1" * 64,
        "report_receipt_sha256": "2" * 64,
        "report_schedule_sha256": "9" * 64,
        "label_shards_complete": 8,
        "result_path": CTRL.REPORT_RUNTIME.RESULT_PATH,
        "result_external_sha256": "4" * 64,
        "result_internal_sha256": result["result_sha256"],
        "decision": result["decision"],
        "composition_packet_review_authorized": True,
        "report_reuse_authorized": False,
        "retry_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["final_sha256"] = CTRL.self_hash(value, "final_sha256")
    return value


def _exports():
    return [{
        "logical_path": CTRL.MODEL_PATHS[index],
        "sha256": f"{seed + 501:064x}",
        "metadata": {
            "surface": "play", "seed": seed, "epoch": 8,
            "model_state_sha256": f"{seed + 101:064x}",
            "checkpoint_sha256": f"{seed + 1:064x}",
        },
    } for index, seed in enumerate(MODEL.TRAINING_SEEDS)]


def test_terminal_report_result_is_reopened_without_reselection(
        monkeypatch, tmp_path) -> None:
    packet = _report_packet()
    packet["report_contract"] = {"states": 2}
    result = _report_result(packet)
    supervisor = _report_supervisor_final(result)
    result_path = tmp_path / CTRL.REPORT_RUNTIME.RESULT_PATH
    result_path.parent.mkdir(parents=True)
    result_path.write_text("result")
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(
        CTRL.REPORT_RUNTIME, "_packet",
        lambda *_args, **_kw: (packet, {}, {}, {}, []))
    monkeypatch.setattr(CTRL.REPORT_RUNTIME, "_receipt",
                        lambda *_args, **_kw: {
                            "report_open_admission_slot_sha256": "3" * 64})
    supervisor_path = tmp_path / CTRL.REPORT_SUPERVISOR.FINAL_PATH
    supervisor_path.parent.mkdir(parents=True, exist_ok=True)
    supervisor_path.write_text("supervisor")
    review_claim = {"one_composition_controller_freeze_authorized": True}
    monkeypatch.setattr(
        CTRL.REPORT_SUPERVISOR, "expected_review_claim",
        lambda **_kw: review_claim)
    monkeypatch.setattr(CTRL, "_marker_claim",
                        lambda *_args, **_kw: review_claim)
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(
        CTRL, "sha256_file",
        lambda path: "5" * 64 if path.resolve() == supervisor_path.resolve()
        else "4" * 64)
    monkeypatch.setattr(
        CTRL, "load_json",
        lambda path: supervisor if path.resolve() == supervisor_path.resolve()
        else result)
    packet_out, result_out = CTRL.validate_report_result(
        report_packet_path=tmp_path / "packet.json",
        report_packet_sha256="1" * 64,
        report_review_record=tmp_path / "review.txt",
        fresh_report_review_record=tmp_path / "fresh-review.txt",
        state_set_review_record=tmp_path / "state-review.txt",
        report_receipt_path=tmp_path / "receipt.json",
        report_receipt_sha256="2" * 64,
        report_result_path=result_path,
        report_result_sha256="4" * 64,
        report_supervisor_final_path=supervisor_path,
        report_supervisor_final_sha256="5" * 64,
        report_result_review_record=tmp_path / "result-review.txt")
    assert packet_out is packet
    assert result_out is result

    broken = copy.deepcopy(result)
    broken["composition_packet_review_authorized"] = False
    broken["result_sha256"] = CTRL.self_hash(broken, "result_sha256")
    monkeypatch.setattr(CTRL, "load_json", lambda _path: broken)
    with pytest.raises(CTRL.CompositionControllerRefused,
                       match="identity/authority"):
        CTRL.validate_report_result(
            report_packet_path=tmp_path / "packet.json",
            report_packet_sha256="1" * 64,
            report_review_record=tmp_path / "review.txt",
            fresh_report_review_record=tmp_path / "fresh-review.txt",
            state_set_review_record=tmp_path / "state-review.txt",
            report_receipt_path=tmp_path / "receipt.json",
            report_receipt_sha256="2" * 64,
            report_result_path=result_path,
            report_result_sha256="4" * 64,
            report_supervisor_final_path=supervisor_path,
            report_supervisor_final_sha256="5" * 64,
            report_result_review_record=tmp_path / "result-review.txt")


def test_packet_binds_exact_models_population_and_narrow_authority(
        monkeypatch, tmp_path) -> None:
    packet = _report_packet()
    result = _report_result(packet)
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "5" * 64)
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "_source_sha256s",
                        lambda: {"source": "6" * 64})
    monkeypatch.setattr(CTRL, "runtime_contract", _runtime_contract)
    built = CTRL.build_packet(
        git="a" * 40, report_packet=packet,
        report_packet_ref={"logical_path": "report-packet.json",
                           "external_sha256": "1" * 64},
        report_review_ref={"logical_path": "review.txt",
                           "external_sha256": "7" * 64},
        fresh_report_review_ref={"logical_path": "fresh-review.txt",
                                 "external_sha256": "8" * 64},
        state_set_review_ref={"logical_path": "state-review.txt",
                              "external_sha256": "9" * 64},
        report_receipt_ref={"logical_path": "receipt.json",
                            "external_sha256": "2" * 64},
        report_result=result,
        report_result_ref={"logical_path": "result.json",
                           "external_sha256": "4" * 64},
        report_supervisor_final_ref={
            "logical_path": "report-supervisor-final.json",
            "external_sha256": "a" * 64},
        report_result_review_ref={
            "logical_path": "report-result-review.txt",
            "external_sha256": "b" * 64},
        exports=_exports())
    assert built["selected_capability"] == _capability()
    assert len(built["model_exports"]) == 8
    assert built["screen_contract"]["clusters"] == 2_048
    assert built["screen_contract"]["shards"] == 8
    assert built["screen_contract"]["supervisor_signal_contract"] == {
        "handled_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
        "signals_deferred_until_child_registered": True,
        "terminates_all_owned_children": True,
        "orphaned_shards_authorized": False,
    }
    assert built["capacity_contract"]["clusters"] == 4
    assert built["authority"] == {
        "capacity_preflight_review_authorized": True,
        "capacity_preflight_launch_authorized": False,
        "screen_packet_review_authorized": False,
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "v11_inference_authorized": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert built["packet_sha256"] == CTRL.self_hash(
        built, "packet_sha256")
    assert len(built["result_contract"]["shard_admission_slots"]) == 8
    assert built["candidate_contract"]["novel_model_proposer"] \
        == "v11pair_ep07_value"
    assert built["candidate_contract"]["v11_artifact_loaded"] is True
    assert built["candidate_contract"]["literal_live_policy_is_incumbent"] \
        is True


def test_commands_cover_each_shard_and_bind_existing_receipt() -> None:
    commands = CTRL._commands()
    assert commands["capacity_preflight"][2] == "capacity-preflight"
    assert commands["supervise"][2] == "supervise"
    assert len(commands["supervisor_child_shards"]) == CTRL.SHARD_COUNT
    assert [command[command.index("--shard-index") + 1]
            for command in commands["supervisor_child_shards"]] \
        == [str(index) for index in range(CTRL.SHARD_COUNT)]
    assert all(command[
        command.index("--expected-screen-receipt-sha256") + 1]
        == "{receipt_sha256}"
        for command in commands["supervisor_child_shards"])
    assert all("--expected-supervisor-admission-sha256" in command
               for command in commands["supervisor_child_shards"])
    assert "--expected-supervisor-final-sha256" in commands["aggregate"]
    assert "--supervisor-review-record" in commands["aggregate"]
    assert commands["aggregate"][
        commands["aggregate"].index("--shards") + 1:
        commands["aggregate"].index("--out")] == list(CTRL.SHARD_PATHS)


def test_model_export_population_refuses_late_collision_before_loading(
        monkeypatch, tmp_path) -> None:
    packet = _report_packet()
    collision = tmp_path / CTRL.MODEL_PATHS[-1]
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"old-export")
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(
        CTRL.TRAIN, "load_snapshot",
        lambda *_args, **_kw: pytest.fail(
            "checkpoint opened before full output preflight"))
    with pytest.raises(CTRL.CompositionControllerRefused,
                       match="existing Stage-C NumPy export"):
        CTRL._export_models(packet, verify=False)
    assert not (tmp_path / CTRL.MODEL_PATHS[0]).exists()


def test_initial_review_claim_authorizes_capacity_only(
        monkeypatch, tmp_path) -> None:
    packet = _report_packet()
    result = _report_result(packet)
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "5" * 64)
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "_source_sha256s", lambda: {})
    monkeypatch.setattr(CTRL, "runtime_contract", _runtime_contract)
    built = CTRL.build_packet(
        git="a" * 40, report_packet=packet,
        report_packet_ref={}, report_review_ref={},
        fresh_report_review_ref={}, state_set_review_ref={},
        report_receipt_ref={}, report_result=result,
        report_result_ref={"external_sha256": "4" * 64},
        report_supervisor_final_ref={"external_sha256": "5" * 64},
        report_result_review_ref={"external_sha256": "6" * 64},
        exports=_exports())
    claim = CTRL.expected_review_claim(built, "8" * 64)
    assert claim["one_capacity_preflight_authorized"] is True
    assert claim["one_screen_execution_authorized"] is False
    assert claim["python_executable"] == "/reviewed/python"
    assert claim["python_executable_resolved"] \
        == "/resolved/reviewed/python"
    assert claim["python_executable_sha256"] == "e" * 64
    assert claim["supervisor_heartbeat_seconds"] == 30
    assert claim["supervisor_signal_contract"][
        "orphaned_shards_authorized"] is False
    assert claim["confirmation_launch_authorized"] is False
    assert claim["v11_inference_authorized"] is True
    assert claim["strength_claim"] is False
    assert claim["production_promotion"] is False


def test_capacity_review_claim_is_the_only_screen_authority() -> None:
    packet = {
        "producer": {"git": "a" * 40},
    }
    capacity = {
        "result_sha256": "b" * 64,
        "elapsed_seconds": 12.5,
        "projection": {
            "screen_fleet_hours": 3.0,
            "screen_max_shard_hours": 0.375,
        },
        "screen_max_shard_seconds": 1_350.0,
    }
    claim = CTRL.expected_capacity_review_claim(
        packet, "c" * 64, capacity, "d" * 64)
    assert claim["capacity_pass"] is True
    assert claim["score_free"] is True
    assert claim["one_screen_execution_authorized"] is True
    assert claim["confirmation_launch_authorized"] is False
    assert claim["strength_claim"] is False
