from __future__ import annotations

import copy

import pytest

import teacher_stage_c_report_controller as CTRL
from shengji.rl import stage_c_model as MODEL


def _label_packet() -> dict:
    return {
        "schedule": {"shards": [
            {
                "index": index,
                "split": ("DESIGN" if index < 8 else
                          "CALIB" if index < 12 else "REPORT"),
                "local_shard": (index if index < 8 else
                                index - 8 if index < 12 else index - 12),
                "state_count": 128,
            }
            for index in range(16)
        ]},
        "result_contract": {"receipt": "server/runs/logs/label/receipt.json"},
        "parents": {"state_set": {
            "logical_path": "server/runs/logs/capture/states.json",
            "external_sha256": "9" * 64,
        }},
    }


def _sealed_report() -> list[dict]:
    return [{
        "index": index,
        "split": "REPORT",
        "sha256": f"{index + 1:064x}",
        "row_sha256s_sha256": f"{index + 101:064x}",
    } for index in range(12, 16)]


def test_report_manifest_derives_paths_without_touching_report_files(
        monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL.TRAIN_CTRL, "REPO", tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sealed REPORT file was touched")

    monkeypatch.setattr(CTRL, "sha256_file", forbidden)
    monkeypatch.setattr(CTRL, "load_json", forbidden)
    result = CTRL._report_manifest(
        _label_packet(), {"sealed_report_shards": _sealed_report()})
    assert [value["index"] for value in result] == list(range(12, 16))
    assert [value["states"] for value in result] == [128] * 4
    assert [value["logical_path"] for value in result] == [
        f"server/runs/logs/{CTRL.LABEL._ctrl().RUN_ID}/report/shard-{i:02d}.json"
        for i in range(4)
    ]


def test_training_aggregate_review_claim_binds_selected_capability() -> None:
    aggregate = {
        "git": "a" * 40,
        "aggregate_sha256": "b" * 64,
        "controller_packet_sha256": "c" * 64,
        "training_receipt_sha256": "d" * 64,
        "model_dataset_sha256": "e" * 64,
        "cell_count": 48,
        "decision": "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW",
        "selection": {
            "selection_sha256": "f" * 64,
            "selected_capability": {
                "surface": "play", "head": "ranking", "epoch": 8,
            },
        },
        "selected_ensemble": [{"seed": seed}
                              for seed in MODEL.TRAINING_SEEDS],
    }
    before = CTRL.expected_training_aggregate_review_claim(
        aggregate, "1" * 64)
    changed = copy.deepcopy(aggregate)
    changed["selection"]["selected_capability"]["head"] = "outcome"
    after = CTRL.expected_training_aggregate_review_claim(changed, "1" * 64)
    assert before["selected_capability"]["head"] == "ranking"
    assert after["selected_capability"]["head"] == "outcome"
    assert before != after
    assert before["report_rows_opened_by_training_review"] == 0


def test_report_packet_binds_runtime_and_only_review_authority(
        monkeypatch) -> None:
    runtime = {
        "host": "mini", "python": "3.14", "torch": "2.13",
        "numpy": "2.5", "device": "cpu", "cpu_threads": 1,
    }
    capability = {"surface": "play", "head": "ranking", "epoch": 8}
    ensemble = [{
        "seed": seed, "surface": "play", "head": "ranking", "epoch": 8,
        "checkpoint_path": f"checkpoint-{seed}.pt",
        "checkpoint_sha256": f"{seed + 1:064x}",
        "model_state_sha256": f"{seed + 101:064x}",
        "checkpoint_contract": {"seed": seed},
    } for seed in MODEL.TRAINING_SEEDS]
    training_packet = {
        "runtime_contract": {
            "host": "mini", "python": "3.14", "torch": "2.13",
            "numpy": "2.5", "device": "cpu",
        },
    }
    aggregate = {
        "selection": {"selected_capability": capability},
        "selected_ensemble": ensemble,
        "controller_packet_sha256": "1" * 64,
        "aggregate_sha256": "2" * 64,
        "model_dataset_sha256": "3" * 64,
    }
    dataset = {"examples": {"DESIGN": {"play": [{}]}}}
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: runtime)
    monkeypatch.setattr(
        CTRL, "_source_sha256s",
        lambda: {path: "4" * 64 for path in CTRL.SOURCE_PATHS})
    monkeypatch.setattr(CTRL, "_checkpoint_manifest",
                        lambda *_args: ensemble)
    monkeypatch.setattr(CTRL, "_report_manifest",
                        lambda *_args: [{"index": index, "split": "REPORT",
                                        "states": 128}
                                       for index in range(12, 16)])
    monkeypatch.setattr(CTRL.TRAIN, "state_balanced_prior",
                        lambda _values: [0.125] * 8)
    packet = CTRL.build_packet(
        git="a" * 40, training_packet=training_packet,
        training_aggregate=aggregate, training_aggregate_sha256="5" * 64,
        training_aggregate_review={"verdict": "PASS"}, dataset=dataset,
        label_packet=_label_packet(), label_controller_sha256="6" * 64,
        label_receipt_sha256="7" * 64)
    assert packet["runtime_contract"] == runtime
    assert packet["authority"]["one_report_execution_authorized"] is False
    assert packet["report_contract"][
        "retry_after_report_open_or_failure_authorized"] is False
    claim = CTRL.expected_review_claim(packet, "8" * 64)
    assert claim["one_report_execution_authorized"] is True
    assert claim["composition_authorized"] is False
    assert claim["report_open_admission_slot"].endswith(
        ".report-open.consumed.json")

    drifted = copy.deepcopy(training_packet)
    drifted["runtime_contract"]["host"] = "air"
    with pytest.raises(CTRL.ReportControllerRefused, match="runtime"):
        CTRL.build_packet(
            git="a" * 40, training_packet=drifted,
            training_aggregate=aggregate,
            training_aggregate_sha256="5" * 64,
            training_aggregate_review={"verdict": "PASS"}, dataset=dataset,
            label_packet=_label_packet(), label_controller_sha256="6" * 64,
            label_receipt_sha256="7" * 64)
