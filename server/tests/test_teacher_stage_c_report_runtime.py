from __future__ import annotations

import json
from pathlib import Path

import pytest

import teacher_stage_c_report_runtime as RUNTIME
from shengji.rl import stage_c_model as MODEL


def _packet() -> dict:
    return {
        "producer": {"git": "a" * 40},
        "packet_sha256": "b" * 64,
        "selected_capability": {
            "surface": "play", "head": "ranking", "epoch": 8,
        },
        "checkpoint_manifest": [],
        "report_manifest": [{
            "index": index, "split": "REPORT", "states": 128,
            "logical_path": f"report/shard-{index - 12:02d}.json",
            "sha256": f"{index + 1:064x}",
            "row_sha256s_sha256": f"{index + 101:064x}",
        } for index in range(12, 16)],
        "design_prior_distribution": [0.125] * 8,
    }


def test_report_open_slot_prevents_retry_after_evaluation_failure(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = tmp_path / "review.md"
    review.write_text("review\n")
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *_args, **_kwargs: (packet, {}, {}, {}))
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *_args, **_kwargs: {})
    calls = []

    def fail_after_slot(*_args, **_kwargs):
        calls.append("opened")
        raise RuntimeError("simulated failure after REPORT-open admission")

    monkeypatch.setattr(RUNTIME, "_report_examples", fail_after_slot)
    kwargs = {
        "packet_path": tmp_path / "packet.json",
        "expected_packet_sha256": "c" * 64,
        "review_record": review,
        "receipt_path": tmp_path / "receipt.json",
        "expected_receipt_sha256": "d" * 64,
        "out": tmp_path / RUNTIME.RESULT_PATH,
    }
    with pytest.raises(RuntimeError, match="simulated"):
        RUNTIME.evaluate(**kwargs)
    slot = tmp_path / RUNTIME.REPORT_OPEN_ADMISSION_PATH
    assert slot.is_file()
    assert json.loads(slot.read_text())[
        "retry_after_report_open_or_failure_authorized"] is False
    with pytest.raises(RUNTIME.ReportRuntimeRefused, match="existing output"):
        RUNTIME.evaluate(**kwargs)
    assert calls == ["opened"]


def test_packet_validation_does_not_touch_sealed_report_paths(
        monkeypatch, tmp_path) -> None:
    git = "a" * 40
    packet_sha = "1" * 64
    training_packet_sha = "2" * 64
    aggregate_sha = "3" * 64
    dataset_sha = "4" * 64
    label_sha = "5" * 64
    state_sha = "6" * 64
    capability = {"surface": "play", "head": "ranking", "epoch": 8}
    checkpoints = [{
        "seed": seed, "surface": "play", "head": "ranking", "epoch": 8,
        "checkpoint_path": f"checkpoint-{seed}.pt",
        "checkpoint_sha256": f"{seed + 1:064x}",
        "model_state_sha256": f"{seed + 101:064x}",
        "checkpoint_contract": {"seed": seed},
    } for seed in MODEL.TRAINING_SEEDS]
    ensemble = [{key: value for key, value in item.items()
                 if key != "checkpoint_contract"} for item in checkpoints]
    training_packet = {"schedule": {"cells": []}}
    aggregate = {
        "aggregate_sha256": "7" * 64,
        "selection": {"selected_capability": capability},
        "selected_ensemble": ensemble,
    }
    dataset = {
        "examples": {"DESIGN": {"play": [{}]}},
        "report_rows_included": False,
        "report_shard_files_opened": 0,
    }
    dataset["dataset_sha256"] = RUNTIME.TRAIN_CTRL.self_hash(
        dataset, "dataset_sha256")
    label_packet = {
        "parents": {"state_set": {
            "logical_path": "server/runs/logs/capture/states.json",
            "external_sha256": state_sha,
        }},
        "schedule": {"shards": [
            {
                "split": ("DESIGN" if index < 8 else
                          "CALIB" if index < 12 else "REPORT"),
                "local_shard": (index if index < 8 else
                                index - 8 if index < 12 else index - 12),
            }
            for index in range(16)
        ]},
    }
    state_set = {"states": [{} for _ in range(2048)]}
    sources = {"source.py": "8" * 64}
    runtime = {
        "host": "mini", "python": "3.14", "torch": "2.13",
        "numpy": "2.5", "device": "cpu", "cpu_threads": 1,
    }
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME.TRAIN_CTRL, "REPO", tmp_path)
    report_manifest = [{
        "index": index, "split": "REPORT", "states": 128,
        "logical_path": str(RUNTIME.TRAIN_CTRL._expected_label_shard_path(
            label_packet, index).relative_to(tmp_path)),
        "sha256": f"{index + 10:064x}",
        "row_sha256s_sha256": f"{index + 110:064x}",
    } for index in range(12, 16)]
    packet = {
        "schema": RUNTIME.CTRL.SCHEMA,
        "packet_id": RUNTIME.CTRL.PACKET_ID,
        "run_id": RUNTIME.CTRL.RUN_ID,
        "producer": {"git": git, "tree_dirty": False, "sources": sources},
        "runtime_contract": runtime,
        "parents": {
            "training_packet": {
                "logical_path": RUNTIME.TRAIN_CTRL.PACKET_PATH,
                "external_sha256": training_packet_sha,
            },
            "training_aggregate": {
                "logical_path": RUNTIME.TRAIN_RUNTIME.AGGREGATE_PATH,
                "external_sha256": aggregate_sha,
                "internal_sha256": aggregate["aggregate_sha256"],
            },
            "model_dataset": {
                "logical_path": RUNTIME.TRAIN_CTRL.DATASET_PATH,
                "external_sha256": dataset_sha,
            },
            "label_controller": {
                "logical_path": RUNTIME.LABEL._ctrl().CONTROLLER_PACKET_PATH,
                "external_sha256": label_sha,
            },
            "state_set": label_packet["parents"]["state_set"],
        },
        "selected_capability": capability,
        "checkpoint_manifest": checkpoints,
        "design_prior_distribution": [0.125] * 8,
        "report_manifest": report_manifest,
        "report_contract": {
            "surface": "play", "head": "ranking", "states": 480,
            "single_report_look": True,
            "model_score_tie_epsilon":
                RUNTIME.REPORT.MODEL_SCORE_TIE_EPSILON,
            "tie_break": "lowest candidate index within epsilon",
            "durable_report_open_admission_slot":
                RUNTIME.REPORT_OPEN_ADMISSION_PATH,
            "retry_after_report_open_or_failure_authorized": False,
            "report_cannot_change_surface_head_epoch_or_seed_population": True,
        },
        "authority": {
            "report_shard_files_opened": 0, "report_rows_opened": 0,
            "one_report_execution_authorized": False,
            "composition_authorized": False, "strength_claim": False,
            "production_promotion": False, "production_deployment": False,
        },
    }
    packet["packet_sha256"] = RUNTIME.self_hash(packet, "packet_sha256")
    packet_path = tmp_path / RUNTIME.CTRL.PACKET_PATH
    parent_values = {
        "training packet": (
            tmp_path / RUNTIME.TRAIN_CTRL.PACKET_PATH, training_packet),
        "training aggregate": (
            tmp_path / RUNTIME.TRAIN_RUNTIME.AGGREGATE_PATH, aggregate),
        "model dataset": (
            tmp_path / RUNTIME.TRAIN_CTRL.DATASET_PATH, dataset),
        "label controller": (
            tmp_path / RUNTIME.LABEL._ctrl().CONTROLLER_PACKET_PATH,
            label_packet),
        "state set": (
            tmp_path / label_packet["parents"]["state_set"]["logical_path"],
            state_set),
    }
    hashed = []

    def fake_sha(path: Path) -> str:
        logical = str(path)
        if "/report/shard-" in logical:
            raise AssertionError("sealed REPORT path touched before admission")
        hashed.append(logical)
        return packet_sha

    monkeypatch.setattr(RUNTIME, "sha256_file", fake_sha)
    monkeypatch.setattr(RUNTIME, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(RUNTIME, "load_json", lambda _path: packet)
    monkeypatch.setattr(RUNTIME, "_parent_file",
                        lambda _parent, label: parent_values[label])
    monkeypatch.setattr(RUNTIME, "_git",
                        lambda *args: "" if args[0] == "status" else git)
    monkeypatch.setattr(RUNTIME.CTRL, "_source_sha256s", lambda: sources)
    monkeypatch.setattr(RUNTIME.CTRL, "runtime_contract", lambda: runtime)
    monkeypatch.setattr(
        RUNTIME.TRAIN_RUNTIME, "_packet",
        lambda *_args, **_kwargs: (training_packet, dataset))
    expected_label_packet = dict(label_packet)
    expected_label_packet["external_sha256"] = label_sha
    monkeypatch.setattr(
        RUNTIME.TRAIN_CTRL, "_reviewed_upstream_label_packet",
        lambda *_args, **_kwargs: expected_label_packet)
    monkeypatch.setattr(RUNTIME, "_validate_checkpoint_manifest",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(RUNTIME.TRAIN, "state_balanced_prior",
                        lambda _examples: [0.125] * 8)
    reopened = RUNTIME._packet(packet_path, packet_sha)
    assert reopened == (packet, dataset, expected_label_packet, state_set)
    assert hashed == [str(packet_path)]


def test_report_examples_open_exact_four_shards_and_selected_surface(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    packet["parents"] = {"label_receipt": {
        "logical_path": "label-receipt.json", "external_sha256": "e" * 64,
    }}
    packet["report_contract"] = {"states": 480}
    label_packet = {
        "result_contract": {"receipt": "label-receipt.json"},
    }
    states = []
    shards = {}
    cursor = 0
    for item in packet["report_manifest"]:
        state_ids = []
        rows = []
        for local in range(128):
            surface = "play" if local < 120 else "bury"
            state_id = f"report-{cursor}"
            cursor += 1
            state_ids.append(state_id)
            states.append({"state_id": state_id, "surface_type": surface})
            rows.append({"state_id": state_id})
        row_hashes = [f"{item['index'] + 200:064x}"] * 128
        item["row_sha256s_sha256"] = RUNTIME.sha256_bytes(
            RUNTIME.canonical_json(row_hashes))
        shards[str(tmp_path / item["logical_path"])] = {
            "status": "COMPLETE", "refused_rows": 0,
            "state_ids": state_ids, "rows": rows,
            "row_sha256s": row_hashes,
        }
    opened_paths = []
    validated = []
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_parent_file",
        lambda _parent, _label: (tmp_path / "label-receipt.json", {}))
    monkeypatch.setattr(RUNTIME, "is_regular_unlinked", lambda _path: True)

    def fake_sha(path: Path) -> str:
        opened_paths.append(str(path))
        manifest = next(value for value in packet["report_manifest"]
                        if str(tmp_path / value["logical_path"]) == str(path))
        return manifest["sha256"]

    monkeypatch.setattr(RUNTIME, "sha256_file", fake_sha)
    monkeypatch.setattr(RUNTIME, "load_json",
                        lambda path: shards[str(path)])
    monkeypatch.setattr(RUNTIME.LABEL, "_load_v11", lambda: object())
    monkeypatch.setattr(
        RUNTIME.LABEL, "validate_shard",
        lambda _shard, **kwargs: validated.append(kwargs["index"]))
    monkeypatch.setattr(RUNTIME.CAPTURE, "replay_state", lambda state: state)
    monkeypatch.setattr(
        RUNTIME.MODEL, "materialize_example",
        lambda state, _row, _rnd: {
            "state_id": state["state_id"], "split": "REPORT",
            "surface_type": state["surface_type"],
        })
    monkeypatch.setattr(RUNTIME.TRAIN, "_validate_example",
                        lambda *_args, **_kwargs: None)
    examples, manifest = RUNTIME._report_examples(
        packet, label_packet, {"states": states})
    assert len(examples) == 480
    assert all(value["surface_type"] == "play" for value in examples)
    assert validated == list(range(12, 16))
    assert len(manifest) == 4
    assert opened_paths == [
        str(tmp_path / value["logical_path"])
        for value in packet["report_manifest"]
    ]


def test_member_predictions_reopen_exact_eight_frozen_models(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    packet["checkpoint_manifest"] = [{
        "checkpoint_path": f"checkpoint-{seed}.pt",
        "checkpoint_contract": {"seed": seed},
    } for seed in RUNTIME.MODEL.TRAINING_SEEDS]
    configured = []
    loaded = []
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME.TRAIN, "_configure_determinism",
        lambda seed: configured.append(seed))

    def load(path, *, expected_contract):
        loaded.append((str(path), expected_contract["seed"]))
        return {"state_dict": {"seed": expected_contract["seed"]}}

    monkeypatch.setattr(RUNTIME.TRAIN, "load_snapshot", load)

    class Net:
        def __init__(self, **_kwargs):
            self.seed = None

        def load_state_dict(self, state, *, strict):
            assert strict is True
            self.seed = state["seed"]

    monkeypatch.setattr(RUNTIME.MODEL, "StageCRankingOutcomeNet", Net)
    monkeypatch.setattr(
        RUNTIME.TRAIN, "predict_examples",
        lambda net, _examples: ([net.seed], [[net.seed]]))
    result = RUNTIME._member_predictions(packet, [{"state_id": "x"}])
    assert configured == [RUNTIME.MODEL.TRAINING_SEEDS[0]]
    assert len(loaded) == 8
    assert [value[0][0] for value in result] \
        == list(RUNTIME.MODEL.TRAINING_SEEDS)


def test_json_publication_cannot_overwrite_raced_destination(
        monkeypatch, tmp_path) -> None:
    path = tmp_path / "result.json"
    real_link = RUNTIME.os.link

    def raced_link(source, destination, *, follow_symlinks):
        path.write_bytes(b"other publisher")
        return real_link(source, destination,
                         follow_symlinks=follow_symlinks)

    monkeypatch.setattr(RUNTIME.os, "link", raced_link)
    with pytest.raises(RUNTIME.ReportRuntimeRefused, match="raced"):
        RUNTIME.publish_exclusive(path, {"value": 1})
    assert path.read_bytes() == b"other publisher"
    assert (tmp_path / "result.json.partial").is_file()
