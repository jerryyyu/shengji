#!/usr/bin/env python3
"""Freeze one fresh-REPORT evaluation of the protected-anchor Teacher.

The unconditional Stage-C training route terminally selected no capability.
A separately reviewed post-terminal diagnostic froze one narrower policy on
DESIGN: average the eight epoch-32 play-ranking logits and keep candidate zero
unless the strongest alternative clears a strict 0.2 margin.  CALIB supported
that hypothesis but was diagnostic, not fresh confirmation.

This controller binds that exact protected policy to the separately reviewed
fresh REPORT replacement.  It derives only a digest-sealed, score-free
eight-shard work schedule.  It does not publish state material, compute Teacher
labels, run model inference, or open REPORT utility.

After independent review, one runtime may consume the durable REPORT slot,
reconstruct the reviewed fresh states, label the already-selected surface with
the frozen finite-work Teacher, and evaluate the frozen ensemble exactly once.
V11 is neither loaded nor reconstructed on this path.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_fresh_report_controller as FRESH  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
import teacher_stage_c_protected_anchor_controller as PROTECTED  # noqa: E402
import teacher_stage_c_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_training_runtime as TRAIN_RUNTIME  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-protected-anchor-fresh-report-controller-v1"
PACKET_ID = \
    "teacher-v3-hard-tail-stage-c-protected-anchor-fresh-report-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-protected-anchor-fresh-report-v1"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-protected-anchor-fresh-report-controller-v1"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
REVIEW_SCHEMA = \
    "teacher-stage-c-protected-anchor-fresh-report-controller-review-v1"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_PROTECTED_ANCHOR_FRESH_REPORT_CONTROLLER_V1_REVIEW "

REPORT_SURFACE_COUNTS = {"play": 480, "bury": 32}
REPORT_SHARDS = 8
SUPERVISOR_MAX_WORKERS = 8
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_report_controller.py",
    "server/scripts/teacher_stage_c_report_runtime.py",
    "server/scripts/teacher_stage_c_report_supervisor.py",
    "server/shengji/rl/stage_c_report.py",
    "server/shengji/rl/stage_c_model.py",
    "server/shengji/rl/stage_c_training.py",
    "server/shengji/rl/encode.py",
    "server/shengji/rl/exact_resume.py",
    "server/scripts/teacher_stage_c_training_controller.py",
    "server/scripts/teacher_stage_c_training_runtime.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
    "server/scripts/teacher_stage_c_fresh_report_controller.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/scripts/teacher_stage_c_protected_anchor_controller.py",
)


class ReportControllerRefused(RuntimeError):
    """A training, checkpoint, sealed-REPORT or authority identity drifted."""


canonical_json = TRAIN_CTRL.canonical_json
sha256_bytes = TRAIN_CTRL.sha256_bytes
sha256_file = TRAIN_CTRL.sha256_file
self_hash = TRAIN_CTRL.self_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ReportControllerRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReportControllerRefused(f"cannot read JSON {path}: {exc}") \
            from exc
    if not isinstance(value, dict):
        raise ReportControllerRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _source_sha256s() -> dict[str, str]:
    result = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ReportControllerRefused(
                f"Stage-C REPORT source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise ReportControllerRefused("review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise ReportControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        value = json.loads(matches[0])
    except ValueError as exc:
        raise ReportControllerRefused("review marker is not JSON") from exc
    if not isinstance(value, dict):
        raise ReportControllerRefused("review marker root is not an object")
    return value


def _manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def runtime_contract() -> dict:
    """Bind REPORT inference to the exact reviewed training environment."""
    value = TRAIN_CTRL.runtime_contract()
    return {
        "host": value["host"],
        "python": value["python"],
        "torch": value["torch"],
        "numpy": value["numpy"],
        "device": value["device"],
        "cpu_threads": TRAIN.CPU_THREADS,
        "max_concurrent_label_shards": SUPERVISOR_MAX_WORKERS,
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_signal_contract": {
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_label_workers_authorized": False,
        },
    }


@contextlib.contextmanager
def evidence_scope(evidence_repo: Path):
    """Point frozen-parent validators at the immutable evidence worktree."""
    modules = []
    for module in (
            TRAIN_CTRL, TRAIN_RUNTIME, FRESH, CAPTURE, LABEL,
            getattr(FRESH, "LABEL", None), getattr(FRESH, "CAPTURE", None)):
        if module is not None and hasattr(module, "REPO") \
                and all(module is not value[0] for value in modules):
            modules.append((module, module.REPO))
    try:
        for module, _old in modules:
            module.REPO = evidence_repo
        yield
    finally:
        for module, old in modules:
            module.REPO = old


def validate_training_aggregate(
    *, evidence_repo: Path, training_review_record: Path,
) -> tuple[dict, dict, dict]:
    try:
        packet, dataset, expected, _play_cells = PROTECTED.validate_parent(
            evidence_repo=evidence_repo,
            training_review_record=training_review_record)
    except (PROTECTED.ProtectedAnchorRefused,
            TRAIN_RUNTIME.TrainingRuntimeRefused,
            TRAIN_CTRL.TrainingControllerRefused,
            TRAIN.StageCTrainingError) as exc:
        raise ReportControllerRefused(
            f"Stage-C terminal training replay refused: {exc}") from exc
    selection = expected.get("selection", {})
    if (expected.get("decision")
            != "SELECT_NONE"
            or expected.get("report_packet_review_authorized") is not False
            or expected.get("report_rows_opened") != 0
            or expected.get("report_open_authorized") is not False
            or selection.get("selected_capability") is not None
            or expected.get("selected_ensemble") != []
            or expected.get("aggregate_sha256")
            != PROTECTED.TRAINING_AGGREGATE_INTERNAL_SHA256
            or expected.get("model_dataset_sha256")
            != PROTECTED.MODEL_DATASET_SHA256):
        raise ReportControllerRefused(
            "Stage-C terminal training aggregate identity/authority drift")
    return packet, dataset, expected


def protected_policy_contract(capability: Mapping[str, object]) -> dict:
    """Map the reviewed capability to the exact executable REPORT contract."""
    expected_capability = {
        "surface": PROTECTED.SURFACE,
        "head": PROTECTED.HEAD,
        "epoch": PROTECTED.EPOCH,
        "curve_fraction": PROTECTED.CURVE_FRACTION,
        "seeds": list(MODEL.TRAINING_SEEDS),
        "ensemble": "arithmetic mean of per-seed rank logits",
        "incumbent": "candidate0",
        "alternative": (
            "highest ensemble-mean rank logit among candidate indices 1+; "
            "ties choose the lowest index"
        ),
        "activation": (
            "override candidate0 iff alternative ensemble rank logit minus "
            "candidate0 ensemble rank logit is strictly greater than 0.2"
        ),
        "threshold": PROTECTED.EXPECTED_SELECTED_THRESHOLD,
        "strict_greater_than_threshold": True,
        "fallback": "candidate0",
        "bury_behavior": "unchanged incumbent",
    }
    if dict(capability) != expected_capability:
        raise ReportControllerRefused(
            "protected-anchor capability policy drift")
    return {
        "schema": REPORT.PROTECTED_POLICY_SCHEMA,
        "surface": "play",
        "head": "ranking",
        "ensemble": "arithmetic_mean_raw_rank_logits_across_eight_seeds",
        "incumbent_index": 0,
        "alternative_start_index": 1,
        "threshold": PROTECTED.EXPECTED_SELECTED_THRESHOLD,
        "strict_greater_than_threshold": True,
        "alternative_tie_break": "lowest_candidate_index",
        "fallback_index": 0,
        "bury_behavior": "unchanged_incumbent",
    }


def validate_protected_capability(
    *, packet_path: Path, packet_sha256: str, review_record: Path,
    training_aggregate: Mapping[str, object],
) -> tuple[dict, dict]:
    if (not is_regular_unlinked(packet_path)
            or sha256_file(packet_path) != packet_sha256):
        raise ReportControllerRefused(
            "protected-anchor packet path/SHA drift")
    packet = load_json(packet_path)
    authority = {
        "new_training_authorized": False,
        "training_retry_authorized": False,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "one_report_controller_freeze_authorized": False,
        "report_execution_authorized": False,
        "composition_authorized": False,
        "whole_game_screen_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    parent = packet.get("parent", {})
    manifest = packet.get("checkpoint_manifest")
    threshold_selection = packet.get("threshold_selection", {})
    if (packet.get("schema") != PROTECTED.SCHEMA
            or packet.get("packet_id") != PROTECTED.PACKET_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git")
            != "65c2b3c56e4e26af92e5710652809df72071e06f"
            or packet.get("producer", {}).get("tree_dirty") is not False
            or parent.get("training_aggregate_sha256")
            != PROTECTED.TRAINING_AGGREGATE_SHA256
            or parent.get("training_aggregate_internal_sha256")
            != PROTECTED.TRAINING_AGGREGATE_INTERNAL_SHA256
            or parent.get("terminal_decision") != "SELECT_NONE"
            or parent.get("report_rows_opened") != 0
            or training_aggregate.get("aggregate_sha256")
            != parent.get("training_aggregate_internal_sha256")
            or packet.get("authority") != authority
            or packet.get("diagnostics", {}).get("screen_gate", {}).get(
                "decision") != "REQUEST_EXTERNAL_CAPABILITY_REVIEW"
            or not isinstance(manifest, list)
            or len(manifest) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in manifest]
            != list(MODEL.TRAINING_SEEDS)
            or any(value.get("surface") != PROTECTED.SURFACE
                   or value.get("head") != PROTECTED.HEAD
                   or value.get("epoch") != PROTECTED.EPOCH
                   or value.get("curve_fraction")
                   != PROTECTED.CURVE_FRACTION
                   for value in manifest)
            or packet.get("checkpoint_manifest_sha256")
            != _manifest_hash(manifest)
            or packet.get("diagnostics_sha256")
            != _manifest_hash(packet.get("diagnostics"))
            or threshold_selection.get("grid")
            != list(PROTECTED.THRESHOLD_GRID)
            or threshold_selection.get("selection_split") != "DESIGN"
            or threshold_selection.get("selected_threshold")
            != PROTECTED.EXPECTED_SELECTED_THRESHOLD
            or threshold_selection.get("post_terminal_exploration") is not True
            or threshold_selection.get("calib_was_inspected_during_diagnosis")
            is not True
            or threshold_selection.get("calib_role")
            != "diagnostic screen only, not fresh confirmation"
            or threshold_selection.get("fresh_report_role")
            != "only untouched final offline confirmation"):
        raise ReportControllerRefused(
            "protected-anchor packet identity/authority drift")
    policy = protected_policy_contract(packet.get("capability", {}))
    claim = marker_claim(review_record, PROTECTED.REVIEW_MARKER)
    if claim != PROTECTED.expected_review_claim(packet, packet_sha256):
        raise ReportControllerRefused(
            "protected-anchor capability PASS marker drift")
    return packet, policy


def _checkpoint_manifest(
    training_packet: Mapping[str, object],
    protected_capability: Mapping[str, object],
    evidence_repo: Path,
) -> list[dict]:
    values = []
    capability = protected_capability["capability"]
    manifest = protected_capability.get("checkpoint_manifest")
    if (not isinstance(manifest, list)
            or len(manifest) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in manifest]
            != list(MODEL.TRAINING_SEEDS)):
        raise ReportControllerRefused(
            "protected-anchor checkpoint manifest population drift")
    for item in manifest:
        path = (evidence_repo / str(item["checkpoint_path"])).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item["checkpoint_sha256"]):
            raise ReportControllerRefused(
                "Stage-C selected checkpoint path/SHA drift")
        cell = next(value for value in training_packet["schedule"]["cells"]
                    if value["surface"] == capability["surface"]
                    and value["seed"] == item["seed"]
                    and value["curve_fraction"] == 1.0)
        contract = TRAIN_RUNTIME._snapshot_contract(
            training_packet, cell, int(capability["epoch"]),
            str(item["model_state_sha256"]))
        reopened = TRAIN.load_snapshot(path, expected_contract=contract)
        if reopened["model_state_sha256"] != item["model_state_sha256"]:
            raise ReportControllerRefused(
                "Stage-C selected checkpoint model-state drift")
        if item.get("checkpoint_contract") != contract:
            raise ReportControllerRefused(
                "protected-anchor checkpoint contract drift")
        values.append(dict(item))
    if values != manifest:
        raise ReportControllerRefused(
            "protected-anchor checkpoint manifest drift")
    return values


def _candidate_world_ceiling(state: Mapping[str, object]) -> int:
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ReportControllerRefused(
            "fresh REPORT state lacks a frozen candidate tensor")
    count = len(candidates)
    recipe = LABEL.recipe_for_state(state)
    if recipe == "ordinary_anchor":
        return count * (
            LABEL.ORDINARY_SELECTION_WORLDS
            + LABEL.ORDINARY_REPORT_WORLDS)
    return (count * LABEL.HARD_SELECTION_WORLDS
            + 2 * LABEL.HARD_REPORT_WORLDS)


def _selected_fresh_states(
    fresh_report: Mapping[str, object], state_set_review_record: Path,
    evidence_repo: Path,
) -> list[dict]:
    """Recompute the sealed population without publishing its material."""
    try:
        capture_packet, state_set, _verification, _review = \
            FRESH._capture_parents(
                capture_packet_path=(
                    evidence_repo / FRESH.CAPTURE_PACKET_PATH).resolve(),
                state_set_path=(
                    evidence_repo / FRESH.CAPTURE_STATE_SET_PATH).resolve(),
                verification_path=(
                    evidence_repo / FRESH.CAPTURE_VERIFICATION_PATH).resolve(),
                state_set_review_record=state_set_review_record)
        capture_shards = FRESH._report_shards(capture_packet, state_set)
        sealed, states = FRESH.sealed_selection(
            capture_packet=capture_packet, state_set=state_set,
            shards=capture_shards)
    except (FRESH.FreshReportRefused, CAPTURE.RuntimeRefused) as exc:
        raise ReportControllerRefused(
            f"fresh REPORT material reconstruction failed: {exc}") from exc
    if sealed != fresh_report.get("sealed_selection"):
        raise ReportControllerRefused(
            "fresh REPORT material differs from reviewed sealed selection")
    return states


def build_report_schedule(
    states: Sequence[Mapping[str, object]], *, surface: str,
) -> dict:
    """Partition the selected surface without publishing state identifiers."""
    if surface not in MODEL.SURFACES:
        raise ReportControllerRefused("fresh REPORT surface is unknown")
    selected = sorted(
        (state for state in states if state.get("surface_type") == surface),
        key=lambda state: str(state["state_id"]),
    )
    if (len(selected) != REPORT_SURFACE_COUNTS[surface]
            or len({str(state["state_id"]) for state in selected})
            != len(selected)):
        raise ReportControllerRefused(
            "fresh REPORT selected-surface population drift")
    shards = []
    for index in range(REPORT_SHARDS):
        population = selected[index::REPORT_SHARDS]
        ids = [str(state["state_id"]) for state in population]
        shards.append({
            "index": index,
            "state_count": len(population),
            "state_ids_sha256": _manifest_hash(ids),
            "candidate_world_ceiling": sum(
                _candidate_world_ceiling(state) for state in population),
            "result": (
                f"server/runs/logs/{RUN_ID}/labels/shard-{index:02d}.json"),
        })
    schedule = {
        "schema": "teacher-stage-c-fresh-report-schedule-v1",
        "surface": surface,
        "states": len(selected),
        "selected_surface_state_ids_sha256": _manifest_hash(
            [str(state["state_id"]) for state in selected]),
        "partition_rule": (
            "sort selected-surface states by state_id, then assign position "
            "modulo eight"),
        "shard_count": REPORT_SHARDS,
        "shards": shards,
        "candidate_world_ceiling": sum(
            int(shard["candidate_world_ceiling"]) for shard in shards),
        "audit_folds_computed": False,
        "state_material_published": False,
        "teacher_labels_computed": False,
        "model_predictions_computed": False,
    }
    schedule["schedule_sha256"] = self_hash(schedule, "schedule_sha256")
    return schedule


def build_packet(
    *, git: str, training_packet: Mapping[str, object],
    evidence_repo: Path, training_review_record: Path,
    training_aggregate: Mapping[str, object],
    training_aggregate_sha256: str,
    protected_capability: Mapping[str, object],
    protected_capability_sha256: str,
    protected_capability_review: Mapping[str, object],
    policy_contract: Mapping[str, object],
    dataset: Mapping[str, object], fresh_report: Mapping[str, object],
    fresh_report_review: Mapping[str, object],
    fresh_states: Sequence[Mapping[str, object]],
) -> dict:
    capability = protected_capability["capability"]
    surface = str(capability["surface"])
    checkpoints = _checkpoint_manifest(
        training_packet, protected_capability, evidence_repo)
    report_schedule = build_report_schedule(fresh_states, surface=surface)
    prior = TRAIN.state_balanced_prior(
        dataset["examples"]["DESIGN"][surface])
    current_runtime = runtime_contract()
    training_runtime = training_packet.get("runtime_contract", {})
    if any(training_runtime.get(key) != current_runtime[key]
           for key in ("host", "python", "torch", "numpy", "device")):
        raise ReportControllerRefused(
            "Stage-C REPORT/training runtime contract drift")
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": git,
            "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "parents": {
            "training_evidence": {
                "absolute_path": str(evidence_repo.resolve()),
                "git": PROTECTED.PARENT_GIT,
                "tracked_tree_clean": True,
                "training_review_record_absolute_path": str(
                    training_review_record.resolve()),
                "training_review_record_sha256": sha256_file(
                    training_review_record),
            },
            "training_packet": {
                "logical_path": TRAIN_CTRL.PACKET_PATH,
                "external_sha256": training_aggregate[
                    "controller_packet_sha256"],
            },
            "training_aggregate": {
                "logical_path": TRAIN_RUNTIME.AGGREGATE_PATH,
                "external_sha256": training_aggregate_sha256,
                "internal_sha256": training_aggregate["aggregate_sha256"],
            },
            "protected_capability": {
                "logical_path": PROTECTED.PACKET_PATH,
                "external_sha256": protected_capability_sha256,
                "internal_sha256": protected_capability["packet_sha256"],
                "review_claim_sha256": _manifest_hash(
                    protected_capability_review),
                "checkpoint_manifest_sha256": protected_capability[
                    "checkpoint_manifest_sha256"],
                "diagnostics_sha256": protected_capability[
                    "diagnostics_sha256"],
                "parent_terminal_decision": protected_capability[
                    "parent"]["terminal_decision"],
                "report_rows_opened": 0,
            },
            "model_dataset": {
                "logical_path": TRAIN_CTRL.DATASET_PATH,
                "external_sha256": training_aggregate[
                    "model_dataset_sha256"],
            },
            "fresh_report_selection": {
                "logical_path": FRESH.PACKET_PATH,
                "external_sha256": TRAIN_CTRL.FRESH_REPORT_PACKET_SHA256,
                "internal_sha256": fresh_report["packet_sha256"],
                "review_claim_sha256": _manifest_hash(fresh_report_review),
                "sealed_selection_sha256": fresh_report[
                    "sealed_selection"]["sealed_selection_sha256"],
                "fresh_report_state_ids_sha256": fresh_report[
                    "sealed_selection"]["fresh_report_state_ids_sha256"],
                "fresh_report_state_material_sha256": fresh_report[
                    "sealed_selection"]["fresh_report_state_material_sha256"],
                "fresh_report_states": fresh_report[
                    "sealed_selection"]["fresh_report_states"],
                "state_material_published": False,
            },
        },
        "selected_capability": dict(capability),
        "protected_policy": dict(policy_contract),
        "runtime_contract": current_runtime,
        "checkpoint_manifest": checkpoints,
        "design_prior_distribution": prior,
        "report_schedule": report_schedule,
        "report_contract": {
            "surface": surface,
            "head": capability["head"],
            "states": REPORT_SURFACE_COUNTS[surface],
            "ensemble_models": len(MODEL.TRAINING_SEEDS),
            "ensemble_seeds": list(MODEL.TRAINING_SEEDS),
            "rank_ensemble": "arithmetic mean of raw rank logits across seeds",
            "outcome_ensemble": "mean eight-bin probability across seeds",
            "protected_policy": dict(policy_contract),
            "activation_threshold": policy_contract["threshold"],
            "activation_is_strict": True,
            "tie_break": "lowest alternative candidate index",
            "primary_gate":
                "paired-state Teacher improvement vs candidate0 LCB > 0",
            "outcome_head_additional_gate":
                "REPORT outcome NLL improvement vs DESIGN prior LCB > 0",
            "critical": REPORT.REPORT_T_CRITICAL,
            "fresh_teacher_label_recipe": (
                "same finite-work iid-with-replacement Stage-C v2 label "
                "recipe; selected surface only; no audit fold"),
            "candidate_world_ceiling": report_schedule[
                "candidate_world_ceiling"],
            "v11_checkpoint_loaded": False,
            "v11_candidates_reconstructed": False,
            "captured_candidate_tensor_authenticated": True,
            "single_report_look": True,
            "durable_report_open_admission_slot":
                f"server/runs/locks/{RUN_ID}.report-open.consumed.json",
            "retry_after_report_open_or_failure_authorized": False,
            "report_cannot_change_surface_head_epoch_or_seed_population": True,
            "pass_authority": "composition packet review only",
        },
        "commands": {
            "admit": [
                "{python}",
                "server/scripts/teacher_stage_c_report_runtime.py", "admit",
                "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--fresh-report-review-record",
                "{fresh_report_review_record}",
                "--state-set-review-record", "{state_set_review_record}",
                "--out", f"server/runs/logs/{RUN_ID}/report-receipt.json",
            ],
            "run_shards": [[
                "{python}",
                "server/scripts/teacher_stage_c_report_runtime.py", "run-shard",
                "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--fresh-report-review-record",
                "{fresh_report_review_record}",
                "--state-set-review-record", "{state_set_review_record}",
                "--report-receipt",
                f"server/runs/logs/{RUN_ID}/report-receipt.json",
                "--expected-report-receipt-sha256", "{receipt_sha256}",
                "--shard-index", str(shard["index"]),
                "--progress-every", "1",
                "--out", shard["result"],
            ] for shard in report_schedule["shards"]],
            "evaluate": [
                "{python}",
                "server/scripts/teacher_stage_c_report_runtime.py", "evaluate",
                "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--fresh-report-review-record",
                "{fresh_report_review_record}",
                "--state-set-review-record", "{state_set_review_record}",
                "--report-receipt",
                f"server/runs/logs/{RUN_ID}/report-receipt.json",
                "--expected-report-receipt-sha256", "{receipt_sha256}",
                "--label-shards", *[
                    shard["result"] for shard in report_schedule["shards"]],
                "--out", f"server/runs/logs/{RUN_ID}/report-result.json",
            ],
            "supervise": [
                "{python}",
                "server/scripts/teacher_stage_c_report_supervisor.py",
                "launch",
                "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--fresh-report-review-record",
                "{fresh_report_review_record}",
                "--state-set-review-record", "{state_set_review_record}",
                "--report-receipt",
                f"server/runs/logs/{RUN_ID}/report-receipt.json",
                "--expected-report-receipt-sha256", "{receipt_sha256}",
                "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
            ],
        },
        "authority": {
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
        },
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object],
                          packet_external_sha256: str) -> dict:
    sources = packet["producer"]["sources"]
    capability = packet["selected_capability"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_report_controller.py"],
        "runtime_script_sha256": sources[
            "server/scripts/teacher_stage_c_report_runtime.py"],
        "supervisor_script_sha256": sources[
            "server/scripts/teacher_stage_c_report_supervisor.py"],
        "report_model_sha256": sources[
            "server/shengji/rl/stage_c_report.py"],
        "training_aggregate_sha256": packet["parents"][
            "training_aggregate"]["external_sha256"],
        "training_evidence_git": packet["parents"][
            "training_evidence"]["git"],
        "training_review_record_sha256": packet["parents"][
            "training_evidence"]["training_review_record_sha256"],
        "training_parent_terminal_decision": packet["parents"][
            "protected_capability"]["parent_terminal_decision"],
        "protected_capability_packet_sha256": packet["parents"][
            "protected_capability"]["external_sha256"],
        "protected_capability_review_claim_sha256": packet["parents"][
            "protected_capability"]["review_claim_sha256"],
        "selected_capability": capability,
        "protected_policy": packet["protected_policy"],
        "checkpoint_manifest_sha256": _manifest_hash(
            packet["checkpoint_manifest"]),
        "ensemble_models": len(packet["checkpoint_manifest"]),
        "fresh_report_packet_sha256": packet["parents"][
            "fresh_report_selection"]["external_sha256"],
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "report_label_shards": packet["report_schedule"]["shard_count"],
        "report_candidate_world_ceiling": packet["report_schedule"][
            "candidate_world_ceiling"],
        "report_surface_states": packet["report_contract"]["states"],
        "max_concurrent_label_shards": SUPERVISOR_MAX_WORKERS,
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_signal_contract": packet["runtime_contract"][
            "supervisor_signal_contract"],
        "activation_threshold": packet["report_contract"][
            "activation_threshold"],
        "activation_is_strict": packet["report_contract"][
            "activation_is_strict"],
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "numpy": packet["runtime_contract"]["numpy"],
        "teacher_labels_computed_before_review": 0,
        "model_predictions_computed_before_review": 0,
        "report_utility_opened_before_review": False,
        "fresh_report_state_material_published": False,
        "v11_checkpoint_loaded": False,
        "single_report_look": True,
        "report_open_admission_slot": packet["report_contract"][
            "durable_report_open_admission_slot"],
        "retry_after_report_open_or_failure_authorized": False,
        "independent_review": True,
        "one_report_execution_authorized": True,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ReportControllerRefused(f"refusing existing output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ReportControllerRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--evidence-repo", required=True)
    root.add_argument("--training-review-record", required=True)
    root.add_argument("--protected-capability-packet", required=True)
    root.add_argument(
        "--expected-protected-capability-packet-sha256", required=True)
    root.add_argument("--protected-capability-review-record", required=True)
    root.add_argument("--fresh-report-controller", required=True)
    root.add_argument("--expected-fresh-report-controller-sha256", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--out", required=True)
    root.add_argument("--expected-out-sha256")
    return root


def _validated_inputs(args) -> tuple[
        dict, dict, dict, dict, dict, dict, dict, dict, list, Path, Path]:
    if _git("status", "--porcelain"):
        raise ReportControllerRefused(
            "real Stage-C REPORT packet freeze refuses dirty tree")
    evidence_repo = Path(args.evidence_repo).resolve()
    training_review_record = Path(args.training_review_record).resolve()
    training_packet, dataset, training_aggregate = \
        validate_training_aggregate(
            evidence_repo=evidence_repo,
            training_review_record=training_review_record)
    protected_capability, policy = validate_protected_capability(
        packet_path=Path(args.protected_capability_packet).resolve(),
        packet_sha256=args.expected_protected_capability_packet_sha256,
        review_record=Path(
            args.protected_capability_review_record).resolve(),
        training_aggregate=training_aggregate)
    protected_review = marker_claim(
        Path(args.protected_capability_review_record).resolve(),
        PROTECTED.REVIEW_MARKER)
    try:
        with evidence_scope(evidence_repo):
            fresh_report, fresh_review = TRAIN_CTRL.validate_fresh_report(
                Path(args.fresh_report_controller).resolve(),
                args.expected_fresh_report_controller_sha256,
                Path(args.fresh_report_review_record).resolve(),
                Path(args.state_set_review_record).resolve())
    except TRAIN_CTRL.TrainingControllerRefused as exc:
        raise ReportControllerRefused(
            f"reviewed fresh REPORT validation failed: {exc}") from exc
    if (training_packet["parents"]["fresh_report_selection"][
            "external_sha256"]
            != args.expected_fresh_report_controller_sha256
            or dataset.get("fresh_report_selection")
            != TRAIN_CTRL.fresh_report_dataset_contract(
                fresh_report, fresh_review)
            or dataset.get("old_report_labels_quarantined") is not True
            or dataset.get("report_rows_included") is not False
            or dataset.get("fresh_report_states_materialized") is not False):
        raise ReportControllerRefused(
            "Stage-C REPORT fresh-selection/training parent drift")
    with evidence_scope(evidence_repo):
        fresh_states = _selected_fresh_states(
            fresh_report, Path(args.state_set_review_record).resolve(),
            evidence_repo)
    return (training_packet, dataset, training_aggregate,
            protected_capability, protected_review, policy,
            fresh_report, fresh_review, fresh_states,
            evidence_repo, training_review_record)


def main() -> int:
    args = parser().parse_args()
    inputs = _validated_inputs(args)
    packet = build_packet(
        git=_git("rev-parse", "HEAD"),
        training_packet=inputs[0], dataset=inputs[1],
        evidence_repo=inputs[9], training_review_record=inputs[10],
        training_aggregate=inputs[2],
        training_aggregate_sha256=PROTECTED.TRAINING_AGGREGATE_SHA256,
        protected_capability=inputs[3],
        protected_capability_sha256=
            args.expected_protected_capability_packet_sha256,
        protected_capability_review=inputs[4], policy_contract=inputs[5],
        fresh_report=inputs[6], fresh_report_review=inputs[7],
        fresh_states=inputs[8])
    out = Path(args.out).resolve()
    if out != (REPO / PACKET_PATH).resolve():
        raise ReportControllerRefused("Stage-C REPORT packet output path drift")
    if args.command == "freeze":
        publish_exclusive(out, packet)
    elif (not args.expected_out_sha256
          or sha256_file(out) != args.expected_out_sha256
          or load_json(out) != packet):
        raise ReportControllerRefused("Stage-C REPORT packet verification drift")
    print(json.dumps({
        "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
        "packet_sha256": sha256_file(out),
        "packet_internal_sha256": packet["packet_sha256"],
        "selected_capability": packet["selected_capability"],
        "fresh_report_state_material_published": False,
        "teacher_labels_computed": 0,
        "model_predictions_computed": 0,
        "report_utility_opened": False,
        "report_execution_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportControllerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
