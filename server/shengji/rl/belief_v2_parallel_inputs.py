"""Deterministic process-parallel scan of V2 synthetic training inputs.

Workers reopen disjoint round chunks and return only compact schedule rows,
source identities, and negative-control dose.  The parent emits chunks in the
same lane/split/coordinate order as the serial scanner, owns progress and the
durable deadline refusal, and never opens a test target.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import time
from pathlib import Path
from typing import Any, Callable

from .belief_v2_controller import (
    _reopen_synthetic_training_round_examples,
    reopen_actor_capture_lane_manifest,
)
from .belief_v2_deadline import BeliefV2DeadlineError, V2StageDeadlineV1
from .belief_v2_execution_identity import configure_numerical_runtime
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_protocol import V2_CAPTURE_LANES, v2_lane_coordinates
from .belief_v2_schedule import calibration_row, training_row
from .belief_v2_streaming_inputs import _source
from .belief_v2_streaming_training import V2StreamingSourceV1
from .belief_v2_training import label_control_changed_cell_count


PARALLEL_INPUT_CHUNK_ROUNDS = 8

_WORKER_ROOT: Path | None = None
_WORKER_FREEZE: V2ExecutionFreezeV1 | None = None
_WORKER_ADMISSION: V2PipelineAdmissionV1 | None = None
_WORKER_DEADLINE: V2StageDeadlineV1 | None = None
_WORKER_LANES: dict[int, tuple[tuple[Any, ...], dict[str, Any]]] = {}


class BeliefV2ParallelInputError(ValueError):
    """A parallel input task, result, deadline, or order drifted."""


def _initialize_worker(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        deadline: V2StageDeadlineV1 | None) -> None:
    global _WORKER_ROOT
    global _WORKER_FREEZE
    global _WORKER_ADMISSION
    global _WORKER_DEADLINE
    global _WORKER_LANES
    configure_numerical_runtime()
    _WORKER_ROOT = root
    _WORKER_FREEZE = freeze
    _WORKER_ADMISSION = admission
    _WORKER_DEADLINE = deadline
    _WORKER_LANES = {}


def _worker_lane(lane: int) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if _WORKER_ROOT is None or _WORKER_FREEZE is None \
            or _WORKER_ADMISSION is None:
        raise BeliefV2ParallelInputError(
            "V2 parallel input worker was not initialized")
    cached = _WORKER_LANES.get(lane)
    if cached is None:
        coordinates = tuple(v2_lane_coordinates(lane))
        payload = reopen_actor_capture_lane_manifest(
            _WORKER_ROOT / "capture" / f"lane-{lane:02d}",
            freeze=_WORKER_FREEZE, admission=_WORKER_ADMISSION,
            lane=lane)
        if len(coordinates) != len(payload["rounds"]):
            raise BeliefV2ParallelInputError(
                "V2 parallel input lane population drift")
        cached = (coordinates, payload)
        _WORKER_LANES[lane] = cached
    return cached


def _scan_chunk(task):
    (task_index, lane, split, coordinate_indices,
     unit_index_start) = task
    if type(task_index) is not int or task_index < 0 \
            or type(lane) is not int or not 0 <= lane < V2_CAPTURE_LANES \
            or split not in {"train", "calibration"} \
            or type(coordinate_indices) is not tuple \
            or not coordinate_indices \
            or len(coordinate_indices) > PARALLEL_INPUT_CHUNK_ROUNDS \
            or any(type(index) is not int or index < 0
                   for index in coordinate_indices) \
            or type(unit_index_start) is not int or unit_index_start < 0:
        raise BeliefV2ParallelInputError(
            "V2 parallel input task drift")
    coordinates, payload = _worker_lane(lane)
    train_rows = []
    calibration_rows = []
    sources: list[V2StreamingSourceV1] = []
    control_dose = 0
    try:
        for offset, coordinate_index in enumerate(coordinate_indices):
            if coordinate_index >= len(coordinates):
                raise BeliefV2ParallelInputError(
                    "V2 parallel input coordinate drift")
            coordinate = coordinates[coordinate_index]
            if coordinate.split != split:
                raise BeliefV2ParallelInputError(
                    "V2 parallel input split drift")
            next_unit = unit_index_start + offset
            if _WORKER_DEADLINE is not None:
                _WORKER_DEADLINE.check(
                    phase="before-unit", next_unit_index=next_unit,
                    observed_monotonic_nanoseconds=time.monotonic_ns())
            examples = _reopen_synthetic_training_round_examples(
                _WORKER_ROOT / "capture" / f"lane-{lane:02d}",
                coordinate=coordinate,
                row=payload["rounds"][coordinate_index], split=split)
            sources.append(_source(
                examples, token=f"synthetic:{lane}:{coordinate_index}"))
            if split == "train":
                train_rows.extend(training_row(row) for row in examples)
                control_dose += label_control_changed_cell_count(examples)
            else:
                calibration_rows.extend(
                    calibration_row(row) for row in examples)
            if _WORKER_DEADLINE is not None:
                _WORKER_DEADLINE.check(
                    phase="after-unit", next_unit_index=next_unit + 1,
                    observed_monotonic_nanoseconds=time.monotonic_ns())
    except BeliefV2DeadlineError as exc:
        return task_index, None, exc.refusal
    return task_index, (
        tuple(train_rows), tuple(calibration_rows), tuple(sources),
        control_dose, len(coordinate_indices)), None


def _tasks() -> tuple[tuple[Any, ...], ...]:
    rows = []
    task_index = 0
    unit = 0
    for lane in range(V2_CAPTURE_LANES):
        coordinates = tuple(v2_lane_coordinates(lane))
        for split in ("train", "calibration"):
            indices = tuple(index for index, coordinate
                            in enumerate(coordinates)
                            if coordinate.split == split)
            if not indices:
                raise BeliefV2ParallelInputError(
                    "V2 parallel input lane split population is empty")
            for offset in range(0, len(indices),
                                PARALLEL_INPUT_CHUNK_ROUNDS):
                chunk = indices[offset:offset + PARALLEL_INPUT_CHUNK_ROUNDS]
                rows.append((task_index, lane, split, chunk, unit))
                task_index += 1
                unit += len(chunk)
    return tuple(rows)


def scan_parallel_synthetic_training_inputs(
        capture: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, worker_count: int,
        deadline: V2StageDeadlineV1 | None = None,
        deadline_check: Callable[[str, int], None] | None = None):
    """Return the serial scanner's exact synthetic rows in canonical order."""
    if not isinstance(capture, Path) or capture.name != "capture" \
            or capture.is_symlink() or not capture.is_dir() \
            or type(freeze) is not V2ExecutionFreezeV1 \
            or type(admission) is not V2PipelineAdmissionV1 \
            or type(worker_count) is not int or worker_count < 2 \
            or type(deadline) not in {V2StageDeadlineV1, type(None)} \
            or (deadline_check is not None and not callable(deadline_check)):
        raise BeliefV2ParallelInputError(
            "V2 parallel input scan inputs drift")
    tasks = _tasks()
    results: dict[int, tuple[Any, ...]] = {}
    next_submit = 0
    next_emit = 0
    train_rows = []
    calibration_rows = []
    sources = []
    control_dose = 0
    unit_count = 0
    context = multiprocessing.get_context("spawn")
    executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=worker_count, mp_context=context,
        initializer=_initialize_worker,
        initargs=(capture.parent, freeze, admission, deadline))
    futures: dict[concurrent.futures.Future, int] = {}

    def submit(task) -> None:
        if deadline_check is not None:
            deadline_check("before-unit", task[4])
        futures[executor.submit(_scan_chunk, task)] = task[0]

    try:
        while next_submit < min(worker_count * 2, len(tasks)):
            submit(tasks[next_submit])
            next_submit += 1
        while futures:
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                expected = futures.pop(future)
                actual, result, refusal = future.result()
                if actual != expected or actual in results:
                    raise BeliefV2ParallelInputError(
                        "V2 parallel input worker result drift")
                if refusal is not None:
                    if deadline_check is not None:
                        deadline_check(refusal.phase,
                                       refusal.next_unit_index)
                    raise BeliefV2ParallelInputError(
                        "V2 parallel input worker deadline drift")
                if type(result) is not tuple or len(result) != 5:
                    raise BeliefV2ParallelInputError(
                        "V2 parallel input worker payload drift")
                results[actual] = result
                if next_submit < len(tasks):
                    submit(tasks[next_submit])
                    next_submit += 1
            while next_emit in results:
                train, calibration, chunk_sources, dose, units = (
                    results.pop(next_emit))
                task = tasks[next_emit]
                if units != len(task[3]) or units <= 0 \
                        or task[4] != unit_count \
                        or type(dose) is not int or dose < 0:
                    raise BeliefV2ParallelInputError(
                        "V2 parallel input result population drift")
                train_rows.extend(train)
                calibration_rows.extend(calibration)
                sources.extend(chunk_sources)
                control_dose += dose
                for offset in range(units):
                    unit_count += 1
                    if deadline_check is not None:
                        deadline_check("after-unit", unit_count)
                next_emit += 1
        executor.shutdown(wait=True)
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    if results or next_emit != len(tasks) \
            or unit_count != sum(len(task[3]) for task in tasks) \
            or control_dose <= 0:
        raise BeliefV2ParallelInputError(
            "V2 parallel input parent accounting drift")
    return (tuple(train_rows), tuple(calibration_rows), tuple(sources),
            control_dose, unit_count)
