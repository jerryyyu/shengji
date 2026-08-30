"""Score-free PT-Luna command and tool-boundary diagnostic.

The executable is supplied by the caller (tests use a local fake executable),
so this module never discovers or launches Codex implicitly. The subprocess
crosses a real file-mailbox bridge; only mailbox request count and redacted
identities are retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from . import privileged_teacher_luna_selfplay as luna
from . import privileged_teacher_luna_selfplay_execution as execution
from .privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "pt-luna-command-ladder-v3"
MODEL = luna.MODEL
EFFORT = execution.REASONING_EFFORT
VARIANTS = ("A", "B", "C", "D")
GAME_SCHEMA = luna.GAME_SCHEMA
FINAL_SCHEMA = "privileged-teacher-luna-selfplay-final-response-v2"
COMPLETION_TOKEN = "a" * 64
SOL0_TOOL = (Path(__file__).resolve().parents[2] / "scripts"
             / "privileged_teacher_sol0_tool.py")
LUNA_TOOL = (Path(__file__).resolve().parents[2] / "scripts"
             / "privileged_teacher_luna_selfplay_tool.py")
HOOK = execution.STOP_HOOK_SCRIPT


class DiagnosticError(RuntimeError):
    """The diagnostic cannot safely run or publish its bounded report."""


@dataclass(frozen=True)
class ProbeCompleted:
    returncode: int


@dataclass(frozen=True)
class ExecutableBinding:
    """The reviewed executable bytes and its stable regular-file identity."""

    sha256: str
    identity_sha256: str
    identity: tuple[int, int, int, int, int, int, int, int, int]


class ProbeMailboxServer:
    """Synthetic terminal server accepting only real ``observe`` requests."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.operation_count = 0
        self.observe_count = 0
        self._handled: set[str] = set()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        if self.path.exists() or self.path.is_symlink():
            raise DiagnosticError("mailbox occupied")
        self.path.mkdir(mode=0o700)
        self._thread = threading.Thread(target=self._serve,
                                        name="pt-luna-probe-mailbox",
                                        daemon=True)

    @staticmethod
    def _read(path: Path) -> dict[str, object]:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
        if type(value) is not dict:
            raise DiagnosticError("mailbox request shape")
        return value

    @staticmethod
    def _publish(path: Path, value: dict[str, object]) -> None:
        raw = canonical_json_bytes(value)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o400)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                for request_path in sorted(self.path.glob("request-*.json")):
                    token = request_path.name.removeprefix("request-").removesuffix(
                        ".json")
                    if token in self._handled or len(token) != 64:
                        continue
                    try:
                        request = self._read(request_path)
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        # The bridge publishes the request atomically by
                        # creation, but allow a reader to race its final write.
                        continue
                    self._handled.add(token)
                    self.operation_count += 1
                    response = {"status": "error"}
                    if request == {"op": "observe"}:
                        self.observe_count += 1
                        response = {
                            "schema": GAME_SCHEMA,
                            "status": "round_end",
                            "completion_token": COMPLETION_TOKEN,
                        }
                    self._publish(self.path / f"response-{token}.json", response)
                self._stop.wait(0.001)
        except BaseException as exc:  # pragma: no cover - defensive thread guard
            self._error = exc
            self._stop.set()

    def __enter__(self) -> "ProbeMailboxServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        if self._thread.is_alive() or self._error is not None:
            raise DiagnosticError("mailbox server cleanup refused")
        for child in self.path.iterdir():
            if child.is_symlink() or not child.is_file():
                raise DiagnosticError("mailbox population drift")
            child.unlink()
        self.path.rmdir()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _command_sha(command: tuple[str, ...]) -> str:
    return _sha_bytes(canonical_json_bytes(list(command)))


def _tool_sha(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DiagnosticError("bridge unavailable") from exc
    if not path.is_file() or path.is_symlink():
        raise DiagnosticError("bridge identity drift")
    return _sha_bytes(raw)


def _executable_identity(stat_result: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (stat_result.st_dev, stat_result.st_ino, stat_result.st_mode,
            stat_result.st_nlink, stat_result.st_uid, stat_result.st_gid,
            stat_result.st_size, stat_result.st_mtime_ns,
            stat_result.st_ctime_ns)


def _reviewed_executable(path: Path) -> ExecutableBinding:
    """Read one executable without following a replacement symlink."""
    path = Path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise DiagnosticError("executable unavailable") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise DiagnosticError("executable read refused") from exc
    finally:
        os.close(descriptor)
    identity = _executable_identity(before)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or identity != _executable_identity(after)):
        raise DiagnosticError("executable identity drift")
    raw = b"".join(chunks)
    if len(raw) != before.st_size:
        raise DiagnosticError("executable identity drift")
    identity_sha256 = _sha_bytes(canonical_json_bytes(list(identity)))
    return ExecutableBinding(sha256=_sha_bytes(raw),
                             identity_sha256=identity_sha256,
                             identity=identity)


def _revalidate_executable(path: Path, binding: ExecutableBinding) -> None:
    current = _reviewed_executable(path)
    if (current.sha256 != binding.sha256
            or current.identity != binding.identity):
        raise DiagnosticError("executable identity drift")


def _old_command(*, executable: Path, workspace: Path, final_output: Path,
                 json_output: bool, hook_override: str | None = None
                 ) -> tuple[str, ...]:
    command = [str(executable), "exec", "--ephemeral"]
    if json_output:
        command.append("--json")
    command += ["--ignore-user-config", "--ignore-rules",
                "--skip-git-repo-check", "--sandbox", "workspace-write"]
    if hook_override is not None:
        command.append(execution.STOP_HOOK_AUTOMATION_FLAG)
    command += ["-C", str(workspace), "-m", MODEL]
    if hook_override is not None:
        command += ["-c", hook_override]
    command += ["-c", f'model_reasoning_effort="{EFFORT}"']
    command += ["--output-last-message", str(final_output), "-"]
    return tuple(command)


def _diagnostic_prompt(*, bridge: Path, mailbox: Path) -> str:
    tool = f"{sys.executable} -P -B {bridge} --mailbox {mailbox}"
    terminal = json.dumps({"schema": FINAL_SCHEMA, "status": "complete",
                           "completion_token": COMPLETION_TOKEN},
                          separators=(",", ":"), ensure_ascii=True)
    return ("Use only this local diagnostic tool: " + tool + " observe\n"
            "Call observe exactly once. Then return exactly this JSON and no "
            "other text: " + terminal + "\n")


def _variant_identity(variant: str, *, executable: Path, workspace: Path,
                      mailbox: Path | None = None,
                      model_mailbox: Path | None = None,
                      hook_mailbox: Path | None = None,
                      final_output: Path
                      ) -> tuple[tuple[str, ...], Path, str]:
    if variant not in VARIANTS:
        raise DiagnosticError("unknown ladder variant")
    legacy_mailbox = model_mailbox is None and mailbox is not None
    if model_mailbox is None:
        model_mailbox = mailbox
    if model_mailbox is None:
        raise DiagnosticError("model mailbox absent")
    if hook_mailbox is None:
        hook_mailbox = (mailbox if legacy_mailbox
                        else model_mailbox.with_name(model_mailbox.name + "-hook"))
    bridge = SOL0_TOOL if variant in ("A", "B", "C") else LUNA_TOOL
    hook_override = None
    if variant == "C":
        hook_override = execution._stop_hook_binding(mailbox_path=hook_mailbox)[
            "config_override"]
    if variant == "D":
        command = execution.process_command(
            codex_binary=executable, workspace=workspace,
            final_output_path=final_output, mailbox_path=hook_mailbox)
    else:
        command = _old_command(
            executable=executable, workspace=workspace,
            final_output=final_output, json_output=variant in ("B", "C"),
            hook_override=hook_override)
    prompt = _diagnostic_prompt(bridge=bridge, mailbox=model_mailbox)
    return command, bridge, prompt


def _kill_group(process: subprocess.Popen[bytes], pgid: int) -> None:
    """Terminate the captured process group even after its leader exits."""
    try:
        os.killpg(pgid, signal.SIGTERM)
        process.wait(timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.5)


def _reap_group(pgid: int, *, deadline: float) -> None:
    """Wait until no process remains in the captured group."""
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except OSError:
            return
        time.sleep(0.01)
    # A final bounded kill is safe because pgid was captured from our
    # start_new_session process and is never discovered from arbitrary PIDs.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        return
    while True:
        try:
            os.killpg(pgid, 0)
        except OSError:
            return
        if time.monotonic() >= deadline + 0.5:
            raise DiagnosticError("process group cleanup deadline")
        time.sleep(0.01)


def run_subprocess_probe(*, command: tuple[str, ...], prompt: str,
                         timeout_seconds: float) -> ProbeCompleted:
    """Run one bounded executable in a new process group without retaining output."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise DiagnosticError("non-positive deadline")
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=command[command.index("-C") + 1],
            start_new_session=True)
    except OSError as exc:
        raise DiagnosticError("subprocess launch refused") from exc
    # start_new_session=True makes the leader's PID the private PGID.
    pgid = process.pid
    try:
        process.communicate(input=prompt.encode("utf-8"),
                            timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _kill_group(process, pgid)
        raise TimeoutError from exc
    finally:
        _kill_group(process, pgid)
        # Cleanup gets its own bounded grace period.  Computing this deadline
        # at launch would consume the grace while a healthy planner is still
        # running and make long successful probes spuriously fail cleanup.
        _reap_group(pgid, deadline=time.monotonic() + 1.0)
    return ProbeCompleted(process.returncode if process.returncode is not None
                          else -1)


def _failed(variant: str, command: tuple[str, ...], bridge: Path, *,
            result: ProbeCompleted | None, error: str | None,
            model_operations: int, model_observes: int,
            hook_operations: int, hook_observes: int,
            valid_probe: bool) -> dict[str, object]:
    return {
        "variant": variant,
        "command_sha256": _command_sha(command),
        "bridge_sha256": _tool_sha(bridge),
        "exit_code": result.returncode if result is not None else None,
        "error_sha256": _sha_text(error) if error else None,
        "model_mailbox_operations": model_operations,
        "model_observes": model_observes,
        "hook_mailbox_operations": hook_operations,
        "hook_observes": hook_observes,
        # Kept as a compatibility aggregate for existing report consumers;
        # pass/fail is determined from the two causally separate counters.
        "mailbox_operations": model_operations + hook_operations,
        "passed": (result is not None and result.returncode == 0
                    and error is None and valid_probe),
    }


def _valid_final_output(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected = {"schema": FINAL_SCHEMA, "status": "complete",
                "completion_token": COMPLETION_TOKEN}
    return value == expected and canonical_json_bytes(value) == raw


def run_variant(variant: str, *, executable: Path, workspace: Path,
                mailbox: Path | None = None,
                model_mailbox: Path | None = None,
                hook_mailbox: Path | None = None, final_output: Path,
                timeout_seconds: float = 30.0) -> dict[str, object]:
    """Run one actual file-mailbox subprocess probe exactly once."""
    if final_output.exists() or final_output.is_symlink():
        raise DiagnosticError("output occupied")
    if model_mailbox is None:
        model_mailbox = mailbox
    if model_mailbox is None:
        raise DiagnosticError("model mailbox absent")
    if hook_mailbox is None:
        hook_mailbox = model_mailbox.with_name(model_mailbox.name + "-hook")
    command, bridge, prompt = _variant_identity(
        variant, executable=executable, workspace=workspace,
        model_mailbox=model_mailbox, hook_mailbox=hook_mailbox,
        final_output=final_output)
    hook_context = (ProbeMailboxServer(hook_mailbox)
                    if variant in ("C", "D") else None)
    with ExitStack() as stack:
        model_server = stack.enter_context(ProbeMailboxServer(model_mailbox))
        if hook_context is not None:
            hook_context = stack.enter_context(hook_context)
        started = time.monotonic()
        result: ProbeCompleted | None = None
        error: str | None = None
        try:
            result = run_subprocess_probe(
                command=command, prompt=prompt, timeout_seconds=timeout_seconds)
            if result.returncode != 0:
                error = "nonzero exit"
            elif time.monotonic() - started > timeout_seconds:
                error = "overall wall deadline exceeded"
        except TimeoutError:
            error = "overall wall deadline exceeded"
        except Exception as exc:  # noqa: BLE001 - hash class only.
            error = type(exc).__name__
        if error is None and not _valid_final_output(final_output):
            error = "final output invalid"
        expected_hook_observes = 1 if variant in ("C", "D") else 0
        valid_probe = (model_server.observe_count == 1
                       and model_server.operation_count == 1
                       and (hook_context is None
                            or (hook_context.observe_count == expected_hook_observes
                                and hook_context.operation_count == expected_hook_observes)))
        row = _failed(
            variant, command, bridge, result=result, error=error,
            model_operations=model_server.operation_count,
            model_observes=model_server.observe_count,
            hook_operations=(hook_context.operation_count
                             if hook_context is not None else 0),
            hook_observes=(hook_context.observe_count
                           if hook_context is not None else 0),
            valid_probe=valid_probe and error is None)
    return row


def _publish_exclusive(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise DiagnosticError("output occupied")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def run_ladder(*, executable: Path, output: Path,
               progress: Callable[[str], None] = print,
               wall_seconds: float = 120.0) -> dict[str, object]:
    """Run A-D once with one executable and publish the redacted report."""
    if not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise DiagnosticError("non-positive overall deadline")
    if output.exists() or output.is_symlink():
        raise DiagnosticError("output occupied")
    try:
        # Resolve the caller's command once (the installed `codex` entrypoint
        # is commonly a symlink), then bind and launch that exact target.
        executable = Path(executable).resolve(strict=True)
    except OSError as exc:
        raise DiagnosticError("executable unavailable") from exc
    binding = _reviewed_executable(executable)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pt-luna-command-ladder-",
                                     dir="/tmp") as raw:
        root = Path(raw)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        rows: list[dict[str, object]] = []
        for variant in VARIANTS:
            progress(f"pt-luna-command-ladder variant={variant} phase=start")
            _revalidate_executable(executable, binding)
            remaining = wall_seconds - (time.monotonic() - started)
            if remaining <= 0:
                command, bridge, _prompt = _variant_identity(
                    variant, executable=executable, workspace=workspace,
                    model_mailbox=root / f"model-mailbox-{variant}",
                    hook_mailbox=root / f"hook-mailbox-{variant}",
                    final_output=root / f"final-{variant}")
                row = _failed(variant, command, bridge, result=None,
                              error="overall wall deadline exceeded",
                              model_operations=0, model_observes=0,
                              hook_operations=0, hook_observes=0,
                              valid_probe=False)
            else:
                row = run_variant(
                    variant, executable=executable, workspace=workspace,
                    model_mailbox=root / f"model-mailbox-{variant}",
                    hook_mailbox=root / f"hook-mailbox-{variant}",
                    final_output=root / f"final-{variant}",
                    timeout_seconds=remaining)
            _revalidate_executable(executable, binding)
            rows.append(row)
            progress(f"pt-luna-command-ladder variant={variant} "
                     f"passed={str(row['passed']).lower()}")
        report = {"schema": SCHEMA,
                  "executable_sha256": binding.sha256,
                  "executable_identity_sha256": binding.identity_sha256,
                  "variants": rows,
                  "passed": all(row["passed"] for row in rows)}
    _publish_exclusive(
        Path(output), json.dumps(report, sort_keys=True,
                                 separators=(",", ":"),
                                 ensure_ascii=True).encode("ascii"))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True,
                        help="reviewed executable or deterministic fake")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wall-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    report = run_ladder(executable=args.executable, output=args.output,
                        wall_seconds=args.wall_seconds)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
