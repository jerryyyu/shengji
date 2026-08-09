from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "teacher_stage_c_design.py"
SPEC = importlib.util.spec_from_file_location("stage_c_design", SCRIPT)
assert SPEC and SPEC.loader
stage_c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_c)


def _adapter() -> dict:
    return {
        "schema": stage_c.ADAPTER_SCHEMA,
        "complete": True,
        "branch": "PASS",
        "terminal_audit_verdict": "PASS",
        "external_review_required": True,
        "compute_authorized": False,
        "bulk_label_authorized": False,
        "training_authorized": False,
        "production_promotion": False,
        "contract": {
            "packet_id": stage_c.PACKET_ID,
            "decision": "DESIGN_HARD_TAIL_STAGE_C",
            "next_authority": "AUTHORIZE_STAGE_C_PACKET_REVIEW",
            "model_work_authorized_only_after_teacher_gate": True,
            "live_parent": {
                "policy": stage_c.LIVE_PARENT_AUTH.CHAMPION_POLICY,
                "authenticator": stage_c.LIVE_PARENT_AUTH.SCHEMA,
                "must_reopen_at_packet_freeze": True,
            },
            "separate_gates_required": [
                "hard_tail_regret_upper_bound",
                "ordinary_anchor_regret_upper_bound",
                "exact_work_and_zero_fallbacks",
                "proposal_recall_vs_same_budget_random_diversity",
            ],
            "label_routing_required": {
                "ordinary_anchor": (
                    "cheap_proxy_only_under_passed_audit_contract"),
                "uncertainty_or_disagreement": "gold_report_lcb_or_deeper",
                "exact_eligible_late_ply": "information_set_legal_exact_late",
                "oracle_hidden_card_features_for_deployable_targets": False,
                "raw_candidate_tensor_preserved": True,
            },
        },
        "evidence": {
            "gate": {"sha256": "a" * 64},
            "supervisor_progress": {"sha256": "b" * 64},
        },
    }


def _h0_controller() -> dict:
    return {
        "score_free_preflight": {
            "cell_counts": {
                "DESIGN:play:lead:early:attacker": 384,
                "DESIGN:bury:bury:pre-play:defender": 36,
                "AUDIT:play:lead:early:attacker": 128,
                "AUDIT:bury:bury:pre-play:defender": 9,
            },
        },
        "inputs": {
            "live_parent": stage_c.LIVE_PARENT_AUTH.expected_parent(),
        },
    }


def _h0_review() -> dict:
    return {
        "schema": stage_c.H0_CONTROLLER.REVIEW_SCHEMA,
        "verdict": "PASS",
    }


def test_geometry_is_exactly_2048_and_split_disjoint() -> None:
    geometry = stage_c._split_geometry()
    assert {split: item["total"] for split, item in geometry.items()} == {
        "DESIGN": 1024, "CALIB": 512, "REPORT": 512}
    assert sum(item["total"] for item in geometry.values()) == 2048
    assert len({item["seed_start"] for item in geometry.values()}) == 3
    assert all(item["scan_deals"] == 250_000 for item in geometry.values())


def test_adapter_requires_design_only_pass(monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path) -> None:
    path = tmp_path / "adapter.json"
    path.write_text(json.dumps(_adapter()))
    monkeypatch.setattr(stage_c, "sha256_file",
                        lambda candidate: stage_c.ADAPTER_SHA256
                        if Path(candidate) == path else "0" * 64)
    assert stage_c.validate_adapter(path, stage_c.ADAPTER_SHA256)["branch"] == "PASS"
    bad = _adapter()
    bad["compute_authorized"] = True
    path.write_text(json.dumps(bad))
    with pytest.raises(stage_c.StageCDesignError, match="authority/decision"):
        stage_c.validate_adapter(path, stage_c.ADAPTER_SHA256)


def test_adapter_requires_exact_packet_and_live_parent(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "adapter.json"
    monkeypatch.setattr(stage_c, "sha256_file",
                        lambda candidate: stage_c.ADAPTER_SHA256
                        if Path(candidate) == path else "0" * 64)
    wrong_packet = _adapter()
    wrong_packet["contract"]["packet_id"] = "nearby-stage-c"
    path.write_text(json.dumps(wrong_packet))
    with pytest.raises(stage_c.StageCDesignError, match="authority/decision"):
        stage_c.validate_adapter(path, stage_c.ADAPTER_SHA256)

    wrong_parent = _adapter()
    wrong_parent["contract"]["live_parent"]["policy"] = "mc-strong"
    path.write_text(json.dumps(wrong_parent))
    with pytest.raises(stage_c.StageCDesignError, match="live-parent"):
        stage_c.validate_adapter(path, stage_c.ADAPTER_SHA256)


def test_passed_h0_controller_reopens_exactly_and_audit_stays_diagnostic(
        ) -> None:
    repo = Path(__file__).parents[2]
    packet, claim = stage_c.validate_h0_controller(
        repo / "server/runs/logs/"
        "human-v8-h0-counterfactual-controller-v2/controller_packet.json",
        stage_c.H0_CONTROLLER_SHA256,
        repo / "HANDOFF_REVIEW.md",
    )
    assert packet["schema"] == stage_c.H0_CONTROLLER_SCHEMA
    assert packet["score_free_preflight"]["rows_replayed"] == 557
    assert packet["score_free_preflight"]["worlds_sampled"] == 0
    assert claim["verdict"] == "PASS"
    assert claim["one_counterfactual_execution_authorized"] is True
    assert claim["labels_authorized"] is False


def test_h0_controller_authority_or_self_hash_mutation_refuses(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Path(__file__).parents[2]
    original = repo / "server/runs/logs/" \
        "human-v8-h0-counterfactual-controller-v2/controller_packet.json"
    packet = json.loads(original.read_text())
    packet["authority"]["labels_authorized"] = True
    mutated = tmp_path / "controller.json"
    mutated.write_text(json.dumps(packet))
    original_hash = stage_c.sha256_file
    monkeypatch.setattr(
        stage_c,
        "sha256_file",
        lambda path: (stage_c.H0_CONTROLLER_SHA256
                      if Path(path) == mutated else original_hash(path)),
    )
    with pytest.raises(
            stage_c.StageCDesignError, match="identity/preflight drift"):
        stage_c.validate_h0_controller(
            mutated, stage_c.H0_CONTROLLER_SHA256,
            repo / "HANDOFF_REVIEW.md")


def test_h0_controller_requires_exact_external_pass_marker(tmp_path: Path) -> None:
    repo = Path(__file__).parents[2]
    controller = repo / "server/runs/logs/" \
        "human-v8-h0-counterfactual-controller-v2/controller_packet.json"
    review = tmp_path / "review.md"
    review.write_text("no marker\n")
    with pytest.raises(stage_c.StageCDesignError,
                       match="review cannot reopen"):
        stage_c.validate_h0_controller(
            controller, stage_c.H0_CONTROLLER_SHA256, review)


def test_packet_authority_refuses_capture_or_training() -> None:
    expected = {"authority": {
        "score_free": True,
        "worlds_sampled": False,
        "outcomes_computed": False,
        "design_review_authorized": True,
        "capture_controller_implementation_authorized": False,
        "state_capture_authorized": False,
        "compute_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }}
    assert stage_c.packet_problems(expected, expected) == []
    widened = json.loads(json.dumps(expected))
    widened["authority"]["state_capture_authorized"] = True
    assert "Stage-C packet authority widened" in stage_c.packet_problems(
        widened, expected)


def test_underfilled_population_is_terminal_hold() -> None:
    geometry = stage_c._split_geometry()
    assert all(item["scan_deals"] > item["total"]
               for item in geometry.values())
    # The actual packet literal is tested through this invariant: there is no
    # adaptive scan extension or outcome-dependent replacement geometry.
    assert stage_c.SPLITS["REPORT"]["seed_start"] == 172_000_000


def test_hard_tail_target_cannot_fall_back_to_n30() -> None:
    geometry = stage_c._split_geometry()
    ceiling = stage_c._work_ceiling(geometry)
    assert ceiling["all_optional_mechanisms_max"] == 10_494_720
    assert ceiling["recursive_mc_continuation_rollouts"] == 0
    assert ceiling["ordinary_labels"] == 5_996_544
    assert ceiling["hard_tail_selection_and_fixed_report"] == 2_880_768
    assert ceiling["deeper_audit_reference"] == 1_015_808


def test_v3_packet_binds_executable_h0_and_conditional_mechanisms(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stage_c, "validate_adapter",
                        lambda *_args: _adapter())
    monkeypatch.setattr(
        stage_c, "validate_h0_controller",
        lambda *_args: (_h0_controller(), _h0_review()))
    monkeypatch.setattr(stage_c, "producer_identity", lambda **_kwargs: {
        "git": "c" * 40, "tree_dirty": False,
        "promotable": False, "script_sha256": "d" * 64,
    })
    packet = stage_c.build_packet(
        tmp_path / "adapter.json", stage_c.ADAPTER_SHA256,
        tmp_path / "h0-controller.json", stage_c.H0_CONTROLLER_SHA256,
        tmp_path / "review.md", smoke=True)

    assert packet["schema"] == "teacher-stage-c-hard-tail-design-v3"
    assert packet["packet_id"] == _adapter()["contract"]["packet_id"]
    parent = packet["authority_parent"]["live_parent"]
    assert parent["authenticator_schema"] == "live-champion-parent-v1"
    assert parent["reopened_at_packet_freeze"] is False
    assert parent["mode"] == "smoke-expected-payload-only"
    assert parent["payload"]["champion_policy"] == "mc-s0-report-lcb"
    conditional = packet["label_contract"]["point_banking"]["conditional_s4"]
    assert conditional == stage_c.S4_CONDITIONAL
    assert conditional["git"] == \
        "cad399294b888865a3bb79c47a9892200b896013"
    assert conditional["required_terminal_verdict"] == \
        "AUTHORIZE_CONFIRM_PACKET_REVIEW"
    assert packet["label_contract"]["exact_late"]["conditional_s3c"] == \
        stage_c.S3C_CONDITIONAL
    assert packet["label_contract"]["defensive_point_protection"][
        "conditional_s5"] == stage_c.S5_CONDITIONAL
    witnesses = packet["population_contract"]["human_witnesses"]
    assert witnesses["design_rows"] == 420
    assert witnesses["audit_rows_preserved"] == 137
    assert witnesses[
        "human_action_requires_counterfactual_support_before_use"] is True
    candidates = packet["candidate_contract"]
    assert candidates["human_action_union_on_fresh_2048"] is False
    assert candidates["max_unique_play_actions"] == 20
    assert candidates["max_unique_bury_actions"] == 33
    hard = packet["label_contract"]["uncertainty_disagreement_bury"]
    assert hard["rollout_continuation"] == "HeuristicBot"
    assert hard["recursive_mc_continuation"] is False
    assert hard["selection_worlds_all_candidates"] == 64
    assert hard[
        "report_worlds_fixed_selection_winner_and_candidate0"] == 300
    assert packet["work_contract"]["all_optional_mechanisms_max"] == \
        10_494_720
    review = packet["review_contract"]
    assert review["schema"] == stage_c.REVIEW_SCHEMA
    assert review["pass_authorizes"].startswith("implementation of one")
    assert "state capture" in review["pass_does_not_authorize"]

    gate = packet["gate_contract"]
    assert gate["audit_reference"]["selection_worlds"] == 128
    assert gate["audit_reference"]["report_worlds"] == 600
    assert gate["audit_reference"][
        "all_audit_worlds_disjoint_from_label_worlds"] is True
    assert "audit-reference minus label-choice" in \
        gate["audit_reference"]["regret"]
    assert "lower bound" in gate["proposal_recall"]["gate"]
    assert gate["proposal_recall"]["candidate_counts_equal_per_state"] is True


def test_real_packet_must_reopen_live_parent(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stage_c, "validate_adapter",
                        lambda *_args: _adapter())
    monkeypatch.setattr(
        stage_c, "validate_h0_controller",
        lambda *_args: (_h0_controller(), _h0_review()))
    monkeypatch.setattr(stage_c, "producer_identity", lambda **_kwargs: {
        "git": "c" * 40, "tree_dirty": False,
        "promotable": True, "script_sha256": "d" * 64,
    })
    with pytest.raises(stage_c.StageCDesignError,
                       match="requires --live-parent-repo"):
        stage_c.reopen_live_parent(smoke=False, repo=None, python=None)

    attestation = {
        "authenticator_schema": stage_c.LIVE_PARENT_AUTH.SCHEMA,
        "reopened_at_packet_freeze": True,
        "mode": "explicit-clean-evidence-checkout",
        "authenticator_git": "e" * 40,
        "authenticator_script_sha256": "f" * 64,
        "payload": stage_c.LIVE_PARENT_AUTH.expected_parent(),
    }
    packet = stage_c.build_packet(
        tmp_path / "adapter.json", stage_c.ADAPTER_SHA256,
        tmp_path / "h0-controller.json", stage_c.H0_CONTROLLER_SHA256,
        tmp_path / "review.md", smoke=False,
        live_parent_attestation=attestation)
    assert packet["authority_parent"]["live_parent"][
        "reopened_at_packet_freeze"] is True

    not_reopened = dict(attestation, reopened_at_packet_freeze=False)
    with pytest.raises(stage_c.StageCDesignError,
                       match="reopen attestation drift"):
        stage_c.build_packet(
            tmp_path / "adapter.json", stage_c.ADAPTER_SHA256,
            tmp_path / "h0-controller.json", stage_c.H0_CONTROLLER_SHA256,
            tmp_path / "review.md", smoke=False,
            live_parent_attestation=not_reopened)


def test_stage_c_refuses_h0_and_capture_parent_mismatch(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    controller = _h0_controller()
    controller["inputs"]["live_parent"] = {
        **controller["inputs"]["live_parent"],
        "champion_policy": "mc-strong",
    }
    monkeypatch.setattr(stage_c, "validate_adapter",
                        lambda *_args: _adapter())
    monkeypatch.setattr(
        stage_c, "validate_h0_controller",
        lambda *_args: (controller, _h0_review()))
    monkeypatch.setattr(stage_c, "producer_identity", lambda **_kwargs: {
        "git": "c" * 40, "tree_dirty": False,
        "promotable": False, "script_sha256": "d" * 64,
    })
    with pytest.raises(stage_c.StageCDesignError,
                       match="live parent differ"):
        stage_c.build_packet(
            tmp_path / "adapter.json", stage_c.ADAPTER_SHA256,
            tmp_path / "controller.json", stage_c.H0_CONTROLLER_SHA256,
            tmp_path / "review.md", smoke=True)
