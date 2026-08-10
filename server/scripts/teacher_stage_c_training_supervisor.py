#!/usr/bin/env python3
"""Own the one reviewed Stage-C training execution from cells to aggregate.

The training runtime deliberately gives every one of its 48 cells an
immutable admission slot and no retry path.  This supervisor supplies the
missing operational owner: it keeps exactly eight cells live, starts every
later wave, records each child exit, emits visible progress, and invokes the
frozen aggregate only after all 48 cells exit zero.  It never changes a model,
target, split, seed, curve, epoch, selector, or output path.

Any child failure, collision, handled termination signal, identity drift, or
publication failure terminates the remaining children and leaves the progress
file partial.  The supervisor cannot resume, retry, open REPORT, claim
strength, promote, or deploy.  Its ``verify`` command reopens every terminal
child/checkpoint and recomputes the aggregate from the reviewed packet.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
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

import teacher_stage_c_training_controller as CTRL  # noqa: E402
import teacher_stage_c_training_runtime as RUNTIME  # noqa: E402


SCHEMA = "teacher-stage-c-training-supervisor-v1"
EXIT_SCHEMA = "teacher-stage-c-training-supervisor-exit-v1"
FINAL_SCHEMA = "teacher-stage-c-training-supervisor-final-v1"
MAX_WORKERS = CTRL.SUPERVISOR_MAX_WORKERS
HEARTBEAT_SECONDS = CTRL.SUPERVISOR_HEARTBEAT_SECONDS
PROGRESS_PATH = Path(
    f"server/runs/logs/{CTRL.RUN_ID}/training-supervisor.jsonl"
)
FINAL_PATH = Path(
    f"server/runs/logs/{CTRL.RUN_ID}/training-supervisor-final.json"
)
LOG_DIRECTORY = Path(f"server/runs/logs/{CTRL.RUN_ID}/supervisor-logs")
EXIT_DIRECTORY = Path(f"server/runs/logs/{CTRL.RUN_ID}/supervisor-exits")
AGGREGATE_JOB = "aggregate"


class TrainingSupervisorRefused(RuntimeError):
    """The reviewed one-shot training execution cannot proceed or verify."""


class TrainingSupervisorInterrupted(BaseException):
    """A handled process signal interrupted the one-shot owner."""

    def __init__(self, signum: int):
        self.signum = int(signum)
        self.signal_name = signal.Signals(signum).name
        super().__init__(
            f"training supervisor received {self.signal_name}; "
            "all owned children are terminally stopped")


@dataclass(frozen=True)
class Config:
    expected_git: str
    packet_path: Path
    expected_packet_sha256: str
    review_record: Path
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
    """Own live children across catchable process termination signals.

    A handled signal is deferred around ``Popen`` until the new child is
    registered. This closes the otherwise unavoidable interval where the
    supervisor could die after spawning a cell but before its scheduler list
    knew the PID, without leaking a blocked signal mask into the child.
    """

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
            # Ignore repeats while Python unwinds and waits for children; a
            # second signal must not interrupt the cleanup it asked for.
            for handled in self.signals:
                signal.signal(handled, signal.SIG_IGN)
        if not self.spawning:
            raise TrainingSupervisorInterrupted(self.interrupted_by)

    def register(self, job: RunningJob) -> None:
        if job in self.jobs:
            raise TrainingSupervisorRefused(
                f"duplicate signal ownership for {job.spec.name}")
        self.jobs.append(job)

    def unregister(self, job: RunningJob) -> None:
        try:
            self.jobs.remove(job)
        except ValueError as exc:
            raise TrainingSupervisorRefused(
                f"lost signal ownership for {job.spec.name}") from exc

    @contextlib.contextmanager
    def deferred_until_registered(self):
        if self.spawning:
            raise TrainingSupervisorRefused(
                "nested training child spawn is not authorized")
        self.spawning = True
        try:
            yield
        finally:
            self.spawning = False
            if self.interrupted_by is not None:
                raise TrainingSupervisorInterrupted(self.interrupted_by)


def canonical_json(value: object) -> bytes:
    return CTRL.canonical_json(value)


def sha256_file(path: Path) -> str:
    return CTRL.sha256_file(path)


def sha256_bytes(value: bytes) -> str:
    return CTRL.sha256_bytes(value)


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
        raise TrainingSupervisorRefused(
            f"cannot reopen JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TrainingSupervisorRefused(f"JSON root is not an object: {path}")
    return value


def _publish_partial(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise TrainingSupervisorRefused(
            f"refusing to overwrite {destination}") from exc
    source.unlink()


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_partial = partial(path)
    if lexists(path) or lexists(target_partial):
        raise TrainingSupervisorRefused(f"refusing existing artifact {path}")
    try:
        with target_partial.open("xb") as handle:
            handle.write(canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        _publish_partial(target_partial, path)
    except BaseException:
        raise


class Progress:
    def __init__(self) -> None:
        self.final = (REPO / PROGRESS_PATH).resolve()
        self.partial = partial(self.final)
        self.final.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.partial.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise TrainingSupervisorRefused(
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


def _validated_parents(config: Config) -> tuple[dict, dict, dict]:
    if _git("rev-parse", "HEAD") != config.expected_git:
        raise TrainingSupervisorRefused("training supervisor Git drift")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise TrainingSupervisorRefused("training supervisor refuses dirty tree")
    try:
        packet, dataset = RUNTIME._packet(
            config.packet_path, config.expected_packet_sha256)
        packet["external_sha256"] = config.expected_packet_sha256
        receipt = RUNTIME._receipt(
            config.receipt_path, config.expected_receipt_sha256,
            packet, config.expected_packet_sha256, config.review_record)
    except (RUNTIME.TrainingRuntimeRefused,
            CTRL.TrainingControllerRefused) as exc:
        raise TrainingSupervisorRefused(
            f"training parent refused: {exc}") from exc
    runtime = packet.get("runtime_contract", {})
    signal_contract = runtime.get("supervisor_signal_contract", {})
    if (runtime.get("max_concurrent_cells") != MAX_WORKERS
            or runtime.get("cpu_threads_per_cell") != 1
            or runtime.get("device") != "cpu"
            or config.heartbeat_seconds != HEARTBEAT_SECONDS
            or signal_contract != {
                "handled_signals": list(CTRL.SUPERVISOR_HANDLED_SIGNALS),
                "signals_deferred_until_child_registered": True,
                "terminates_all_owned_children": True,
                "orphaned_cells_authorized": False,
            }):
        raise TrainingSupervisorRefused(
            "training supervisor concurrency/runtime drift")
    return packet, dataset, receipt


def _substitutions(config: Config) -> dict[str, str]:
    return {
        "{python}": sys.executable,
        "{git}": config.expected_git,
        "{packet_sha256}": config.expected_packet_sha256,
        "{controller_review_record}": str(config.review_record),
        "{receipt_sha256}": config.expected_receipt_sha256,
    }


def expand_command(template: Sequence[object],
                   substitutions: Mapping[str, str]) -> tuple[str, ...]:
    if not isinstance(template, (list, tuple)) or not template:
        raise TrainingSupervisorRefused("training command template is empty")
    values = []
    for raw in template:
        if not isinstance(raw, str) or not raw:
            raise TrainingSupervisorRefused(
                "training command template has a non-string token")
        value = substitutions.get(raw, raw)
        if "{" in value or "}" in value:
            raise TrainingSupervisorRefused(
                f"training command has an unresolved token: {value}")
        values.append(value)
    return tuple(values)


def cell_specs(packet: Mapping[str, object], config: Config) -> list[JobSpec]:
    rows = packet.get("commands", {}).get("run_cells")
    cells = packet.get("schedule", {}).get("cells")
    if (not isinstance(rows, list) or not isinstance(cells, list)
            or len(rows) != CTRL.TRAINING_CELLS
            or len(cells) != CTRL.TRAINING_CELLS):
        raise TrainingSupervisorRefused("training cell command population drift")
    result = []
    substitutions = _substitutions(config)
    for index, (row, cell) in enumerate(zip(rows, cells, strict=True)):
        if (not isinstance(row, dict) or row.get("index") != index
                or not isinstance(cell, dict) or cell.get("index") != index):
            raise TrainingSupervisorRefused("training cell command order drift")
        cell_id = str(cell.get("cell_id"))
        output = (REPO / str(cell.get("result"))).resolve()
        result.append(JobSpec(
            name=cell_id,
            index=index,
            argv=expand_command(row.get("command", []), substitutions),
            output=output,
            log_final=(REPO / LOG_DIRECTORY / f"{cell_id}.log").resolve(),
            exit_final=(REPO / EXIT_DIRECTORY / f"{cell_id}.json").resolve(),
        ))
    if (len({spec.name for spec in result}) != CTRL.TRAINING_CELLS
            or len({spec.output for spec in result}) != CTRL.TRAINING_CELLS):
        raise TrainingSupervisorRefused("training cell output collision")
    return result


def aggregate_spec(packet: Mapping[str, object], config: Config) -> JobSpec:
    command = packet.get("commands", {}).get("aggregate")
    output = (REPO / RUNTIME.AGGREGATE_PATH).resolve()
    return JobSpec(
        name=AGGREGATE_JOB,
        index=None,
        argv=expand_command(command, _substitutions(config)),
        output=output,
        log_final=(REPO / LOG_DIRECTORY / "aggregate.log").resolve(),
        exit_final=(REPO / EXIT_DIRECTORY / "aggregate.json").resolve(),
    )


def _snapshot_paths(packet: Mapping[str, object]) -> Iterable[Path]:
    for cell in packet["schedule"]["cells"]:
        for epoch in CTRL.MODEL.EPOCH_GRID:
            yield RUNTIME._snapshot_path(cell, epoch)


def _owned_targets(packet: Mapping[str, object], config: Config) \
        -> Iterable[Path]:
    for path in ((REPO / PROGRESS_PATH).resolve(),
                 (REPO / FINAL_PATH).resolve()):
        yield path
        yield partial(path)
    for spec in [*cell_specs(packet, config), aggregate_spec(packet, config)]:
        yield spec.log_final
        yield partial(spec.log_final)
        yield spec.exit_final
        yield partial(spec.exit_final)


def preflight_problems(packet: Mapping[str, object], config: Config) -> list[str]:
    problems = []
    for path in _owned_targets(packet, config):
        if lexists(path):
            problems.append(f"one-shot supervisor collision {path}")
    aggregate = (REPO / RUNTIME.AGGREGATE_PATH).resolve()
    if lexists(aggregate) or lexists(partial(aggregate)):
        problems.append(f"one-shot aggregate collision {aggregate}")
    for spec in cell_specs(packet, config):
        slot = RUNTIME._cell_slot_path(int(spec.index))
        if lexists(slot) or lexists(partial(slot)):
            problems.append(f"consumed training cell slot {slot}")
        if lexists(spec.output) or lexists(partial(spec.output)):
            problems.append(f"training cell output collision {spec.output}")
    for path in _snapshot_paths(packet):
        if lexists(path) or lexists(partial(path)):
            problems.append(f"training checkpoint collision {path}")
    try:
        rows = subprocess.run(
            ["ps", "-axo", "command="], check=True,
            capture_output=True, text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"training process inspection failed: {exc}")
    else:
        if any("teacher_stage_c_training_runtime.py run-cell" in row
               for row in rows):
            problems.append("a Stage-C training cell process already exists")
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
        raise TrainingSupervisorRefused(
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
                # A surviving partial is intentional terminal-failure evidence.
                pass


def _latest_epoch(job: RunningJob) -> dict[str, object] | None:
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
        if (isinstance(value, dict) and value.get("status") == "TRAINING"
                and isinstance(value.get("epoch"), int)):
            return {
                "job": job.spec.name,
                "epoch": value["epoch"],
                "max_epoch": value.get("max_epoch"),
                "updates": value.get("updates"),
            }
    return None


def _cell_output_problems(spec: JobSpec) -> list[str]:
    problems = []
    if not is_regular_unlinked(spec.output):
        return [f"{spec.name} exited zero without regular output"]
    if lexists(partial(spec.output)):
        problems.append(f"{spec.name} left an output partial")
    try:
        value = _load_json(spec.output)
    except TrainingSupervisorRefused as exc:
        return [str(exc)]
    if (value.get("schema") != RUNTIME.CELL_SCHEMA
            or value.get("run_id") != CTRL.RUN_ID
            or value.get("index") != spec.index
            or value.get("cell_id") != spec.name
            or value.get("status") != "COMPLETE"
            or value.get("report_rows_opened") != 0
            or value.get("report_open_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False):
        problems.append(f"{spec.name} terminal identity/authority drift")
    return problems


def _heartbeat(progress: Progress, *, live: Sequence[RunningJob],
               completed: int, total: int) -> None:
    progress.event(
        "cells", "running", completed=completed, total=total,
        live=[job.spec.name for job in live],
        pids=[job.process.pid for job in live],
        epochs=[value for value in (_latest_epoch(job) for job in live)
                if value is not None],
    )


def _run_cells(packet: Mapping[str, object], config: Config,
               progress: Progress,
               owner: SignalOwner | None = None) -> list[JobSpec]:
    specs = cell_specs(packet, config)
    queued = list(specs)
    live: list[RunningJob] = []
    complete: list[JobSpec] = []
    last_heartbeat = time.monotonic()
    interval = config.heartbeat_seconds
    try:
        while queued or live:
            while queued and len(live) < MAX_WORKERS:
                spec = queued.pop(0)
                job = _start_job(spec, owner)
                live.append(job)
                progress.event(
                    "cell", "started", job=spec.name, index=spec.index,
                    pid=job.process.pid, completed=len(complete),
                    queued=len(queued))
            for job in list(live):
                code = job.process.poll()
                if code is None:
                    continue
                _finish_job(job, code)
                if owner is not None:
                    owner.unregister(job)
                progress.event(
                    "cell", "exit", job=job.spec.name,
                    index=job.spec.index, pid=job.process.pid,
                    returncode=code)
                live.remove(job)
                if code != 0:
                    raise TrainingSupervisorRefused(
                        f"{job.spec.name} exited {code}; no aggregate")
                problems = _cell_output_problems(job.spec)
                if problems:
                    raise TrainingSupervisorRefused("; ".join(problems))
                complete.append(job.spec)
            now = time.monotonic()
            if (queued or live) and now - last_heartbeat >= interval:
                _heartbeat(
                    progress, live=live, completed=len(complete),
                    total=len(specs))
                last_heartbeat = now
            if queued or live:
                time.sleep(min(0.25, interval))
    except BaseException:
        _stop_jobs(live)
        raise
    if len(complete) != CTRL.TRAINING_CELLS:
        raise TrainingSupervisorRefused("training supervisor lost a cell")
    return complete


def _run_aggregate(packet: Mapping[str, object], config: Config,
                   progress: Progress,
                   owner: SignalOwner | None = None) -> JobSpec:
    spec = aggregate_spec(packet, config)
    job = _start_job(spec, owner)
    progress.event("aggregate", "started", pid=job.process.pid)
    last_heartbeat = time.monotonic()
    try:
        while job.process.poll() is None:
            now = time.monotonic()
            if now - last_heartbeat >= config.heartbeat_seconds:
                progress.event("aggregate", "running", pid=job.process.pid)
                last_heartbeat = now
            time.sleep(min(0.25, config.heartbeat_seconds))
        code = int(job.process.returncode)
        _finish_job(job, code)
        if owner is not None:
            owner.unregister(job)
    except BaseException:
        _stop_jobs([job])
        raise
    progress.event("aggregate", "exit", pid=job.process.pid, returncode=code)
    if code != 0:
        raise TrainingSupervisorRefused(f"aggregate exited {code}")
    if not is_regular_unlinked(spec.output) or lexists(partial(spec.output)):
        raise TrainingSupervisorRefused("aggregate lacks a regular final")
    value = _load_json(spec.output)
    decision = value.get("decision")
    expected_report_review = (
        decision == "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW")
    if (value.get("schema") != RUNTIME.AGGREGATE_SCHEMA
            or value.get("aggregate_sha256")
            != CTRL.self_hash(value, "aggregate_sha256")
            or value.get("run_id") != CTRL.RUN_ID
            or value.get("git") != config.expected_git
            or value.get("controller_packet_sha256")
            != config.expected_packet_sha256
            or value.get("training_receipt_sha256")
            != config.expected_receipt_sha256
            or value.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or value.get("cell_count") != CTRL.TRAINING_CELLS
            or decision not in {
                "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW", "SELECT_NONE"}
            or value.get("report_packet_review_authorized")
            is not expected_report_review
            or value.get("report_rows_opened") != 0
            or value.get("report_open_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False):
        raise TrainingSupervisorRefused("aggregate terminal authority drift")
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
    for spec in [*cell_specs(packet, config), aggregate_spec(packet, config)]:
        for path, label in ((spec.output, "output"),
                            (spec.log_final, "log"),
                            (spec.exit_final, "exit")):
            if not is_regular_unlinked(path) or lexists(partial(path)):
                raise TrainingSupervisorRefused(
                    f"terminal {spec.name} {label} missing/partial")
        exit_value = _load_json(spec.exit_final)
        if not _expected_exit(spec, exit_value):
            raise TrainingSupervisorRefused(
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
    aggregate_path = (REPO / RUNTIME.AGGREGATE_PATH).resolve()
    aggregate = _load_json(aggregate_path)
    value = {
        "schema": FINAL_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": config.expected_git,
        "controller_packet_sha256": config.expected_packet_sha256,
        "training_receipt_sha256": config.expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "cells_complete": CTRL.TRAINING_CELLS,
        "max_concurrent_cells": MAX_WORKERS,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "progress_sha256": sha256_file((REPO / PROGRESS_PATH).resolve()),
        "jobs": list(job_evidence),
        "aggregate_path": RUNTIME.AGGREGATE_PATH,
        "aggregate_sha256": sha256_file(aggregate_path),
        "decision": aggregate["decision"],
        "report_packet_review_authorized":
            aggregate.get("report_packet_review_authorized") is True,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_authorized": False,
    }
    value["final_sha256"] = CTRL.self_hash(value, "final_sha256")
    return value


def launch(config: Config) -> dict:
    packet, _dataset, _receipt = _validated_parents(config)
    problems = preflight_problems(packet, config)
    if problems:
        raise TrainingSupervisorRefused("; ".join(problems))
    progress = Progress()
    try:
        with SignalOwner() as owner:
            progress.event(
                "launch", "started", cells=CTRL.TRAINING_CELLS,
                max_workers=MAX_WORKERS,
                packet_sha256=config.expected_packet_sha256,
                receipt_sha256=config.expected_receipt_sha256)
            _run_cells(packet, config, progress, owner)
            _run_aggregate(packet, config, progress, owner)
            jobs = terminal_job_evidence(packet, config)
            progress.event("launch", "complete", cells=CTRL.TRAINING_CELLS)
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
    packet, _dataset, _receipt = _validated_parents(config)
    progress_path = (REPO / PROGRESS_PATH).resolve()
    final_path = (REPO / FINAL_PATH).resolve()
    for path in (progress_path, final_path):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise TrainingSupervisorRefused(
                f"terminal supervisor artifact missing/partial: {path}")
    specs = cell_specs(packet, config)
    recomputed = RUNTIME.recompute_aggregate(
        packet_path=config.packet_path,
        expected_packet_sha256=config.expected_packet_sha256,
        receipt_path=config.receipt_path,
        expected_receipt_sha256=config.expected_receipt_sha256,
        review_record=config.review_record,
        cell_paths=[spec.output for spec in specs],
    )
    aggregate_path = (REPO / RUNTIME.AGGREGATE_PATH).resolve()
    if _load_json(aggregate_path) != recomputed:
        raise TrainingSupervisorRefused(
            "terminal training aggregate full recomputation drift")
    jobs = terminal_job_evidence(packet, config)
    expected_final = final_payload(
        config=config, packet=packet, job_evidence=jobs)
    if _load_json(final_path) != expected_final:
        raise TrainingSupervisorRefused("training supervisor final drift")
    value = {
        "verified": True,
        "run_id": CTRL.RUN_ID,
        "final_sha256": sha256_file(final_path),
        "aggregate_sha256": sha256_file(aggregate_path),
        "decision": recomputed["decision"],
        "report_open_authorized": False,
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
    root.add_argument("--training-receipt", required=True)
    root.add_argument("--expected-training-receipt-sha256", required=True)
    root.add_argument(
        "--heartbeat-seconds", type=float,
        default=float(HEARTBEAT_SECONDS))
    return root


def main() -> int:
    args = parser().parse_args()
    if args.heartbeat_seconds != HEARTBEAT_SECONDS:
        raise TrainingSupervisorRefused(
            f"heartbeat must equal the reviewed {HEARTBEAT_SECONDS} seconds")
    config = Config(
        expected_git=args.expected_git,
        packet_path=Path(args.controller_packet).resolve(),
        expected_packet_sha256=args.expected_controller_packet_sha256,
        review_record=Path(args.controller_review_record).resolve(),
        receipt_path=Path(args.training_receipt).resolve(),
        expected_receipt_sha256=args.expected_training_receipt_sha256,
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
    except TrainingSupervisorInterrupted as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (TrainingSupervisorRefused, RUNTIME.TrainingRuntimeRefused,
            CTRL.TrainingControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
