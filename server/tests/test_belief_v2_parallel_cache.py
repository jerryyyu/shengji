"""Determinism, deadline, and capacity teeth for the parallel cache parent."""

from __future__ import annotations

import concurrent.futures
from dataclasses import replace
from types import SimpleNamespace

import pytest

import shengji.rl.belief_v2_parallel_cache as PARALLEL
import shengji.rl.belief_v2_parallel_inputs as PARALLEL_INPUTS
from shengji.rl.belief_v2_parallel_cache import (
    BeliefV2ParallelCacheError,
    build_parallel_tensor_cache,
    build_parallel_tensor_cache_with_control_overlay,
    parallel_cache_build_topology,
    parallel_cache_worker_count,
    primary_cache_first_build_order,
)
from shengji.rl.belief_v2_parallel_inputs import (
    BeliefV2ParallelInputError,
    parallel_input_worker_count,
)
from shengji.rl.belief_v2_deadline import V2StageDeadlineV1
from shengji.rl.belief_v2_streaming_training import (
    V2StreamingTrainingBatchReaderV1,
)
from shengji.rl.belief_v2_schedule import _schedule_sha256
from shengji.rl.belief_v2_tensor_cache import (
    V2TensorCacheBindingV1,
    build_label_overlay,
    build_tensor_cache,
)
from shengji.rl.belief_v2_training import label_control_batch_from_natural
from tests.test_belief_v2_cohort_training import _streaming_fixture
from tests.test_belief_v2_controller import _admission, _cpu_only_freeze


class _ImmediateExecutor:
    """Exercise production parent wiring without hiding it behind a mock."""

    def __init__(self, *, max_workers, mp_context, initializer, initargs):
        del max_workers, mp_context
        initializer(*initargs)

    def submit(self, function, *args):
        future = concurrent.futures.Future()
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *, wait, cancel_futures=False):
        assert wait is True
        assert type(cancel_futures) is bool


def _fixture(tmp_path, monkeypatch):
    index, realizations, _, by_group = _streaming_fixture()
    realization = next(
        row for row in realizations if row.kind == "synthetic-primary")
    def load_round(source):
        return by_group[source.round_group_key]
    reader = V2StreamingTrainingBatchReaderV1(
        index, realization, load_round=load_round)
    batches = tuple(reader.batch(batch_index)[0]
                    for batch_index in range(reader.batch_count))
    root = tmp_path / "evidence"
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    binding = V2TensorCacheBindingV1(
        cache_id=realization.cohort_id, split="train",
        decision_population_sha256=realization.decision_population_sha256,
        batch_schedule_sha256=realization.batch_schedule_sha256,
        source_index_sha256="a" * 64,
        runtime_profile_sha256="b" * 64,
        expected_decision_count=sum(
            len(batch.decision_keys) for batch in batches),
        expected_batch_count=len(batches),
        storage_cap_bytes=1_000_000_000)
    monkeypatch.setattr(
        PARALLEL.concurrent.futures, "ProcessPoolExecutor",
        _ImmediateExecutor)
    monkeypatch.setattr(
        PARALLEL, "V2ArtifactRoundLoader",
        lambda *_args, **_kwargs: load_round)
    return index, realization, batches, freeze, admission, binding


def test_worker_count_uses_every_safe_core_and_refuses_bad_runtime():
    gib = 1024 ** 3
    assert parallel_cache_worker_count(SimpleNamespace(
        cpu_count=10, memory_bytes=16 * gib), 16 * gib) == 5
    assert parallel_cache_worker_count(SimpleNamespace(
        cpu_count=16, memory_bytes=32 * gib), 24 * gib) == 8
    assert parallel_cache_worker_count(SimpleNamespace(
        cpu_count=16, memory_bytes=64 * gib), 48 * gib) == 16
    assert parallel_cache_worker_count(SimpleNamespace(
        cpu_count=1, memory_bytes=2 * gib), 2 * gib) == 1
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="runtime capacity"):
        parallel_cache_worker_count(SimpleNamespace(
            cpu_count=True, memory_bytes=16 * gib), 16 * gib)
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="runtime capacity"):
        parallel_cache_worker_count(SimpleNamespace(
            cpu_count=16, memory_bytes=32 * gib), True)


def test_input_worker_count_respects_frozen_memory_cap_and_larger_reader():
    gib = 1024 ** 3
    runtime = SimpleNamespace(cpu_count=16, memory_bytes=32 * gib)
    assert parallel_input_worker_count(runtime, 24 * gib) == 8
    assert parallel_input_worker_count(runtime, 16 * gib) == 6
    assert parallel_input_worker_count(
        SimpleNamespace(cpu_count=4, memory_bytes=32 * gib), 24 * gib) == 4
    assert parallel_input_worker_count(runtime, 4 * gib) == 1
    with pytest.raises(BeliefV2ParallelInputError,
                       match="runtime capacity"):
        parallel_input_worker_count(runtime, True)


def test_build_topology_serializes_large_readers_and_uses_safe_workers():
    gib = 1024 ** 3
    runtime = SimpleNamespace(cpu_count=16, memory_bytes=32 * gib)
    assert parallel_cache_build_topology(runtime, 24 * gib, 4) == (1, 8)
    assert parallel_cache_build_topology(runtime, 24 * gib, 1) == (1, 8)
    assert parallel_cache_build_topology(SimpleNamespace(
        cpu_count=8, memory_bytes=32 * gib), 24 * gib, 4) == (1, 8)
    assert parallel_cache_build_topology(SimpleNamespace(
        cpu_count=4, memory_bytes=32 * gib), 24 * gib, 4) == (1, 4)
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="build population"):
        parallel_cache_build_topology(runtime, 24 * gib, 0)


def test_primary_cache_is_scheduled_first_without_changing_population():
    specs = (
        ("synthetic-primary", "primary"),
        ("human-mixture", "human"),
        ("synthetic-scale-50", "scale"),
        ("common-calibration", "calibration"),
    )
    ordered = primary_cache_first_build_order(
        specs, "synthetic-primary")
    assert ordered == (specs[0], specs[1], specs[2], specs[3])
    assert sorted(ordered) == sorted(specs)
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="order population"):
        primary_cache_first_build_order(
            specs + (specs[0],), "synthetic-primary")
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="order population"):
        primary_cache_first_build_order(specs, "absent")


def test_parallel_input_parent_reduces_worker_chunks_in_canonical_order(
        tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    capture = root / "capture"
    capture.mkdir(parents=True)
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    tasks = (
        (0, 0, "train", (2,), 0),
        (1, 0, "calibration", (3,), 1),
    )
    monkeypatch.setattr(PARALLEL_INPUTS, "_tasks", lambda: tasks)
    monkeypatch.setattr(
        PARALLEL_INPUTS.concurrent.futures, "ProcessPoolExecutor",
        _ImmediateExecutor)

    def scan(task):
        index = task[0]
        if index == 0:
            return index, (("train-row",), (), ("train-source",), 7, 1), None
        return index, ((), ("calibration-row",),
                       ("calibration-source",), 0, 1), None

    monkeypatch.setattr(PARALLEL_INPUTS, "_scan_chunk", scan)
    phases = []
    result = PARALLEL_INPUTS.scan_parallel_synthetic_training_inputs(
        capture, freeze=freeze, admission=admission, worker_count=2,
        deadline_check=lambda phase, unit: phases.append((phase, unit)))
    assert result == (
        ("train-row",), ("calibration-row",),
        ("train-source", "calibration-source"), 7, 2)
    assert phases == [
        ("before-unit", 0), ("before-unit", 1),
        ("after-unit", 1), ("after-unit", 2)]


def test_parallel_input_worker_expiry_reaches_parent_deadline_wiring(
        tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    capture = root / "capture"
    capture.mkdir(parents=True)
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    monkeypatch.setattr(
        PARALLEL_INPUTS, "_tasks",
        lambda: ((0, 0, "train", (2,), 0),))
    monkeypatch.setattr(
        PARALLEL_INPUTS.concurrent.futures, "ProcessPoolExecutor",
        _ImmediateExecutor)
    refusal = SimpleNamespace(phase="before-unit", next_unit_index=0)
    monkeypatch.setattr(
        PARALLEL_INPUTS, "_scan_chunk",
        lambda task: (task[0], None, refusal))
    phases = []

    def deadline(phase, unit):
        phases.append((phase, unit))
        if len(phases) == 2:
            raise BeliefV2ParallelInputError("deadline witness")

    with pytest.raises(BeliefV2ParallelInputError,
                       match="deadline witness"):
        PARALLEL_INPUTS.scan_parallel_synthetic_training_inputs(
            capture, freeze=freeze, admission=admission, worker_count=2,
            deadline_check=deadline)
    assert phases == [("before-unit", 0), ("before-unit", 0)]


def test_parallel_input_worker_checks_deadline_before_opening_round(
        tmp_path, monkeypatch):
    deadline = V2StageDeadlineV1(
        freeze_sha256="a" * 64, admission_sha256="b" * 64,
        stage="training", slot="input-index",
        started_monotonic_nanoseconds=1,
        wall_cap_nanoseconds=100,
        next_unit_wall_estimate_nanoseconds=20,
        safety_reserve_nanoseconds=10)
    monkeypatch.setattr(PARALLEL_INPUTS, "_WORKER_ROOT", tmp_path)
    monkeypatch.setattr(PARALLEL_INPUTS, "_WORKER_DEADLINE", deadline)
    monkeypatch.setattr(
        PARALLEL_INPUTS, "_worker_lane",
        lambda lane: ((SimpleNamespace(split="train"),),
                      {"rounds": (object(),)}))
    monkeypatch.setattr(
        PARALLEL_INPUTS, "_reopen_synthetic_training_round_examples",
        lambda *args, **kwargs: pytest.fail(
            "expired worker opened a round"))
    monkeypatch.setattr(PARALLEL_INPUTS.time, "monotonic_ns", lambda: 100)
    index, result, refusal = PARALLEL_INPUTS._scan_chunk(
        (0, 0, "train", (0,), 0))
    assert index == 0
    assert result is None
    assert refusal.phase == "before-unit"
    assert refusal.next_unit_index == 0


def test_parallel_parent_is_byte_identical_to_serial(tmp_path, monkeypatch):
    (index, realization, batches, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    serial = build_tensor_cache(
        tmp_path / "serial", batches=lambda: iter(batches), binding=binding)
    parallel = build_parallel_tensor_cache(
        tmp_path / "parallel", root=tmp_path / "evidence",
        freeze=freeze, admission=admission, index=index,
        schedule=realization, mode="train", binding=binding,
        worker_count=2)

    assert parallel == serial
    assert {path.name: path.read_bytes()
            for path in (tmp_path / "parallel").iterdir()} \
        == {path.name: path.read_bytes()
            for path in (tmp_path / "serial").iterdir()}


def test_parallel_primary_build_emits_byte_identical_control_overlay_in_pass(
        tmp_path, monkeypatch):
    (index, realization, batches, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    serial = build_tensor_cache(
        tmp_path / "serial", batches=lambda: iter(batches), binding=binding)
    controls_and_dose = tuple(
        label_control_batch_from_natural(batch) for batch in batches)
    serial_overlay = build_label_overlay(
        tmp_path / "serial-overlay",
        batches=lambda: (row for row, _ in controls_and_dose),
        actor_directory=tmp_path / "serial",
        actor_manifest_sha256=serial["manifest_sha256"],
        binding=binding, overlay_id="e" * 64)

    parallel, parallel_overlay = (
        build_parallel_tensor_cache_with_control_overlay(
            tmp_path / "parallel",
            control_overlay_directory=tmp_path / "parallel-overlay",
            control_overlay_id="e" * 64,
            expected_control_changed_cell_count=sum(
                dose for _, dose in controls_and_dose),
            root=tmp_path / "evidence", freeze=freeze,
            admission=admission, index=index, schedule=realization,
            binding=binding, worker_count=2))

    assert parallel == serial
    assert parallel_overlay == serial_overlay
    for expected, actual in (
            (tmp_path / "serial", tmp_path / "parallel"),
            (tmp_path / "serial-overlay",
             tmp_path / "parallel-overlay")):
        assert {path.name: path.read_bytes() for path in actual.iterdir()} \
            == {path.name: path.read_bytes()
                for path in expected.iterdir()}

    with pytest.raises(BeliefV2ParallelCacheError,
                       match="parent accounting"):
        build_parallel_tensor_cache_with_control_overlay(
            tmp_path / "bad-dose",
            control_overlay_directory=tmp_path / "bad-dose-overlay",
            control_overlay_id="e" * 64,
            expected_control_changed_cell_count=(
                sum(dose for _, dose in controls_and_dose) + 1),
            root=tmp_path / "evidence", freeze=freeze,
            admission=admission, index=index, schedule=realization,
            binding=binding, worker_count=2)


def test_deadline_refuses_seal_then_exact_partial_resumes(
        tmp_path, monkeypatch):
    (index, realization, _, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    phases = []

    def expire_before_seal(phase, unit):
        phases.append((phase, unit))
        if phase == "before-seal":
            raise BeliefV2ParallelCacheError("deadline witness")

    directory = tmp_path / "parallel"
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="deadline witness"):
        build_parallel_tensor_cache(
            directory, root=tmp_path / "evidence", freeze=freeze,
            admission=admission, index=index, schedule=realization,
            mode="train", binding=binding, worker_count=2,
            deadline_check=expire_before_seal)
    assert not directory.exists()
    assert directory.with_name("parallel.partial").is_dir()
    assert not (directory.with_name("parallel.partial")
                / "manifest.json").exists()
    assert phases[-1] == ("before-seal", binding.expected_batch_count)

    receipt = build_parallel_tensor_cache(
        directory, root=tmp_path / "evidence", freeze=freeze,
        admission=admission, index=index, schedule=realization,
        mode="train", binding=binding, worker_count=2)
    assert receipt["batch_count"] == binding.expected_batch_count
    assert directory.is_dir()


def test_combined_primary_and_control_partials_resume_together(
        tmp_path, monkeypatch):
    (index, realization, batches, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    changed = sum(label_control_batch_from_natural(batch)[1]
                  for batch in batches)
    phases = []

    def expire_before_seal(phase, unit):
        phases.append((phase, unit))
        if phase == "before-seal":
            raise BeliefV2ParallelCacheError("combined deadline witness")

    direct = tmp_path / "combined"
    overlay = tmp_path / "combined-overlay"
    with pytest.raises(BeliefV2ParallelCacheError,
                       match="combined deadline witness"):
        build_parallel_tensor_cache_with_control_overlay(
            direct, control_overlay_directory=overlay,
            control_overlay_id="e" * 64,
            expected_control_changed_cell_count=changed,
            root=tmp_path / "evidence", freeze=freeze,
            admission=admission, index=index, schedule=realization,
            binding=binding, worker_count=2,
            deadline_check=expire_before_seal)
    assert not direct.exists() and not overlay.exists()
    assert direct.with_name("combined.partial").is_dir()
    assert overlay.with_name("combined-overlay.partial").is_dir()
    assert phases[-1] == ("before-seal", binding.expected_batch_count)

    direct_receipt, overlay_receipt = (
        build_parallel_tensor_cache_with_control_overlay(
            direct, control_overlay_directory=overlay,
            control_overlay_id="e" * 64,
            expected_control_changed_cell_count=changed,
            root=tmp_path / "evidence", freeze=freeze,
            admission=admission, index=index, schedule=realization,
            binding=binding, worker_count=2))
    assert direct_receipt["batch_count"] == binding.expected_batch_count
    assert overlay_receipt["batch_count"] == binding.expected_batch_count
    assert direct.is_dir() and overlay.is_dir()


def test_parallel_cap_is_global_across_workers(tmp_path, monkeypatch):
    (index, realization, _, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    keys = realization.batches[0]
    assert len(keys) >= 2
    midpoint = len(keys) // 2
    two_batches = (keys[:midpoint], keys[midpoint:])
    realization = replace(
        realization, batches=two_batches,
        batch_schedule_sha256=_schedule_sha256(two_batches))
    binding = replace(
        binding, batch_schedule_sha256=realization.batch_schedule_sha256,
        expected_batch_count=2)
    load_round = PARALLEL.V2ArtifactRoundLoader(
        tmp_path / "evidence", freeze=freeze, admission=admission,
        index=index)
    reader = V2StreamingTrainingBatchReaderV1(
        index, realization, load_round=load_round)
    batches = tuple(reader.batch(batch_index)[0]
                    for batch_index in range(reader.batch_count))
    build_tensor_cache(
        tmp_path / "probe", batches=lambda: iter(batches), binding=binding)
    pair_bytes = tuple(
        (tmp_path / "probe" / f"batch-{index:05d}.actor.pt").stat().st_size
        + (tmp_path / "probe" / f"batch-{index:05d}.labels.pt").stat().st_size
        for index in range(len(batches)))
    aggregate_cap = sum(pair_bytes[:2]) - 1
    assert aggregate_cap >= max(pair_bytes[:2])
    tiny = replace(binding, storage_cap_bytes=aggregate_cap)
    with pytest.raises(ValueError, match="storage cap exceeded"):
        build_parallel_tensor_cache(
            tmp_path / "too-small", root=tmp_path / "evidence",
            freeze=freeze, admission=admission, index=index,
            schedule=realization, mode="train", binding=tiny,
            worker_count=2)
    assert not (tmp_path / "too-small").exists()
