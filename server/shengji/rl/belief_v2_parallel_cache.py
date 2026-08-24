"""Deterministic process-parallel construction of non-test tensor caches.

Workers reopen independent scheduled batches and publish only their uniquely
named actor/label files.  A primary-cache worker may also emit its deterministic
negative-control labels from the same in-memory natural batch.  The parent owns
submission deadlines, global byte and decision accounting, canonical row order,
progress, and the sole manifest seals.  Worker completion order therefore
cannot change either logical cache.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
from pathlib import Path
from typing import Any, Callable

from .belief_v2_execution_identity import configure_numerical_runtime
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
)
from .belief_v2_streaming_inputs import V2ArtifactRoundLoader
from .belief_v2_streaming_training import (
    CONTROL_KIND,
    V2StreamingCalibrationBatchReaderV1,
    V2StreamingTrainingBatchReaderV1,
    V2StreamingTrainingIndexV1,
)
from .belief_v2_tensor_cache import (
    BeliefV2TensorCacheError,
    V2TensorCacheBindingV1,
    _build_label_overlay_batch,
    _build_tensor_cache_batch,
    _prepare_cache_directory,
    _seal_label_overlay,
    _seal_tensor_cache,
)
from .belief_v2_training import label_control_batch_from_natural


MAX_PARALLEL_CACHE_WORKERS = 16
MAX_WORKERS_PER_CACHE_BUILD = 8
MIN_WORKERS_PER_CONCURRENT_BUILD = 4
PARALLEL_CACHE_PARENT_RESERVE_BYTES = 4 * 1024 ** 3
# R5-1 measured 30.45 GB at 16 workers despite a frozen 24-GiB cap. A cache
# worker therefore cannot honestly be budgeted as one GiB. 2.25 GiB per
# worker plus the four-GiB parent reserve selects eight workers at that exact
# cap while still allowing reviewed larger-cap hosts to use more cores.
PARALLEL_CACHE_WORKER_BUDGET_BYTES = 2304 * 1024 ** 2


_WORKER_READER: Any = None
_WORKER_PARTIAL: Path | None = None
_WORKER_BINDING: V2TensorCacheBindingV1 | None = None
_WORKER_RESERVED_BYTES: Any = None
_WORKER_CONTROL_OVERLAY_PARTIAL: Path | None = None
_WORKER_CONTROL_OVERLAY_RESERVED_BYTES: Any = None


class BeliefV2ParallelCacheError(ValueError):
    """Parallel cache topology or canonical parent accounting drifted."""


def parallel_cache_worker_count(runtime, host_memory_cap_bytes: int) -> int:
    """Use only capacity allowed by both the host and the frozen cap."""
    cpu_count = getattr(runtime, "cpu_count", None)
    memory_bytes = getattr(runtime, "memory_bytes", None)
    if type(cpu_count) is not int or cpu_count <= 0 \
            or type(memory_bytes) is not int or memory_bytes <= 0 \
            or type(host_memory_cap_bytes) is not int \
            or host_memory_cap_bytes <= 0:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache runtime capacity drift")
    available = min(memory_bytes, host_memory_cap_bytes)
    memory_workers = max(
        1, (available - PARALLEL_CACHE_PARENT_RESERVE_BYTES)
        // PARALLEL_CACHE_WORKER_BUDGET_BYTES)
    return max(1, min(
        MAX_PARALLEL_CACHE_WORKERS, cpu_count, memory_workers))


def parallel_cache_build_topology(
        runtime, host_memory_cap_bytes: int,
        build_count: int) -> tuple[int, int]:
    """Spend safe surplus workers on disjoint caches, not contention."""
    if type(build_count) is not int or build_count <= 0:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache build population drift")
    worker_budget = parallel_cache_worker_count(
        runtime, host_memory_cap_bytes)
    concurrent_builds = min(
        build_count,
        max(1, worker_budget // MIN_WORKERS_PER_CONCURRENT_BUILD))
    workers_per_build = min(
        MAX_WORKERS_PER_CACHE_BUILD,
        max(1, worker_budget // concurrent_builds))
    if concurrent_builds * workers_per_build > worker_budget:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache build topology drift")
    return concurrent_builds, workers_per_build


def _initialize_worker(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        index: V2StreamingTrainingIndexV1,
        schedule: V2CohortRealizationV1 | V2CalibrationScheduleV1,
        mode: str, partial: Path, binding: V2TensorCacheBindingV1,
        reserved_bytes, control_overlay_partial,
        control_overlay_reserved_bytes) -> None:
    global _WORKER_READER
    global _WORKER_PARTIAL
    global _WORKER_BINDING
    global _WORKER_RESERVED_BYTES
    global _WORKER_CONTROL_OVERLAY_PARTIAL
    global _WORKER_CONTROL_OVERLAY_RESERVED_BYTES
    configure_numerical_runtime()
    loader = V2ArtifactRoundLoader(
        root, freeze=freeze, admission=admission, index=index)
    if mode == "train" and type(schedule) is V2CohortRealizationV1:
        if schedule.kind == CONTROL_KIND:
            raise BeliefV2ParallelCacheError(
                "V2 parallel cache refuses control overlay")
        reader = V2StreamingTrainingBatchReaderV1(
            index, schedule, load_round=loader)
    elif mode == "calibration" \
            and type(schedule) is V2CalibrationScheduleV1:
        reader = V2StreamingCalibrationBatchReaderV1(
            index, schedule, load_round=loader)
    else:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache worker mode drift")
    _WORKER_READER = reader
    _WORKER_PARTIAL = partial
    _WORKER_BINDING = binding
    _WORKER_RESERVED_BYTES = reserved_bytes
    _WORKER_CONTROL_OVERLAY_PARTIAL = control_overlay_partial
    _WORKER_CONTROL_OVERLAY_RESERVED_BYTES = (
        control_overlay_reserved_bytes)


def _reserve_worker_bytes(byte_count: int) -> None:
    if type(byte_count) is not int or byte_count <= 0 \
            or _WORKER_RESERVED_BYTES is None \
            or _WORKER_BINDING is None:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache byte reservation drift")
    with _WORKER_RESERVED_BYTES.get_lock():
        next_value = _WORKER_RESERVED_BYTES.value + byte_count
        if next_value > _WORKER_BINDING.storage_cap_bytes:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache storage cap exceeded")
        _WORKER_RESERVED_BYTES.value = next_value


def _reserve_control_overlay_worker_bytes(byte_count: int) -> None:
    if type(byte_count) is not int or byte_count <= 0 \
            or _WORKER_CONTROL_OVERLAY_RESERVED_BYTES is None \
            or _WORKER_BINDING is None:
        raise BeliefV2ParallelCacheError(
            "V2 parallel control-overlay byte reservation drift")
    with _WORKER_CONTROL_OVERLAY_RESERVED_BYTES.get_lock():
        next_value = (
            _WORKER_CONTROL_OVERLAY_RESERVED_BYTES.value + byte_count)
        if next_value > _WORKER_BINDING.storage_cap_bytes:
            raise BeliefV2TensorCacheError(
                "V2 tensor label overlay storage cap exceeded")
        _WORKER_CONTROL_OVERLAY_RESERVED_BYTES.value = next_value


def _build_worker_batch(batch_index: int) \
        -> tuple[int, dict[str, Any], int,
                 dict[str, Any] | None, int, int]:
    if _WORKER_READER is None or _WORKER_PARTIAL is None \
            or _WORKER_BINDING is None:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache worker was not initialized")
    value = _WORKER_READER.batch(batch_index)
    if isinstance(value, tuple):
        batch, dose = value
        if type(dose) is not int or dose != 0:
            raise BeliefV2ParallelCacheError(
                "V2 parallel cache natural batch dose drift")
    else:
        batch = value
    row, artifact_bytes = _build_tensor_cache_batch(
        _WORKER_PARTIAL, index=batch_index, batch=batch,
        binding=_WORKER_BINDING, reserve_bytes=_reserve_worker_bytes)
    overlay_row = None
    overlay_bytes = 0
    changed_cells = 0
    if _WORKER_CONTROL_OVERLAY_PARTIAL is not None:
        control, changed_cells = label_control_batch_from_natural(batch)
        overlay_row, overlay_bytes = _build_label_overlay_batch(
            _WORKER_CONTROL_OVERLAY_PARTIAL, index=batch_index,
            batch=control, binding=_WORKER_BINDING,
            reserve_bytes=_reserve_control_overlay_worker_bytes)
    elif _WORKER_CONTROL_OVERLAY_RESERVED_BYTES is not None:
        raise BeliefV2ParallelCacheError(
            "V2 parallel control-overlay worker state drift")
    return (batch_index, row, artifact_bytes,
            overlay_row, overlay_bytes, changed_cells)


def _build_parallel_tensor_cache(
        directory: Path, *, root: Path,
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        index: V2StreamingTrainingIndexV1,
        schedule: V2CohortRealizationV1 | V2CalibrationScheduleV1,
        mode: str, binding: V2TensorCacheBindingV1,
        worker_count: int,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        control_overlay_directory: Path | None = None,
        control_overlay_id: str | None = None,
        expected_control_changed_cell_count: int | None = None,
        control_overlay_progress: Callable[[int, int, str], None]
        | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build one cache with bounded spawn workers and one canonical parent."""
    if not isinstance(directory, Path) or not isinstance(root, Path) \
            or type(freeze) is not V2ExecutionFreezeV1 \
            or type(admission) is not V2PipelineAdmissionV1 \
            or type(index) is not V2StreamingTrainingIndexV1 \
            or mode not in {"train", "calibration"} \
            or type(worker_count) is not int or worker_count < 2 \
            or worker_count > parallel_cache_worker_count(
                freeze.runtime,
                freeze.resource_caps.training_host_memory_bytes) \
            or (deadline_check is not None
                and not callable(deadline_check)) \
            or (progress is not None and not callable(progress)) \
            or (control_overlay_progress is not None
                and not callable(control_overlay_progress)):
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache build inputs drift")
    overlay_requested = control_overlay_directory is not None
    if overlay_requested != (control_overlay_id is not None) \
            or overlay_requested \
            != (expected_control_changed_cell_count is not None) \
            or overlay_requested and (
                mode != "train"
                or not isinstance(control_overlay_directory, Path)
                or control_overlay_directory == directory
                or type(control_overlay_id) is not str
                or len(control_overlay_id) != 64
                or any(char not in "0123456789abcdef"
                       for char in control_overlay_id)
                or type(expected_control_changed_cell_count) is not int
                or expected_control_changed_cell_count <= 0):
        raise BeliefV2ParallelCacheError(
            "V2 parallel control-overlay inputs drift")
    if mode == "train":
        if type(schedule) is not V2CohortRealizationV1 \
                or schedule.kind == CONTROL_KIND:
            raise BeliefV2ParallelCacheError(
                "V2 parallel cache train schedule drift")
    elif type(schedule) is not V2CalibrationScheduleV1:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache calibration schedule drift")
    batch_count = len(schedule.batches)
    if batch_count != binding.expected_batch_count \
            or batch_count <= 0:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache batch population drift")
    partial = _prepare_cache_directory(directory)
    overlay_partial = (_prepare_cache_directory(control_overlay_directory)
                       if overlay_requested else None)
    if progress is not None:
        progress(0, batch_count, binding.cache_id)
    if control_overlay_progress is not None:
        control_overlay_progress(0, batch_count, control_overlay_id)

    context = multiprocessing.get_context("spawn")
    reserved_bytes = context.Value("Q", 0, lock=True)
    overlay_reserved_bytes = (
        context.Value("Q", 0, lock=True) if overlay_requested else None)
    rows_by_index: dict[
        int, tuple[dict[str, Any], int,
                   dict[str, Any] | None, int, int]] = {}
    rows: list[dict[str, Any]] = []
    overlay_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    overlay_total_bytes = 0
    control_changed_cell_count = 0
    next_submit = 0
    next_emit = 0
    futures: dict[concurrent.futures.Future, int] = {}
    executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=worker_count, mp_context=context,
        initializer=_initialize_worker,
        initargs=(root, freeze, admission, index, schedule, mode,
                  partial, binding, reserved_bytes, overlay_partial,
                  overlay_reserved_bytes))

    def submit_one(batch_index: int) -> None:
        if deadline_check is not None:
            deadline_check("before-unit", batch_index)
        future = executor.submit(_build_worker_batch, batch_index)
        futures[future] = batch_index

    try:
        while next_submit < min(worker_count, batch_count):
            submit_one(next_submit)
            next_submit += 1
        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                expected_index = futures.pop(future)
                (actual_index, row, artifact_bytes, overlay_row,
                 overlay_artifact_bytes, changed_cells) = future.result()
                if actual_index != expected_index \
                        or actual_index in rows_by_index:
                    raise BeliefV2ParallelCacheError(
                        "V2 parallel cache worker result drift")
                rows_by_index[actual_index] = (
                    row, artifact_bytes, overlay_row,
                    overlay_artifact_bytes, changed_cells)
                if next_submit < batch_count:
                    submit_one(next_submit)
                    next_submit += 1
            while next_emit in rows_by_index:
                (row, artifact_bytes, overlay_row,
                 overlay_artifact_bytes,
                 changed_cells) = rows_by_index.pop(next_emit)
                keys = tuple(row["decision_keys"])
                if not keys or any(key in seen for key in keys):
                    raise BeliefV2TensorCacheError(
                        "V2 tensor cache duplicate decision")
                seen.update(keys)
                total_bytes += artifact_bytes
                if total_bytes > binding.storage_cap_bytes:
                    raise BeliefV2TensorCacheError(
                        "V2 tensor cache storage cap exceeded")
                rows.append(row)
                if overlay_requested:
                    if type(overlay_row) is not dict \
                            or overlay_row.get("index") != next_emit \
                            or overlay_row.get("decision_keys") \
                            != row["decision_keys"] \
                            or type(overlay_artifact_bytes) is not int \
                            or overlay_artifact_bytes <= 0 \
                            or type(changed_cells) is not int \
                            or changed_cells < 0:
                        raise BeliefV2ParallelCacheError(
                            "V2 parallel control-overlay result drift")
                    overlay_rows.append(overlay_row)
                    overlay_total_bytes += overlay_artifact_bytes
                    control_changed_cell_count += changed_cells
                elif overlay_row is not None \
                        or overlay_artifact_bytes != 0 \
                        or changed_cells != 0:
                    raise BeliefV2ParallelCacheError(
                        "V2 parallel unexpected control-overlay result")
                next_emit += 1
                if deadline_check is not None:
                    deadline_check("after-unit", next_emit)
                if progress is not None:
                    progress(next_emit, batch_count, binding.cache_id)
                if control_overlay_progress is not None:
                    control_overlay_progress(
                        next_emit, batch_count, control_overlay_id)
        executor.shutdown(wait=True)
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    if rows_by_index or next_emit != batch_count \
            or reserved_bytes.value != total_bytes \
            or overlay_requested and (
                overlay_reserved_bytes.value != overlay_total_bytes
                or control_changed_cell_count
                != expected_control_changed_cell_count):
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache parent accounting drift")
    direct_receipt = _seal_tensor_cache(
        directory, partial=partial, rows=rows, total_bytes=total_bytes,
        binding=binding, deadline_check=deadline_check)
    overlay_receipt = (_seal_label_overlay(
        control_overlay_directory, partial=overlay_partial,
        rows=overlay_rows, total_bytes=overlay_total_bytes,
        actor_manifest_sha256=direct_receipt["manifest_sha256"],
        binding=binding, overlay_id=control_overlay_id,
        deadline_check=deadline_check) if overlay_requested else None)
    return direct_receipt, overlay_receipt


def build_parallel_tensor_cache(
        directory: Path, *, root: Path,
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        index: V2StreamingTrainingIndexV1,
        schedule: V2CohortRealizationV1 | V2CalibrationScheduleV1,
        mode: str, binding: V2TensorCacheBindingV1,
        worker_count: int,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> dict[str, Any]:
    """Build one direct cache without an alternate-label overlay."""
    direct, overlay = _build_parallel_tensor_cache(
        directory, root=root, freeze=freeze, admission=admission,
        index=index, schedule=schedule, mode=mode, binding=binding,
        worker_count=worker_count, deadline_check=deadline_check,
        progress=progress)
    if overlay is not None:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache returned an unexpected overlay")
    return direct


def build_parallel_tensor_cache_with_control_overlay(
        directory: Path, *, control_overlay_directory: Path,
        control_overlay_id: str,
        expected_control_changed_cell_count: int,
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        index: V2StreamingTrainingIndexV1,
        schedule: V2CohortRealizationV1,
        binding: V2TensorCacheBindingV1, worker_count: int,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        control_overlay_progress: Callable[[int, int, str], None]
        | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build natural actors and deterministic control labels in one pass."""
    direct, overlay = _build_parallel_tensor_cache(
        directory, root=root, freeze=freeze, admission=admission,
        index=index, schedule=schedule, mode="train", binding=binding,
        worker_count=worker_count, deadline_check=deadline_check,
        progress=progress,
        control_overlay_directory=control_overlay_directory,
        control_overlay_id=control_overlay_id,
        expected_control_changed_cell_count=(
            expected_control_changed_cell_count),
        control_overlay_progress=control_overlay_progress)
    if overlay is None:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache omitted the requested control overlay")
    return direct, overlay
