"""Deterministic process-parallel construction of non-test tensor caches.

Workers reopen independent scheduled batches and publish only their uniquely
named actor/label files.  The parent owns submission deadlines, global byte and
decision accounting, canonical row order, progress, and the sole manifest
seal.  Worker completion order therefore cannot change the logical cache.
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
    _build_tensor_cache_batch,
    _prepare_cache_directory,
    _seal_tensor_cache,
)


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
        reserved_bytes) -> None:
    global _WORKER_READER
    global _WORKER_PARTIAL
    global _WORKER_BINDING
    global _WORKER_RESERVED_BYTES
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


def _build_worker_batch(batch_index: int) \
        -> tuple[int, dict[str, Any], int]:
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
    return batch_index, row, artifact_bytes


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
            or (progress is not None and not callable(progress)):
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache build inputs drift")
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
    if progress is not None:
        progress(0, batch_count, binding.cache_id)

    context = multiprocessing.get_context("spawn")
    reserved_bytes = context.Value("Q", 0, lock=True)
    rows_by_index: dict[int, tuple[dict[str, Any], int]] = {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    next_submit = 0
    next_emit = 0
    futures: dict[concurrent.futures.Future, int] = {}
    executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=worker_count, mp_context=context,
        initializer=_initialize_worker,
        initargs=(root, freeze, admission, index, schedule, mode,
                  partial, binding, reserved_bytes))

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
                actual_index, row, artifact_bytes = future.result()
                if actual_index != expected_index \
                        or actual_index in rows_by_index:
                    raise BeliefV2ParallelCacheError(
                        "V2 parallel cache worker result drift")
                rows_by_index[actual_index] = (row, artifact_bytes)
                if next_submit < batch_count:
                    submit_one(next_submit)
                    next_submit += 1
            while next_emit in rows_by_index:
                row, artifact_bytes = rows_by_index.pop(next_emit)
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
                next_emit += 1
                if deadline_check is not None:
                    deadline_check("after-unit", next_emit)
                if progress is not None:
                    progress(next_emit, batch_count, binding.cache_id)
        executor.shutdown(wait=True)
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    if rows_by_index or next_emit != batch_count \
            or reserved_bytes.value != total_bytes:
        raise BeliefV2ParallelCacheError(
            "V2 parallel cache parent accounting drift")
    return _seal_tensor_cache(
        directory, partial=partial, rows=rows, total_bytes=total_bytes,
        binding=binding, deadline_check=deadline_check)
