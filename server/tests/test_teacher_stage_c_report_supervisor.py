from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

import teacher_stage_c_report_controller as CTRL
import teacher_stage_c_report_supervisor as SUP


def _config(tmp_path: Path) -> SUP.Config:
    return SUP.Config(
        expected_git="a" * 40,
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="b" * 64,
        review_record=tmp_path / "review.md",
        fresh_report_review_record=tmp_path / "fresh-review.md",
        state_set_review_record=tmp_path / "state-review.md",
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="c" * 64,
        heartbeat_seconds=1.0,
    )


def _packet() -> dict:
    shared = [
        "{python}", "server/scripts/teacher_stage_c_report_runtime.py",
        "run-shard", "--expected-git", "{git}",
        "--controller-packet", CTRL.PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
        "--fresh-report-review-record", "{fresh_report_review_record}",
        "--state-set-review-record", "{state_set_review_record}",
        "--report-receipt", "receipt.json",
        "--expected-report-receipt-sha256", "{receipt_sha256}",
    ]
    shards = [{
        "index": index,
        "result": SUP.RUNTIME.SHARD_PATHS[index],
    } for index in range(CTRL.REPORT_SHARDS)]
    commands = [[
        *shared, "--shard-index", str(index), "--progress-every", "1",
        "--out", SUP.RUNTIME.SHARD_PATHS[index],
    ] for index in range(CTRL.REPORT_SHARDS)]
    evaluate = [
        "{python}", "server/scripts/teacher_stage_c_report_runtime.py",
        "evaluate", "--expected-git", "{git}",
        "--controller-packet", CTRL.PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
        "--fresh-report-review-record", "{fresh_report_review_record}",
        "--state-set-review-record", "{state_set_review_record}",
        "--report-receipt", "receipt.json",
        "--expected-report-receipt-sha256", "{receipt_sha256}",
        "--label-shards", *SUP.RUNTIME.SHARD_PATHS,
        "--out", SUP.RUNTIME.RESULT_PATH,
    ]
    return {
        "runtime_contract": {
            "max_concurrent_label_shards": 8,
            "supervisor_signal_contract": {
                "handled_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
                "signals_deferred_until_child_registered": True,
                "terminates_all_owned_children": True,
                "orphaned_label_workers_authorized": False,
            },
        },
        "report_schedule": {
            "schedule_sha256": "d" * 64,
            "shards": shards,
        },
        "commands": {"run_shards": commands, "evaluate": evaluate},
    }


def test_packet_binds_supervisor_source_and_command() -> None:
    assert ("server/scripts/teacher_stage_c_report_supervisor.py"
            in CTRL.SOURCE_PATHS)


def test_shard_specs_expand_all_eight_immutable_commands(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    specs = SUP.shard_specs(_packet(), _config(tmp_path))
    assert len(specs) == CTRL.REPORT_SHARDS == 8
    assert [spec.index for spec in specs] == list(range(8))
    assert len({spec.output for spec in specs}) == 8
    for index, spec in enumerate(specs):
        assert spec.argv[0] == sys.executable
        position = spec.argv.index("--shard-index")
        assert spec.argv[position + 1] == str(index)
        assert "{" not in "".join(spec.argv)


def test_command_expansion_refuses_unknown_or_non_string_tokens() -> None:
    with pytest.raises(SUP.ReportSupervisorRefused, match="unresolved"):
        SUP.expand_command(["python", "{unknown}"], {})
    with pytest.raises(SUP.ReportSupervisorRefused, match="non-string"):
        SUP.expand_command(["python", 3], {})


def test_preflight_detects_consumed_shard_or_result(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    monkeypatch.setattr(
        SUP.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args, returncode=0, stdout=""))
    packet = _packet()
    config = _config(tmp_path)
    assert SUP.preflight_problems(packet, config) == []

    slot = tmp_path / SUP.RUNTIME.SHARD_ADMISSION_PATHS[0]
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_text("consumed")
    assert any("consumed REPORT shard slot" in value
               for value in SUP.preflight_problems(packet, config))
    slot.unlink()

    result = tmp_path / SUP.RUNTIME.RESULT_PATH
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text("already evaluated")
    assert any("REPORT result collision" in value
               for value in SUP.preflight_problems(packet, config))


def test_parent_validation_refuses_unreviewed_heartbeat_drift(
        monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path)
    packet = _packet()
    monkeypatch.setattr(
        SUP, "_git",
        lambda *args: config.expected_git if args == ("rev-parse", "HEAD")
        else "")
    monkeypatch.setattr(
        SUP.RUNTIME, "_packet",
        lambda *args, **kwargs: (packet, {}, {}, {}, []))
    monkeypatch.setattr(SUP.RUNTIME, "_receipt", lambda *args: {})
    monkeypatch.setattr(SUP.CTRL, "runtime_contract",
                        lambda: packet["runtime_contract"])
    with pytest.raises(
            SUP.ReportSupervisorRefused, match="concurrency/runtime drift"):
        SUP._validated_parents(config)


class _FakeProcess:
    def __init__(self, pid: int, returncode=0):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


class _FakeProgress:
    def __init__(self):
        self.events = []

    def event(self, phase, status, **fields):
        self.events.append((phase, status, fields))


def test_scheduler_starts_all_eight_before_first_exit(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    started = []

    def start(spec, owner=None):
        started.append(spec.index)
        return SUP.RunningJob(
            spec=spec, process=_FakeProcess(1000 + int(spec.index)),
            log_handle=io.StringIO(),
            log_partial=tmp_path / f"{spec.index}.partial",
            started_ns=1)

    monkeypatch.setattr(SUP, "_start_job", start)
    monkeypatch.setattr(SUP, "_finish_job", lambda *args: None)
    monkeypatch.setattr(SUP, "_validate_shard_output", lambda *args, **kw: None)
    progress = _FakeProgress()
    complete = SUP._run_shards(
        _packet(), [], _config(tmp_path), progress)
    assert [spec.index for spec in complete] == list(range(8))
    assert started == list(range(8))
    first_exit = next(index for index, event in enumerate(progress.events)
                      if event[1] == "exit")
    assert [event[1] for event in progress.events[:first_exit]] \
        == ["started"] * 8


def test_failed_shard_stops_all_peers_and_never_evaluates(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    started = []
    stopped = []

    def start(spec, owner=None):
        started.append(spec.index)
        code = 7 if spec.index == 0 else None
        return SUP.RunningJob(
            spec=spec, process=_FakeProcess(2000 + int(spec.index), code),
            log_handle=io.StringIO(),
            log_partial=tmp_path / f"{spec.index}.partial",
            started_ns=1)

    monkeypatch.setattr(SUP, "_start_job", start)
    monkeypatch.setattr(SUP, "_finish_job", lambda *args: None)
    monkeypatch.setattr(
        SUP, "_stop_jobs",
        lambda jobs: stopped.extend(job.spec.index for job in jobs))
    with pytest.raises(SUP.ReportSupervisorRefused, match="exited 7"):
        SUP._run_shards(_packet(), [], _config(tmp_path), _FakeProgress())
    assert started == list(range(8))
    assert stopped == list(range(1, 8))


def test_shard_progress_reads_latest_complete_json(tmp_path: Path) -> None:
    spec = SUP.JobSpec(
        name="shard-00", index=0, argv=("python",),
        output=tmp_path / "shard.json", log_final=tmp_path / "shard.log",
        exit_final=tmp_path / "exit.json")
    log_partial = SUP.partial(spec.log_final)
    log_partial.write_text(
        "not-json\n"
        + json.dumps({
            "event": "stage-c-fresh-report-label-progress-v1",
            "states_complete": 4, "states_total": 60, "refusals": 0,
        }) + "\n")
    job = SUP.RunningJob(
        spec=spec, process=_FakeProcess(1), log_handle=io.StringIO(),
        log_partial=log_partial, started_ns=1)
    assert SUP._latest_shard_progress(job) == {
        "job": "shard-00", "states_complete": 4,
        "states_total": 60, "refusals": 0}


def test_result_validation_requires_full_recomputation(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    spec = SUP.JobSpec(
        name=SUP.EVALUATE_JOB, index=None, argv=("python",),
        output=tmp_path / "result.json", log_final=tmp_path / "result.log",
        exit_final=tmp_path / "exit.json")
    expected = {"result_sha256": "1" * 64, "decision": "SELECT_NONE"}
    spec.output.write_text(json.dumps(expected))
    monkeypatch.setattr(SUP.RUNTIME, "recompute_result",
                        lambda **kwargs: expected)
    assert SUP._validate_result_output(spec, _config(tmp_path)) == expected
    spec.output.write_text(json.dumps({**expected, "decision": "PASS"}))
    with pytest.raises(
            SUP.ReportSupervisorRefused, match="full recomputation drift"):
        SUP._validate_result_output(spec, _config(tmp_path))


def test_terminal_review_claim_authorizes_only_composition_freeze() -> None:
    packet = {
        "producer": {"git": "a" * 40},
        "report_schedule": {"schedule_sha256": "d" * 64},
        "parents": {"fresh_report_selection": {
            "sealed_selection_sha256": "e" * 64}},
        "selected_capability": {
            "surface": "play", "head": "ranking", "epoch": 8},
        "protected_policy": {
            "schema": CTRL.REPORT.PROTECTED_POLICY_SCHEMA,
            "surface": "play", "head": "ranking",
            "ensemble":
                "arithmetic_mean_raw_rank_logits_across_eight_seeds",
            "incumbent_index": 0, "alternative_start_index": 1,
            "threshold": 0.2, "strict_greater_than_threshold": True,
            "alternative_tie_break": "lowest_candidate_index",
            "fallback_index": 0, "bury_behavior": "unchanged_incumbent",
        },
    }
    result = {
        "result_sha256": "f" * 64,
        "report_label_shard_files_opened": 8,
        "selected_surface_rows_labeled": 480,
        "report_label_refusals": 0,
        "work": {
            "candidate_worlds_attempted": 100,
            "candidate_worlds_completed": 100,
        },
        "candidate_world_ceiling": 120,
        "candidate_world_ceiling_respected": True,
        "evaluation": {"result_sha256": "1" * 64},
        "decision": "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW",
        "composition_packet_review_authorized": True,
    }
    final = {"final_sha256": "2" * 64}
    claim = SUP.expected_review_claim(
        packet=packet, packet_external_sha256="3" * 64,
        receipt_external_sha256="4" * 64, result=result,
        result_external_sha256="5" * 64, supervisor_final=final,
        supervisor_external_sha256="6" * 64)
    assert claim["one_composition_controller_freeze_authorized"] is True
    assert claim["report_reuse_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_promotion"] is False


def test_exit_evidence_binds_exact_command_and_forbids_retry() -> None:
    spec = SUP.JobSpec(
        name="shard-00", index=0, argv=("python", "run"),
        output=SUP.REPO / "shard.json",
        log_final=SUP.REPO / "shard.log",
        exit_final=SUP.REPO / "exit.json")
    value = {
        "schema": SUP.EXIT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "job": "shard-00",
        "index": 0,
        "pid": 1,
        "started_ns": 1,
        "finished_ns": 2,
        "returncode": 0,
        "argv_sha256": SUP.hashlib.sha256(b"python\0run").hexdigest(),
        "output": str(spec.output.relative_to(SUP.REPO)),
        "retry_authorized": False,
    }
    assert SUP._expected_exit(spec, value)
    value["retry_authorized"] = True
    assert not SUP._expected_exit(spec, value)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_handled_signal_terminates_registered_real_child_without_orphan(
        monkeypatch, tmp_path: Path, signum: int) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    spec = SUP.JobSpec(
        name="signal-owned-shard", index=0,
        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
        output=tmp_path / "shard.json",
        log_final=tmp_path / "shard.log",
        exit_final=tmp_path / "exit.json")
    job = None
    with pytest.raises(SUP.ReportSupervisorInterrupted) as caught:
        with SUP.SignalOwner() as owner:
            job = SUP._start_job(spec, owner)
            assert job.process.poll() is None
            os.kill(os.getpid(), signum)
    assert caught.value.signum == signum
    assert job is not None
    job.process.wait(timeout=2.0)
    assert job.process.poll() is not None
    assert spec.log_final.is_file()
    assert not SUP.partial(spec.log_final).exists()
    assert json.loads(spec.exit_final.read_text())["retry_authorized"] is False


def test_signal_during_spawn_is_deferred_until_child_registration(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(SUP, "REPO", tmp_path)
    spec = SUP.JobSpec(
        name="spawn-window-shard", index=0,
        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
        output=tmp_path / "shard.json",
        log_final=tmp_path / "shard.log",
        exit_final=tmp_path / "exit.json")
    real_popen = subprocess.Popen
    spawned = []

    def signal_before_popen_returns(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        os.kill(os.getpid(), signal.SIGTERM)
        return process

    monkeypatch.setattr(SUP.subprocess, "Popen", signal_before_popen_returns)
    try:
        with pytest.raises(SUP.ReportSupervisorInterrupted):
            with SUP.SignalOwner() as owner:
                SUP._start_job(spec, owner)
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2.0)
    assert len(spawned) == 1
    assert spawned[0].poll() is not None
    assert spec.exit_final.is_file()
    assert not SUP.partial(spec.log_final).exists()
