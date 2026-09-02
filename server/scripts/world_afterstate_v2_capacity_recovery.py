#!/usr/bin/env python3
"""Run the bounded, score-free Census-11 capacity re-adjudication.

Only a fresh preflight and sustained width-two/width-four cohort benchmark run.
The command consumes the exact immutable Census-11 refusal and cannot rerun the
retained representative DAG, open outcomes, or authorize scientific work.
"""

from __future__ import annotations

import os
import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 capacity recovery requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 capacity recovery refuses PYTHONPATH")
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


def _preimport_bytecode_scan() -> None:
    for prefix in (SERVER / "scripts", SERVER / "shengji"):
        if not prefix.is_dir() or prefix.is_symlink():
            raise RuntimeError("Value V2 recovery source root drift")
        for _current, dirs, files in os.walk(
                prefix, topdown=True, followlinks=False):
            if "__pycache__" in dirs or any(name.endswith(".pyc")
                                              for name in files):
                raise RuntimeError(
                    "Value V2 recovery refuses source bytecode artifacts")


if __name__ in ("__main__", "__mp_main__"):
    _preimport_bytecode_scan()

from shengji.rl.belief_artifacts import stable_read_bytes  # noqa: E402
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl import world_afterstate_v2_capacity_runner as _runner  # noqa: E402,F401
from shengji.rl.world_afterstate_v2_capacity_recovery import (  # noqa: E402
    BASE_FAILURE_EXTERNAL_SHA256, RECOVERY_COMMAND_WALL_SECONDS,
    CapacityRecoveryError, CapacityRecoveryFailureV2,
    publish_capacity_recovery_failure_v2,
    publish_capacity_recovery_receipt_v2,
    reopen_capacity_recovery_failure_v2_bytes,
    reopen_capacity_recovery_receipt_v2_bytes,
    run_capacity_recovery_v2,
)
from shengji.rl.world_afterstate_v2_execution import (  # noqa: E402
    bind_runtime_expectation, live_runtime_profile,
)
from shengji.rl.world_afterstate_v2_freeze_builder import (  # noqa: E402
    _source_closure,
)

REPO = SERVER.parent


def _assert_module_origins() -> None:
    for name in (
            "shengji.rl.belief_artifacts",
            "shengji.rl.belief_contract",
            "shengji.rl.world_afterstate_v2_capacity_recovery",
            "shengji.rl.world_afterstate_v2_capacity_runner",
            "shengji.rl.world_afterstate_v2_execution",
            "shengji.rl.world_afterstate_v2_freeze_builder"):
        module = sys.modules.get(name)
        origin = None if module is None else getattr(module, "__file__", None)
        try:
            Path(origin).resolve(strict=True).relative_to(
                SERVER.resolve(strict=True))
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError("Value V2 recovery module origin drift") from exc


_assert_module_origins()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="bounded score-free Value V2 capacity re-adjudication")
    value.add_argument("--base-failure", type=Path, required=True,
                       help="immutable exact Census-11 failure receipt")
    value.add_argument("--out", type=Path, required=True,
                       help="new canonical composite receipt path")
    value.add_argument("--failure-out", type=Path, required=True,
                       help="new canonical recovery-failure path")
    value.add_argument("--progress", action="store_true",
                       help="emit bounded score-free progress to stderr")
    return value


def _progress(row: dict[str, object]) -> None:
    print(json.dumps(row, sort_keys=True, separators=(",", ":")),
          file=sys.stderr, flush=True)


def _source_sha256() -> str:
    rows = []
    for path in _source_closure(REPO):
        raw = path.read_bytes()
        rows.append({
            "path": path.relative_to(REPO).as_posix(),
            "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    return hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-capacity-source-v2",
        "files": rows,
    })).hexdigest()


def _runtime_sha256() -> str:
    return hashlib.sha256(canonical_json_bytes(
        live_runtime_profile())).hexdigest()


def _lexical_path(value: Path) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return current.is_symlink()


def _validate_paths(base: Path, output: Path, failure: Path) -> bytes:
    if len({base, output, failure}) != 3:
        raise CapacityRecoveryError("capacity recovery path alias drift")
    if (_has_symlink_component(base) or not base.is_file()
            or base.stat().st_mode & 0o777 != 0o400
            or base.stat().st_nlink != 1):
        raise CapacityRecoveryError("capacity recovery base file drift")
    if any(path.exists() or path.is_symlink()
           or _has_symlink_component(path)
           for path in (output, failure)):
        raise CapacityRecoveryError("capacity recovery output occupied")
    raw = stable_read_bytes(base)
    if hashlib.sha256(raw).hexdigest() != BASE_FAILURE_EXTERNAL_SHA256:
        raise CapacityRecoveryError("capacity recovery base bytes drift")
    return raw


def _failure(exc: BaseException, *, started_ns: int, source_sha256: str,
             runtime_sha256: str, reason: str = "capacity-recovery-refused") \
        -> CapacityRecoveryFailureV2:
    detail = str(exc) or type(exc).__name__
    return CapacityRecoveryFailureV2(
        reason=reason, detail_message=detail[:512],
        elapsed_seconds=min(
            RECOVERY_COMMAND_WALL_SECONDS,
            max(0, (time.perf_counter_ns() - started_ns) // 1_000_000_000)),
        source_sha256=source_sha256, runtime_sha256=runtime_sha256,
        base_failure_external_sha256=BASE_FAILURE_EXTERNAL_SHA256)


def _worker_deadline_expired(_signum: int, _frame: object) -> None:
    os.killpg(os.getpgrp(), signal.SIGKILL)


def _worker_entry(writer: object, base_raw: bytes, progress: bool) -> None:
    try:
        os.setsid()
        signal.signal(signal.SIGALRM, _worker_deadline_expired)
        signal.alarm(RECOVERY_COMMAND_WALL_SECONDS)
        started_ns = time.perf_counter_ns()
        source_sha256 = _source_sha256()
        runtime_sha256 = _runtime_sha256()
        bind_runtime_expectation(runtime_sha256)
        try:
            receipt = run_capacity_recovery_v2(
                base_failure_raw=base_raw, source_sha256=source_sha256,
                runtime_sha256=runtime_sha256,
                progress=_progress if progress else None)
            if (_source_sha256() != source_sha256
                    or _runtime_sha256() != runtime_sha256):
                raise CapacityRecoveryError(
                    "capacity recovery source/runtime changed")
            raw = canonical_json_bytes(receipt.payload())
            reopened = reopen_capacity_recovery_receipt_v2_bytes(raw)
            if canonical_json_bytes(reopened.payload()) != raw:
                raise CapacityRecoveryError(
                    "capacity recovery worker reconstruction drift")
            writer.send_bytes(raw)
            code = 0
        except (CapacityRecoveryError, ValueError, OSError) as exc:
            failure = _failure(
                exc, started_ns=started_ns, source_sha256=source_sha256,
                runtime_sha256=runtime_sha256)
            writer.send_bytes(canonical_json_bytes(failure.payload()))
            code = 2
        finally:
            signal.alarm(0)
            writer.close()
    except BaseException:
        try:
            writer.close()
        finally:
            raise
    raise SystemExit(code)


def _spawn(base_raw: bytes, progress: bool):
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_entry, args=(writer, base_raw, progress), daemon=False)
    process.start()
    writer.close()
    return process, reader


def _kill(process: multiprocessing.Process) -> None:
    if process.pid is not None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.is_alive():
        process.kill()
    process.join(30)


def _publish_parent_failure(exc: BaseException, *, failure_path: Path,
                            started_ns: int, source_sha256: str,
                            runtime_sha256: str, reason: str) -> int:
    try:
        receipt = _failure(
            exc, started_ns=started_ns, source_sha256=source_sha256,
            runtime_sha256=runtime_sha256, reason=reason)
        publish_capacity_recovery_failure_v2(failure_path, receipt)
        if reopen_capacity_recovery_failure_v2_bytes(
                failure_path.read_bytes()) != receipt:
            raise CapacityRecoveryError(
                "capacity recovery failure publication drift")
    except (CapacityRecoveryError, OSError) as publish_exc:
        print(f"REFUSED: {exc}; failure publication refused: {publish_exc}",
              file=sys.stderr)
        return 2
    print(f"REFUSED: {exc}", file=sys.stderr)
    return 2


def _supervised(base: Path, base_raw: bytes, output: Path,
                failure_path: Path, progress: bool) -> int:
    started_ns = time.perf_counter_ns()
    source_sha256 = _source_sha256()
    runtime_sha256 = _runtime_sha256()
    process, reader = _spawn(base_raw, progress)
    try:
        if not reader.poll(RECOVERY_COMMAND_WALL_SECONDS):
            _kill(process)
            return _publish_parent_failure(
                CapacityRecoveryError(
                    "capacity recovery deadline killed worker group"),
                failure_path=failure_path, started_ns=started_ns,
                source_sha256=source_sha256, runtime_sha256=runtime_sha256,
                reason="capacity-recovery-deadline")
        try:
            raw = reader.recv_bytes()
        except EOFError as exc:
            raise CapacityRecoveryError(
                "capacity recovery worker exited without result") from exc
        process.join(30)
        if process.is_alive():
            _kill(process)
            raise CapacityRecoveryError("capacity recovery worker did not exit")
        if (_source_sha256() != source_sha256
                or _runtime_sha256() != runtime_sha256
                or stable_read_bytes(base) != base_raw):
            raise CapacityRecoveryError(
                "capacity recovery parent source/runtime/input drift")
        if process.exitcode == 0:
            receipt = reopen_capacity_recovery_receipt_v2_bytes(raw)
            if (receipt.source_sha256 != source_sha256
                    or receipt.runtime_sha256 != runtime_sha256):
                raise CapacityRecoveryError(
                    "capacity recovery success binding drift")
            publish_capacity_recovery_receipt_v2(output, receipt)
            if reopen_capacity_recovery_receipt_v2_bytes(
                    output.read_bytes()) != receipt:
                raise CapacityRecoveryError(
                    "capacity recovery success publication drift")
            return 0
        if process.exitcode == 2:
            failure = reopen_capacity_recovery_failure_v2_bytes(raw)
            if (failure.source_sha256 != source_sha256
                    or failure.runtime_sha256 != runtime_sha256):
                raise CapacityRecoveryError(
                    "capacity recovery failure binding drift")
            publish_capacity_recovery_failure_v2(failure_path, failure)
            print(f"REFUSED: {failure.reason}", file=sys.stderr)
            return 2
        raise CapacityRecoveryError(
            "capacity recovery worker exited without typed result")
    except (CapacityRecoveryError, ValueError, OSError,
            subprocess.TimeoutExpired) as exc:
        if process.is_alive():
            _kill(process)
        return _publish_parent_failure(
            exc, failure_path=failure_path, started_ns=started_ns,
            source_sha256=source_sha256, runtime_sha256=runtime_sha256,
            reason="capacity-recovery-supervisor")
    finally:
        reader.close()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    base = _lexical_path(args.base_failure)
    output = _lexical_path(args.out)
    failure = _lexical_path(args.failure_out)
    try:
        base_raw = _validate_paths(base, output, failure)
    except (CapacityRecoveryError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return _supervised(base, base_raw, output, failure, args.progress)


if __name__ == "__main__":
    raise SystemExit(main())
