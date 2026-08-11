#!/usr/bin/env python3
"""Own the reviewed expanded Stage-C label run through aggregation.

The expanded controller schedules sixteen one-shot label shards and permits at
most eight concurrent workers.  This supervisor runs them in two waves,
publishes durable progress every 30 seconds, owns every child across
SIGHUP/SIGINT/SIGTERM, stops siblings on any failure, and recomputes the
terminal aggregate before publication of its own final record.

It cannot retry a consumed shard, train a model, open REPORT, claim strength,
promote, or deploy.
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

import teacher_stage_c_expanded_label_runtime as ENTRY  # noqa: E402
import teacher_stage_c_expansion_controller as CTRL  # noqa: E402


BASE = ENTRY.BASE
SCHEMA = "teacher-stage-c-expanded-label-supervisor-v1"
EXIT_SCHEMA = "teacher-stage-c-expanded-label-supervisor-exit-v1"
FINAL_SCHEMA = "teacher-stage-c-expanded-label-supervisor-final-v1"
HEARTBEAT_SECONDS = 30
MAX_WORKERS = CTRL.MAX_CONCURRENT_SHARDS
HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
PROGRESS_PATH = Path(f"server/runs/logs/{CTRL.RUN_ID}/supervisor.jsonl")
FINAL_PATH = Path(f"server/runs/logs/{CTRL.RUN_ID}/supervisor-final.json")
LOG_DIRECTORY = Path(f"server/runs/logs/{CTRL.RUN_ID}/supervisor-logs")
EXIT_DIRECTORY = Path(f"server/runs/logs/{CTRL.RUN_ID}/supervisor-exits")


class ExpandedSupervisorRefused(RuntimeError):
    """A reviewed supervisor identity, child or terminal result drifted."""


class ExpandedSupervisorInterrupted(BaseException):
    def __init__(self, signum: int):
        self.signum = int(signum)
        self.signal_name = signal.Signals(signum).name
        super().__init__(
            f"expanded label supervisor received {self.signal_name}")


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


def canonical_json(value: object) -> bytes:
    return CTRL.canonical_json(value)


def sha256_file(path: Path) -> str:
    return CTRL.sha256_file(path)


def partial(path: Path) -> Path:
    return Path(str(path) + ".partial")


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _load_json(path: Path) -> dict:
    if not is_regular_unlinked(path) or lexists(partial(path)):
        raise ExpandedSupervisorRefused(
            f"expanded terminal JSON unavailable: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ExpandedSupervisorRefused(
            f"cannot reopen expanded JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExpandedSupervisorRefused("expanded JSON root is not an object")
    return value


def _publish_partial(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise ExpandedSupervisorRefused(
            f"refusing to overwrite {destination}") from exc
    source.unlink()


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_partial = partial(path)
    if lexists(path) or lexists(target_partial):
        raise ExpandedSupervisorRefused(
            f"refusing existing supervisor artifact {path}")
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
            raise ExpandedSupervisorRefused(
                "expanded progress already exists") from exc
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


class SignalOwner:
    def __init__(self) -> None:
        self.signals = tuple(getattr(signal, name) for name in HANDLED_SIGNALS)
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

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
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
            raise ExpandedSupervisorInterrupted(self.interrupted_by)

    def register(self, job: RunningJob) -> None:
        if job in self.jobs:
            raise ExpandedSupervisorRefused("duplicate child ownership")
        self.jobs.append(job)

    def unregister(self, job: RunningJob) -> None:
        try:
            self.jobs.remove(job)
        except ValueError as exc:
            raise ExpandedSupervisorRefused("lost child ownership") from exc

    @contextlib.contextmanager
    def deferred_until_registered(self):
        if self.spawning:
            raise ExpandedSupervisorRefused("nested child spawn")
        self.spawning = True
        try:
            yield
        finally:
            self.spawning = False
            if self.interrupted_by is not None:
                raise ExpandedSupervisorInterrupted(self.interrupted_by)


def _substitutions(config: Config) -> dict[str, str]:
    return {
        "{python}": sys.executable,
        "{git}": config.expected_git,
        "{packet_sha256}": config.expected_packet_sha256,
        "{controller_review_record}": str(config.review_record),
        "{receipt_sha256}": config.expected_receipt_sha256,
    }


def expand_command(template: Sequence[object], config: Config) -> tuple[str, ...]:
    if not isinstance(template, (list, tuple)) or not template:
        raise ExpandedSupervisorRefused("expanded command template missing")
    substitutions = _substitutions(config)
    values = []
    for raw in template:
        if not isinstance(raw, str) or not raw:
            raise ExpandedSupervisorRefused("expanded command token drift")
        value = substitutions.get(raw, raw)
        if "{" in value or "}" in value:
            raise ExpandedSupervisorRefused(
                f"unresolved expanded command token: {value}")
        values.append(value)
    return tuple(values)


def shard_specs(packet: Mapping[str, object], config: Config) -> list[JobSpec]:
    commands = packet.get("commands", {}).get("run_shards")
    schedule = packet.get("schedule", {}).get("shards")
    if (not isinstance(commands, list) or not isinstance(schedule, list)
            or len(commands) != CTRL.LABEL_SHARDS
            or len(schedule) != CTRL.LABEL_SHARDS):
        raise ExpandedSupervisorRefused("expanded shard command drift")
    result = []
    for index, (entry, shard) in enumerate(
            zip(commands, schedule, strict=True)):
        if (not isinstance(entry, dict) or entry.get("index") != index
                or entry.get("split") != shard.get("split")
                or shard.get("index") != index):
            raise ExpandedSupervisorRefused("expanded shard order drift")
        output = (REPO / packet["result_contract"]["shards"][index]).resolve()
        result.append(JobSpec(
            name=f"shard-{index:02d}", index=index,
            argv=expand_command(entry.get("command"), config), output=output,
            log_final=(REPO / LOG_DIRECTORY /
                       f"shard-{index:02d}.log").resolve(),
            exit_final=(REPO / EXIT_DIRECTORY /
                        f"shard-{index:02d}.json").resolve(),
        ))
    return result


def aggregate_spec(packet: Mapping[str, object], config: Config) -> JobSpec:
    return JobSpec(
        name="aggregate", index=None,
        argv=expand_command(packet.get("commands", {}).get("aggregate"),
                            config),
        output=(REPO / packet["result_contract"]["aggregate"]).resolve(),
        log_final=(REPO / LOG_DIRECTORY / "aggregate.log").resolve(),
        exit_final=(REPO / EXIT_DIRECTORY / "aggregate.json").resolve(),
    )


def _validated_parents(config: Config) -> tuple[dict, dict, dict]:
    if (_git("rev-parse", "HEAD") != config.expected_git
            or _git("status", "--porcelain", "--untracked-files=all")):
        raise ExpandedSupervisorRefused("expanded supervisor Git drift")
    try:
        packet = BASE._controller_packet(
            config.packet_path, config.expected_packet_sha256)
        state_set, _verification = BASE._validated_parents(
            packet, config.review_record)
        receipt = BASE._receipt(
            config.receipt_path, config.expected_receipt_sha256,
            packet, config.expected_packet_sha256,
            config.review_record, config.review_record)
    except (BASE.LabelRefused, CTRL.ExpansionControllerRefused) as exc:
        raise ExpandedSupervisorRefused(
            f"expanded parent refused: {exc}") from exc
    schedule = packet.get("schedule", {})
    if (schedule.get("shard_count") != CTRL.LABEL_SHARDS
            or schedule.get("max_concurrent_shards") != MAX_WORKERS
            or config.heartbeat_seconds != HEARTBEAT_SECONDS):
        raise ExpandedSupervisorRefused(
            "expanded supervisor schedule/runtime drift")
    return packet, state_set, receipt


def _owned_targets(packet: Mapping[str, object], config: Config) \
        -> Iterable[Path]:
    for path in ((REPO / PROGRESS_PATH).resolve(),
                 (REPO / FINAL_PATH).resolve()):
        yield path
        yield partial(path)
    for spec in [*shard_specs(packet, config), aggregate_spec(packet, config)]:
        for path in (spec.output, spec.log_final, spec.exit_final):
            yield path
            yield partial(path)


def preflight_problems(packet: Mapping[str, object], config: Config) \
        -> list[str]:
    problems = [f"expanded output collision {path}"
                for path in _owned_targets(packet, config) if lexists(path)]
    for index in range(CTRL.LABEL_SHARDS):
        slot = (REPO / CTRL.shard_admission_logical_path(index)).resolve()
        if lexists(slot) or lexists(partial(slot)):
            problems.append(f"expanded shard slot consumed {slot}")
    try:
        rows = subprocess.run(
            ["ps", "-axo", "command="], check=True,
            capture_output=True, text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"expanded process inspection failed: {exc}")
    else:
        if any("teacher_stage_c_expanded_label_runtime.py run-shard" in row
               or "teacher_stage_c_expanded_label_runtime.py aggregate" in row
               for row in rows):
            problems.append("an expanded label worker already exists")
    return sorted(set(problems))


def _start_job(spec: JobSpec, owner: SignalOwner) -> RunningJob:
    spec.log_final.parent.mkdir(parents=True, exist_ok=True)
    log_partial = partial(spec.log_final)
    try:
        handle = log_partial.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ExpandedSupervisorRefused("expanded child log exists") from exc
    process = None
    registered = False
    try:
        with owner.deferred_until_registered():
            process = subprocess.Popen(
                spec.argv, cwd=REPO,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdout=handle, stderr=subprocess.STDOUT, text=True)
            job = RunningJob(
                spec=spec, process=process, log_handle=handle,
                log_partial=log_partial, started_ns=time.time_ns())
            owner.register(job)
            registered = True
        return job
    except BaseException:
        if process is not None and not registered and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
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
            "\0".join(job.spec.argv).encode()).hexdigest(),
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
    _write_json_exclusive(job.spec.exit_final,
                          _exit_payload(job, returncode))
    job.finished = True


def _stop_jobs(jobs: Iterable[RunningJob]) -> None:
    values = list(jobs)
    live = [job for job in values if job.process.poll() is None]
    for job in live:
        job.process.terminate()
    deadline = time.monotonic() + 10
    for job in live:
        try:
            job.process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait()
    for job in values:
        code = job.process.poll()
        if code is not None and not job.finished:
            try:
                _finish_job(job, int(code))
            except Exception:
                pass


def _latest_progress(job: RunningJob) -> dict[str, object] | None:
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
        if isinstance(value, dict) and value.get("status") == "LABELING":
            return {
                "job": job.spec.name,
                "states_complete": value.get("states_complete"),
                "states_total": value.get("states_total"),
                "refusals": value.get("refusals"),
            }
    return None


def _validate_shard(spec: JobSpec, *, packet: Mapping[str, object],
                    state_set: Mapping[str, object], config: Config,
                    net: object) -> None:
    try:
        BASE.validate_shard(
            _load_json(spec.output), packet=packet,
            receipt_sha256=config.expected_receipt_sha256,
            state_set=state_set, index=int(spec.index), net=net)
    except (BASE.LabelRefused, CTRL.ExpansionControllerRefused) as exc:
        raise ExpandedSupervisorRefused(
            f"expanded {spec.name} validation refused: {exc}") from exc


def _run_shards(packet: Mapping[str, object], state_set: Mapping[str, object],
                config: Config, progress: Progress,
                owner: SignalOwner) -> list[JobSpec]:
    queued = list(shard_specs(packet, config))
    live: list[RunningJob] = []
    completed: list[JobSpec] = []
    net = BASE._load_v11()
    last_heartbeat = time.monotonic()
    try:
        while queued or live:
            while queued and len(live) < MAX_WORKERS:
                spec = queued.pop(0)
                job = _start_job(spec, owner)
                live.append(job)
                progress.event(
                    "shard", "started", job=spec.name,
                    index=spec.index, pid=job.process.pid,
                    queued=len(queued), live=len(live),
                    completed=len(completed))
            for job in list(live):
                code = job.process.poll()
                if code is None:
                    continue
                _finish_job(job, int(code))
                owner.unregister(job)
                live.remove(job)
                progress.event(
                    "shard", "exit", job=job.spec.name,
                    index=job.spec.index, pid=job.process.pid,
                    returncode=int(code), queued=len(queued),
                    live=len(live), completed=len(completed))
                if code != 0:
                    raise ExpandedSupervisorRefused(
                        f"expanded {job.spec.name} exited {code}")
                _validate_shard(
                    job.spec, packet=packet, state_set=state_set,
                    config=config, net=net)
                completed.append(job.spec)
            now = time.monotonic()
            if (queued or live) and now - last_heartbeat >= \
                    config.heartbeat_seconds:
                progress.event(
                    "shards", "running", queued=len(queued),
                    live=len(live), completed=len(completed),
                    workers=[value for value in
                             (_latest_progress(job) for job in live)
                             if value is not None])
                last_heartbeat = now
            if queued or live:
                time.sleep(min(0.25, config.heartbeat_seconds))
    except BaseException:
        _stop_jobs(live)
        raise
    if len(completed) != CTRL.LABEL_SHARDS:
        raise ExpandedSupervisorRefused("expanded shard completion drift")
    return sorted(completed, key=lambda spec: int(spec.index))


def _recompute_aggregate(packet: Mapping[str, object],
                         state_set: Mapping[str, object],
                         config: Config) -> dict:
    paths = [(REPO / logical).resolve()
             for logical in packet["result_contract"]["shards"]]
    try:
        expected, _shards = BASE.recompute_aggregate_payload(
            packet=packet,
            expected_packet_sha256=config.expected_packet_sha256,
            expected_receipt_sha256=config.expected_receipt_sha256,
            state_set=state_set, shard_paths=paths)
    except (BASE.LabelRefused, CTRL.ExpansionControllerRefused) as exc:
        raise ExpandedSupervisorRefused(
            f"expanded aggregate replay refused: {exc}") from exc
    actual = _load_json(
        (REPO / packet["result_contract"]["aggregate"]).resolve())
    if actual != expected:
        raise ExpandedSupervisorRefused(
            "expanded aggregate full recomputation drift")
    return actual


def _run_aggregate(packet: Mapping[str, object],
                   state_set: Mapping[str, object], config: Config,
                   progress: Progress, owner: SignalOwner) -> JobSpec:
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
        owner.unregister(job)
    except BaseException:
        _stop_jobs([job])
        raise
    progress.event("aggregate", "exit", pid=job.process.pid,
                   returncode=code)
    if code != 0:
        raise ExpandedSupervisorRefused(
            f"expanded aggregate exited {code}")
    _recompute_aggregate(packet, state_set, config)
    return spec


def _expected_exit(spec: JobSpec, value: Mapping[str, object]) -> bool:
    return (value.get("schema") == EXIT_SCHEMA
            and value.get("run_id") == CTRL.RUN_ID
            and value.get("job") == spec.name
            and value.get("index") == spec.index
            and isinstance(value.get("pid"), int)
            and isinstance(value.get("started_ns"), int)
            and isinstance(value.get("finished_ns"), int)
            and value["finished_ns"] >= value["started_ns"]
            and value.get("returncode") == 0
            and value.get("argv_sha256") == hashlib.sha256(
                "\0".join(spec.argv).encode()).hexdigest()
            and value.get("output") == str(spec.output.relative_to(REPO))
            and value.get("retry_authorized") is False)


def terminal_job_evidence(packet: Mapping[str, object], config: Config) \
        -> list[dict]:
    result = []
    for spec in [*shard_specs(packet, config), aggregate_spec(packet, config)]:
        for path in (spec.output, spec.log_final, spec.exit_final):
            if not is_regular_unlinked(path) or lexists(partial(path)):
                raise ExpandedSupervisorRefused(
                    f"terminal expanded artifact missing: {path}")
        if not _expected_exit(spec, _load_json(spec.exit_final)):
            raise ExpandedSupervisorRefused(
                f"terminal expanded exit drift: {spec.name}")
        result.append({
            "job": spec.name,
            "index": spec.index,
            "output_sha256": sha256_file(spec.output),
            "log_sha256": sha256_file(spec.log_final),
            "exit_sha256": sha256_file(spec.exit_final),
        })
    return result


def final_payload(*, packet: Mapping[str, object], config: Config,
                  jobs: Sequence[Mapping[str, object]],
                  aggregate: Mapping[str, object]) -> dict:
    value = {
        "schema": FINAL_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": config.expected_git,
        "controller_packet_sha256": config.expected_packet_sha256,
        "label_receipt_sha256": config.expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "label_shards_complete": CTRL.LABEL_SHARDS,
        "max_concurrent_shards": MAX_WORKERS,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "progress_sha256": sha256_file((REPO / PROGRESS_PATH).resolve()),
        "jobs": list(jobs),
        "aggregate_external_sha256": sha256_file(
            (REPO / packet["result_contract"]["aggregate"]).resolve()),
        "aggregate_internal_sha256": aggregate["aggregate_sha256"],
        "aggregate_status": aggregate["status"],
        "model_packet_review_authorized": aggregate.get(
            "model_packet_review_authorized") is True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_authorized": False,
    }
    value["final_sha256"] = CTRL.self_hash(value, "final_sha256")
    return value


def launch(config: Config) -> dict:
    packet, state_set, _receipt = _validated_parents(config)
    problems = preflight_problems(packet, config)
    if problems:
        raise ExpandedSupervisorRefused("; ".join(problems))
    progress = Progress()
    try:
        with SignalOwner() as owner:
            progress.event(
                "launch", "started", label_shards=CTRL.LABEL_SHARDS,
                max_workers=MAX_WORKERS,
                packet_sha256=config.expected_packet_sha256,
                receipt_sha256=config.expected_receipt_sha256)
            _run_shards(packet, state_set, config, progress, owner)
            _run_aggregate(packet, state_set, config, progress, owner)
            progress.event("launch", "complete",
                           label_shards=CTRL.LABEL_SHARDS)
            progress.publish()
            aggregate = _recompute_aggregate(packet, state_set, config)
            jobs = terminal_job_evidence(packet, config)
            value = final_payload(
                packet=packet, config=config, jobs=jobs,
                aggregate=aggregate)
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
    packet, state_set, _receipt = _validated_parents(config)
    progress_path = (REPO / PROGRESS_PATH).resolve()
    final_path = (REPO / FINAL_PATH).resolve()
    for path in (progress_path, final_path):
        if not is_regular_unlinked(path) or lexists(partial(path)):
            raise ExpandedSupervisorRefused(
                f"terminal expanded supervisor artifact missing: {path}")
    aggregate = _recompute_aggregate(packet, state_set, config)
    jobs = terminal_job_evidence(packet, config)
    expected = final_payload(
        packet=packet, config=config, jobs=jobs, aggregate=aggregate)
    if _load_json(final_path) != expected:
        raise ExpandedSupervisorRefused(
            "expanded supervisor final recomputation drift")
    value = {
        "verified": True,
        "run_id": CTRL.RUN_ID,
        "final_sha256": sha256_file(final_path),
        "aggregate_sha256": sha256_file(
            (REPO / packet["result_contract"]["aggregate"]).resolve()),
        "aggregate_status": aggregate["status"],
        "model_packet_review_authorized": aggregate.get(
            "model_packet_review_authorized") is True,
        "training_authorized": False,
        "report_open_authorized": False,
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
    root.add_argument("--label-receipt", required=True)
    root.add_argument("--expected-label-receipt-sha256", required=True)
    root.add_argument("--heartbeat-seconds", type=float,
                      default=float(HEARTBEAT_SECONDS))
    return root


def main() -> int:
    args = parser().parse_args()
    if args.heartbeat_seconds != HEARTBEAT_SECONDS:
        raise ExpandedSupervisorRefused(
            f"heartbeat must equal {HEARTBEAT_SECONDS} seconds")
    config = Config(
        expected_git=args.expected_git,
        packet_path=Path(args.controller_packet).resolve(),
        expected_packet_sha256=args.expected_controller_packet_sha256,
        review_record=Path(args.controller_review_record).resolve(),
        receipt_path=Path(args.label_receipt).resolve(),
        expected_receipt_sha256=args.expected_label_receipt_sha256,
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
    except ExpandedSupervisorInterrupted as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (ExpandedSupervisorRefused, BASE.LabelRefused,
            CTRL.ExpansionControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
