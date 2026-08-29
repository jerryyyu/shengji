"""Fast contract tests for the score-free V2 capacity runner."""

import pytest
import subprocess
import time

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_capacity import ARM_GRIDS
from shengji.rl.world_afterstate_v2_capacity_runner import (
    CapacityRunnerError, FixtureV2, HostTelemetryV2, PreflightResultV2,
    RawMeasurementV2, SyntheticMeasurementBackendV2, measure_capacity_v2,
    reopen_capacity_receipt_v2, reopen_capacity_receipt_v2_bytes,
    build_receipt_v2, _arm_from_raw, _PRODUCTION_PROVENANCE,
    RealMeasurementBackendV2, FullDAGCapacityDependencyBlocked,
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
    receipt = build_receipt_v2(
        arms, host=HostTelemetryV2(16, free_disk_bytes=10**9), preflight=preflight,
        _provenance=_PRODUCTION_PROVENANCE)
    assert reopen_capacity_receipt_v2(receipt.payload()).payload() == receipt.payload()
    assert reopen_capacity_receipt_v2_bytes(
        canonical_json_bytes(receipt.payload())).payload() == receipt.payload()
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


def test_production_refuses_unimplemented_full_dag_dependency():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    backend = _backend(fixture)
    with pytest.raises(CapacityRunnerError, match="production capacity refuses"):
        measure_capacity_v2(preflight=preflight, backend=backend,
                            host=HostTelemetryV2(16))
    assert FullDAGCapacityDependencyBlocked.dependency
