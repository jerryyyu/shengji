#!/usr/bin/env python3
"""Label and evaluate the reviewed protected-anchor policy once on REPORT.

Admission authenticates the frozen DESIGN-selected protected ensemble and the
digest-sealed replacement population without computing a label or prediction.
Eight one-shot workers then reconstruct their reviewed state partitions and
run the finite-work Teacher directly on the captured candidate tensor; they
never load V11. Evaluation reopens all eight terminal label shards, scores the
frozen ensemble, and publishes one accept/reject result.

No command here composes a bot, launches games, confirms, promotes or deploys.
Every admission is consumed even when later work crashes or refuses.
"""
from __future__ import annotations

import argparse
import importlib
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
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_fresh_report_controller as FRESH  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
_CONTROLLER_MODULE = os.environ.get(
    "SHENGJI_STAGE_C_REPORT_CONTROLLER",
    "teacher_stage_c_report_controller")
if _CONTROLLER_MODULE not in {
        "teacher_stage_c_report_controller",
        "teacher_stage_c_expanded_report_controller",
        "teacher_stage_c_expanded_play_report_controller"}:
    raise RuntimeError("unrecognized Stage-C REPORT controller module")
CTRL = importlib.import_module(_CONTROLLER_MODULE)  # noqa: E402
import teacher_stage_c_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_training_runtime as TRAIN_RUNTIME  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


RECEIPT_SCHEMA = getattr(
    CTRL, "RUNTIME_RECEIPT_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-receipt-v1")
ADMISSION_SCHEMA = getattr(
    CTRL, "RUNTIME_ADMISSION_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-admission-v1")
REPORT_OPEN_ADMISSION_SCHEMA = getattr(
    CTRL, "RUNTIME_REPORT_OPEN_ADMISSION_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-open-admission-v1")
SHARD_ADMISSION_SCHEMA = getattr(
    CTRL, "RUNTIME_SHARD_ADMISSION_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-shard-admission-v1")
SHARD_SCHEMA = getattr(
    CTRL, "RUNTIME_SHARD_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-label-shard-v1")
RESULT_SCHEMA = getattr(
    CTRL, "RUNTIME_RESULT_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-result-v1")
RECEIPT_PATH = f"server/runs/logs/{CTRL.RUN_ID}/report-receipt.json"
RESULT_PATH = f"server/runs/logs/{CTRL.RUN_ID}/report-result.json"
ADMISSION_PATH = f"server/runs/locks/{CTRL.RUN_ID}.consumed.json"
REPORT_OPEN_ADMISSION_PATH = \
    f"server/runs/locks/{CTRL.RUN_ID}.report-open.consumed.json"
SHARD_ADMISSION_PATHS = tuple(
    f"server/runs/locks/{CTRL.RUN_ID}.shard-{index:02d}.consumed.json"
    for index in range(CTRL.REPORT_SHARDS))
SHARD_PATHS = tuple(
    f"server/runs/logs/{CTRL.RUN_ID}/labels/shard-{index:02d}.json"
    for index in range(CTRL.REPORT_SHARDS))


class ReportRuntimeRefused(RuntimeError):
    """A packet, admission, fresh state, label, model or result drifted."""


canonical_json = CTRL.canonical_json
sha256_bytes = CTRL.sha256_bytes
sha256_file = CTRL.sha256_file
self_hash = CTRL.self_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ReportRuntimeRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReportRuntimeRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportRuntimeRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _require_clean_tree() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ReportRuntimeRefused("Stage-C REPORT runtime refuses a dirty tree")


def _require_output_available(path: Path) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ReportRuntimeRefused(f"refusing existing output: {path}")


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    _require_output_available(path)
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ReportRuntimeRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def _expected_packet_path() -> Path:
    return (REPO / CTRL.PACKET_PATH).resolve()


def _expected_receipt_path() -> Path:
    return (REPO / RECEIPT_PATH).resolve()


def _expected_result_path() -> Path:
    return (REPO / RESULT_PATH).resolve()


def _parent_file(parent: Mapping[str, object], label: str) -> tuple[Path, dict]:
    path = (REPO / str(parent.get("logical_path"))).resolve()
    if (not is_regular_unlinked(path)
            or sha256_file(path) != parent.get("external_sha256")):
        raise ReportRuntimeRefused(f"Stage-C REPORT {label} path/SHA drift")
    return path, load_json(path)


def _validate_checkpoint_manifest(packet: Mapping[str, object],
                                  training_packet: Mapping[str, object],
                                  evidence_repo: Path) -> None:
    capability = packet["selected_capability"]
    manifest = packet.get("checkpoint_manifest")
    if (not isinstance(manifest, list)
            or len(manifest) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in manifest]
            != list(MODEL.TRAINING_SEEDS)):
        raise ReportRuntimeRefused("Stage-C REPORT checkpoint manifest drift")
    training_packet = dict(training_packet)
    training_packet["external_sha256"] = packet["parents"][
        "training_packet"]["external_sha256"]
    for item in manifest:
        path = (evidence_repo / str(item.get("checkpoint_path"))).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item.get("checkpoint_sha256")
                or item.get("surface") != capability["surface"]
                or item.get("head") != capability["head"]
                or item.get("epoch") != capability["epoch"]):
            raise ReportRuntimeRefused(
                "Stage-C REPORT checkpoint identity drift")
        cell = next(value for value in training_packet["schedule"]["cells"]
                    if value["surface"] == capability["surface"]
                    and value["seed"] == item["seed"]
                    and value["curve_fraction"] == 1.0)
        expected_contract = TRAIN_RUNTIME._snapshot_contract(
            training_packet, cell, int(capability["epoch"]),
            str(item["model_state_sha256"]))
        if item.get("checkpoint_contract") != expected_contract:
            raise ReportRuntimeRefused(
                "Stage-C REPORT checkpoint contract drift")
        TRAIN.load_snapshot(path, expected_contract=expected_contract)


def _packet(
    path: Path, expected_sha256: str, *, fresh_report_review_record: Path,
    state_set_review_record: Path,
) -> tuple[dict, dict, dict, dict, list[dict]]:
    _require_clean_tree()
    adapter = getattr(CTRL, "validate_runtime_packet", None)
    if adapter is not None:
        try:
            value = adapter(
                path=path, expected_sha256=expected_sha256,
                fresh_report_review_record=fresh_report_review_record,
                state_set_review_record=state_set_review_record)
        except CTRL.ReportControllerRefused as exc:
            raise ReportRuntimeRefused(str(exc)) from exc
        if not isinstance(value, tuple) or len(value) != 5:
            raise ReportRuntimeRefused(
                "Stage-C REPORT controller adapter contract drift")
        return value
    if (path.resolve() != _expected_packet_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportRuntimeRefused("Stage-C REPORT packet path/SHA drift")
    packet = load_json(path)
    expected_authority = {
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
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git")
            != _git("rev-parse", "HEAD")
            or packet.get("producer", {}).get("tree_dirty") is not False
            or packet.get("producer", {}).get("sources")
            != CTRL._source_sha256s()
            or packet.get("runtime_contract") != CTRL.runtime_contract()
            or packet.get("authority") != expected_authority):
        raise ReportRuntimeRefused(
            "Stage-C fresh REPORT packet identity/authority drift")

    parents = packet.get("parents")
    if not isinstance(parents, dict) or set(parents) != {
            "training_evidence", "training_packet", "training_aggregate",
            "protected_capability", "model_dataset",
            "fresh_report_selection"}:
        raise ReportRuntimeRefused("Stage-C REPORT parent population drift")

    evidence = parents["training_evidence"]
    if not isinstance(evidence, dict):
        raise ReportRuntimeRefused("Stage-C REPORT evidence parent drift")
    evidence_repo = Path(str(evidence.get("absolute_path"))).resolve()
    training_review_record = Path(str(
        evidence.get("training_review_record_absolute_path"))).resolve()
    if (str(evidence_repo) != evidence.get("absolute_path")
            or evidence.get("git") != CTRL.PROTECTED.PARENT_GIT
            or evidence.get("tracked_tree_clean") is not True
            or not CTRL.is_regular_unlinked(training_review_record)
            or CTRL.sha256_file(training_review_record)
            != evidence.get("training_review_record_sha256")):
        raise ReportRuntimeRefused("Stage-C REPORT evidence identity drift")
    try:
        training_packet, dataset, aggregate = \
            CTRL.validate_training_aggregate(
                evidence_repo=evidence_repo,
                training_review_record=training_review_record)
    except CTRL.ReportControllerRefused as exc:
        raise ReportRuntimeRefused(str(exc)) from exc
    expected_training_packet_parent = {
        "logical_path": TRAIN_CTRL.PACKET_PATH,
        "external_sha256": CTRL.PROTECTED.TRAINING_PACKET_SHA256,
    }
    expected_aggregate_parent = {
        "logical_path": TRAIN_RUNTIME.AGGREGATE_PATH,
        "external_sha256": CTRL.PROTECTED.TRAINING_AGGREGATE_SHA256,
        "internal_sha256": CTRL.PROTECTED.TRAINING_AGGREGATE_INTERNAL_SHA256,
    }
    expected_dataset_parent = {
        "logical_path": TRAIN_CTRL.DATASET_PATH,
        "external_sha256": CTRL.PROTECTED.MODEL_DATASET_SHA256,
    }
    if (parents["training_packet"] != expected_training_packet_parent
            or parents["training_aggregate"] != expected_aggregate_parent
            or parents["model_dataset"] != expected_dataset_parent
            or dataset.get("dataset_sha256")
            != CTRL.PROTECTED.MODEL_DATASET_INTERNAL_SHA256
            or dataset.get("old_report_labels_quarantined") is not True
            or dataset.get("report_rows_included") is not False
            or dataset.get("report_label_shard_files_opened") != 0
            or dataset.get("fresh_report_states_materialized") is not False):
        raise ReportRuntimeRefused(
            "Stage-C REPORT terminal training parent drift")

    protected_parent = parents["protected_capability"]
    protected_path, protected = _parent_file(
        protected_parent, "protected capability")
    expected_protected_parent = {
        "logical_path": CTRL.PROTECTED.PACKET_PATH,
        "external_sha256": protected_parent["external_sha256"],
        "internal_sha256": protected.get("packet_sha256"),
        "review_claim_sha256": protected_parent["review_claim_sha256"],
        "checkpoint_manifest_sha256": protected.get(
            "checkpoint_manifest_sha256"),
        "diagnostics_sha256": protected.get("diagnostics_sha256"),
        "parent_terminal_decision": "SELECT_NONE",
        "report_rows_opened": 0,
    }
    if (protected_path
            != (REPO / CTRL.PROTECTED.PACKET_PATH).resolve()
            or protected_parent != expected_protected_parent
            or protected.get("schema") != CTRL.PROTECTED.SCHEMA
            or protected.get("packet_sha256")
            != self_hash(protected, "packet_sha256")
            or protected.get("capability")
            != packet.get("selected_capability")
            or protected.get("checkpoint_manifest")
            != packet.get("checkpoint_manifest")
            or protected.get("authority", {}).get("report_open_authorized")
            is not False
            or protected.get("authority", {}).get(
                "report_execution_authorized") is not False
            or protected.get("authority", {}).get("strength_claim")
            is not False
            or protected.get("parent", {}).get(
                "training_aggregate_internal_sha256")
            != aggregate.get("aggregate_sha256")
            or CTRL.protected_policy_contract(protected["capability"])
            != packet.get("protected_policy")):
        raise ReportRuntimeRefused(
            "Stage-C REPORT protected-capability parent drift")
    fresh_parent = parents["fresh_report_selection"]
    fresh_path = (evidence_repo / FRESH.PACKET_PATH).resolve()
    try:
        with CTRL.evidence_scope(evidence_repo):
            fresh_report, fresh_review = TRAIN_CTRL.validate_fresh_report(
                fresh_path, str(fresh_parent["external_sha256"]),
                fresh_report_review_record, state_set_review_record)
    except TRAIN_CTRL.TrainingControllerRefused as exc:
        raise ReportRuntimeRefused(str(exc)) from exc
    sealed = fresh_report["sealed_selection"]
    expected_fresh_parent = {
        "logical_path": FRESH.PACKET_PATH,
        "external_sha256": TRAIN_CTRL.FRESH_REPORT_PACKET_SHA256,
        "internal_sha256": fresh_report["packet_sha256"],
        "review_claim_sha256": CTRL._manifest_hash(fresh_review),
        "sealed_selection_sha256": sealed["sealed_selection_sha256"],
        "fresh_report_state_ids_sha256": sealed[
            "fresh_report_state_ids_sha256"],
        "fresh_report_state_material_sha256": sealed[
            "fresh_report_state_material_sha256"],
        "fresh_report_states": sealed["fresh_report_states"],
        "state_material_published": False,
    }
    if (fresh_parent != expected_fresh_parent
            or dataset.get("fresh_report_selection")
            != TRAIN_CTRL.fresh_report_dataset_contract(
                fresh_report, fresh_review)):
        raise ReportRuntimeRefused(
            "fresh REPORT selection/dataset binding drift")
    with CTRL.evidence_scope(evidence_repo):
        states = CTRL._selected_fresh_states(
            fresh_report, state_set_review_record, evidence_repo)

    _validate_checkpoint_manifest(packet, training_packet, evidence_repo)
    surface = packet["selected_capability"]["surface"]
    prior = TRAIN.state_balanced_prior(dataset["examples"]["DESIGN"][surface])
    schedule = CTRL.build_report_schedule(states, surface=surface)
    contract = packet.get("report_contract", {})
    if (packet.get("design_prior_distribution") != prior
            or packet.get("report_schedule") != schedule
            or contract.get("surface") != surface
            or contract.get("head") != packet["selected_capability"]["head"]
            or contract.get("states") != CTRL.REPORT_SURFACE_COUNTS[surface]
            or contract.get("candidate_world_ceiling")
            != schedule["candidate_world_ceiling"]
            or contract.get("v11_checkpoint_loaded") is not False
            or contract.get("v11_candidates_reconstructed") is not False
            or contract.get("captured_candidate_tensor_authenticated")
            is not True
            or contract.get("single_report_look") is not True
            or contract.get("protected_policy")
            != packet.get("protected_policy")
            or contract.get("activation_threshold")
            != CTRL.PROTECTED.EXPECTED_SELECTED_THRESHOLD
            or contract.get("activation_is_strict") is not True
            or contract.get("rank_ensemble")
            != "arithmetic mean of raw rank logits across seeds"
            or contract.get("tie_break")
            != "lowest alternative candidate index"
            or contract.get("durable_report_open_admission_slot")
            != REPORT_OPEN_ADMISSION_PATH
            or contract.get("retry_after_report_open_or_failure_authorized")
            is not False
            or contract.get(
                "report_cannot_change_surface_head_epoch_or_seed_population")
            is not True):
        raise ReportRuntimeRefused("Stage-C fresh REPORT contract drift")
    return packet, dataset, training_packet, fresh_report, states


def _review_claim(path: Path, packet: Mapping[str, object],
                  packet_sha256: str) -> dict:
    claim = CTRL.marker_claim(path, CTRL.REVIEW_MARKER)
    if claim != CTRL.expected_review_claim(packet, packet_sha256):
        raise ReportRuntimeRefused("Stage-C REPORT packet PASS marker drift")
    return claim


def _slot_payload(packet: Mapping[str, object], packet_sha256: str,
                  review_record: Path) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "selected_capability": packet["selected_capability"],
        "protected_policy": packet.get("protected_policy"),
        "checkpoint_manifest_sha256": CTRL._manifest_hash(
            packet["checkpoint_manifest"]),
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "controller_review_record_sha256": sha256_file(review_record),
        "receipt_path": RECEIPT_PATH,
        "consumed_even_if_receipt_or_report_publication_fails": True,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _report_open_slot_payload(
    packet: Mapping[str, object], packet_sha256: str,
    review_record: Path, admission_slot_sha256: str,
) -> dict:
    value = {
        "schema": REPORT_OPEN_ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "admission_slot_sha256": admission_slot_sha256,
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "selected_capability": packet["selected_capability"],
        "protected_policy": packet.get("protected_policy"),
        "consumed_before_any_teacher_label_or_model_prediction": True,
        "retry_after_failure_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _require_admission_outputs_available(out: Path) -> tuple[Path, Path]:
    if out.resolve() != _expected_receipt_path():
        raise ReportRuntimeRefused("Stage-C REPORT receipt path drift")
    slot_path = (REPO / ADMISSION_PATH).resolve()
    report_slot_path = (REPO / REPORT_OPEN_ADMISSION_PATH).resolve()
    for path in (slot_path, report_slot_path, out):
        _require_output_available(path)
    return slot_path, report_slot_path


def admit(*, packet_path: Path, expected_packet_sha256: str,
          review_record: Path, fresh_report_review_record: Path,
          state_set_review_record: Path, out: Path) -> dict:
    slot_path, report_slot_path = _require_admission_outputs_available(out)
    packet, _dataset, _training, _fresh, _states = _packet(
        packet_path, expected_packet_sha256,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record)
    _review_claim(review_record, packet, expected_packet_sha256)
    slot = _slot_payload(packet, expected_packet_sha256, review_record)
    slot_sha256 = sha256_bytes(canonical_json(slot))
    report_slot = _report_open_slot_payload(
        packet, expected_packet_sha256, review_record, slot_sha256)
    report_slot_sha256 = sha256_bytes(canonical_json(report_slot))
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "selected_capability": packet["selected_capability"],
        "protected_policy": packet.get("protected_policy"),
        "admission_slot": ADMISSION_PATH,
        "admission_slot_sha256": slot_sha256,
        "report_open_admission_slot": REPORT_OPEN_ADMISSION_PATH,
        "report_open_admission_slot_sha256": report_slot_sha256,
        "report_open_admission_consumed": True,
        "report_execution_authorized": True,
        "teacher_labels_computed": 0,
        "model_predictions_computed": 0,
        "v11_checkpoint_loaded": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = self_hash(receipt, "receipt_sha256")
    _packet(
        packet_path, expected_packet_sha256,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record)
    _review_claim(review_record, packet, expected_packet_sha256)
    _require_admission_outputs_available(out)
    publish_exclusive(slot_path, slot)
    publish_exclusive(report_slot_path, report_slot)
    publish_exclusive(out, receipt)
    return receipt


def _receipt(path: Path, expected_sha256: str,
             packet: Mapping[str, object], packet_sha256: str,
             review_record: Path) -> dict:
    if (path.resolve() != _expected_receipt_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportRuntimeRefused("Stage-C REPORT receipt path/SHA drift")
    receipt = load_json(path)
    slot_path = (REPO / ADMISSION_PATH).resolve()
    expected_slot = _slot_payload(packet, packet_sha256, review_record)
    if (not is_regular_unlinked(slot_path)
            or load_json(slot_path) != expected_slot
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("run_id") != CTRL.RUN_ID
            or receipt.get("git") != packet["producer"]["git"]
            or receipt.get("controller_packet_sha256") != packet_sha256
            or receipt.get("controller_review_record_sha256")
            != sha256_file(review_record)
            or receipt.get("selected_capability")
            != packet["selected_capability"]
            or receipt.get("protected_policy") != packet.get(
                "protected_policy")
            or receipt.get("admission_slot") != ADMISSION_PATH
            or receipt.get("admission_slot_sha256") != sha256_file(slot_path)
            or receipt.get("report_open_admission_slot")
            != REPORT_OPEN_ADMISSION_PATH
            or receipt.get("report_open_admission_consumed") is not True
            or receipt.get("report_execution_authorized") is not True
            or receipt.get("teacher_labels_computed") != 0
            or receipt.get("model_predictions_computed") != 0
            or receipt.get("v11_checkpoint_loaded") is not False
            or receipt.get("composition_authorized") is not False
            or receipt.get("receipt_sha256")
            != self_hash(receipt, "receipt_sha256")):
        raise ReportRuntimeRefused("Stage-C REPORT receipt/slot drift")
    report_slot_path = (REPO / REPORT_OPEN_ADMISSION_PATH).resolve()
    expected_report_slot = _report_open_slot_payload(
        packet, packet_sha256, review_record, sha256_file(slot_path))
    if (not is_regular_unlinked(report_slot_path)
            or sha256_file(report_slot_path)
            != receipt.get("report_open_admission_slot_sha256")
            or load_json(report_slot_path) != expected_report_slot):
        raise ReportRuntimeRefused(
            "Stage-C REPORT open admission slot drift")
    return receipt


def _surface_states(packet: Mapping[str, object],
                    states: Sequence[dict]) -> list[dict]:
    surface = packet["selected_capability"]["surface"]
    values = sorted(
        (state for state in states if state.get("surface_type") == surface),
        key=lambda state: str(state["state_id"]))
    if len(values) != packet["report_contract"]["states"]:
        raise ReportRuntimeRefused(
            "fresh REPORT selected-surface population drift")
    return values


def _shard_states(packet: Mapping[str, object], states: Sequence[dict],
                  index: int) -> list[dict]:
    if not 0 <= index < CTRL.REPORT_SHARDS:
        raise ReportRuntimeRefused("fresh REPORT shard index drift")
    values = _surface_states(packet, states)[index::CTRL.REPORT_SHARDS]
    schedule = packet["report_schedule"]["shards"][index]
    if (schedule.get("index") != index
            or schedule.get("state_count") != len(values)
            or schedule.get("state_ids_sha256") != CTRL._manifest_hash(
                [str(state["state_id"]) for state in values])
            or schedule.get("candidate_world_ceiling") != sum(
                CTRL._candidate_world_ceiling(state) for state in values)
            or schedule.get("result") != SHARD_PATHS[index]):
        raise ReportRuntimeRefused(
            "fresh REPORT shard schedule/material drift")
    return values


def _shard_slot_payload(packet: Mapping[str, object], packet_sha256: str,
                        receipt_sha256: str, index: int) -> dict:
    value = {
        "schema": SHARD_ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "report_receipt_sha256": receipt_sha256,
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "shard_index": index,
        "shard_schedule": packet["report_schedule"]["shards"][index],
        "retry_after_failure_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _consume_shard_slot(packet: Mapping[str, object], packet_sha256: str,
                        receipt_sha256: str, index: int) -> str:
    path = (REPO / SHARD_ADMISSION_PATHS[index]).resolve()
    publish_exclusive(
        path, _shard_slot_payload(packet, packet_sha256, receipt_sha256, index))
    return sha256_file(path)


def _validate_shard_slot(packet: Mapping[str, object], packet_sha256: str,
                         receipt_sha256: str, index: int,
                         expected_sha256: str) -> None:
    path = (REPO / SHARD_ADMISSION_PATHS[index]).resolve()
    if (not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256
            or load_json(path) != _shard_slot_payload(
                packet, packet_sha256, receipt_sha256, index)):
        raise ReportRuntimeRefused(
            f"fresh REPORT shard {index} admission drift")


def run_shard(*, packet_path: Path, expected_packet_sha256: str,
              review_record: Path, fresh_report_review_record: Path,
              state_set_review_record: Path, receipt_path: Path,
              expected_receipt_sha256: str, shard_index: int,
              progress_every: int, out: Path) -> dict:
    if not 0 <= shard_index < CTRL.REPORT_SHARDS:
        raise ReportRuntimeRefused("fresh REPORT shard index drift")
    if (progress_every <= 0
            or out.resolve() != (REPO / SHARD_PATHS[shard_index]).resolve()):
        raise ReportRuntimeRefused("fresh REPORT shard output/progress drift")
    packet, _dataset, _training, _fresh, states = _packet(
        packet_path, expected_packet_sha256,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record)
    _review_claim(review_record, packet, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, review_record)
    population = _shard_states(packet, states, shard_index)
    slot_sha256 = _consume_shard_slot(
        packet, expected_packet_sha256, expected_receipt_sha256, shard_index)
    rows = []
    for ordinal, state in enumerate(population, 1):
        ledger = LABEL.WorkLedger()
        try:
            rnd = CAPTURE.replay_state(state)
            row = LABEL.label_replayed_state(
                state, rnd, include_audit=False, ledger=ledger)
            LABEL.validate_label_row(
                state, rnd, row, audit_expected=False)
        except Exception as exc:
            row = LABEL.refusal_record(state, exc, ledger)
        rows.append(row)
        if ordinal % progress_every == 0 or ordinal == len(population):
            print(json.dumps({
                "event": "stage-c-fresh-report-label-progress-v1",
                "shard_index": shard_index,
                "states_complete": ordinal,
                "states_total": len(population),
                "refusals": sum(
                    value.get("status") != "COMPLETE" for value in rows),
            }, sort_keys=True), file=sys.stderr, flush=True)
    work = LABEL._work_from_rows(rows)
    refusals = sum(row.get("status") != "COMPLETE" for row in rows)
    payload = {
        "schema": SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "report_receipt_sha256": expected_receipt_sha256,
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "shard_index": shard_index,
        "state_ids": [str(state["state_id"]) for state in population],
        "state_ids_sha256": packet["report_schedule"]["shards"][
            shard_index]["state_ids_sha256"],
        "shard_admission_slot": SHARD_ADMISSION_PATHS[shard_index],
        "shard_admission_slot_sha256": slot_sha256,
        "status": ("COMPLETE" if refusals == 0
                   else "REFUSED_INCOMPLETE_NO_REPORT_UTILITY"),
        "complete_rows": len(rows) - refusals,
        "refused_rows": refusals,
        "rows": rows,
        "row_sha256s": [row["row_sha256"] for row in rows],
        "work": work,
        "candidate_world_ceiling": packet["report_schedule"]["shards"][
            shard_index]["candidate_world_ceiling"],
        "candidate_world_ceiling_respected": (
            work["candidate_worlds_attempted"]
            <= packet["report_schedule"]["shards"][shard_index][
                "candidate_world_ceiling"]),
        "audit_folds_computed": False,
        "v11_checkpoint_loaded": False,
        "model_predictions_computed": 0,
        "report_utility_published": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["shard_sha256"] = self_hash(payload, "shard_sha256")
    final_packet, _d2, _t2, _f2, final_states = _packet(
        packet_path, expected_packet_sha256,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record)
    _review_claim(review_record, final_packet, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    if ([state["state_id"] for state in _shard_states(
            final_packet, final_states, shard_index)]
            != [state["state_id"] for state in population]):
        raise ReportRuntimeRefused(
            "fresh REPORT state population changed during labeling")
    publish_exclusive(out, payload)
    return payload


def validate_shard(shard: Mapping[str, object], *,
                   packet: Mapping[str, object], states: Sequence[dict],
                   packet_sha256: str, receipt_sha256: str,
                   index: int) -> None:
    population = _shard_states(packet, states, index)
    rows = shard.get("rows")
    fixed = {
        "schema": SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "report_receipt_sha256": receipt_sha256,
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "shard_index": index,
        "state_ids": [str(state["state_id"]) for state in population],
        "state_ids_sha256": packet["report_schedule"]["shards"][index][
            "state_ids_sha256"],
        "shard_admission_slot": SHARD_ADMISSION_PATHS[index],
        "candidate_world_ceiling": packet["report_schedule"]["shards"][
            index]["candidate_world_ceiling"],
        "audit_folds_computed": False,
        "v11_checkpoint_loaded": False,
        "model_predictions_computed": 0,
        "report_utility_published": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if (not isinstance(rows, list) or len(rows) != len(population)
            or shard.get("shard_sha256")
            != self_hash(shard, "shard_sha256")
            or any(shard.get(key) != value for key, value in fixed.items())
            or not isinstance(shard.get("shard_admission_slot_sha256"), str)):
        raise ReportRuntimeRefused(
            f"fresh REPORT shard {index} identity drift")
    _validate_shard_slot(
        packet, packet_sha256, receipt_sha256, index,
        str(shard["shard_admission_slot_sha256"]))
    complete = 0
    refused = 0
    for state, row in zip(population, rows, strict=True):
        if row.get("status") == "COMPLETE":
            LABEL.validate_label_row(
                state, CAPTURE.replay_state(state), row,
                audit_expected=False)
            complete += 1
        else:
            LABEL.validate_refusal_record(
                state, row, audit_expected=False)
            refused += 1
    work = LABEL._work_from_rows(rows)
    expected_status = ("COMPLETE" if refused == 0
                       else "REFUSED_INCOMPLETE_NO_REPORT_UTILITY")
    if (shard.get("status") != expected_status
            or shard.get("complete_rows") != complete
            or shard.get("refused_rows") != refused
            or shard.get("row_sha256s")
            != [row["row_sha256"] for row in rows]
            or shard.get("work") != work
            or shard.get("candidate_world_ceiling_respected")
            is not (work["candidate_worlds_attempted"]
                    <= fixed["candidate_world_ceiling"])):
        raise ReportRuntimeRefused(
            f"fresh REPORT shard {index} work/status drift")


def _member_predictions(packet: Mapping[str, object],
                        examples: list[dict]):
    TRAIN._configure_determinism(MODEL.TRAINING_SEEDS[0])
    evidence_repo = Path(str(packet["parents"]["training_evidence"][
        "absolute_path"])).resolve()
    values = []
    for item in packet["checkpoint_manifest"]:
        path = (evidence_repo / str(item["checkpoint_path"])).resolve()
        reopened = TRAIN.load_snapshot(
            path, expected_contract=item["checkpoint_contract"])
        net = MODEL.StageCRankingOutcomeNet(hidden=TRAIN.HIDDEN)
        net.load_state_dict(reopened["state_dict"], strict=True)
        values.append(TRAIN.predict_examples(net, examples))
    return values


def recompute_result(
    *, packet_path: Path, expected_packet_sha256: str,
    review_record: Path, fresh_report_review_record: Path,
    state_set_review_record: Path, receipt_path: Path,
    expected_receipt_sha256: str, shard_paths: Sequence[Path],
) -> dict:
    """Recompute the fixed terminal result without publishing or admitting."""
    packet, _dataset, _training, _fresh, states = _packet(
        packet_path, expected_packet_sha256,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record)
    receipt = _receipt(
        receipt_path, expected_receipt_sha256, packet,
        expected_packet_sha256, review_record)
    expected_paths = [(REPO / logical).resolve() for logical in SHARD_PATHS]
    if (len(shard_paths) != CTRL.REPORT_SHARDS
            or [path.resolve() for path in shard_paths] != expected_paths):
        raise ReportRuntimeRefused("fresh REPORT label-shard paths drift")
    surface_states = {
        str(state["state_id"]): state
        for state in _surface_states(packet, states)}
    opened = []
    examples = []
    validated_shards = []
    total_work = {
        "candidate_worlds_attempted": 0,
        "candidate_worlds_completed": 0,
        "sampler_attempts": 0,
        "accepted_worlds": 0,
    }
    refusals = 0
    for index, path in enumerate(shard_paths):
        before = sha256_file(path)
        shard = load_json(path)
        validate_shard(
            shard, packet=packet, states=states,
            packet_sha256=expected_packet_sha256,
            receipt_sha256=expected_receipt_sha256, index=index)
        if sha256_file(path) != before:
            raise ReportRuntimeRefused(
                f"fresh REPORT shard {index} changed during validation")
        refusals += int(shard["refused_rows"])
        for key in total_work:
            total_work[key] += int(shard["work"][key])
        validated_shards.append(shard)
        opened.append({
            "index": index,
            "logical_path": SHARD_PATHS[index],
            "external_sha256": before,
            "internal_sha256": shard["shard_sha256"],
            "state_ids_sha256": shard["state_ids_sha256"],
            "row_sha256s_sha256": sha256_bytes(canonical_json(
                shard["row_sha256s"])),
            "status": shard["status"],
            "refused_rows": shard["refused_rows"],
        })
    evaluation = None
    if refusals == 0:
        for shard in validated_shards:
            for state_id, row in zip(
                    shard["state_ids"], shard["rows"], strict=True):
                state = surface_states[str(state_id)]
                example = MODEL.materialize_example(
                    state, row, CAPTURE.replay_state(state))
                TRAIN._validate_example(
                    example, split="REPORT",
                    surface=packet["selected_capability"]["surface"])
                examples.append(example)
        examples.sort(key=lambda value: str(value["state_id"]))
        if (len(examples) != packet["report_contract"]["states"]
                or len({value["state_id"] for value in examples})
                != len(examples)):
            raise ReportRuntimeRefused(
                "fresh REPORT example population drift")
        predictions = _member_predictions(packet, examples)
        capability = packet["selected_capability"]
        evaluation = REPORT.evaluate_capability(
            examples, predictions, surface=capability["surface"],
            head=capability["head"],
            prior_distribution=packet["design_prior_distribution"],
            protected_policy=packet.get("protected_policy"))
        decision = evaluation["decision"]
        composition_authorized = evaluation[
            "composition_packet_review_authorized"]
    else:
        decision = "SELECT_NONE_REPORT_LABEL_REFUSAL"
        composition_authorized = False
    payload = {
        "schema": RESULT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "report_receipt_sha256": expected_receipt_sha256,
        "report_open_admission_slot": REPORT_OPEN_ADMISSION_PATH,
        "report_open_admission_slot_sha256": receipt[
            "report_open_admission_slot_sha256"],
        "selected_capability": packet["selected_capability"],
        "protected_policy": packet.get("protected_policy"),
        "checkpoint_manifest_sha256": CTRL._manifest_hash(
            packet["checkpoint_manifest"]),
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "opened_report_label_shards": opened,
        "report_label_shard_files_opened": len(opened),
        "fresh_report_states_reconstructed": len(states),
        "selected_surface_rows_labeled": sum(
            item["state_count"]
            for item in packet["report_schedule"]["shards"]),
        "report_label_refusals": refusals,
        "work": total_work,
        "candidate_world_ceiling": packet["report_schedule"][
            "candidate_world_ceiling"],
        "candidate_world_ceiling_respected": (
            total_work["candidate_worlds_attempted"]
            <= packet["report_schedule"]["candidate_world_ceiling"]),
        "v11_checkpoint_loaded": False,
        "evaluation": evaluation,
        "decision": decision,
        "composition_packet_review_authorized": composition_authorized,
        "report_reuse_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["result_sha256"] = self_hash(payload, "result_sha256")
    final_packet, _d2, _t2, _f2, final_states = _packet(
        packet_path, expected_packet_sha256,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record)
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    if ([state["state_id"]
         for state in _surface_states(final_packet, final_states)]
            != [state["state_id"]
                for state in _surface_states(packet, states)]):
        raise ReportRuntimeRefused(
            "fresh REPORT state population changed during evaluation")
    for item in opened:
        if sha256_file(REPO / str(item["logical_path"])) \
                != item["external_sha256"]:
            raise ReportRuntimeRefused(
                "fresh REPORT label shard changed during evaluation")
    return payload


def evaluate(*, packet_path: Path, expected_packet_sha256: str,
             review_record: Path, fresh_report_review_record: Path,
             state_set_review_record: Path, receipt_path: Path,
             expected_receipt_sha256: str,
             shard_paths: Sequence[Path], out: Path) -> dict:
    if out.resolve() != _expected_result_path():
        raise ReportRuntimeRefused("Stage-C REPORT result path drift")
    payload = recompute_result(
        packet_path=packet_path,
        expected_packet_sha256=expected_packet_sha256,
        review_record=review_record,
        fresh_report_review_record=fresh_report_review_record,
        state_set_review_record=state_set_review_record,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        shard_paths=shard_paths)
    publish_exclusive(out, payload)
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("admit", "run-shard", "evaluate"):
        child = commands.add_parser(name)
        child.add_argument("--expected-git", required=True)
        child.add_argument("--controller-packet", required=True)
        child.add_argument("--expected-controller-packet-sha256", required=True)
        child.add_argument("--controller-review-record", required=True)
        child.add_argument("--fresh-report-review-record", required=True)
        child.add_argument("--state-set-review-record", required=True)
        child.add_argument("--out", required=True)
        if name in {"run-shard", "evaluate"}:
            child.add_argument("--report-receipt", required=True)
            child.add_argument(
                "--expected-report-receipt-sha256", required=True)
        if name == "run-shard":
            child.add_argument("--shard-index", required=True, type=int)
            child.add_argument("--progress-every", type=int, default=1)
        if name == "evaluate":
            child.add_argument("--label-shards", nargs="+", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.expected_git != _git("rev-parse", "HEAD"):
        raise ReportRuntimeRefused("Stage-C REPORT expected git drift")
    common = {
        "packet_path": Path(args.controller_packet).resolve(),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
        "review_record": Path(args.controller_review_record).resolve(),
        "fresh_report_review_record": Path(
            args.fresh_report_review_record).resolve(),
        "state_set_review_record": Path(
            args.state_set_review_record).resolve(),
        "out": Path(args.out).resolve(),
    }
    if args.command == "admit":
        value = admit(**common)
    elif args.command == "run-shard":
        value = run_shard(
            **common,
            receipt_path=Path(args.report_receipt).resolve(),
            expected_receipt_sha256=args.expected_report_receipt_sha256,
            shard_index=args.shard_index,
            progress_every=args.progress_every)
    else:
        value = evaluate(
            **common,
            receipt_path=Path(args.report_receipt).resolve(),
            expected_receipt_sha256=args.expected_report_receipt_sha256,
            shard_paths=[Path(item).resolve() for item in args.label_shards])
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReportRuntimeRefused, CTRL.ReportControllerRefused,
            LABEL.LabelRefused, REPORT.StageCReportError,
            TRAIN.StageCTrainingError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
