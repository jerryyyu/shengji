#!/usr/bin/env python3
"""Freeze the no-compute Teacher Stage-C hard-tail design contract.

This tool consumes the independently verified T1 terminal adapter and the
score-free H0 human-action packet.  It emits experiment geometry only: fresh
seed blocks, split/stratum quotas, candidate sources, label routing, gates and
authority.  It never captures a state, samples a world, labels an action,
trains a model or promotes a policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT_AUTH  # noqa: E402


SCHEMA = "teacher-stage-c-hard-tail-design-v2"
# The terminal adapter grants this literal packet identity.  A previous draft
# silently dropped the word "design" and therefore did not consume its parent
# authority exactly even though no compute had started.
PACKET_ID = "teacher-v3-hard-tail-stage-c-design-v1"
ADAPTER_SCHEMA = "teacher-v3-terminal-adapter-v2"
ADAPTER_SHA256 = "56ccefbd62d9ea2aef30a4c6e54e11a0d2231e464f129e754b84b3488f1c2442"
H0_SCHEMA = "human-h0-counterfactual-design-v1"
H0_SHA256 = "9ff160a9bc54a30daa85a07b29440f5c4cdd1c8feb4574f81c102158e46247d3"
HUMAN_CORPUS_SHA256 = "b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553"
S4_CONDITIONAL = {
    "run_id": "s4-point-banking-state-screen-161m-v2",
    "git": "1b35fb7c6234fb6022181b54ce8210c796cc35c3",
    "states_sha256": "4538be8573a4d4bcf50524afe83c5dac25c5269b3ed95ab15f645343d0ff6b5f",
    "use_requires_separate_terminal_pass": True,
    "required_terminal_verdict": "AUTHORIZE_FULL_GAME_PACKET_REVIEW",
    "terminal_screen_sha256_must_bind_at_execution": True,
}

SPLITS = {
    "DESIGN": {
        "seed_start": 170_000_000,
        "scan_deals": 250_000,
        "play": {
            "ordinary_anchor": 240,
            "champion_uncertainty": 240,
            "proposal_disagreement": 240,
            "exact_late_eligible": 160,
            "point_banking_opportunity": 80,
        },
        "bury": {"ordinary_anchor": 32, "structured_point_void": 32},
    },
    "CALIB": {
        "seed_start": 171_000_000,
        "scan_deals": 250_000,
        "play": {
            "ordinary_anchor": 120,
            "champion_uncertainty": 120,
            "proposal_disagreement": 120,
            "exact_late_eligible": 80,
            "point_banking_opportunity": 40,
        },
        "bury": {"ordinary_anchor": 16, "structured_point_void": 16},
    },
    "REPORT": {
        "seed_start": 172_000_000,
        "scan_deals": 250_000,
        "play": {
            "ordinary_anchor": 120,
            "champion_uncertainty": 120,
            "proposal_disagreement": 120,
            "exact_late_eligible": 80,
            "point_banking_opportunity": 40,
        },
        "bury": {"ordinary_anchor": 16, "structured_point_void": 16},
    },
}


class StageCDesignError(RuntimeError):
    """A prerequisite or frozen design invariant is not exact."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise StageCDesignError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageCDesignError(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    if dirty and not smoke:
        raise StageCDesignError("real Stage-C freeze refuses a dirty tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "promotable": not smoke,
        "script_sha256": sha256_file(__file__),
    }


def validate_adapter(path: Path, expected_sha256: str) -> dict:
    if expected_sha256 != ADAPTER_SHA256 or sha256_file(path) != ADAPTER_SHA256:
        raise StageCDesignError("Teacher terminal adapter SHA-256 drift")
    adapter = _load_json(path)
    contract = adapter.get("contract", {})
    if (adapter.get("schema") != ADAPTER_SCHEMA
            or adapter.get("complete") is not True
            or adapter.get("branch") != "PASS"
            or adapter.get("terminal_audit_verdict") != "PASS"
            or adapter.get("external_review_required") is not True
            or adapter.get("compute_authorized") is not False
            or adapter.get("bulk_label_authorized") is not False
            or adapter.get("training_authorized") is not False
            or adapter.get("production_promotion") is not False
            or contract.get("decision") != "DESIGN_HARD_TAIL_STAGE_C"
            or contract.get("packet_id") != PACKET_ID
            or contract.get("next_authority") != "AUTHORIZE_STAGE_C_PACKET_REVIEW"
            or contract.get("model_work_authorized_only_after_teacher_gate")
            is not True):
        raise StageCDesignError("Teacher terminal adapter authority/decision")
    if contract.get("live_parent") != {
            "policy": LIVE_PARENT_AUTH.CHAMPION_POLICY,
            "authenticator": LIVE_PARENT_AUTH.SCHEMA,
            "must_reopen_at_packet_freeze": True,
    }:
        raise StageCDesignError("Teacher terminal adapter live-parent contract")
    required_gates = set(contract.get("separate_gates_required", []))
    if required_gates != {
        "hard_tail_regret_upper_bound",
        "ordinary_anchor_regret_upper_bound",
        "exact_work_and_zero_fallbacks",
        "proposal_recall_vs_same_budget_random_diversity",
    }:
        raise StageCDesignError("Teacher terminal adapter gate contract")
    if contract.get("label_routing_required") != {
        "ordinary_anchor": "cheap_proxy_only_under_passed_audit_contract",
        "uncertainty_or_disagreement": "gold_report_lcb_or_deeper",
        "exact_eligible_late_ply": "information_set_legal_exact_late",
        "oracle_hidden_card_features_for_deployable_targets": False,
        "raw_candidate_tensor_preserved": True,
    }:
        raise StageCDesignError("Teacher terminal adapter label routing")
    return adapter


def validate_h0(path: Path, expected_sha256: str) -> dict:
    if expected_sha256 != H0_SHA256 or sha256_file(path) != H0_SHA256:
        raise StageCDesignError("H0 design packet SHA-256 drift")
    h0 = _load_json(path)
    authority = h0.get("authority", {})
    selected = h0.get("split_contract", {}).get("selected", {})
    if (h0.get("schema") != H0_SCHEMA
            or h0.get("human_corpus", {}).get("manifest_sha256")
            != HUMAN_CORPUS_SHA256
            or len(selected.get("DESIGN", [])) != 384
            or len(selected.get("AUDIT", [])) != 128
            or authority.get("score_free") is not True
            or authority.get("outcomes_computed") is not False
            or authority.get("counterfactual_execution_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False):
        raise StageCDesignError("H0 packet identity/authority")
    return h0


def _split_geometry() -> dict:
    geometry = {}
    for split, definition in SPLITS.items():
        play_total = sum(definition["play"].values())
        bury_total = sum(definition["bury"].values())
        geometry[split] = {
            **definition,
            "play_total": play_total,
            "bury_total": bury_total,
            "total": play_total + bury_total,
        }
    if ({name: item["total"] for name, item in geometry.items()}
            != {"DESIGN": 1024, "CALIB": 512, "REPORT": 512}):
        raise StageCDesignError("Stage-C split geometry does not total 2,048")
    return geometry


def build_packet(adapter_path: Path, adapter_sha256: str,
                 h0_path: Path, h0_sha256: str, *, smoke: bool) -> dict:
    adapter = validate_adapter(adapter_path, adapter_sha256)
    h0 = validate_h0(h0_path, h0_sha256)
    try:
        live_parent = (LIVE_PARENT_AUTH.expected_parent() if smoke else
                       LIVE_PARENT_AUTH.require_live_champion_parent())
    except Exception as exc:
        raise StageCDesignError(
            f"live champion parent did not reopen: {type(exc).__name__}: {exc}"
        ) from exc
    LIVE_PARENT_AUTH.require_parent_payload(live_parent)
    geometry = _split_geometry()
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "producer": producer_identity(smoke=smoke),
        "authority_parent": {
            "terminal_adapter_sha256": ADAPTER_SHA256,
            "terminal_adapter_decision": adapter["contract"]["decision"],
            "audit_gate_sha256": adapter["evidence"]["gate"]["sha256"],
            "audit_supervisor_sha256": (
                adapter["evidence"]["supervisor_progress"]["sha256"]),
            "live_parent": {
                "authenticator_schema": LIVE_PARENT_AUTH.SCHEMA,
                "reopened_at_packet_freeze": not smoke,
                "must_reopen_at_capture_and_label": True,
                "payload": live_parent,
            },
        },
        "objective": (
            "Build a 2,048-state counterfactual Teacher whose hard-tail labels "
            "cover champion uncertainty, new proposals and observed human "
            "failure mechanisms instead of scaling heuristic self-imitation."
        ),
        "population_contract": {
            "splits": geometry,
            "total_states": 2048,
            "one_state_per_deal_across_all_splits": True,
            "fixed_scan_then_hash_smallest_selection": True,
            "underfilled_stratum_action": "TERMINAL_HOLD_NO_EXTENSION",
            "known_evaluation_deals_and_assets_excluded": True,
            "selection_features_cannot_enter_label_report_worlds": True,
            "split_outcomes_never_cross": True,
            "play_cross_cells": {
                "ordinary_anchor": (
                    "equal phase(early/mid/late) x role x lead/follow cells"
                ),
                "champion_uncertainty": (
                    "equal phase x role x lead/follow cells"
                ),
                "proposal_disagreement": (
                    "equal phase x role x lead/follow cells"
                ),
                "exact_late_eligible": "equal role x lead/follow cells",
                "point_banking_opportunity": "equal attacker/defender roles",
            },
            "human_witnesses": {
                "h0_packet_sha256": H0_SHA256,
                "allowed_source_split": "DESIGN",
                "supplemental_dev_diagnostic_only": True,
                "included_in_calib_or_report": False,
                "audit_rows_consumed": False,
                "design_rows": len(h0["split_contract"]["selected"]["DESIGN"]),
            },
        },
        "candidate_contract": {
            "play_union": [
                "live_champion_analysis_ballot",
                "v11pair_top_proposal",
                "named_structured_lead_or_follow_mechanisms",
                "same_budget_random_diversifier",
            ],
            "bury_union": [
                "live_smart_bury",
                "s3a_structured_point_void_bury",
                "same_budget_random_structured_bury",
            ],
            "human_action_union": "H0 DESIGN diagnostics only",
            "v11pair_is_proposal_not_scalar_leaf": True,
            "s3a_source_git": "c599b42e1a61c4a49346165940fc964632a71f16",
            "all_actions_replayed_legal_before_label": True,
        },
        "label_contract": {
            "utility": "acting-team-signed-level-utility",
            "belief_sampler": "strict-public-history-v1",
            "common_worlds_within_state_action_comparisons": True,
            "folds_disjoint_by_seed_and_world_digest": True,
            "ordinary_anchor": {
                "continuation": "passed-cheap-proxy",
                "selection_worlds": 256,
                "report_worlds": 256,
            },
            "uncertainty_disagreement_bury": {
                "continuation": "live-mc-s0-report-lcb-gold",
                "gold_selection_worlds": 64,
                "gold_report_worlds": 64,
                "n30_may_screen_but_cannot_supply_hard_tail_target": True,
            },
            "exact_late": {
                "preferred": "reviewed-information-set-legal-exact-solver",
                "oracle_hidden_hands_for_deployable_label": False,
                "fallback": "live-mc-s0-report-lcb-gold-64-plus-64",
                "silent_skip_authorized": False,
            },
            "point_banking": {
                "production_continuation_always_reported": True,
                "conditional_s4": S4_CONDITIONAL,
                "s4_result_cannot_replace_production_estimand": True,
            },
            "raw_action_tensor_and_uncertainty_preserved": True,
            "selected_argmax_only_is_invalid": True,
            "exact_work_and_refusal_counters_required": True,
        },
        "gate_contract": {
            "report_never_selects_recipe": True,
            "hard_tail_audit_states": 256,
            "hard_tail_audit_source": "REPORT only, hash-frozen before labels",
            "hard_tail_audit_quota": {
                "play_ordinary_anchor": 48,
                "play_champion_uncertainty": 48,
                "play_proposal_disagreement": 48,
                "play_exact_late_eligible": 48,
                "play_point_banking_opportunity": 32,
                "bury_all_report": 32,
            },
            "choice_rules": {
                "ordinary_anchor": (
                    "fixed cheap-heuristic selection-fold argmax"),
                "hard_tail": (
                    "fixed declared gold-or-exact label selection-fold argmax"),
                "audit_reference": (
                    "fixed live-report-lcb-gold audit-selection argmax"),
            },
            "audit_reference": {
                "continuation": "live-mc-s0-report-lcb-gold",
                "selection_worlds": 64,
                "report_worlds": 64,
                "selection_and_report_worlds_disjoint": True,
                "all_audit_worlds_disjoint_from_label_worlds": True,
                "fixed_choice_pair_evaluated_on_common_report_worlds": True,
                "regret": (
                    "audit-reference minus label-choice acting-team signed "
                    "level utility, clustered by deal/state"),
            },
            "regret_estimands": {
                "ordinary_anchor": (
                    "audit-reference choice minus frozen cheap-label choice"),
                "hard_tail": (
                    "audit-reference choice minus frozen gold-or-exact "
                    "hard-tail label choice"),
                "one_sided_interval": "Student-t 95% upper bound by state",
            },
            "hard_tail_regret_one_sided_95_upper_bound_max": 0.10,
            "ordinary_anchor_regret_one_sided_95_upper_bound_max": 0.10,
            "proposal_recall": {
                "target": "fixed audit-reference action",
                "treatment": (
                    "base analysis ballot plus named proposal sources"),
                "control": (
                    "same base ballot plus equal-count random legal diversity"),
                "candidate_counts_equal_per_state": True,
                "paired_unit": "deal/state",
                "gate": (
                    "one-sided 95% lower bound of treatment-minus-control "
                    "recall is greater than zero"),
            },
            "proposal_recall_must_beat_same_budget_random_diversity": True,
            "per_role_surface_phase_results_required": True,
            "exact_work_zero_fallbacks_required": True,
            "pass_next_authority": "AUTHORIZE_MODEL_PACKET_REVIEW",
            "nonpass_next_authority": "DIAGNOSE_FROZEN_STAGE_C_ONLY",
        },
        "execution_stages": [
            "review this design",
            "implement and review a score-free capture/controller",
            "capture and review the exact 2,048-state population",
            "capacity preflight without retained outcomes",
            "separately review and launch labels",
            "terminally gate Teacher fidelity before model work",
        ],
        "authority": {
            "design_review_authorized": True,
            "state_capture_authorized": False,
            "compute_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "retry_or_extension_authorized": False,
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("Stage-C packet full recomputation drift")
    authority = actual.get("authority", {})
    if (authority.get("design_review_authorized") is not True
            or authority.get("state_capture_authorized") is not False
            or authority.get("compute_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("retry_or_extension_authorized") is not False):
        problems.append("Stage-C packet authority widened")
    return sorted(set(problems))


def publish_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise StageCDesignError("refusing existing packet or partial")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StageCDesignError("published packet is not regular/unlinked")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "verify"):
        child = sub.add_parser(command)
        child.add_argument("--adapter", required=True)
        child.add_argument("--expected-adapter-sha256", required=True)
        child.add_argument("--h0-packet", required=True)
        child.add_argument("--expected-h0-sha256", required=True)
        child.add_argument("--packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise StageCDesignError("producer Git differs from expected Git")
    expected = build_packet(
        Path(args.adapter), args.expected_adapter_sha256,
        Path(args.h0_packet), args.expected_h0_sha256, smoke=args.smoke)
    packet_path = Path(args.packet)
    if args.command == "freeze":
        publish_exclusive(packet_path, expected)
        print(json.dumps({
            "status": "FROZEN_FOR_DESIGN_REVIEW",
            "packet": str(packet_path),
            "sha256": sha256_file(packet_path),
            "states": expected["population_contract"]["total_states"],
            "compute_authorized": False,
        }, sort_keys=True))
        return
    actual = _load_json(packet_path)
    problems = packet_problems(actual, expected)
    if problems:
        raise StageCDesignError("; ".join(problems))
    print(json.dumps({
        "status": "VERIFIED_FOR_DESIGN_REVIEW",
        "packet": str(packet_path),
        "sha256": sha256_file(packet_path),
        "compute_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
