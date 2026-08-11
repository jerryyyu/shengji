from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path

import pytest

import teacher_stage_c_expansion_controller as CTRL
import teacher_stage_c_label_runtime as LABEL_RUNTIME


def _state(*, split: str, surface: str, index: int) -> dict:
    return {
        "state_id": f"{split}:{surface}:{index:05d}",
        "split": split,
        "surface_type": surface,
        "stratum": "ordinary_anchor",
        "candidates": [{"cards": ["C2"], "sources": []}],
    }


def _selection() -> dict:
    states = []
    reused = []
    new = []
    report = []
    surfaces = {
        "DESIGN": {"play": 5_120, "bury": 512},
        "CALIB": {"play": 1_280, "bury": 128},
        "REPORT": {"play": 480, "bury": 32},
    }
    originals = {
        "DESIGN": {"play": 960, "bury": 64},
        "CALIB": {"play": 480, "bury": 32},
    }
    for split, counts in surfaces.items():
        for surface, count in counts.items():
            for index in range(count):
                value = _state(split=split, surface=surface, index=index)
                states.append(value)
                if split == "REPORT":
                    report.append(value["state_id"])
                elif index < originals[split][surface]:
                    reused.append(value["state_id"])
                else:
                    new.append(value["state_id"])
    return {
        "states": states,
        "states_sha256": CTRL.manifest_hash(states),
        "selection_sha256": "1" * 64,
        "reused_training_state_ids": sorted(reused),
        "reused_training_state_ids_sha256": CTRL.manifest_hash(
            sorted(reused)),
        "new_label_state_ids": sorted(new),
        "new_label_state_ids_sha256": CTRL.manifest_hash(sorted(new)),
        "sealed_report_state_ids_sha256": CTRL.manifest_hash(sorted(report)),
    }


def test_training_state_set_does_not_publish_sealed_report(
        monkeypatch) -> None:
    monkeypatch.setattr(CTRL, "_git", lambda *_args, **_kwargs: "a" * 40)
    selection = _selection()
    value = CTRL.build_training_state_set(
        selection=selection,
        evidence_repo=CTRL.REPO,
        capture_state_set={"dataset_sha256": "b" * 64},
    )

    assert value["state_count"] == 7_040
    assert len(value["reused_training_state_ids"]) == 1_536
    assert len(value["new_label_state_ids"]) == 5_504
    assert value["sealed_report_manifest"]["states"] == 512
    assert value["sealed_report_manifest"][
        "state_material_published"] is False
    encoded = json.dumps(value, sort_keys=True)
    assert "REPORT:play:" not in encoded
    assert "REPORT:bury:" not in encoded


def test_expanded_schedule_covers_only_new_design_and_calib() -> None:
    selection = _selection()
    state_set = {
        "states": [state for state in selection["states"]
                   if state["split"] != "REPORT"],
        "new_label_state_ids": selection["new_label_state_ids"],
    }
    schedule = CTRL.build_schedule(state_set)

    assert schedule["shard_count"] == 16
    assert schedule["state_count"] == 5_504
    assert schedule["reused_label_states_not_recomputed"] == 1_536
    assert schedule["report_states_scheduled"] == 0
    assert [shard["state_count"] for shard in schedule["shards"]] == (
        [384] * 12 + [224] * 4)
    assert schedule["candidate_worlds"] == 5_504 * 512
    scheduled = [state_id for shard in schedule["shards"]
                 for state_id in shard["state_ids"]]
    assert len(scheduled) == len(set(scheduled)) == 5_504
    assert set(scheduled) == set(selection["new_label_state_ids"])


def test_review_claim_grants_only_one_label_execution() -> None:
    packet = {
        "producer": {"git": "a" * 40,
                     "controller_script_sha256": "b" * 64},
        "packet_sha256": "c" * 64,
        "parents": {"state_set": {
            "external_sha256": "d" * 64,
            "internal_sha256": "e" * 64,
        }},
        "schedule": {
            "schedule_sha256": "f" * 64,
            "candidate_worlds": 123,
            "sampler_attempt_cap": 456,
        },
        "runtime_sources": {
            "server/scripts/teacher_stage_c_expanded_label_supervisor.py":
                "1" * 64,
        },
        "supervisor_contract": {
            "max_concurrent_shards": 8,
            "heartbeat_seconds": 30,
        },
    }
    claim = CTRL.expected_review_claim(packet, "0" * 64)
    assert claim["one_label_execution_authorized"] is True
    assert claim["training_authorized"] is False
    assert claim["report_open_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_promotion"] is False


def test_frozen_verify_rebuilds_exact_canonical_artifacts(
        monkeypatch) -> None:
    with tempfile.TemporaryDirectory(
            dir=CTRL.REPO / "server/runs/logs") as raw:
        root = Path(raw)
        state_path = root / "state-set.json"
        packet_path = root / "packet.json"
        state_set = {"state_count": 7_040, "dataset_sha256": "a" * 64}
        packet = {
            "schedule": {"state_count": 5_504},
            "producer": {
                "git": "b" * 40,
                "controller_script_sha256": "c" * 64,
            },
            "parents": {"state_set": {
                "external_sha256": "d" * 64,
                "internal_sha256": "a" * 64,
            }},
            "runtime_sources": {
                "server/scripts/teacher_stage_c_expanded_label_supervisor.py":
                    "e" * 64,
            },
            "supervisor_contract": {},
            "packet_sha256": "f" * 64,
        }
        state_path.write_bytes(CTRL.canonical_json(state_set))
        packet_path.write_bytes(CTRL.canonical_json(packet))
        monkeypatch.setattr(
            CTRL, "STATE_SET_PATH", str(state_path.relative_to(CTRL.REPO)))
        monkeypatch.setattr(
            CTRL, "CONTROLLER_PACKET_PATH",
            str(packet_path.relative_to(CTRL.REPO)))
        monkeypatch.setattr(
            CTRL, "_rebuild_state_set",
            lambda **_kwargs: (state_set, {}, {}, {}))
        monkeypatch.setattr(
            CTRL, "build_packet", lambda **_kwargs: packet)

        rebuilt = CTRL.verify_frozen(
            evidence_repo=CTRL.REPO,
            state_set_review_record=state_path,
            fresh_report_review_record=packet_path,
            state_set_path=state_path,
            expected_state_set_sha256=CTRL.sha256_file(state_path),
            packet_path=packet_path,
            expected_packet_sha256=CTRL.sha256_file(packet_path),
            smoke=True)
        assert rebuilt == (state_set, packet)

        state_path.write_bytes(CTRL.canonical_json({
            "state_count": 7_039,
            "dataset_sha256": "a" * 64,
        }))
        with pytest.raises(
                CTRL.ExpansionControllerRefused,
                match="state-set recomputation drift"):
            CTRL.verify_frozen(
                evidence_repo=CTRL.REPO,
                state_set_review_record=state_path,
                fresh_report_review_record=packet_path,
                state_set_path=state_path,
                expected_state_set_sha256=CTRL.sha256_file(state_path),
                packet_path=packet_path,
                expected_packet_sha256=CTRL.sha256_file(packet_path),
                smoke=True)


def test_expanded_aggregate_uses_completion_gate_not_audit(
        monkeypatch) -> None:
    class FakeCtrl:
        RUN_ID = "expanded-test"
        AGGREGATE_SCHEMA = "expanded-aggregate-test"
        LABEL_SHARDS = 1
        EXPECTED_STATES = 1
        TRAINING_LABEL_STATES = 1
        REUSED_LABEL_STATES = 2
        SEALED_REPORT_STATES = 3
        COMPUTE_FIDELITY_GATE = False

        sha256_file = staticmethod(
            lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())

    with tempfile.TemporaryDirectory(
            dir=LABEL_RUNTIME.REPO / "server/runs/logs") as raw:
        root = Path(raw)
        packet_path = root / "controller.json"
        receipt_path = root / "receipt.json"
        review = root / "review.txt"
        checkpoint = root / "v11.npz"
        shard_path = root / "design.json"
        aggregate_path = root / "aggregate.json"
        for path in (packet_path, receipt_path, review, checkpoint):
            path.write_text("fixture\n")
        shard_path.write_text(json.dumps({
            "shard_index": 0,
            "split": "DESIGN",
            "rows": [{"state_id": "DESIGN:new", "status": "COMPLETE"}],
            "row_sha256s": ["1" * 64],
        }) + "\n")
        packet = {
            "producer": {"git": "f" * 40},
            "parents": {"state_set": {"external_sha256": "c" * 64}},
            "schedule": {"schedule_sha256": "d" * 64},
            "result_contract": {
                "aggregate": str(aggregate_path.relative_to(
                    LABEL_RUNTIME.REPO)),
                "shards": [str(shard_path.relative_to(LABEL_RUNTIME.REPO))],
                "max_candidate_worlds": 0,
                "max_sampler_attempts": 0,
            },
        }
        state_set = {"states": [{"state_id": "DESIGN:new"}]}
        work = {
            "candidate_worlds_attempted": 0,
            "candidate_worlds_completed": 0,
            "sampler_attempts": 0,
            "accepted_worlds": 0,
        }
        monkeypatch.setattr(LABEL_RUNTIME, "_ctrl", lambda: FakeCtrl)
        monkeypatch.setattr(
            LABEL_RUNTIME, "_controller_packet",
            lambda *_args, **_kwargs: packet)
        monkeypatch.setattr(
            LABEL_RUNTIME, "_validated_parents",
            lambda *_args, **_kwargs: (state_set, {}))
        monkeypatch.setattr(
            LABEL_RUNTIME, "_receipt", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(LABEL_RUNTIME, "_load_v11", lambda: object())
        monkeypatch.setattr(
            LABEL_RUNTIME, "validate_shard", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            LABEL_RUNTIME, "_work_from_rows", lambda _rows: work)
        monkeypatch.setattr(
            LABEL_RUNTIME, "_audit_gate",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("expanded aggregate must not reopen audit")))
        monkeypatch.setattr(
            LABEL_RUNTIME.CAPTURE, "V11_PATH",
            checkpoint.relative_to(LABEL_RUNTIME.REPO))
        monkeypatch.setattr(
            LABEL_RUNTIME.CAPTURE, "V11_SHA256",
            FakeCtrl.sha256_file(checkpoint))

        result = LABEL_RUNTIME.aggregate(
            packet_path=packet_path, expected_packet_sha256="b" * 64,
            receipt_path=receipt_path, expected_receipt_sha256="e" * 64,
            controller_review_record=review,
            state_set_review_record=review,
            shard_paths=[shard_path], out=aggregate_path)

        assert result["model_packet_review_authorized"] is True
        assert result["fidelity_gate"]["fidelity_recomputed"] is False
        assert result["design_calib_manifest"]["states"] == 1
        assert result["design_calib_manifest"][
            "reused_labels_not_in_shards"] == 2
        assert result["sealed_report_manifest"]["states"] == 3
