#!/usr/bin/env python3
"""Fail-fast orchestration with exact process recovery for BELIEF V2/R5."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("BELIEF V2 supervisor requires Python -P -B")

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import time
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
SOURCE_ROOT = REPO / "server" / "shengji"
PROGRESS_PREFIX = "BELIEF_V2_PROGRESS "
STATUS_SCHEMA = "belief-v1-v2-ops-status-v4"
START_SCHEMA = "belief-v1-v2-ops-start-v4"
RESUME_SCHEMA = "belief-v1-v2-ops-resume-v2"
NS_PER_SECOND = 1_000_000_000


def _refuse_import_shadows() -> None:
    for path in SOURCE_ROOT.rglob("*"):
        if path.name == "__pycache__" or path.suffix.lower() in {
                ".pyc", ".pyo"}:
            raise RuntimeError("BELIEF V2 supervisor refuses bytecode shadows")


_refuse_import_shadows()

from shengji.rl.belief_artifacts import stable_read_bytes  # noqa: E402
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.belief_v2_execution_identity import (  # noqa: E402
    _boot_identity,
)
from shengji.rl.belief_v2_freeze import (  # noqa: E402
    execution_freeze_from_bytes,
)
from shengji.rl.belief_v2_supervisor_plan import (  # noqa: E402
    SUPERVISOR_WALL_CAP_SECONDS,
    V2SupervisorPlanV1,
    V2SupervisorTaskV1,
    build_supervisor_plan,
)


SUPERVISOR_WALL_CAP_NANOSECONDS = (
    SUPERVISOR_WALL_CAP_SECONDS * NS_PER_SECOND)


class BeliefV2SupervisorError(RuntimeError):
    """The immutable task plan or one fail-fast worker refused."""


class Supervisor:
    def __init__(
            self, *, plan: V2SupervisorPlanV1, root: Path, ops: Path,
            python: Path, worker: Path, boot_identity: str,
            resume: bool = False,
            monotonic_ns=time.monotonic_ns) -> None:
        if type(boot_identity) is not str or len(boot_identity) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in boot_identity) \
                or not callable(monotonic_ns):
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor runtime contract drift")
        self.plan = plan
        self.root = root
        self.ops = ops
        self.python = python
        self.worker = worker
        self.logs = ops / "logs"
        self.status_path = ops / "status.json"
        self.started_path = ops / "started.json"
        self.active: dict[str, subprocess.Popen[str]] = {}
        self.reader_threads: dict[str, threading.Thread] = {}
        self.stdout_files: dict[str, Any] = {}
        self.stderr_files: dict[str, Any] = {}
        self.stop_requested = False
        self.recover_existing = resume
        self.boot_identity = boot_identity
        self.monotonic_ns = monotonic_ns
        self.started_monotonic_nanoseconds: int | None = None
        self.hard_deadline_monotonic_nanoseconds: int | None = None
        self.resume_count = 0
        self.lock_descriptor: int | None = None
        self.lock = threading.RLock()
        self.state: dict[str, Any] = {
            "schema": STATUS_SCHEMA,
            "state": "starting",
            "current_stage": "supervisor-start",
            "stage_index": 0,
            "stage_count": len(plan.stages),
            "completed_tasks": 0,
            "completed_task_names": [],
            "total_tasks": sum(len(stage.tasks) for stage in plan.stages),
            "running_tasks": [],
            "running_processes": {},
            "launching_task": None,
            "latest_worker_progress": {},
            "task_weighted_percent_basis_points": 0,
            "outcome_blind": True,
            "retry_authorized": False,
            "resume_authorized": True,
            "resume_count": 0,
            "resume_mode": False,
            "boot_identity": boot_identity,
            "supervisor_wall_cap_nanoseconds": (
                SUPERVISOR_WALL_CAP_NANOSECONDS),
            "hard_deadline_monotonic_nanoseconds": None,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }
        self.environment = {
            **os.environ,
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SHENGJI_FAST": "1",
            "SHENGJI_REQUIRE_VOIDS": "1",
            "VIRTUAL_ENV": str(python.parent.parent),
        }
        self.environment.pop("PYTHONPATH", None)

    def _bind_supervisor_deadline(self, started: int) -> None:
        if type(started) is not int or started <= 0:
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor deadline identity drift")
        self.started_monotonic_nanoseconds = started
        self.hard_deadline_monotonic_nanoseconds = (
            started + SUPERVISOR_WALL_CAP_NANOSECONDS)
        self.state.update({
            "boot_identity": self.boot_identity,
            "supervisor_wall_cap_nanoseconds": (
                SUPERVISOR_WALL_CAP_NANOSECONDS),
            "hard_deadline_monotonic_nanoseconds": (
                self.hard_deadline_monotonic_nanoseconds),
        })

    def _check_supervisor_deadline(self) -> None:
        started = self.started_monotonic_nanoseconds
        hard = self.hard_deadline_monotonic_nanoseconds
        observed = self.monotonic_ns()
        if type(observed) is not int or started is None or hard is None \
                or observed < started:
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor monotonic deadline drift")
        if observed >= hard:
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor absolute deadline exhausted")

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        partial = path.with_name(
            f"{path.name}.partial-{os.getpid()}-{threading.get_ident()}")
        raw = canonical_json_bytes(value)
        descriptor = os.open(
            partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(partial, path)

    def _update_status(self, **changes: Any) -> None:
        with self.lock:
            self.state.update(changes)
            progress_equivalents = 0
            for name in self.state["running_tasks"]:
                row = self.state["latest_worker_progress"].get(name)
                if row is not None:
                    progress_equivalents += row["percent_basis_points"]
            numerator = (self.state["completed_tasks"] * 10_000
                         + progress_equivalents)
            self.state["task_weighted_percent_basis_points"] = (
                numerator // self.state["total_tasks"])
            self.state["updated_unix_seconds"] = int(time.time())
            self._atomic_json(self.status_path, self.state)

    def _progress_reader(
            self, name: str, pipe: Any, log_handle: Any) -> None:
        for line in iter(pipe.readline, ""):
            log_handle.write(line)
            log_handle.flush()
            if not line.startswith(PROGRESS_PREFIX):
                continue
            try:
                row = json.loads(line.removeprefix(PROGRESS_PREFIX))
                if row.get("outcome_blind") is not True \
                        or type(row.get("percent_basis_points")) is not int \
                        or not 0 <= row["percent_basis_points"] <= 10_000:
                    continue
                with self.lock:
                    self.state["latest_worker_progress"][name] = row
                self._update_status()
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

    def _worker_command(self, task: V2SupervisorTaskV1) -> list[str]:
        recovery = ["--recover-existing"] if self.recover_existing else []
        completed = (["--require-existing-final"]
                     if self.recover_existing and task.name in self.state[
                         "completed_task_names"] else [])
        return [str(self.python), "-P", "-B", str(self.worker),
                *task.arguments, "--root", str(self.root),
                *recovery, *completed]

    def _start_task(self, task: V2SupervisorTaskV1) -> None:
        self._check_supervisor_deadline()
        suffix = ("" if self.resume_count == 0
                  else f".resume-{self.resume_count:02d}")
        self._update_status(launching_task=task.name)
        out = (self.logs / f"{task.name}{suffix}.stdout.log").open(
            "x", encoding="utf-8")
        err = (self.logs / f"{task.name}{suffix}.stderr.log").open(
            "x", encoding="utf-8")
        process = subprocess.Popen(
            self._worker_command(task), env=self.environment,
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE,
            text=True, bufsize=1, start_new_session=True)
        if process.stderr is None:
            raise BeliefV2SupervisorError(
                "BELIEF V2 worker stderr pipe is absent")
        self.active[task.name] = process
        self.stdout_files[task.name] = out
        self.stderr_files[task.name] = err
        thread = threading.Thread(
            target=self._progress_reader,
            args=(task.name, process.stderr, err),
            name=f"progress-{task.name}", daemon=True)
        self.reader_threads[task.name] = thread
        thread.start()
        self._update_status(
            launching_task=None,
            running_tasks=sorted(self.active),
            running_processes={
                name: child.pid for name, child in self.active.items()})

    def _close_task(self, name: str) -> None:
        self.reader_threads[name].join(timeout=5)
        self.stdout_files[name].close()
        self.stderr_files[name].close()
        self.reader_threads.pop(name, None)
        self.stdout_files.pop(name, None)
        self.stderr_files.pop(name, None)
        self.active.pop(name, None)

    def _terminate_active(self) -> None:
        for process in tuple(self.active.values()):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(
                process.poll() is None for process in self.active.values()):
            time.sleep(0.2)
        for process in tuple(self.active.values()):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def request_stop(self, signum: int) -> None:
        self.stop_requested = True
        self._update_status(
            state="interrupted", failure=f"signal-{signum}")
        self._terminate_active()

    def _acquire_lock(self) -> None:
        path = self.ops / "supervisor.lock"
        try:
            descriptor = os.open(
                path, os.O_RDWR | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError as exc:
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor lock open refused") from exc
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 \
                or info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(descriptor)
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor lock identity drift")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor is already active") from exc
        self.lock_descriptor = descriptor

    def _release_lock(self) -> None:
        if self.lock_descriptor is not None:
            fcntl.flock(self.lock_descriptor, fcntl.LOCK_UN)
            os.close(self.lock_descriptor)
            self.lock_descriptor = None

    def _prepare_resume(self) -> None:
        if not self.ops.is_dir() or self.ops.is_symlink() \
                or not self.logs.is_dir() or self.logs.is_symlink():
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor recovery ops shape drift")
        started_raw = self.started_path.read_bytes()
        status_raw = self.status_path.read_bytes()
        started = _strict_json(self.started_path)
        prior = _strict_json(self.status_path)
        expected_summary = hashlib.sha256(
            self.plan.canonical_summary_bytes()).hexdigest()
        expected_execution = self.plan.execution_sha256()
        if set(started) != {
                "schema", "started_unix_seconds",
                "started_monotonic_nanoseconds", "pid",
                "plan_summary_sha256", "execution_plan_sha256",
                "boot_identity", "supervisor_wall_cap_nanoseconds",
                "hard_deadline_monotonic_nanoseconds",
                "retry_authorized", "resume_authorized"} \
                or started["schema"] != START_SCHEMA \
                or started["plan_summary_sha256"] != expected_summary \
                or started["execution_plan_sha256"] != expected_execution \
                or started["boot_identity"] != self.boot_identity \
                or started["supervisor_wall_cap_nanoseconds"] \
                != SUPERVISOR_WALL_CAP_NANOSECONDS \
                or started["retry_authorized"] is not False \
                or started["resume_authorized"] is not True \
                or type(started["started_monotonic_nanoseconds"]) is not int \
                or started["started_monotonic_nanoseconds"] <= 0 \
                or started["hard_deadline_monotonic_nanoseconds"] \
                != started["started_monotonic_nanoseconds"] \
                + SUPERVISOR_WALL_CAP_NANOSECONDS:
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor recovery start binding drift")
        self._bind_supervisor_deadline(
            started["started_monotonic_nanoseconds"])
        self._check_supervisor_deadline()
        all_names = {
            task.name for stage in self.plan.stages for task in stage.tasks}
        completed = prior.get("completed_task_names")
        running = prior.get("running_tasks")
        processes = prior.get("running_processes")
        if prior.get("schema") != STATUS_SCHEMA \
                or prior.get("state") not in {
                    "running", "interrupted", "recovering"} \
                or prior.get("outcome_blind") is not True \
                or prior.get("retry_authorized") is not False \
                or prior.get("resume_authorized") is not True \
                or prior.get("boot_identity") != self.boot_identity \
                or prior.get("supervisor_wall_cap_nanoseconds") \
                != SUPERVISOR_WALL_CAP_NANOSECONDS \
                or prior.get("hard_deadline_monotonic_nanoseconds") \
                != self.hard_deadline_monotonic_nanoseconds \
                or prior.get("strength_claim_authorized") is not False \
                or prior.get("deployment_authorized") is not False \
                or type(prior.get("resume_count")) is not int \
                or prior["resume_count"] < 0 \
                or type(completed) is not list \
                or len(completed) != len(set(completed)) \
                or completed != sorted(completed) \
                or not set(completed).issubset(all_names) \
                or prior.get("completed_tasks") != len(completed) \
                or prior.get("total_tasks") != len(all_names) \
                or prior.get("launching_task") is not None \
                or type(running) is not list \
                or running != sorted(running) \
                or len(running) != len(set(running)) \
                or type(processes) is not dict \
                or not set(processes).issubset(all_names) \
                or set(running) != set(processes) \
                or set(completed) & set(running) \
                or len(processes.values()) != len(set(processes.values())) \
                or any(type(pid) is not int or pid <= 0
                       for pid in processes.values()):
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor recovery status drift")
        for pid in processes.values():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError as exc:
                raise BeliefV2SupervisorError(
                    "BELIEF V2 recovery worker identity unavailable") from exc
            raise BeliefV2SupervisorError(
                "BELIEF V2 recovery worker is still active")
        self.resume_count = prior["resume_count"] + 1
        receipt_path = self.ops / f"resume-{self.resume_count:02d}.json"
        receipt = {
            "schema": RESUME_SCHEMA,
            "resume_count": self.resume_count,
            "pid": os.getpid(),
            "started_sha256": hashlib.sha256(started_raw).hexdigest(),
            "prior_status_sha256": hashlib.sha256(status_raw).hexdigest(),
            "plan_summary_sha256": expected_summary,
            "execution_plan_sha256": expected_execution,
            "original_started_monotonic_nanoseconds": (
                started["started_monotonic_nanoseconds"]),
            "boot_identity": self.boot_identity,
            "supervisor_wall_cap_nanoseconds": (
                SUPERVISOR_WALL_CAP_NANOSECONDS),
            "hard_deadline_monotonic_nanoseconds": (
                self.hard_deadline_monotonic_nanoseconds),
            "completed_task_names_before_recovery": sorted(completed),
            "test_split_open_authorized": False,
            "retry_authorized": False,
            "resume_authorized": True,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }
        if receipt_path.is_symlink():
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor recovery receipt identity drift")
        if receipt_path.exists():
            existing = _strict_json(receipt_path)
            # A process may die after the receipt's durable rename and before
            # status.json advances.  Reusing only the byte-exact same intent
            # (apart from the observational writer PID) closes that
            # availability window without creating another scientific
            # attempt or silently overwriting a receipt.
            existing_intent = dict(existing)
            receipt_intent = dict(receipt)
            existing_pid = existing_intent.pop("pid", None)
            receipt_intent.pop("pid")
            if type(existing_pid) is not int or existing_pid <= 0 \
                    or existing_intent != receipt_intent:
                raise BeliefV2SupervisorError(
                    "BELIEF V2 supervisor recovery receipt slot is occupied")
        else:
            self._atomic_json(receipt_path, receipt)
        self.state = prior
        self.state.update({
            "state": "recovering",
            "current_stage": "supervisor-recovery",
            "stage_index": 0,
            "running_tasks": [],
            "running_processes": {},
            "launching_task": None,
            "latest_worker_progress": {},
            "resume_count": self.resume_count,
            "resume_mode": True,
        })
        self._update_status()

    def _run_stage(self, stage_index: int) -> None:
        self._check_supervisor_deadline()
        stage = self.plan.stages[stage_index - 1]
        pending = list(stage.tasks)
        completed = 0
        self._update_status(
            state="running", current_stage=stage.name,
            stage_index=stage_index, stage_total_tasks=len(stage.tasks),
            stage_completed_tasks=0, running_tasks=[])
        while pending or self.active:
            self._check_supervisor_deadline()
            if self.stop_requested:
                raise BeliefV2SupervisorError("BELIEF V2 supervisor stopped")
            while pending and len(self.active) < stage.concurrency:
                self._start_task(pending.pop(0))
            self._update_status(running_tasks=sorted(self.active))
            finished = [name for name, process in self.active.items()
                        if process.poll() is not None]
            if not finished:
                time.sleep(1)
                continue
            for name in finished:
                returncode = self.active[name].returncode
                self._close_task(name)
                if returncode != 0:
                    self._update_status(
                        state="failed", failure_task=name,
                        failure_returncode=returncode,
                        running_tasks=sorted(self.active),
                        running_processes={
                            task_name: child.pid
                            for task_name, child in self.active.items()})
                    self._terminate_active()
                    raise BeliefV2SupervisorError(
                        f"BELIEF V2 task {name} failed with {returncode}")
                completed += 1
                completed_names = list(self.state["completed_task_names"])
                if name not in completed_names:
                    completed_names.append(name)
                self._update_status(
                    completed_tasks=len(completed_names),
                    completed_task_names=sorted(completed_names),
                    stage_completed_tasks=completed,
                    running_tasks=sorted(self.active),
                    running_processes={
                        task_name: child.pid
                        for task_name, child in self.active.items()})

    def run(self) -> None:
        try:
            if self.recover_existing:
                if not self.ops.exists() or self.ops.is_symlink():
                    raise BeliefV2SupervisorError(
                        "BELIEF V2 supervisor recovery ops slot is absent")
                self._acquire_lock()
                self._prepare_resume()
            else:
                if self.ops.exists() or self.ops.is_symlink():
                    raise BeliefV2SupervisorError(
                        "BELIEF V2 supervisor ops slot is occupied")
                self.ops.mkdir(mode=0o700, parents=True)
                self.logs.mkdir(mode=0o700)
                self._acquire_lock()
                started_monotonic = self.monotonic_ns()
                self._bind_supervisor_deadline(started_monotonic)
                self._check_supervisor_deadline()
                self._atomic_json(self.started_path, {
                    "schema": START_SCHEMA,
                    "started_unix_seconds": int(time.time()),
                    "started_monotonic_nanoseconds": started_monotonic,
                    "pid": os.getpid(),
                    "plan_summary_sha256": hashlib.sha256(
                        self.plan.canonical_summary_bytes()).hexdigest(),
                    "execution_plan_sha256": self.plan.execution_sha256(),
                    "boot_identity": self.boot_identity,
                    "supervisor_wall_cap_nanoseconds": (
                        SUPERVISOR_WALL_CAP_NANOSECONDS),
                    "hard_deadline_monotonic_nanoseconds": (
                        self.hard_deadline_monotonic_nanoseconds),
                    "retry_authorized": False,
                    "resume_authorized": True,
                })
                self._update_status()
            for stage_index in range(1, len(self.plan.stages) + 1):
                self._run_stage(stage_index)
            self._check_supervisor_deadline()
            self._update_status(
                state="complete", current_stage="complete",
                stage_index=len(self.plan.stages), running_tasks=[],
                running_processes={}, launching_task=None,
                completed_tasks=self.state["total_tasks"],
                task_weighted_percent_basis_points=10_000)
        except BaseException as exc:
            self._terminate_active()
            if self.state.get("state") not in {"failed", "interrupted"}:
                self._update_status(
                    state="failed", failure=f"{type(exc).__name__}: {exc}",
                    running_tasks=[], running_processes={})
            raise
        finally:
            self._release_lock()


def _strict_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2SupervisorError(
            "BELIEF V2 supervisor input is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise BeliefV2SupervisorError(
            "BELIEF V2 supervisor input is not canonical JSON")
    return value


def _supervisor_boot_identity(root: Path) -> str:
    """Bind the wrapper clock to the reviewed freeze's live boot."""
    try:
        freeze = execution_freeze_from_bytes(stable_read_bytes(
            root / "freeze.json"))
        live = _boot_identity()
    except (OSError, ValueError) as exc:
        raise BeliefV2SupervisorError(
            "BELIEF V2 supervisor freeze runtime refused") from exc
    if live != freeze.runtime.boot_identity:
        raise BeliefV2SupervisorError(
            "BELIEF V2 supervisor live boot identity drift")
    return live


def _absolute_python_path(path: Path) -> Path:
    """Make the interpreter path absolute without resolving its venv link."""
    if not isinstance(path, Path):
        raise BeliefV2SupervisorError(
            "BELIEF V2 supervisor Python path type drift")
    return Path(os.path.abspath(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ops", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--human-sources", type=Path, required=True)
    parser.add_argument("--group-split", type=Path, required=True)
    parser.add_argument("--validate-plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise BeliefV2SupervisorError("BELIEF V2 supervisor refuses PYTHONPATH")
    root = args.root.resolve()
    ops = args.ops.resolve()
    # Resolving a venv's ``bin/python`` symlink selects the system interpreter
    # and silently drops the venv site-packages needed by every worker.
    python = _absolute_python_path(args.python)
    worker = args.worker.resolve()
    human_sources = args.human_sources.resolve()
    group_split_path = args.group_split.resolve()
    if any(not path.is_absolute() for path in (
            root, ops, python, worker, human_sources, group_split_path)) \
            or root == ops or not python.is_file() \
            or worker != SCRIPT.with_name("belief_v2_worker.py") \
            or not human_sources.is_dir() or not group_split_path.is_file():
        raise BeliefV2SupervisorError(
            "BELIEF V2 supervisor path identity drift")
    sources = tuple(sorted(human_sources.glob("*.jsonl")))
    plan = build_supervisor_plan(
        human_source_paths=sources,
        group_split=_strict_json(group_split_path))
    if args.validate_plan_only:
        if args.resume:
            raise BeliefV2SupervisorError(
                "BELIEF V2 plan-only cannot recover execution")
        if ops.exists() or ops.is_symlink():
            raise BeliefV2SupervisorError(
                "BELIEF V2 plan-only ops slot is occupied")
        sys.stdout.buffer.write(plan.canonical_summary_bytes())
        return
    supervisor = Supervisor(
        plan=plan, root=root, ops=ops, python=python, worker=worker,
        boot_identity=_supervisor_boot_identity(root), resume=args.resume)
    signal.signal(signal.SIGTERM,
                  lambda signum, _frame: supervisor.request_stop(signum))
    signal.signal(signal.SIGINT,
                  lambda signum, _frame: supervisor.request_stop(signum))
    supervisor.run()


if __name__ == "__main__":
    main()
