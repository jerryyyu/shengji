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
            "decision": "DESIGN_HARD_TAIL_STAGE_C",
            "next_authority": "AUTHORIZE_STAGE_C_PACKET_REVIEW",
            "model_work_authorized_only_after_teacher_gate": True,
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


def _h0() -> dict:
    return {
        "schema": stage_c.H0_SCHEMA,
        "human_corpus": {"manifest_sha256": stage_c.HUMAN_CORPUS_SHA256},
        "split_contract": {
            "selected": {"DESIGN": [{}] * 384, "AUDIT": [{}] * 128}},
        "authority": {
            "score_free": True,
            "outcomes_computed": False,
            "counterfactual_execution_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
        },
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


def test_h0_audit_rows_remain_unconsumed(monkeypatch: pytest.MonkeyPatch,
                                         tmp_path: Path) -> None:
    path = tmp_path / "h0.json"
    path.write_text(json.dumps(_h0()))
    monkeypatch.setattr(stage_c, "sha256_file",
                        lambda candidate: stage_c.H0_SHA256
                        if Path(candidate) == path else "0" * 64)
    packet = stage_c.validate_h0(path, stage_c.H0_SHA256)
    assert len(packet["split_contract"]["selected"]["AUDIT"]) == 128
    packet["authority"]["labels_authorized"] = True
    path.write_text(json.dumps(packet))
    with pytest.raises(stage_c.StageCDesignError, match="identity/authority"):
        stage_c.validate_h0(path, stage_c.H0_SHA256)


def test_packet_authority_refuses_capture_or_training() -> None:
    expected = {"authority": {
        "design_review_authorized": True,
        "state_capture_authorized": False,
        "compute_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
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
    source = SCRIPT.read_text()
    assert '"continuation": "live-mc-s0-report-lcb-gold"' in source
    assert '"fallback": "live-mc-s0-report-lcb-gold-64-plus-64"' in source
    assert '"n30_may_screen_but_cannot_supply_hard_tail_target": True' in source
