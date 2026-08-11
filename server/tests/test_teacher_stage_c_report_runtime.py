from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import teacher_stage_c_report_runtime as RUNTIME


def _state(index: int) -> dict:
    return {
        "state_id": f"state-{index:04d}",
        "split": "REPORT",
        "surface_type": "play",
        "stratum": "ordinary_anchor",
        "candidates": [{"cards": ["C2"], "sources": ["captured"]}],
    }


def _packet(states: list[dict]) -> dict:
    shards = []
    for index in range(RUNTIME.CTRL.REPORT_SHARDS):
        population = states[index::RUNTIME.CTRL.REPORT_SHARDS]
        shards.append({
            "index": index,
            "state_count": len(population),
            "state_ids_sha256": RUNTIME.CTRL._manifest_hash(
                [state["state_id"] for state in population]),
            "candidate_world_ceiling": len(population) * 512,
            "result": RUNTIME.SHARD_PATHS[index],
        })
    schedule = {
        "schedule_sha256": "3" * 64,
        "shards": shards,
        "shard_count": 8,
        "candidate_world_ceiling": len(states) * 512,
    }
    return {
        "producer": {"git": "a" * 40},
        "selected_capability": {
            "surface": "play", "head": "ranking", "epoch": 8},
        "checkpoint_manifest": [],
        "parents": {"fresh_report_selection": {
            "sealed_selection_sha256": "2" * 64}},
        "report_schedule": schedule,
        "report_contract": {"states": len(states)},
    }


def test_admission_consumes_report_open_slot_before_any_label(
        monkeypatch, tmp_path) -> None:
    states = [_state(index) for index in range(8)]
    packet = _packet(states)
    review = tmp_path / "review.md"
    review.write_text("review\n")
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *_args, **_kwargs: (packet, {}, {}, {}, states))
    monkeypatch.setattr(RUNTIME, "_review_claim", lambda *_args: {})
    out = tmp_path / RUNTIME.RECEIPT_PATH
    receipt = RUNTIME.admit(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="1" * 64,
        review_record=review,
        fresh_report_review_record=review,
        state_set_review_record=review,
        out=out)
    assert receipt["report_open_admission_consumed"] is True
    assert receipt["teacher_labels_computed"] == 0
    assert receipt["model_predictions_computed"] == 0
    assert receipt["v11_checkpoint_loaded"] is False
    assert (tmp_path / RUNTIME.ADMISSION_PATH).is_file()
    assert (tmp_path / RUNTIME.REPORT_OPEN_ADMISSION_PATH).is_file()
    assert receipt["admission_slot_sha256"] == RUNTIME.sha256_file(
        tmp_path / RUNTIME.ADMISSION_PATH)
    assert receipt["report_open_admission_slot_sha256"] \
        == RUNTIME.sha256_file(tmp_path / RUNTIME.REPORT_OPEN_ADMISSION_PATH)

    with pytest.raises(RUNTIME.ReportRuntimeRefused,
                       match="existing output"):
        RUNTIME.admit(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="1" * 64,
            review_record=review,
            fresh_report_review_record=review,
            state_set_review_record=review,
            out=out)


@pytest.mark.parametrize(
    "occupied",
    (
        "slot", "slot.partial", "report-slot", "report-slot.partial",
        "receipt", "receipt.partial",
    ),
)
def test_report_admission_preflights_all_three_outputs_before_packet_open(
        monkeypatch, tmp_path: Path, occupied: str) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    slot = (tmp_path / RUNTIME.ADMISSION_PATH).resolve()
    report_slot = (tmp_path / RUNTIME.REPORT_OPEN_ADMISSION_PATH).resolve()
    receipt = (tmp_path / RUNTIME.RECEIPT_PATH).resolve()
    paths = {
        "slot": slot,
        "slot.partial": Path(str(slot) + ".partial"),
        "report-slot": report_slot,
        "report-slot.partial": Path(str(report_slot) + ".partial"),
        "receipt": receipt,
        "receipt.partial": Path(str(receipt) + ".partial"),
    }
    paths[occupied].parent.mkdir(parents=True, exist_ok=True)
    paths[occupied].write_text("occupied\n")
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *args, **kwargs: pytest.fail(
            "REPORT packet opened before admission preflight"))

    with pytest.raises(RUNTIME.ReportRuntimeRefused, match="existing output"):
        RUNTIME.admit(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="1" * 64,
            review_record=tmp_path / "review.md",
            fresh_report_review_record=tmp_path / "fresh-review.md",
            state_set_review_record=tmp_path / "state-review.md",
            out=receipt)
    if occupied in {"receipt", "receipt.partial"}:
        assert not slot.exists()
        assert not report_slot.exists()


def test_run_shard_labels_captured_tensor_without_loading_v11(
        monkeypatch, tmp_path) -> None:
    state = _state(0)
    packet = _packet([state])
    packet["report_schedule"]["shards"][0]["result"] = \
        RUNTIME.SHARD_PATHS[0]
    review = tmp_path / "review.md"
    review.write_text("review\n")
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *_args, **_kwargs: (packet, {}, {}, {}, [state]))
    monkeypatch.setattr(RUNTIME, "_review_claim", lambda *_args: {})
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *_args: {})
    monkeypatch.setattr(
        RUNTIME, "_shard_states",
        lambda _packet, _states, index: [state] if index == 0 else [])
    monkeypatch.setattr(
        RUNTIME, "_consume_shard_slot", lambda *_args: "4" * 64)
    monkeypatch.setattr(RUNTIME.CAPTURE, "replay_state", lambda value: value)
    monkeypatch.setattr(
        RUNTIME.LABEL, "_load_v11",
        lambda: (_ for _ in ()).throw(AssertionError("V11 loaded")))
    row = {
        "status": "COMPLETE", "state_id": state["state_id"],
        "row_sha256": "5" * 64,
    }
    monkeypatch.setattr(
        RUNTIME.LABEL, "label_replayed_state",
        lambda *_args, **_kwargs: copy.deepcopy(row))
    monkeypatch.setattr(
        RUNTIME.LABEL, "validate_label_row", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        RUNTIME.LABEL, "_work_from_rows", lambda _rows: {
            "candidate_worlds_attempted": 512,
            "candidate_worlds_completed": 512,
            "sampler_attempts": 512,
            "accepted_worlds": 512,
        })
    out = tmp_path / RUNTIME.SHARD_PATHS[0]
    result = RUNTIME.run_shard(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="1" * 64,
        review_record=review,
        fresh_report_review_record=review,
        state_set_review_record=review,
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="6" * 64,
        shard_index=0, progress_every=1, out=out)
    assert result["status"] == "COMPLETE"
    assert result["v11_checkpoint_loaded"] is False
    assert result["audit_folds_computed"] is False
    assert result["candidate_world_ceiling_respected"] is True
    assert out.is_file()

    monkeypatch.setattr(
        RUNTIME, "_validate_shard_slot", lambda *_args, **_kwargs: None)
    RUNTIME.validate_shard(
        result, packet=packet, states=[state], packet_sha256="1" * 64,
        receipt_sha256="6" * 64, index=0)
    mutated = copy.deepcopy(result)
    mutated["v11_checkpoint_loaded"] = True
    mutated["shard_sha256"] = RUNTIME.self_hash(
        mutated, "shard_sha256")
    with pytest.raises(RUNTIME.ReportRuntimeRefused, match="identity drift"):
        RUNTIME.validate_shard(
            mutated, packet=packet, states=[state],
            packet_sha256="1" * 64, receipt_sha256="6" * 64, index=0)


def test_evaluate_closes_on_any_label_refusal_without_model_look(
        monkeypatch, tmp_path) -> None:
    states = [_state(index) for index in range(8)]
    packet = _packet(states)
    review = tmp_path / "review.md"
    review.write_text("review\n")
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *_args, **_kwargs: (packet, {}, {}, {}, states))
    monkeypatch.setattr(
        RUNTIME, "_receipt",
        lambda *_args, **_kwargs: {
            "report_open_admission_slot_sha256": "7" * 64})
    monkeypatch.setattr(
        RUNTIME, "validate_shard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        RUNTIME, "_member_predictions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model inference ran after label refusal")))

    paths = []
    for index, logical in enumerate(RUNTIME.SHARD_PATHS):
        path = tmp_path / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": ("REFUSED_INCOMPLETE_NO_REPORT_UTILITY"
                       if index == 0 else "COMPLETE"),
            "refused_rows": 1 if index == 0 else 0,
            "state_ids": [states[index]["state_id"]],
            "state_ids_sha256": RUNTIME.CTRL._manifest_hash(
                [states[index]["state_id"]]),
            "rows": [{"row_sha256": f"{index + 10:064x}"}],
            "row_sha256s": [f"{index + 10:064x}"],
            "shard_sha256": f"{index + 20:064x}",
            "work": {
                "candidate_worlds_attempted": 0,
                "candidate_worlds_completed": 0,
                "sampler_attempts": 0,
                "accepted_worlds": 0,
            },
        }
        path.write_text(json.dumps(payload))
        paths.append(path)
    out = tmp_path / RUNTIME.RESULT_PATH
    result = RUNTIME.evaluate(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="1" * 64,
        review_record=review,
        fresh_report_review_record=review,
        state_set_review_record=review,
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="6" * 64,
        shard_paths=paths, out=out)
    assert result["decision"] == "SELECT_NONE_REPORT_LABEL_REFUSAL"
    assert result["evaluation"] is None
    assert result["composition_packet_review_authorized"] is False
    assert result["report_label_refusals"] == 1
    assert result["v11_checkpoint_loaded"] is False
    assert out.is_file()


def test_parser_requires_fresh_and_state_review_records() -> None:
    parser = RUNTIME.parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "admit", "--expected-git", "a", "--controller-packet", "p",
            "--expected-controller-packet-sha256", "b",
            "--controller-review-record", "r", "--out", "o",
        ])
