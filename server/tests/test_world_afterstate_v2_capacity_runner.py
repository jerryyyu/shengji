"""Fast contract tests for the score-free V2 capacity runner."""

import pytest
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from shengji.rl.world_afterstate_v2_capacity import (
    ARM_GRIDS, COMPOSED_STAGE_NAMES, composed_critical_path_seconds)
from shengji.rl.world_afterstate_v2_capacity_runner import (
    CapacityRunnerError, FixtureV2, HostTelemetryV2, PreflightResultV2,
    RawMeasurementV2, SyntheticMeasurementBackendV2, measure_capacity_v2,
    build_receipt_v2, _arm_from_raw, _PRODUCTION_PROVENANCE,
    RealMeasurementBackendV2, FullDAGCapacityDependencyBlocked,
    RepresentativeDAGV2, _batched_tensor_identity, _composed_projection,
    _run_with_torch_threads, _scientific_stage_units, _tiers, _dag_attestation,
    _FULL_DAG_PROVENANCE,
)
from shengji.rl.world_afterstate_v2_capacity_supervisor import (
    FullDAGCapacityMeasurementV2,
    _RECOVERY_CAPABILITY_NAMES,
)


def _preflight() -> PreflightResultV2:
    fixture = FixtureV2({"score_free": True})
    return PreflightResultV2(
        accepted_fixtures=(fixture,) * 32, attempted=32, accepted=32,
        rejection_counts=(), candidate_distribution=((2, 32),),
        stratum_distribution=(("early/lead/attacker", 32),))


def _backend(fixture: FixtureV2, **changes):
    values = {}
    for stage, variants in ARM_GRIDS.items():
        for variant in variants:
            values[(stage, variant)] = RawMeasurementV2(
                elapsed_ns=(variant + 1) * 1_000_000_000,
                process_cpu_ns=(variant + 1) * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256=fixture.fixture_sha256)
    values.update(changes)
    return SyntheticMeasurementBackendV2(values)


def _full_dag_measurement(*, capabilities=None, member_workers=2,
                          torch_threads=4, inference_batch=128,
                          wall_seconds=1, cpu_seconds=1):
    capabilities = ({name: True for name in _RECOVERY_CAPABILITY_NAMES}
                    if capabilities is None else capabilities)
    walls = tuple((name, wall_seconds) for name in COMPOSED_STAGE_NAMES)
    units = tuple((name, 32) for name in COMPOSED_STAGE_NAMES)
    cpu = tuple((name, cpu_seconds * 1_000_000_000)
                for name in COMPOSED_STAGE_NAMES)
    return FullDAGCapacityMeasurementV2(
        tuple((name, value * 1_000_000_000) for name, value in walls), 1,
        COMPOSED_STAGE_NAMES, 0, True, capabilities, _FULL_DAG_PROVENANCE,
        units, cpu, member_workers, torch_threads, inference_batch)


def _selected_arms(fixture: FixtureV2):
    arms = []
    for stage, variants in ARM_GRIDS.items():
        for variant in variants:
            raw = RawMeasurementV2(
                elapsed_ns=(variant + 1) * 1_000_000_000,
                process_cpu_ns=(variant + 1) * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256=fixture.fixture_sha256)
            arms.append(_arm_from_raw(
                stage, variant, raw, fixture.fixture_sha256, raw.elapsed_ns))
    return tuple(arms)


def test_every_frozen_arm_runs_and_synthetic_cannot_publish():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    events = []
    result = measure_capacity_v2(
        preflight=preflight, backend=_backend(fixture),
        host=HostTelemetryV2(16, free_disk_bytes=10**9),
        progress=events.append, production=False)
    assert {(arm.stage, arm.variant) for arm in result.arms} == {
        (stage, variant) for stage, variants in ARM_GRIDS.items()
        for variant in variants}
    assert result.synthetic is True
    with pytest.raises(CapacityRunnerError, match="synthetic"):
        result.production_receipt()
    with pytest.raises(CapacityRunnerError, match="synthetic"):
        build_receipt_v2(result.arms, host=HostTelemetryV2(16), preflight=preflight)
    assert events[0]["completed_units"] == 1
    assert events[-1]["completed_units"] == len(ARM_GRIDS[events[-1]["stage"]])


def test_member_concurrency_trains_four_members_and_only_changes_executor_width(
        monkeypatch):
    import torch
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_model as model_module
    import shengji.rl.world_afterstate_v2_training as training_module

    model_count = []
    train_calls = []

    class FakeModel:
        def __init__(self, index):
            self.index = index

    def make_model(_seed):
        index = len(model_count) % 4
        model_count.append(index)
        value = FakeModel(index)
        return value

    class FakeOptimizer:
        pass

    widths = []

    class SpyExecutor(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            widths.append(kwargs.get("max_workers", args[0] if args else None))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runner, "_capacity_training_batch", lambda values: object())
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model", make_model)
    monkeypatch.setattr(training_module, "new_optimizer",
                        lambda model, config: FakeOptimizer())
    monkeypatch.setattr(training_module, "train_epoch",
                        lambda model, optimizer, batches, **kwargs: train_calls.append(
                            (model.index, batches, kwargs)) or object())
    monkeypatch.setattr(training_module, "model_state_sha256",
                        lambda model: f"{model.index + 1:064x}")
    monkeypatch.setattr(runner, "ThreadPoolExecutor", SpyExecutor)
    fixture = FixtureV2({"score_free": True})

    digests = []
    for width in (1, 2, 4):
        operation = runner._model_operation("member-concurrency", width,
                                           (fixture,))
        digests.append(runner._run_with_torch_threads(operation, 1))

    assert widths == [1, 2, 4]
    assert len(model_count) == 12
    assert len(train_calls) == 12
    assert all(call[1] == (object,) or len(call[1]) == 1 for call in train_calls)
    assert len(set(digests)) == 1


def test_selected_layout_is_frozen_before_supervisor_and_bound_to_receipt(
        monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor
    import shengji.rl.world_afterstate_v2_model as model_module

    preflight = _preflight()
    target = {"member-concurrency": 2,
              "torch-threads-per-member": 4, "inference-batch": 128}

    class Backend:
        synthetic = False

        def measure(self, stage, variant, fixture, operation):
            seconds = 1 if target.get(stage) == variant else 2
            return RawMeasurementV2(
                elapsed_ns=seconds * 1_000_000_000,
                process_cpu_ns=seconds * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256="a" * 64)

    seen = {}

    def run_supervisor(fixtures, **kwargs):
        seen.update(kwargs)
        return _full_dag_measurement(
            member_workers=kwargs["member_workers"],
            torch_threads=kwargs["torch_threads"],
            inference_batch=kwargs["inference_batch"])

    monkeypatch.setattr(runner, "run_score_free_preflight",
                        lambda **kwargs: preflight)
    monkeypatch.setattr(runner, "observe_host",
                        lambda: HostTelemetryV2(16, free_disk_bytes=10**12))
    monkeypatch.setattr(runner, "RealMeasurementBackendV2",
                        lambda **kwargs: Backend())
    monkeypatch.setattr(runner, "_model_operation",
                        lambda stage, variant, fixtures: lambda: "a" * 64)
    monkeypatch.setattr(runner, "_parallel_operation",
                        lambda stage, variant, fixtures: lambda: "a" * 64)
    monkeypatch.setattr(supervisor, "run_full_dag_supervisor", run_supervisor)
    monkeypatch.setattr(model_module, "count_trainable_parameters",
                        lambda model: 123)
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model",
                        lambda seed: object())

    result = runner.measure_capacity_v2(production=True)
    receipt = result.production_receipt()
    assert (seen["member_workers"], seen["torch_threads"],
            seen["inference_batch"]) == (2, 4, 128)
    assert (receipt.member_workers, receipt.torch_threads,
            receipt.inference_batch) == (2, 4, 128)
    assert receipt.command_wall_seconds == (
        sum(arm.wall_seconds for arm in result.arms)
        + len(COMPOSED_STAGE_NAMES))

    from dataclasses import replace
    bad = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES),
        progress_recovery=_full_dag_measurement().progress_recovery,
        provenance_token=_FULL_DAG_PROVENANCE,
        stage_source_unit_counts=tuple((name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=1, torch_threads=4, inference_batch=128)
    bad = replace(bad, attestation_sha256=_dag_attestation(bad))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="layout"):
        build_receipt_v2(
            result.arms, host=HostTelemetryV2(16, free_disk_bytes=10**12),
            preflight=preflight, representative_dag=bad,
            _provenance=_PRODUCTION_PROVENANCE)


def test_refuses_byte_mismatch_and_preflight_not_32():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    bad = RawMeasurementV2(
        elapsed_ns=1_000_000_000, process_cpu_ns=14_400_000_000,
        peak_rss_bytes=1_000_000, task_count=1,
        byte_identity_sha256="0" * 64)
    with pytest.raises(CapacityRunnerError, match="byte-identical"):
        values = {(stage, variant): value
                  for (stage, variant), value in _backend(fixture).measurements.items()}
        values[("state-successor", 1)] = bad
        measure_capacity_v2(
            preflight=preflight, backend=SyntheticMeasurementBackendV2(values),
            host=HostTelemetryV2(16), production=False)
    with pytest.raises(CapacityRunnerError, match="32"):
        PreflightResultV2(
            accepted_fixtures=(fixture,) * 31, attempted=31, accepted=31,
            rejection_counts=(), candidate_distribution=((2, 31),),
            stratum_distribution=(("early/lead/attacker", 31),)).validate()


def test_receipt_reopens_exactly_and_host_caps_refuse():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    arms = tuple(_arm_from_raw(
        stage, variant, RawMeasurementV2(
            elapsed_ns=1_000_000_000,
            process_cpu_ns=14_400_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(900_000,),
            byte_identity_sha256=fixture.fixture_sha256), fixture.fixture_sha256,
        1, synthetic=False)
                  for stage, variants in ARM_GRIDS.items() for variant in variants)
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="full-DAG"):
        build_receipt_v2(
            arms, host=HostTelemetryV2(16, free_disk_bytes=10**9),
            preflight=preflight, _provenance=_PRODUCTION_PROVENANCE)
    with pytest.raises(CapacityRunnerError, match="16 logical"):
        HostTelemetryV2(8).validate()
    with pytest.raises(CapacityRunnerError, match="zero swap"):
        HostTelemetryV2(16, swap_bytes=1).validate()


def test_real_monitor_witnesses_samples_and_child_cpu():
    backend = RealMeasurementBackendV2()
    before = backend.measure("state-successor", 1, FixtureV2({"x": 1}),
                             lambda: subprocess.run(
                                 ["sh", "-c", "python3 -c 'sum(i*i for i in range(1000000))'"],
                                 check=True))
    before.validate()
    assert before.process_cpu_ns > 0
    assert before.sample_memory_bytes
    assert before.sample_task_counts
    assert before.sample_free_disk_bytes


def test_real_deadline_interrupts_hung_operation():
    backend = RealMeasurementBackendV2(
        deadline_ns=time.perf_counter_ns() + 20_000_000)
    with pytest.raises(CapacityRunnerError, match="deadline"):
        backend.measure("state-successor", 1, FixtureV2({"x": 1}),
                        lambda: time.sleep(.2))


def test_torch_thread_arm_preserves_output_digest_and_restores_width():
    import torch
    before = torch.get_num_threads()
    assert _run_with_torch_threads(lambda: "a" * 64, 1) == "a" * 64
    assert torch.get_num_threads() == before


def test_inference_output_identity_is_batch_partition_invariant():
    import torch
    rows = torch.arange(24, dtype=torch.float32).reshape(6, 4)
    assert _batched_tensor_identity((rows[:2], rows[2:])) \
        == _batched_tensor_identity((rows[:1], rows[1:4], rows[4:]))


def test_composed_projection_counts_epochs_and_scales_tiers_by_stage():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    selected = {}
    for stage, variants in ARM_GRIDS.items():
        raw = RawMeasurementV2(
            elapsed_ns=1_000_000_000, process_cpu_ns=1_000_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(62_500,),
            byte_identity_sha256=fixture.fixture_sha256)
        selected[stage] = _arm_from_raw(
            stage, variants[0], raw, fixture.fixture_sha256, raw.elapsed_ns)
    dag = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES))
    composed = _composed_projection(selected, 32, 10**9, dag)
    units = {name: (measured, projected)
             for name, measured, projected in composed.stage_unit_counts}
    assert units["optimizer-canary"] == (8_000, 8_000)
    assert units["nested-curve-25"] == (20, 848)
    assert units["nested-curve-50"] == (24, 1648)
    assert units["nested-curve-100"] == (16, 208)
    assert units["p0"] == (32, 96)
    assert units["label-p0"] == (32, 96)
    assert units["label-fit"] == (32, 88)
    assert units["label-precision-select"] == (32, 24)
    assert units["label-audit"] == (32, 48)
    assert sum(units[name][1] for name in (
        "label-p0", "label-fit", "label-precision-select", "label-audit")) == 256
    assert units["block-1-natural"] == (32, 3_200)
    tiers = _tiers(composed)
    assert tiers[0].complete_dag_wall_seconds == composed_critical_path_seconds(
        dict(composed.stage_walls_seconds))
    assert tiers[1].complete_dag_wall_seconds \
        > tiers[0].complete_dag_wall_seconds * 2
    assert [tier.exact_source_supply for tier in tiers] == [True, False, False]


def test_projected_label_cpu_uses_measured_stage_cpu_not_wall_times_sixteen():
    fixture = _preflight().accepted_fixtures[0]
    selected = {stage: _arm_from_raw(
        stage, variants[0], RawMeasurementV2(
            elapsed_ns=1_000_000_000, process_cpu_ns=14_400_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(900_000,),
            byte_identity_sha256=fixture.fixture_sha256),
        fixture.fixture_sha256, 1) for stage, variants in ARM_GRIDS.items()}
    cpu_seconds = {name: 1 for name in COMPOSED_STAGE_NAMES}
    cpu_seconds.update({"label-p0": 2, "label-fit": 3,
                        "label-precision-select": 1, "label-audit": 4})
    dag = RepresentativeDAGV2(
        10, 10, 10, 10, 10, 10, 10, 1, admissible=True,
        stage_walls_seconds=tuple((name, 10) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple((name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, value * 1_000_000_000)
            for name, value in cpu_seconds.items()),
        member_workers=1, torch_threads=1, inference_batch=32,
        progress_recovery={name: True for name in _RECOVERY_CAPABILITY_NAMES})
    composed = _composed_projection(selected, 32, 10**12, dag)
    tiers = _tiers(composed)
    assert dict(composed.measured_stage_cpu_seconds)["label-p0"] == 2
    assert dict(composed.stage_cpu_seconds)["label-p0"] == 6
    assert tiers[0].label_cpu_seconds == 22
    assert tiers[0].label_cpu_seconds != tiers[0].label_wall_seconds * 16


def test_build_receipt_cannot_promote_false_measured_progress_probe():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    capabilities = {name: True for name in _RECOVERY_CAPABILITY_NAMES}
    capabilities["reports_stage_counts"] = False
    dag = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple((name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=1, torch_threads=1, inference_batch=32,
        progress_recovery=capabilities)
    dag = __import__("dataclasses").replace(
        dag, provenance_token=_FULL_DAG_PROVENANCE)
    dag = __import__("dataclasses").replace(dag,
        attestation_sha256=_dag_attestation(dag))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="progress"):
        build_receipt_v2(
            _selected_arms(fixture),
            host=HostTelemetryV2(16, free_disk_bytes=10**12),
            preflight=preflight, representative_dag=dag,
            _provenance=_PRODUCTION_PROVENANCE)


def test_all_tiers_account_for_each_label_bucket_once():
    from shengji.rl.world_afterstate_v2_protocol import TIER_SPECS
    for spec in TIER_SPECS:
        units = _scientific_stage_units(spec)
        labels = sum(units[name] for name in (
            "label-p0", "label-fit", "label-precision-select", "label-audit"))
        assert labels == spec.total
        assert units["label-p0"] == 96
        assert units["label-fit"] == spec.fit - 96 + spec.select // 2
        assert units["label-precision-select"] == spec.select // 2
        assert units["label-audit"] == spec.audit


def test_production_refuses_unimplemented_full_dag_dependency():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    backend = _backend(fixture)
    with pytest.raises(CapacityRunnerError, match="production capacity refuses"):
        measure_capacity_v2(preflight=preflight, backend=backend,
                            host=HostTelemetryV2(16))
    assert FullDAGCapacityDependencyBlocked.dependency
