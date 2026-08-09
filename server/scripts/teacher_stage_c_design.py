#!/usr/bin/env python3
"""Freeze the no-compute Teacher Stage-C hard-tail design contract.

This tool consumes the independently verified T1 terminal adapter plus the
reviewed executable H0 human-action controller and its exact PASS marker.  It
emits experiment geometry only: fresh seed blocks, split/stratum quotas,
candidate sources, label routing, gates and authority.  It never captures a
state, samples a world, labels an action, trains a model or promotes a policy.
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
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT_AUTH  # noqa: E402
import h0_human_counterfactual_controller as H0_CONTROLLER  # noqa: E402
import h0_human_counterfactual_runtime as H0_RUNTIME  # noqa: E402


SCHEMA = "teacher-stage-c-hard-tail-design-v3"
REVIEW_SCHEMA = "teacher-stage-c-hard-tail-design-review-v3"
REVIEW_MARKER = "TEACHER_STAGE_C_V3_REVIEW "
# The terminal adapter grants this literal packet identity.  A previous draft
# silently dropped the word "design" and therefore did not consume its parent
# authority exactly even though no compute had started.
PACKET_ID = "teacher-v3-hard-tail-stage-c-design-v1"
ADAPTER_SCHEMA = "teacher-v3-terminal-adapter-v2"
ADAPTER_SHA256 = "56ccefbd62d9ea2aef30a4c6e54e11a0d2231e464f129e754b84b3488f1c2442"
H0_CONTROLLER_SCHEMA = "human-h0-counterfactual-controller-v2"
H0_CONTROLLER_SHA256 = (
    "3f68dc6ec6d5f90043f36c0a68847ca9ef510641e01760ac4fa11ebd6a6a7fcf"
)
H0_CONTROLLER_INTERNAL_SHA256 = (
    "7744c745fd92f5ae725c8a2f45882b7e6668c14b5bf2a3570c738d245dc6b9ec"
)
H0_CONTROLLER_GIT = "6977dbbdc77276b115faf941509b8034d7801bf0"
H0_CONTROLLER_PACKET_GIT = "d99f7e8245e8f521475a1f109dcf7a9196e88878"
H0_SCHEDULE_SHA256 = (
    "f54ce37425707dfeea3563bbc5d635617943152166a82825a74e55ad00131793"
)
H0_CANDIDATE_GEOMETRY_SHA256 = (
    "876ed56bd8f436d58cb6f3d58774a0f06756afb4d8c98ffdb49d9424b545ff2b"
)
HUMAN_CORPUS_SHA256 = "b9699790bdfe1c217922c9f9c72b237c1856174fa64c11753329a8ff11e16553"
S4_CONDITIONAL = {
    "run_id": "s4-point-banking-duel-screen-100b-v2",
    "git": "cad399294b888865a3bb79c47a9892200b896013",
    "design_packet_sha256": (
        "17036e6307ad0072ae10aeaaddde0ed3628a2f526ca440e909cdc35cd5071385"
    ),
    "execution_receipt_sha256": (
        "20a420d2e939f8f1ce375ca32cee81d044db2c29dff7e52fbe7080a000dd65cc"
    ),
    "use_requires_separate_terminal_pass": True,
    "required_terminal_verdict": "AUTHORIZE_CONFIRM_PACKET_REVIEW",
    "terminal_screen_sha256_must_bind_at_execution": True,
}
S3C_CONDITIONAL = {
    "controller_git": "e9db4a23457ff4221d342c9a422e50ea491fe7ab",
    "controller_packet_sha256": (
        "f58d23b74046dd04963b4f10fbf605030221219eef6d325c5e8319043643874a"
    ),
    "controller_review_schema": "s3c-one-card-capacity-controller-review-v1",
    "one_card_use_requires_complete_mechanics_execution": True,
    "two_or_three_card_use_requires_separate_reviewed_stage": True,
}
S5_CONDITIONAL = {
    "required_census_schema": "s5-point-protection-census-v1",
    "required_census_decision": "S5_DESIGN_REVIEW_ELIGIBLE",
    "human_witnesses_are_design_only": True,
    "fresh_trigger_matched_population_required": True,
    "treatment_requires_separate_design_review": True,
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
PLAY_CANDIDATE_CAP = 20
BURY_CANDIDATE_CAP = 33
ORDINARY_SELECTION_WORLDS = 256
ORDINARY_REPORT_WORLDS = 256
HARD_TAIL_SELECTION_WORLDS = 64
HARD_TAIL_REPORT_WORLDS = 300
AUDIT_REFERENCE_SELECTION_WORLDS = 128
AUDIT_REFERENCE_REPORT_WORLDS = 600
FIXED_REPORT_ACTIONS = 2
CONDITIONAL_MECHANISM_STATES = 160


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
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True
    ).stdout.strip()


def reopen_live_parent(*, smoke: bool, repo: Path | None,
                       python: Path | None) -> dict:
    """Reopen the champion from an explicit clean evidence checkout.

    The active Mini checkout owns the canonical RLCB-C1 artifacts while design
    work normally happens in a separate clean worktree.  Importing the local
    authenticator would silently redirect its canonical paths to that scratch
    worktree.  Real freezes therefore execute the exact same authenticator from
    an explicit evidence checkout, while binding its Git and script bytes.
    """
    if smoke:
        payload = LIVE_PARENT_AUTH.expected_parent()
        LIVE_PARENT_AUTH.require_parent_payload(payload)
        return {
            "authenticator_schema": LIVE_PARENT_AUTH.SCHEMA,
            "reopened_at_packet_freeze": False,
            "mode": "smoke-expected-payload-only",
            "payload": payload,
        }
    if repo is None or python is None:
        raise StageCDesignError(
            "real Stage-C freeze requires --live-parent-repo and "
            "--live-parent-python")
    repo = repo.resolve()
    python = python.resolve()
    script = repo / "server/scripts/live_champion_parent.py"
    if (not repo.is_dir() or not python.is_file() or not script.is_file()
            or repo.is_symlink() or script.is_symlink()):
        raise StageCDesignError("live-parent reopener path is not regular")
    try:
        git = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], check=True,
            capture_output=True, text=True).stdout.splitlines()
    except subprocess.CalledProcessError as exc:
        raise StageCDesignError("live-parent evidence checkout is not Git") from exc
    # The evidence checkout may receive an unrelated handoff-note edit while a
    # sealed run owns it.  Requiring global cleanliness would make a Markdown
    # mailbox block a source-hash authenticator.  Any server or deployment
    # change still refuses; the authenticator itself rehashes every champion,
    # engine, evaluator and binary input before returning.
    relevant_dirty = []
    for line in status:
        path = line[3:] if len(line) >= 4 else line
        paths = path.split(" -> ")
        if any(item == "fly.toml" or item.startswith("server/")
               for item in paths):
            relevant_dirty.append(line)
    if relevant_dirty:
        raise StageCDesignError(
            "live-parent evidence checkout has relevant dirty paths: "
            + ",".join(relevant_dirty))
    local_authenticator_sha = sha256_file(LIVE_PARENT_AUTH.__file__)
    if sha256_file(script) != local_authenticator_sha:
        raise StageCDesignError("live-parent authenticator source differs")
    env = dict(os.environ)
    env["SHENGJI_FAST"] = "1"
    env["SHENGJI_REQUIRE_VOIDS"] = "1"
    portable_reopen = (
        "import json,sys;sys.path.insert(0,'scripts');"
        "import live_champion_parent as parent;"
        "print(json.dumps("
        "parent.require_portable_live_champion_parent(),sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [str(python), "-c", portable_reopen], cwd=repo / "server",
            env=env, check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout)
        LIVE_PARENT_AUTH.require_parent_payload(payload)
    except (subprocess.CalledProcessError, ValueError, TypeError,
            LIVE_PARENT_AUTH.ProtocolRefused) as exc:
        raise StageCDesignError(
            f"live champion parent did not reopen: {type(exc).__name__}: {exc}"
        ) from exc
    return {
        "authenticator_schema": LIVE_PARENT_AUTH.SCHEMA,
        "reopened_at_packet_freeze": True,
        "mode": "explicit-clean-evidence-checkout",
        "authenticator_git": git,
        "authenticator_script_sha256": local_authenticator_sha,
        "payload": payload,
    }


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


def validate_h0_controller(path: Path, expected_sha256: str,
                           review_record: Path) -> tuple[dict, dict]:
    """Bind Stage C to the passed executable H0 controller, not its draft.

    Stage-C v2 consumed the score-free H0 *design* packet.  That left the
    proposal caps, schedule, strict runtime and refusal semantics as prose.
    The reviewed controller is the first artifact that makes those semantics
    executable, so v3 requires both its immutable packet and its exact PASS
    marker while preserving the controller's no-outcome/no-label authority.
    """
    if (expected_sha256 != H0_CONTROLLER_SHA256
            or not H0_CONTROLLER.is_regular_unlinked(path)
            or sha256_file(path) != H0_CONTROLLER_SHA256):
        raise StageCDesignError("H0 controller packet SHA-256 drift")
    packet = _load_json(path)
    authority = packet.get("authority", {})
    preflight = packet.get("score_free_preflight", {})
    inputs = packet.get("inputs", {})
    result = packet.get("result_contract", {})
    if (packet.get("schema") != H0_CONTROLLER_SCHEMA
            or packet.get("packet_id") != H0_CONTROLLER.PACKET_ID
            or packet.get("run_id") != H0_CONTROLLER.RUN_ID
            or packet.get("packet_sha256") !=
            H0_CONTROLLER_INTERNAL_SHA256
            or packet.get("producer") != {
                "git": H0_CONTROLLER_GIT,
                "promotable": True,
                "script_sha256": H0_CONTROLLER.sha256_file(
                    H0_CONTROLLER.SCRIPT),
                "tree_dirty": False,
            }
            or packet.get("design", {}).get("sha256") !=
            H0_CONTROLLER.DESIGN_PACKET_SHA256
            or inputs.get("human_corpus", {}).get("manifest_sha256") !=
            HUMAN_CORPUS_SHA256
            or inputs.get("source_snapshot", {}).get("manifest_sha256") !=
            H0_CONTROLLER.SOURCE_MANIFEST_SHA256
            or inputs.get("v11pair", {}).get("sha256") !=
            H0_CONTROLLER.V11PAIR_SHA256
            or inputs.get("selected_play_rows_sha256") !=
            H0_CONTROLLER.SELECTED_PLAY_ROWS_SHA256
            or inputs.get("selected_bury_rows_sha256") !=
            H0_CONTROLLER.SELECTED_BURY_ROWS_SHA256
            or preflight.get("status") != "VERIFIED_SCORE_FREE"
            or preflight.get("rows_replayed") != 557
            or preflight.get("worlds_sampled") != 0
            or preflight.get("candidate_world_rollouts") != 0
            or preflight.get("outcomes_computed") is not False
            or packet.get("schedule", {}).get("shard_count") != 8
            or packet.get("packet_sha256") != sha256_bytes(canonical_json({
                key: value for key, value in packet.items()
                if key != "packet_sha256"
            }))):
        raise StageCDesignError("H0 controller identity/preflight drift")
    # Schedule identity and candidate geometry are independent boundaries;
    # the maximum future work lives in the result contract.
    if (packet.get("schedule", {}).get("schedule_sha256") !=
            H0_SCHEDULE_SHA256
            or preflight.get("candidate_geometry_sha256") !=
            H0_CANDIDATE_GEOMETRY_SHA256
            or result.get("work", {}).get("candidate_world_ceiling") !=
            H0_CONTROLLER.MAX_CANDIDATE_WORLDS
            or result.get("durable_one_shot_admission_slot") !=
            H0_CONTROLLER.admission_slot_logical_path()
            or result.get("receipt_deletion_cannot_reissue") is not True
            or authority != {
                "score_free": True,
                "worlds_sampled": False,
                "outcomes_computed": False,
                "controller_review_authorized": True,
                "counterfactual_execution_authorized": False,
                "labels_authorized": False,
                "training_authorized": False,
                "strength_claim": False,
                "production_promotion": False,
                "production_deployment": False,
                "human_evaluation_data_may_train_or_select": False,
            }):
        raise StageCDesignError("H0 controller work/authority drift")
    try:
        LIVE_PARENT_AUTH.require_parent_payload(inputs.get("live_parent"))
    except LIVE_PARENT_AUTH.ProtocolRefused as exc:
        raise StageCDesignError("H0 controller live-parent drift") from exc
    if not H0_CONTROLLER.is_regular_unlinked(review_record):
        raise StageCDesignError("H0 controller review record is not regular")
    try:
        claim = H0_CONTROLLER._marker_claim(
            review_record, H0_CONTROLLER.REVIEW_MARKER)
        expected_claim = H0_RUNTIME._expected_review_claim(
            packet, H0_CONTROLLER_SHA256)
    except (H0_CONTROLLER.ControllerRefused, KeyError, TypeError) as exc:
        raise StageCDesignError("H0 controller review cannot reopen") from exc
    if claim != expected_claim:
        raise StageCDesignError("H0 controller PASS marker drift")
    return packet, claim


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


def _work_ceiling(geometry: dict) -> dict:
    ordinary_play = sum(
        split["play"]["ordinary_anchor"] for split in geometry.values())
    ordinary_bury = sum(
        split["bury"]["ordinary_anchor"] for split in geometry.values())
    total_play = sum(split["play_total"] for split in geometry.values())
    total_bury = sum(split["bury_total"] for split in geometry.values())
    hard_play = total_play - ordinary_play
    hard_bury = total_bury - ordinary_bury
    ordinary = (
        ordinary_play * PLAY_CANDIDATE_CAP
        + ordinary_bury * BURY_CANDIDATE_CAP
    ) * (ORDINARY_SELECTION_WORLDS + ORDINARY_REPORT_WORLDS)
    hard_selection = (
        hard_play * PLAY_CANDIDATE_CAP
        + hard_bury * BURY_CANDIDATE_CAP
    ) * HARD_TAIL_SELECTION_WORLDS
    hard_report = (
        hard_play + hard_bury
    ) * FIXED_REPORT_ACTIONS * HARD_TAIL_REPORT_WORLDS
    audit_play, audit_bury = 224, 32
    audit_selection = (
        audit_play * PLAY_CANDIDATE_CAP
        + audit_bury * BURY_CANDIDATE_CAP
    ) * AUDIT_REFERENCE_SELECTION_WORLDS
    audit_report = (
        audit_play + audit_bury
    ) * FIXED_REPORT_ACTIONS * AUDIT_REFERENCE_REPORT_WORLDS
    one_conditional = CONDITIONAL_MECHANISM_STATES * (
        PLAY_CANDIDATE_CAP * HARD_TAIL_SELECTION_WORLDS
        + FIXED_REPORT_ACTIONS * HARD_TAIL_REPORT_WORLDS
    )
    base = ordinary + hard_selection + hard_report
    audit = audit_selection + audit_report
    total = base + audit + 2 * one_conditional
    if (ordinary_play, ordinary_bury, hard_play, hard_bury) != (
            480, 64, 1440, 64):
        raise StageCDesignError("Stage-C work population drift")
    if total != 10_494_720:
        raise StageCDesignError("Stage-C work ceiling arithmetic drift")
    return {
        "unit": "candidate-world rollout",
        "ordinary_labels": ordinary,
        "hard_tail_selection_and_fixed_report":
            hard_selection + hard_report,
        "deeper_audit_reference": audit,
        "conditional_s4_max": one_conditional,
        "conditional_s5_max": one_conditional,
        "all_optional_mechanisms_max": total,
        "recursive_mc_continuation_rollouts": 0,
        "exact_solver_nodes": (
            "separately bounded by a passed S3c stage and replace, never add "
            "to, the corresponding heuristic continuation fold"
        ),
    }


def build_packet(adapter_path: Path, adapter_sha256: str,
                 h0_controller_path: Path, h0_controller_sha256: str,
                 h0_review_record: Path, *, smoke: bool,
                 live_parent_attestation: dict | None = None) -> dict:
    adapter = validate_adapter(adapter_path, adapter_sha256)
    h0, h0_review = validate_h0_controller(
        h0_controller_path, h0_controller_sha256, h0_review_record)
    h0_cells = h0["score_free_preflight"]["cell_counts"]
    h0_design_rows = sum(
        count for cell, count in h0_cells.items()
        if cell.startswith("DESIGN:"))
    h0_audit_rows = sum(
        count for cell, count in h0_cells.items()
        if cell.startswith("AUDIT:"))
    if (h0_design_rows != 420 or h0_audit_rows != 137
            or h0_design_rows + h0_audit_rows != 557):
        raise StageCDesignError("H0 controller split geometry drift")
    if live_parent_attestation is None:
        live_parent_attestation = reopen_live_parent(
            smoke=smoke, repo=None, python=None)
    if (not isinstance(live_parent_attestation, dict)
            or live_parent_attestation.get("authenticator_schema")
            != LIVE_PARENT_AUTH.SCHEMA
            or live_parent_attestation.get("reopened_at_packet_freeze")
            is not (not smoke)):
        raise StageCDesignError("live-parent reopen attestation drift")
    LIVE_PARENT_AUTH.require_parent_payload(
        live_parent_attestation.get("payload"))
    if (h0.get("inputs", {}).get("live_parent") !=
            live_parent_attestation.get("payload")):
        raise StageCDesignError(
            "H0 controller and Stage-C live parent differ")
    geometry = _split_geometry()
    work_ceiling = _work_ceiling(geometry)
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
                **live_parent_attestation,
                "must_reopen_at_capture_and_label": True,
            },
            "h0_controller": {
                "packet_sha256": H0_CONTROLLER_SHA256,
                "packet_internal_sha256": H0_CONTROLLER_INTERNAL_SHA256,
                "source_git": H0_CONTROLLER_GIT,
                "packet_git": H0_CONTROLLER_PACKET_GIT,
                "design_packet_sha256":
                    H0_CONTROLLER.DESIGN_PACKET_SHA256,
                "review_claim": h0_review,
                "schedule_sha256": H0_SCHEDULE_SHA256,
                "candidate_geometry_sha256":
                    H0_CANDIDATE_GEOMETRY_SHA256,
                "max_candidate_worlds":
                    H0_CONTROLLER.MAX_CANDIDATE_WORLDS,
                "execution_is_diagnostic_not_label_authority": True,
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
            "conditional_secondary_tags": {
                "replay_verified_point_protection": {
                    "maximum_states": CONDITIONAL_MECHANISM_STATES,
                    "must_overlap_existing_play_quota": True,
                    "requires": S5_CONDITIONAL,
                },
                "human_derived_proposer_disagreement": {
                    "must_overlap_proposal_disagreement": True,
                    "requires_supported_h0_design_result": True,
                },
            },
            "human_witnesses": {
                "h0_controller_packet_sha256": H0_CONTROLLER_SHA256,
                "h0_controller_review_schema":
                    H0_CONTROLLER.REVIEW_SCHEMA,
                "allowed_source_split": "DESIGN",
                "supplemental_dev_diagnostic_only": True,
                "included_in_calib_or_report": False,
                "audit_rows_consumed": False,
                "design_rows": h0_design_rows,
                "audit_rows_preserved": h0_audit_rows,
                "human_action_requires_counterfactual_support_before_use":
                    True,
            },
        },
        "candidate_contract": {
            "max_unique_play_actions": PLAY_CANDIDATE_CAP,
            "max_unique_bury_actions": BURY_CANDIDATE_CAP,
            "play_union": [
                "live_champion_analysis_ballot",
                "v11pair_top_proposal",
                "named_structured_lead_or_follow_mechanisms",
                "conditional_replay_verified_s5_mechanism",
                "same_budget_random_diversifier",
            ],
            "bury_union": [
                "live_smart_bury",
                "s3a_structured_point_void_bury",
                "same_budget_random_structured_bury",
            ],
            "human_action_union_on_fresh_2048": False,
            "human_derived_proposer": (
                "may enter only as a separately frozen rule/model derived "
                "from supported H0 DESIGN proposals; H0 AUDIT cannot tune it"
            ),
            "v11pair_is_proposal_not_scalar_leaf": True,
            "s3a_source_git": "c599b42e1a61c4a49346165940fc964632a71f16",
            "s3a_terminal_result": (
                "SELECT_NONE; retain candidate source only for per-state "
                "Teacher evaluation, never as a policy prior"
            ),
            "all_actions_replayed_legal_before_label": True,
            "unsupported_human_action_fallback": (
                "omit human source; preserve V11/structured/random sources"
            ),
        },
        "label_contract": {
            "utility": "acting-team-signed-level-utility",
            "belief_sampler": "strict-public-history-v1",
            "common_worlds_within_state_action_comparisons": True,
            "folds_disjoint_by_seed_and_world_digest": True,
            "ordinary_anchor": {
                "continuation": "HeuristicBot",
                "source": "passed Stage-B cheap-proxy contract",
                "selection_worlds": ORDINARY_SELECTION_WORLDS,
                "report_worlds": ORDINARY_REPORT_WORLDS,
                "all_candidates_receive_both_folds": True,
            },
            "uncertainty_disagreement_bury": {
                "root_semantics": (
                    "report-LCB-compatible candidate comparison under the "
                    "exact live ballot/sampler"
                ),
                "rollout_continuation": "HeuristicBot",
                "recursive_mc_continuation": False,
                "selection_worlds_all_candidates":
                    HARD_TAIL_SELECTION_WORLDS,
                "selection_rule": (
                    "highest acting-team signed mean; deterministic lowest "
                    "candidate index tie-break"
                ),
                "report_worlds_fixed_selection_winner_and_candidate0":
                    HARD_TAIL_REPORT_WORLDS,
                "final_choice_rule": (
                    "use the fixed selection winner only when its paired "
                    "one-sided 95% LCB versus candidate0 is greater than 0; "
                    "otherwise use candidate0"
                ),
                "report_fold_never_reselects": True,
                "n30_may_screen_but_cannot_supply_hard_tail_target": True,
            },
            "exact_late": {
                "preferred": "reviewed-information-set-legal-exact-solver",
                "oracle_hidden_hands_for_deployable_label": False,
                "fallback": (
                    "the same non-recursive root label contract; never "
                    "silently substitute recursive MC"
                ),
                "silent_skip_authorized": False,
                "conditional_s3c": S3C_CONDITIONAL,
            },
            "point_banking": {
                "production_continuation_always_reported": True,
                "conditional_s4": S4_CONDITIONAL,
                "s4_result_cannot_replace_production_estimand": True,
            },
            "defensive_point_protection": {
                "conditional_s5": S5_CONDITIONAL,
                "production_continuation_always_reported": True,
                "unverified_human_loss_rows_cannot_supply_labels": True,
            },
            "raw_action_tensor_and_uncertainty_preserved": True,
            "selected_argmax_only_is_invalid": True,
            "exact_work_and_refusal_counters_required": True,
        },
        "work_contract": {
            **work_ceiling,
            "candidate_caps_are_hard_refusal_boundaries": True,
            "all_split_and_stratum_quotas_must_fill_without_extension": True,
            "conditional_tags_do_not_increase_state_count": True,
            "partial_or_underfilled_fold_publishes_no_label_for_that_state":
                True,
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
                    "fixed 64-world selection winner, accepted only by its "
                    "disjoint 300-world LCB versus candidate0; exact may "
                    "replace only under its separate passed stage"),
                "audit_reference": (
                    "fixed 128-world selection winner, accepted only by its "
                    "disjoint 600-world LCB versus candidate0"),
            },
            "audit_reference": {
                "rollout_continuation": "HeuristicBot",
                "recursive_mc_continuation": False,
                "selection_worlds": AUDIT_REFERENCE_SELECTION_WORLDS,
                "report_worlds": AUDIT_REFERENCE_REPORT_WORLDS,
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
        "review_contract": {
            "schema": REVIEW_SCHEMA,
            "marker": REVIEW_MARKER.strip(),
            "required_verdict": "PASS",
            "pass_authorizes": (
                "implementation of one score-free Stage-C capture/controller "
                "packet only"
            ),
            "pass_does_not_authorize": [
                "state capture", "belief-world sampling", "labels",
                "training", "strength claim", "promotion", "deployment",
            ],
            "required_claim_fields": [
                "schema", "git", "script_sha256", "packet_sha256",
                "adapter_sha256", "h0_controller_sha256",
                "h0_controller_review_schema", "live_parent_schema",
                "live_parent_policy", "states", "design_states",
                "calib_states", "report_states", "play_candidate_cap",
                "bury_candidate_cap", "max_candidate_worlds",
                "recursive_mc_continuation_rollouts", "ordinary_worlds",
                "hard_tail_selection_worlds", "hard_tail_report_worlds",
                "audit_selection_worlds", "audit_report_worlds",
                "score_free", "worlds_sampled_before_review",
                "outcomes_computed_before_review", "independent_review",
                "capture_controller_implementation_authorized",
                "state_capture_authorized", "labels_authorized",
                "training_authorized", "strength_claim",
                "production_promotion", "production_deployment", "verdict",
            ],
        },
        "authority": {
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
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("Stage-C packet full recomputation drift")
    authority = actual.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("design_review_authorized") is not True
            or authority.get("capture_controller_implementation_authorized")
            is not False
            or authority.get("state_capture_authorized") is not False
            or authority.get("compute_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False
            or authority.get("retry_or_extension_authorized") is not False):
        problems.append("Stage-C packet authority widened")
    return sorted(set(problems))


def expected_review_claim(packet: dict, packet_sha256: str) -> dict:
    if (packet.get("schema") != SCHEMA
            or packet.get("producer", {}).get("promotable") is not True
            or len(packet_sha256) != 64):
        raise StageCDesignError("cannot derive review claim from packet")
    splits = packet["population_contract"]["splits"]
    candidates = packet["candidate_contract"]
    work = packet["work_contract"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "script_sha256": packet["producer"]["script_sha256"],
        "packet_sha256": packet_sha256,
        "adapter_sha256": ADAPTER_SHA256,
        "h0_controller_sha256": H0_CONTROLLER_SHA256,
        "h0_controller_review_schema": H0_CONTROLLER.REVIEW_SCHEMA,
        "live_parent_schema": LIVE_PARENT_AUTH.SCHEMA,
        "live_parent_policy": LIVE_PARENT_AUTH.CHAMPION_POLICY,
        "states": packet["population_contract"]["total_states"],
        "design_states": splits["DESIGN"]["total"],
        "calib_states": splits["CALIB"]["total"],
        "report_states": splits["REPORT"]["total"],
        "play_candidate_cap": candidates["max_unique_play_actions"],
        "bury_candidate_cap": candidates["max_unique_bury_actions"],
        "max_candidate_worlds": work["all_optional_mechanisms_max"],
        "recursive_mc_continuation_rollouts":
            work["recursive_mc_continuation_rollouts"],
        "ordinary_worlds": [
            ORDINARY_SELECTION_WORLDS, ORDINARY_REPORT_WORLDS],
        "hard_tail_selection_worlds": HARD_TAIL_SELECTION_WORLDS,
        "hard_tail_report_worlds": HARD_TAIL_REPORT_WORLDS,
        "audit_selection_worlds": AUDIT_REFERENCE_SELECTION_WORLDS,
        "audit_report_worlds": AUDIT_REFERENCE_REPORT_WORLDS,
        "score_free": True,
        "worlds_sampled_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "capture_controller_implementation_authorized": True,
        "state_capture_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


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
        child.add_argument("--h0-controller", required=True)
        child.add_argument("--expected-h0-controller-sha256", required=True)
        child.add_argument("--h0-review-record", required=True)
        child.add_argument("--packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--live-parent-repo")
        child.add_argument("--live-parent-python")
        child.add_argument("--smoke", action="store_true")
        if command == "verify":
            child.add_argument("--expected-packet-sha256")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if not args.smoke and not args.expected_git:
        raise StageCDesignError("real Stage-C freeze/verify requires --expected-git")
    if (args.command == "verify" and not args.smoke
            and not args.expected_packet_sha256):
        raise StageCDesignError(
            "real Stage-C verification requires --expected-packet-sha256")
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise StageCDesignError("producer Git differs from expected Git")
    live_parent_attestation = reopen_live_parent(
        smoke=args.smoke,
        repo=(Path(args.live_parent_repo)
              if args.live_parent_repo is not None else None),
        python=(Path(args.live_parent_python)
                if args.live_parent_python is not None else None),
    )
    expected = build_packet(
        Path(args.adapter), args.expected_adapter_sha256,
        Path(args.h0_controller), args.expected_h0_controller_sha256,
        Path(args.h0_review_record), smoke=args.smoke,
        live_parent_attestation=live_parent_attestation)
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
    if (args.expected_packet_sha256
            and sha256_file(packet_path) != args.expected_packet_sha256):
        raise StageCDesignError("external Stage-C packet SHA-256 drift")
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
