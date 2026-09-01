#!/usr/bin/env python3
"""Run and publish the score-free Value-Afterstate V2 capacity receipt.

This command has capacity authority only.  It does not train, open labels or
outcomes, run an audit, or authorize a consumer.  The output path is
single-writer and non-destructive.
"""

from __future__ import annotations

import os
import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 capacity requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 capacity refuses PYTHONPATH")


def _require_runtime_environment() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise RuntimeError(
            "Value V2 requires SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import multiprocessing  # noqa: E402
from pathlib import Path  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

SERVER = Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(SERVER):
    sys.path.insert(0, str(SERVER))


def _preimport_bytecode_scan(
        prefixes: tuple[Path, ...] | None = None) -> None:
    """Refuse ignored bytecode before importing any project module."""
    roots = prefixes or (SERVER / "scripts", SERVER / "shengji")
    for prefix in roots:
        if not prefix.is_dir() or prefix.is_symlink():
            raise RuntimeError("Value V2 capacity source root drift")
        for _current, dirs, files in os.walk(
                prefix, topdown=True, followlinks=False):
            if "__pycache__" in dirs or any(name.endswith(".pyc")
                                              for name in files):
                raise RuntimeError(
                    "Value V2 capacity refuses source bytecode artifacts")


if __name__ in ("__main__", "__mp_main__"):
    _require_runtime_environment()
    _preimport_bytecode_scan()

from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.world_afterstate_v2_capacity_runner import (  # noqa: E402
    CapacityRunnerError, publish_capacity_failure_receipt_v2,
    publish_capacity_receipt_v2, reopen_capacity_failure_receipt_v2,
    reopen_capacity_receipt_v2, run_capacity_v2,
)
from shengji.rl.world_afterstate_v2_capacity import (  # noqa: E402
    MAX_COMMAND_WALL_SECONDS, CapacityFailureReceiptV2)
from shengji.rl.world_afterstate_v2_freeze_builder import _source_closure  # noqa: E402
from shengji.rl.world_afterstate_v2_execution import (  # noqa: E402
    bind_runtime_expectation, live_runtime_profile,
)


REPO = SERVER.parent


def _assert_module_origins() -> None:
    for name in (
            "shengji.rl.belief_contract",
            "shengji.rl.world_afterstate_v2_capacity",
            "shengji.rl.world_afterstate_v2_capacity_runner",
            "shengji.rl.world_afterstate_v2_execution",
            "shengji.rl.world_afterstate_v2_freeze_builder"):
        module = sys.modules.get(name)
        origin = None if module is None else getattr(module, "__file__", None)
        try:
            Path(origin).resolve(strict=True).relative_to(SERVER.resolve(strict=True))
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError("Value V2 capacity module origin drift") from exc


_assert_module_origins()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="bounded score-free Value-Afterstate V2 capacity measurement")
    value.add_argument("--out", type=Path, required=True,
                       help="new canonical receipt path")
    value.add_argument("--failure-out", type=Path, required=True,
                       help="new canonical failure-receipt path")
    value.add_argument("--work-root", type=Path, required=True,
                       help="fresh private capacity-work namespace retained on failure")
    value.add_argument("--progress", action="store_true",
                       help="emit bounded score-free progress to stderr")
    return value


def _progress(row: dict[str, object]) -> None:
    print(json.dumps(row, sort_keys=True, separators=(",", ":")),
          file=sys.stderr, flush=True)


def _lexical_path(value: Path) -> Path:
    """Return an absolute path without following the requested final entry."""
    return Path(os.path.abspath(os.fspath(value)))


def _has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return current.is_symlink()


def _source_rows() -> tuple[dict[str, object], ...]:
    """Bind the complete tracked Value V2 import closure before execution."""
    rows = []
    for path in _source_closure(REPO):
        raw = path.read_bytes()
        rows.append({
            "path": path.relative_to(REPO).as_posix(),
            "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return tuple(rows)


def _source_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-capacity-source-v2",
        "files": list(_source_rows()),
    })).hexdigest()


def _runtime_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(live_runtime_profile())).hexdigest()


def _worker_deadline_expired(_signum: int, _frame: object) -> None:
    """Hard-stop the isolated child group even if its parent disappears."""
    os.killpg(os.getpgrp(), signal.SIGKILL)


class _SpawnedCapacityWorker:
    """Small communicate/wait adapter around a private spawn child."""

    def __init__(self, process: multiprocessing.Process, reader: object) -> None:
        self.process = process
        self.reader = reader

    @property
    def pid(self) -> int:
        if self.process.pid is None:
            raise CapacityRunnerError("capacity worker PID is unavailable")
        return self.process.pid

    @property
    def returncode(self) -> int | None:
        return self.process.exitcode

    def communicate(self, timeout: float) -> tuple[bytes, None]:
        started = time.monotonic()
        if not self.reader.poll(timeout):
            raise subprocess.TimeoutExpired(("capacity-worker",), timeout)
        try:
            raw = self.reader.recv_bytes()
        except EOFError:
            raw = b""
        remaining = max(0.0, timeout - (time.monotonic() - started))
        self.process.join(remaining)
        if self.process.is_alive():
            raise subprocess.TimeoutExpired(("capacity-worker",), timeout)
        self.reader.close()
        return raw, None

    def kill(self) -> None:
        if self.process.is_alive():
            self.process.kill()

    def wait(self, timeout: float | None = None) -> int | None:
        self.process.join(timeout)
        if self.process.is_alive():
            raise subprocess.TimeoutExpired(("capacity-worker",), timeout)
        self.reader.close()
        return self.process.exitcode


def _worker_process_entry(writer: object, args: argparse.Namespace,
                          output: Path, failure_out: Path,
                          work_root: Path) -> None:
    """Private multiprocessing target; it is not dispatchable from the CLI."""
    try:
        os.setsid()
        previous = signal.signal(signal.SIGALRM, _worker_deadline_expired)
        signal.alarm(MAX_COMMAND_WALL_SECONDS)
        try:
            code, raw = _run_worker(
                args, output=output, failure_out=failure_out,
                work_root=work_root)
            writer.send_bytes(raw)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
            writer.close()
    except BaseException:
        try:
            writer.close()
        finally:
            raise
    raise SystemExit(code)


def _spawn_worker(args: argparse.Namespace, *, output: Path,
                  failure_out: Path, work_root: Path) -> _SpawnedCapacityWorker:
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_process_entry,
        args=(writer, args, output, failure_out, work_root), daemon=False)
    process.start()
    writer.close()
    return _SpawnedCapacityWorker(process, reader)


def _input_sha256(output: Path, failure_out: Path, work_root: Path) -> str:
    return hashlib.sha256(canonical_json_bytes({
        "output": str(output), "failure_output": str(failure_out),
        "work_root": str(work_root),
    })).hexdigest()


def _failure_receipt(exc: BaseException, *, started_ns: int, output: Path,
                     failure_out: Path, work_root: Path,
                     source_sha256: str,
                     runtime_sha256: str) -> CapacityFailureReceiptV2:
    input_sha256 = _input_sha256(output, failure_out, work_root)
    namespace_sha256 = hashlib.sha256(canonical_json_bytes({
        "source_sha256": source_sha256, "input_sha256": input_sha256,
        "runtime_sha256": runtime_sha256,
    })).hexdigest()
    assessments = tuple(getattr(exc, "assessments", ()))
    projection_diagnostic = getattr(exc, "projection_diagnostic", None)
    detail_message = str(exc)
    detail_sha256 = hashlib.sha256(canonical_json_bytes({
        "message": detail_message,
        "assessments": [row.payload() for row in assessments],
        "projection_diagnostic": (
            None if projection_diagnostic is None else
            projection_diagnostic.payload()),
    })).hexdigest()
    return CapacityFailureReceiptV2(
        stage=getattr(exc, "stage", "runner"),
        reason=getattr(exc, "reason_code", "capacity-runner-refused"),
        elapsed_seconds=min(MAX_COMMAND_WALL_SECONDS, max(
            0, (time.perf_counter_ns() - started_ns) // 1_000_000_000)),
        source_sha256=source_sha256, input_sha256=input_sha256,
        runtime_sha256=runtime_sha256,
        namespace_sha256=namespace_sha256,
        detail_sha256=detail_sha256, detail_message=detail_message,
        assessments=assessments,
        projection_diagnostic=projection_diagnostic)


def _validate_namespaces(output: Path, failure_out: Path,
                         work_root: Path) -> None:
    if len({output, failure_out, work_root}) != 3:
        raise CapacityRunnerError(
            "capacity output namespace is aliased", stage="capacity-cli",
            reason_code="capacity-namespace-refused")
    real = {Path(os.path.realpath(path))
            for path in (output, failure_out, work_root)}
    if len(real) != 3 or any(
            path.exists() or path.is_symlink() or _has_symlink_component(path)
            for path in (output, failure_out, work_root)):
        raise CapacityRunnerError(
            "capacity output namespace is occupied or aliased",
            stage="capacity-cli", reason_code="capacity-namespace-refused")


def _run_worker(args: argparse.Namespace, *, output: Path, failure_out: Path,
                work_root: Path) -> tuple[int, bytes]:
    """Run capacity in the killable worker; return canonical bytes to parent."""
    started_ns = time.perf_counter_ns()
    source_sha256 = _source_sha256()
    runtime_sha256 = _runtime_sha256()
    bind_runtime_expectation(runtime_sha256)
    try:
        receipt = run_capacity_v2(
            source_sha256=source_sha256,
            runtime_sha256=runtime_sha256,
            progress=_progress if args.progress else None, output_root=work_root)
        if _source_sha256() != source_sha256:
            raise CapacityRunnerError(
                "capacity source changed during worker execution",
                stage="runner", reason_code="capacity-source-drift")
        if _runtime_sha256() != runtime_sha256:
            raise CapacityRunnerError(
                "capacity runtime changed during worker execution",
                stage="runner", reason_code="capacity-runtime-drift")
        raw = canonical_json_bytes(receipt.payload())
        if canonical_json_bytes(reopen_capacity_receipt_v2(
                json.loads(raw.decode("ascii"))).payload()) != raw:
            raise CapacityRunnerError("worker receipt reconstruction drift")
        return 0, raw
    except (CapacityRunnerError, ValueError, OSError) as exc:
        return 2, canonical_json_bytes(_failure_receipt(
            exc, started_ns=started_ns, output=output,
            failure_out=failure_out, work_root=work_root,
            source_sha256=source_sha256,
            runtime_sha256=runtime_sha256).payload())


def _kill_process_group(process: object) -> None:
    """Hard-stop the worker and every inherited process-pool child."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    # A spawn child has a short bootstrap/import window before its target can
    # call setsid().  In that window no PGID==PID exists, so kill the direct
    # child as a mandatory second boundary instead of waiting indefinitely.
    try:
        process.kill()
    except ProcessLookupError:
        pass
    process.wait(timeout=30)


def _publish_failure(exc: BaseException, *, started_ns: int, output: Path,
                     failure_out: Path, work_root: Path,
                     source_sha256: str,
                     runtime_sha256: str) -> int:
    if output.exists() or output.is_symlink():
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    failure = _failure_receipt(
        exc, started_ns=started_ns, output=output,
        failure_out=failure_out, work_root=work_root,
        source_sha256=source_sha256,
        runtime_sha256=runtime_sha256)
    try:
        publish_capacity_failure_receipt_v2(failure_out, failure)
        reopened = reopen_capacity_failure_receipt_v2(
            json.loads(failure_out.read_text(encoding="ascii")))
        if canonical_json_bytes(reopened.payload()) != failure_out.read_bytes():
            raise CapacityRunnerError(
                "published failure receipt independent reopen drift")
    except (CapacityRunnerError, ValueError, OSError) as publish_exc:
        print(f"REFUSED: {exc}; failure publication refused: {publish_exc}",
              file=sys.stderr)
        return 2
    print(f"REFUSED: {exc}", file=sys.stderr)
    return 2


def _supervised_main(args: argparse.Namespace, *, output: Path,
                     failure_out: Path, work_root: Path) -> int:
    started_ns = time.perf_counter_ns()
    source_sha256 = _source_sha256()
    runtime_sha256 = _runtime_sha256()
    try:
        process = _spawn_worker(
            args, output=output, failure_out=failure_out, work_root=work_root)
        try:
            raw, _ = process.communicate(timeout=MAX_COMMAND_WALL_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            return _publish_failure(CapacityRunnerError(
                "capacity deadline killed worker process group",
                stage="measurement", reason_code="capacity-deadline-exceeded"),
                started_ns=started_ns, output=output, failure_out=failure_out,
                work_root=work_root, source_sha256=source_sha256,
                runtime_sha256=runtime_sha256)
        if process.returncode == 0:
            if (_source_sha256() != source_sha256
                    or _runtime_sha256() != runtime_sha256):
                raise CapacityRunnerError(
                    "capacity source/runtime changed during supervised execution",
                    stage="publication", reason_code="capacity-binding-drift")
            receipt = reopen_capacity_receipt_v2(json.loads(raw.decode("ascii")))
            if (receipt.source_sha256 != source_sha256
                    or receipt.runtime_sha256 != runtime_sha256):
                raise CapacityRunnerError(
                    "worker success receipt source/runtime binding drift",
                    stage="publication", reason_code="capacity-binding-drift")
            publish_capacity_receipt_v2(output, receipt)
            reopened = reopen_capacity_receipt_v2(
                json.loads(output.read_text(encoding="ascii")))
            if canonical_json_bytes(reopened.payload()) != output.read_bytes():
                raise CapacityRunnerError(
                    "published receipt independent reopen drift")
            return 0
        if process.returncode == 2:
            failure = reopen_capacity_failure_receipt_v2(
                json.loads(raw.decode("ascii")))
            if (failure.source_sha256 != source_sha256
                    or _source_sha256() != source_sha256
                    or failure.runtime_sha256 != runtime_sha256
                    or _runtime_sha256() != runtime_sha256
                    or failure.input_sha256 != _input_sha256(
                        output, failure_out, work_root)):
                raise CapacityRunnerError(
                    "worker failure receipt binding drift",
                    stage="publication", reason_code="capacity-binding-drift")
            publish_capacity_failure_receipt_v2(failure_out, failure)
            reopened = reopen_capacity_failure_receipt_v2(
                json.loads(failure_out.read_text(encoding="ascii")))
            if reopened != failure \
                    or canonical_json_bytes(reopened.payload()) \
                    != failure_out.read_bytes():
                raise CapacityRunnerError(
                    "published worker failure reconstruction drift",
                    stage="publication", reason_code="capacity-binding-drift")
            print(f"REFUSED: {failure.stage}: {failure.reason}", file=sys.stderr)
            return 2
        raise CapacityRunnerError(
            "capacity worker exited without a typed result",
            stage="runner", reason_code="capacity-worker-exit")
    except (CapacityRunnerError, ValueError, OSError,
            UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _publish_failure(
            exc, started_ns=started_ns, output=output,
            failure_out=failure_out, work_root=work_root,
            source_sha256=source_sha256,
            runtime_sha256=runtime_sha256)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    output = _lexical_path(args.out)
    failure_out = _lexical_path(args.failure_out)
    work_root = _lexical_path(args.work_root)
    try:
        _validate_namespaces(output, failure_out, work_root)
    except CapacityRunnerError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return _supervised_main(
        args, output=output, failure_out=failure_out, work_root=work_root)


if __name__ == "__main__":
    raise SystemExit(main())
