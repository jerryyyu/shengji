"""Durable reviewed-device cohort stage for BELIEF-V1 V2.

The caller supplies split-safe, independently reopened examples and their
realized schedules.  This stage reauthenticates the execution freeze, binds
the post-capture CPU-versus-accelerator qualification to the exact primary
schedule, trains one frozen cohort, and publishes portable non-executable CPU
checkpoints in a no-retry directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_cohort_training import (
    V2TrainedCohortArtifactsV1,
    reopen_trained_v2_cohort,
    train_v2_cohort_in_memory,
)
from .belief_v2_controller import _stage_gate
from .belief_v2_deadline import (
    BeliefV2DeadlineError,
    publish_deadline_refusal,
    stage_deadline,
)
from .belief_v2_device_qualification import (
    V2DeviceQualificationPlanV1,
    V2DeviceQualificationResultV1,
    build_qualification_plan_from_primary,
    validate_qualification_result,
)
from .belief_v2_device_runner import (
    device_peak_memory_bytes,
    host_peak_memory_bytes,
    prepare_device_memory_measurement,
    synchronize_training_device,
)
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
)
from .belief_v2_training import V2TrainingExampleV1


TRAINING_STAGE_SCHEMA = "belief-v1-v2-training-stage-result-v1"
TRAINING_RESOURCE_SCHEMA = "belief-v1-v2-training-stage-resource-v1"


class BeliefV2TrainingControllerError(ValueError):
    """A qualification, cohort, checkpoint, resource, or slot drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checkpoint_filename(index: int) -> str:
    return f"member-{index:02d}.checkpoint.bin"


def _validate_device_binding(
        freeze: V2ExecutionFreezeV1,
        primary: V2CohortRealizationV1,
        plan: V2DeviceQualificationPlanV1,
        result: V2DeviceQualificationResultV1) -> str:
    _validate_realization_binding(freeze, primary)
    try:
        expected = build_qualification_plan_from_primary(
            execution_git=freeze.execution_git,
            candidate_device=freeze.training_candidate_device,
            primary=primary,
            host_memory_cap_bytes=(
                freeze.resource_caps.training_host_memory_bytes),
            device_memory_cap_bytes=(
                freeze.resource_caps.training_device_memory_bytes))
        validate_qualification_result(plan, result)
    except ValueError as exc:
        raise BeliefV2TrainingControllerError(
            "V2 training device qualification refused") from exc
    if plan.canonical_bytes() != expected.canonical_bytes():
        raise BeliefV2TrainingControllerError(
            "V2 training device plan/primary binding drift")
    return result.selected_device


def _validate_realization_binding(
        freeze: V2ExecutionFreezeV1,
        realization: V2CohortRealizationV1) -> None:
    plans = [plan for plan in freeze.cohorts
             if plan.cohort_id == realization.cohort_id]
    if len(plans) != 1 \
            or type(realization.cohort_id) is not str \
            or not realization.cohort_id \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                   for char in realization.cohort_id) \
            or realization.cohort_id.startswith("-") \
            or realization.cohort_id.endswith("-"):
        raise BeliefV2TrainingControllerError(
            "V2 training cohort is absent or duplicated in freeze")
    plan = plans[0]
    expected_plan_sha = _sha256(canonical_json_bytes(plan.to_dict()))
    try:
        realization.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2TrainingControllerError(
            "V2 training realization refused") from exc
    if realization.kind != plan.kind \
            or realization.cohort_plan_sha256 != expected_plan_sha \
            or realization.comparator_cohort_id \
            != plan.comparator_cohort_id:
        raise BeliefV2TrainingControllerError(
            "V2 training realization/freeze binding drift")


def _resource_row(
        freeze: V2ExecutionFreezeV1, *, started: int, finished: int,
        cpu_nanoseconds: int, artifact_bytes: int,
        selected_device: str, peak_host_memory_bytes: int,
        peak_device_memory_bytes: int) -> dict[str, Any]:
    wall = finished - started
    caps = freeze.resource_caps
    if type(started) is not int or type(finished) is not int \
            or not 0 <= started < finished \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or type(artifact_bytes) is not int or artifact_bytes <= 0 \
            or type(peak_host_memory_bytes) is not int \
            or peak_host_memory_bytes <= 0 \
            or type(peak_device_memory_bytes) is not int \
            or peak_device_memory_bytes < 0 \
            or wall > caps.training_wall_seconds * 1_000_000_000 \
            or wall > caps.training_device_hours * 3_600_000_000_000 \
            or artifact_bytes > caps.training_bytes \
            or peak_host_memory_bytes \
            > caps.training_host_memory_bytes \
            or peak_device_memory_bytes \
            > caps.training_device_memory_bytes:
        raise BeliefV2TrainingControllerError(
            "V2 training resource cap or measurement drift")
    return {
        "schema": TRAINING_RESOURCE_SCHEMA,
        "boot_identity": freeze.runtime.boot_identity,
        "selected_device": selected_device,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": wall,
        "cpu_nanoseconds": cpu_nanoseconds,
        "training_compute_nanoseconds": wall,
        "artifact_bytes": artifact_bytes,
        "peak_host_memory_bytes": peak_host_memory_bytes,
        "peak_device_memory_bytes": peak_device_memory_bytes,
        "retry_count": 0,
        "drop_count": 0,
    }


def _stage_manifest(
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1,
        realization: V2CohortRealizationV1,
        calibration: V2CalibrationScheduleV1,
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1,
        trained: V2TrainedCohortArtifactsV1,
        resources: dict[str, Any]) -> dict[str, Any]:
    result_raw = qualification_result.canonical_bytes(qualification_plan)
    trained_raw = trained.manifest_bytes()
    return {
        "schema": TRAINING_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "primary_realization_sha256": primary.sha256(),
        "cohort_id": realization.cohort_id,
        "cohort_kind": realization.kind,
        "realization_sha256": realization.sha256(),
        "common_calibration_sha256": calibration.sha256(),
        "qualification_plan_sha256": qualification_plan.sha256(),
        "qualification_result_sha256": _sha256(result_raw),
        "selected_device": qualification_result.selected_device,
        "trained_manifest_filename": "trained-cohort.json",
        "trained_manifest_byte_count": len(trained_raw),
        "trained_manifest_sha256": _sha256(trained_raw),
        "checkpoints": [{
            "member_index": index,
            "filename": _checkpoint_filename(index),
            "byte_count": len(raw),
            "sha256": _sha256(raw),
        } for index, raw in enumerate(trained.checkpoint_bundles)],
        "resources": resources,
        "contains_corpus_rows": False,
        "contains_optimizer_resume_state": False,
        "test_split_opened": False,
        "test_split_open_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_training_cohort(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        review_marker: bytes, primary: V2CohortRealizationV1,
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...],
        calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...],
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1) \
        -> dict[str, Any]:
    """Train and atomically publish one exact frozen V2 cohort."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    _validate_realization_binding(freeze, realization)
    selected_device = _validate_device_binding(
        freeze, primary, qualification_plan, qualification_result)
    parent = root / "training"
    if parent.is_symlink():
        raise BeliefV2TrainingControllerError(
            "V2 training parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / realization.cohort_id
    partial = parent / f"{realization.cohort_id}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2TrainingControllerError(
            "V2 training cohort slot is occupied")
    partial.mkdir(mode=0o700)
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    deadline = stage_deadline(
        freeze, admission, stage="training", slot=realization.cohort_id,
        started_monotonic_nanoseconds=started)

    def deadline_check(phase: str, next_unit_index: int) -> None:
        try:
            deadline.check(
                phase=phase, next_unit_index=next_unit_index,
                observed_monotonic_nanoseconds=time.monotonic_ns())
        except BeliefV2DeadlineError as exc:
            publish_deadline_refusal(partial, exc.refusal)
            raise BeliefV2TrainingControllerError(
                "V2 training deadline exhausted and recorded") from exc

    try:
        prepare_device_memory_measurement(
            selected_device,
            freeze.resource_caps.training_device_memory_bytes)
        synchronize_training_device(selected_device)
        trained = train_v2_cohort_in_memory(
            realization, training_examples, calibration,
            calibration_examples, device=selected_device,
            deadline_check=deadline_check)
        synchronize_training_device(selected_device)
        peak_host_memory = host_peak_memory_bytes()
        peak_device_memory = device_peak_memory_bytes(selected_device)
    except (RuntimeError, ValueError) as exc:
        raise BeliefV2TrainingControllerError(
            "V2 cohort training refused") from exc
    if trained.training_device != selected_device:
        raise BeliefV2TrainingControllerError(
            "V2 trained cohort selected-device drift")
    deadline_check("before-seal", len(trained.epochs))
    trained_raw = trained.manifest_bytes()
    publish_exclusive_bytes(partial / "trained-cohort.json", trained_raw)
    for index, raw in enumerate(trained.checkpoint_bundles):
        publish_exclusive_bytes(
            partial / _checkpoint_filename(index), raw)
    finished = time.monotonic_ns()
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=len(trained_raw)
        + sum(len(raw) for raw in trained.checkpoint_bundles),
        selected_device=selected_device,
        peak_host_memory_bytes=peak_host_memory,
        peak_device_memory_bytes=peak_device_memory)
    manifest = _stage_manifest(
        freeze, admission, primary, realization, calibration,
        qualification_plan, qualification_result, trained, resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_training_cohort(
        final, freeze=freeze, admission=admission, primary=primary,
        realization=realization, training_examples=training_examples,
        calibration=calibration,
        calibration_examples=calibration_examples,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result)
    if reopened[0] != manifest or reopened[1] != trained:
        raise BeliefV2TrainingControllerError(
            "V2 training cohort post-publish drift")
    return manifest


def reopen_training_cohort(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1,
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...],
        calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...],
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1) \
        -> tuple[dict[str, Any], V2TrainedCohortArtifactsV1]:
    """Reopen every persisted byte and reconstruct the trained cohort."""
    _validate_realization_binding(freeze, realization)
    selected_device = _validate_device_binding(
        freeze, primary, qualification_plan, qualification_result)
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() \
            or directory.name != realization.cohort_id:
        raise BeliefV2TrainingControllerError(
            "V2 training cohort directory drift")
    manifest_raw = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2TrainingControllerError(
            "V2 training stage manifest is not JSON") from exc
    trained_raw = stable_read_bytes(directory / "trained-cohort.json")
    checkpoint_bundles = tuple(stable_read_bytes(
        directory / _checkpoint_filename(index))
        for index in range(len(COHORT_SEEDS)))
    try:
        trained = reopen_trained_v2_cohort(
            trained_raw, checkpoint_bundles, realization,
            training_examples, calibration, calibration_examples)
    except ValueError as exc:
        raise BeliefV2TrainingControllerError(
            "V2 persisted trained cohort refused") from exc
    if trained.training_device != selected_device:
        raise BeliefV2TrainingControllerError(
            "V2 persisted trained cohort selected-device drift")
    resources = payload.get("resources") if type(payload) is dict else None
    expected = _stage_manifest(
        freeze, admission, primary, realization, calibration,
        qualification_plan, qualification_result, trained, resources)
    expected_files = {
        "manifest.json", "trained-cohort.json",
        *(_checkpoint_filename(index) for index in range(len(COHORT_SEEDS)))}
    if type(payload) is not dict \
            or canonical_json_bytes(payload) != manifest_raw \
            or payload != expected \
            or payload["selected_device"] != selected_device \
            or {path.name for path in directory.iterdir()} != expected_files:
        raise BeliefV2TrainingControllerError(
            "V2 training stage manifest reconstruction drift")
    resource_keys = {
        "schema", "boot_identity", "selected_device",
        "started_monotonic_nanoseconds", "finished_monotonic_nanoseconds",
        "wall_nanoseconds", "cpu_nanoseconds",
        "training_compute_nanoseconds", "artifact_bytes",
        "peak_host_memory_bytes", "peak_device_memory_bytes",
        "retry_count", "drop_count"}
    caps = freeze.resource_caps
    if type(resources) is not dict or set(resources) != resource_keys \
            or resources["schema"] != TRAINING_RESOURCE_SCHEMA \
            or resources["boot_identity"] != freeze.runtime.boot_identity \
            or resources["selected_device"] != selected_device \
            or type(resources["started_monotonic_nanoseconds"]) is not int \
            or type(resources["finished_monotonic_nanoseconds"]) is not int \
            or not 0 <= resources["started_monotonic_nanoseconds"] \
            < resources["finished_monotonic_nanoseconds"] \
            or resources["wall_nanoseconds"] != (
                resources["finished_monotonic_nanoseconds"]
                - resources["started_monotonic_nanoseconds"]) \
            or resources["training_compute_nanoseconds"] \
            != resources["wall_nanoseconds"] \
            or type(resources["cpu_nanoseconds"]) is not int \
            or resources["cpu_nanoseconds"] < 0 \
            or resources["artifact_bytes"] != (
                len(trained_raw) + sum(len(raw)
                                       for raw in checkpoint_bundles)) \
            or type(resources["peak_host_memory_bytes"]) is not int \
            or resources["peak_host_memory_bytes"] <= 0 \
            or type(resources["peak_device_memory_bytes"]) is not int \
            or resources["peak_device_memory_bytes"] < 0 \
            or resources["wall_nanoseconds"] \
            > caps.training_wall_seconds * 1_000_000_000 \
            or resources["training_compute_nanoseconds"] \
            > caps.training_device_hours * 3_600_000_000_000 \
            or resources["artifact_bytes"] > caps.training_bytes \
            or resources["peak_host_memory_bytes"] \
            > caps.training_host_memory_bytes \
            or resources["peak_device_memory_bytes"] \
            > caps.training_device_memory_bytes \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0:
        raise BeliefV2TrainingControllerError(
            "V2 training stage resource drift")
    return payload, trained
