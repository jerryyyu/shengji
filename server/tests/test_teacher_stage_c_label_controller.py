from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "teacher_stage_c_label_controller.py")
SPEC = importlib.util.spec_from_file_location("stage_c_label_controller", SCRIPT)
assert SPEC and SPEC.loader
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)

import teacher_stage_c_label_capacity as capacity  # noqa: E402

CAPTURE_PACKET = (
    Path(__file__).parents[1] / "runs/logs" /
    controller.CAPTURE_CTRL.PACKET_ID / "controller_packet.json"
)


def _state_set() -> dict:
    states = []
    surface_counts = {"DESIGN": 64, "CALIB": 32, "REPORT": 32}
    for split, total in controller.EXPECTED_SPLITS.items():
        bury = surface_counts[split]
        for index in range(total):
            surface = "bury" if index < bury else "play"
            if split == "REPORT" and index < 256:
                if index < 16:
                    stratum = "ordinary_anchor"
                elif index < 32:
                    stratum = "structured_point_void"
                elif index < 80:
                    stratum = "ordinary_anchor"
                elif index < 128:
                    stratum = "champion_uncertainty"
                elif index < 176:
                    stratum = "proposal_disagreement"
                elif index < 224:
                    stratum = "exact_late_eligible"
                else:
                    stratum = "point_banking_opportunity"
            else:
                stratum = "ordinary_anchor" if index % 4 == 0 else \
                    ("structured_point_void" if surface == "bury" else
                     "proposal_disagreement")
            states.append({
                "schema": "teacher-stage-c-replay-state-v1",
                "state_id": f"{split}:{index}",
                "split": split,
                "surface_type": surface,
                "stratum": stratum,
                "seed": {"DESIGN": 170_000_000,
                         "CALIB": 171_000_000,
                         "REPORT": 172_000_000}[split] + index,
                "seat": index % 4,
                "ply": 0 if surface == "bury" else index % 11,
                "candidates": [
                    {"cards": ["C2"], "sources": ["live_production_ballot"]},
                    {"cards": ["C3"], "sources": ["v11pair_top_proposal"]},
                    {"cards": ["C4"],
                     "sources": ["same_budget_random_diversifier"]},
                ],
                "selection_metadata": {
                    "selection_features_may_train_or_label": False,
                },
            })
    audit_ids = [state["state_id"] for state in states
                 if state["split"] == "REPORT"][:controller.EXPECTED_AUDIT]
    value = {
        "schema": controller.CAPTURE_CTRL.DATASET_SCHEMA,
        "run_id": controller.CAPTURE_RUN_ID,
        "git": controller.CAPTURE_SOURCE_GIT,
        "controller_packet_sha256": controller.CAPTURE_CONTROLLER_SHA256,
        "capture_receipt_sha256": "a" * 64,
        "complete": True,
        "state_count": controller.EXPECTED_STATES,
        "split_counts": controller.EXPECTED_SPLITS,
        "surface_counts": {
            "play": controller.EXPECTED_PLAY,
            "bury": controller.EXPECTED_BURY,
        },
        "report_audit_state_ids": audit_ids,
        "report_audit_state_ids_sha256": controller.sha256_bytes(
            controller.canonical_json(audit_ids)),
        "states": states,
        "states_sha256": controller.sha256_bytes(
            controller.canonical_json(states)),
        "terminal_disposition_replay_required": True,
        "state_set_review_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["dataset_sha256"] = controller.self_hash(value, "dataset_sha256")
    return value


def _verification(state_set_sha256: str) -> dict:
    value = {
        "schema": controller.CAPTURE_CTRL.VERIFICATION_SCHEMA,
        "run_id": controller.CAPTURE_RUN_ID,
        "git": controller.CAPTURE_SOURCE_GIT,
        "controller_packet_sha256": controller.CAPTURE_CONTROLLER_SHA256,
        "capture_receipt_sha256": "a" * 64,
        "schedule_sha256": "b" * 64,
        "status": "VERIFIED_STAGE_C_CAPTURE",
        "dataset_sha256": state_set_sha256,
        "states": controller.EXPECTED_STATES,
        "split_counts": controller.EXPECTED_SPLITS,
        "surface_counts": {
            "play": controller.EXPECTED_PLAY,
            "bury": controller.EXPECTED_BURY,
        },
        "replay_every_selected_state": True,
        "terminal_disposition_replay_deals": 750_000,
        "all_scan_dispositions_replay_authenticated": True,
        "state_set_review_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["verification_sha256"] = controller.self_hash(
        value, "verification_sha256")
    return value


def _write_inputs(root: Path, state_set: dict | None = None):
    state_set = state_set or _state_set()
    state_path = root / "state-set.json"
    state_path.write_bytes(controller.canonical_json(state_set))
    state_sha = controller.sha256_file(state_path)
    verification = _verification(state_sha)
    verification_path = root / "terminal-verification.json"
    verification_path.write_bytes(controller.canonical_json(verification))
    verification_sha = controller.sha256_file(verification_path)
    claim = controller.expected_state_set_review_claim(
        state_set, state_sha, verification, verification_sha)
    review_path = root / "review.txt"
    review_path.write_text(
        controller.STATE_SET_REVIEW_MARKER
        + json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n")
    return (state_path, state_sha, verification_path, verification_sha,
            review_path)


def _write_capacity_inputs(root: Path, inputs) -> tuple[Path, str, Path, str,
                                                               Path]:
    packet = capacity.build_packet(
        CAPTURE_PACKET, inputs[0], inputs[1], inputs[2], inputs[3], inputs[4],
        smoke=True)
    packet_path = root / "capacity-controller.json"
    packet_path.write_bytes(capacity.canonical_json(packet))
    packet_sha = capacity.sha256_file(packet_path)
    state_set = json.loads(inputs[0].read_text())
    label_schedule = capacity.CTRL.build_schedule(state_set)
    samples = []
    for descriptor in packet["preflight_schedule"]["samples"]:
        work = int(descriptor["expected_candidate_worlds"])
        samples.append({
            **descriptor,
            "status": "COMPLETE_OUTCOMES_DISCARDED",
            "candidate_worlds_attempted": work,
            "candidate_worlds_completed": work,
            "sampler": {
                "sampler_attempts": 1, "accepted_worlds": 1,
                "failed_worlds": 0, "rejected_worlds": 0,
                "impossible_worlds": 0, "overlap_discarded": 0,
                "duplicate_discarded": 0,
            },
            "elapsed_seconds": work / 1_000.0,
            "v11_load_seconds": 1.0,
            "reason_class": None,
            "reason_sha256": None,
            "outcome_tensor_returned": False,
            "outcomes_retained": False,
        })
    result = capacity.build_pass_or_hold_result(
        packet, packet_sha, "d" * 64, samples, 60.0, label_schedule)
    result_path = root / "capacity-result.json"
    result_path.write_bytes(capacity.canonical_json(result))
    result_sha = capacity.sha256_file(result_path)
    claim = capacity.expected_result_review_claim(result, result_sha)
    review_path = root / "capacity-result-review.txt"
    review_path.write_text(capacity.RESULT_REVIEW_MARKER + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n")
    return packet_path, packet_sha, result_path, result_sha, review_path


def test_label_lane_is_bound_to_capture_v7_not_v6() -> None:
    packet = controller.validate_capture_controller(CAPTURE_PACKET)
    assert packet["schema"] == "teacher-stage-c-capture-controller-v7"
    assert packet["run_id"] == controller.CAPTURE_RUN_ID
    assert packet["producer"]["git"] == controller.CAPTURE_SOURCE_GIT

    old = (Path(__file__).parents[1] / "runs/logs" /
           "teacher-v3-hard-tail-stage-c-capture-controller-v6" /
           "controller_packet.json")
    with pytest.raises(controller.ControllerRefused,
                       match="external SHA-256 drift"):
        controller.validate_capture_controller(old)


def test_v6_state_set_marker_cannot_authorize_v7_labels() -> None:
    log_root = controller.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        inputs = _write_inputs(Path(raw))
        claim = inputs[4].read_text().split(" ", 1)[1]
        inputs[4].write_text(
            "TEACHER_STAGE_C_STATE_SET_V6_REVIEW " + claim)
        with pytest.raises(controller.ControllerRefused,
                           match="must contain exactly one .*V7_REVIEW"):
            controller.validate_state_set(
                inputs[0], inputs[1], inputs[2], inputs[3], inputs[4])


def test_state_set_review_and_schedule_are_exact() -> None:
    log_root = controller.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        inputs = _write_inputs(Path(raw))
        state_set, verification, claim = controller.validate_state_set(
            inputs[0], inputs[1], inputs[2], inputs[3], inputs[4])
        assert claim["states"] == 2048
        assert verification["terminal_disposition_replay_deals"] == 750_000
        schedule = controller.build_schedule(state_set)
        assert schedule["shard_count"] == 16
        assert schedule["state_count"] == 2048
        assert schedule["audit_state_count"] == 256
        assert {shard["split"] for shard in schedule["shards"]} == {
            "DESIGN", "CALIB", "REPORT"}
        assert schedule["candidate_worlds"] <= \
            controller.BASE_MAX_CANDIDATE_WORLDS


def test_state_set_review_refuses_split_and_label_leak_mutations() -> None:
    log_root = controller.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        root = Path(raw)
        leaked = _state_set()
        leaked["states"][0]["label_action"] = {"index": 0}
        leaked["states_sha256"] = controller.sha256_bytes(
            controller.canonical_json(leaked["states"]))
        leaked["dataset_sha256"] = controller.self_hash(
            leaked, "dataset_sha256")
        inputs = _write_inputs(root, leaked)
        with pytest.raises(controller.ControllerRefused, match="identity/authority"):
            controller.validate_state_set(
                inputs[0], inputs[1], inputs[2], inputs[3], inputs[4])

        wrong = _state_set()
        wrong["report_audit_state_ids"][0] = wrong["states"][0]["state_id"]
        wrong["report_audit_state_ids_sha256"] = controller.sha256_bytes(
            controller.canonical_json(wrong["report_audit_state_ids"]))
        wrong["dataset_sha256"] = controller.self_hash(
            wrong, "dataset_sha256")
        other = root / "other"
        other.mkdir()
        inputs = _write_inputs(other, wrong)
        with pytest.raises(controller.ControllerRefused,
                           match="split/identity population"):
            controller.validate_state_set(
                inputs[0], inputs[1], inputs[2], inputs[3], inputs[4])


def test_packet_preserves_3x400_audit_and_report_seal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    log_root = controller.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        inputs = _write_inputs(Path(raw))
        monkeypatch.setattr(
            controller.CAPTURE_CTRL, "require_runtime_mode",
            lambda: {"environment": {"SHENGJI_FAST": "1",
                                     "SHENGJI_REQUIRE_VOIDS": "1"},
                     "experimental_sampler_flags": [],
                     "fast_engine": True,
                     "fast_router_sha256": "c" * 64,
                     "compiled_fast_binary_sha256": "d" * 64})
        capacity_inputs = _write_capacity_inputs(Path(raw), inputs)
        packet = controller.build_packet(
            CAPTURE_PACKET, inputs[0], inputs[1], inputs[2], inputs[3],
            inputs[4], *capacity_inputs, smoke=True)
        amendment = packet["audit_contract_amendment"]
        assert amendment["base_report_geometry"]["candidate_worlds"] == 1200
        assert amendment["successor_report_geometry"] == {
            "slot_roles": ["candidate0", "audit_selection_winner",
                           "frozen_label_choice"],
            "logical_actions": 3,
            "worlds": 400,
            "candidate_worlds": 1200,
            "duplicate_identities_consume_work": True,
            "identified_both_estimands": True,
        }
        assert packet["split_boundary"][
            "training_or_seed_selection_may_read_report"] is False
        claim = controller.expected_review_claim(packet, "e" * 64)
        assert claim["audit_report_actions"] == 3
        assert claim["audit_report_worlds"] == 400
        assert claim["one_label_execution_authorized"] is True
        assert claim["training_authorized"] is False
        assert claim["capacity_pass"] is True
        assert claim["capacity_packet_sha256"] == capacity_inputs[1]
        assert claim["capacity_result_sha256"] == capacity_inputs[3]


def test_packet_refuses_forged_capacity_result(
        monkeypatch: pytest.MonkeyPatch) -> None:
    log_root = controller.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        root = Path(raw)
        inputs = _write_inputs(root)
        monkeypatch.setattr(
            controller.CAPTURE_CTRL, "require_runtime_mode",
            lambda: {"environment": {"SHENGJI_FAST": "1",
                                     "SHENGJI_REQUIRE_VOIDS": "1"},
                     "experimental_sampler_flags": [],
                     "fast_engine": True,
                     "fast_router_sha256": "c" * 64,
                     "compiled_fast_binary_sha256": "d" * 64})
        capacity_inputs = list(_write_capacity_inputs(root, inputs))
        result = json.loads(capacity_inputs[2].read_text())
        result["projection"]["projected_fleet_hours"] += 1.0
        result["result_sha256"] = capacity.self_hash(result, "result_sha256")
        capacity_inputs[2].write_bytes(capacity.canonical_json(result))
        capacity_inputs[3] = capacity.sha256_file(capacity_inputs[2])
        claim = capacity.expected_result_review_claim(result, capacity_inputs[3])
        capacity_inputs[4].write_text(capacity.RESULT_REVIEW_MARKER + json.dumps(
            claim, sort_keys=True, separators=(",", ":")) + "\n")
        with pytest.raises(controller.ControllerRefused,
                           match="projection/gate drift"):
            controller.build_packet(
                CAPTURE_PACKET, inputs[0], inputs[1], inputs[2], inputs[3],
                inputs[4], *capacity_inputs, smoke=True)


def test_review_marker_is_exact_not_subset() -> None:
    log_root = controller.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        inputs = _write_inputs(Path(raw))
        state_set = json.loads(inputs[0].read_text())
        verification = json.loads(inputs[2].read_text())
        expected = controller.expected_state_set_review_claim(
            state_set, inputs[1], verification, inputs[3])
        forged = copy.deepcopy(expected)
        forged["labels_authorized"] = True
        inputs[4].write_text(
            controller.STATE_SET_REVIEW_MARKER
            + json.dumps(forged, sort_keys=True, separators=(",", ":")) + "\n")
        with pytest.raises(controller.ControllerRefused, match="PASS marker drift"):
            controller.validate_state_set(
                inputs[0], inputs[1], inputs[2], inputs[3], inputs[4])
