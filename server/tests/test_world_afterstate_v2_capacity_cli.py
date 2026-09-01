from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from scripts import world_afterstate_v2_capacity as cli
from shengji.rl.world_afterstate_v2_capacity import (
    ARM_GRIDS, AUTHORITY, COMPOSED_STAGE_NAMES, CapacityCensusAssessmentV2,
    RejectedProjectionDiagnosticV2, composed_critical_path_seconds,
    reopen_capacity_failure_receipt_v2_bytes)
from shengji.rl.world_afterstate_v2_capacity_runner import CapacityRunnerError
from shengji.rl.world_afterstate_v2_freeze_builder import capacity_source_sha256


def _private_spawn_transport_probe(writer):
    os.setsid()
    writer.send_bytes(b"private-spawn-ok")
    writer.close()
    raise SystemExit(2)


def _pre_setsid_wedge_probe():
    time.sleep(30)


def test_capacity_source_manifest_covers_the_executed_value_closure():
    paths = {row["path"] for row in cli._source_rows()}
    required = {
        "server/scripts/world_afterstate_v2_capacity.py",
        "server/shengji/rl/world_afterstate_v2_artifacts.py",
        "server/shengji/rl/world_afterstate_v2_capacity_runner.py",
        "server/shengji/rl/world_afterstate_v2_capacity_supervisor.py",
        "server/shengji/rl/world_afterstate_v2_continuation.py",
        "server/shengji/rl/world_afterstate_v2_execution.py",
        "server/shengji/rl/world_afterstate_v2_inference.py",
        "server/shengji/rl/world_afterstate_v2_label_controller.py",
        "server/shengji/rl/world_afterstate_v2_population.py",
        "server/shengji/rl/world_afterstate_v2_protocol.py",
        "server/shengji/rl/world_afterstate_v2_source_driver.py",
        "server/shengji/rl/world_afterstate_v2_training.py",
        "server/shengji/rl/world_afterstate_v2_training_stage_adapters.py",
        "server/shengji/rl/world_afterstate_v2_training_stage_inputs.py",
    }
    assert required <= paths
    assert cli._source_sha256() == capacity_source_sha256(cli.REPO)


def test_cli_refusal_publishes_only_typed_failure_and_cannot_retry(
        tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_source_sha256", lambda: "f" * 64)
    expected_runtime = cli._runtime_sha256()
    output = tmp_path / "capacity.json"
    failure = tmp_path / "capacity-failure.json"
    work = tmp_path / "capacity-work"
    calls = []

    def refused(**kwargs):
        calls.append(kwargs)
        raise CapacityRunnerError(
            "full-DAG dependency failed at label-p0",
            stage="label-p0", reason_code="full-dag-dependency-failed")

    monkeypatch.setattr(cli, "run_capacity_v2", refused)
    argv = ["--out", str(output), "--failure-out", str(failure),
            "--work-root", str(work)]
    args = argparse.Namespace(progress=False)
    code, raw = cli._run_worker(
        args, output=output, failure_out=failure, work_root=work)
    assert code == 2

    class Worker:
        pid = 999999
        returncode = 2

        def communicate(self, timeout):
            assert timeout == 7200
            return raw, None

    monkeypatch.setattr(cli, "_spawn_worker", lambda *args, **kwargs: Worker())
    assert cli.main(argv) == 2
    assert len(calls) == 1 and calls[0]["output_root"] == work.resolve()
    assert not output.exists()
    receipt = reopen_capacity_failure_receipt_v2_bytes(failure.read_bytes())
    assert receipt.stage == "label-p0"
    assert receipt.reason == "full-dag-dependency-failed"
    assert receipt.runtime_sha256 == expected_runtime
    assert receipt.namespace_sha256 == hashlib.sha256(
        cli.canonical_json_bytes({
            "source_sha256": "f" * 64,
            "input_sha256": receipt.input_sha256,
            "runtime_sha256": expected_runtime,
        })).hexdigest()
    assert receipt.payload()["authority"] == AUTHORITY
    stat = failure.stat()
    assert stat.st_mode & 0o777 == 0o400 and stat.st_nlink == 1

    # The immutable failure consumes this exact attempt namespace. A second
    # invocation must refuse before re-entering the runner and cannot replace
    # either success or failure evidence.
    before = failure.read_bytes()
    assert cli.main(argv) == 2
    assert len(calls) == 1
    assert failure.read_bytes() == before and not output.exists()


def test_cli_failure_receipt_preserves_structured_census_assessments(tmp_path):
    rows = []
    for category, variants in ARM_GRIDS.items():
        selected = 64 if category == "continuation-mechanics" else variants[0]
        rows.append(CapacityCensusAssessmentV2(
            category=category, selected_variant=selected,
            exact_wall_ns=1_000_000_000, exact_busy_core_ns=12_800_000_000,
            measured_unit_count=128 if category == "continuation-mechanics" else 1,
            observed_utilization_ppm=800_000,
            required_utilization_ppm=850_000, projected_share_ppm=100_000,
            material=True, cpu_bound=True,
            immediate_next_variant=(None if selected == variants[-1]
                                    else variants[variants.index(selected) + 1]),
            next_memory_eligible=(None if selected == variants[-1] else True),
            next_byte_identical=(None if selected == variants[-1] else True),
            next_strictly_slower=False, violates_gate=True))
    exc = CapacityRunnerError(
        "capacity arm census refused low-utilization material arm",
        stage="measurement", reason_code="arm-census-low-utilization",
        assessments=tuple(rows))
    output = tmp_path / "capacity.json"
    failure = tmp_path / "failure.json"
    work = tmp_path / "work"
    receipt = cli._failure_receipt(
        exc, started_ns=time.perf_counter_ns(), output=output,
        failure_out=failure, work_root=work, source_sha256="f" * 64,
        runtime_sha256="e" * 64)
    reopened = reopen_capacity_failure_receipt_v2_bytes(
        cli.canonical_json_bytes(receipt.payload()))
    assert len(reopened.assessments) == len(ARM_GRIDS)
    assert any(row.violates_gate for row in reopened.assessments)
    assert reopened.payload()["authority"] == AUTHORITY


def test_cli_failure_receipt_preserves_rejected_projection(tmp_path):
    walls = tuple((name, 100_000 if name == "label-p0" else 1)
                  for name in COMPOSED_STAGE_NAMES)
    diagnostic = RejectedProjectionDiagnosticV2(
        stage_walls_seconds=walls,
        stage_cpu_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES),
        stage_unit_counts=tuple(
            (name, 1, 1) for name in COMPOSED_STAGE_NAMES),
        measured_stage_wall_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        measured_stage_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        composed_wall_seconds=composed_critical_path_seconds(dict(walls)),
        peak_memory_bytes=1, composed_artifact_bytes=1,
        free_disk_bytes_before=10**12)
    diagnostic.validate()
    exc = CapacityRunnerError(
        "composed projection cap drift", stage="full-dag",
        reason_code="composed-projection-cap-drift",
        projection_diagnostic=diagnostic)
    receipt = cli._failure_receipt(
        exc, started_ns=time.perf_counter_ns(),
        output=tmp_path / "capacity.json",
        failure_out=tmp_path / "failure.json", work_root=tmp_path / "work",
        source_sha256="f" * 64, runtime_sha256="e" * 64)
    reopened = reopen_capacity_failure_receipt_v2_bytes(
        cli.canonical_json_bytes(receipt.payload()))
    assert reopened.projection_diagnostic == diagnostic
    assert reopened.stage == "full-dag"
    assert reopened.reason == "composed-projection-cap-drift"


def test_cli_refuses_aliased_success_failure_and_work_paths(
        tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    called = False

    def unexpected(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("aliased namespace reached the runner")

    monkeypatch.setattr(cli, "run_capacity_v2", unexpected)
    assert cli.main(["--out", str(shared), "--failure-out", str(shared),
                     "--work-root", str(tmp_path / "work")]) == 2
    assert called is False
    assert not shared.exists()


def test_direct_worker_flag_is_not_a_public_execution_path(tmp_path,
                                                            monkeypatch):
    called = False

    def unexpected(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "run_capacity_v2", unexpected)
    with pytest.raises(SystemExit) as raised:
        cli.main([
            "--worker", "--out", str(tmp_path / "out"),
            "--failure-out", str(tmp_path / "failure"),
            "--work-root", str(tmp_path / "work")])
    assert raised.value.code == 2 and called is False


def test_private_spawn_transport_runs_in_its_own_process_group():
    context = cli.multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(
        target=_private_spawn_transport_probe, args=(writer,), daemon=False)
    process.start()
    writer.close()
    worker = cli._SpawnedCapacityWorker(process, reader)
    raw, _ = worker.communicate(timeout=10)
    assert raw == b"private-spawn-ok"
    assert worker.returncode == 2 and worker.pid != os.getpid()


def test_hard_kill_stops_spawn_child_before_setsid():
    context = cli.multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_pre_setsid_wedge_probe, daemon=False)
    process.start()
    writer.close()
    worker = cli._SpawnedCapacityWorker(process, reader)
    started = time.monotonic()
    cli._kill_process_group(worker)
    assert time.monotonic() - started < 5
    assert process.exitcode is not None and not process.is_alive()


def test_cli_refuses_symlinked_output_or_work_namespace(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(target, target_is_directory=True)
    called = False

    def unexpected(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "run_capacity_v2", unexpected)
    assert cli.main([
        "--out", str(linked_parent / "capacity.json"),
        "--failure-out", str(tmp_path / "failure.json"),
        "--work-root", str(tmp_path / "work")]) == 2
    assert called is False

    stale_work = tmp_path / "stale-work"
    stale_work.mkdir()
    assert cli.main([
        "--out", str(tmp_path / "capacity-2.json"),
        "--failure-out", str(tmp_path / "failure-2.json"),
        "--work-root", str(stale_work)]) == 2
    assert called is False


def test_supervisor_reopens_worker_success_before_publication(tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(cli, "_source_sha256", lambda: "f" * 64)
    monkeypatch.setattr(cli, "_runtime_sha256", lambda: "d" * 64)
    output = tmp_path / "capacity.json"
    failure = tmp_path / "failure.json"
    work = tmp_path / "work"
    events = []

    class Receipt:
        source_sha256 = "f" * 64
        runtime_sha256 = "d" * 64

        def payload(self):
            return {"schema": "test-capacity-success",
                    "source_sha256": self.source_sha256,
                    "runtime_sha256": self.runtime_sha256}

    class Worker:
        pid = 999998
        returncode = 0

        def communicate(self, timeout):
            assert timeout == 7200
            return (b'{"schema":"test-capacity-success",'
                    b'"source_sha256":"' + b'f' * 64 + b'",'
                    b'"runtime_sha256":"' + b'd' * 64 + b'"}\n'), None

    def reopen(value):
        assert value == {"schema": "test-capacity-success",
                         "source_sha256": "f" * 64,
                         "runtime_sha256": "d" * 64}
        events.append("reopen")
        return Receipt()

    def publish(path, receipt):
        events.append("publish")
        Path(path).write_bytes(cli.canonical_json_bytes(receipt.payload()))

    monkeypatch.setattr(cli, "_spawn_worker", lambda *args, **kwargs: Worker())
    monkeypatch.setattr(cli, "reopen_capacity_receipt_v2", reopen)
    monkeypatch.setattr(cli, "publish_capacity_receipt_v2", publish)
    args = argparse.Namespace(progress=False)
    assert cli._supervised_main(
        args, output=output, failure_out=failure, work_root=work) == 0
    assert events == ["reopen", "publish", "reopen"]
    assert output.exists() and not failure.exists()


def test_supervisor_refuses_success_from_a_different_source(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(cli, "_source_sha256", lambda: "f" * 64)
    monkeypatch.setattr(cli, "_runtime_sha256", lambda: "d" * 64)
    output = tmp_path / "capacity.json"
    failure = tmp_path / "failure.json"
    work = tmp_path / "work"

    class Receipt:
        source_sha256 = "e" * 64

    class Worker:
        pid = 999997
        returncode = 0

        def communicate(self, timeout):
            assert timeout == 7200
            return b'{}\n', None

    refused = []
    monkeypatch.setattr(cli, "_spawn_worker", lambda *args, **kwargs: Worker())
    monkeypatch.setattr(cli, "reopen_capacity_receipt_v2",
                        lambda _value: Receipt())
    monkeypatch.setattr(
        cli, "_publish_failure",
        lambda exc, **_kwargs: refused.append(str(exc)) or 2)
    args = argparse.Namespace(progress=False)
    assert cli._supervised_main(
        args, output=output, failure_out=failure, work_root=work) == 2
    assert refused == ["worker success receipt source/runtime binding drift"]
    assert not output.exists()


def test_supervisor_refuses_failure_from_a_different_runtime(tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(cli, "_source_sha256", lambda: "f" * 64)
    monkeypatch.setattr(cli, "_runtime_sha256", lambda: "d" * 64)
    output = tmp_path / "capacity.json"
    failure = tmp_path / "failure.json"
    work = tmp_path / "work"
    worker_failure = cli._failure_receipt(
        CapacityRunnerError("worker refused"),
        started_ns=time.perf_counter_ns(), output=output,
        failure_out=failure, work_root=work,
        source_sha256="f" * 64, runtime_sha256="e" * 64)

    class Worker:
        pid = 999996
        returncode = 2

        def communicate(self, timeout):
            assert timeout == 7200
            return cli.canonical_json_bytes(worker_failure.payload()), None

    refused = []
    monkeypatch.setattr(cli, "_spawn_worker", lambda *args, **kwargs: Worker())
    monkeypatch.setattr(
        cli, "_publish_failure",
        lambda exc, **_kwargs: refused.append(str(exc)) or 2)
    args = argparse.Namespace(progress=False)
    assert cli._supervised_main(
        args, output=output, failure_out=failure, work_root=work) == 2
    assert refused == ["worker failure receipt binding drift"]
    assert not output.exists() and not failure.exists()


def test_hard_kill_stops_process_group_descendant_before_publication(tmp_path):
    marker = tmp_path / "late-write"
    child = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',"
        f"\"import time,pathlib;time.sleep(.4);pathlib.Path({str(marker)!r}).write_text('late')\"]);"
        "time.sleep(30)")
    process = subprocess.Popen(
        [sys.executable, "-c", child], start_new_session=True)
    time.sleep(.1)
    cli._kill_process_group(process)
    assert process.poll() is not None
    time.sleep(.5)
    assert not marker.exists()


def test_timeout_kills_worker_group_before_failure_publication(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(cli, "_source_sha256", lambda: "f" * 64)
    events = []

    class Worker:
        pid = 999997

        def communicate(self, timeout):
            raise subprocess.TimeoutExpired(("worker",), timeout)

    monkeypatch.setattr(cli, "_spawn_worker", lambda *args, **kwargs: Worker())
    monkeypatch.setattr(
        cli, "_kill_process_group", lambda process: events.append("kill"))

    def publish(*args, **kwargs):
        events.append("publish")
        assert events == ["kill", "publish"]
        return 2

    monkeypatch.setattr(cli, "_publish_failure", publish)
    args = argparse.Namespace(progress=False)
    assert cli._supervised_main(
        args, output=tmp_path / "out", failure_out=tmp_path / "failure",
        work_root=tmp_path / "work") == 2
    assert events == ["kill", "publish"]
