#!/usr/bin/env python3
"""Freeze one sealed REPORT exam for the expanded Stage-C bury ensemble.

The expanded 7,040-state DESIGN/CALIB run selected one capability without
opening its third 512-state REPORT tranche: the eight-seed, epoch-32 bury
ranking ensemble trained with the original all-pairs objective.  A command
contract failure spent that third REPORT before producing evidence.  This
controller therefore authenticates all three spent REPORT populations and
binds the same capability to a fourth, genuinely untouched 512-state tranche.

Freezing and verifying are score-free.  They reconstruct the deterministic
REPORT population only to authenticate its hashes and schedule; they compute
no Teacher label, model prediction, utility, strength claim, composition,
promotion, or deployment.  A separate raw controller PASS is required before
the generic one-shot REPORT runtime may consume the durable admission.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_expanded_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_expansion_controller as EXPANSION  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
from shengji.rl import stage_c_expansion as EXP  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-expanded-fresh-report-controller-v2"
PACKET_ID = "teacher-v3-hard-tail-stage-c-expanded-fresh-report-controller-v2"
RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-fresh-report-v2"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-expanded-fresh-report-controller-v2"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"

TRAINING_RESULT_REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-training-result-review-v1"
TRAINING_RESULT_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_TRAINING_RESULT_V1_REVIEW "
REVIEW_SCHEMA = "teacher-stage-c-expanded-fresh-report-controller-review-v2"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_FRESH_REPORT_CONTROLLER_V2_REVIEW "
RECOVERY_REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-recovery-review-v2"
RECOVERY_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_FRESH_REPORT_RECOVERY_V2_REVIEW "

SPENT_REPORT_V1_PACKET_SHA256 = \
    "5ce892db48750f151eb5b24341edb043e844b4c25e6a4d7139f2cac4291525f0"
SPENT_REPORT_V1_RECEIPT_SHA256 = \
    "3c4b1f39350aa5d4a8bc46e3574da6fba21704dcef34eae642ed28ab28f674bf"
SPENT_REPORT_V1_PROGRESS_SHA256 = \
    "3867db0ce657ba5349c6ae5246d32631cdff345edfb50601ce79f7492ae9735f"
SPENT_REPORT_V1_LOG_SHA256 = \
    "b1db628539910152828e15997ba496725d66e3ba4a3a691f8774fc884bc23db5"
SPENT_REPORT_V1_REVIEW_RECORD_SHA256 = \
    "ccc61a51a1f4c602726581b0531500bdbb11107d00412d62ff25eb316e3c8441"

RUNTIME_RECEIPT_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-receipt-v2"
RUNTIME_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-admission-v2"
RUNTIME_REPORT_OPEN_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-open-admission-v2"
RUNTIME_SHARD_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-shard-admission-v2"
RUNTIME_SHARD_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-label-shard-v2"
RUNTIME_RESULT_SCHEMA = "teacher-stage-c-expanded-fresh-report-result-v2"
SUPERVISOR_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-supervisor-v2"
SUPERVISOR_EXIT_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-supervisor-exit-v2"
SUPERVISOR_FINAL_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-supervisor-final-v2"
SUPERVISOR_REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-fresh-report-result-review-v2"
SUPERVISOR_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_FRESH_REPORT_RESULT_V2_REVIEW "

TRAINING_GIT = "c18b80e04f8daa9805bf1853c8479cdfa936d9de"
TRAINING_PACKET_SHA256 = \
    "d137f31265caef8a839e0b344c8b5bebe75a76823205475da80023a639871888"
MODEL_DATASET_SHA256 = \
    "c24923f669d8333eeea0824d4dbaebf025937be7ab87e9c3cb7395aa4e5a8382"
TRAINING_RECEIPT_SHA256 = \
    "2bc3b99e55dfe07c6d28989f585ec31b0d62f6363cf5f49f3555ff7d1c0d7f5f"
TRAINING_AGGREGATE_SHA256 = \
    "5ad77eb0addbfc91c4a96bddc702da769eba681736297e5b17ff6f4230cfb6bd"
TRAINING_AGGREGATE_INTERNAL_SHA256 = \
    "44974a594634a36256690d5daec475fb4e554b3ec7cb35f2ae4dabdfb25fa729"
TRAINING_SUPERVISOR_FINAL_SHA256 = \
    "be17e50e53bee70b2d14c2098b75dd504917b06493488b24ba1e16f6f51d71e4"
TRAINING_SUPERVISOR_FINAL_INTERNAL_SHA256 = \
    "0a2d3b20106501aa4a8fac973dab131a3c670fd0506d12b0f917765c915f8956"
TRAINING_PROGRESS_SHA256 = \
    "ebce92e001f239da1a8065be43d8653cc9ca51cf326f5e58cf293320e34418fe"
TRAINING_REVIEW_RECORD_SHA256 = \
    "5c458daf5e3d5d742554ddabfbd46a773dfdb432ee6a1666ac1945fe3222685a"

TRAINING_RECEIPT_PATH = \
    f"server/runs/logs/{TRAIN_CTRL.RUN_ID}/training-receipt.json"
TRAINING_AGGREGATE_PATH = \
    f"server/runs/logs/{TRAIN_CTRL.RUN_ID}/training-aggregate.json"
TRAINING_FINAL_PATH = \
    f"server/runs/logs/{TRAIN_CTRL.RUN_ID}/training-supervisor-final.json"
TRAINING_PROGRESS_PATH = \
    f"server/runs/logs/{TRAIN_CTRL.RUN_ID}/training-supervisor.jsonl"

REPORT_SURFACE_COUNTS = {"play": 480, "bury": 32}
REPORT_SHARDS = 8
SUPERVISOR_MAX_WORKERS = 8
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
RUNTIME_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_expanded_report_runtime.py"
SUPERVISOR_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_expanded_report_supervisor.py"

SOURCE_PATHS = tuple(dict.fromkeys((
    "server/scripts/teacher_stage_c_expanded_report_controller.py",
    RUNTIME_SCRIPT_PATH,
    SUPERVISOR_SCRIPT_PATH,
    "server/scripts/teacher_stage_c_report_runtime.py",
    "server/scripts/teacher_stage_c_report_supervisor.py",
    "server/shengji/rl/stage_c_report.py",
    *TRAIN_CTRL.SOURCE_PATHS,
    *EXPANSION.SOURCE_PATHS,
)))


class ReportControllerRefused(RuntimeError):
    """A terminal training, sealed state, checkpoint, or authority drifted."""


canonical_json = TRAIN_CTRL.canonical_json
sha256_bytes = TRAIN_CTRL.sha256_bytes
sha256_file = TRAIN_CTRL.sha256_file
self_hash = TRAIN_CTRL.self_hash


def _manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


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


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


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


def _source_sha256s() -> dict[str, str]:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ReportControllerRefused(
                f"expanded REPORT source unavailable: {logical}")
        values[logical] = sha256_file(path)
    return dict(sorted(values.items()))


def runtime_contract() -> dict:
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


def _selected_capability(aggregate: Mapping[str, object]) -> dict:
    value = aggregate.get("selection", {}).get("selected_capability")
    expected = {
        "loss_recipe": "all_pairs_v1",
        "surface": "bury",
        "head": "ranking",
        "epoch": 32,
        "action_improvement_positive_seeds": 8,
        "calibration_positive_seeds": 8,
        "median_action_improvement_vs_candidate0": 0.01641845703125,
        "mean_teacher_regret": 0.1615142822265625,
        "median_outcome_nll_improvement": 0.02034193337756174,
    }
    if not isinstance(value, dict) or any(
            value.get(key) != item for key, item in expected.items()):
        raise ReportControllerRefused(
            "expanded training selected capability drift")
    return expected


def expected_training_result_review_claim(
    aggregate: Mapping[str, object], receipt: Mapping[str, object],
    final: Mapping[str, object],
) -> dict:
    capability = _selected_capability(aggregate)
    return {
        "schema": TRAINING_RESULT_REVIEW_SCHEMA,
        "git": TRAINING_GIT,
        "controller_packet_sha256": TRAINING_PACKET_SHA256,
        "training_receipt_sha256": TRAINING_RECEIPT_SHA256,
        "training_receipt_internal_sha256": receipt["receipt_sha256"],
        "controller_review_record_sha256": TRAINING_REVIEW_RECORD_SHA256,
        "schedule_sha256": aggregate["schedule_sha256"],
        "training_aggregate_sha256": TRAINING_AGGREGATE_SHA256,
        "training_aggregate_internal_sha256": aggregate["aggregate_sha256"],
        "supervisor_final_sha256": TRAINING_SUPERVISOR_FINAL_SHA256,
        "supervisor_final_internal_sha256": final["final_sha256"],
        "supervisor_progress_sha256": TRAINING_PROGRESS_SHA256,
        "cells_complete": 96,
        "checkpoints_reopened": 576,
        "terminal_jobs_reopened": 97,
        "full_aggregate_recomputed": True,
        "decision": "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW",
        "selection_sha256": aggregate["selection"]["selection_sha256"],
        "selected_capability": capability,
        "selected_ensemble_models": 8,
        "single_capability_selection": True,
        "single_seed_selection": False,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "one_expanded_report_controller_freeze_authorized": True,
        "retry_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "independent_review": True,
        "verdict": "PASS",
    }


def _evidence_path(root: Path, logical: str, expected_sha256: str) -> Path:
    path = (root / logical).resolve()
    if (not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportControllerRefused(
            f"expanded training evidence drift: {logical}")
    return path


def _checkpoint_contract(
    packet: Mapping[str, object], cell: Mapping[str, object],
    item: Mapping[str, object],
) -> dict:
    value = MODEL.checkpoint_contract(
        surface=str(cell["surface"]), seed=int(cell["seed"]),
        epoch=int(item["epoch"]),
        curve_fraction=float(cell["curve_fraction"]),
        state_dict_sha256=str(item["model_state_sha256"]),
        loss_recipe=str(cell["loss_recipe"]))
    value.update({
        "run_id": TRAIN_CTRL.RUN_ID,
        "cell_id": cell["cell_id"],
        "controller_packet_sha256": TRAINING_PACKET_SHA256,
        "model_dataset_sha256": MODEL_DATASET_SHA256,
        "report_rows_opened": 0,
    })
    return value


def _checkpoint_manifest(
    *, evidence_repo: Path, packet: Mapping[str, object],
    aggregate: Mapping[str, object], reopen: bool,
) -> list[dict]:
    capability = _selected_capability(aggregate)
    raw = aggregate.get("selected_ensemble")
    if (not isinstance(raw, list) or len(raw) != len(MODEL.TRAINING_SEEDS)
            or [item.get("seed") for item in raw]
            != list(MODEL.TRAINING_SEEDS)):
        raise ReportControllerRefused(
            "expanded selected ensemble population drift")
    result = []
    for item in raw:
        if (item.get("surface") != capability["surface"]
                or item.get("head") != capability["head"]
                or item.get("epoch") != capability["epoch"]
                or item.get("loss_recipe") != capability["loss_recipe"]):
            raise ReportControllerRefused(
                "expanded selected checkpoint capability drift")
        cell = next((value for value in packet["schedule"]["cells"]
                     if value["surface"] == item["surface"]
                     and value["loss_recipe"] == item["loss_recipe"]
                     and value["seed"] == item["seed"]
                     and value["curve_fraction"] == 1.0), None)
        if cell is None:
            raise ReportControllerRefused(
                "expanded selected checkpoint cell missing")
        path = (evidence_repo / str(item["checkpoint_path"])).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item["checkpoint_sha256"]):
            raise ReportControllerRefused(
                "expanded selected checkpoint external identity drift")
        contract = _checkpoint_contract(packet, cell, item)
        if reopen:
            snapshot = TRAIN.load_snapshot(path, expected_contract=contract)
            if snapshot["model_state_sha256"] != item["model_state_sha256"]:
                raise ReportControllerRefused(
                    "expanded selected checkpoint model-state drift")
        result.append({**dict(item), "checkpoint_contract": contract})
    return result


def validate_training_evidence(
    *, evidence_repo: Path, training_result_review_record: Path,
    reopen_checkpoints: bool,
) -> tuple[dict, dict, dict, dict, dict, list[dict]]:
    evidence_repo = evidence_repo.resolve()
    if (_git("rev-parse", "HEAD", cwd=evidence_repo) != TRAINING_GIT
            or _git("status", "--porcelain", "--untracked-files=no",
                    cwd=evidence_repo)):
        raise ReportControllerRefused("expanded training evidence Git drift")
    packet_path = _evidence_path(
        evidence_repo, TRAIN_CTRL.PACKET_PATH, TRAINING_PACKET_SHA256)
    dataset_path = _evidence_path(
        evidence_repo, TRAIN_CTRL.DATASET_PATH, MODEL_DATASET_SHA256)
    receipt_path = _evidence_path(
        evidence_repo, TRAINING_RECEIPT_PATH, TRAINING_RECEIPT_SHA256)
    aggregate_path = _evidence_path(
        evidence_repo, TRAINING_AGGREGATE_PATH, TRAINING_AGGREGATE_SHA256)
    final_path = _evidence_path(
        evidence_repo, TRAINING_FINAL_PATH,
        TRAINING_SUPERVISOR_FINAL_SHA256)
    _evidence_path(
        evidence_repo, TRAINING_PROGRESS_PATH, TRAINING_PROGRESS_SHA256)
    packet = load_json(packet_path)
    dataset = load_json(dataset_path)
    receipt = load_json(receipt_path)
    aggregate = load_json(aggregate_path)
    final = load_json(final_path)
    if (packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or dataset.get("dataset_sha256")
            != self_hash(dataset, "dataset_sha256")
            or receipt.get("receipt_sha256")
            != self_hash(receipt, "receipt_sha256")
            or aggregate.get("aggregate_sha256")
            != self_hash(aggregate, "aggregate_sha256")
            or final.get("final_sha256") != self_hash(final, "final_sha256")):
        raise ReportControllerRefused(
            "expanded terminal evidence internal hash drift")
    try:
        TRAIN_CTRL.validate_runtime_dataset(dataset)
        TRAIN_CTRL.validate_runtime_packet_parents(packet, dataset)
    except TRAIN_CTRL.TrainingControllerRefused as exc:
        raise ReportControllerRefused(str(exc)) from exc
    selection = aggregate.get("selection", {})
    if (packet.get("producer", {}).get("git") != TRAINING_GIT
            or aggregate.get("git") != TRAINING_GIT
            or final.get("git") != TRAINING_GIT
            or receipt.get("git") != TRAINING_GIT
            or receipt.get("controller_packet_sha256")
            != TRAINING_PACKET_SHA256
            or receipt.get("controller_review_record_sha256")
            != TRAINING_REVIEW_RECORD_SHA256
            or receipt.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or aggregate.get("controller_packet_sha256")
            != TRAINING_PACKET_SHA256
            or aggregate.get("training_receipt_sha256")
            != TRAINING_RECEIPT_SHA256
            or aggregate.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or aggregate.get("cell_count") != 96
            or aggregate.get("decision")
            != "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW"
            or aggregate.get("report_packet_review_authorized") is not True
            or aggregate.get("report_rows_opened") != 0
            or aggregate.get("report_open_authorized") is not False
            or aggregate.get("strength_claim") is not False
            or selection.get("single_capability_selection") is not True
            or selection.get("single_seed_selection") is not False
            or final.get("cells_complete") != 96
            or final.get("jobs") is None or len(final["jobs"]) != 97
            or final.get("aggregate_sha256") != TRAINING_AGGREGATE_SHA256
            or final.get("progress_sha256") != TRAINING_PROGRESS_SHA256
            or final.get("retry_authorized") is not False):
        raise ReportControllerRefused(
            "expanded terminal selection/authority drift")
    claim = marker_claim(
        training_result_review_record, TRAINING_RESULT_REVIEW_MARKER)
    if claim != expected_training_result_review_claim(
            aggregate, receipt, final):
        raise ReportControllerRefused(
            "expanded training-result PASS marker drift")
    for item in final["jobs"]:
        for path_key, sha_key in (
                ("output_path", "output_sha256"),
                ("log_path", "log_sha256"),
                ("exit_path", "exit_sha256")):
            _evidence_path(
                evidence_repo, str(item[path_key]), str(item[sha_key]))
        exit_value = load_json(evidence_repo / str(item["exit_path"]))
        if exit_value.get("returncode") != 0:
            raise ReportControllerRefused(
                "expanded terminal job did not exit cleanly")
    manifest = _checkpoint_manifest(
        evidence_repo=evidence_repo, packet=packet, aggregate=aggregate,
        reopen=reopen_checkpoints)
    return packet, dataset, receipt, aggregate, final, manifest


def _selected_report_states(
    *, capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path,
) -> tuple[dict, dict, list[dict]]:
    try:
        parents = EXPANSION.validate_evidence(
            evidence_repo=capture_evidence_repo,
            state_set_review_record=state_set_review_record,
            fresh_report_review_record=fresh_report_review_record)
        capture, original, _verification, _state_review, shards, current = \
            parents
        spent_selection = EXP.select_expanded_states(
            capture_packet=capture,
            retained_states=[state for shard in shards
                             for state in shard["retained_states"]],
            original_states=original["states"],
            current_fresh_report_states=current)
        selection = EXP.select_successor_report_states(
            capture_packet=capture,
            retained_states=[state for shard in shards
                             for state in shard["retained_states"]],
            original_states=original["states"],
            current_fresh_report_states=current)
    except (EXPANSION.ExpansionControllerRefused,
            EXP.ExpansionError) as exc:
        raise ReportControllerRefused(
            f"expanded REPORT selection reconstruction refused: {exc}") \
            from exc
    states = list(selection["states"])
    if (len(states) != EXP.SEALED_REPORT_STATES
            or selection.get("spent_report_populations") != 3
            or selection.get("spent_state_overlap") != 0
            or selection.get("spent_deal_seed_overlap") != 0
            or selection.get("labels_or_outcomes_opened") is not False
            or selection.get("report_labels_opened") is not False):
        raise ReportControllerRefused(
            "expanded REPORT selected population drift")
    return spent_selection, selection, states


def expected_recovery_review_claim(
    selection: Mapping[str, object], *, git: str | None = None,
) -> dict:
    """Describe the only authority that may freeze a fourth-REPORT packet."""
    if (selection.get("schema") != EXP.SUCCESSOR_REPORT_SCHEMA
            or selection.get("state_count") != EXP.SEALED_REPORT_STATES
            or selection.get("surface_counts") != REPORT_SURFACE_COUNTS
            or selection.get("spent_report_populations") != 3
            or selection.get("spent_report_states") != 1_536
            or selection.get("spent_state_overlap") != 0
            or selection.get("spent_deal_seed_overlap") != 0
            or selection.get("labels_or_outcomes_opened") is not False
            or selection.get("report_labels_opened") is not False
            or selection.get("selection_sha256")
            != _manifest_hash({key: value for key, value in selection.items()
                               if key != "selection_sha256"})):
        raise ReportControllerRefused(
            "expanded REPORT recovery selection drift")
    sources = _source_sha256s()
    return {
        "schema": RECOVERY_REVIEW_SCHEMA,
        "git": git if git is not None else _git("rev-parse", "HEAD"),
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_expanded_report_controller.py"],
        "selection_script_sha256": sources[
            "server/shengji/rl/stage_c_expansion.py"],
        "command_contract_test_sha256": sha256_file(
            REPO / "server/tests/"
            "test_teacher_stage_c_expanded_report_controller.py"),
        "spent_report_v1_packet_sha256": SPENT_REPORT_V1_PACKET_SHA256,
        "spent_report_v1_receipt_sha256": SPENT_REPORT_V1_RECEIPT_SHA256,
        "spent_report_v1_progress_partial_sha256":
            SPENT_REPORT_V1_PROGRESS_SHA256,
        "spent_report_v1_log_sha256": SPENT_REPORT_V1_LOG_SHA256,
        "spent_report_v1_review_record_sha256":
            SPENT_REPORT_V1_REVIEW_RECORD_SHA256,
        "spent_report_v1_children": 8,
        "spent_report_v1_child_returncode": 2,
        "spent_report_v1_labels_predictions_utility_results": 0,
        "spent_report_v1_namespace_terminal": True,
        "successor_report_selection_sha256": selection[
            "selection_sha256"],
        "successor_report_state_ids_sha256": selection[
            "state_ids_sha256"],
        "successor_report_state_material_sha256": selection[
            "states_sha256"],
        "successor_report_states": selection["state_count"],
        "successor_report_surface_counts": selection["surface_counts"],
        "prior_report_populations_spent": selection[
            "spent_report_populations"],
        "prior_report_states": selection["spent_report_states"],
        "prior_report_state_overlap": selection["spent_state_overlap"],
        "prior_report_deal_seed_overlap": selection[
            "spent_deal_seed_overlap"],
        "remaining_report_supply_after_selection": selection[
            "remaining_report_supply_after_selection"],
        "command_templates_parse": True,
        "one_score_free_v2_packet_freeze_authorized": True,
        "report_execution_authorized": False,
        "retry_authorized": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "independent_review": True,
        "verdict": "PASS",
    }


def validate_recovery_review(
    path: Path, selection: Mapping[str, object],
) -> dict:
    claim = marker_claim(path, RECOVERY_REVIEW_MARKER)
    if claim != expected_recovery_review_claim(selection):
        raise ReportControllerRefused(
            "expanded REPORT recovery PASS marker drift")
    return claim


def _candidate_world_ceiling(state: Mapping[str, object]) -> int:
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ReportControllerRefused(
            "expanded REPORT state lacks candidates")
    count = len(candidates)
    recipe = LABEL.recipe_for_state(state)
    if recipe == "ordinary_anchor":
        return count * (
            LABEL.ORDINARY_SELECTION_WORLDS + LABEL.ORDINARY_REPORT_WORLDS)
    return (count * LABEL.HARD_SELECTION_WORLDS
            + 2 * LABEL.HARD_REPORT_WORLDS)


def build_report_schedule(
    states: Sequence[Mapping[str, object]], *, surface: str,
) -> dict:
    selected = sorted(
        (state for state in states if state.get("surface_type") == surface),
        key=lambda state: str(state["state_id"]))
    if (surface not in REPORT_SURFACE_COUNTS
            or len(selected) != REPORT_SURFACE_COUNTS[surface]
            or len({str(state["state_id"]) for state in selected})
            != len(selected)):
        raise ReportControllerRefused(
            "expanded REPORT selected-surface population drift")
    shards = []
    for index in range(REPORT_SHARDS):
        population = selected[index::REPORT_SHARDS]
        shards.append({
            "index": index,
            "state_count": len(population),
            "state_ids_sha256": _manifest_hash([
                str(state["state_id"]) for state in population]),
            "candidate_world_ceiling": sum(
                _candidate_world_ceiling(state) for state in population),
            "result": f"server/runs/logs/{RUN_ID}/labels/shard-{index:02d}.json",
        })
    value = {
        "schema": "teacher-stage-c-expanded-fresh-report-schedule-v1",
        "surface": surface,
        "states": len(selected),
        "selected_surface_state_ids_sha256": _manifest_hash([
            str(state["state_id"]) for state in selected]),
        "partition_rule": (
            "sort selected-surface states by state_id, then assign position "
            "modulo eight"),
        "shard_count": REPORT_SHARDS,
        "shards": shards,
        "candidate_world_ceiling": sum(
            int(shard["candidate_world_ceiling"]) for shard in shards),
    }
    value["schedule_sha256"] = _manifest_hash(value)
    return value


def _commands(schedule: Mapping[str, object]) -> dict:
    common = [
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
        "--fresh-report-review-record", "{fresh_report_review_record}",
        "--state-set-review-record", "{state_set_review_record}",
        "--report-receipt", f"server/runs/logs/{RUN_ID}/report-receipt.json",
        "--expected-report-receipt-sha256", "{receipt_sha256}",
    ]
    return {
        "admit": [
            "{python}", RUNTIME_SCRIPT_PATH, "admit",
            "--expected-git", "{git}",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{controller_review_record}",
            "--fresh-report-review-record", "{fresh_report_review_record}",
            "--state-set-review-record", "{state_set_review_record}",
            "--out", f"server/runs/logs/{RUN_ID}/report-receipt.json",
        ],
        "run_shards": [[
            "{python}", RUNTIME_SCRIPT_PATH, "run-shard", *common,
            "--shard-index", str(shard["index"]),
            "--progress-every", "1", "--out", shard["result"],
        ] for shard in schedule["shards"]],
        "evaluate": [
            "{python}", RUNTIME_SCRIPT_PATH, "evaluate", *common,
            "--label-shards", *[shard["result"]
                                 for shard in schedule["shards"]],
            "--out", f"server/runs/logs/{RUN_ID}/report-result.json",
        ],
        "supervise": [
            "{python}", SUPERVISOR_SCRIPT_PATH, "launch",
            "--expected-git", "{git}",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{controller_review_record}",
            "--fresh-report-review-record", "{fresh_report_review_record}",
            "--state-set-review-record", "{state_set_review_record}",
            "--report-receipt", f"server/runs/logs/{RUN_ID}/report-receipt.json",
            "--expected-report-receipt-sha256", "{receipt_sha256}",
            "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
        ],
    }


def build_packet(
    *, git: str, evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, recovery_review_record: Path,
    training_packet: Mapping[str, object],
    dataset: Mapping[str, object], aggregate: Mapping[str, object],
    manifest: Sequence[Mapping[str, object]],
    spent_selection: Mapping[str, object],
    selection: Mapping[str, object], report_states: Sequence[Mapping[str, object]],
) -> dict:
    capability = _selected_capability(aggregate)
    schedule = build_report_schedule(report_states, surface="bury")
    sealed = dataset["sealed_report_selection"]
    spent_states = [state for state in spent_selection["states"]
                    if state.get("split") == "REPORT"]
    if (sealed.get("state_ids_sha256")
            != spent_selection["sealed_report_state_ids_sha256"]
            or sealed.get("state_material_sha256") != _manifest_hash([
                state for state in spent_states])
            or sealed.get("states") != len(report_states)
            or sealed.get("surface_counts") != {"play": 480, "bury": 32}
            or sealed.get("state_material_published") is not False
            or sealed.get("labels_or_predictions_computed") is not False):
        raise ReportControllerRefused(
            "expanded sealed REPORT dataset binding drift")
    if (selection.get("state_count") != len(report_states)
            or selection.get("surface_counts") != REPORT_SURFACE_COUNTS
            or selection.get("spent_report_populations") != 3
            or selection.get("spent_state_overlap") != 0
            or selection.get("spent_deal_seed_overlap") != 0
            or selection.get("labels_or_outcomes_opened") is not False
            or selection.get("report_labels_opened") is not False):
        raise ReportControllerRefused(
            "expanded successor REPORT selection drift")
    prior = TRAIN.state_balanced_prior(
        dataset["examples"]["DESIGN"]["bury"])
    result = {
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
                "git": TRAINING_GIT,
                "tracked_tree_clean": True,
                "training_result_review_record_absolute_path": str(
                    training_result_review_record.resolve()),
                "training_result_review_record_sha256": sha256_file(
                    training_result_review_record),
            },
            "training_packet": {
                "logical_path": TRAIN_CTRL.PACKET_PATH,
                "external_sha256": TRAINING_PACKET_SHA256,
                "internal_sha256": training_packet["packet_sha256"],
            },
            "training_aggregate": {
                "logical_path": TRAINING_AGGREGATE_PATH,
                "external_sha256": TRAINING_AGGREGATE_SHA256,
                "internal_sha256": aggregate["aggregate_sha256"],
                "selection_sha256": aggregate["selection"][
                    "selection_sha256"],
            },
            "model_dataset": {
                "logical_path": TRAIN_CTRL.DATASET_PATH,
                "external_sha256": MODEL_DATASET_SHA256,
                "internal_sha256": dataset["dataset_sha256"],
            },
            "spent_expanded_report_selection": {
                "sealed_selection_sha256": _manifest_hash(sealed),
                "state_ids_sha256": sealed["state_ids_sha256"],
                "state_material_sha256": sealed["state_material_sha256"],
                "states": sealed["states"],
                "state_material_published": False,
            },
            "capture_evidence": {
                "absolute_path": str(capture_evidence_repo.resolve()),
                "git": EXPANSION.EVIDENCE_GIT,
                "state_set_review_record_sha256": sha256_file(
                    state_set_review_record),
                "fresh_report_review_record_sha256": sha256_file(
                    fresh_report_review_record),
            },
            "recovery_review": {
                "absolute_path": str(recovery_review_record.resolve()),
                "sha256": sha256_file(recovery_review_record),
                "claim_sha256": _manifest_hash(marker_claim(
                    recovery_review_record, RECOVERY_REVIEW_MARKER)),
                "one_score_free_v2_packet_freeze_authorized": True,
                "report_execution_authorized": False,
            },
            # Keep this generic alias for the shared one-shot runtime.
            "fresh_report_selection": {
                "sealed_selection_sha256": selection["selection_sha256"],
                "fresh_report_state_ids_sha256": selection[
                    "state_ids_sha256"],
                "fresh_report_state_material_sha256": selection[
                    "states_sha256"],
                "fresh_report_states": selection["state_count"],
                "spent_report_populations": selection[
                    "spent_report_populations"],
                "spent_report_state_ids_sha256": selection[
                    "spent_report_state_ids_sha256"],
                "spent_report_deal_seeds_sha256": selection[
                    "spent_report_deal_seeds_sha256"],
                "spent_state_overlap": selection["spent_state_overlap"],
                "spent_deal_seed_overlap": selection[
                    "spent_deal_seed_overlap"],
                "remaining_report_supply_after_selection": selection[
                    "remaining_report_supply_after_selection"],
                "state_material_published": False,
            },
        },
        "selected_capability": capability,
        "protected_policy": None,
        "checkpoint_manifest": [dict(value) for value in manifest],
        "design_prior_distribution": prior,
        "runtime_contract": runtime_contract(),
        "report_schedule": schedule,
        "report_contract": {
            "surface": "bury",
            "head": "ranking",
            "states": 32,
            "candidate_world_ceiling": schedule[
                "candidate_world_ceiling"],
            "v11_checkpoint_loaded": False,
            "v11_candidates_reconstructed": False,
            "captured_candidate_tensor_authenticated": True,
            "single_report_look": True,
            "report_population_ordinal": 4,
            "prior_report_populations_spent": 3,
            "prior_report_state_overlap": 0,
            "prior_report_deal_seed_overlap": 0,
            "protected_policy": None,
            "model_score_tie_epsilon": REPORT.MODEL_SCORE_TIE_EPSILON,
            "rank_ensemble": (
                "mean within-ballot softmax probability across seeds"),
            "tie_break": "lowest candidate index within epsilon",
            "durable_report_open_admission_slot": (
                f"server/runs/locks/{RUN_ID}.report-open.consumed.json"),
            "retry_after_report_open_or_failure_authorized": False,
            "report_cannot_change_surface_head_epoch_or_seed_population":
                True,
        },
        "commands": _commands(schedule),
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
    result["packet_sha256"] = self_hash(result, "packet_sha256")
    return result


def expected_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
) -> dict:
    sources = packet["producer"]["sources"]
    capability = packet["selected_capability"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_expanded_report_controller.py"],
        "runtime_wrapper_sha256": sources[RUNTIME_SCRIPT_PATH],
        "supervisor_wrapper_sha256": sources[SUPERVISOR_SCRIPT_PATH],
        "shared_runtime_sha256": sources[
            "server/scripts/teacher_stage_c_report_runtime.py"],
        "shared_supervisor_sha256": sources[
            "server/scripts/teacher_stage_c_report_supervisor.py"],
        "training_aggregate_sha256": TRAINING_AGGREGATE_SHA256,
        "training_result_review_record_sha256": packet["parents"][
            "training_evidence"]["training_result_review_record_sha256"],
        "recovery_review_record_sha256": packet["parents"][
            "recovery_review"]["sha256"],
        "recovery_review_claim_sha256": packet["parents"][
            "recovery_review"]["claim_sha256"],
        "selected_capability": capability,
        "checkpoint_manifest_sha256": _manifest_hash(
            packet["checkpoint_manifest"]),
        "ensemble_models": len(packet["checkpoint_manifest"]),
        "sealed_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "report_label_shards": REPORT_SHARDS,
        "report_surface_states": packet["report_contract"]["states"],
        "report_candidate_world_ceiling": packet["report_schedule"][
            "candidate_world_ceiling"],
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "numpy": packet["runtime_contract"]["numpy"],
        "teacher_labels_computed_before_review": 0,
        "model_predictions_computed_before_review": 0,
        "report_utility_opened_before_review": False,
        "fresh_report_state_material_published": False,
        "report_population_ordinal": packet["report_contract"][
            "report_population_ordinal"],
        "prior_report_populations_spent": packet["report_contract"][
            "prior_report_populations_spent"],
        "prior_report_state_overlap": packet["report_contract"][
            "prior_report_state_overlap"],
        "prior_report_deal_seed_overlap": packet["report_contract"][
            "prior_report_deal_seed_overlap"],
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


def _build_inputs(
    *, evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, recovery_review_record: Path,
    reopen_checkpoints: bool,
) -> tuple[dict, dict, dict, list[dict], dict, dict, list[dict]]:
    packet, dataset, _receipt, aggregate, _final, manifest = \
        validate_training_evidence(
            evidence_repo=evidence_repo,
            training_result_review_record=training_result_review_record,
            reopen_checkpoints=reopen_checkpoints)
    spent_selection, selection, report_states = _selected_report_states(
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record)
    validate_recovery_review(recovery_review_record, selection)
    return (packet, dataset, aggregate, manifest, spent_selection, selection,
            report_states)


def freeze(
    *, evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, recovery_review_record: Path,
    out: Path, smoke: bool,
) -> dict:
    if (_git("status", "--porcelain", "--untracked-files=all") and not smoke):
        raise ReportControllerRefused(
            "real expanded REPORT freeze refuses dirty tree")
    if out.resolve() != (REPO / PACKET_PATH).resolve():
        raise ReportControllerRefused("expanded REPORT output path drift")
    values = _build_inputs(
        evidence_repo=evidence_repo,
        training_result_review_record=training_result_review_record,
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        recovery_review_record=recovery_review_record,
        reopen_checkpoints=True)
    packet = build_packet(
        git=_git("rev-parse", "HEAD"), evidence_repo=evidence_repo,
        training_result_review_record=training_result_review_record,
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        recovery_review_record=recovery_review_record,
        training_packet=values[0], dataset=values[1], aggregate=values[2],
        manifest=values[3], spent_selection=values[4],
        selection=values[5], report_states=values[6])
    publish_exclusive(out, packet)
    return packet


def verify_frozen(
    *, evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, recovery_review_record: Path,
    packet_path: Path,
    expected_packet_sha256: str, smoke: bool,
) -> dict:
    if (packet_path.resolve() != (REPO / PACKET_PATH).resolve()
            or not is_regular_unlinked(packet_path)
            or sha256_file(packet_path) != expected_packet_sha256):
        raise ReportControllerRefused(
            "expanded REPORT frozen packet path/SHA drift")
    if (_git("status", "--porcelain", "--untracked-files=all") and not smoke):
        raise ReportControllerRefused(
            "real expanded REPORT verify refuses dirty tree")
    values = _build_inputs(
        evidence_repo=evidence_repo,
        training_result_review_record=training_result_review_record,
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        recovery_review_record=recovery_review_record,
        reopen_checkpoints=True)
    rebuilt = build_packet(
        git=_git("rev-parse", "HEAD"), evidence_repo=evidence_repo,
        training_result_review_record=training_result_review_record,
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        recovery_review_record=recovery_review_record,
        training_packet=values[0], dataset=values[1], aggregate=values[2],
        manifest=values[3], spent_selection=values[4],
        selection=values[5], report_states=values[6])
    if (load_json(packet_path) != rebuilt
            or packet_path.read_bytes() != canonical_json(rebuilt)):
        raise ReportControllerRefused(
            "expanded REPORT frozen packet recomputation drift")
    return rebuilt


def validate_runtime_packet(
    *, path: Path, expected_sha256: str,
    fresh_report_review_record: Path, state_set_review_record: Path,
) -> tuple[dict, dict, dict, dict, list[dict]]:
    if (path.resolve() != (REPO / PACKET_PATH).resolve()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportControllerRefused(
            "expanded REPORT runtime packet path/SHA drift")
    frozen = load_json(path)
    evidence = frozen.get("parents", {}).get("training_evidence", {})
    capture = frozen.get("parents", {}).get("capture_evidence", {})
    recovery = frozen.get("parents", {}).get("recovery_review", {})
    training_review = Path(str(
        evidence.get("training_result_review_record_absolute_path"))).resolve()
    recovery_review = Path(str(recovery.get("absolute_path"))).resolve()
    if (not is_regular_unlinked(training_review)
            or sha256_file(training_review)
            != evidence.get("training_result_review_record_sha256")
            or sha256_file(state_set_review_record)
            != capture.get("state_set_review_record_sha256")
            or sha256_file(fresh_report_review_record)
            != capture.get("fresh_report_review_record_sha256")
            or not is_regular_unlinked(recovery_review)
            or sha256_file(recovery_review) != recovery.get("sha256")):
        raise ReportControllerRefused(
            "expanded REPORT runtime review-record drift")
    values = _build_inputs(
        evidence_repo=Path(str(evidence.get("absolute_path"))).resolve(),
        training_result_review_record=training_review,
        capture_evidence_repo=Path(str(capture.get("absolute_path"))).resolve(),
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        recovery_review_record=recovery_review,
        reopen_checkpoints=False)
    rebuilt = build_packet(
        git=_git("rev-parse", "HEAD"),
        evidence_repo=Path(str(evidence["absolute_path"])),
        training_result_review_record=training_review,
        capture_evidence_repo=Path(str(capture["absolute_path"])),
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        recovery_review_record=recovery_review,
        training_packet=values[0], dataset=values[1], aggregate=values[2],
        manifest=values[3], spent_selection=values[4],
        selection=values[5], report_states=values[6])
    if (frozen != rebuilt or frozen.get("packet_sha256")
            != self_hash(frozen, "packet_sha256")):
        raise ReportControllerRefused(
            "expanded REPORT runtime packet recomputation drift")
    return frozen, values[1], values[0], values[5], values[6]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--evidence-repo", required=True)
    root.add_argument("--training-result-review-record", required=True)
    root.add_argument("--capture-evidence-repo", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--recovery-review-record", required=True)
    root.add_argument("--out", default=PACKET_PATH)
    root.add_argument("--expected-packet-sha256")
    root.add_argument("--smoke", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    common = {
        "evidence_repo": Path(args.evidence_repo).resolve(),
        "training_result_review_record": Path(
            args.training_result_review_record).resolve(),
        "capture_evidence_repo": Path(args.capture_evidence_repo).resolve(),
        "state_set_review_record": Path(
            args.state_set_review_record).resolve(),
        "fresh_report_review_record": Path(
            args.fresh_report_review_record).resolve(),
        "recovery_review_record": Path(
            args.recovery_review_record).resolve(),
        "smoke": bool(args.smoke),
    }
    if args.command == "freeze":
        packet = freeze(out=Path(args.out).resolve(), **common)
        print(json.dumps({
            "status": "FROZEN_NO_REPORT_OPEN",
            "packet_sha256": sha256_file(Path(args.out)),
            "packet_internal_sha256": packet["packet_sha256"],
            "expected_review_claim": expected_review_claim(
                packet, sha256_file(Path(args.out))),
        }, indent=2, sort_keys=True))
    else:
        if not args.expected_packet_sha256:
            raise ReportControllerRefused(
                "verify requires --expected-packet-sha256")
        packet = verify_frozen(
            packet_path=Path(args.out).resolve(),
            expected_packet_sha256=args.expected_packet_sha256, **common)
        print(json.dumps({
            "status": "VERIFIED_NO_REPORT_OPEN",
            "packet_sha256": args.expected_packet_sha256,
            "packet_internal_sha256": packet["packet_sha256"],
            "expected_review_claim": expected_review_claim(
                packet, args.expected_packet_sha256),
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportControllerRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
