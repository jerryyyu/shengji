"""Failing-direction witnesses for the no-duplicate Value V2 capacity path."""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from scripts import world_afterstate_v2_capacity_recovery as cli
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl import world_afterstate_v2_capacity_recovery as recovery
from shengji.rl import world_afterstate_v2_capacity_runner as runner
from shengji.rl.world_afterstate_v2_capacity import (
    ARM_GRIDS, COMPOSED_STAGE_NAMES, MIN_CPU_UTILIZATION_PPM,
    CapacityArmV2, CapacityCensusAssessmentV2, CapacityFailureReceiptV2,
    ComposedProjectionV2, RejectedProjectionDiagnosticV2,
    WorldAfterstateV2CapacityError,
    composed_critical_path_seconds, composed_dag_edges_for_cohort_workers,
    projected_arm_wall_shares_ppm,
)


STAGE_WALLS = {
    "label-p0": 4479, "p0": 19, "optimizer-canary": 643,
    "label-fit": 859, "nested-curve-25": 1018,
    "nested-curve-50": 1099, "block-1-natural": 1318,
    "nested-curve-100": 208,
    "block-1-action-association-permutation": 3012,
    "block-1-label-permutation": 3012,
    "block-1-complete-world-shuffle": 3200,
    "block-2-natural": 1318,
    "block-2-complete-world-shuffle": 2259,
    "precision-select-inference": 48,
    "label-precision-select": 1226, "precision-select": 42,
    "label-audit": 304, "audit": 39, "reconstruction": 280,
}
STAGE_UNITS = {
    "label-p0": (16, 96), "p0": (96, 96),
    "optimizer-canary": (8000, 8000), "label-fit": (2, 88),
    "nested-curve-25": (5, 848), "nested-curve-50": (9, 1648),
    "block-1-natural": (17, 3200), "nested-curve-100": (1, 208),
    "block-1-action-association-permutation": (17, 3200),
    "block-1-label-permutation": (17, 3200),
    "block-1-complete-world-shuffle": (17, 3200),
    "block-2-natural": (17, 3200),
    "block-2-complete-world-shuffle": (17, 3200),
    "precision-select-inference": (7, 48),
    "label-precision-select": (7, 24), "precision-select": (7, 48),
    "label-audit": (5, 48), "audit": (5, 48),
    "reconstruction": (32, 256),
}
BASE_VARIANTS = {
    "state-successor": 1, "continuation-mechanics": 16,
    "member-concurrency": 2, "cohort-concurrency": 2,
    "inference-batch": 256, "reconstruction": 4,
}


def _base_failure(monkeypatch):
    walls = tuple((name, STAGE_WALLS[name]) for name in COMPOSED_STAGE_NAMES)
    exact_wall = tuple((name, 1_000_000_000)
                       for name in COMPOSED_STAGE_NAMES)
    exact_cpu = tuple((name, 14_000_000_000)
                      for name in COMPOSED_STAGE_NAMES)
    projection = ComposedProjectionV2(
        stage_walls_seconds=walls,
        composed_wall_seconds=composed_critical_path_seconds(
            STAGE_WALLS, composed_dag_edges_for_cohort_workers(2)),
        peak_memory_bytes=1_000_000_000,
        composed_artifact_bytes=100_000_000,
        free_disk_bytes_before=1_000_000_000_000,
        stage_unit_counts=tuple(
            (name, *STAGE_UNITS[name]) for name in COMPOSED_STAGE_NAMES),
        stage_cpu_seconds=tuple(
            (name, STAGE_WALLS[name] * 14)
            for name in COMPOSED_STAGE_NAMES),
        measured_stage_wall_nanoseconds=exact_wall,
        measured_stage_cpu_nanoseconds=exact_cpu,
        cohort_workers=2,
        dag_edges=composed_dag_edges_for_cohort_workers(2))
    diagnostic = RejectedProjectionDiagnosticV2.from_projection(projection)
    diagnostic.validate()
    assert diagnostic.composed_wall_seconds == 23_065
    shares = projected_arm_wall_shares_ppm(STAGE_WALLS)
    assessments = []
    for stage, variants in ARM_GRIDS.items():
        selected = BASE_VARIANTS[stage]
        position = variants.index(selected)
        immediate = variants[position + 1] if position + 1 < len(variants) else None
        assessments.append(CapacityCensusAssessmentV2(
            category=stage, selected_variant=selected,
            exact_wall_ns=1_000_000_000,
            exact_busy_core_ns=14_000_000_000,
            measured_unit_count=128,
            observed_utilization_ppm=875_000,
            required_utilization_ppm=MIN_CPU_UTILIZATION_PPM,
            projected_share_ppm=shares[stage],
            material=shares[stage] >= 50_000, cpu_bound=True,
            immediate_next_variant=immediate,
            next_memory_eligible=None if immediate is None else True,
            next_byte_identical=None if immediate is None else True,
            next_strictly_slower=False, violates_gate=False))
    source, input_sha, runtime = "1" * 64, "2" * 64, "3" * 64
    namespace = hashlib.sha256(canonical_json_bytes({
        "source_sha256": source, "input_sha256": input_sha,
        "runtime_sha256": runtime,
    })).hexdigest()
    message = "composed projection cap drift"
    detail = hashlib.sha256(canonical_json_bytes({
        "message": message,
        "assessments": [row.payload() for row in assessments],
        "projection_diagnostic": diagnostic.payload(),
    })).hexdigest()
    failure = CapacityFailureReceiptV2(
        stage="full-dag", reason="composed-projection-cap-drift",
        elapsed_seconds=6_680, source_sha256=source,
        input_sha256=input_sha, runtime_sha256=runtime,
        namespace_sha256=namespace, detail_sha256=detail,
        detail_message=message, assessments=tuple(assessments),
        projection_diagnostic=diagnostic)
    raw = canonical_json_bytes(failure.payload())
    monkeypatch.setattr(
        recovery, "BASE_FAILURE_EXTERNAL_SHA256",
        hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(
        recovery, "BASE_FAILURE_RECEIPT_SHA256",
        failure.payload()["failure_receipt_sha256"])
    monkeypatch.setattr(recovery, "BASE_FAILURE_SOURCE_SHA256", source)
    return failure, raw


def _preflight():
    fixtures = tuple(runner.FixtureV2(
        {"fixture": index}, deal_sha256=f"{index + 1:064x}")
                     for index in range(32))
    value = runner.PreflightResultV2(
        accepted_fixtures=fixtures, attempted=32, accepted=32,
        rejection_counts=(), candidate_distribution=((2, 32),),
        stratum_distribution=(("early/lead/attacker", 32),),
        elapsed_wall_nanoseconds=1_000_000_000)
    value.validate()
    return value


def _arm(width: int, *, wall_seconds: int, utilization_ppm: int = 900_000):
    wall_ns = wall_seconds * 1_000_000_000
    busy_ns = wall_ns * 16 * utilization_ppm // 1_000_000
    return CapacityArmV2(
        stage="cohort-concurrency", variant=width,
        wall_seconds=wall_seconds,
        busy_core_seconds=(busy_ns + 999_999_999) // 1_000_000_000,
        mean_cpu_utilization_ppm=utilization_ppm,
        p50_cpu_utilization_ppm=utilization_ppm,
        p95_cpu_utilization_ppm=utilization_ppm,
        scaling_efficiency_ppm=900_000, queue_depth=0,
        wall_share_ppm=100_000, peak_memory_bytes=2_000_000_000,
        swap_bytes=0, task_count=16, byte_identity_sha256="f" * 64,
        cpu_bound=True, wall_ns=wall_ns, busy_core_ns=busy_ns,
        measured_unit_count=128, peak_task_count=32)


def _receipt(monkeypatch, *, width4_utilization=900_000):
    _failure, raw = _base_failure(monkeypatch)
    preflight = dataclasses.replace(
        _preflight(), elapsed_wall_nanoseconds=1)
    host = runner.HostTelemetryV2(
        16, free_disk_bytes=900_000_000_000, task_count=16)
    receipt = recovery.build_capacity_recovery_receipt_v2(
        base_failure_raw=raw, source_sha256="a" * 64,
        runtime_sha256="b" * 64, preflight=preflight,
        sustained_arms=(
            _arm(2, wall_seconds=200),
            _arm(4, wall_seconds=100,
                 utilization_ppm=width4_utilization)),
        host=host, elapsed_nanoseconds=302_000_000_000,
        fresh_free_disk_bytes=899_000_000_000)
    return receipt, raw


def test_composite_reuses_every_retained_stage_and_unlocks_width_four(
        monkeypatch):
    receipt, raw = _receipt(monkeypatch)
    assert receipt._variant("cohort-concurrency") == 4
    assert receipt.composed.composed_wall_seconds == 17_041
    assert receipt.choose_tier().name == "D256"
    assert receipt.composed.stage_walls_seconds \
        == receipt.base_failure.projection_diagnostic.stage_walls_seconds
    serialized = canonical_json_bytes(receipt.payload())
    assert recovery.reopen_capacity_recovery_receipt_v2_bytes(
        serialized) == receipt
    assert recovery.reopen_capacity_evidence_v2_bytes(serialized) == receipt

    with pytest.raises(recovery.CapacityRecoveryError,
                       match="base bytes"):
        recovery.build_capacity_recovery_receipt_v2(
            base_failure_raw=raw[:-1] + b" ", source_sha256="a" * 64,
            runtime_sha256="b" * 64, preflight=_preflight(),
            sustained_arms=receipt.sustained_arms,
            host=runner.HostTelemetryV2(
                16, free_disk_bytes=900_000_000_000, task_count=16),
            elapsed_nanoseconds=302_000_000_000,
            fresh_free_disk_bytes=899_000_000_000)

    changed_walls = dict(receipt.composed.stage_walls_seconds)
    changed_walls["p0"] += 1
    changed_composed = dataclasses.replace(
        receipt.composed,
        stage_walls_seconds=tuple(changed_walls.items()),
        composed_wall_seconds=composed_critical_path_seconds(
            changed_walls, receipt.composed.dag_edges))
    with pytest.raises(recovery.CapacityRecoveryError,
                       match="inherited DAG"):
        dataclasses.replace(receipt, composed=changed_composed).validate()


def test_width_four_low_utilization_and_resource_rewrites_refuse(monkeypatch):
    with pytest.raises(recovery.CapacityRecoveryError,
                       match="all-core"):
        _receipt(monkeypatch, width4_utilization=800_000)

    receipt, _raw = _receipt(monkeypatch)
    with pytest.raises(recovery.CapacityRecoveryError,
                       match="wall accounting"):
        dataclasses.replace(
            receipt,
            command_wall_seconds=receipt.command_wall_seconds - 1,
        ).validate()


def test_width_two_remaining_fastest_cannot_relabel_old_cap_failure(
        monkeypatch):
    _failure, raw = _base_failure(monkeypatch)
    preflight = dataclasses.replace(
        _preflight(), elapsed_wall_nanoseconds=1)
    host = runner.HostTelemetryV2(
        16, free_disk_bytes=900_000_000_000, task_count=16)

    with pytest.raises(WorldAfterstateV2CapacityError,
                       match="composed projection cap drift"):
        recovery.build_capacity_recovery_receipt_v2(
            base_failure_raw=raw, source_sha256="a" * 64,
            runtime_sha256="b" * 64, preflight=preflight,
            sustained_arms=(
                _arm(2, wall_seconds=100),
                _arm(4, wall_seconds=200)),
            host=host, elapsed_nanoseconds=302_000_000_000,
            fresh_free_disk_bytes=899_000_000_000)


def test_composite_supplies_the_same_authenticated_downstream_resources(
        monkeypatch):
    from shengji.rl import world_afterstate_v2_freeze_inputs as freeze_inputs
    from shengji.rl import world_afterstate_v2_late_stage_adapters as late
    from shengji.rl import world_afterstate_v2_training_stage_inputs as training

    receipt, _raw = _receipt(monkeypatch)
    serialized = canonical_json_bytes(receipt.payload())
    reopened, tier, state_workers, continuation_workers = \
        freeze_inputs.capacity_context(serialized)
    assert reopened == receipt and tier == "D256"
    assert state_workers == 1 and continuation_workers == 16
    assert training._capacity_resources(receipt) == (
        2, 4, 4, 1, 256, 256)

    monkeypatch.setattr(late, "_capacity_receipt",
                        lambda *_args, **_kwargs: receipt)
    assert late._selected_capacity_variant(
        object(), object(), __import__("pathlib").Path("."),
        "reconstruction", (1, 4, 8, 16, 32)) == 4
    with pytest.raises(recovery.CapacityRecoveryError,
                       match="wall accounting"):
        dataclasses.replace(
            receipt, fresh_free_disk_bytes=receipt.fresh_free_disk_bytes + 1,
        ).validate()


def test_recovery_runner_measures_warm_2_4_then_measured_4_2(monkeypatch):
    _failure, raw = _base_failure(monkeypatch)
    preflight = dataclasses.replace(
        _preflight(), elapsed_wall_nanoseconds=1)
    host = runner.HostTelemetryV2(
        16, free_disk_bytes=900_000_000_000, task_count=16)
    calls = []

    class Backend:
        def __init__(self, **_kwargs):
            pass

        def measure(self, stage, variant, _fixture, operation):
            identity = operation()
            calls.append((stage, variant))
            wall_ns = 2_000 if variant == 2 else 1_000
            busy_ns = wall_ns * 16 * 900_000 // 1_000_000
            return runner.RawMeasurementV2(
                elapsed_ns=wall_ns, process_cpu_ns=busy_ns,
                peak_rss_bytes=2_000_000_000, task_count=16,
                sample_utilization_ppm=(900_000,),
                sample_memory_bytes=(2_000_000_000,),
                sample_task_counts=(16,), sample_swap_bytes=(0,),
                sample_free_disk_bytes=(899_000_000_000,),
                byte_identity_sha256=identity, cpu_bound=True)

    def cohort(_fixtures, variant, *, max_epochs, report_units):
        assert max_epochs == 8 and report_units is True
        return "f" * 64, 64

    monkeypatch.setattr(runner, "run_score_free_preflight",
                        lambda **_kwargs: preflight)
    monkeypatch.setattr(runner, "observe_host", lambda: host)
    monkeypatch.setattr(runner, "RealMeasurementBackendV2", Backend)
    monkeypatch.setattr(runner, "_run_cohort_concurrency_benchmark", cohort)
    receipt = recovery.run_capacity_recovery_v2(
        base_failure_raw=raw, source_sha256="a" * 64,
        runtime_sha256="b" * 64)
    assert calls == [
        ("cohort-recovery-warm", 2),
        ("cohort-recovery-warm", 4),
        ("cohort-recovery", 4),
        ("cohort-recovery", 2),
    ]
    assert receipt._variant("cohort-concurrency") == 4
    assert {arm.measured_unit_count for arm in receipt.sustained_arms} == {128}


def test_recovery_cli_success_and_deadline_paths_are_wired(
        tmp_path, monkeypatch):
    receipt, raw = _receipt(monkeypatch)
    monkeypatch.setattr(cli, "BASE_FAILURE_EXTERNAL_SHA256",
                        recovery.BASE_FAILURE_EXTERNAL_SHA256)
    monkeypatch.setattr(cli, "_source_sha256", lambda: receipt.source_sha256)
    monkeypatch.setattr(cli, "_runtime_sha256", lambda: receipt.runtime_sha256)
    base = tmp_path / "census-11-failure.json"
    base.write_bytes(raw)
    base.chmod(0o400)

    class Reader:
        def __init__(self, payload, ready=True):
            self.payload = payload
            self.ready = ready

        def poll(self, timeout):
            assert timeout == recovery.RECOVERY_COMMAND_WALL_SECONDS
            return self.ready

        def recv_bytes(self):
            return self.payload

        def close(self):
            pass

    class Process:
        pid = 999_999

        def __init__(self, exitcode=0, alive=False):
            self.exitcode = exitcode
            self.alive = alive

        def join(self, _timeout=None):
            pass

        def is_alive(self):
            return self.alive

        def kill(self):
            self.alive = False

    success_raw = canonical_json_bytes(receipt.payload())
    monkeypatch.setattr(cli, "_spawn",
                        lambda _raw, _progress:
                        (Process(), Reader(success_raw)))
    output = tmp_path / "capacity.json"
    failure = tmp_path / "capacity-failure.json"
    argv = ["--base-failure", str(base), "--out", str(output),
            "--failure-out", str(failure)]
    assert cli.main(argv) == 0
    assert recovery.reopen_capacity_recovery_receipt_v2_bytes(
        output.read_bytes()) == receipt
    assert not failure.exists()

    output_two = tmp_path / "capacity-two.json"
    failure_two = tmp_path / "capacity-two-failure.json"
    process = Process(exitcode=None, alive=True)
    monkeypatch.setattr(cli, "_spawn",
                        lambda _raw, _progress:
                        (process, Reader(b"", ready=False)))
    monkeypatch.setattr(cli, "_kill",
                        lambda value: setattr(value, "alive", False))
    argv = ["--base-failure", str(base), "--out", str(output_two),
            "--failure-out", str(failure_two)]
    assert cli.main(argv) == 2
    refused = recovery.reopen_capacity_recovery_failure_v2_bytes(
        failure_two.read_bytes())
    assert refused.reason == "capacity-recovery-deadline"
    assert not output_two.exists()
