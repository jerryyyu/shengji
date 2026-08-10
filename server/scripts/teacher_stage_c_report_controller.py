#!/usr/bin/env python3
"""Freeze the one-shot fresh-REPORT evaluator for a CALIB-selected model.

The original Stage-C REPORT labels are diagnostic-only: the V11-free route was
chosen after their V11 statistic was inspected.  This controller therefore
binds the separately reviewed fresh REPORT replacement and the exact
eight-model capability selected on DESIGN/CALIB.  It derives only a digest-
sealed, score-free eight-shard work schedule.  It does not publish state
material, compute Teacher labels, run model inference, or open REPORT utility.

After independent review, one runtime may consume the durable REPORT slot,
reconstruct the reviewed fresh states, label the already-selected surface with
the frozen finite-work Teacher, and evaluate the frozen ensemble exactly once.
V11 is neither loaded nor reconstructed on this path.
"""
from __future__ import annotations

import argparse
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
import teacher_stage_c_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_training_runtime as TRAIN_RUNTIME  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-v11-free-fresh-report-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-v11-free-fresh-report-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-v11-free-fresh-report-v1"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-v11-free-fresh-report-controller-v1"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
TRAINING_AGGREGATE_REVIEW_SCHEMA = \
    "teacher-stage-c-training-aggregate-review-v1"
TRAINING_AGGREGATE_REVIEW_MARKER = \
    "TEACHER_STAGE_C_TRAINING_AGGREGATE_V1_REVIEW "
REVIEW_SCHEMA = "teacher-stage-c-v11-free-fresh-report-controller-review-v1"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_V11_FREE_FRESH_REPORT_CONTROLLER_V1_REVIEW "

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


def expected_training_aggregate_review_claim(
    aggregate: Mapping[str, object], aggregate_external_sha256: str,
) -> dict:
    selection = aggregate.get("selection")
    ensemble = aggregate.get("selected_ensemble")
    if not isinstance(selection, dict) or not isinstance(ensemble, list):
        raise ReportControllerRefused(
            "Stage-C training selection/ensemble is missing")
    return {
        "schema": TRAINING_AGGREGATE_REVIEW_SCHEMA,
        "git": aggregate.get("git"),
        "aggregate_sha256": aggregate_external_sha256,
        "aggregate_internal_sha256": aggregate.get("aggregate_sha256"),
        "controller_packet_sha256": aggregate.get(
            "controller_packet_sha256"),
        "training_receipt_sha256": aggregate.get("training_receipt_sha256"),
        "model_dataset_sha256": aggregate.get("model_dataset_sha256"),
        "cell_count": aggregate.get("cell_count"),
        "decision": aggregate.get("decision"),
        "selection_sha256": selection.get("selection_sha256"),
        "selected_capability": selection.get("selected_capability"),
        "selected_ensemble_sha256": _manifest_hash(ensemble),
        "selected_ensemble_models": len(ensemble),
        "report_rows_opened_by_training_review": 0,
        "independent_review": True,
        "one_report_controller_freeze_authorized": True,
        "report_open_authorized": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _cell_paths(training_packet: Mapping[str, object]) -> list[Path]:
    return [(REPO / str(cell["result"])).resolve()
            for cell in training_packet["schedule"]["cells"]]


def validate_training_aggregate(
    *, training_packet_path: Path, training_packet_sha256: str,
    training_review_record: Path, training_receipt_path: Path,
    training_receipt_sha256: str, aggregate_path: Path,
    aggregate_sha256: str, aggregate_review_record: Path,
) -> tuple[dict, dict, dict, dict]:
    packet, dataset = TRAIN_RUNTIME._packet(
        training_packet_path, training_packet_sha256)
    packet["external_sha256"] = training_packet_sha256
    TRAIN_RUNTIME._receipt(
        training_receipt_path, training_receipt_sha256, packet,
        training_packet_sha256, training_review_record)
    expected = TRAIN_RUNTIME.recompute_aggregate(
        packet_path=training_packet_path,
        expected_packet_sha256=training_packet_sha256,
        receipt_path=training_receipt_path,
        expected_receipt_sha256=training_receipt_sha256,
        review_record=training_review_record,
        cell_paths=_cell_paths(packet))
    if (aggregate_path.resolve()
            != (REPO / TRAIN_RUNTIME.AGGREGATE_PATH).resolve()
            or sha256_file(aggregate_path) != aggregate_sha256
            or load_json(aggregate_path) != expected):
        raise ReportControllerRefused(
            "Stage-C training aggregate replay/path/SHA drift")
    selection = expected.get("selection", {})
    ensemble = expected.get("selected_ensemble")
    capability = selection.get("selected_capability")
    if (expected.get("decision")
            != "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW"
            or expected.get("report_packet_review_authorized") is not True
            or expected.get("report_rows_opened") != 0
            or expected.get("report_open_authorized") is not False
            or not isinstance(capability, dict)
            or capability.get("surface") not in MODEL.SURFACES
            or capability.get("head") not in MODEL.CAPABILITY_HEADS
            or capability.get("epoch") not in MODEL.EPOCH_GRID
            or not isinstance(ensemble, list)
            or len(ensemble) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in ensemble]
            != list(MODEL.TRAINING_SEEDS)
            or any(value.get("surface") != capability["surface"]
                   or value.get("head") != capability["head"]
                   or value.get("epoch") != capability["epoch"]
                   for value in ensemble)):
        raise ReportControllerRefused(
            "Stage-C training aggregate selection/authority drift")
    claim = marker_claim(
        aggregate_review_record, TRAINING_AGGREGATE_REVIEW_MARKER)
    expected_claim = expected_training_aggregate_review_claim(
        expected, aggregate_sha256)
    if claim != expected_claim:
        raise ReportControllerRefused(
            "Stage-C training aggregate PASS marker drift")
    return packet, dataset, expected, claim


def _checkpoint_manifest(
    training_packet: Mapping[str, object],
    aggregate: Mapping[str, object],
) -> list[dict]:
    values = []
    capability = aggregate["selection"]["selected_capability"]
    for item in aggregate["selected_ensemble"]:
        path = (REPO / str(item["checkpoint_path"])).resolve()
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
        values.append({
            **dict(item),
            "checkpoint_contract": contract,
        })
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
) -> list[dict]:
    """Recompute the sealed population without publishing its material."""
    try:
        capture_packet, state_set, _verification, _review = \
            FRESH._capture_parents(
                capture_packet_path=(REPO / FRESH.CAPTURE_PACKET_PATH).resolve(),
                state_set_path=(REPO / FRESH.CAPTURE_STATE_SET_PATH).resolve(),
                verification_path=(
                    REPO / FRESH.CAPTURE_VERIFICATION_PATH).resolve(),
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
    training_aggregate: Mapping[str, object],
    training_aggregate_sha256: str,
    training_aggregate_review: Mapping[str, object],
    dataset: Mapping[str, object], fresh_report: Mapping[str, object],
    fresh_report_review: Mapping[str, object],
    fresh_states: Sequence[Mapping[str, object]],
) -> dict:
    capability = training_aggregate["selection"]["selected_capability"]
    surface = str(capability["surface"])
    checkpoints = _checkpoint_manifest(
        training_packet, training_aggregate)
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
            "training_aggregate_review_claim_sha256": _manifest_hash(
                training_aggregate_review),
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
            "rank_ensemble":
                "mean within-ballot softmax probability across seeds",
            "outcome_ensemble": "mean eight-bin probability across seeds",
            "model_score_tie_epsilon": REPORT.MODEL_SCORE_TIE_EPSILON,
            "tie_break": "lowest candidate index within epsilon",
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
        "selected_capability": capability,
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
        "model_score_tie_epsilon": packet["report_contract"][
            "model_score_tie_epsilon"],
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
    root.add_argument("--training-packet", required=True)
    root.add_argument("--expected-training-packet-sha256", required=True)
    root.add_argument("--training-review-record", required=True)
    root.add_argument("--training-receipt", required=True)
    root.add_argument("--expected-training-receipt-sha256", required=True)
    root.add_argument("--training-aggregate", required=True)
    root.add_argument("--expected-training-aggregate-sha256", required=True)
    root.add_argument("--training-aggregate-review-record", required=True)
    root.add_argument("--fresh-report-controller", required=True)
    root.add_argument("--expected-fresh-report-controller-sha256", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--out", required=True)
    root.add_argument("--expected-out-sha256")
    return root


def _validated_inputs(args) -> tuple[dict, dict, dict, dict, dict, dict, list]:
    if _git("status", "--porcelain"):
        raise ReportControllerRefused(
            "real Stage-C REPORT packet freeze refuses dirty tree")
    training_packet, dataset, training_aggregate, training_review = \
        validate_training_aggregate(
            training_packet_path=Path(args.training_packet).resolve(),
            training_packet_sha256=args.expected_training_packet_sha256,
            training_review_record=Path(args.training_review_record).resolve(),
            training_receipt_path=Path(args.training_receipt).resolve(),
            training_receipt_sha256=args.expected_training_receipt_sha256,
            aggregate_path=Path(args.training_aggregate).resolve(),
            aggregate_sha256=args.expected_training_aggregate_sha256,
            aggregate_review_record=Path(
                args.training_aggregate_review_record).resolve())
    try:
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
    fresh_states = _selected_fresh_states(
        fresh_report, Path(args.state_set_review_record).resolve())
    return (training_packet, dataset, training_aggregate, training_review,
            fresh_report, fresh_review, fresh_states)


def main() -> int:
    args = parser().parse_args()
    inputs = _validated_inputs(args)
    packet = build_packet(
        git=_git("rev-parse", "HEAD"),
        training_packet=inputs[0], dataset=inputs[1],
        training_aggregate=inputs[2],
        training_aggregate_sha256=args.expected_training_aggregate_sha256,
        training_aggregate_review=inputs[3], fresh_report=inputs[4],
        fresh_report_review=inputs[5], fresh_states=inputs[6])
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
