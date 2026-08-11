#!/usr/bin/env python3
"""Own the reviewed fresh-REPORT execution from labels to one evaluation.

The REPORT runtime gives every label shard a durable one-shot admission and
consumes the global REPORT-open admission before any label or model score is
computed.  This supervisor supplies the process owner around those commands:
it starts exactly eight label workers, emits durable progress, terminates all
siblings on any failure or handled signal, and invokes evaluation only after
all eight terminal shards validate.

It cannot retry, resume, change the selected capability, compose a bot, launch
games, promote, or deploy.  ``verify`` reopens every terminal artifact and
recomputes the fixed REPORT result without consuming another admission.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

_CONTROLLER_MODULE = os.environ.get(
    "SHENGJI_STAGE_C_REPORT_CONTROLLER",
    "teacher_stage_c_report_controller")
if _CONTROLLER_MODULE not in {
        "teacher_stage_c_report_controller",
        "teacher_stage_c_expanded_report_controller",
        "teacher_stage_c_expanded_play_report_controller"}:
    raise RuntimeError("unrecognized Stage-C REPORT controller module")
CTRL = importlib.import_module(_CONTROLLER_MODULE)  # noqa: E402
import teacher_stage_c_report_runtime as RUNTIME  # noqa: E402


SCHEMA = getattr(
    CTRL, "SUPERVISOR_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-supervisor-v1")
EXIT_SCHEMA = getattr(
    CTRL, "SUPERVISOR_EXIT_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-supervisor-exit-v1")
FINAL_SCHEMA = getattr(
    CTRL, "SUPERVISOR_FINAL_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-supervisor-final-v1")
REVIEW_SCHEMA = getattr(
    CTRL, "SUPERVISOR_REVIEW_SCHEMA",
    "teacher-stage-c-protected-anchor-fresh-report-result-review-v1")
REVIEW_MARKER = getattr(
    CTRL, "SUPERVISOR_REVIEW_MARKER",
    "TEACHER_STAGE_C_V11_FREE_FRESH_REPORT_RESULT_V1_REVIEW ")
MAX_WORKERS = CTRL.SUPERVISOR_MAX_WORKERS
HEARTBEAT_SECONDS = CTRL.SUPERVISOR_HEARTBEAT_SECONDS
PROGRESS_PATH = Path(
    f"server/runs/logs/{CTRL.RUN_ID}/report-supervisor.jsonl")
FINAL_PATH = Path(
    f"server/runs/logs/{CTRL.RUN_ID}/report-supervisor-final.json")
LOG_DIRECTORY = Path(
    f"server/runs/logs/{CTRL.RUN_ID}/supervisor-logs")
EXIT_DIRECTORY = Path(
    f"server/runs/logs/{CTRL.RUN_ID}/supervisor-exits")
EVALUATE_JOB = "evaluate"


class ReportSupervisorRefused(RuntimeError):
    """The reviewed one-shot REPORT execution cannot proceed or verify."""


class ReportSupervisorInterrupted(BaseException):
    """A handled process signal interrupted the one-shot owner."""

    def __init__(self, signum: int):
        self.signum = int(signum)
        self.signal_name = signal.Signals(signum).name
        super().__init__(
            f"REPORT supervisor received {self.signal_name}; "
            "all owned children are terminally stopped")


@dataclass(frozen=True)
class Config:
    expected_git: str
    packet_path: Path
    expected_packet_sha256: str
    review_record: Path
    fresh_report_review_record: Path
    state_set_review_record: Path
    receipt_path: Path
    expected_receipt_sha256: str
    heartbeat_seconds: float = float(HEARTBEAT_SECONDS)


@dataclass(frozen=True)
class JobSpec:
    name: str
    index: int | None
    argv: tuple[str, ...]
    output: Path
    log_final: Path
    exit_final: Path


@dataclass
class RunningJob:
    spec: JobSpec
    process: subprocess.Popen
    log_handle: IO[str]
    log_partial: Path
    started_ns: int
    finished: bool = False


class SignalOwner:
    """Own children across signals, including the Popen registration gap."""

    def __init__(self) -> None:
        self.signals = tuple(
            getattr(signal, name) for name in CTRL.SUPERVISOR_HANDLED_SIGNALS)
        self.previous: dict[int, object] = {}
        self.jobs: list[RunningJob] = []
        self.interrupted_by: int | None = None
        self.spawning = False

    def __enter__(self) -> "SignalOwner":
        self.previous = {
            signum: signal.getsignal(signum) for signum in self.signals}
        for signum in self.signals:
            signal.signal(signum, self._handle)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is not None or self.jobs:
                _stop_jobs(self.jobs)
        finally:
            for signum, previous in self.previous.items():
                signal.signal(signum, previous)
        return False

    def _handle(self, signum: int, _frame: object) -> None:
        if self.interrupted_by is None:
            self.interrupted_by = signum
            for handled in self.signals:
                signal.signal(handled, signal.SIG_IGN)
        if not self.spawning:
            raise ReportSupervisorInterrupted(self.interrupted_by)

    def register(self, job: RunningJob) -> None:
        if job in self.jobs:
            raise ReportSupervisorRefused(
                f"duplicate signal ownership for {job.spec.name}")
        self.jobs.append(job)

    def unregister(self, job: RunningJob) -> None:
        try:
            self.jobs.remove(job)
        except ValueError as exc:
            raise ReportSupervisorRefused(
                f"lost signal ownership for {job.spec.name}") from exc

    @contextlib.contextmanager
    def deferred_until_registered(self):
        if self.spawning:
            raise ReportSupervisorRefused(
                "nested REPORT child spawn is not authorized")
        self.spawning = True
        try:
            yield
        finally:
            self.spawning = False
            if self.interrupted_by is not None:
                raise ReportSupervisorInterrupted(self.interrupted_by)


def canonical_json(value: object) -> bytes:
    return CTRL.canonical_json(value)


def sha256_file(path: Path) -> str:
    return CTRL.sha256_file(path)


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def partial(path: Path) -> Path:
    return Path(str(path) + ".partial")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReportSupervisorRefused(
            f"cannot reopen JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportSupervisorRefused(f"JSON root is not an object: {path}")
    return value


def _publish_partial(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise ReportSupervisorRefused(
            f"refusing to overwrite {destination}") from exc
    source.unlink()


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_partial = partial(path)
    if lexists(path) or lexists(target_partial):
        raise ReportSupervisorRefused(f"refusing existing artifact {path}")
    with target_partial.open("xb") as handle:
        handle.write(canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    _publish_partial(target_partial, path)


class Progress:
    def __init__(self) -> None:
        self.final = (REPO / PROGRESS_PATH).resolve()
        self.partial = partial(self.final)
        self.final.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.partial.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise ReportSupervisorRefused(
                f"refusing existing progress {self.partial}") from exc
        self.closed = False

    def event(self, phase: str, status: str, **fields: object) -> None:
        value = {
            "schema": SCHEMA,
            "time_ns": time.time_ns(),
            "phase": phase,
            "status": status,
            **fields,
        }
        self.handle.write(json.dumps(
            value, sort_keys=True, separators=(",", ":")) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        visible = {key: item for key, item in value.items()
                   if key not in {"schema", "time_ns"}}
        print(json.dumps(visible, sort_keys=True), flush=True)

    def close(self) -> None:
        if not self.closed:
            self.handle.close()
            self.closed = True

    def publish(self) -> None:
        self.close()
        _publish_partial(self.partial, self.final)


def _validated_parents(config: Config) -> tuple[dict, list[dict], dict]:
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise ReportSupervisorRefused("REPORT supervisor Git drift")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ReportSupervisorRefused("REPORT supervisor refuses dirty tree")
    try:
        packet, _dataset, _training, _fresh, states = RUNTIME._packet(
            config.packet_path, config.expected_packet_sha256,
            fresh_report_review_record=config.fresh_report_review_record,
            state_set_review_record=config.state_set_review_record)
        receipt = RUNTIME._receipt(
            config.receipt_path, config.expected_receipt_sha256,
            packet, config.expected_packet_sha256, config.review_record)
    except (RUNTIME.ReportRuntimeRefused,
            CTRL.ReportControllerRefused) as exc:
        raise ReportSupervisorRefused(
            f"REPORT parent refused: {exc}") from exc
    runtime = packet.get("runtime_contract", {})
    if (runtime != CTRL.runtime_contract()
            or runtime.get("max_concurrent_label_shards") != MAX_WORKERS
            or config.heartbeat_seconds != HEARTBEAT_SECONDS
            or runtime.get("supervisor_signal_contract") != {
                "handled_signals": list(CTRL.SUPERVISOR_HANDLED_SIGNALS),
                "signals_deferred_until_child_registered": True,
                "terminates_all_owned_children": True,
                "orphaned_label_workers_authorized": False,
            }):
        raise ReportSupervisorRefused(
            "REPORT supervisor concurrency/runtime drift")
    return packet, states, receipt


def _substitutions(config: Config) -> dict[str, str]:
    return {
        "{python}": sys.executable,
        "{git}": config.expected_git,
        "{packet_sha256}": config.expected_packet_sha256,
        "{controller_review_record}": str(config.review_record),
        "{fresh_report_review_record}": str(
            config.fresh_report_review_record),
        "{state_set_review_record}": str(config.state_set_review_record),
        "{receipt_sha256}": config.expected_receipt_sha256,
    }


def expand_command(template: Sequence[object],
                   substitutions: Mapping[str, str]) -> tuple[str, ...]:
    if not isinstance(template, (list, tuple)) or not template:
        raise ReportSupervisorRefused("REPORT command template is empty")
    values = []
    for raw in template:
        if not isinstance(raw, str) or not raw:
            raise ReportSupervisorRefused(
                "REPORT command template has a non-string token")
        value = substitutions.get(raw, raw)
        if "{" in value or "}" in value:
            raise ReportSupervisorRefused(
                f"REPORT command has an unresolved token: {value}")
        values.append(value)
    return tuple(values)


def shard_specs(packet: Mapping[str, object], config: Config) -> list[JobSpec]:
    commands = packet.get("commands", {}).get("run_shards")
    shards = packet.get("report_schedule", {}).get("shards")
    if (not isinstance(commands, list) or not isinstance(shards, list)
            or len(commands) != CTRL.REPORT_SHARDS
            or len(shards) != CTRL.REPORT_SHARDS):
        raise ReportSupervisorRefused(
            "REPORT shard command population drift")
    substitutions = _substitutions(config)
    result = []
    for index, (command, shard) in enumerate(
            zip(commands, shards, strict=True)):
        if not isinstance(shard, dict) or shard.get("index") != index:
            raise ReportSupervisorRefused("REPORT shard order drift")
        output = (REPO / str(shard.get("result"))).resolve()
        result.append(JobSpec(
            name=f"shard-{index:02d}", index=index,
            argv=expand_command(command, substitutions), output=output,
            log_final=(REPO / LOG_DIRECTORY /
                       f"shard-{index:02d}.log").resolve(),
            exit_final=(REPO / EXIT_DIRECTORY /
                        f"shard-{index:02d}.json").resolve(),
        ))
    if len({spec.output for spec in result}) != CTRL.REPORT_SHARDS:
        raise ReportSupervisorRefused("REPORT shard output collision")
    return result


def evaluate_spec(packet: Mapping[str, object], config: Config) -> JobSpec:
    return JobSpec(
        name=EVALUATE_JOB, index=None,
        argv=expand_command(
            packet.get("commands", {}).get("evaluate"),
            _substitutions(config)),
        output=(REPO / RUNTIME.RESULT_PATH).resolve(),
        log_final=(REPO / LOG_DIRECTORY / "evaluate.log").resolve(),
        exit_final=(REPO / EXIT_DIRECTORY / "evaluate.json").resolve(),
    )


def _owned_targets(packet: Mapping[str, object], config: Config) \
        -> Iterable[Path]:
    for path in ((REPO / PROGRESS_PATH).resolve(),
                 (REPO / FINAL_PATH).resolve()):
        yield path
        yield partial(path)
    for spec in [*shard_specs(packet, config), evaluate_spec(packet, config)]:
        yield spec.log_final
        yield partial(spec.log_final)
        yield spec.exit_final
        yield partial(spec.exit_final)


def preflight_problems(packet: Mapping[str, object], config: Config) \
        -> list[str]:
    problems = []
    for path in _owned_targets(packet, config):
        if lexists(path):
            problems.append(f"one-shot REPORT supervisor collision {path}")
    for spec in shard_specs(packet, config):
        slot = (REPO / RUNTIME.SHARD_ADMISSION_PATHS[
            int(spec.index)]).resolve()
        if lexists(slot) or lexists(partial(slot)):
            problems.append(f"consumed REPORT shard slot {slot}")
        if lexists(spec.output) or lexists(partial(spec.output)):
            problems.append(f"REPORT shard output collision {spec.output}")
    result = (REPO / RUNTIME.RESULT_PATH).resolve()
    if lexists(result) or lexists(partial(result)):
        problems.append(f"REPORT result collision {result}")
    try:
        rows = subprocess.run(
            ["ps", "-axo", "command="], check=True,
            capture_output=True, text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"REPORT process inspection failed: {exc}")
    else:
        runtime_name = Path(getattr(
            CTRL, "RUNTIME_SCRIPT_PATH",
            "server/scripts/teacher_stage_c_report_runtime.py")).name
        if any(f"{runtime_name} run-shard" in row
               or f"{runtime_name} evaluate" in row
               for row in rows):
            problems.append("a Stage-C REPORT worker process already exists")
    return sorted(set(problems))


def _child_environment() -> dict[str, str]:
    value = dict(os.environ)
    value["PYTHONUNBUFFERED"] = "1"
    return value


def _start_job(spec: JobSpec, owner: SignalOwner | None = None) -> RunningJob:
    spec.log_final.parent.mkdir(parents=True, exist_ok=True)
    log_partial = partial(spec.log_final)
    try:
        handle = log_partial.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ReportSupervisorRefused(
            f"refusing existing child log {log_partial}") from exc
    process = None
    registered = False
    try:
        blocker = owner.deferred_until_registered() if owner is not None \
            else contextlib.nullcontext()
        with blocker:
            process = subprocess.Popen(
                spec.argv, cwd=REPO, env=_child_environment(),
                stdout=handle, stderr=subprocess.STDOUT, text=True,
            )
            job = RunningJob(
                spec=spec, process=process, log_handle=handle,
                log_partial=log_partial, started_ns=time.time_ns())
            if owner is not None:
                owner.register(job)
                registered = True
        return job
    except BaseException:
        if process is not None and not registered and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if not registered:
            handle.close()
        raise


def _exit_payload(job: RunningJob, returncode: int) -> dict:
    return {
        "schema": EXIT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "job": job.spec.name,
        "index": job.spec.index,
        "pid": job.process.pid,
        "started_ns": job.started_ns,
        "finished_ns": time.time_ns(),
        "returncode": returncode,
        "argv_sha256": hashlib.sha256(
            "\0".join(job.spec.argv).encode("utf-8")).hexdigest(),
        "output": str(job.spec.output.relative_to(REPO)),
        "retry_authorized": False,
    }


def _finish_job(job: RunningJob, returncode: int) -> None:
    if job.finished:
        return
    job.log_handle.flush()
    os.fsync(job.log_handle.fileno())
    job.log_handle.close()
    _publish_partial(job.log_partial, job.spec.log_final)
    _write_json_exclusive(job.spec.exit_final, _exit_payload(job, returncode))
    job.finished = True


def _stop_jobs(jobs: Iterable[RunningJob]) -> None:
    values = list(jobs)
    live = [job for job in values if job.process.poll() is None]
    for job in live:
        job.process.terminate()
    deadline = time.monotonic() + 10.0
    for job in live:
        try:
            job.process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait()
    for job in values:
        code = job.process.poll()
        if code is not None and not job.finished:
            try:
                _finish_job(job, code)
            except Exception:
                pass


def _latest_shard_progress(job: RunningJob) -> dict[str, object] | None:
    path = job.log_partial if job.log_partial.exists() else job.spec.log_final
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if (isinstance(value, dict)
                and value.get("event")
                == "stage-c-fresh-report-label-progress-v1"):
            return {
                "job": job.spec.name,
                "states_complete": value.get("states_complete"),
                "states_total": value.get("states_total"),
                "refusals": value.get("refusals"),
            }
    return None


def _validate_shard_output(
    spec: JobSpec, *, packet: Mapping[str, object], states: Sequence[dict],
    config: Config,
) -> None:
    if not is_regular_unlinked(spec.output) or lexists(partial(spec.output)):
        raise ReportSupervisorRefused(
            f"{spec.name} exited zero without regular output")
    try:
        RUNTIME.validate_shard(
            _load_json(spec.output), packet=packet, states=states,
            packet_sha256=config.expected_packet_sha256,
            receipt_sha256=config.expected_receipt_sha256,
            index=int(spec.index))
    except (RUNTIME.ReportRuntimeRefused,
            CTRL.ReportControllerRefused) as exc:
        raise ReportSupervisorRefused(
            f"{spec.name} terminal output drift: {exc}") from exc


def _run_shards(packet: Mapping[str, object], states: Sequence[dict],
                config: Config, progress: Progress,
                owner: SignalOwner | None = None) -> list[JobSpec]:
    specs = shard_specs(packet, config)
    if len(specs) > MAX_WORKERS:
        raise ReportSupervisorRefused(
            "REPORT shard concurrency exceeds reviewed maximum")
    live: list[RunningJob] = []
    complete: list[JobSpec] = []
    try:
        for spec in specs:
            job = _start_job(spec, owner)
            live.append(job)
            progress.event(
                "shard", "started", job=spec.name, index=spec.index,
                pid=job.process.pid, completed=0)
        last_heartbeat = time.monotonic()
        while live:
            for job in list(live):
                code = job.process.poll()
                if code is None:
                    continue
                _finish_job(job, code)
                if owner is not None:
                    owner.unregister(job)
                progress.event(
                    "shard", "exit", job=job.spec.name,
                    index=job.spec.index, pid=job.process.pid,
                    returncode=code)
                live.remove(job)
                if code != 0:
                    raise ReportSupervisorRefused(
                        f"{job.spec.name} exited {code}; no evaluation")
                _validate_shard_output(
                    job.spec, packet=packet, states=states, config=config)
                complete.append(job.spec)
            now = time.monotonic()
            if live and now - last_heartbeat >= config.heartbeat_seconds:
                progress.event(
                    "shards", "running", completed=len(complete),
                    total=len(specs),
                    live=[job.spec.name for job in live],
                    progress=[value for value in (
                        _latest_shard_progress(job) for job in live)
                        if value is not None])
                last_heartbeat = now
            if live:
                time.sleep(min(0.25, config.heartbeat_seconds))
    except BaseException:
        _stop_jobs(live)
        raise
    if len(complete) != CTRL.REPORT_SHARDS:
        raise ReportSupervisorRefused("REPORT supervisor lost a shard")
    return complete


def _validate_result_output(spec: JobSpec, config: Config) -> dict:
    if not is_regular_unlinked(spec.output) or lexists(partial(spec.output)):
        raise ReportSupervisorRefused(
            "REPORT evaluation exited zero without regular output")
    try:
        expected = RUNTIME.recompute_result(
            packet_path=config.packet_path,
            expected_packet_sha256=config.expected_packet_sha256,
            review_record=config.review_record,
            fresh_report_review_record=config.fresh_report_review_record,
            state_set_review_record=config.state_set_review_record,
            receipt_path=config.receipt_path,
            expected_receipt_sha256=config.expected_receipt_sha256,
            shard_paths=[(REPO / logical).resolve()
                         for logical in RUNTIME.SHARD_PATHS])
    except (RUNTIME.ReportRuntimeRefused,
            CTRL.ReportControllerRefused) as exc:
        raise ReportSupervisorRefused(
            f"REPORT result recomputation refused: {exc}") from exc
    if _load_json(spec.output) != expected:
        raise ReportSupervisorRefused(
            "REPORT result full recomputation drift")
    return expected


def _run_evaluate(packet: Mapping[str, object], config: Config,
                  progress: Progress,
                  owner: SignalOwner | None = None) -> JobSpec:
    spec = evaluate_spec(packet, config)
    job = _start_job(spec, owner)
    progress.event("evaluate", "started", pid=job.process.pid)
    last_heartbeat = time.monotonic()
    try:
        while job.process.poll() is None:
            now = time.monotonic()
            if now - last_heartbeat >= config.heartbeat_seconds:
                progress.event("evaluate", "running", pid=job.process.pid)
                last_heartbeat = now
            time.sleep(min(0.25, config.heartbeat_seconds))
        code = int(job.process.returncode)
        _finish_job(job, code)
        if owner is not None:
            owner.unregister(job)
    except BaseException:
        _stop_jobs([job])
        raise
    progress.event("evaluate", "exit", pid=job.process.pid, returncode=code)
    if code != 0:
        raise ReportSupervisorRefused(f"REPORT evaluation exited {code}")
    _validate_result_output(spec, config)
    return spec


def _expected_exit(spec: JobSpec, value: Mapping[str, object]) -> bool:
    return (value.get("schema") == EXIT_SCHEMA
            and value.get("run_id") == CTRL.RUN_ID
            and value.get("job") == spec.name
            and value.get("index") == spec.index
            and isinstance(value.get("pid"), int)
            and isinstance(value.get("started_ns"), int)
            and isinstance(value.get("finished_ns"), int)
            and value.get("finished_ns") >= value.get("started_ns")
            and value.get("returncode") == 0
            and value.get("argv_sha256") == hashlib.sha256(
                "\0".join(spec.argv).encode("utf-8")).hexdigest()
            and value.get("output") == str(spec.output.relative_to(REPO))
            and value.get("retry_authorized") is False)


def terminal_job_evidence(packet: Mapping[str, object], config: Config) \
        -> list[dict]:
    result = []
    for spec in [*shard_specs(packet, config), evaluate_spec(packet, config)]:
        for path, label in ((spec.output, "output"),
                            (spec.log_final, "log"),
                            (spec.exit_final, "exit")):
            if not is_regular_unlinked(path) or lexists(partial(path)):
                raise ReportSupervisorRefused(
                    f"terminal {spec.name} {label} missing/partial")
        if not _expected_exit(spec, _load_json(spec.exit_final)):
            raise ReportSupervisorRefused(
                f"terminal {spec.name} exit evidence drift")
        result.append({
            "job": spec.name,
            "index": spec.index,
            "output_path": str(spec.output.relative_to(REPO)),
            "output_sha256": sha256_file(spec.output),
            "log_path": str(spec.log_final.relative_to(REPO)),
            "log_sha256": sha256_file(spec.log_final),
            "exit_path": str(spec.exit_final.relative_to(REPO)),
            "exit_sha256": sha256_file(spec.exit_final),
        })
    return result


def final_payload(*, config: Config, packet: Mapping[str, object],
                  job_evidence: Sequence[Mapping[str, object]]) -> dict:
    result_path = (REPO / RUNTIME.RESULT_PATH).resolve()
    result = _load_json(result_path)
    value = {
        "schema": FINAL_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": config.expected_git,
        "controller_packet_sha256": config.expected_packet_sha256,
        "report_receipt_sha256": config.expected_receipt_sha256,
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "label_shards_complete": CTRL.REPORT_SHARDS,
        "max_concurrent_label_shards": MAX_WORKERS,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "progress_sha256": sha256_file((REPO / PROGRESS_PATH).resolve()),
        "jobs": list(job_evidence),
        "result_path": RUNTIME.RESULT_PATH,
        "result_external_sha256": sha256_file(result_path),
        "result_internal_sha256": result["result_sha256"],
        "decision": result["decision"],
        "composition_packet_review_authorized": result.get(
            "composition_packet_review_authorized") is True,
        "report_reuse_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_authorized": False,
    }
    value["final_sha256"] = CTRL.self_hash(value, "final_sha256")
    return value


def expected_review_claim(
    *, packet: Mapping[str, object], packet_external_sha256: str,
    receipt_external_sha256: str, result: Mapping[str, object],
    result_external_sha256: str, supervisor_final: Mapping[str, object],
    supervisor_external_sha256: str,
) -> dict:
    """Bind an independent terminal replay to its narrow next authority."""
    work = result.get("work")
    evaluation = result.get("evaluation")
    if (not isinstance(work, dict)
            or (evaluation is not None and not isinstance(evaluation, dict))):
        raise ReportSupervisorRefused(
            "REPORT result cannot form an external review claim")
    composition = result.get("composition_packet_review_authorized") is True
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": CTRL.RUN_ID,
        "controller_packet_sha256": packet_external_sha256,
        "report_receipt_sha256": receipt_external_sha256,
        "report_result_sha256": result_external_sha256,
        "report_result_internal_sha256": result["result_sha256"],
        "supervisor_final_sha256": supervisor_external_sha256,
        "supervisor_final_internal_sha256": supervisor_final["final_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "selected_capability": packet["selected_capability"],
        "protected_policy": packet.get("protected_policy"),
        "report_label_shards": result["report_label_shard_files_opened"],
        "selected_surface_rows_labeled": result[
            "selected_surface_rows_labeled"],
        "report_label_refusals": result["report_label_refusals"],
        "candidate_worlds_attempted": work[
            "candidate_worlds_attempted"],
        "candidate_worlds_completed": work[
            "candidate_worlds_completed"],
        "candidate_world_ceiling": result["candidate_world_ceiling"],
        "candidate_world_ceiling_respected": result[
            "candidate_world_ceiling_respected"],
        "evaluation_internal_sha256": (
            None if evaluation is None else evaluation["result_sha256"]),
        "decision": result["decision"],
        "v11_checkpoint_loaded": False,
        "terminal_full_recomputation_passed": True,
        "independent_review": True,
        "one_composition_controller_freeze_authorized": composition,
        "report_reuse_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def launch(config: Config) -> dict:
    packet, states, _receipt = _validated_parents(config)
    problems = preflight_problems(packet, config)
    if problems:
        raise ReportSupervisorRefused("; ".join(problems))
    progress = Progress()
    try:
        with SignalOwner() as owner:
            progress.event(
                "launch", "started", label_shards=CTRL.REPORT_SHARDS,
                max_workers=MAX_WORKERS,
                packet_sha256=config.expected_packet_sha256,
                receipt_sha256=config.expected_receipt_sha256)
            _run_shards(packet, states, config, progress, owner)
            _run_evaluate(packet, config, progress, owner)
            jobs = terminal_job_evidence(packet, config)
            progress.event(
                "launch", "complete", label_shards=CTRL.REPORT_SHARDS)
            progress.publish()
            value = final_payload(
                config=config, packet=packet, job_evidence=jobs)
            _write_json_exclusive((REPO / FINAL_PATH).resolve(), value)
            print(json.dumps(value, indent=2, sort_keys=True), flush=True)
            return value
    except BaseException as exc:
        try:
            progress.event("launch", "refused", error=type(exc).__name__)
        except Exception:
            pass
        raise
    finally:
        progress.close()


def verify(config: Config) -> dict:
    packet, _states, _receipt = _validated_parents(config)
    progress_path = (REPO / PROGRESS_PATH).resolve()
    final_path = (REPO / FINAL_PATH).resolve()
    for path in (progress_path, final_path):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise ReportSupervisorRefused(
                f"terminal supervisor artifact missing/partial: {path}")
    result = _validate_result_output(evaluate_spec(packet, config), config)
    jobs = terminal_job_evidence(packet, config)
    expected_final = final_payload(
        config=config, packet=packet, job_evidence=jobs)
    if _load_json(final_path) != expected_final:
        raise ReportSupervisorRefused("REPORT supervisor final drift")
    value = {
        "verified": True,
        "run_id": CTRL.RUN_ID,
        "final_sha256": sha256_file(final_path),
        "result_sha256": sha256_file((REPO / RUNTIME.RESULT_PATH).resolve()),
        "decision": result["decision"],
        "composition_packet_review_authorized": result.get(
            "composition_packet_review_authorized") is True,
        "strength_claim": False,
        "production_promotion": False,
    }
    print(json.dumps(value, sort_keys=True), flush=True)
    return value


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("launch", "verify"))
    root.add_argument("--expected-git", required=True)
    root.add_argument("--controller-packet", required=True)
    root.add_argument("--expected-controller-packet-sha256", required=True)
    root.add_argument("--controller-review-record", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--report-receipt", required=True)
    root.add_argument("--expected-report-receipt-sha256", required=True)
    root.add_argument(
        "--heartbeat-seconds", type=float,
        default=float(HEARTBEAT_SECONDS))
    return root


def main() -> int:
    args = parser().parse_args()
    if args.heartbeat_seconds != HEARTBEAT_SECONDS:
        raise ReportSupervisorRefused(
            f"heartbeat must equal the reviewed {HEARTBEAT_SECONDS} seconds")
    config = Config(
        expected_git=args.expected_git,
        packet_path=Path(args.controller_packet).resolve(),
        expected_packet_sha256=args.expected_controller_packet_sha256,
        review_record=Path(args.controller_review_record).resolve(),
        fresh_report_review_record=Path(
            args.fresh_report_review_record).resolve(),
        state_set_review_record=Path(args.state_set_review_record).resolve(),
        receipt_path=Path(args.report_receipt).resolve(),
        expected_receipt_sha256=args.expected_report_receipt_sha256,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    if args.command == "launch":
        launch(config)
    else:
        verify(config)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportSupervisorInterrupted as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (ReportSupervisorRefused, RUNTIME.ReportRuntimeRefused,
            CTRL.ReportControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
