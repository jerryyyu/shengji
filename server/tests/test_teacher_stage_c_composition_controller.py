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
        "report_manifest": [{
            "index": index,
            "logical_path": f"report/shard-{index - 12}.json",
            "sha256": f"{index + 1:064x}",
            "row_sha256s_sha256": f"{index + 101:064x}",
        } for index in range(12, 16)],
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
        "report_manifest_sha256": CTRL.REPORT_CTRL._manifest_hash(
            packet["report_manifest"]),
        "opened_report_shards": [{
            "index": item["index"],
            "logical_path": item["logical_path"],
            "external_sha256": item["sha256"],
            "row_sha256s_sha256": item["row_sha256s_sha256"],
        } for item in packet["report_manifest"]],
        "report_shard_files_opened": 4,
        "report_rows_opened": 512,
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
    result_path = tmp_path / CTRL.REPORT_RUNTIME.RESULT_PATH
    result_path.parent.mkdir(parents=True)
    result_path.write_text("result")
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(
        CTRL.REPORT_RUNTIME, "_packet",
        lambda *_args, **_kw: (packet, {}, {}, {}))
    monkeypatch.setattr(CTRL.REPORT_RUNTIME, "_receipt",
                        lambda *_args, **_kw: {})
    reopened = []
    monkeypatch.setattr(
        CTRL.REPORT_RUNTIME, "_validate_report_open_slot",
        lambda *_args, **_kw: reopened.append(True))
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "4" * 64)
    monkeypatch.setattr(CTRL, "load_json", lambda _path: result)
    packet_out, result_out = CTRL.validate_report_result(
        report_packet_path=tmp_path / "packet.json",
        report_packet_sha256="1" * 64,
        report_review_record=tmp_path / "review.txt",
        report_receipt_path=tmp_path / "receipt.json",
        report_receipt_sha256="2" * 64,
        report_result_path=result_path,
        report_result_sha256="4" * 64)
    assert packet_out is packet
    assert result_out is result
    assert reopened == [True]

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
            report_receipt_path=tmp_path / "receipt.json",
            report_receipt_sha256="2" * 64,
            report_result_path=result_path,
            report_result_sha256="4" * 64)


def test_packet_binds_exact_models_population_and_narrow_authority(
        monkeypatch, tmp_path) -> None:
    packet = _report_packet()
    result = _report_result(packet)
    v11 = tmp_path / CTRL.V11_PATH
    v11.parent.mkdir(parents=True)
    v11.write_bytes(b"v11")
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL.CAPTURE_RUNTIME, "V11_SHA256", "5" * 64)
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "5" * 64)
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "_source_sha256s",
                        lambda: {"source": "6" * 64})
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: {
        "host": "mini", "python": "3.14", "numpy": "2.5",
    })
    built = CTRL.build_packet(
        git="a" * 40, report_packet=packet,
        report_packet_ref={"logical_path": "report-packet.json",
                           "external_sha256": "1" * 64},
        report_review_ref={"logical_path": "review.txt",
                           "external_sha256": "7" * 64},
        report_receipt_ref={"logical_path": "receipt.json",
                            "external_sha256": "2" * 64},
        report_result=result,
        report_result_ref={"logical_path": "result.json",
                           "external_sha256": "4" * 64},
        exports=_exports())
    assert built["selected_capability"] == _capability()
    assert len(built["model_exports"]) == 8
    assert built["screen_contract"]["clusters"] == 2_048
    assert built["screen_contract"]["shards"] == 8
    assert built["authority"] == {
        "screen_packet_review_authorized": True,
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert built["packet_sha256"] == CTRL.self_hash(
        built, "packet_sha256")
    assert len(built["result_contract"]["shard_admission_slots"]) == 8


def test_commands_cover_each_shard_and_bind_existing_receipt() -> None:
    commands = CTRL._commands()
    assert len(commands["run_shards"]) == CTRL.SHARD_COUNT
    assert [command[command.index("--shard-index") + 1]
            for command in commands["run_shards"]] \
        == [str(index) for index in range(CTRL.SHARD_COUNT)]
    assert all(command[
        command.index("--expected-screen-receipt-sha256") + 1]
        == "{receipt_sha256}" for command in commands["run_shards"])
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


def test_review_claim_can_authorize_screen_only(monkeypatch, tmp_path) -> None:
    packet = _report_packet()
    result = _report_result(packet)
    v11 = tmp_path / CTRL.V11_PATH
    v11.parent.mkdir(parents=True)
    v11.write_bytes(b"v11")
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL.CAPTURE_RUNTIME, "V11_SHA256", "5" * 64)
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "5" * 64)
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "_source_sha256s", lambda: {})
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: {
        "host": "mini", "python": "3.14", "numpy": "2.5",
    })
    built = CTRL.build_packet(
        git="a" * 40, report_packet=packet,
        report_packet_ref={}, report_review_ref={},
        report_receipt_ref={}, report_result=result,
        report_result_ref={"external_sha256": "4" * 64},
        exports=_exports())
    claim = CTRL.expected_review_claim(built, "8" * 64)
    assert claim["one_screen_execution_authorized"] is True
    assert claim["confirmation_launch_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_promotion"] is False
