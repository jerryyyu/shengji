"""Process and durability boundary for PT-Luna self-play.

The game/engine boundary lives in :mod:`privileged_teacher_luna_selfplay`.
This module owns only the untrusted process boundary: each team receives a
private file mailbox, while both mailboxes dispatch into the one engine-owned
game.  The default runner is intentionally never selected by tests; callers
may inject a fake runner for the bounded source test.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Mapping, Protocol

from . import privileged_teacher_luna_selfplay as luna
from . import privileged_teacher_sol0 as sol0
from .privileged_teacher_pt0 import canonical_json_bytes


MODEL = luna.MODEL
REASONING_EFFORT = "high"
LEGACY_FINAL_RESPONSE_SCHEMA = "privileged-teacher-luna-selfplay-final-response-v1"
FINAL_RESPONSE_SCHEMA = "privileged-teacher-luna-selfplay-final-response-v2"
LEGACY_PRIVATE_TRACE_SCHEMA = "privileged-teacher-luna-selfplay-private-process-trace-v1"
PRIVATE_TRACE_SCHEMA = "privileged-teacher-luna-selfplay-private-process-trace-v2"
LEGACY_ATTEMPT_SCHEMA = "privileged-teacher-luna-selfplay-private-attempt-v1"
ATTEMPT_SCHEMA = "privileged-teacher-luna-selfplay-private-attempt-v2"
ARTIFACT_SCHEMA = "privileged-teacher-luna-selfplay-private-artifact-v1"
MAX_REQUEST_BYTES = 1 << 20
MAX_PROCESS_BYTES = 16 << 20
MAX_GAME_WALL_SECONDS = 1200
CODEX_USAGE_KEYS = frozenset({
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens",
})
SANDBOX_PROFILE_SCHEMA = "privileged-teacher-luna-selfplay-sandbox-profile-v1"
RESOURCE_SCHEMA = "privileged-teacher-luna-process-tree-resource-v1"
RECOVERY_SCHEMA = "privileged-teacher-luna-selfplay-pre-manifest-recovery-v1"
PRODUCTION_EXECUTION_KIND = "verified-subprocess"
SYNTHETIC_EXECUTION_KIND = "synthetic-injected-runner"


class LunaExecutionError(ValueError):
    """The process boundary, private artifact, or frozen identity drifted."""


class LunaProcessError(LunaExecutionError):
    """A planner process did not complete its assigned game."""


@dataclass(frozen=True)
class SandboxIdentity:
    """OS-level peer path isolation identity bound into private evidence."""

    binary: str | None
    profile_sha256: str
    profile_path: str
    enforced: bool

    def payload(self) -> dict[str, object]:
        return {"schema": SANDBOX_PROFILE_SCHEMA, "binary": self.binary,
                "profile_sha256": self.profile_sha256,
                "profile_path": self.profile_path, "enforced": self.enforced}


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _valid_completion_token(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _publish(path: Path, raw: bytes, *, mode: int) -> None:
    """Write one canonical private file, refusing replacement or symlinks."""
    if path.exists() or path.is_symlink():
        raise LunaExecutionError("private output slot occupied")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        raise


def _read_regular(path: Path, *, mode: int, limit: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise LunaExecutionError("private file open refused") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != mode
            or any(getattr(before, f) != getattr(after, f) for f in stable_fields)):
        raise LunaExecutionError("private file identity drift")
    raw = b"".join(chunks)
    if len(raw) > limit or len(raw) != before.st_size:
        raise LunaExecutionError("private file size drift")
    return raw


def _read_process_file(path: Path, *, limit: int) -> bytes:
    """Read a process-created output without following a replacement link."""
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise LunaExecutionError("process output open refused") from exc
    try:
        before = os.fstat(descriptor)
        raw = os.read(descriptor, limit + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or any(getattr(before, f) != getattr(after, f) for f in fields)
            or len(raw) > limit or len(raw) != before.st_size):
        raise LunaExecutionError("process output identity drift")
    return raw


def _recovery_inventory(attempt: Path) -> tuple[list[dict[str, object]], str]:
    """Hash every pre-manifest byte without following links.

    This inventory is deliberately independent of the normal artifact schema:
    a controller can die before a trajectory/evidence file exists, but the
    bytes that did exist must still be preserved and bound forever.
    """
    entries: list[dict[str, object]] = []
    for child in sorted(attempt.rglob("*")):
        if child.is_dir():
            if child.is_symlink():
                raise LunaExecutionError("recovery directory identity drift")
            continue
        if child.is_symlink() or not child.is_file():
            raise LunaExecutionError("recovery file identity drift")
        relative = child.relative_to(attempt)
        if relative == Path("manifest.json"):
            continue
        raw = _read_process_file(child, limit=MAX_PROCESS_BYTES)
        entries.append({"path": relative.as_posix(), "size": len(raw),
                        "sha256": _sha_bytes(raw)})
    return entries, _sha(entries)


def seal_pre_manifest_attempt(*, attempt: Path,
                              coordinate: tuple[str, int, int], mirror: int,
                              root_sha256: str,
                              error: str = "controller-death-before-manifest") -> Path:
    """Seal an orphaned attempt as incomplete, without inventing artifacts."""
    attempt = Path(attempt)
    if not attempt.is_dir() or attempt.is_symlink():
        raise LunaExecutionError("recovery attempt identity drift")
    manifest = attempt / "manifest.json"
    if manifest.exists() or manifest.is_symlink():
        raise LunaExecutionError("recovery manifest already exists")
    if type(error) is not str or not error:
        raise LunaExecutionError("recovery error drift")
    luna.LunaCoordinate(*coordinate)
    if type(mirror) is not int or mirror not in luna.MIRRORS:
        raise LunaExecutionError("recovery mirror drift")
    if type(root_sha256) is not str or len(root_sha256) != 64:
        raise LunaExecutionError("recovery root SHA drift")
    inventory, inventory_sha = _recovery_inventory(attempt)
    body = {"schema": ARTIFACT_SCHEMA, "status": "incomplete",
            "coordinate": list(coordinate), "mirror": mirror,
            "root_sha256": root_sha256,
            "planner": None, "runtime": None,
            "trajectory_sha256": None, "terminal_receipt_sha256": None,
            "evidence": [], "error": error,
            "execution_kind": SYNTHETIC_EXECUTION_KIND,
            "scientific_admissible": False,
            "recovery": {"schema": RECOVERY_SCHEMA,
                          "inventory": inventory,
                          "inventory_sha256": inventory_sha}}
    _publish(manifest, canonical_json_bytes(
        {**body, "manifest_sha256": _sha(body)}), mode=0o400)
    return manifest


def _strict_json(raw: bytes, label: str) -> dict[str, object]:
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LunaExecutionError(f"{label} is not canonical JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise LunaExecutionError(f"{label} is not canonical JSON")
    return payload


@dataclass(frozen=True)
class LunaPlannerConfig:
    """Frozen process identity and wall bound."""

    model: str = MODEL
    reasoning_effort: str = REASONING_EFFORT
    max_game_wall_seconds: int = MAX_GAME_WALL_SECONDS

    def __post_init__(self) -> None:
        if self.model != MODEL or self.reasoning_effort != REASONING_EFFORT:
            raise LunaExecutionError("planner model identity drift")
        if (isinstance(self.max_game_wall_seconds, bool)
                or not isinstance(self.max_game_wall_seconds, int)
                or not 1 <= self.max_game_wall_seconds <= MAX_GAME_WALL_SECONDS):
            raise LunaExecutionError("planner wall budget drift")

    def payload(self) -> dict[str, object]:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort,
                "max_game_wall_seconds": self.max_game_wall_seconds}


def planner_prompt(*, mailbox_path: Path, tool_script: Path,
                   python: Path = Path(sys.executable)) -> str:
    tool = f"{python} -P -B {tool_script} --mailbox {mailbox_path}"
    return f"""You are PT-Luna, one team in a bounded full-information Shengji self-play round.
You control both seats of your assigned partnership. Use only this tool:
  {tool} observe
  {tool} wait
  {tool} rollout --decision SHA --candidates 0,1 --continuations heuristic-all
  {tool} play --decision SHA --candidate 0 --confidence low
Call observe before every decision. If it reports waiting, call wait; wait
wakes when the other team acts, the round ends, or the game fails. You may
roll out only on your team's decision and may play only one listed candidate.
Candidate zero is always the production prior and is the bounded fallback.
Continue until round_end.
The final legal play or subsequent observe/wait returns a one-time
completion_token. Do not stop early. Your final response must contain only
this JSON object, with TOKEN replaced by that exact engine-returned value:
{{"schema":"{FINAL_RESPONSE_SCHEMA}","status":"complete","completion_token":"TOKEN"}}
"""


class PlannerProcess(Protocol):
    def __call__(self, session: luna.LunaTeamSession, *, workspace: Path,
                 mailbox_path: Path, tool_script: Path, codex_binary: Path,
                 prompt: str, final_output_path: Path) -> subprocess.CompletedProcess[bytes]:
        ...


def process_command(*, codex_binary: Path, workspace: Path,
                    model: str = MODEL, reasoning_effort: str = REASONING_EFFORT,
                    final_output_path: Path, peer_workspace: Path | None = None,
                    peer_outputs: tuple[Path, ...] = (),
                    sandbox_profile_path: Path | None = None) -> tuple[str, ...]:
    if model != MODEL or reasoning_effort != REASONING_EFFORT:
        raise LunaExecutionError("process identity drift")
    command = (str(codex_binary), "exec", "--ephemeral", "--json",
            "--ignore-user-config",
            "--ignore-rules", "--skip-git-repo-check", "--sandbox",
            "workspace-write", "-C", str(workspace), "-m", model, "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "--output-last-message", str(final_output_path), "-")
    if peer_workspace is None:
        return command
    sandbox = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    if sandbox is None:
        return command
    if sandbox_profile_path is None:
        raise LunaExecutionError("sandbox profile path absent")
    # sandbox-exec is the outermost process, so Codex and all of its children
    # inherit peer path denial.
    return (sandbox, "-f", str(sandbox_profile_path), *command)


def _sb_quote(path: Path) -> str:
    return json.dumps(str(path.resolve()))


def sandbox_profile(*, workspace: Path, peer_workspace: Path,
                    peer_outputs: tuple[Path, ...] = ()) -> str:
    """Construct a deny-only peer profile for macOS sandbox-exec."""
    paths = (peer_workspace, *peer_outputs)
    lines = ["(version 1)", "(allow default)"]
    for path in paths:
        lines.append(f"(deny file-read* (subpath {_sb_quote(path)}))")
        lines.append(f"(deny file-write* (subpath {_sb_quote(path)}))")
    # Keep the own workspace explicit in the identity/profile even though the
    # default policy allows it; tests can inspect the exact peer boundaries.
    lines.append(f"; own-workspace {_sb_quote(workspace)}")
    return "\n".join(lines) + "\n"


def runtime_identity(*, codex_binary: Path, tool_script: Path) -> dict[str, object]:
    """Return the immutable interpreter/tool/provider identity used by a process."""
    binary = Path(codex_binary)
    version: str | None = None
    if binary.is_file():
        try:
            completed = subprocess.run((str(binary), "--version"),
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT,
                                       check=False, timeout=5)
            if completed.returncode == 0:
                candidate = completed.stdout.decode("utf-8").strip()
                version = candidate if candidate else None
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            version = None
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "python_sha256": _sha_bytes(Path(sys.executable).read_bytes()),
        "codex_binary": str(binary.resolve()) if binary.exists() else str(binary),
        "codex_binary_sha256": (_sha_bytes(binary.read_bytes())
                                if binary.is_file() else None),
        "codex_version": version,
        "platform": sys.platform,
        "tool_script": str(tool_script.resolve()),
        "tool_script_sha256": _sha_bytes(Path(tool_script).read_bytes()),
    }


def _cpu_time_nanoseconds(value: str) -> int:
    """Parse the portable ``ps time`` form, including an optional day prefix."""
    if type(value) is not str or not value:
        raise LunaExecutionError("process CPU time drift")
    days = 0
    clock = value
    if "-" in value:
        day, clock = value.split("-", 1)
        if not day.isdigit():
            raise LunaExecutionError("process CPU time drift")
        days = int(day)
    fields = clock.split(":")
    if len(fields) == 2:
        hours = 0
        minutes, seconds = fields
    elif len(fields) == 3:
        hours, minutes, seconds = fields
    else:
        raise LunaExecutionError("process CPU time drift")
    try:
        seconds_value = float(seconds)
        total = (((days * 24 + int(hours)) * 60 + int(minutes)) * 60
                 + seconds_value)
    except ValueError as exc:
        raise LunaExecutionError("process CPU time drift") from exc
    if not (0 <= int(minutes) < 60 and 0 <= seconds_value < 60
            and total >= 0):
        raise LunaExecutionError("process CPU time drift")
    return int(round(total * 1_000_000_000))


def _darwin_swap_used_bytes() -> int:
    if sys.platform != "darwin":
        return 0
    completed = subprocess.run(
        ("/usr/sbin/sysctl", "-n", "vm.swapusage"),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False, timeout=5)
    if completed.returncode != 0:
        raise LunaExecutionError("swap telemetry unavailable")
    try:
        output = completed.stdout.decode("ascii")
    except UnicodeDecodeError as exc:
        raise LunaExecutionError("swap telemetry drift") from exc
    match = re.search(r"used\s*=\s*([0-9]+(?:\.[0-9]+)?)M", output)
    if match is None:
        raise LunaExecutionError("swap telemetry drift")
    return int(round(float(match.group(1)) * 1024 * 1024))


class ProcessTreeResourceMeter:
    """Sample only the process groups launched for one Luna game.

    The meter starts before either planner process.  ``ProcessSupervisor``
    registers the two new-session process-group ids at their actual launch
    boundary.  Sampling is intentionally independent from evidence parsing so
    a completed model cannot manufacture its CPU/RSS receipt.
    """

    def __init__(self, *, sample_interval_seconds: float = 0.05,
                 ps_runner: Callable[[], bytes] | None = None,
                 swap_reader: Callable[[], int] | None = None):
        if isinstance(sample_interval_seconds, bool) \
                or not isinstance(sample_interval_seconds, (int, float)) \
                or not 0.005 <= sample_interval_seconds <= 1.0:
            raise LunaExecutionError("resource sample interval drift")
        self._interval = float(sample_interval_seconds)
        self._ps_runner = ps_runner or self._default_ps
        self._swap_reader = swap_reader or _darwin_swap_used_bytes
        self._lock = threading.Lock()
        self._groups: set[int] = set()
        self._cpu_by_pid: dict[int, int] = {}
        self._peak_rss_bytes = 0
        self._sample_count = 0
        self._error: str | None = None
        self._stop = threading.Event()
        self._initial_swap = self._read_swap()
        self._peak_swap = self._initial_swap
        self._thread = threading.Thread(
            target=self._loop, name="pt-luna-resource-meter", daemon=True)
        self._thread.start()

    @staticmethod
    def _default_ps() -> bytes:
        completed = subprocess.run(
            ("/bin/ps", "-axo", "pid=,pgid=,rss=,time="),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, timeout=5)
        if completed.returncode != 0:
            raise LunaExecutionError("process-tree telemetry unavailable")
        return completed.stdout

    def _read_swap(self) -> int:
        value = self._swap_reader()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LunaExecutionError("swap telemetry value drift")
        return value

    def register(self, process_group: int) -> None:
        if isinstance(process_group, bool) or not isinstance(process_group, int) \
                or process_group <= 0:
            raise LunaExecutionError("resource process-group drift")
        with self._lock:
            self._groups.add(process_group)

    def unregister(self, process_group: int) -> None:
        # Take one last best-effort sample while the id is still admitted.
        self._sample()
        with self._lock:
            self._groups.discard(process_group)

    def _sample(self, *, force_swap: bool = False) -> None:
        try:
            raw = self._ps_runner()
            if type(raw) is not bytes:
                raise LunaExecutionError("process-tree telemetry bytes drift")
            with self._lock:
                groups = set(self._groups)
            rss = 0
            cpu_rows: dict[int, int] = {}
            for line in raw.decode("ascii").splitlines():
                fields = line.split()
                if len(fields) != 4:
                    continue
                try:
                    pid, group, rss_kib = map(int, fields[:3])
                except ValueError:
                    continue
                if group not in groups:
                    continue
                if pid <= 0 or rss_kib < 0:
                    raise LunaExecutionError("process-tree telemetry row drift")
                rss += rss_kib * 1024
                cpu_rows[pid] = _cpu_time_nanoseconds(fields[3])
            with self._lock:
                next_sample = self._sample_count + 1
            # ``sysctl`` is itself a child process on macOS.  Sampling it on
            # every 50-ms RSS tick would materially perturb an 8-game arm.
            swap = (self._read_swap()
                    if force_swap or next_sample % 20 == 0 else None)
            with self._lock:
                for pid, cpu in cpu_rows.items():
                    self._cpu_by_pid[pid] = max(
                        cpu, self._cpu_by_pid.get(pid, 0))
                self._peak_rss_bytes = max(self._peak_rss_bytes, rss)
                if swap is not None:
                    self._peak_swap = max(self._peak_swap, swap)
                self._sample_count += 1
        except BaseException as exc:
            with self._lock:
                self._error = self._error or (type(exc).__name__ + ": " + str(exc))
            self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._sample()

    def close(self) -> dict[str, int | str]:
        self._sample(force_swap=True)
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise LunaExecutionError("resource meter thread survived close")
        with self._lock:
            if self._error is not None or self._sample_count <= 0:
                raise LunaExecutionError(
                    self._error or "resource telemetry sample absent")
            return {
                "schema": RESOURCE_SCHEMA,
                "busy_cpu_nanoseconds": sum(self._cpu_by_pid.values()),
                "peak_rss_bytes": self._peak_rss_bytes,
                "swap_bytes": max(0, self._peak_swap - self._initial_swap),
                "sample_count": self._sample_count,
            }


class ProcessSupervisor:
    """Owns process groups and one shared game deadline."""

    def __init__(self, deadline: float,
                 resource_meter: ProcessTreeResourceMeter | None = None):
        self.deadline = deadline
        self.resource_meter = resource_meter
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[bytes]] = {}
        self._aborted = threading.Event()
        self.reason: str | None = None

    @property
    def aborted(self) -> bool:
        return self._aborted.is_set()

    def register(self, team: int, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes[team] = process
            if self.resource_meter is not None:
                self.resource_meter.register(process.pid)
            if self._aborted.is_set() and process.poll() is None:
                self._terminate_one(process)

    @staticmethod
    def _terminate_one(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    @staticmethod
    def _kill_one(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def abort(self, reason: str) -> None:
        with self._lock:
            if not self._aborted.is_set():
                self.reason = reason
                self._aborted.set()
            processes = list(self._processes.values())
            for process in processes:
                self._terminate_one(process)
        # Give process groups a short grace interval, then kill stragglers.
        end = time.monotonic() + 0.25
        while time.monotonic() < end and any(p.poll() is None for p in processes):
            time.sleep(0.005)
        with self._lock:
            for process in processes:
                self._kill_one(process)

    def unregister(self, team: int) -> None:
        with self._lock:
            process = self._processes.pop(team, None)
        if process is not None and self.resource_meter is not None:
            self.resource_meter.unregister(process.pid)


def _codex_jsonl_usage(raw: bytes) -> dict[str, int]:
    """Validate Codex JSONL and return the final turn's measured token usage."""
    events: list[dict[str, object]] = []
    for line in raw.splitlines():
        if not line:
            continue
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LunaExecutionError("Codex JSONL output drift") from exc
        if type(event) is not dict or type(event.get("type")) is not str:
            raise LunaExecutionError("Codex JSONL event drift")
        events.append(event)
    if not events:
        raise LunaExecutionError("Codex JSONL output absent")
    completed = [event for event in events
                 if event.get("type") == "turn.completed"]
    if len(completed) != 1 or type(completed[0].get("usage")) is not dict:
        raise LunaExecutionError("Codex completion telemetry drift")
    usage = completed[0]["usage"]
    if set(usage) != CODEX_USAGE_KEYS or any(
            isinstance(usage[key], bool) or not isinstance(usage[key], int)
            or usage[key] < 0 for key in CODEX_USAGE_KEYS):
        raise LunaExecutionError("Codex token telemetry drift")
    return {key: usage[key] for key in sorted(CODEX_USAGE_KEYS)}


def _default_process(session: luna.LunaTeamSession, *, workspace: Path,
                     mailbox_path: Path, tool_script: Path,
                     codex_binary: Path, prompt: str,
                     final_output_path: Path,
                     supervisor: ProcessSupervisor | None = None,
                     command: tuple[str, ...] | None = None) -> subprocess.CompletedProcess[bytes]:
    del mailbox_path, tool_script
    command = command or process_command(codex_binary=codex_binary,
                                         workspace=workspace,
                                         final_output_path=final_output_path)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    process = subprocess.Popen(command, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               cwd=workspace, env=env, start_new_session=(os.name == "posix"))
    if supervisor is not None:
        supervisor.register(session.team, process)
    try:
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        while True:
            if supervisor is not None and (supervisor.aborted or time.monotonic() >= supervisor.deadline):
                if supervisor.reason is None:
                    supervisor.abort("shared Luna game deadline exceeded")
                break
            try:
                out, _ = process.communicate(timeout=0.05)
                completed = subprocess.CompletedProcess(
                    command, process.returncode or 0, out or b"")
                # CompletedProcess is intentionally retained as the narrow
                # handoff object, but this private marker proves that the
                # default runner actually crossed Popen's launch boundary.
                completed._pt_luna_actual_subprocess = True
                return completed
            except subprocess.TimeoutExpired:
                continue
        if process.poll() is None:
            supervisor.abort(supervisor.reason or "shared Luna game deadline exceeded") if supervisor else process.terminate()
        out, _ = process.communicate(timeout=1.0)
        completed = subprocess.CompletedProcess(
            command, process.returncode or 0, out or b"")
        completed._pt_luna_actual_subprocess = True
        return completed
    except subprocess.TimeoutExpired:
        if supervisor is not None:
            supervisor.abort("Luna process cleanup deadline exceeded")
        else:
            process.kill()
        out, _ = process.communicate()
        completed = subprocess.CompletedProcess(
            command, process.returncode or -9, out or b"")
        completed._pt_luna_actual_subprocess = True
        return completed
    finally:
        if supervisor is not None:
            supervisor.unregister(session.team)


class LunaToolServer:
    """Team-scoped canonical JSON mailbox backed by one Luna session."""

    def __init__(self, path: Path, session: luna.LunaTeamSession):
        if path.exists() or path.is_symlink():
            raise LunaExecutionError("tool mailbox already exists")
        if session.team not in luna.TEAMS:
            raise LunaExecutionError("team identity drift")
        self.path, self.session = path, session
        path.mkdir(mode=0o700)
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._handled: set[str] = set()
        self.trace: list[dict[str, object]] = []
        self._thread = threading.Thread(target=self._serve,
                                        name=f"pt-luna-tool-{session.team}",
                                        daemon=True)

    @staticmethod
    def _read_request(path: Path) -> dict[str, object]:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                return _strict_json(_read_regular(
                    path, mode=0o600, limit=MAX_REQUEST_BYTES), "tool request")
            except LunaExecutionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.001)

    @staticmethod
    def _publish_response(path: Path, response: Mapping[str, object]) -> bytes:
        raw = canonical_json_bytes(dict(response))
        _publish(path, raw, mode=0o400)
        return raw

    def _dispatch(self, request: Mapping[str, object]) -> dict[str, object]:
        if type(request) is not dict or "op" not in request:
            raise luna.LunaPlannerRequestError("tool request schema drift")
        op = request.get("op")
        if op == "observe":
            if set(request) != {"op"}:
                raise luna.LunaPlannerRequestError("observe request shape drift")
            return self.session.observe()
        if op == "wait":
            if set(request) != {"op"}:
                raise luna.LunaPlannerRequestError("wait request shape drift")
            self.session.wait(timeout=None)
            return self.session.observe()
        if op == "rollout":
            return self.session.rollout(request)
        if op == "play":
            return self.session.play(request)
        raise luna.LunaPlannerRequestError("unknown tool operation")

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                for request_path in sorted(self.path.glob("request-*.json")):
                    token = request_path.name.removeprefix("request-").removesuffix(".json")
                    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
                        continue
                    if token in self._handled:
                        continue
                    self._handled.add(token)
                    response_path = self.path / f"response-{token}.json"
                    request: dict[str, object] = {"op": "unreadable"}
                    try:
                        request = self._read_request(request_path)
                        response = self._dispatch(request)
                    except Exception as exc:
                        # A tool/process boundary failure aborts the shared game
                        # and wakes the peer; no request is retried.
                        self.session.game.fail(type(exc).__name__ + ": " + str(exc))
                        response = {"status": "error", "error": str(exc)}
                    response_raw = self._publish_response(response_path, response)
                    self.trace.append({"request": request,
                                       "response": dict(response),
                                       "request_sha256": _sha(request),
                                       "response_sha256": _sha_bytes(response_raw)})
                self._stop.wait(0.005)
        except BaseException as exc:
            self._error = exc
            self.session.game.fail(type(exc).__name__ + ": " + str(exc))
            self._stop.set()

    def __enter__(self) -> "LunaToolServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise LunaExecutionError("tool mailbox server did not stop")
        if self._error is not None and exc_type is None:
            raise LunaExecutionError("tool mailbox server failed") from self._error
        for child in list(self.path.iterdir()):
            if child.is_symlink() or not child.is_file():
                raise LunaExecutionError("tool mailbox file population drift")
            child.unlink()
        self.path.rmdir()


def tool_request(mailbox_path: Path, request: Mapping[str, object]) -> dict[str, object]:
    """Submit one strict request and return only its bounded response."""
    if not mailbox_path.is_dir() or mailbox_path.is_symlink():
        raise LunaExecutionError("tool mailbox identity drift")
    raw = canonical_json_bytes(dict(request))
    if len(raw) > MAX_REQUEST_BYTES:
        raise LunaExecutionError("tool request too large")
    token = hashlib.sha256(raw + os.urandom(32)).hexdigest()
    request_path = mailbox_path / f"request-{token}.json"
    response_path = mailbox_path / f"response-{token}.json"
    _publish(request_path, raw, mode=0o600)
    deadline = time.monotonic() + MAX_GAME_WALL_SECONDS
    while not response_path.is_file():
        if time.monotonic() > deadline:
            raise LunaExecutionError("tool response deadline exceeded")
        time.sleep(0.005)
    while True:
        try:
            return _strict_json(_read_regular(
                response_path, mode=0o400, limit=MAX_REQUEST_BYTES),
                "tool response")
        except LunaExecutionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.001)


@dataclass(frozen=True)
class LunaProcessEvidence:
    team: int
    body: Mapping[str, object]
    sha256: str

    def payload(self) -> dict[str, object]:
        return {"team": self.team, "evidence_sha256": self.sha256}


@dataclass(frozen=True)
class LunaExecutionResult:
    status: str
    attempt_path: Path
    evidence: tuple[LunaProcessEvidence, ...]
    trajectory_sha256: str | None
    terminal_receipt_sha256: str | None
    error: str | None
    scientific_admissible: bool = False

    def payload(self) -> dict[str, object]:
        return {"schema": ARTIFACT_SCHEMA, "status": self.status,
                "evidence": [item.payload() for item in self.evidence],
                "trajectory_sha256": self.trajectory_sha256,
                "terminal_receipt_sha256": self.terminal_receipt_sha256,
                "scientific_admissible": self.scientific_admissible,
                # Error detail remains only in the private manifest/evidence.
                "error": (None if self.error is None else "incomplete")}


def _attempt_path(private_root: Path, game: luna.LunaSelfPlayGame) -> Path:
    coordinate = "-".join(str(item) for item in game.coordinate)
    return private_root / f"{coordinate}-mirror-{game.mirror}"


def _validate_workspace_population(workspace: Path, *, complete: bool) -> None:
    """Refuse planner-created files outside the two frozen workspace files."""
    if not workspace.is_dir() or workspace.is_symlink():
        raise LunaExecutionError("planner workspace identity drift")
    names = set()
    for child in workspace.iterdir():
        if child.is_symlink() or not child.is_file():
            raise LunaExecutionError("planner workspace file population drift")
        names.add(child.name)
    allowed = {"sandbox.sb", "final.json"}
    if not names <= allowed or "sandbox.sb" not in names \
            or (complete and names != allowed):
        raise LunaExecutionError("planner workspace file population drift")


def _validate_budget(value: object) -> None:
    if type(value) is not dict or set(value) != {
            "rollout_calls", "rollout_calls_limit", "used", "round_used",
            "decision_limit", "round_limit"}:
        raise LunaExecutionError("process rollout budget drift")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0
           for item in value.values()):
        raise LunaExecutionError("process rollout budget drift")
    if (value["rollout_calls_limit"] != sol0.MAX_ROLLOUT_CALLS_PER_DECISION
            or value["decision_limit"] != sol0.MAX_EVALUATIONS_PER_DECISION
            or value["round_limit"] != sol0.MAX_EVALUATIONS_PER_ROUND
            or value["rollout_calls"] > value["rollout_calls_limit"]
            or value["used"] > value["decision_limit"]
            or value["round_used"] > value["round_limit"]):
        raise LunaExecutionError("process rollout budget drift")


def _validate_trace_semantics(
        event: Mapping[str, object], *, team: int,
        trajectory_events: Mapping[str, Mapping[str, object]],
        complete: bool, completion_token_sha256: str | None) -> None:
    """Bind every private tool exchange to the frozen game/tool contract."""
    request = event["request"]
    response = event["response"]
    if type(request) is not dict or type(response) is not dict:
        raise LunaExecutionError("process trace payload drift")
    op = request.get("op")
    if op not in ("observe", "wait", "rollout", "play"):
        raise LunaExecutionError("process trace operation drift")
    if response.get("status") == "error":
        if set(response) != {"status", "error"} \
                or type(response.get("error")) is not str or complete:
            raise LunaExecutionError("process trace error response drift")
        return
    if op in ("observe", "wait"):
        if set(request) != {"op"}:
            raise LunaExecutionError("process observe/wait request drift")
        status = response.get("status")
        if status == "round_end":
            if completion_token_sha256 is None:
                valid = response == {
                    "schema": luna.GAME_SCHEMA, "status": "round_end"}
            else:
                valid = (set(response) == {
                    "schema", "status", "completion_token"}
                    and response.get("schema") == luna.GAME_SCHEMA
                    and _valid_completion_token(
                        response.get("completion_token"))
                    and _sha_bytes(
                        response["completion_token"].encode("ascii"))
                    == completion_token_sha256)
            if not valid:
                raise LunaExecutionError("process observation response drift")
        elif status == "failed":
            if set(response) != {"schema", "status", "error"} \
                    or response.get("schema") != luna.GAME_SCHEMA \
                    or type(response.get("error")) is not str or complete:
                raise LunaExecutionError("process observation response drift")
        elif status == "waiting":
            if (set(response) != {"schema", "status", "acting_team", "banker",
                    "trump_rank", "hands_by_seat", "hidden_burial",
                    "current_state"}
                    or response.get("schema") != luna.GAME_SCHEMA
                    or response.get("acting_team") == team):
                raise LunaExecutionError("process observation response drift")
        elif status == "decision":
            if (set(response) != {"schema", "status", "decision_sha256",
                    "team", "acting_seat", "banker", "trump_rank",
                    "hands_by_seat", "hidden_burial", "current_state",
                    "candidates", "candidate_zero_is_production_prior",
                    "budget"}
                    or response.get("schema") != luna.GAME_SCHEMA
                    or response.get("team") != team
                    or response.get("candidate_zero_is_production_prior") is not True
                    or response.get("decision_sha256") not in trajectory_events):
                raise LunaExecutionError("process decision observation drift")
            target = trajectory_events[response["decision_sha256"]]
            if (response.get("acting_seat") != target["seat"]
                    or response.get("candidates") != target["legal_ballot"]):
                raise LunaExecutionError("process decision observation binding drift")
            _validate_budget(response.get("budget"))
        else:
            raise LunaExecutionError("process observation status drift")
        return
    if op == "rollout":
        if set(request) != {"op", "decision_sha256", "candidate_indices",
                           "continuations"}:
            raise LunaExecutionError("process rollout request drift")
        decision = request.get("decision_sha256")
        candidates = request.get("candidate_indices")
        continuations = request.get("continuations")
        if (decision not in trajectory_events or type(candidates) is not list
                or not candidates or len(set(candidates)) != len(candidates)
                or any(isinstance(index, bool) or not isinstance(index, int)
                       or not 0 <= index < len(
                           trajectory_events[decision]["legal_ballot"])
                       for index in candidates)
                or type(continuations) is not list or not continuations
                or len(set(continuations)) != len(continuations)
                or any(name not in sol0.CONTINUATIONS for name in continuations)
                or len(candidates) * len(continuations)
                > sol0.MAX_NEW_EVALUATIONS_PER_CALL):
            raise LunaExecutionError("process rollout request drift")
        if (set(response) != {"schema", "status", "new_evaluations",
                "cached_evaluations", "results", "budget"}
                or response.get("schema") != luna.GAME_SCHEMA
                or response.get("status") != "rollout_complete"):
            raise LunaExecutionError("process rollout response drift")
        results = response.get("results")
        keys = [(index, name) for index in candidates for name in continuations]
        if (type(results) is not list or len(results) != len(keys)
                or isinstance(response.get("new_evaluations"), bool)
                or not isinstance(response.get("new_evaluations"), int)
                or isinstance(response.get("cached_evaluations"), bool)
                or not isinstance(response.get("cached_evaluations"), int)
                or response["new_evaluations"] < 0
                or response["cached_evaluations"] < 0
                or response["new_evaluations"] + response["cached_evaluations"]
                != len(keys)):
            raise LunaExecutionError("process rollout response drift")
        for result, (index, name) in zip(results, keys):
            if (type(result) is not dict or set(result) != {
                    "candidate_index", "continuation", "rollout_points"}
                    or result.get("candidate_index") != index
                    or result.get("continuation") != name
                    or isinstance(result.get("rollout_points"), bool)
                    or not isinstance(result.get("rollout_points"), int)):
                raise LunaExecutionError("process rollout result drift")
        _validate_budget(response.get("budget"))
        return
    if (set(request) != {"op", "decision_sha256", "candidate_index",
                         "confidence"}
            or request.get("decision_sha256") not in trajectory_events
            or request.get("confidence") not in sol0.CONFIDENCE_LEVELS
            or isinstance(request.get("candidate_index"), bool)
            or not isinstance(request.get("candidate_index"), int)
            or not 0 <= request["candidate_index"] < len(
                trajectory_events[request["decision_sha256"]]["legal_ballot"])
            or set(response) not in ({"schema", "status", "acting_team"},
                                     {"schema", "status", "acting_team",
                                      "completion_token"})
            or response.get("schema") != luna.GAME_SCHEMA
            or response.get("status") not in ("waiting", "round_end", "failed")):
        raise LunaExecutionError("process play trace drift")
    if response.get("status") == "round_end":
        token = response.get("completion_token")
        if completion_token_sha256 is None:
            valid = set(response) == {"schema", "status", "acting_team"}
        else:
            valid = (set(response) == {"schema", "status", "acting_team",
                                      "completion_token"}
                     and _valid_completion_token(token)
                     and _sha_bytes(token.encode("ascii"))
                     == completion_token_sha256)
        if not valid:
            raise LunaExecutionError("process play completion drift")
    elif "completion_token" in response:
        raise LunaExecutionError("process play completion drift")


def run_luna_game(
        game: luna.LunaSelfPlayGame, *, private_root: Path,
        tool_script: Path, planner_process: PlannerProcess | None = None,
        codex_binary: Path | None = None,
        config: LunaPlannerConfig | None = None,
        resource_meter: ProcessTreeResourceMeter | None = None) \
        -> LunaExecutionResult:
    """Launch both planners concurrently, seal one non-retryable game attempt."""
    if type(game) is not luna.LunaSelfPlayGame:
        raise LunaExecutionError("game identity drift")
    if not tool_script.is_file():
        raise LunaExecutionError("planner tool script absent")
    config = config or LunaPlannerConfig()
    private_root = Path(private_root)
    if private_root.exists() and private_root.is_symlink():
        raise LunaExecutionError("private root identity drift")
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    attempt = _attempt_path(private_root, game)
    try:
        attempt.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise LunaExecutionError("game attempt already exists; retry refused") from exc
    binary: Path
    if codex_binary is None:
        found = shutil.which("codex")
        binary = Path(found) if found else Path("codex")
    else:
        binary = Path(codex_binary)
    runtime = runtime_identity(codex_binary=binary, tool_script=tool_script)
    if planner_process is None and (sys.platform != "darwin"
                                    or shutil.which("sandbox-exec") is None):
        raise LunaExecutionError("production peer sandbox unavailable")
    attempt_body = {"schema": ATTEMPT_SCHEMA, "coordinate": list(game.coordinate),
                    "mirror": game.mirror, "root_sha256": game.root_sha256,
                    "planner": config.payload(), "runtime": runtime,
                    "private_trace_schema": PRIVATE_TRACE_SCHEMA,
                    "final_response_schema": FINAL_RESPONSE_SCHEMA,
                    "status": "started"}
    _publish(attempt / "attempt.json", canonical_json_bytes(
        {**attempt_body, "attempt_sha256": _sha(attempt_body)}), mode=0o400)

    runner = planner_process or _default_process
    barrier = threading.Barrier(2)
    evidence: list[LunaProcessEvidence] = []
    evidence_lock = threading.Lock()
    deadline = time.monotonic() + config.max_game_wall_seconds
    if resource_meter is not None \
            and type(resource_meter) is not ProcessTreeResourceMeter:
        raise LunaExecutionError("resource meter type drift")
    supervisor = ProcessSupervisor(deadline, resource_meter)
    captures: dict[int, dict[str, object]] = {}

    def one(team: int) -> None:
        session = game.session(team)
        workspace = attempt / f"workspace-team-{team}"
        workspace.mkdir(mode=0o700)
        mailbox = workspace / "mailbox"
        final = workspace / "final.json"
        peer = attempt / f"workspace-team-{1 - team}"
        peer_trace = attempt / f"process-team-{1 - team}.json"
        profile_path = workspace / "sandbox.sb"
        profile_raw = sandbox_profile(workspace=workspace,
                                      peer_workspace=peer,
                                      peer_outputs=(peer_trace,
                                                    attempt / "terminal-receipt.json"))
        _publish(profile_path, profile_raw.encode("utf-8"), mode=0o400)
        sandbox_binary = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
        command = process_command(codex_binary=binary, workspace=workspace,
                                  final_output_path=final,
                                  peer_workspace=peer,
                                  peer_outputs=(peer_trace,),
                                  sandbox_profile_path=profile_path)
        sandbox_identity = SandboxIdentity(
            sandbox_binary,
            _sha_bytes(profile_raw.encode("utf-8")), str(profile_path),
            sandbox_binary is not None)
        trace_server: LunaToolServer | None = None
        completed: subprocess.CompletedProcess[bytes] | None = None
        process_error: str | None = None
        stdout = b""
        try:
            with LunaToolServer(mailbox, session) as trace_server:
                barrier.wait(timeout=10)
                prompt = planner_prompt(mailbox_path=mailbox, tool_script=tool_script)
                try:
                    completed = runner(session, workspace=workspace,
                                       mailbox_path=mailbox, tool_script=tool_script,
                                       codex_binary=binary, prompt=prompt,
                                       final_output_path=final,
                                       supervisor=supervisor, command=command)
                except subprocess.TimeoutExpired as exc:
                    process_error = "Luna model process exceeded wall deadline"
                    stdout = bytes(exc.stdout or b"")
                if completed is not None:
                    stdout = bytes(completed.stdout or b"")
                if completed is not None and completed.returncode != 0:
                    process_error = "Luna model process did not complete engine round"
                if completed is None and process_error is None:
                    process_error = "Luna model process absent"
        except BaseException as exc:
            process_error = process_error or (type(exc).__name__ + ": " + str(exc))
        if final.exists() or final.is_symlink():
            try:
                final_raw = _read_process_file(final, limit=MAX_PROCESS_BYTES)
            except LunaExecutionError as exc:
                final_raw = b""
                process_error = process_error or str(exc)
        else:
            final_raw = b""
        if len(stdout) > MAX_PROCESS_BYTES or len(final_raw) > MAX_PROCESS_BYTES:
            process_error = process_error or "Luna model output too large"
        try:
            usage = _codex_jsonl_usage(stdout)
        except LunaExecutionError as exc:
            usage = {key: 0 for key in sorted(CODEX_USAGE_KEYS)}
            process_error = process_error or str(exc)
        try:
            final_obj = json.loads(final_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            final_obj = None
        expected_final = {"schema": FINAL_RESPONSE_SCHEMA, "status": "complete",
                          "completion_token": session._completion_token}
        if final_obj != expected_final:
            process_error = process_error or "Luna model final response absent or malformed"
        if not game.complete:
            process_error = process_error or "Luna model process did not complete engine round"
        if process_error is not None:
            game.fail(process_error)
            supervisor.abort(process_error)
        trace = list(trace_server.trace) if trace_server is not None else []
        actual_subprocess = bool(
            planner_process is None and completed is not None
            and getattr(completed, "_pt_luna_actual_subprocess", False))
        execution_kind = (PRODUCTION_EXECUTION_KIND if actual_subprocess
                          else SYNTHETIC_EXECUTION_KIND)
        body = {"schema": PRIVATE_TRACE_SCHEMA, "team": team,
                "planner_identity": session.planner_identity,
                "command": list(command),
                "config": config.payload(), "trace": trace,
                "runtime": runtime,
                "sandbox": sandbox_identity.payload(),
                "prompt_sha256": _sha_bytes(prompt.encode("utf-8")),
                "codex_usage": usage,
                "stdout_base64": base64.b64encode(stdout).decode("ascii"),
                "final_base64": base64.b64encode(final_raw).decode("ascii"),
                "completion_token_sha256": _sha_bytes(
                    session._completion_token.encode("ascii")),
                "process_returncode": (completed.returncode if completed else None),
                "process_error": process_error,
                "execution_kind": execution_kind,
                "synthetic": not actual_subprocess,
                "actual_subprocess": actual_subprocess,
                "authority": dict(luna.AUTHORITY)}
        evidence_body = {**body, "output_sha256": _sha_bytes(stdout + b"\0" + final_raw)}
        evidence_raw = canonical_json_bytes({**evidence_body,
                                             "evidence_sha256": _sha(evidence_body)})
        # Capture now, but publish only once both planner processes terminate.
        with evidence_lock:
            captures[team] = {"raw": evidence_raw, "body": evidence_body,
                              "sha256": _sha(evidence_body)}

    threads = [threading.Thread(target=one, args=(team,),
                                name=f"pt-luna-process-{team}") for team in luna.TEAMS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        supervisor.abort("shared Luna game deadline exceeded")
        game.fail("shared Luna game deadline exceeded")
        for thread in threads:
            thread.join(5.0)
    if any(thread.is_alive() for thread in threads):
        raise LunaExecutionError(
            "planner thread survived process-group cleanup; evidence not sealed")

    for team in luna.TEAMS:
        try:
            _validate_workspace_population(
                attempt / f"workspace-team-{team}", complete=game.complete)
        except LunaExecutionError as exc:
            game.fail(str(exc))

    # Neither peer can read the other's evidence while the game is executing.
    for team in luna.TEAMS:
        capture = captures.get(team)
        if capture is None:
            game.fail(f"team {team} process evidence absent")
            continue
        _publish(attempt / f"process-team-{team}.json", capture["raw"], mode=0o400)
        evidence.append(LunaProcessEvidence(
            team, {**capture["body"], "evidence_sha256": capture["sha256"]},
            capture["sha256"]))

    if game.complete and not game.trajectory.events:
        game.fail("Luna trajectory has no state/action events")
    trajectory = game.sealed_trajectory()
    trajectory_raw = trajectory.private_bytes()
    _publish(attempt / "trajectory.json", trajectory_raw, mode=0o400)
    # A complete route must contain at least one actual state/action event;
    # accepting a zero-event trajectory would make a mechanics failure look
    # like a successful source game.
    status = "complete" if game.complete else "incomplete"
    receipt_sha: str | None = None
    if game.complete:
        receipt = game.terminal_receipt()
        receipt_raw = canonical_json_bytes(receipt.payload())
        _publish(attempt / "terminal-receipt.json", receipt_raw, mode=0o400)
        receipt_sha = receipt.receipt_sha256
    error = None if game.complete else (game.failed or "Luna game incomplete")
    scientific_admissible = (status == "complete" and bool(evidence)
                             and all(item.body.get("execution_kind")
                                     == PRODUCTION_EXECUTION_KIND
                                     and item.body.get("synthetic") is False
                                     and item.body.get("actual_subprocess") is True
                                     for item in evidence))
    manifest_body = {"schema": ARTIFACT_SCHEMA, "status": status,
                     "coordinate": list(game.coordinate), "mirror": game.mirror,
                     "root_sha256": game.root_sha256,
                     "planner": config.payload(), "runtime": runtime,
                     "trajectory_sha256": trajectory.sha256,
                     "terminal_receipt_sha256": receipt_sha,
                     "evidence": [item.payload() for item in sorted(evidence, key=lambda x: x.team)],
                     "error": error,
                     "execution_kind": (PRODUCTION_EXECUTION_KIND
                                        if scientific_admissible
                                        else SYNTHETIC_EXECUTION_KIND),
                     "scientific_admissible": scientific_admissible,
                     "recovery": None}
    _publish(attempt / "manifest.json", canonical_json_bytes(
        {**manifest_body, "manifest_sha256": _sha(manifest_body)}), mode=0o400)
    return LunaExecutionResult(status, attempt,
                               tuple(sorted(evidence, key=lambda x: x.team)),
                               trajectory.sha256, receipt_sha, error,
                               scientific_admissible)


def reopen_attempt(attempt: Path) -> LunaExecutionResult:
    """Reopen and verify a sealed private attempt without an engine or model."""
    attempt = Path(attempt)
    if not attempt.is_dir() or attempt.is_symlink():
        raise LunaExecutionError("private attempt identity drift")
    manifest = _strict_json(_read_regular(attempt / "manifest.json", mode=0o400,
                                          limit=MAX_PROCESS_BYTES), "manifest")
    manifest_sha = manifest.pop("manifest_sha256", None)
    if not isinstance(manifest_sha, str) or manifest_sha != _sha(manifest):
        raise LunaExecutionError("manifest hash drift")
    if (set(manifest) != {"schema", "status", "coordinate", "mirror",
                          "root_sha256", "planner", "runtime",
                          "trajectory_sha256", "terminal_receipt_sha256",
                          "evidence", "error", "execution_kind",
                          "scientific_admissible", "recovery"}
            or manifest.get("schema") != ARTIFACT_SCHEMA
            or manifest.get("status") not in ("complete", "incomplete")):
        raise LunaExecutionError("manifest schema drift")
    recovery = manifest.get("recovery")
    if recovery is not None:
        if (manifest["status"] != "incomplete" or manifest["execution_kind"]
                != SYNTHETIC_EXECUTION_KIND
                or manifest["scientific_admissible"] is not False
                or type(recovery) is not dict
                or set(recovery) != {"schema", "inventory", "inventory_sha256"}
                or recovery["schema"] != RECOVERY_SCHEMA
                or type(recovery["inventory"] ) is not list
                or recovery["inventory_sha256"] != _sha(recovery["inventory"])
                or not isinstance(manifest["error"], str)):
            raise LunaExecutionError("pre-manifest recovery schema drift")
        expected_inventory = recovery["inventory"]
        actual_inventory, actual_sha = _recovery_inventory(attempt)
        if actual_inventory != expected_inventory or actual_sha != recovery["inventory_sha256"]:
            raise LunaExecutionError("pre-manifest recovery inventory drift")
        expected_attempt_name = ("-".join(str(item) for item in
                                 manifest["coordinate"])
                                 + f"-mirror-{manifest['mirror']}")
        if attempt.name != expected_attempt_name:
            raise LunaExecutionError("attempt path binding drift")
        return LunaExecutionResult("incomplete", attempt, tuple(), None, None,
                                   manifest["error"], False)
    expected_population = {
        "attempt.json", "manifest.json", "trajectory.json",
        "process-team-0.json", "process-team-1.json",
        "workspace-team-0", "workspace-team-1",
    }
    if manifest["status"] == "complete":
        expected_population.add("terminal-receipt.json")
    if {child.name for child in attempt.iterdir()} != expected_population:
        raise LunaExecutionError("private attempt file population drift")
    for team in luna.TEAMS:
        _validate_workspace_population(
            attempt / f"workspace-team-{team}",
            complete=manifest["status"] == "complete")
    attempt_payload = _strict_json(_read_regular(attempt / "attempt.json", mode=0o400,
                                                  limit=MAX_REQUEST_BYTES), "attempt")
    attempt_sha = attempt_payload.pop("attempt_sha256", None)
    if not isinstance(attempt_sha, str) or attempt_sha != _sha(attempt_payload):
        raise LunaExecutionError("attempt hash drift")
    attempt_schema = attempt_payload.get("schema")
    current_attempt_keys = {"schema", "coordinate", "mirror", "root_sha256",
                            "planner", "runtime", "private_trace_schema",
                            "final_response_schema", "status"}
    legacy_attempt_keys = {"schema", "coordinate", "mirror", "root_sha256",
                           "planner", "runtime", "status"}
    if (attempt_schema == ATTEMPT_SCHEMA
            and set(attempt_payload) == current_attempt_keys
            and attempt_payload.get("private_trace_schema") == PRIVATE_TRACE_SCHEMA
            and attempt_payload.get("final_response_schema") == FINAL_RESPONSE_SCHEMA):
        expected_private_trace_schema = PRIVATE_TRACE_SCHEMA
    elif (attempt_schema == LEGACY_ATTEMPT_SCHEMA
            and set(attempt_payload) == legacy_attempt_keys):
        expected_private_trace_schema = LEGACY_PRIVATE_TRACE_SCHEMA
    else:
        raise LunaExecutionError("attempt schema drift")
    if attempt_payload.get("status") != "started":
        raise LunaExecutionError("attempt schema drift")
    if (manifest.get("coordinate") != attempt_payload.get("coordinate")
            or manifest.get("mirror") != attempt_payload.get("mirror")
            or manifest.get("root_sha256") != attempt_payload.get("root_sha256")
            or manifest.get("planner") != attempt_payload.get("planner")
            or manifest.get("runtime") != attempt_payload.get("runtime")):
        raise LunaExecutionError("attempt manifest binding drift")
    if manifest.get("schema") != ARTIFACT_SCHEMA:
        raise LunaExecutionError("manifest schema drift")
    if manifest.get("execution_kind") not in (PRODUCTION_EXECUTION_KIND,
                                                SYNTHETIC_EXECUTION_KIND) \
            or type(manifest.get("scientific_admissible")) is not bool:
        raise LunaExecutionError("manifest execution provenance drift")
    trajectory_raw = _read_regular(attempt / "trajectory.json", mode=0o400,
                                   limit=MAX_PROCESS_BYTES)
    trajectory_sha = _sha(json.loads(trajectory_raw.decode("ascii")))
    try:
        trajectory = luna.SealedTrajectory.reopen(trajectory_raw)
    except Exception as exc:
        raise LunaExecutionError("trajectory reopen refused") from exc
    trajectory_body = trajectory.body
    if trajectory.sha256 != trajectory_sha:
        raise LunaExecutionError("trajectory hash drift")
    if (manifest.get("coordinate") != trajectory_body.get("coordinate")
            or manifest.get("mirror") != trajectory_body.get("mirror")
            or manifest.get("trajectory_sha256") != trajectory_sha):
        raise LunaExecutionError("manifest trajectory binding drift")
    expected_attempt_name = ("-".join(str(item) for item in
                             trajectory_body["coordinate"])
                             + f"-mirror-{trajectory_body['mirror']}")
    if attempt.name != expected_attempt_name:
        raise LunaExecutionError("attempt path binding drift")
    receipt_sha = manifest.get("terminal_receipt_sha256")
    if manifest["status"] == "complete":
        receipt_payload = _strict_json(_read_regular(
            attempt / "terminal-receipt.json", mode=0o400,
            limit=MAX_REQUEST_BYTES), "terminal receipt")
        actual_receipt_sha = receipt_payload.get("receipt_sha256")
        try:
            receipt = luna.TerminalReceipt(
                coordinate=tuple(receipt_payload["coordinate"]),
                mirror=receipt_payload["mirror"],
                root_sha256=receipt_payload["root_sha256"],
                trajectory_sha256=receipt_payload["trajectory_sha256"],
                final_attacker_points=receipt_payload["final_attacker_points"],
                signed_level_utility=receipt_payload["signed_level_utility"],
                completion=receipt_payload["completion"],
                receipt_sha256=receipt_payload["receipt_sha256"],
                authority=receipt_payload["authority"])
            artifacts = luna.CompletedGameArtifacts(trajectory, receipt)
        except Exception as exc:
            raise LunaExecutionError("terminal receipt reopen refused") from exc
        if receipt_sha != actual_receipt_sha or artifacts.payload()["trajectory_sha256"] != trajectory_sha:
            raise LunaExecutionError("manifest receipt binding drift")
    elif receipt_sha is not None:
        raise LunaExecutionError("incomplete receipt drift")
    else:
        try:
            for event in trajectory_body["events"]:
                luna._validate_transition(event)
        except Exception as exc:
            raise LunaExecutionError(
                "incomplete trajectory mechanics refused") from exc
    trajectory_events_by_team: dict[int, dict[str, Mapping[str, object]]] = {}
    for team in luna.TEAMS:
        rows = {event["state_sha256"]: event
                for event in trajectory_body["events"] if event["team"] == team
                and len(event["legal_ballot"]) > 1}
        if len(rows) != sum(event["team"] == team
                            and len(event["legal_ballot"]) > 1
                            for event in trajectory_body["events"]):
            raise LunaExecutionError("trajectory decision identity collision")
        trajectory_events_by_team[team] = rows
    entries: list[LunaProcessEvidence] = []
    for team in luna.TEAMS:
        body = _strict_json(_read_regular(
            attempt / f"process-team-{team}.json", mode=0o400,
            limit=MAX_PROCESS_BYTES), f"team {team} process trace")
        evidence_sha = body.pop("evidence_sha256", None)
        if not isinstance(evidence_sha, str) or evidence_sha != _sha(body):
            raise LunaExecutionError("process evidence hash drift")
        common_keys = {"schema", "team", "planner_identity", "command",
                         "config", "trace", "runtime", "sandbox",
                         "prompt_sha256", "codex_usage",
                         "stdout_base64", "final_base64", "process_returncode",
                         "process_error", "output_sha256", "execution_kind",
                         "synthetic", "actual_subprocess", "authority"}
        body_schema = body.get("schema")
        expected_keys = (common_keys | {"completion_token_sha256"}
                         if body_schema == PRIVATE_TRACE_SCHEMA else common_keys)
        if (body_schema != expected_private_trace_schema
                or set(body) != expected_keys) \
                or body["team"] != team or body["config"] != attempt_payload["planner"] \
                or body["runtime"] != attempt_payload["runtime"]:
            raise LunaExecutionError("process trace schema/binding drift")
        completion_token_sha256 = body.get("completion_token_sha256")
        if (body_schema == PRIVATE_TRACE_SCHEMA
                and not _valid_completion_token(completion_token_sha256)):
            raise LunaExecutionError("process completion binding drift")
        if (body["execution_kind"] not in (PRODUCTION_EXECUTION_KIND,
                                            SYNTHETIC_EXECUTION_KIND)
                or type(body["synthetic"]) is not bool
                or type(body["actual_subprocess"]) is not bool
                or body["synthetic"] != (not body["actual_subprocess"])
                or body["authority"] != luna.AUTHORITY):
            raise LunaExecutionError("process execution provenance drift")
        if body["execution_kind"] == PRODUCTION_EXECUTION_KIND \
                and (body["synthetic"] or not body["actual_subprocess"]):
            raise LunaExecutionError("production process provenance drift")
        if body["execution_kind"] == SYNTHETIC_EXECUTION_KIND \
                and body["actual_subprocess"]:
            raise LunaExecutionError("synthetic process provenance drift")
        if (type(body["prompt_sha256"]) is not str
                or len(body["prompt_sha256"]) != 64
                or type(body["codex_usage"]) is not dict
                or set(body["codex_usage"]) != CODEX_USAGE_KEYS
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in body["codex_usage"].values())):
            raise LunaExecutionError("process telemetry binding drift")
        if (type(body["stdout_base64"]) is not str
                or type(body["final_base64"]) is not str):
            raise LunaExecutionError("process output base64 schema drift")
        try:
            stdout = base64.b64decode(body["stdout_base64"], validate=True)
            final = base64.b64decode(body["final_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise LunaExecutionError("process output base64 drift") from exc
        if body["output_sha256"] != _sha_bytes(stdout + b"\0" + final):
            raise LunaExecutionError("process output hash drift")
        planner_identity = body["planner_identity"]
        if (type(body["command"]) is not list
                or any(type(item) is not str for item in body["command"])
                or type(planner_identity) is not dict):
            raise LunaExecutionError("process identity drift")
        command = body["command"]
        if ("exec" not in command or "--ephemeral" not in command
                or "--json" not in command
                or "-m" not in command or command[command.index("-m") + 1] != MODEL
                or f'model_reasoning_effort="{REASONING_EFFORT}"' not in command):
            raise LunaExecutionError("process command identity drift")
        if (set(planner_identity) != {"team", "model",
                    "agent_identity", "model_process_id", "session_id"}
                or planner_identity.get("team") != team
                or planner_identity.get("model") != MODEL
                or any(type(planner_identity[key]) is not
                       (int if key in ("team", "agent_identity") else str)
                       for key in planner_identity)):
            raise LunaExecutionError("planner identity schema drift")
        sandbox = body["sandbox"]
        if (type(sandbox) is not dict or set(sandbox) != {"schema", "binary",
                "profile_sha256", "profile_path", "enforced"}
                or sandbox["schema"] != SANDBOX_PROFILE_SCHEMA
                or type(sandbox["enforced"]) is not bool
                or (sandbox["enforced"] and not isinstance(sandbox["binary"], str))):
            raise LunaExecutionError("sandbox identity drift")
        if sandbox["enforced"]:
            if (command[:3] != [sandbox["binary"], "-f", sandbox["profile_path"]]
                    or body["runtime"].get("codex_binary") is None):
                raise LunaExecutionError("sandbox command binding drift")
        elif command and command[0] == sandbox["binary"]:
            raise LunaExecutionError("sandbox fallback command drift")
        profile_path = Path(sandbox["profile_path"])
        try:
            profile_bytes = _read_regular(profile_path, mode=0o400,
                                          limit=MAX_REQUEST_BYTES)
        except LunaExecutionError as exc:
            raise LunaExecutionError("sandbox profile reopen refused") from exc
        if _sha_bytes(profile_bytes) != sandbox["profile_sha256"]:
            raise LunaExecutionError("sandbox profile hash drift")
        trace = body["trace"]
        if type(trace) is not list:
            raise LunaExecutionError("process trace event drift")
        for event in trace:
            if type(event) is not dict or set(event) != {"request", "response",
                    "request_sha256", "response_sha256"}:
                raise LunaExecutionError("process trace event schema drift")
            if (event["request_sha256"] != _sha(event["request"])
                    or event["response_sha256"] != _sha(event["response"])):
                raise LunaExecutionError("process trace event hash drift")
            _validate_trace_semantics(
                event, team=team,
                trajectory_events=trajectory_events_by_team[team],
                complete=manifest["status"] == "complete",
                completion_token_sha256=completion_token_sha256)
        if (body_schema == PRIVATE_TRACE_SCHEMA
                and manifest["status"] == "complete"
                and not any(event["response"].get("status") == "round_end"
                            for event in trace)):
            raise LunaExecutionError("process terminal mailbox witness absent")
        try:
            if _codex_jsonl_usage(stdout) != body["codex_usage"]:
                raise LunaExecutionError("Codex usage binding drift")
        except LunaExecutionError:
            if manifest["status"] == "complete":
                raise
        entries.append(LunaProcessEvidence(team, {**body, "evidence_sha256": evidence_sha}, evidence_sha))
    expected_evidence = [{"team": item.team, "evidence_sha256": item.sha256}
                         for item in entries]
    if manifest.get("evidence") != expected_evidence:
        raise LunaExecutionError("manifest evidence binding drift")
    expected_admissible = (manifest["status"] == "complete"
                           and manifest["execution_kind"] == PRODUCTION_EXECUTION_KIND
                           and all(item.body["execution_kind"] == PRODUCTION_EXECUTION_KIND
                                   and item.body["actual_subprocess"] is True
                                   and item.body["synthetic"] is False
                                   for item in entries))
    if manifest["scientific_admissible"] != expected_admissible:
        raise LunaExecutionError("manifest scientific admission drift")
    error = manifest.get("error")
    if manifest["status"] == "complete" and error is not None:
        raise LunaExecutionError("complete manifest error drift")
    if manifest["status"] == "incomplete" and not isinstance(error, str):
        raise LunaExecutionError("incomplete manifest error drift")
    if manifest["status"] == "complete":
        for item in entries:
            try:
                final = json.loads(base64.b64decode(
                    item.body["final_base64"]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LunaExecutionError(
                    "complete process evidence drift") from exc
            is_current = item.body["schema"] == PRIVATE_TRACE_SCHEMA
            token = final.get("completion_token") if type(final) is dict else None
            expected_final = ({"schema": FINAL_RESPONSE_SCHEMA,
                               "status": "complete",
                               "completion_token": token}
                              if is_current else {
                                  "schema": LEGACY_FINAL_RESPONSE_SCHEMA,
                                  "status": "complete"})
            if (item.body["process_returncode"] != 0
                    or item.body["process_error"] is not None
                    or final != expected_final
                    or is_current and (
                        not _valid_completion_token(token)
                        or _sha_bytes(token.encode("ascii"))
                        != item.body["completion_token_sha256"])):
                raise LunaExecutionError("complete process evidence drift")
    # Every contested play must have one matching private mailbox request. A
    # forced engine action has no request and is intentionally excluded.
    events_by_team = {team: [event for event in trajectory_body["events"]
                             if event["team"] == team and len(event["legal_ballot"]) > 1]
                      for team in luna.TEAMS}
    for item in entries:
        plays = [event for event in item.body["trace"]
                 if event["request"].get("op") == "play"]
        expected = events_by_team[item.team]
        if len(plays) != len(expected):
            raise LunaExecutionError("process play trace coverage drift")
        for trace_event, trajectory_event in zip(plays, expected):
            request = trace_event["request"]
            if (set(request) != {"op", "decision_sha256", "candidate_index", "confidence"}
                    or request["decision_sha256"] != trajectory_event["state_sha256"]
                    or request["candidate_index"] != trajectory_event["candidate_index"]
                    or trace_event["response"].get("status") == "error"):
                raise LunaExecutionError("process play binding drift")
    return LunaExecutionResult(manifest["status"], attempt, tuple(entries),
                               trajectory_sha, receipt_sha, error,
                               expected_admissible)


# Explicitly named alias used by callers that prefer a process-oriented verb.
run_luna_processes = run_luna_game


__all__ = ["ARTIFACT_SCHEMA", "ATTEMPT_SCHEMA", "FINAL_RESPONSE_SCHEMA",
           "LunaExecutionError", "LunaPlannerConfig", "LunaProcessError",
           "LunaExecutionResult", "LunaProcessEvidence", "LunaToolServer",
           "CODEX_USAGE_KEYS", "ProcessSupervisor", "ProcessTreeResourceMeter",
           "RESOURCE_SCHEMA",
           "SandboxIdentity", "SANDBOX_PROFILE_SCHEMA",
           "MAX_GAME_WALL_SECONDS", "MODEL", "PRIVATE_TRACE_SCHEMA",
           "REASONING_EFFORT", "planner_prompt", "process_command",
           "sandbox_profile", "run_luna_game", "run_luna_processes", "reopen_attempt",
           "runtime_identity", "tool_request", "RECOVERY_SCHEMA",
           "PRODUCTION_EXECUTION_KIND", "SYNTHETIC_EXECUTION_KIND",
           "seal_pre_manifest_attempt"]
