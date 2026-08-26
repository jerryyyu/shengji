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
from typing import Any, Callable

import torch

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_cohort_training import (
    V2TrainedCohortArtifactsV1,
    _calibration_batches,
    reopen_trained_v2_cohort,
    train_v2_cohort_from_batch_factories,
    train_v2_cohort_in_memory,
    train_v2_cohort_streaming,
)
from .belief_v2_controller import _stage_gate
from .belief_v2_deadline import (
    DEADLINE_REFUSAL_FILENAME,
    BeliefV2DeadlineError,
    publish_deadline_refusal,
    stage_deadline,
)
from .belief_v2_epoch_journal import (
    MANIFEST_FILENAME as EPOCH_JOURNAL_MANIFEST_FILENAME,
    V2EpochJournalBindingV1,
    publish_epoch_resume_state,
    reopen_epoch_manifests,
    reopen_epoch_snapshots,
    reopen_latest_epoch_resume,
)
from .belief_v2_device_qualification import (
    V2DeviceQualificationPlanV1,
    V2DeviceQualificationResultV1,
    build_qualification_plan_from_primary,
    training_host_memory_upper_bound,
    validate_qualification_result,
)
from .belief_v2_device_runner import (
    device_peak_memory_bytes,
    host_peak_memory_bytes,
    prepare_device_memory_measurement,
    synchronize_training_device,
)
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_progress import ProgressCallback
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
)
from .belief_v2_training import V2TrainingExampleV1
from .belief_v2_streaming_training import (
    iter_streaming_calibration_batches,
)
from .belief_model import new_from_scratch_model
from .belief_v2_accelerator import (
    evaluate_v2_calibration_cohort_stream_nanonats,
)


TRAINING_STAGE_SCHEMA = "belief-v1-v2-training-stage-result-v1"
TRAINING_RESOURCE_SCHEMA = "belief-v1-v2-training-stage-resource-v2"


class BeliefV2TrainingControllerError(ValueError):
    """A qualification, cohort, checkpoint, resource, or slot drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checkpoint_filename(index: int) -> str:
    return f"member-{index:02d}.checkpoint.bin"


def _tree_bytes(directory: Path) -> int:
    if directory.is_symlink() or not directory.is_dir():
        raise BeliefV2TrainingControllerError(
            "V2 training artifact tree drift")
    total = 0
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise BeliefV2TrainingControllerError(
                "V2 training artifact tree contains a symlink")
        if path.is_file():
            total += path.stat().st_size
    return total


def _journal_binding(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        realization: V2CohortRealizationV1,
        calibration: V2CalibrationScheduleV1,
        selected_device: str) -> V2EpochJournalBindingV1:
    return V2EpochJournalBindingV1(
        freeze_sha256=freeze.sha256(),
        admission_sha256=admission.sha256(),
        cohort_id=realization.cohort_id,
        realization_sha256=realization.sha256(),
        common_calibration_sha256=calibration.sha256(),
        selected_device=selected_device,
        torch_num_threads=torch.get_num_threads(),
        journal_byte_cap=freeze.resource_caps.training_bytes)


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
    try:
        host_memory_process_count, aggregate_host_memory = (
            training_host_memory_upper_bound(
                peak_host_memory_bytes, selected_device=selected_device,
                cpu_cohort_process_count=len(freeze.cohorts)))
    except ValueError as exc:
        raise BeliefV2TrainingControllerError(
            "V2 training resource cap or measurement drift") from exc
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
            or aggregate_host_memory \
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
        "host_memory_process_count": host_memory_process_count,
        "aggregate_peak_host_memory_upper_bound_bytes": (
            aggregate_host_memory),
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
        resources: dict[str, Any], *, journal_head: dict[str, Any],
        journal_head_sha256: str, deadline_refusal: dict[str, Any] | None,
        cache_manifest_sha256: str | None) \
        -> dict[str, Any]:
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
        "epoch_journal": {
            "directory": "epoch-journal",
            "epoch_count": len(trained.epochs),
            "head_manifest_sha256": journal_head_sha256,
            "exact_resume_count": journal_head["exact_resume_count"],
            "mandatory_latest_epoch_resume": True,
        },
        "truncated_by_deadline": trained.truncated_by_deadline,
        "deadline_refusal": deadline_refusal,
        "tensor_cache_stage_manifest_sha256": cache_manifest_sha256,
        "resources": resources,
        "contains_corpus_rows": False,
        "contains_optimizer_resume_state": True,
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
        training_examples: tuple[V2TrainingExampleV1, ...] | None,
        calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...] | None,
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1,
        streaming_index=None, load_round=None,
        training_batch_factory: Callable[[], Any] | None = None,
        calibration_batch_factory: Callable[[], Any] | None = None,
        cache_manifest_sha256: str | None = None,
        cache_control_dose: int | None = None,
        progress: ProgressCallback | None = None) \
        -> dict[str, Any]:
    """Train and atomically publish one exact frozen V2 cohort."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    _validate_realization_binding(freeze, realization)
    selected_device = _validate_device_binding(
        freeze, primary, qualification_plan, qualification_result)
    streaming = streaming_index is not None or load_round is not None
    materialized = training_examples is not None \
        and calibration_examples is not None
    cached = any(value is not None for value in (
        training_batch_factory, calibration_batch_factory,
        cache_manifest_sha256, cache_control_dose))
    if streaming != (streaming_index is not None and callable(load_round)) \
            or (training_examples is None) \
            != (calibration_examples is None) \
            or cached != (callable(training_batch_factory)
                          and callable(calibration_batch_factory)
                          and type(cache_manifest_sha256) is str
                          and len(cache_manifest_sha256) == 64
                          and type(cache_control_dose) is int
                          and cache_control_dose >= 0) \
            or sum((streaming, materialized, cached)) != 1:
        raise BeliefV2TrainingControllerError(
            "V2 training input mode drift")
    parent = root / "training"
    if parent.is_symlink():
        raise BeliefV2TrainingControllerError(
            "V2 training parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / realization.cohort_id
    partial = parent / f"{realization.cohort_id}.partial"
    if final.exists() or final.is_symlink():
        raise BeliefV2TrainingControllerError(
            "V2 training cohort slot is occupied")
    resuming = partial.exists()
    if resuming:
        if partial.is_symlink() or not partial.is_dir() \
                or {path.name for path in partial.iterdir()} \
                != {"epoch-journal"}:
            raise BeliefV2TrainingControllerError(
                "V2 training partial is not exactly resumable")
    else:
        partial.mkdir(mode=0o700)
    journal = partial / "epoch-journal"
    journal_binding = _journal_binding(
        freeze, admission, realization, calibration, selected_device)
    reopened_resume = (
        reopen_latest_epoch_resume(journal, journal_binding)
        if resuming else None)
    if resuming and reopened_resume is None:
        raise BeliefV2TrainingControllerError(
            "V2 training partial lacks a completed resume epoch")
    resume_state = None if reopened_resume is None else reopened_resume[0]
    prior_head = None if reopened_resume is None else reopened_resume[1]
    started = (time.monotonic_ns() if prior_head is None else
               prior_head["stage_started_monotonic_nanoseconds"])
    prior_cpu = (0 if prior_head is None else
                 prior_head["cumulative_cpu_nanoseconds"])
    exact_resume_count = (0 if prior_head is None else
                          prior_head["exact_resume_count"] + 1)
    cpu_started = time.process_time_ns()
    deadline = stage_deadline(
        freeze, admission, stage="training", slot=realization.cohort_id,
        started_monotonic_nanoseconds=started)

    deadline_refusal_value = None

    def deadline_check(phase: str, next_unit_index: int) -> None:
        nonlocal deadline_refusal_value
        try:
            deadline.check(
                phase=phase, next_unit_index=next_unit_index,
                observed_monotonic_nanoseconds=time.monotonic_ns())
        except BeliefV2DeadlineError as exc:
            # A completed-epoch expiry is recorded only when the final
            # truncated artifact is ready to publish.  Until then the durable
            # epoch journal is the only partial state, so a crash cannot leave
            # an unresumable journal+refusal mixture.  A pre-epoch expiry has
            # no resumable state and is persisted by the exception path below.
            deadline_refusal_value = exc.refusal
            raise

    def epoch_checkpoint(state) -> None:
        publish_epoch_resume_state(
            journal, journal_binding, state,
            stage_started_monotonic_nanoseconds=started,
            observed_monotonic_nanoseconds=time.monotonic_ns(),
            cumulative_cpu_nanoseconds=(
                prior_cpu + time.process_time_ns() - cpu_started),
            exact_resume_count=exact_resume_count)

    try:
        prepare_device_memory_measurement(
            selected_device,
            freeze.resource_caps.training_device_memory_bytes)
        synchronize_training_device(selected_device)
        if cached:
            trained = train_v2_cohort_from_batch_factories(
                realization, calibration, device=selected_device,
                training_batches=training_batch_factory,
                calibration_batches=calibration_batch_factory,
                control_dose=cache_control_dose,
                deadline_check=deadline_check,
                resume_state=resume_state,
                epoch_checkpoint=epoch_checkpoint, progress=progress)
        elif streaming:
            trained = train_v2_cohort_streaming(
                realization, calibration, index=streaming_index,
                load_round=load_round, device=selected_device,
                deadline_check=deadline_check,
                resume_state=resume_state,
                epoch_checkpoint=epoch_checkpoint, progress=progress)
        else:
            trained = train_v2_cohort_in_memory(
                realization, training_examples, calibration,
                calibration_examples, device=selected_device,
                deadline_check=deadline_check,
                resume_state=resume_state,
                epoch_checkpoint=epoch_checkpoint, progress=progress)
        synchronize_training_device(selected_device)
        peak_host_memory = host_peak_memory_bytes()
        peak_device_memory = device_peak_memory_bytes(selected_device)
    except (RuntimeError, ValueError) as exc:
        if deadline_refusal_value is not None \
                and reopen_latest_epoch_resume(
                    journal, journal_binding) is None \
                and not (partial / DEADLINE_REFUSAL_FILENAME).exists():
            publish_deadline_refusal(partial, deadline_refusal_value)
        raise BeliefV2TrainingControllerError(
            "V2 cohort training refused") from exc
    if trained.training_device != selected_device:
        raise BeliefV2TrainingControllerError(
            "V2 trained cohort selected-device drift")
    reopened_head = reopen_latest_epoch_resume(journal, journal_binding)
    if reopened_head is None or len(reopened_head[0].epochs) \
            != len(trained.epochs):
        raise BeliefV2TrainingControllerError(
            "V2 training epoch journal head drift")
    journal_head = reopened_head[1]
    journal_head_raw = stable_read_bytes(
        journal / f"epoch-{len(trained.epochs):04d}"
        / EPOCH_JOURNAL_MANIFEST_FILENAME)
    deadline_refusal = None
    if trained.truncated_by_deadline:
        if deadline_refusal_value is None:
            raise BeliefV2TrainingControllerError(
                "V2 truncated cohort lacks its exact deadline refusal")
        publish_deadline_refusal(partial, deadline_refusal_value)
        refusal_raw = stable_read_bytes(
            partial / DEADLINE_REFUSAL_FILENAME)
        deadline_refusal = {
            "filename": DEADLINE_REFUSAL_FILENAME,
            "byte_count": len(refusal_raw),
            "sha256": _sha256(refusal_raw),
            "final_artifact_sealed": True,
            "calibration_open_authorized": False,
            "test_split_open_authorized": False,
        }
    trained_raw = trained.manifest_bytes()
    publish_exclusive_bytes(partial / "trained-cohort.json", trained_raw)
    for index, raw in enumerate(trained.checkpoint_bundles):
        publish_exclusive_bytes(
            partial / _checkpoint_filename(index), raw)
    finished = time.monotonic_ns()
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=(prior_cpu + time.process_time_ns() - cpu_started),
        artifact_bytes=len(trained_raw)
        + sum(len(raw) for raw in trained.checkpoint_bundles)
        + _tree_bytes(journal)
        + (0 if deadline_refusal is None else
           deadline_refusal["byte_count"]),
        selected_device=selected_device,
        peak_host_memory_bytes=peak_host_memory,
        peak_device_memory_bytes=peak_device_memory)
    manifest = _stage_manifest(
        freeze, admission, primary, realization, calibration,
        qualification_plan, qualification_result, trained, resources,
        journal_head=journal_head,
        journal_head_sha256=_sha256(journal_head_raw),
        deadline_refusal=deadline_refusal,
        cache_manifest_sha256=cache_manifest_sha256)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopen_control_dose = (
        cache_control_dose if cached else
        streaming_index.control_changed_cell_count
        if streaming and realization.kind
        == "hard-geometry-label-permutation" else 0
        if streaming else None)
    if cached:
        # The cached R5 path performs the expensive saved-epoch re-score once,
        # after every cohort and the calibration selection have sealed.  Here
        # we still reopen the complete journal/stage/checkpoint identity, but
        # do not replay the same calibration cache after each cohort publish.
        reopened = reopen_training_cohort_checkpoint_identity(
            final, freeze=freeze, admission=admission, primary=primary,
            realization=realization, calibration=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result,
            compact_control_dose=reopen_control_dose,
            cache_manifest_sha256=cache_manifest_sha256)
    else:
        reopened = reopen_training_cohort(
            final, freeze=freeze, admission=admission, primary=primary,
            realization=realization, training_examples=training_examples,
            calibration=calibration,
            calibration_examples=calibration_examples,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result,
            compact_control_dose=reopen_control_dose,
            calibration_batch_factory=(
                (lambda: iter_streaming_calibration_batches(
                    streaming_index, calibration, load_round=load_round))
                if streaming else None),
            cache_manifest_sha256=cache_manifest_sha256)
    if reopened[0] != manifest or reopened[1] != trained:
        raise BeliefV2TrainingControllerError(
            "V2 training cohort post-publish drift")
    return manifest


def _reopen_training_cohort(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1,
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...] | None,
        calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...] | None,
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1,
        compact_control_dose: int | None = None,
        calibration_batch_factory: Callable[[], Any] | None = None,
        cache_manifest_sha256: str | None = None,
        verify_epoch_calibration_losses: bool,
        progress: ProgressCallback | None = None) \
        -> tuple[dict[str, Any], V2TrainedCohortArtifactsV1]:
    """Reopen persisted bytes at one explicitly selected proof altitude."""
    _validate_realization_binding(freeze, realization)
    selected_device = _validate_device_binding(
        freeze, primary, qualification_plan, qualification_result)
    compact = compact_control_dose is not None
    materialized = training_examples is not None \
        and calibration_examples is not None
    cached = cache_manifest_sha256 is not None
    if type(verify_epoch_calibration_losses) is not bool \
            or progress is not None and not callable(progress) \
            or (training_examples is None) != (calibration_examples is None) \
            or compact == materialized \
            or (verify_epoch_calibration_losses
                and compact != callable(calibration_batch_factory)) \
            or (not verify_epoch_calibration_losses
                and calibration_batch_factory is not None) \
            or cached and (type(cache_manifest_sha256) is not str
                           or len(cache_manifest_sha256) != 64):
        raise BeliefV2TrainingControllerError(
            "V2 training reopen input mode drift")
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
            training_examples, calibration, calibration_examples,
            compact_control_dose=compact_control_dose)
    except ValueError as exc:
        raise BeliefV2TrainingControllerError(
            "V2 persisted trained cohort refused") from exc
    if trained.training_device != selected_device:
        raise BeliefV2TrainingControllerError(
            "V2 persisted trained cohort selected-device drift")
    journal = directory / "epoch-journal"
    journal_binding = _journal_binding(
        freeze, admission, realization, calibration, selected_device)
    snapshots = (reopen_epoch_snapshots(journal, journal_binding)
                 if verify_epoch_calibration_losses
                 else reopen_epoch_manifests(journal, journal_binding))
    if len(snapshots) != len(trained.epochs):
        raise BeliefV2TrainingControllerError(
            "V2 persisted epoch journal head drift")
    if snapshots[-1].curves != trained.epochs:
        raise BeliefV2TrainingControllerError(
            "V2 persisted epoch curve cross-binding drift")
    if verify_epoch_calibration_losses:
        if materialized:
            calibration_batches = _calibration_batches(
                calibration, calibration_examples)
            calibration_factory = lambda: iter(calibration_batches)
        else:
            calibration_factory = calibration_batch_factory
        if progress is not None:
            progress(0, len(snapshots), "reopen-saved-epoch-curves")
        for epoch_index, (snapshot, curve) in enumerate(zip(
                snapshots, trained.epochs, strict=True), 1):
            models = []
            for seed, state in zip(
                    COHORT_SEEDS, snapshot.current_model_states, strict=True):
                model = new_from_scratch_model(seed)
                try:
                    model.load_state_dict(state, strict=True)
                except (RuntimeError, ValueError) as exc:
                    raise BeliefV2TrainingControllerError(
                        "V2 epoch calibration model state refused") from exc
                models.append(model)
            try:
                rescored = evaluate_v2_calibration_cohort_stream_nanonats(
                    tuple(models), calibration_factory(), device="cpu")
            except ValueError as exc:
                raise BeliefV2TrainingControllerError(
                    "V2 epoch calibration source re-score refused") from exc
            if rescored != curve.member_calibration_loss_nanonats:
                raise BeliefV2TrainingControllerError(
                    "V2 epoch calibration loss re-score drift")
            if progress is not None:
                progress(epoch_index, len(snapshots),
                         "reopen-saved-epoch-curves")
    journal_head = snapshots[-1].manifest
    journal_head_raw = stable_read_bytes(
        journal / f"epoch-{len(trained.epochs):04d}"
        / EPOCH_JOURNAL_MANIFEST_FILENAME)
    deadline_refusal = None
    if trained.truncated_by_deadline:
        refusal_raw = stable_read_bytes(
            directory / DEADLINE_REFUSAL_FILENAME)
        deadline_refusal = {
            "filename": DEADLINE_REFUSAL_FILENAME,
            "byte_count": len(refusal_raw),
            "sha256": _sha256(refusal_raw),
            "final_artifact_sealed": True,
            "calibration_open_authorized": False,
            "test_split_open_authorized": False,
        }
    resources = payload.get("resources") if type(payload) is dict else None
    expected = _stage_manifest(
        freeze, admission, primary, realization, calibration,
        qualification_plan, qualification_result, trained, resources,
        journal_head=journal_head,
        journal_head_sha256=_sha256(journal_head_raw),
        deadline_refusal=deadline_refusal,
        cache_manifest_sha256=cache_manifest_sha256)
    expected_files = {
        "manifest.json", "trained-cohort.json", "epoch-journal",
        *(_checkpoint_filename(index) for index in range(len(COHORT_SEEDS)))}
    if trained.truncated_by_deadline:
        expected_files.add(DEADLINE_REFUSAL_FILENAME)
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
        "peak_host_memory_bytes", "host_memory_process_count",
        "aggregate_peak_host_memory_upper_bound_bytes",
        "peak_device_memory_bytes",
        "retry_count", "drop_count"}
    caps = freeze.resource_caps
    try:
        expected_host_process_count, expected_aggregate_host_memory = (
            training_host_memory_upper_bound(
                resources.get("peak_host_memory_bytes"),
                selected_device=selected_device,
                cpu_cohort_process_count=len(freeze.cohorts)))
    except (AttributeError, ValueError) as exc:
        raise BeliefV2TrainingControllerError(
            "V2 training stage resource drift") from exc
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
                                       for raw in checkpoint_bundles)
                + _tree_bytes(journal)
                + (0 if deadline_refusal is None else
                   deadline_refusal["byte_count"])) \
            or type(resources["peak_host_memory_bytes"]) is not int \
            or resources["peak_host_memory_bytes"] <= 0 \
            or resources["host_memory_process_count"] \
            != expected_host_process_count \
            or resources["aggregate_peak_host_memory_upper_bound_bytes"] \
            != expected_aggregate_host_memory \
            or type(resources["peak_device_memory_bytes"]) is not int \
            or resources["peak_device_memory_bytes"] < 0 \
            or resources["wall_nanoseconds"] \
            > caps.training_wall_seconds * 1_000_000_000 \
            or resources["training_compute_nanoseconds"] \
            > caps.training_device_hours * 3_600_000_000_000 \
            or resources["artifact_bytes"] > caps.training_bytes \
            or resources["aggregate_peak_host_memory_upper_bound_bytes"] \
            > caps.training_host_memory_bytes \
            or resources["peak_device_memory_bytes"] \
            > caps.training_device_memory_bytes \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0:
        raise BeliefV2TrainingControllerError(
            "V2 training stage resource drift")
    return payload, trained


def reopen_training_cohort(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1,
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...] | None,
        calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...] | None,
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1,
        compact_control_dose: int | None = None,
        calibration_batch_factory: Callable[[], Any] | None = None,
        cache_manifest_sha256: str | None = None,
        progress: ProgressCallback | None = None) \
        -> tuple[dict[str, Any], V2TrainedCohortArtifactsV1]:
    """Fully reopen a cohort, including every saved-epoch loss re-score."""
    return _reopen_training_cohort(
        directory, freeze=freeze, admission=admission, primary=primary,
        realization=realization, training_examples=training_examples,
        calibration=calibration,
        calibration_examples=calibration_examples,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result,
        compact_control_dose=compact_control_dose,
        calibration_batch_factory=calibration_batch_factory,
        cache_manifest_sha256=cache_manifest_sha256,
        verify_epoch_calibration_losses=True, progress=progress)


def reopen_training_cohort_checkpoint_identity(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        primary: V2CohortRealizationV1,
        realization: V2CohortRealizationV1,
        calibration: V2CalibrationScheduleV1,
        qualification_plan: V2DeviceQualificationPlanV1,
        qualification_result: V2DeviceQualificationResultV1,
        compact_control_dose: int,
        cache_manifest_sha256: str) \
        -> tuple[dict[str, Any], V2TrainedCohortArtifactsV1]:
    """Authenticate selected checkpoints without claiming curve re-score.

    Calibration may use this target-blind identity boundary before the durable
    pre-test readiness stage performs the one full saved-epoch proof.  It is
    intentionally unable to consume a batch factory or authorize a test open.
    """
    if type(compact_control_dose) is not int or compact_control_dose < 0:
        raise BeliefV2TrainingControllerError(
            "V2 checkpoint identity control dose drift")
    return _reopen_training_cohort(
        directory, freeze=freeze, admission=admission, primary=primary,
        realization=realization, training_examples=None,
        calibration=calibration, calibration_examples=None,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result,
        compact_control_dose=compact_control_dose,
        calibration_batch_factory=None,
        cache_manifest_sha256=cache_manifest_sha256,
        verify_epoch_calibration_losses=False, progress=None)
