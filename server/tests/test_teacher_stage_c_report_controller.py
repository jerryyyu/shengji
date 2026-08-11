from __future__ import annotations

import copy
import json

import pytest

import teacher_stage_c_report_controller as CTRL
from shengji.rl import stage_c_model as MODEL


def _state(index: int, *, surface: str = "play",
           stratum: str = "ordinary_anchor", candidates: int = 3) -> dict:
    return {
        "state_id": f"state-{index:04d}",
        "seed": 10_000 + index,
        "split": "REPORT",
        "surface_type": surface,
        "stratum": stratum,
        "candidates": [
            {"cards": [f"C{candidate + 2}"], "sources": ["captured"]}
            for candidate in range(candidates)
        ],
    }


def _fresh_states() -> list[dict]:
    return ([_state(index) for index in range(480)]
            + [_state(480 + index, surface="bury") for index in range(32)])


def test_candidate_world_ceiling_matches_frozen_label_recipe() -> None:
    ordinary = _state(0, candidates=5)
    hard = _state(1, stratum="proposal_disagreement", candidates=7)
    assert CTRL._candidate_world_ceiling(ordinary) == 5 * (256 + 256)
    assert CTRL._candidate_world_ceiling(hard) == 7 * 64 + 2 * 300


def test_report_schedule_is_balanced_digest_only_and_order_stable() -> None:
    states = _fresh_states()
    schedule = CTRL.build_report_schedule(states, surface="play")
    assert schedule["states"] == 480
    assert schedule["shard_count"] == 8
    assert [shard["state_count"] for shard in schedule["shards"]] == [60] * 8
    assert all("state_ids" not in shard for shard in schedule["shards"])
    assert schedule["state_material_published"] is False
    assert schedule["teacher_labels_computed"] is False
    assert schedule["model_predictions_computed"] is False
    assert schedule["candidate_world_ceiling"] == 480 * 3 * 512
    assert schedule["schedule_sha256"] == CTRL.self_hash(
        schedule, "schedule_sha256")
    assert CTRL.build_report_schedule(
        list(reversed(states)), surface="play") == schedule

    changed = copy.deepcopy(states)
    changed[0]["candidates"].append(
        {"cards": ["H9"], "sources": ["captured"]})
    mutated = CTRL.build_report_schedule(changed, surface="play")
    assert mutated["candidate_world_ceiling"] == (
        schedule["candidate_world_ceiling"] + 512)
    assert mutated["schedule_sha256"] != schedule["schedule_sha256"]


def test_report_schedule_rejects_missing_surface_row() -> None:
    with pytest.raises(CTRL.ReportControllerRefused,
                       match="selected-surface population"):
        CTRL.build_report_schedule(_fresh_states()[:-1], surface="bury")


def _reviewable_protected_packet() -> dict:
    capability = {
        "surface": "play", "head": "ranking", "epoch": 32,
        "curve_fraction": 1.0, "seeds": list(MODEL.TRAINING_SEEDS),
        "ensemble": "arithmetic mean of per-seed rank logits",
        "incumbent": "candidate0",
        "alternative": (
            "highest ensemble-mean rank logit among candidate indices 1+; "
            "ties choose the lowest index"),
        "activation": (
            "override candidate0 iff alternative ensemble rank logit minus "
            "candidate0 ensemble rank logit is strictly greater than 0.2"),
        "threshold": 0.2, "strict_greater_than_threshold": True,
        "fallback": "candidate0", "bury_behavior": "unchanged incumbent",
    }
    manifest = [{
        "seed": seed, "surface": "play", "head": "ranking", "epoch": 32,
        "curve_fraction": 1.0,
    } for seed in MODEL.TRAINING_SEEDS]
    diagnostics = {
        "screen_gate": {"decision": "REQUEST_EXTERNAL_CAPABILITY_REVIEW"},
        "selected_design": {}, "selected_calib": {},
    }
    packet = {
        "schema": CTRL.PROTECTED.SCHEMA,
        "packet_id": CTRL.PROTECTED.PACKET_ID,
        "producer": {
            "git": "65c2b3c56e4e26af92e5710652809df72071e06f",
            "tree_dirty": False,
        },
        "parent": {
            "training_aggregate_sha256":
                CTRL.PROTECTED.TRAINING_AGGREGATE_SHA256,
            "training_aggregate_internal_sha256":
                CTRL.PROTECTED.TRAINING_AGGREGATE_INTERNAL_SHA256,
            "terminal_decision": "SELECT_NONE", "report_rows_opened": 0,
        },
        "capability": capability,
        "checkpoint_manifest": manifest,
        "checkpoint_manifest_sha256": CTRL._manifest_hash(manifest),
        "threshold_selection": {
            "grid": list(CTRL.PROTECTED.THRESHOLD_GRID),
            "selection_split": "DESIGN", "selected_threshold": 0.2,
            "post_terminal_exploration": True,
            "calib_was_inspected_during_diagnosis": True,
            "calib_role": "diagnostic screen only, not fresh confirmation",
            "fresh_report_role": "only untouched final offline confirmation",
        },
        "diagnostics": diagnostics,
        "diagnostics_sha256": CTRL._manifest_hash(diagnostics),
        "authority": {
            "new_training_authorized": False,
            "training_retry_authorized": False,
            "report_rows_opened": 0, "report_open_authorized": False,
            "one_report_controller_freeze_authorized": False,
            "report_execution_authorized": False,
            "composition_authorized": False,
            "whole_game_screen_authorized": False,
            "strength_claim": False, "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = CTRL.self_hash(packet, "packet_sha256")
    return packet


def test_protected_capability_review_binds_policy_and_mutations(
        tmp_path) -> None:
    packet = _reviewable_protected_packet()
    packet_path = tmp_path / "capability.json"
    packet_path.write_bytes(CTRL.canonical_json(packet))
    external = CTRL.sha256_file(packet_path)
    review = tmp_path / "review.md"
    claim = CTRL.PROTECTED.expected_review_claim(packet, external)
    review.write_text(
        CTRL.PROTECTED.REVIEW_MARKER + json.dumps(claim, sort_keys=True) + "\n")
    aggregate = {
        "aggregate_sha256":
            CTRL.PROTECTED.TRAINING_AGGREGATE_INTERNAL_SHA256}
    actual, policy = CTRL.validate_protected_capability(
        packet_path=packet_path, packet_sha256=external,
        review_record=review, training_aggregate=aggregate)
    assert actual == packet
    assert policy["threshold"] == 0.2

    changed = copy.deepcopy(packet)
    changed["capability"]["strict_greater_than_threshold"] = False
    changed["packet_sha256"] = CTRL.self_hash(changed, "packet_sha256")
    packet_path.write_bytes(CTRL.canonical_json(changed))
    with pytest.raises(CTRL.ReportControllerRefused, match="policy drift"):
        CTRL.validate_protected_capability(
            packet_path=packet_path, packet_sha256=CTRL.sha256_file(packet_path),
            review_record=review, training_aggregate=aggregate)


def test_report_packet_binds_fresh_selection_and_no_v11_dependency(
        monkeypatch, tmp_path) -> None:
    runtime = {
        "host": "mini", "python": "3.14", "torch": "2.13",
        "numpy": "2.5", "device": "cpu", "cpu_threads": 1,
        "max_concurrent_label_shards": 8,
        "supervisor_heartbeat_seconds": 30,
        "supervisor_signal_contract": {
            "handled_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_label_workers_authorized": False,
        },
    }
    capability = {
        "surface": "play", "head": "ranking", "epoch": 32,
        "curve_fraction": 1.0, "seeds": list(MODEL.TRAINING_SEEDS),
        "ensemble": "arithmetic mean of per-seed rank logits",
        "incumbent": "candidate0",
        "alternative": (
            "highest ensemble-mean rank logit among candidate indices 1+; "
            "ties choose the lowest index"),
        "activation": (
            "override candidate0 iff alternative ensemble rank logit minus "
            "candidate0 ensemble rank logit is strictly greater than 0.2"),
        "threshold": 0.2, "strict_greater_than_threshold": True,
        "fallback": "candidate0", "bury_behavior": "unchanged incumbent",
    }
    ensemble = [{
        "seed": seed, "surface": "play", "head": "ranking", "epoch": 32,
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
        "controller_packet_sha256": "1" * 64,
        "aggregate_sha256": "2" * 64,
        "model_dataset_sha256": "3" * 64,
    }
    protected = {
        "capability": capability, "checkpoint_manifest": ensemble,
        "packet_sha256": "a" * 64,
        "checkpoint_manifest_sha256": "b" * 64,
        "diagnostics_sha256": "c" * 64,
        "parent": {"terminal_decision": "SELECT_NONE"},
    }
    policy = CTRL.protected_policy_contract(capability)
    dataset = {"examples": {"DESIGN": {"play": [{}]}}}
    sealed = {
        "sealed_selection_sha256": "4" * 64,
        "fresh_report_state_ids_sha256": "5" * 64,
        "fresh_report_state_material_sha256": "6" * 64,
        "fresh_report_states": 512,
    }
    fresh = {"packet_sha256": "7" * 64, "sealed_selection": sealed}
    fresh_review = {"schema": CTRL.FRESH.REVIEW_SCHEMA, "verdict": "PASS"}
    monkeypatch.setattr(CTRL, "runtime_contract", lambda: runtime)
    monkeypatch.setattr(
        CTRL, "_source_sha256s",
        lambda: {path: "8" * 64 for path in CTRL.SOURCE_PATHS})
    monkeypatch.setattr(CTRL, "_checkpoint_manifest",
                        lambda *_args: ensemble)
    monkeypatch.setattr(
        CTRL.TRAIN, "state_balanced_prior", lambda _examples: [0.125] * 8)
    review = tmp_path / "training-review.md"
    review.write_text("review\n")

    packet = CTRL.build_packet(
        git="a" * 40, training_packet=training_packet,
        evidence_repo=tmp_path, training_review_record=review,
        training_aggregate=aggregate, training_aggregate_sha256="9" * 64,
        protected_capability=protected,
        protected_capability_sha256="d" * 64,
        protected_capability_review={"verdict": "PASS"},
        policy_contract=policy, dataset=dataset,
        fresh_report=fresh, fresh_report_review=fresh_review,
        fresh_states=_fresh_states())

    assert set(packet["parents"]) == {
        "training_evidence", "training_packet", "training_aggregate",
        "protected_capability", "model_dataset",
        "fresh_report_selection",
    }
    assert "label_controller" not in packet["parents"]
    assert "label_receipt" not in packet["parents"]
    assert packet["parents"]["fresh_report_selection"][
        "sealed_selection_sha256"] == "4" * 64
    assert packet["report_schedule"]["shard_count"] == 8
    assert len(packet["commands"]["run_shards"]) == 8
    assert packet["commands"]["supervise"][1] == (
        "server/scripts/teacher_stage_c_report_supervisor.py")
    assert packet["report_contract"]["v11_checkpoint_loaded"] is False
    assert packet["report_contract"]["v11_candidates_reconstructed"] is False
    assert packet["protected_policy"] == policy
    assert packet["report_contract"]["activation_threshold"] == 0.2
    assert packet["report_contract"]["activation_is_strict"] is True
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
    claim = CTRL.expected_review_claim(packet, "b" * 64)
    assert claim["one_report_execution_authorized"] is True
    assert claim["teacher_labels_computed_before_review"] == 0
    assert claim["model_predictions_computed_before_review"] == 0
    assert claim["v11_checkpoint_loaded"] is False
    assert claim["protected_capability_packet_sha256"] == "d" * 64
    assert claim["protected_policy"] == policy
    assert claim["max_concurrent_label_shards"] == 8
    assert claim["supervisor_signal_contract"] == runtime[
        "supervisor_signal_contract"]
    assert claim["composition_authorized"] is False
