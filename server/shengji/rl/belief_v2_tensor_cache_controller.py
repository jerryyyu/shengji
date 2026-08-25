"""Durable lossless train/calibration tensor caches for BELIEF-V1 V2.

This stage runs only after the compact input index exists.  It reopens the
same manifest-bound non-test sources as the streaming trainer, writes one
lossless sparse actor cache per distinct cohort schedule, shares the primary
actor cache with the hard-geometry label control through a label-only overlay,
and writes one common calibration cache shared by every cohort.

Every cache is bound to the exact decision population, batch schedule, source
index, runtime, and storage cap.  No test target is opened and no cache grants
training, evaluation, gameplay, strength, or deployment authority.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import resource
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_controller import _stage_gate
from .belief_v2_cache_import import (
    BeliefV2CacheImportError,
    V2TensorCacheImportSpecV1,
    load_tensor_cache_import_spec,
)
from .belief_v2_deadline import (
    BeliefV2DeadlineError,
    publish_deadline_refusal,
    stage_deadline,
)
from .belief_v2_freeze import (
    CONTROL_COHORT_ID,
    PRIMARY_COHORT_ID,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
)
from .belief_v2_input_index_controller import reopen_training_input_index
from .belief_v2_device_runner import host_peak_memory_bytes
from .belief_v2_progress import ProgressCallback
from .belief_v2_parallel_cache import (
    build_parallel_tensor_cache,
    build_parallel_tensor_cache_with_control_overlay,
    parallel_cache_build_topology,
    parallel_cache_worker_count,
    primary_cache_first_build_order,
)
from .belief_v2_streaming_inputs import V2ArtifactRoundLoader
from .belief_v2_streaming_training import (
    iter_streaming_calibration_batches,
    iter_streaming_training_batches,
)
from .belief_v2_training import label_control_batch_from_natural
from .belief_v2_tensor_cache import (
    V2TensorCacheBindingV1,
    build_label_overlay,
    build_tensor_cache,
    cached_batch_factory,
    reopen_label_overlay,
    reopen_label_overlay_manifest,
    reopen_tensor_cache,
    reopen_tensor_cache_manifest,
)


TENSOR_CACHE_STAGE_SCHEMA = "belief-v1-v2-training-tensor-cache-stage-v4"
TENSOR_CACHE_RESOURCE_SCHEMA = (
    "belief-v1-v2-training-tensor-cache-resource-v4")
TENSOR_CACHE_START_SCHEMA = "belief-v1-v2-training-tensor-cache-start-v1"
TENSOR_CACHE_RESOURCE_REFUSAL_SCHEMA = (
    "belief-v1-v2-training-tensor-cache-resource-refusal-v1")
STAGE_DIRECTORY = "training-tensor-cache"
RESULT_DIRECTORY = "result"
MANIFEST_FILENAME = "manifest.json"
START_FILENAME = "stage-start.json"
RESOURCE_REFUSAL_FILENAME = "resource-refusal.json"
IMPORT_RECEIPT_FILENAME = "cache-import.json"
CALIBRATION_CACHE_ID = "common-calibration"
CONTROL_OVERLAY_DIRECTORY = f"overlay-{CONTROL_COHORT_ID}"


class BeliefV2TensorCacheControllerError(ValueError):
    """A cache source, byte population, cap, or authority binding drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _runtime_sha256(freeze: V2ExecutionFreezeV1) -> str:
    return _sha256(canonical_json_bytes(freeze.runtime.to_dict()))


def _usage_memory_bytes(who: int) -> int:
    value = resource.getrusage(who).ru_maxrss
    if type(value) not in {int, float} or value < 0:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache host memory measurement drift")
    return int(value) if sys.platform == "darwin" else int(value) * 1024


def _process_tree_cpu_time_ns() -> int:
    usages = (resource.getrusage(resource.RUSAGE_SELF),
              resource.getrusage(resource.RUSAGE_CHILDREN))
    return int(sum(row.ru_utime + row.ru_stime for row in usages)
               * 1_000_000_000)


def _aggregate_peak_host_memory_bytes(worker_count: int) -> int:
    if type(worker_count) is not int or worker_count <= 0:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache worker count drift")
    parent = max(host_peak_memory_bytes(),
                 _usage_memory_bytes(resource.RUSAGE_SELF))
    child = _usage_memory_bytes(resource.RUSAGE_CHILDREN)
    return max(parent, parent + child * worker_count if child else parent)


def _cache_directory_name(cohort_id: str) -> str:
    if type(cohort_id) is not str or not cohort_id \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                   for char in cohort_id):
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache cohort identifier drift")
    return f"cache-{cohort_id}"


def _realization_binding(
        freeze: V2ExecutionFreezeV1, input_index_sha256: str,
        realization) -> V2TensorCacheBindingV1:
    return V2TensorCacheBindingV1(
        cache_id=realization.cohort_id,
        split="train",
        decision_population_sha256=realization.decision_population_sha256,
        batch_schedule_sha256=realization.batch_schedule_sha256,
        source_index_sha256=input_index_sha256,
        runtime_profile_sha256=_runtime_sha256(freeze),
        expected_decision_count=len(realization.rows),
        expected_batch_count=len(realization.batches),
        storage_cap_bytes=freeze.resource_caps.training_bytes,
    )


def _calibration_binding(
        freeze: V2ExecutionFreezeV1, input_index_sha256: str,
        calibration) -> V2TensorCacheBindingV1:
    return V2TensorCacheBindingV1(
        cache_id=CALIBRATION_CACHE_ID,
        split="calibration",
        decision_population_sha256=calibration.decision_population_sha256,
        batch_schedule_sha256=calibration.batch_schedule_sha256,
        source_index_sha256=input_index_sha256,
        runtime_profile_sha256=_runtime_sha256(freeze),
        expected_decision_count=len(calibration.rows),
        expected_batch_count=len(calibration.batches),
        storage_cap_bytes=freeze.resource_caps.training_bytes,
    )


def _resource_row(
        freeze: V2ExecutionFreezeV1, *, started: int, finished: int,
        cpu_nanoseconds: int, artifact_bytes: int,
        peak_host_memory_bytes: int, resumed_from_partial: bool,
        cache_worker_count: int, external_cache_reused: bool) \
        -> dict[str, Any]:
    caps = freeze.resource_caps
    if any(type(value) is not int or value <= 0 for value in (
            started, finished, artifact_bytes, peak_host_memory_bytes)) \
            or finished <= started \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or type(resumed_from_partial) is not bool \
            or type(cache_worker_count) is not int \
            or cache_worker_count <= 0 \
            or type(external_cache_reused) is not bool \
            or cache_worker_count \
            != parallel_cache_worker_count(
                freeze.runtime, caps.training_host_memory_bytes) \
            or finished - started > caps.training_wall_seconds * 1_000_000_000 \
            or artifact_bytes > caps.training_bytes \
            or peak_host_memory_bytes > caps.training_host_memory_bytes:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource cap drift")
    return {
        "schema": TENSOR_CACHE_RESOURCE_SCHEMA,
        "boot_identity": freeze.runtime.boot_identity,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": finished - started,
        "cpu_nanoseconds": cpu_nanoseconds,
        "cpu_nanoseconds_is_conservative_upper_bound": (
            resumed_from_partial),
        "artifact_bytes": artifact_bytes,
        "artifact_bytes_are_logical_referenced_bytes": True,
        "peak_host_memory_bytes": peak_host_memory_bytes,
        "cache_worker_count": cache_worker_count,
        "retry_count": 0,
        "drop_count": 0,
        "resumed_from_exact_partial": resumed_from_partial,
        "external_cache_reused": external_cache_reused,
    }


def _resource_refusal_payload(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *,
        input_index_sha256: str, stage_start_sha256: str,
        started: int, finished: int, cpu_nanoseconds: int,
        artifact_bytes: int, peak_host_memory_bytes: int,
        cache_worker_count: int) -> dict[str, Any] | None:
    """Return an immutable refusal only for a measured cap exceedance."""
    caps = freeze.resource_caps
    if any(type(value) is not int or value <= 0 for value in (
            started, finished, artifact_bytes, peak_host_memory_bytes,
            cache_worker_count)) \
            or finished <= started \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or cache_worker_count != parallel_cache_worker_count(
                freeze.runtime, caps.training_host_memory_bytes):
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource refusal inputs drift")
    wall_nanoseconds = finished - started
    exceeded = []
    if wall_nanoseconds > caps.training_wall_seconds * 1_000_000_000:
        exceeded.append("wall_nanoseconds")
    if artifact_bytes > caps.training_bytes:
        exceeded.append("artifact_bytes")
    if peak_host_memory_bytes > caps.training_host_memory_bytes:
        exceeded.append("peak_host_memory_bytes")
    if not exceeded:
        return None
    return {
        "schema": TENSOR_CACHE_RESOURCE_REFUSAL_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "training_input_index_sha256": input_index_sha256,
        "stage_start_sha256": stage_start_sha256,
        "boot_identity": freeze.runtime.boot_identity,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": wall_nanoseconds,
        "cpu_nanoseconds": cpu_nanoseconds,
        "artifact_bytes": artifact_bytes,
        "peak_host_memory_bytes": peak_host_memory_bytes,
        "cache_worker_count": cache_worker_count,
        "caps": {
            "wall_nanoseconds": (
                caps.training_wall_seconds * 1_000_000_000),
            "artifact_bytes": caps.training_bytes,
            "peak_host_memory_bytes": caps.training_host_memory_bytes,
        },
        "exceeded_dimensions": exceeded,
        "retry_authorized": False,
        "stage_seal_authorized": False,
        "test_split_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _manifest(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *,
        input_index_sha256: str, entries: list[dict[str, Any]],
        calibration: dict[str, Any], control_dose: int,
        stage_start_sha256: str, resources: dict[str, Any],
        cache_worker_count: int, cache_storage: dict[str, Any]) \
        -> dict[str, Any]:
    return {
        "schema": TENSOR_CACHE_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "training_input_index_sha256": input_index_sha256,
        "stage_start_sha256": stage_start_sha256,
        "runtime_profile_sha256": _runtime_sha256(freeze),
        "cohort_caches": entries,
        "common_calibration_cache": calibration,
        "control_changed_cell_count_per_epoch": control_dose,
        "cache_worker_count": cache_worker_count,
        "cache_storage": cache_storage,
        "parallel_actor_cache_build": cache_worker_count > 1,
        "resources": resources,
        "lossless_sparse_event_encoding": True,
        "actor_and_privileged_labels_separate": True,
        "test_split_cached": False,
        "training_authorized_by_this_artifact": False,
        "test_split_open_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _start_payload(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *,
        input_index_sha256: str,
        started_monotonic_nanoseconds: int) -> dict[str, Any]:
    if type(started_monotonic_nanoseconds) is not int \
            or started_monotonic_nanoseconds <= 0:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache start clock drift")
    return {
        "schema": TENSOR_CACHE_START_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "training_input_index_sha256": input_index_sha256,
        "boot_identity": freeze.runtime.boot_identity,
        "started_monotonic_nanoseconds": started_monotonic_nanoseconds,
        "retry_authorized": False,
        "test_split_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _reopen_stage_start(
        path: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *,
        input_index_sha256: str) -> tuple[dict[str, Any], bytes]:
    raw = stable_read_bytes(path)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache start receipt is not JSON") from exc
    if type(payload) is not dict \
            or payload != _start_payload(
                freeze, admission,
                input_index_sha256=input_index_sha256,
                started_monotonic_nanoseconds=payload.get(
                    "started_monotonic_nanoseconds")) \
            or canonical_json_bytes(payload) != raw:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache start receipt drift")
    return payload, raw


def reopen_tensor_cache_resource_refusal(
        path: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        input_index_sha256: str) -> dict[str, Any]:
    """Independently reconstruct one terminal cache resource refusal."""
    raw = stable_read_bytes(path)
    try:
        payload = json.loads(raw)
        _, start_raw = _reopen_stage_start(
            path.parent / START_FILENAME, freeze, admission,
            input_index_sha256=input_index_sha256)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource refusal reopen failed") from exc
    if type(payload) is not dict:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource refusal drift")
    expected = _resource_refusal_payload(
        freeze, admission,
        input_index_sha256=input_index_sha256,
        stage_start_sha256=_sha256(start_raw),
        started=payload.get("started_monotonic_nanoseconds"),
        finished=payload.get("finished_monotonic_nanoseconds"),
        cpu_nanoseconds=payload.get("cpu_nanoseconds"),
        artifact_bytes=payload.get("artifact_bytes"),
        peak_host_memory_bytes=payload.get("peak_host_memory_bytes"),
        cache_worker_count=payload.get("cache_worker_count"))
    if expected is None or payload != expected \
            or canonical_json_bytes(payload) != raw:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource refusal drift")
    return payload


def _completed_cache_receipt(
        directory: Path, *, binding: V2TensorCacheBindingV1) \
        -> dict[str, Any] | None:
    partial = directory.with_name(directory.name + ".partial")
    if partial.exists() and directory.exists():
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache completed/partial ambiguity")
    if not directory.exists():
        return None
    try:
        manifest_raw = stable_read_bytes(directory / "manifest.json")
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache completed manifest refused") from exc
    return _reopen_cache_receipt(
        directory, expected_manifest_sha256=_sha256(manifest_raw),
        binding=binding)


def _completed_overlay_receipt(
        directory: Path, *, actor_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any] | None:
    partial = directory.with_name(directory.name + ".partial")
    if partial.exists() and directory.exists():
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache completed/overlay ambiguity")
    if not directory.exists():
        return None
    try:
        manifest_raw = stable_read_bytes(directory / "labels-manifest.json")
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache completed overlay manifest refused") from exc
    return _reopen_overlay_receipt(
        directory, expected_manifest_sha256=_sha256(manifest_raw),
        actor_manifest_sha256=actor_manifest_sha256,
        binding=binding)


def _entry(
        *, cohort_id: str, realization_sha256: str, kind: str,
        directory: str, binding: V2TensorCacheBindingV1,
        receipt: dict[str, Any], actor_cache_cohort_id: str | None = None,
        actor_manifest_sha256: str | None = None) -> dict[str, Any]:
    return {
        "cohort_id": cohort_id,
        "realization_sha256": realization_sha256,
        "kind": kind,
        "directory": directory,
        "binding": binding.to_dict(),
        "manifest_sha256": receipt["manifest_sha256"],
        "batch_count": receipt["batch_count"],
        "decision_count": receipt["decision_count"],
        "artifact_bytes": receipt["artifact_bytes"],
        "actor_cache_cohort_id": actor_cache_cohort_id,
        "actor_manifest_sha256": actor_manifest_sha256,
    }


def _reopen_cache_receipt(
        directory: Path, *, expected_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    try:
        return reopen_tensor_cache(
            directory,
            expected_manifest_sha256=expected_manifest_sha256,
            binding=binding)
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache byte reopen refused") from exc


def _reopen_overlay_receipt(
        directory: Path, *, expected_manifest_sha256: str,
        actor_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    try:
        return reopen_label_overlay(
            directory,
            expected_manifest_sha256=expected_manifest_sha256,
            actor_manifest_sha256=actor_manifest_sha256,
            binding=binding)
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache overlay reopen refused") from exc


def _reopen_cache_manifest_receipt(
        directory: Path, *, expected_manifest_sha256: str,
        expected_artifact_bytes: int,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    try:
        return reopen_tensor_cache_manifest(
            directory,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_artifact_bytes=expected_artifact_bytes,
            binding=binding)
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache manifest-only reopen refused") from exc


def _reopen_overlay_manifest_receipt(
        directory: Path, *, expected_manifest_sha256: str,
        expected_artifact_bytes: int, actor_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    try:
        return reopen_label_overlay_manifest(
            directory,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_artifact_bytes=expected_artifact_bytes,
            actor_manifest_sha256=actor_manifest_sha256,
            binding=binding)
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache overlay manifest-only reopen refused") from exc


def _local_cache_storage() -> dict[str, Any]:
    return {
        "kind": "local-stage-directory-v1",
        "import_receipt_sha256": None,
        "source_cache_root": None,
        "source_consumption_tombstone_sha256": None,
    }


def _cache_import_receipt(
        spec: V2TensorCacheImportSpecV1, *,
        input_index_sha256: str) -> dict[str, Any]:
    if input_index_sha256 != spec.source_input_index_sha256:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache import input index drift")
    return {
        "schema": "belief-v1-v2-tensor-cache-import-receipt-v1",
        "import_spec_sha256": spec.spec_sha256,
        "source_evidence_root": str(spec.source_evidence_root),
        "source_cache_root": str(spec.source_cache_root),
        "source_execution_git": spec.source_execution_git,
        "source_freeze_sha256": spec.source_freeze_sha256,
        "source_admission_sha256": spec.source_admission_sha256,
        "source_review_marker_sha256": spec.source_review_marker_sha256,
        "source_consumption_tombstone_sha256": (
            spec.source_consumption_tombstone_sha256),
        "source_input_index_sha256": spec.source_input_index_sha256,
        "source_input_index_manifest_sha256": (
            spec.source_input_index_manifest_sha256),
        "source_runtime_profile_sha256": (
            spec.source_runtime_profile_sha256),
        "runtime_portability_rule": (
            "exact-runtime-profile-except-boot-identity-v1"),
        "source_stage_start_sha256": spec.source_stage_start_sha256,
        "child_manifest_sha256s": dict(spec.child_manifest_sha256s),
        "source_admission_remains_spent": True,
        "source_bytes_copied_or_linked": False,
        "retry_authorized": False,
        "test_split_cached": False,
        "test_split_open_authorized": False,
        "training_authorized_by_source_artifact": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _imported_binding(
        binding: V2TensorCacheBindingV1,
        spec: V2TensorCacheImportSpecV1 | None) \
        -> V2TensorCacheBindingV1:
    if spec is None:
        return binding
    return V2TensorCacheBindingV1(
        cache_id=binding.cache_id, split=binding.split,
        decision_population_sha256=binding.decision_population_sha256,
        batch_schedule_sha256=binding.batch_schedule_sha256,
        source_index_sha256=binding.source_index_sha256,
        runtime_profile_sha256=spec.source_runtime_profile_sha256,
        expected_decision_count=binding.expected_decision_count,
        expected_batch_count=binding.expected_batch_count,
        storage_cap_bytes=binding.storage_cap_bytes)


def _imported_cache_storage(
        spec: V2TensorCacheImportSpecV1,
        receipt_raw: bytes) -> dict[str, Any]:
    return {
        "kind": "immutable-external-cache-v1",
        "import_receipt_sha256": _sha256(receipt_raw),
        "source_cache_root": str(spec.source_cache_root),
        "source_consumption_tombstone_sha256": (
            spec.source_consumption_tombstone_sha256),
    }


def run_training_tensor_cache(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Build and atomically publish every exact non-test training cache."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    try:
        index_manifest, inputs = reopen_training_input_index(
            root / "training-input-index" / "result", freeze=freeze,
            admission=admission)
    except ValueError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache input index refused") from exc
    input_index_sha256 = index_manifest["index_sha256"]
    primary_rows = [row for row in inputs.realizations
                    if row.cohort_id == PRIMARY_COHORT_ID]
    control_rows = [row for row in inputs.realizations
                    if row.cohort_id == CONTROL_COHORT_ID]
    if len(primary_rows) != 1 or len(control_rows) != 1 \
            or primary_rows[0].rows != control_rows[0].rows \
            or primary_rows[0].batches != control_rows[0].batches:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache primary/control actor schedule drift")
    parent = root / STAGE_DIRECTORY
    if parent.is_symlink():
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / RESULT_DIRECTORY
    partial = parent / f"{RESULT_DIRECTORY}.partial"
    if final.exists() or final.is_symlink():
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache stage slot is occupied")
    if partial.is_symlink() \
            or partial.exists() and not partial.is_dir():
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache partial stage drift")
    resumed_from_partial = partial.exists()
    if not resumed_from_partial:
        partial.mkdir(mode=0o700)
        started = time.monotonic_ns()
        start_raw = canonical_json_bytes(_start_payload(
            freeze, admission, input_index_sha256=input_index_sha256,
            started_monotonic_nanoseconds=started))
        publish_exclusive_bytes(partial / START_FILENAME, start_raw)
    else:
        if (partial / "deadline-refusal.json").exists() \
                or (partial / RESOURCE_REFUSAL_FILENAME).exists():
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache refused partial cannot resume")
        start, start_raw = _reopen_stage_start(
            partial / START_FILENAME, freeze, admission,
            input_index_sha256=input_index_sha256)
        started = start["started_monotonic_nanoseconds"]
        if started >= time.monotonic_ns():
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache resumed clock drift")
    cpu_started = _process_tree_cpu_time_ns()
    deadline = stage_deadline(
        freeze, admission, stage="training", slot="tensor-cache",
        started_monotonic_nanoseconds=started)
    deadline_lock = threading.Lock()

    def deadline_check(phase: str, next_unit_index: int) -> None:
        with deadline_lock:
            try:
                deadline.check(
                    phase=phase, next_unit_index=next_unit_index,
                    observed_monotonic_nanoseconds=time.monotonic_ns())
            except BeliefV2DeadlineError as exc:
                if not (partial / "deadline-refusal.json").exists():
                    publish_deadline_refusal(partial, exc.refusal)
                raise

    total_batches = (sum(len(row.batches) for row in inputs.realizations)
                     + len(inputs.common_calibration.batches))
    cache_workers = parallel_cache_worker_count(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes)
    progress_lock = threading.Lock()
    progress_totals = {
        row.cohort_id: len(row.batches) for row in inputs.realizations}
    progress_totals[CALIBRATION_CACHE_ID] = len(
        inputs.common_calibration.batches)
    progress_done = {key: 0 for key in progress_totals}
    if progress is not None:
        progress(0, total_batches, "cache-non-test-batches")

    def cache_progress(cache_id: str):
        def update(done: int, total: int, _label: str) -> None:
            if cache_id not in progress_totals \
                    or total != progress_totals[cache_id]:
                raise BeliefV2TensorCacheControllerError(
                    "V2 tensor cache progress population drift")
            with progress_lock:
                if done < progress_done[cache_id]:
                    raise BeliefV2TensorCacheControllerError(
                        "V2 tensor cache progress order drift")
                progress_done[cache_id] = done
                if progress is not None:
                    progress(sum(progress_done.values()), total_batches,
                             "cache-non-test-batches")
        return update

    try:
        import_spec = load_tensor_cache_import_spec(freeze)
    except BeliefV2CacheImportError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache import source refused") from exc
    cache_base = partial
    cache_storage = _local_cache_storage()
    import_receipt_raw = b""
    if import_spec is not None:
        import_receipt_raw = canonical_json_bytes(_cache_import_receipt(
            import_spec, input_index_sha256=input_index_sha256))
        import_path = partial / IMPORT_RECEIPT_FILENAME
        if import_path.exists():
            if stable_read_bytes(import_path) != import_receipt_raw:
                raise BeliefV2TensorCacheControllerError(
                    "V2 tensor cache import receipt drift")
        else:
            publish_exclusive_bytes(import_path, import_receipt_raw)
        cache_base = import_spec.source_cache_root
        cache_storage = _imported_cache_storage(
            import_spec, import_receipt_raw)

    loader = None if import_spec is not None else V2ArtifactRoundLoader(
        root, freeze=freeze, admission=admission, index=inputs.index)
    entries: list[dict[str, Any]] = []
    primary_binding = _imported_binding(_realization_binding(
        freeze, input_index_sha256, primary_rows[0]), import_spec)
    calibration_binding = _imported_binding(_calibration_binding(
        freeze, input_index_sha256, inputs.common_calibration), import_spec)
    direct_specs = primary_cache_first_build_order(tuple(
        (row.cohort_id, cache_base / _cache_directory_name(row.cohort_id),
         row, "train", _imported_binding(_realization_binding(
             freeze, input_index_sha256, row), import_spec))
        for row in inputs.realizations
        if row.cohort_id != CONTROL_COHORT_ID) + ((
            CALIBRATION_CACHE_ID,
            cache_base / _cache_directory_name(CALIBRATION_CACHE_ID),
            inputs.common_calibration, "calibration", calibration_binding),),
        PRIMARY_COHORT_ID)
    build_concurrency, workers_per_build = parallel_cache_build_topology(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes,
        len(direct_specs))

    def build_direct(spec):
        cache_id, cache_directory, schedule, mode, binding = spec
        receipt = _completed_cache_receipt(
            cache_directory, binding=binding)
        if import_spec is not None and (
                receipt is None or receipt["manifest_sha256"]
                != import_spec.child_manifest_sha256(
                    cache_directory.name)):
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache imported child manifest drift")
        overlay_receipt = None
        if receipt is None:
            if cache_id == PRIMARY_COHORT_ID and workers_per_build > 1:
                receipt, overlay_receipt = (
                    build_parallel_tensor_cache_with_control_overlay(
                        cache_directory,
                        control_overlay_directory=(
                            partial / CONTROL_OVERLAY_DIRECTORY),
                        control_overlay_id=control_rows[0].sha256(),
                        expected_control_changed_cell_count=(
                            inputs.index.control_changed_cell_count),
                        root=root, freeze=freeze, admission=admission,
                        index=inputs.index, schedule=schedule,
                        binding=binding, worker_count=workers_per_build,
                        deadline_check=deadline_check,
                        progress=cache_progress(cache_id),
                        control_overlay_progress=cache_progress(
                            CONTROL_COHORT_ID)))
            elif workers_per_build > 1:
                receipt = build_parallel_tensor_cache(
                    cache_directory, root=root, freeze=freeze,
                    admission=admission, index=inputs.index,
                    schedule=schedule, mode=mode, binding=binding,
                    worker_count=workers_per_build,
                    deadline_check=deadline_check,
                    progress=cache_progress(cache_id))
            elif mode == "train":
                receipt = build_tensor_cache(
                    cache_directory,
                    batches=lambda row=schedule: (
                        iter_streaming_training_batches(
                            inputs.index, row, load_round=loader)),
                    binding=binding, deadline_check=deadline_check,
                    progress=cache_progress(cache_id))
            else:
                receipt = build_tensor_cache(
                    cache_directory,
                    batches=lambda: iter_streaming_calibration_batches(
                        inputs.index, inputs.common_calibration,
                        load_round=loader),
                    binding=binding, deadline_check=deadline_check,
                    progress=cache_progress(cache_id))
        else:
            cache_progress(cache_id)(
                len(schedule.batches), len(schedule.batches), cache_id)
        return cache_id, receipt, overlay_receipt

    try:
        if import_spec is not None:
            # External children are already sealed.  Reopen them directly;
            # creating an executor here adds worker startup and obscures the
            # fact that this path performs no cache construction.
            built_rows = tuple(build_direct(spec) for spec in direct_specs)
        else:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=build_concurrency) as executor:
                built_rows = tuple(executor.map(build_direct, direct_specs))
        direct_receipts = {
            cache_id: receipt for cache_id, receipt, _ in built_rows}
        combined_overlay_rows = tuple(
            overlay for _, _, overlay in built_rows
            if overlay is not None)
        if len(combined_overlay_rows) > 1:
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache combined overlay population drift")
        combined_overlay_receipt = (
            combined_overlay_rows[0] if combined_overlay_rows else None)
        primary_receipt = direct_receipts[PRIMARY_COHORT_ID]
        primary_directory = cache_base / _cache_directory_name(
            PRIMARY_COHORT_ID)
        primary_batch_factory = cached_batch_factory(
            primary_directory,
            expected_manifest_sha256=primary_receipt["manifest_sha256"],
            binding=primary_binding)

        def control_batches():
            for natural in primary_batch_factory():
                control, _ = label_control_batch_from_natural(natural)
                yield control

        for realization in inputs.realizations:
            if realization.cohort_id == CONTROL_COHORT_ID:
                overlay_directory = cache_base / CONTROL_OVERLAY_DIRECTORY
                receipt = _completed_overlay_receipt(
                    overlay_directory,
                    actor_manifest_sha256=(
                        primary_receipt["manifest_sha256"]),
                    binding=primary_binding)
                if import_spec is not None and (
                        receipt is None or receipt["manifest_sha256"]
                        != import_spec.child_manifest_sha256(
                            CONTROL_OVERLAY_DIRECTORY)):
                    raise BeliefV2TensorCacheControllerError(
                        "V2 tensor cache imported overlay manifest drift")
                if combined_overlay_receipt is not None:
                    if receipt is None:
                        receipt = combined_overlay_receipt
                    elif receipt != combined_overlay_receipt:
                        raise BeliefV2TensorCacheControllerError(
                            "V2 tensor cache combined overlay receipt drift")
                elif receipt is None:
                    receipt = build_label_overlay(
                        overlay_directory,
                        batches=control_batches,
                        actor_directory=primary_directory,
                        actor_manifest_sha256=(
                            primary_receipt["manifest_sha256"]),
                        binding=primary_binding,
                        overlay_id=realization.sha256(),
                        deadline_check=deadline_check,
                        progress=cache_progress(CONTROL_COHORT_ID))
                else:
                    cache_progress(CONTROL_COHORT_ID)(
                        len(realization.batches), len(realization.batches),
                        CONTROL_COHORT_ID)
                entries.append(_entry(
                    cohort_id=realization.cohort_id,
                    realization_sha256=realization.sha256(),
                    kind="label-overlay",
                    directory=CONTROL_OVERLAY_DIRECTORY,
                    binding=primary_binding, receipt=receipt,
                    actor_cache_cohort_id=PRIMARY_COHORT_ID,
                    actor_manifest_sha256=(
                        primary_receipt["manifest_sha256"])))
            else:
                binding = _imported_binding(_realization_binding(
                    freeze, input_index_sha256, realization), import_spec)
                directory = _cache_directory_name(realization.cohort_id)
                receipt = direct_receipts[realization.cohort_id]
                entries.append(_entry(
                    cohort_id=realization.cohort_id,
                    realization_sha256=realization.sha256(),
                    kind="actor-and-label-cache", directory=directory,
                    binding=binding, receipt=receipt))
        calibration_receipt = direct_receipts[CALIBRATION_CACHE_ID]
        if any(progress_done[key] != progress_totals[key]
               for key in progress_totals):
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache progress completion drift")
        deadline_check("before-seal", total_batches)
    except (RuntimeError, ValueError) as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache construction refused") from exc

    calibration_entry = {
        "schedule_sha256": inputs.common_calibration.sha256(),
        "directory": _cache_directory_name(CALIBRATION_CACHE_ID),
        "binding": calibration_binding.to_dict(),
        **calibration_receipt,
    }
    finished = time.monotonic_ns()
    artifact_bytes = (len(start_raw)
                      + len(import_receipt_raw)
                      + sum(row["artifact_bytes"] for row in entries)
                      + calibration_receipt["artifact_bytes"])
    wall_nanoseconds = finished - started
    cpu_nanoseconds = (
        wall_nanoseconds * (cache_workers + 1)
        if resumed_from_partial
        else _process_tree_cpu_time_ns() - cpu_started)
    peak_host_memory_bytes = (
        max(host_peak_memory_bytes(),
            _usage_memory_bytes(resource.RUSAGE_SELF))
        if import_spec is not None else
        _aggregate_peak_host_memory_bytes(cache_workers))
    refusal = _resource_refusal_payload(
        freeze, admission, input_index_sha256=input_index_sha256,
        stage_start_sha256=_sha256(start_raw), started=started,
        finished=finished, cpu_nanoseconds=cpu_nanoseconds,
        artifact_bytes=artifact_bytes,
        peak_host_memory_bytes=peak_host_memory_bytes,
        cache_worker_count=cache_workers)
    if refusal is not None:
        publish_exclusive_bytes(
            partial / RESOURCE_REFUSAL_FILENAME,
            canonical_json_bytes(refusal))
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource cap exceeded and recorded")
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=cpu_nanoseconds,
        artifact_bytes=artifact_bytes,
        peak_host_memory_bytes=peak_host_memory_bytes,
        resumed_from_partial=resumed_from_partial,
        cache_worker_count=cache_workers,
        external_cache_reused=import_spec is not None)
    manifest = _manifest(
        freeze, admission, input_index_sha256=input_index_sha256,
        entries=entries, calibration=calibration_entry,
        control_dose=inputs.index.control_changed_cell_count,
        stage_start_sha256=_sha256(start_raw),
        resources=resources, cache_worker_count=cache_workers,
        cache_storage=cache_storage)
    publish_exclusive_bytes(
        partial / MANIFEST_FILENAME, canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_training_tensor_cache(
        final, freeze=freeze, admission=admission)
    if reopened[0] != manifest:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache post-publish drift")
    return manifest


def reopen_training_tensor_cache(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        verify_all_bytes: bool = True) \
        -> tuple[dict[str, Any], dict[str, Callable[[], Any]],
                 Callable[[], Any], int, str]:
    """Reopen all cache bytes and return trainer-compatible factories."""
    if type(verify_all_bytes) is not bool \
            or not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != RESULT_DIRECTORY:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache result directory drift")
    manifest_raw = stable_read_bytes(directory / MANIFEST_FILENAME)
    try:
        payload = json.loads(manifest_raw)
        index_manifest, inputs = reopen_training_input_index(
            Path(freeze.evidence_root) / "training-input-index" / "result",
            freeze=freeze, admission=admission)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache manifest/input reopen refused") from exc
    input_index_sha256 = index_manifest["index_sha256"]
    _, start_raw = _reopen_stage_start(
        directory / START_FILENAME, freeze, admission,
        input_index_sha256=input_index_sha256)
    try:
        import_spec = load_tensor_cache_import_spec(freeze)
    except BeliefV2CacheImportError as exc:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache import source refused") from exc
    cache_base = directory
    import_receipt_raw = b""
    cache_storage = _local_cache_storage()
    if import_spec is not None:
        import_receipt_raw = stable_read_bytes(
            directory / IMPORT_RECEIPT_FILENAME)
        if import_receipt_raw != canonical_json_bytes(
                _cache_import_receipt(
                    import_spec,
                    input_index_sha256=input_index_sha256)):
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache import receipt reconstruction drift")
        cache_base = import_spec.source_cache_root
        cache_storage = _imported_cache_storage(
            import_spec, import_receipt_raw)
    by_id = {row.cohort_id: row for row in inputs.realizations}
    if type(payload) is not dict \
            or type(payload.get("cohort_caches")) is not list \
            or len(payload["cohort_caches"]) != len(inputs.realizations):
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache manifest population drift")
    factories: dict[str, Callable[[], Any]] = {}
    receipts = []
    entries = []
    primary_row = by_id[PRIMARY_COHORT_ID]
    primary_binding = _imported_binding(_realization_binding(
        freeze, input_index_sha256, primary_row), import_spec)
    primary_entry = next((row for row in payload["cohort_caches"]
                          if type(row) is dict
                          and row.get("cohort_id") == PRIMARY_COHORT_ID), None)
    if primary_entry is None:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache primary entry absent")
    primary_directory = cache_base / _cache_directory_name(PRIMARY_COHORT_ID)
    for recorded in payload["cohort_caches"]:
        cohort_id = recorded.get("cohort_id") \
            if type(recorded) is dict else None
        realization = by_id.get(cohort_id)
        if realization is None:
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache cohort entry drift")
        if cohort_id == CONTROL_COHORT_ID:
            binding = primary_binding
            receipt = (
                _reopen_overlay_receipt(
                    cache_base / CONTROL_OVERLAY_DIRECTORY,
                    expected_manifest_sha256=recorded.get(
                        "manifest_sha256"),
                    actor_manifest_sha256=(
                        primary_entry.get("manifest_sha256")),
                    binding=binding)
                if verify_all_bytes else
                _reopen_overlay_manifest_receipt(
                    cache_base / CONTROL_OVERLAY_DIRECTORY,
                    expected_manifest_sha256=recorded.get(
                        "manifest_sha256"),
                    expected_artifact_bytes=recorded.get("artifact_bytes"),
                    actor_manifest_sha256=(
                        primary_entry.get("manifest_sha256")),
                    binding=binding))
            expected_entry = _entry(
                cohort_id=cohort_id,
                realization_sha256=realization.sha256(),
                kind="label-overlay", directory=CONTROL_OVERLAY_DIRECTORY,
                binding=binding, receipt=receipt,
                actor_cache_cohort_id=PRIMARY_COHORT_ID,
                actor_manifest_sha256=(
                    primary_entry.get("manifest_sha256")))
            factories[cohort_id] = cached_batch_factory(
                primary_directory,
                expected_manifest_sha256=(
                    primary_entry.get("manifest_sha256")),
                binding=primary_binding,
                label_overlay_directory=(
                    cache_base / CONTROL_OVERLAY_DIRECTORY),
                expected_label_overlay_sha256=(
                    recorded.get("manifest_sha256")))
        else:
            binding = _imported_binding(_realization_binding(
                freeze, input_index_sha256, realization), import_spec)
            cache_directory = cache_base / _cache_directory_name(cohort_id)
            receipt = (
                _reopen_cache_receipt(
                    cache_directory,
                    expected_manifest_sha256=recorded.get(
                        "manifest_sha256"), binding=binding)
                if verify_all_bytes else
                _reopen_cache_manifest_receipt(
                    cache_directory,
                    expected_manifest_sha256=recorded.get(
                        "manifest_sha256"),
                    expected_artifact_bytes=recorded.get("artifact_bytes"),
                    binding=binding))
            expected_entry = _entry(
                cohort_id=cohort_id,
                realization_sha256=realization.sha256(),
                kind="actor-and-label-cache",
                directory=_cache_directory_name(cohort_id),
                binding=binding, receipt=receipt)
            factories[cohort_id] = cached_batch_factory(
                cache_directory,
                expected_manifest_sha256=recorded.get("manifest_sha256"),
                binding=binding)
        if recorded != expected_entry:
            raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache cohort entry reconstruction drift")
        if import_spec is not None and receipt["manifest_sha256"] \
                != import_spec.child_manifest_sha256(
                    recorded["directory"]):
            raise BeliefV2TensorCacheControllerError(
                "V2 tensor cache imported child manifest drift")
        entries.append(expected_entry)
        receipts.append(receipt)
    if tuple(factories) != tuple(row.cohort_id
                                 for row in inputs.realizations):
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache cohort order drift")

    calibration_binding = _imported_binding(_calibration_binding(
        freeze, input_index_sha256, inputs.common_calibration), import_spec)
    calibration_recorded = payload.get("common_calibration_cache")
    if type(calibration_recorded) is not dict:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache calibration entry drift")
    calibration_directory = cache_base / _cache_directory_name(
        CALIBRATION_CACHE_ID)
    calibration_receipt = (
        _reopen_cache_receipt(
            calibration_directory,
            expected_manifest_sha256=calibration_recorded.get(
                "manifest_sha256"), binding=calibration_binding)
        if verify_all_bytes else
        _reopen_cache_manifest_receipt(
            calibration_directory,
            expected_manifest_sha256=calibration_recorded.get(
                "manifest_sha256"),
            expected_artifact_bytes=calibration_recorded.get(
                "artifact_bytes"), binding=calibration_binding))
    calibration_expected = {
        "schedule_sha256": inputs.common_calibration.sha256(),
        "directory": _cache_directory_name(CALIBRATION_CACHE_ID),
        "binding": calibration_binding.to_dict(),
        **calibration_receipt,
    }
    if calibration_recorded != calibration_expected:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache calibration reconstruction drift")
    if import_spec is not None and calibration_receipt["manifest_sha256"] \
            != import_spec.child_manifest_sha256(
                _cache_directory_name(CALIBRATION_CACHE_ID)):
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache imported calibration manifest drift")
    resources = payload.get("resources")
    resource_keys = {
        "schema", "boot_identity", "started_monotonic_nanoseconds",
        "finished_monotonic_nanoseconds", "wall_nanoseconds",
        "cpu_nanoseconds", "artifact_bytes", "peak_host_memory_bytes",
        "cpu_nanoseconds_is_conservative_upper_bound",
        "artifact_bytes_are_logical_referenced_bytes",
        "external_cache_reused",
        "cache_worker_count",
        "retry_count", "drop_count", "resumed_from_exact_partial"}
    artifact_bytes = (len(start_raw)
                      + len(import_receipt_raw)
                      + sum(row["artifact_bytes"] for row in receipts)
                      + calibration_receipt["artifact_bytes"])
    caps = freeze.resource_caps
    if type(resources) is not dict or set(resources) != resource_keys \
            or resources["schema"] != TENSOR_CACHE_RESOURCE_SCHEMA \
            or resources["boot_identity"] != freeze.runtime.boot_identity \
            or resources["wall_nanoseconds"] != (
                resources["finished_monotonic_nanoseconds"]
                - resources["started_monotonic_nanoseconds"]) \
            or resources["wall_nanoseconds"] <= 0 \
            or resources["cpu_nanoseconds"] < 0 \
            or resources["cpu_nanoseconds_is_conservative_upper_bound"] \
            is not resources["resumed_from_exact_partial"] \
            or resources["artifact_bytes"] != artifact_bytes \
            or resources["artifact_bytes_are_logical_referenced_bytes"] \
            is not True \
            or artifact_bytes > caps.training_bytes \
            or resources["peak_host_memory_bytes"] <= 0 \
            or resources["peak_host_memory_bytes"] \
            > caps.training_host_memory_bytes \
            or resources["cache_worker_count"] \
            != parallel_cache_worker_count(
                freeze.runtime, caps.training_host_memory_bytes) \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0 \
            or resources["external_cache_reused"] \
            is not (import_spec is not None) \
            or type(resources["resumed_from_exact_partial"]) is not bool:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache resource reconstruction drift")
    expected = _manifest(
        freeze, admission, input_index_sha256=input_index_sha256,
        entries=entries, calibration=calibration_expected,
        control_dose=inputs.index.control_changed_cell_count,
        stage_start_sha256=_sha256(start_raw),
        resources=resources,
        cache_worker_count=parallel_cache_worker_count(
            freeze.runtime, caps.training_host_memory_bytes),
        cache_storage=cache_storage)
    expected_files = (
        {MANIFEST_FILENAME, START_FILENAME, IMPORT_RECEIPT_FILENAME}
        if import_spec is not None else {
            MANIFEST_FILENAME, START_FILENAME, CONTROL_OVERLAY_DIRECTORY,
            _cache_directory_name(CALIBRATION_CACHE_ID),
            *(_cache_directory_name(row.cohort_id)
              for row in inputs.realizations
              if row.cohort_id != CONTROL_COHORT_ID),
        })
    if canonical_json_bytes(payload) != manifest_raw or payload != expected \
            or {path.name for path in directory.iterdir()} != expected_files:
        raise BeliefV2TensorCacheControllerError(
            "V2 tensor cache stage reconstruction drift")
    calibration_factory = cached_batch_factory(
        calibration_directory,
        expected_manifest_sha256=calibration_receipt["manifest_sha256"],
        binding=calibration_binding)
    return (payload, factories, calibration_factory,
            inputs.index.control_changed_cell_count,
            _sha256(manifest_raw))
