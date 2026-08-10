from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import teacher_stage_c_training_controller as CTRL
import teacher_stage_c_training_supervisor as SUP


def _config(tmp_path: Path) -> SUP.Config:
    return SUP.Config(
        expected_git="a" * 40,
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="b" * 64,
        review_record=tmp_path / "review.md",
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="c" * 64,
        heartbeat_seconds=1.0,
    )


def _packet() -> dict:
    schedule = CTRL.build_schedule()
    return {
        "schedule": schedule,
        "commands": CTRL.commands(schedule),
        "runtime_contract": {
            "max_concurrent_cells": 8,
            "cpu_threads_per_cell": 1,
            "device": "cpu",
        },
    }


def test_packet_binds_supervisor_source_launch_and_verify() -> None:
    assert CTRL.SUPERVISOR_PATH in CTRL.SOURCE_PATHS
    commands = CTRL.commands(CTRL.build_schedule())
    assert commands["supervise"][0:3] == [
        "{python}", CTRL.SUPERVISOR_PATH, "launch"]
    assert commands["verify_supervisor"][0:3] == [
        "{python}", CTRL.SUPERVISOR_PATH, "verify"]
    assert commands["supervise"].count("{receipt_sha256}") == 1
    assert commands["verify_supervisor"].count("{receipt_sha256}") == 1


def test_cell_specs_expand_all_48_immutable_commands(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    specs = SUP.cell_specs(_packet(), _config(tmp_path))
    assert len(specs) == CTRL.TRAINING_CELLS == 48
    assert [spec.index for spec in specs] == list(range(48))
    assert len({spec.name for spec in specs}) == 48
    assert len({spec.output for spec in specs}) == 48
    for index, spec in enumerate(specs):
        assert spec.argv[0] == sys.executable
        position = spec.argv.index("--cell-index")
        assert spec.argv[position + 1] == str(index)
        assert "{" not in "".join(spec.argv)
        assert spec.output == (
            tmp_path / _packet()["schedule"]["cells"][index]["result"]
        ).resolve()


def test_command_expansion_refuses_unknown_or_non_string_tokens() -> None:
    with pytest.raises(SUP.TrainingSupervisorRefused, match="unresolved"):
        SUP.expand_command(["python", "{unknown}"], {})
    with pytest.raises(SUP.TrainingSupervisorRefused, match="non-string"):
        SUP.expand_command(["python", 3], {})


def test_preflight_detects_any_cell_or_supervisor_collision(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    monkeypatch.setattr(
        SUP.RUNTIME, "_cell_slot_path",
        lambda index: tmp_path / "locks" / f"cell-{index}.json")
    monkeypatch.setattr(
        SUP.RUNTIME, "_snapshot_path",
        lambda cell, epoch: tmp_path / "checkpoints" / str(
            cell["cell_id"]) / f"epoch-{epoch}.pt")
    monkeypatch.setattr(
        SUP.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args, returncode=0, stdout=""))
    packet = _packet()
    config = _config(tmp_path)
    assert SUP.preflight_problems(packet, config) == []

    collision = (tmp_path / SUP.PROGRESS_PATH).resolve()
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_text("already here")
    problems = SUP.preflight_problems(packet, config)
    assert any("supervisor collision" in value for value in problems)
    collision.unlink()

    slot = tmp_path / "locks" / "cell-0.json"
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_text("consumed")
    problems = SUP.preflight_problems(packet, config)
    assert any("consumed training cell slot" in value for value in problems)
    slot.unlink()

    output = SUP.cell_specs(packet, config)[0].output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("already trained")
    problems = SUP.preflight_problems(packet, config)
    assert any("training cell output collision" in value
               for value in problems)
    output.unlink()

    checkpoint = next(iter(SUP._snapshot_paths(packet)))
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text("already trained")
    problems = SUP.preflight_problems(packet, config)
    assert any("training checkpoint collision" in value
               for value in problems)


def test_parent_validation_refuses_unreviewed_heartbeat_drift(
        monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path)
    packet = _packet()
    monkeypatch.setattr(
        SUP, "_git",
        lambda *args: config.expected_git if args == ("rev-parse", "HEAD")
        else "")
    monkeypatch.setattr(SUP.RUNTIME, "_packet", lambda *args: (packet, {}))
    monkeypatch.setattr(SUP.RUNTIME, "_receipt", lambda *args: {})
    with pytest.raises(
            SUP.TrainingSupervisorRefused, match="concurrency/runtime drift"):
        SUP._validated_parents(config)


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode = 0

    def poll(self):
        return 0


class _LiveProcess(_FakeProcess):
    def __init__(self, pid: int, returncode=None):
        super().__init__(pid)
        self.returncode = returncode

    def poll(self):
        return self.returncode


class _FakeProgress:
    def __init__(self):
        self.events = []

    def event(self, phase, status, **fields):
        self.events.append((phase, status, fields))


def test_scheduler_starts_all_six_waves_with_eight_before_first_exit(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    started = []

    def start(spec):
        started.append(spec.index)
        return SUP.RunningJob(
            spec=spec, process=_FakeProcess(1000 + int(spec.index)),
            log_handle=io.StringIO(),
            log_partial=tmp_path / f"{spec.index}.partial",
            started_ns=1,
        )

    monkeypatch.setattr(SUP, "_start_job", start)
    monkeypatch.setattr(SUP, "_finish_job", lambda *args: None)
    monkeypatch.setattr(SUP, "_cell_output_problems", lambda spec: [])
    monkeypatch.setattr(SUP.time, "sleep", lambda value: None)
    progress = _FakeProgress()
    complete = SUP._run_cells(_packet(), _config(tmp_path), progress)
    assert [spec.index for spec in complete] == list(range(48))
    assert started == list(range(48))
    first_exit = next(index for index, event in enumerate(progress.events)
                      if event[1] == "exit")
    assert [event[1] for event in progress.events[:first_exit]] \
        == ["started"] * SUP.MAX_WORKERS


def test_failed_first_wave_stops_peers_and_never_starts_later_cells(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    started = []
    stopped = []

    def start(spec):
        started.append(spec.index)
        code = 7 if spec.index == 0 else None
        return SUP.RunningJob(
            spec=spec, process=_LiveProcess(2000 + int(spec.index), code),
            log_handle=io.StringIO(),
            log_partial=tmp_path / f"{spec.index}.partial",
            started_ns=1,
        )

    monkeypatch.setattr(SUP, "_start_job", start)
    monkeypatch.setattr(SUP, "_finish_job", lambda *args: None)
    monkeypatch.setattr(
        SUP, "_stop_jobs",
        lambda jobs: stopped.extend(job.spec.index for job in jobs))
    progress = _FakeProgress()
    with pytest.raises(SUP.TrainingSupervisorRefused, match="exited 7"):
        SUP._run_cells(_packet(), _config(tmp_path), progress)
    assert started == list(range(SUP.MAX_WORKERS))
    assert stopped == list(range(1, SUP.MAX_WORKERS))
    assert not any(index >= SUP.MAX_WORKERS for index in started)


def test_aggregate_gate_binds_identity_self_hash_and_report_authority(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    packet = _packet()
    config = _config(tmp_path)
    spec = SUP.JobSpec(
        name=SUP.AGGREGATE_JOB, index=None, argv=("python", "aggregate"),
        output=tmp_path / "aggregate.json",
        log_final=tmp_path / "aggregate.log",
        exit_final=tmp_path / "aggregate-exit.json")
    value = {
        "schema": SUP.RUNTIME.AGGREGATE_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": config.expected_git,
        "controller_packet_sha256": config.expected_packet_sha256,
        "training_receipt_sha256": config.expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "cell_count": CTRL.TRAINING_CELLS,
        "decision": "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW",
        "report_packet_review_authorized": True,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["aggregate_sha256"] = CTRL.self_hash(value, "aggregate_sha256")
    spec.output.write_bytes(CTRL.canonical_json(value))
    monkeypatch.setattr(SUP, "aggregate_spec", lambda *args: spec)
    monkeypatch.setattr(
        SUP, "_start_job",
        lambda ignored: SUP.RunningJob(
            spec=spec, process=_LiveProcess(3000, 0),
            log_handle=io.StringIO(),
            log_partial=tmp_path / "aggregate.log.partial", started_ns=1))
    monkeypatch.setattr(SUP, "_finish_job", lambda *args: None)
    monkeypatch.setattr(SUP.time, "sleep", lambda value: None)
    assert SUP._run_aggregate(packet, config, _FakeProgress()) == spec

    value["report_packet_review_authorized"] = False
    value["aggregate_sha256"] = CTRL.self_hash(value, "aggregate_sha256")
    spec.output.write_bytes(CTRL.canonical_json(value))
    with pytest.raises(
            SUP.TrainingSupervisorRefused,
            match="aggregate terminal authority drift"):
        SUP._run_aggregate(packet, config, _FakeProgress())


def test_epoch_progress_reads_latest_complete_json(tmp_path: Path) -> None:
    spec = SUP.JobSpec(
        name="play-seed41-curve100", index=0, argv=("python",),
        output=tmp_path / "cell.json", log_final=tmp_path / "cell.log",
        exit_final=tmp_path / "exit.json")
    log_partial = SUP.partial(spec.log_final)
    log_partial.write_text(
        "not-json\n"
        + json.dumps({"status": "TRAINING", "epoch": 1,
                      "max_epoch": 32, "updates": 2}) + "\n"
        + json.dumps({"status": "TRAINING", "epoch": 8,
                      "max_epoch": 32, "updates": 16}) + "\n")
    job = SUP.RunningJob(
        spec=spec, process=_FakeProcess(1), log_handle=io.StringIO(),
        log_partial=log_partial, started_ns=1)
    assert SUP._latest_epoch(job) == {
        "job": spec.name, "epoch": 8, "max_epoch": 32, "updates": 16}


def test_exit_evidence_binds_exact_command_and_forbids_retry() -> None:
    spec = SUP.JobSpec(
        name="cell", index=0, argv=("python", "run"),
        output=SUP.REPO / "cell.json", log_final=SUP.REPO / "cell.log",
        exit_final=SUP.REPO / "exit.json")
    value = {
        "schema": SUP.EXIT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "job": "cell",
        "index": 0,
        "pid": 1,
        "started_ns": 1,
        "finished_ns": 2,
        "returncode": 0,
        "argv_sha256": SUP.hashlib.sha256(
            b"python\0run").hexdigest(),
        "output": str(spec.output.relative_to(SUP.REPO)),
        "retry_authorized": False,
    }
    assert SUP._expected_exit(spec, value)
    value["retry_authorized"] = True
    assert not SUP._expected_exit(spec, value)
    value["retry_authorized"] = False
    value["argv_sha256"] = "0" * 64
    assert not SUP._expected_exit(spec, value)
