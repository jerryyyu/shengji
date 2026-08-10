from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import teacher_stage_c_fresh_report_controller as CTRL


def _state(*, split: str, cell: str, index: int, surface: str) -> dict:
    return {
        "state_id": f"{split}:{cell}:{index}",
        "seed": ({"DESIGN": 1_000_000, "CALIB": 2_000_000,
                  "REPORT": 3_000_000}[split] + index),
        "split": split,
        "cell_id": cell,
        "surface_type": surface,
        "selection_priority": f"{index:064x}",
    }


def _parents() -> tuple[dict, dict, list[dict]]:
    design = [_state(
        split="DESIGN", cell="design", index=index, surface="play")
        for index in range(1024)]
    calib = [_state(
        split="CALIB", cell="calib", index=index, surface="play")
        for index in range(512)]
    old_play = [_state(
        split="REPORT", cell="report-play", index=index, surface="play")
        for index in range(480)]
    old_bury = [_state(
        split="REPORT", cell="report-bury", index=10_000 + index,
        surface="bury") for index in range(32)]
    fresh_play = [_state(
        split="REPORT", cell="report-play", index=20_000 + index,
        surface="play") for index in range(491)]
    fresh_bury = [_state(
        split="REPORT", cell="report-bury", index=30_000 + index,
        surface="bury") for index in range(43)]
    packet = {"schedule": {"quota_cells": {"REPORT": [
        {"cell_id": "report-play", "quota": 480},
        {"cell_id": "report-bury", "quota": 32},
    ]}}}
    state_set = {
        "states": [*design, *calib, *old_play, *old_bury],
        "dataset_sha256": "8" * 64,
        "states_sha256": "9" * 64,
    }
    shards = [{"retained_states": [
        *old_play, *fresh_play, *old_bury, *fresh_bury]}]
    return packet, state_set, shards


def test_sealed_selection_uses_next_quota_without_state_or_seed_overlap() \
        -> None:
    packet, state_set, shards = _parents()
    sealed, selected = CTRL.sealed_selection(
        capture_packet=packet, state_set=state_set, shards=shards)
    assert len(selected) == 512
    assert sealed["fresh_report_surface_counts"] == {
        "play": 480, "bury": 32}
    assert sealed["fresh_report_min_spare_per_cell"] == 11
    assert sealed["state_id_overlap_with_original"] == 0
    assert sealed["deal_seed_overlap_with_original"] == 0
    assert sealed["effective_state_count"] == 2048
    assert selected[0]["state_id"] == "REPORT:report-bury:30000"
    assert selected[32]["state_id"] == "REPORT:report-play:20000"
    assert sealed["state_material_published"] is False
    assert sealed["teacher_labels_computed"] is False
    assert sealed["model_predictions_computed"] is False


def test_sealed_selection_refuses_a_rewritten_original_tranche() -> None:
    packet, state_set, shards = _parents()
    state_set = copy.deepcopy(state_set)
    report_play = [state for state in state_set["states"]
                   if state["cell_id"] == "report-play"]
    report_play[-1]["state_id"] = "REPORT:report-play:not-first-tranche"
    with pytest.raises(
            CTRL.FreshReportRefused, match="first frozen tranche"):
        CTRL.sealed_selection(
            capture_packet=packet, state_set=state_set, shards=shards)


def test_sealed_selection_refuses_old_seed_overlap_or_outcome_material() -> None:
    packet, state_set, shards = _parents()
    overlapped = copy.deepcopy(shards)
    fresh = next(state for state in overlapped[0]["retained_states"]
                 if state["state_id"] == "REPORT:report-play:20000")
    fresh["seed"] = state_set["states"][0]["seed"]
    with pytest.raises(CTRL.FreshReportRefused, match="overlap/uniqueness"):
        CTRL.sealed_selection(
            capture_packet=packet, state_set=state_set, shards=overlapped)

    leaked = copy.deepcopy(shards)
    fresh = next(state for state in leaked[0]["retained_states"]
                 if state["state_id"] == "REPORT:report-play:20000")
    fresh["signed_level_utility"] = 1.0
    with pytest.raises(CTRL.FreshReportRefused, match="label/outcome"):
        CTRL.sealed_selection(
            capture_packet=packet, state_set=state_set, shards=leaked)


def test_packet_publishes_digests_not_selected_state_identity(
        monkeypatch) -> None:
    capture, state_set, shards = _parents()
    capture.update({
        "external_sha256": CTRL.CAPTURE_PACKET_SHA256,
        "packet_sha256": "a" * 64,
        "producer": {"git": "b" * 40},
    })
    verification = {"verification_sha256": "c" * 64}
    review = {"schema": "review"}
    for index, shard in enumerate(shards):
        shard.update({
            "shard_index": 16 + index,
            "external_sha256": "d" * 64,
            "shard_sha256": "e" * 64,
            "retained_state_ids_sha256": "f" * 64,
        })
    monkeypatch.setattr(
        CTRL, "_capture_parents",
        lambda **kwargs: (capture, state_set, verification, review))
    monkeypatch.setattr(CTRL, "_report_shards", lambda *args: shards)
    monkeypatch.setattr(
        CTRL, "source_hashes", lambda: {
            path: "1" * 64 for path in CTRL.SOURCE_PATHS})
    monkeypatch.setattr(CTRL, "producer_identity", lambda **kwargs: {
        "git": "2" * 40, "tree_dirty": False, "promotable": True,
        "controller_script_sha256": "1" * 64,
    })
    packet = CTRL.build_packet(
        smoke=False, capture_packet_path=Path("capture"),
        state_set_path=Path("states"), verification_path=Path("verify"),
        state_set_review_record=Path("review"))
    encoded = json.dumps(packet, sort_keys=True)
    assert "REPORT:report-play:20000" not in encoded
    assert packet["sealed_selection"]["fresh_report_states"] == 512
    assert packet["authority"]["fresh_report_states_materialized"] is False
    claim = CTRL.expected_review_claim(packet, "3" * 64)
    assert claim["old_report_quarantined"] is True
    assert claim["one_v11_free_training_controller_freeze_authorized"] is True
    assert claim["training_authorized"] is False
    assert claim["report_open_authorized"] is False


def test_validate_packet_recomputes_seal_and_refuses_digest_mutation(
        monkeypatch, tmp_path: Path) -> None:
    capture, state_set, shards = _parents()
    capture.update({
        "external_sha256": CTRL.CAPTURE_PACKET_SHA256,
        "packet_sha256": "a" * 64,
        "producer": {"git": "b" * 40},
    })
    verification = {"verification_sha256": "c" * 64}
    review = {"schema": "review"}
    for index, shard in enumerate(shards):
        shard.update({
            "shard_index": 16 + index,
            "external_sha256": "d" * 64,
            "shard_sha256": "e" * 64,
            "retained_state_ids_sha256": "f" * 64,
        })
    sources = {path: "1" * 64 for path in CTRL.SOURCE_PATHS}
    monkeypatch.setattr(
        CTRL, "_capture_parents",
        lambda **kwargs: (capture, state_set, verification, review))
    monkeypatch.setattr(CTRL, "_report_shards", lambda *args: shards)
    monkeypatch.setattr(CTRL, "source_hashes", lambda: sources)
    monkeypatch.setattr(CTRL, "producer_identity", lambda **kwargs: {
        "git": "2" * 40, "tree_dirty": False, "promotable": True,
        "controller_script_sha256": "1" * 64,
    })
    packet = CTRL.build_packet(
        smoke=False, capture_packet_path=Path("capture"),
        state_set_path=Path("states"), verification_path=Path("verify"),
        state_set_review_record=Path("review"))
    path = tmp_path / "packet.json"
    path.write_bytes(CTRL.canonical_json(packet))
    digest = CTRL.sha256_file(path)
    assert CTRL.validate_packet(
        packet_path=path, expected_external_sha256=digest,
        state_set_review_record=Path("review")) == packet

    changed = copy.deepcopy(packet)
    changed["sealed_selection"]["fresh_report_state_ids_sha256"] = "0" * 64
    changed["sealed_selection"]["sealed_selection_sha256"] = CTRL.self_hash(
        changed["sealed_selection"], "sealed_selection_sha256")
    changed["packet_sha256"] = CTRL.self_hash(changed, "packet_sha256")
    path.write_bytes(CTRL.canonical_json(changed))
    with pytest.raises(CTRL.FreshReportRefused, match="recomputation"):
        CTRL.validate_packet(
            packet_path=path, expected_external_sha256=CTRL.sha256_file(path),
            state_set_review_record=Path("review"))
