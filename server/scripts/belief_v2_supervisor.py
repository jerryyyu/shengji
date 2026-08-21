#!/usr/bin/env python3
"""One-shot, fail-fast orchestration for the reviewed BELIEF V2/R4 DAG."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("BELIEF V2 supervisor requires Python -P -B")

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
SOURCE_ROOT = REPO / "server" / "shengji"
PROGRESS_PREFIX = "BELIEF_V2_PROGRESS "


def _refuse_import_shadows() -> None:
    for path in SOURCE_ROOT.rglob("*"):
        if path.name == "__pycache__" or path.suffix.lower() in {
                ".pyc", ".pyo"}:
            raise RuntimeError("BELIEF V2 supervisor refuses bytecode shadows")


_refuse_import_shadows()

from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.belief_v2_supervisor_plan import (  # noqa: E402
    V2SupervisorPlanV1,
    V2SupervisorTaskV1,
    build_supervisor_plan,
)


class BeliefV2SupervisorError(RuntimeError):
    """The immutable task plan or one fail-fast worker refused."""


class Supervisor:
    def __init__(
            self, *, plan: V2SupervisorPlanV1, root: Path, ops: Path,
            python: Path, worker: Path) -> None:
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
        self.lock = threading.RLock()
        self.state: dict[str, Any] = {
            "schema": "belief-v1-v2-ops-status-v2",
            "state": "starting",
            "current_stage": "supervisor-start",
            "stage_index": 0,
            "stage_count": len(plan.stages),
            "completed_tasks": 0,
            "total_tasks": sum(len(stage.tasks) for stage in plan.stages),
            "running_tasks": [],
            "latest_worker_progress": {},
            "task_weighted_percent_basis_points": 0,
            "outcome_blind": True,
            "retry_authorized": False,
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

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        partial = path.with_name(path.name + ".partial")
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
        return [str(self.python), "-P", "-B", str(self.worker),
                *task.arguments, "--root", str(self.root)]

    def _start_task(self, task: V2SupervisorTaskV1) -> None:
        out = (self.logs / f"{task.name}.stdout.log").open(
            "x", encoding="utf-8")
        err = (self.logs / f"{task.name}.stderr.log").open(
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

    def _run_stage(self, stage_index: int) -> None:
        stage = self.plan.stages[stage_index - 1]
        pending = list(stage.tasks)
        completed = 0
        self._update_status(
            state="running", current_stage=stage.name,
            stage_index=stage_index, stage_total_tasks=len(stage.tasks),
            stage_completed_tasks=0, running_tasks=[])
        while pending or self.active:
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
                        running_tasks=sorted(self.active))
                    self._terminate_active()
                    raise BeliefV2SupervisorError(
                        f"BELIEF V2 task {name} failed with {returncode}")
                completed += 1
                self._update_status(
                    completed_tasks=self.state["completed_tasks"] + 1,
                    stage_completed_tasks=completed,
                    running_tasks=sorted(self.active))

    def run(self) -> None:
        if self.ops.exists() or self.ops.is_symlink():
            raise BeliefV2SupervisorError(
                "BELIEF V2 supervisor ops slot is occupied")
        self.ops.mkdir(mode=0o700, parents=True)
        self.logs.mkdir(mode=0o700)
        self._atomic_json(self.started_path, {
            "schema": "belief-v1-v2-ops-start-v2",
            "started_unix_seconds": int(time.time()),
            "pid": os.getpid(),
            "plan_summary_sha256": hashlib.sha256(
                self.plan.canonical_summary_bytes()).hexdigest(),
            "execution_plan_sha256": self.plan.execution_sha256(),
            "retry_authorized": False,
        })
        try:
            for stage_index in range(1, len(self.plan.stages) + 1):
                self._run_stage(stage_index)
            self._update_status(
                state="complete", current_stage="complete",
                stage_index=len(self.plan.stages), running_tasks=[],
                completed_tasks=self.state["total_tasks"],
                task_weighted_percent_basis_points=10_000)
        except BaseException as exc:
            self._terminate_active()
            if self.state.get("state") not in {"failed", "interrupted"}:
                self._update_status(
                    state="failed", failure=f"{type(exc).__name__}: {exc}",
                    running_tasks=[])
            raise


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ops", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--human-sources", type=Path, required=True)
    parser.add_argument("--group-split", type=Path, required=True)
    parser.add_argument("--validate-plan-only", action="store_true")
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise BeliefV2SupervisorError("BELIEF V2 supervisor refuses PYTHONPATH")
    root = args.root.resolve()
    ops = args.ops.resolve()
    python = args.python.resolve()
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
        if ops.exists() or ops.is_symlink():
            raise BeliefV2SupervisorError(
                "BELIEF V2 plan-only ops slot is occupied")
        sys.stdout.buffer.write(plan.canonical_summary_bytes())
        return
    supervisor = Supervisor(
        plan=plan, root=root, ops=ops, python=python, worker=worker)
    signal.signal(signal.SIGTERM,
                  lambda signum, _frame: supervisor.request_stop(signum))
    signal.signal(signal.SIGINT,
                  lambda signum, _frame: supervisor.request_stop(signum))
    supervisor.run()


if __name__ == "__main__":
    main()
