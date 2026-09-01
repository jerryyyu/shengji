"""Immutable admission and stage supervisor for Value-Afterstate V2.

This module is intentionally a narrow orchestration boundary.  It does not
play games, train a model, calculate a metric, or open an audit by itself.
The expensive operations are injected as already typed controller calls.  The
supervisor owns identity, ordering, split admission, one-shot audit opening,
and conservative filesystem recovery.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import multiprocessing
import os
import platform
import resource
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import fcntl

from .belief_artifacts import publish_exclusive_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_audit_attempt import (
    build_audit_attempt_bytes, reopen_audit_attempt_bytes,
)


SCHEMA = "world-afterstate-v2-absolute-leaf-execution-v1"
FREEZE_SCHEMA = "world-afterstate-v2-absolute-leaf-freeze-v3"
ADMISSION_SCHEMA = "world-afterstate-v2-absolute-leaf-admission-v1"
TOMBSTONE_SCHEMA = "world-afterstate-v2-absolute-leaf-consumption-tombstone-v1"
STATE_SCHEMA = "world-afterstate-v2-stage-state-v1"
EVENT_SCHEMA = "world-afterstate-v2-stage-event-v1"
PROGRESS_SCHEMA = "world-afterstate-v2-progress-v1"
PROGRESS_EVENT_SCHEMA = "world-afterstate-v2-progress-event-v1"
RUNTIME_PROFILE_SCHEMA = "world-afterstate-v2-runtime-profile-v1"
META_SCHEMA = "world-afterstate-v2-supervisor-meta-v1"
REVIEW_PREFIX = "WORLD_AFTERSTATE_V2_ABSOLUTE_LEAF_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
MAX_DEADLINE_SECONDS = 12 * 60 * 60
# Progress is operational telemetry, rather than evidence.  Keep the sink
# bounded even if a controller calls its callback more often than the frozen
# heartbeat cadence.
MAX_PROGRESS_EVENTS = 100_000
MAX_PROGRESS_EVENT_BYTES = 64 * 1024
PROGRESS_DIRECTORY = "progress"
RESOURCE_CLOSEOUT_SCHEMA = "world-afterstate-v2-resource-incomplete-closeout-v1"
RESOURCE_CLOSEOUT_RELATIVE = "resource-incomplete-closeout.json"
RUNTIME_EXPECTATION_ENV = "SHENGJI_VALUE_V2_EXPECTED_RUNTIME_SHA256"
_PROC_SELF_MAPS = Path("/proc/self/maps")

# The names are part of the protocol.  A stage may consume only the listed
# split; in particular no helper can accidentally label audit rows early.
STAGE_ORDER = (
    "population", "p0-labels-gates", "optimizer-canary", "fit-select-labels",
    "block-1-natural", "nested-curve", "block-1-controls", "block-2-natural",
    "block-2-controls", "precision-select-power", "audit-attempt",
    "terminal", "reconstruction",
)
COHORT_TRAINING_WAVE = ("block-1-controls", "block-2-natural")
WORK_STAGE_ORDER = STAGE_ORDER[:-2]
TERMINAL_STAGE_ORDER = STAGE_ORDER[-2:]
ALLOWED_SPLITS = {
    "population": ("fit", "select", "audit"),
    "fit-select-labels": ("fit", "select"),
    "p0-labels-gates": ("fit",),
    "optimizer-canary": ("fit",),
    "nested-curve": ("fit", "select"),
    "block-1-natural": ("fit",),
    "block-1-controls": ("fit",),
    "block-2-natural": ("fit",),
    "block-2-controls": ("fit",),
    "precision-select-power": ("select",),
    "audit-attempt": ("audit",),
    "terminal": ("fit", "select", "audit"),
    "reconstruction": ("fit", "select", "audit"),
}
AUTHORITY = {
    "population_authorized": False,
    "label_opening_authorized": False,
    "training_authorized": False,
    "audit_opening_authorized": False,
    "terminal_authorized": False,
    "reconstruction_authorized": False,
    "retry_authorized": False,
    "regeneration_authorized": False,
    "replacement_authorized": False,
    "gameplay_authorized": False,
    "puct_authorized": False,
    "belief_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}
TERMINAL_ROUTES = (
    "REFUSE_MECHANICS_OR_CONTROL", "REFUSE_RESOURCE_INCOMPLETE",
    "REFUSE_TRAINING_RECIPE", "STOP_NO_REPRODUCIBLE_VALUE_LABEL",
    "STOP_BELOW_WORTHWHILE_VALUE_FLOOR", "STOP_UNDERPOWERED",
    "SELECT_NONE_PREAUDIT_LEARNING", "SELECT_NONE_NO_ABSOLUTE_VALUE",
    "SELECT_NONE_NO_ACTION_SENSITIVITY", "SELECT_NONE_NO_WORLD_SIGNAL",
    "PASS_ABSOLUTE_VALUE_LEARNING_ONLY",
    "PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN",
)


class WorldAfterstateV2ExecutionError(ValueError):
    """A freeze, admission, stage transition, or artifact was refused."""


class MissingStageError(WorldAfterstateV2ExecutionError):
    """A required typed controller was not supplied; fail closed."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2ExecutionError(f"{label} drift")
    return value


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(("git", *args), cwd=repo, check=True,
                            capture_output=True, text=not binary)
    return result.stdout if binary else result.stdout.strip()


def _strict(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2ExecutionError(f"{label} bytes drift")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               ValueError(value)))
    except WorldAfterstateV2ExecutionError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2ExecutionError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2ExecutionError(f"{label} is not canonical JSON")
    return value


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise WorldAfterstateV2ExecutionError("duplicate JSON key")
        result[key] = value
    return result


def _write_once(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise WorldAfterstateV2ExecutionError("immutable path occupied")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        publish_exclusive_bytes(path, raw)
    except Exception as exc:
        raise WorldAfterstateV2ExecutionError(
            "immutable publication refused") from exc


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _controller_process_entry(operation: Callable[..., Any],
                              supervisor: "StageSupervisorV2",
                              shards: tuple[str, ...], connection: Any) -> None:
    """Run one scientific controller in its own killable process group."""
    try:
        os.setsid()
        bind_runtime_expectation(supervisor.freeze.runtime_sha256)
        # Spawned controllers have their own process CPU counter.  Do not
        # compare it with the parent's invocation baseline carried through
        # pickling; reset all invocation-relative telemetry in the child.
        supervisor._telemetry_started = supervisor.clock()
        supervisor._process_cpu_baseline = _process_cpu_nanoseconds()
        supervisor._cgroup_directory = _cgroup_v2_directory()
        supervisor._cgroup_cpu_baseline = _cgroup_cpu_nanoseconds(
            supervisor._cgroup_directory)
        if (supervisor.clock() - supervisor._started
                >= supervisor.freeze.deadline_seconds * 1_000_000_000):
            raise WorldAfterstateV2ExecutionError(
                "controller deadline expired before operation")
        result = operation(supervisor, shards)
        connection.send(("result", result))
    except BaseException as exc:  # trusted child; preserve the typed refusal
        try:
            connection.send(("error", exc))
        except BaseException:
            pass
    finally:
        connection.close()


def _controller_context() -> multiprocessing.context.BaseContext:
    """Use a clean interpreter so Torch/native parent threads are not forked."""
    try:
        return multiprocessing.get_context("spawn")
    except ValueError as exc:
        raise WorldAfterstateV2ExecutionError(
            "killable controller process boundary unavailable") from exc


def _terminate_process_group(process: multiprocessing.Process) -> None:
    """Stop a controller and every nested worker before selecting a route."""
    if process.pid is None:
        return
    if process.is_alive():
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        process.join(timeout=2.0)
    if process.is_alive():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.join(timeout=2.0)
    if process.is_alive():
        raise WorldAfterstateV2ExecutionError(
            "controller process survived deadline termination")


def _boot_identity() -> str:
    """Return a stable boot witness used to prevent cross-boot resume."""
    linux = Path("/proc/sys/kernel/random/boot_id")
    if linux.is_file():
        value = linux.read_text(encoding="ascii").strip()
        if value:
            return value
    try:
        value = subprocess.run(("sysctl", "-n", "kern.boottime"), check=True,
                               capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV2ExecutionError("boot identity telemetry unavailable") from exc
    if not value:
        raise WorldAfterstateV2ExecutionError("boot identity telemetry unavailable")
    return value


def _cgroup_v2_directory(*, proc_cgroup: Path | None = None,
                          cgroup_root: Path | None = None) -> Path | None:
    """Resolve this process's unified cgroup directory, if one is usable."""
    proc_cgroup = proc_cgroup or Path("/proc/self/cgroup")
    cgroup_root = cgroup_root or Path("/sys/fs/cgroup")
    try:
        rows = proc_cgroup.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    unified = []
    for row in rows:
        fields = row.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            unified.append(fields[2])
    if len(unified) != 1 or not unified[0].startswith("/") \
            or "\x00" in unified[0]:
        return None
    relative_parts = tuple(part for part in unified[0].split("/") if part)
    if any(part in (".", "..") for part in relative_parts):
        return None
    return cgroup_root.joinpath(*relative_parts)


def _nonnegative_integer(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="ascii").strip())
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if value >= 0 else None


def _cgroup_cpu_nanoseconds(directory: Path | None) -> int | None:
    if directory is None:
        return None
    try:
        values: dict[str, int] = {}
        for row in (directory / "cpu.stat").read_text(encoding="ascii").splitlines():
            fields = row.split()
            if len(fields) != 2 or fields[0] in values:
                return None
            values[fields[0]] = int(fields[1])
        usage_usec = values.get("usage_usec")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if usage_usec is None or usage_usec < 0:
        return None
    return usage_usec * 1_000


def _process_cpu_nanoseconds(usage: Any | None = None) -> int:
    try:
        if usage is None:
            usage = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        seconds = (usage.ru_utime + usage.ru_stime + children.ru_utime
                   + children.ru_stime)
        value = int(seconds * 1_000_000_000)
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        raise WorldAfterstateV2ExecutionError(
            "process CPU telemetry unavailable") from exc
    if value < 0:
        raise WorldAfterstateV2ExecutionError("process CPU telemetry unavailable")
    return value


def _process_memory_bytes(usage: Any) -> int:
    # Older Linux hosts have no cgroup v2; /proc gives current RSS rather than
    # the historical high-water mark returned by getrusage.
    statm = Path("/proc/self/statm")
    try:
        if statm.is_file():
            fields = statm.read_text(encoding="ascii").split()
            if len(fields) > 1:
                rss_pages = int(fields[1])
                if rss_pages >= 0:
                    return rss_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, UnicodeDecodeError, IndexError, ValueError):
        pass
    # macOS exposes only the process high-water mark through this stdlib API;
    # it remains a live nonzero witness and is tracked independently as peak.
    try:
        rss = int(usage.ru_maxrss)
    except (TypeError, ValueError, OverflowError) as exc:
        raise WorldAfterstateV2ExecutionError(
            "process memory telemetry unavailable") from exc
    if rss < 0:
        raise WorldAfterstateV2ExecutionError("process memory telemetry unavailable")
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def _live_telemetry(elapsed_nanoseconds: int, *,
                    process_cpu_baseline: int | None = None,
                    cgroup_directory: Path | None = None,
                    cgroup_cpu_baseline: int | None = None) -> tuple[int, int]:
    """Return process CPU utilization and current cgroup/RSS memory."""
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError("process CPU telemetry unavailable") from exc
    process_cpu_ns = _process_cpu_nanoseconds(usage)
    if process_cpu_baseline is not None and process_cpu_ns >= process_cpu_baseline:
        process_delta_ns = process_cpu_ns - process_cpu_baseline
    else:
        process_delta_ns = None
    cgroup = _cgroup_v2_directory()
    cgroup_cpu_ns = _cgroup_cpu_nanoseconds(cgroup)
    if cgroup is not None and cgroup == cgroup_directory \
            and cgroup_cpu_ns is not None and cgroup_cpu_baseline is not None \
            and cgroup_cpu_ns >= cgroup_cpu_baseline:
        # Only an invocation-relative cgroup delta is comparable with the
        # supervisor's elapsed time; absolute counters may predate this run.
        cpu_ns = cgroup_cpu_ns - cgroup_cpu_baseline
    elif process_delta_ns is not None:
        cpu_ns = process_delta_ns
    else:
        raise WorldAfterstateV2ExecutionError("process CPU telemetry unavailable")
    cpu_ppm = int(cpu_ns * 1_000_000 // max(elapsed_nanoseconds, 1))
    memory = _nonnegative_integer(cgroup / "memory.current") if cgroup is not None else None
    return cpu_ppm, memory if memory is not None else _process_memory_bytes(usage)


def _python_environment_identity() -> dict[str, str]:
    """Bind the resolved interpreter prefixes and ``pyvenv.cfg`` bytes.

    An executable path by itself does not identify a virtual environment.
    Include both prefix paths and an explicit config hash/absence marker so a
    freeze cannot silently reuse an older environment.
    """
    try:
        prefix = Path(sys.prefix).resolve(strict=True)
        base_prefix = Path(sys.base_prefix).resolve(strict=True)
        config = prefix / "pyvenv.cfg"
        if config.is_symlink():
            raise OSError("pyvenv.cfg is symlinked")
        if config.exists():
            if not config.is_file():
                raise OSError("pyvenv.cfg is not a regular file")
            config_sha256 = _sha_bytes(config.read_bytes())
        else:
            config_sha256 = "absent"
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError(
            "runtime Python environment telemetry unavailable") from exc
    return {"python_prefix": str(prefix),
            "python_base_prefix": str(base_prefix),
            "pyvenv_cfg_path": str(config),
            "pyvenv_cfg_sha256": config_sha256}


_RUNTIME_PROFILE_KEYS = frozenset({
    "schema", "python", "python_executable", "python_executable_lexical",
    "python_executable_sha256", "python_prefix", "python_base_prefix",
    "pyvenv_cfg_path", "pyvenv_cfg_sha256", "platform", "machine",
    "cpu_count", "torch_threads", "torch_version", "torch_config_sha256",
    "numpy_version", "environment", "shengji_native_extension",
    "boot_identity",
})


def validate_runtime_profile(profile: Mapping[str, Any]) -> None:
    """Validate the complete runtime identity, including virtualenv bytes."""
    if type(profile) is not dict or set(profile) != _RUNTIME_PROFILE_KEYS:
        raise WorldAfterstateV2ExecutionError("runtime profile field population drift")
    if profile["schema"] != RUNTIME_PROFILE_SCHEMA:
        raise WorldAfterstateV2ExecutionError("runtime profile schema drift")
    for key in ("python", "python_executable", "python_executable_lexical",
                "platform", "machine", "torch_version", "numpy_version",
                "boot_identity"):
        if type(profile[key]) is not str or not profile[key]:
            raise WorldAfterstateV2ExecutionError("runtime profile value drift")
    for key in ("python_prefix", "python_base_prefix", "pyvenv_cfg_path"):
        if (type(profile[key]) is not str or not Path(profile[key]).is_absolute()):
            raise WorldAfterstateV2ExecutionError("runtime Python path drift")
    if profile["pyvenv_cfg_path"] != str(
            Path(profile["python_prefix"]) / "pyvenv.cfg"):
        raise WorldAfterstateV2ExecutionError("runtime pyvenv path drift")
    cfg_hash = profile["pyvenv_cfg_sha256"]
    if cfg_hash != "absent":
        _digest(cfg_hash, "runtime pyvenv.cfg SHA-256")
    _digest(profile["python_executable_sha256"],
            "runtime executable SHA-256")
    _digest(profile["torch_config_sha256"], "runtime Torch config SHA-256")
    if (isinstance(profile["cpu_count"], bool)
            or not isinstance(profile["cpu_count"], int)
            or profile["cpu_count"] < 1
            or isinstance(profile["torch_threads"], bool)
            or not isinstance(profile["torch_threads"], int)
            or profile["torch_threads"] < 1):
        raise WorldAfterstateV2ExecutionError("runtime CPU telemetry drift")
    if type(profile["environment"]) is not dict \
            or type(profile["shengji_native_extension"]) is not dict:
        raise WorldAfterstateV2ExecutionError("runtime environment telemetry drift")


def live_runtime_profile() -> dict[str, Any]:
    """Build the minimal deterministic runtime witness for a new freeze."""
    executable = Path(sys.executable).resolve()
    try:
        executable_sha = _sha_bytes(executable.read_bytes())
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError(
            "runtime executable telemetry unavailable") from exc
    torch_version, torch_config_sha = _torch_profile()
    numpy_version = _numpy_version()
    native = _native_extension_profile()
    profile = {"schema": RUNTIME_PROFILE_SCHEMA, "python": sys.version,
            "python_executable": str(executable),
            "python_executable_lexical": sys.executable,
            "python_executable_sha256": executable_sha,
            **_python_environment_identity(),
            "platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "torch_threads": _torch_threads(),
            "torch_version": torch_version, "torch_config_sha256": torch_config_sha,
            "numpy_version": numpy_version,
            "environment": {
                "SHENGJI_FAST": os.environ.get("SHENGJI_FAST", "absent"),
                "SHENGJI_REQUIRE_VOIDS": os.environ.get(
                    "SHENGJI_REQUIRE_VOIDS", "absent"),
            },
            "shengji_native_extension": native,
            "boot_identity": _boot_identity()}
    validate_runtime_profile(profile)
    return profile


def verify_live_runtime_sha256(expected: str) -> None:
    """Refuse if this process did not import the exact frozen runtime."""
    _digest(expected, "expected runtime SHA-256")
    if _sha(live_runtime_profile()) != expected:
        raise WorldAfterstateV2ExecutionError("spawned runtime identity drift")


def bind_runtime_expectation(expected: str) -> None:
    """Bind one controller tree before it may create nested process workers."""
    verify_live_runtime_sha256(expected)
    inherited = os.environ.get(RUNTIME_EXPECTATION_ENV)
    if inherited is not None and inherited != expected:
        raise WorldAfterstateV2ExecutionError(
            "inherited runtime expectation drift")
    os.environ[RUNTIME_EXPECTATION_ENV] = expected


def _verify_inherited_runtime_expectation(
        expected: str | None = None) -> None:
    """Verify a pool worker and seed its own descendants with the binding.

    The explicit initializer argument is load-bearing.  A multiprocessing
    forkserver may have started before the admitted controller set its
    environment, so ambient inheritance alone is not an authentic channel for
    the expected runtime hash.
    """
    inherited = os.environ.get(RUNTIME_EXPECTATION_ENV)
    if expected is None:
        expected = inherited
        if expected is None:
            raise WorldAfterstateV2ExecutionError(
                "spawned runtime expectation is missing")
    else:
        _digest(expected, "spawned runtime expectation")
        if inherited is not None and inherited != expected:
            raise WorldAfterstateV2ExecutionError(
                "inherited runtime expectation drift")
    verify_live_runtime_sha256(expected)
    os.environ[RUNTIME_EXPECTATION_ENV] = expected


def verified_process_pool_kwargs() -> dict[str, Any]:
    """Return a strict initializer only inside an admitted controller tree."""
    expected = os.environ.get(RUNTIME_EXPECTATION_ENV)
    if expected is None:
        return {}
    _digest(expected, "inherited runtime expectation")
    return {"initializer": _verify_inherited_runtime_expectation,
            "initargs": (expected,)}


def _torch_profile() -> tuple[str, str]:
    try:
        import torch
        config = torch.__config__.show()
        return str(torch.__version__), _sha_bytes(config.encode("utf-8"))
    except Exception as exc:
        raise WorldAfterstateV2ExecutionError("runtime torch telemetry unavailable") from exc


def _numpy_version() -> str:
    try:
        import numpy
        return str(numpy.__version__)
    except Exception:
        return "absent"


def _loaded_native_file_identity(
        resolved: Path, metadata: os.stat_result) -> dict[str, Any]:
    """Bind Linux's mapped extension inode to the path bytes we hash.

    Hashing the pathname alone cannot distinguish a library already mapped
    from an inode that was atomically replaced before the hash.  Perf Cloud,
    the only V2 execution host, exposes the loaded device/inode in procfs.
    """
    if not sys.platform.startswith("linux"):
        return {"status": "unavailable", "device_major": "unavailable",
                "device_minor": "unavailable", "inode": "unavailable"}
    try:
        rows = _PROC_SELF_MAPS.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        if os.environ.get("SHENGJI_FAST") == "1":
            raise WorldAfterstateV2ExecutionError(
                "loaded native extension telemetry unavailable") from exc
        return {"status": "unavailable", "device_major": "unavailable",
                "device_minor": "unavailable", "inode": "unavailable"}
    mapped: set[tuple[int, int, int]] = set()
    for row in rows:
        fields = row.split(maxsplit=5)
        if len(fields) != 6:
            continue
        mapped_path = fields[5].removesuffix(" (deleted)")
        if mapped_path != str(resolved):
            continue
        try:
            major, minor = (int(value, 16) for value in fields[3].split(":"))
            inode = int(fields[4])
        except (TypeError, ValueError):
            continue
        mapped.add((major, minor, inode))
    expected = (os.major(metadata.st_dev), os.minor(metadata.st_dev),
                metadata.st_ino)
    if expected not in mapped:
        if os.environ.get("SHENGJI_FAST") == "1":
            raise WorldAfterstateV2ExecutionError(
                "loaded native extension inode drift")
        return {"status": "not-loaded", "device_major": expected[0],
                "device_minor": expected[1], "inode": expected[2]}
    return {"status": "verified", "device_major": expected[0],
            "device_minor": expected[1], "inode": expected[2]}


def _native_file_snapshot(path: Path) -> tuple[bytes, os.stat_result]:
    """Read and stat one already-open native inode, never the path twice."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError(
            "native extension telemetry unavailable") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    if (identity(before) != identity(after) or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1 or before.st_size != sum(map(len, chunks))):
        raise WorldAfterstateV2ExecutionError(
            "native extension changed during read")
    return b"".join(chunks), before


def _native_extension_profile() -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec("shengji.engine._fast")
    except (ImportError, ModuleNotFoundError, ValueError):
        spec = None
    origin = None if spec is None else spec.origin
    if origin and origin not in ("built-in", "frozen"):
        path = Path(origin)
        expected_parent = Path(__file__).resolve().parents[1] / "engine"
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise WorldAfterstateV2ExecutionError(
                "native extension telemetry unavailable") from exc
        if (path.is_symlink() or not path.is_file()
                or resolved.parent != expected_parent.resolve()
                or not resolved.name.startswith("_fast.")
                or resolved.suffix.lower() not in {".so", ".dylib", ".pyd"}):
            raise WorldAfterstateV2ExecutionError(
                "native extension origin drift")
        raw, metadata = _native_file_snapshot(resolved)
        return {"status": "present", "path": str(resolved),
                "sha256": _sha_bytes(raw),
                "loaded_file_identity": _loaded_native_file_identity(
                    resolved, metadata)}
    return {"status": "absent", "path": "absent", "sha256": "absent"}


def _torch_threads() -> int:
    try:
        import torch
        return int(torch.get_num_threads())
    except Exception as exc:
        raise WorldAfterstateV2ExecutionError("runtime torch telemetry unavailable") from exc


def _sealed(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise WorldAfterstateV2ExecutionError(f"{label} path drift")
    try:
        with path.open("rb") as handle:
            before, raw = os.fstat(handle.fileno()), handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError(f"{label} cannot be read") from exc
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or before.st_size != len(raw) or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateV2ExecutionError(f"{label} is mutable")
    return raw


def _terminal_route(raw: bytes) -> str:
    value = _strict(raw, "terminal result")
    # The reviewed terminal controller emits ``decision`` in terminal.json;
    # the aliases are accepted only for the non-scientific adapter path.
    route = value.get("decision", value.get("terminal_route", value.get("route")))
    if route not in TERMINAL_ROUTES:
        raise WorldAfterstateV2ExecutionError("terminal route artifact drift")
    return route


def _verify_reconstruction_binding(terminal_raw: bytes,
                                   reconstruction_raw: bytes) -> None:
    """Cross-bind the independent receipt to the exact terminal result."""
    terminal = _strict(terminal_raw, "terminal result")
    reconstruction = _strict(reconstruction_raw, "reconstruction result")
    result_sha = terminal.get("result_sha256")
    sealed_sha = reconstruction.get("sealed_terminal_result_sha256")
    if _digest(result_sha, "terminal result SHA-256") != sealed_sha \
            or reconstruction.get("matched") is not True:
        raise WorldAfterstateV2ExecutionError(
            "reconstruction terminal cross-binding drift")


@dataclass(frozen=True)
class SourceBindingV2:
    path: str
    byte_count: int
    sha256: str

    def payload(self) -> dict[str, Any]:
        _digest(self.sha256, "source binding SHA-256")
        if (type(self.path) is not str or not self.path
                or Path(self.path).is_absolute() or "\\" in self.path
                or any(part in ("", ".", "..") for part in Path(self.path).parts)):
            raise WorldAfterstateV2ExecutionError("source binding path drift")
        if type(self.byte_count) is not int or self.byte_count < 1:
            raise WorldAfterstateV2ExecutionError("source binding byte count drift")
        return {"path": self.path, "byte_count": self.byte_count,
                "sha256": self.sha256}


def source_manifest_sha256(source_git: str,
                           bindings: Sequence[SourceBindingV2]) -> str:
    """Canonical digest used for the complete source closure."""
    _digest(source_git, "source manifest Git", length=40)
    rows = [binding.payload() for binding in bindings]
    paths = [row["path"] for row in rows]
    if (not rows or paths != sorted(paths) or len(set(paths)) != len(paths)):
        raise WorldAfterstateV2ExecutionError("source manifest closure drift")
    return _sha({"schema": "world-afterstate-v2-complete-source-manifest-v1",
                 "source_git": source_git, "files": rows})


@dataclass(frozen=True)
class ExecutionFreezeV2:
    source_git: str
    source_manifest_sha256: str
    runtime_sha256: str
    protocol_sha256: str
    capacity_sha256: str
    population_sha256: str
    config_sha256: str
    seed_sha256: str
    continuation_policy_sha256: str
    evidence_root: str
    boot_identity: str
    source_bindings: tuple[SourceBindingV2, ...] = ()
    runtime_profile: Mapping[str, Any] | None = None
    artifact_bindings: tuple[tuple[str, str, str], ...] = ()
    population_tier: str = "D256"
    deadline_seconds: int = MAX_DEADLINE_SECONDS
    heartbeat_seconds: int = 60
    schema: str = FREEZE_SCHEMA

    def payload(self) -> dict[str, Any]:
        if self.schema != FREEZE_SCHEMA or self.population_tier not in ("D256", "D512", "D1024"):
            raise WorldAfterstateV2ExecutionError("freeze schema/tier drift")
        _digest(self.source_git, "source Git", length=40)
        for key in ("source_manifest_sha256", "runtime_sha256", "protocol_sha256",
                    "capacity_sha256", "population_sha256", "config_sha256",
                    "seed_sha256", "continuation_policy_sha256"):
            _digest(getattr(self, key), key)
        if not isinstance(self.evidence_root, str) or not Path(self.evidence_root).is_absolute():
            raise WorldAfterstateV2ExecutionError("freeze evidence root drift")
        if type(self.runtime_profile) is not dict:
            raise WorldAfterstateV2ExecutionError("runtime profile/hash drift")
        validate_runtime_profile(self.runtime_profile)
        if self.runtime_sha256 != _sha(self.runtime_profile):
            raise WorldAfterstateV2ExecutionError("runtime profile/hash drift")
        if type(self.boot_identity) is not str or not self.boot_identity \
                or self.boot_identity != self.runtime_profile.get("boot_identity"):
            raise WorldAfterstateV2ExecutionError("freeze boot identity drift")
        if type(self.deadline_seconds) is not int or not 1 <= self.deadline_seconds <= MAX_DEADLINE_SECONDS:
            raise WorldAfterstateV2ExecutionError("freeze deadline drift")
        if type(self.heartbeat_seconds) is not int or not 1 <= self.heartbeat_seconds <= 60:
            raise WorldAfterstateV2ExecutionError("freeze heartbeat drift")
        bindings = tuple(row.payload() for row in self.source_bindings)
        if tuple(row["path"] for row in bindings) != tuple(sorted(row["path"] for row in bindings)):
            raise WorldAfterstateV2ExecutionError("source binding order drift")
        if not self.source_bindings:
            raise WorldAfterstateV2ExecutionError("source manifest closure drift")
        if source_manifest_sha256(self.source_git, self.source_bindings) \
                != self.source_manifest_sha256:
            raise WorldAfterstateV2ExecutionError("source manifest/hash drift")
        required_artifacts = ("protocol", "capacity", "population", "config", "seed",
                              "continuation-policy")
        if any(type(row) is not tuple or len(row) != 3 for row in self.artifact_bindings) \
                or tuple(row[0] for row in self.artifact_bindings) != required_artifacts or any(
                row[0] not in (
                "protocol", "capacity", "population", "config", "seed",
                "continuation-policy") for row in self.artifact_bindings):
            raise WorldAfterstateV2ExecutionError("freeze artifact binding drift")
        tops = {"protocol": self.protocol_sha256, "capacity": self.capacity_sha256,
                "population": self.population_sha256, "config": self.config_sha256,
                "seed": self.seed_sha256,
                "continuation-policy": self.continuation_policy_sha256}
        for label, path, digest in self.artifact_bindings:
            _digest(digest, f"{label} artifact SHA-256")
            if (type(path) is not str or not path or Path(path).is_absolute()
                    or "\\" in path or any(part in ("", ".", "..")
                                             for part in Path(path).parts)
                    or digest != tops[label]):
                raise WorldAfterstateV2ExecutionError("freeze artifact binding drift")
        return {
            "schema": self.schema, "source_git": self.source_git,
            "source_manifest_sha256": self.source_manifest_sha256,
            "runtime_sha256": self.runtime_sha256,
            "protocol_sha256": self.protocol_sha256,
            "capacity_sha256": self.capacity_sha256,
            "population_sha256": self.population_sha256,
            "config_sha256": self.config_sha256, "seed_sha256": self.seed_sha256,
            "continuation_policy_sha256": self.continuation_policy_sha256,
            "evidence_root": self.evidence_root, "boot_identity": self.boot_identity,
            "population_tier": self.population_tier,
            "deadline_seconds": self.deadline_seconds,
            "heartbeat_seconds": self.heartbeat_seconds,
            "source_bindings": list(bindings), "authority": dict(AUTHORITY),
            "runtime_profile": dict(self.runtime_profile),
            "artifact_bindings": [list(row) for row in self.artifact_bindings],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())

    def sha256(self) -> str:
        return _sha_bytes(self.canonical_bytes())


def validate_execution_freeze(value: ExecutionFreezeV2) -> None:
    if type(value) is not ExecutionFreezeV2:
        raise WorldAfterstateV2ExecutionError("typed execution freeze required")
    value.payload()


def execution_freeze_from_bytes(raw: bytes) -> ExecutionFreezeV2:
    value = _strict(raw, "execution freeze")
    required = {"schema", "source_git", "source_manifest_sha256", "runtime_sha256",
                "protocol_sha256", "capacity_sha256", "population_sha256",
                "config_sha256", "seed_sha256", "continuation_policy_sha256",
                "evidence_root", "boot_identity", "population_tier", "deadline_seconds",
                "heartbeat_seconds", "source_bindings", "runtime_profile",
                "artifact_bindings", "authority"}
    if set(value) != required or value["authority"] != AUTHORITY \
            or type(value["source_bindings"]) is not list:
        raise WorldAfterstateV2ExecutionError("freeze field population drift")
    bindings = []
    for row in value["source_bindings"]:
        if type(row) is not dict or set(row) != {"path", "byte_count", "sha256"}:
            raise WorldAfterstateV2ExecutionError("source binding field drift")
        bindings.append(SourceBindingV2(**row))
    freeze = ExecutionFreezeV2(
        **{key: value[key] for key in ("source_git", "source_manifest_sha256",
          "runtime_sha256", "protocol_sha256", "capacity_sha256",
          "population_sha256", "config_sha256", "seed_sha256",
          "continuation_policy_sha256", "evidence_root", "population_tier",
          "deadline_seconds", "heartbeat_seconds")},
        boot_identity=value["boot_identity"],
        source_bindings=tuple(bindings), runtime_profile=value["runtime_profile"],
        artifact_bindings=tuple(tuple(row) for row in value["artifact_bindings"]),
        schema=value["schema"])
    validate_execution_freeze(freeze)
    if freeze.canonical_bytes() != raw:
        raise WorldAfterstateV2ExecutionError("freeze reconstruction drift")
    return freeze


def expected_review_claim(freeze: ExecutionFreezeV2) -> dict[str, Any]:
    validate_execution_freeze(freeze)
    return {"schema": "world-afterstate-v2-absolute-leaf-review-v1",
            "freeze_sha256": freeze.sha256(), "source_git": freeze.source_git,
            "source_manifest_sha256": freeze.source_manifest_sha256,
            "runtime_sha256": freeze.runtime_sha256,
            "protocol_sha256": freeze.protocol_sha256,
            "capacity_sha256": freeze.capacity_sha256,
            "population_sha256": freeze.population_sha256,
            "config_sha256": freeze.config_sha256,
            "seed_sha256": freeze.seed_sha256,
            "continuation_policy_sha256": freeze.continuation_policy_sha256,
            "boot_identity": freeze.boot_identity,
            # This is a review claim, not execution authority.  It authorizes
            # exactly one scientific execution and one audit opening for this
            # freeze while retaining the serialized all-false authority map.
            "scientific_execution_authorized": True,
            "audit_opening_authorized": True, "retry_authorized": False,
            "gameplay_authorized": False, "puct_authorized": False,
            "belief_authorized": False, "strength_claim_authorized": False,
            "merge_authorized": False, "deployment_authorized": False}


def authenticate_review_commit(
        freeze: ExecutionFreezeV2, *, repo: Path, review_commit: str,
        canonical_ref: str = "origin/main",
        remote_url: str = CANONICAL_REMOTE_URL,
        remote_ref: str = CANONICAL_REMOTE_REF) -> bytes:
    """Authenticate the sole append-only review marker on canonical main."""
    validate_execution_freeze(freeze)
    _digest(review_commit, "review commit", length=40)
    if not isinstance(repo, Path) or not repo.is_absolute() or not canonical_ref \
            or not isinstance(remote_url, str) or not remote_url \
            or not isinstance(remote_ref, str) or not remote_ref:
        raise WorldAfterstateV2ExecutionError("review input drift")
    try:
        local_tip = str(_git(repo, "rev-parse", canonical_ref))
        remote = subprocess.run(("git", "ls-remote", "--exit-code", remote_url,
                                 remote_ref), cwd=repo, check=True,
                                capture_output=True, text=True).stdout.splitlines()
        fields = remote[0].split() if len(remote) == 1 else ()
        if len(fields) != 2 or fields[1] != remote_ref or fields[0] != local_tip:
            raise WorldAfterstateV2ExecutionError("canonical remote tip drift")
        if subprocess.run(("git", "merge-base", "--is-ancestor", review_commit,
                           canonical_ref), cwd=repo, capture_output=True).returncode != 0:
            raise WorldAfterstateV2ExecutionError("review is not on canonical main")
        parent = str(_git(repo, "show", "-s", "--format=%P", review_commit)).split()
        if len(parent) != 1:
            raise WorldAfterstateV2ExecutionError("review parent drift")
        identity = tuple(str(_git(repo, "show", "-s", f"--format={field}", review_commit))
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (REVIEWER_NAME, REVIEWER_EMAIL, REVIEWER_NAME, REVIEWER_EMAIL):
            raise WorldAfterstateV2ExecutionError("review actor drift")
        if REVIEWER_SESSION_TRAILER not in str(_git(repo, "show", "-s", "--format=%B", review_commit)):
            raise WorldAfterstateV2ExecutionError("review session drift")
        changed = str(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", review_commit)).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise WorldAfterstateV2ExecutionError("review file scope drift")
        current = _git(repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(repo, "show", f"{parent[0]}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV2ExecutionError("review Git authentication failed") from exc
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(expected_review_claim(freeze))
    prefix = REVIEW_PREFIX.encode("ascii")
    if not isinstance(current, bytes) or not isinstance(previous, bytes) or not current.startswith(previous):
        raise WorldAfterstateV2ExecutionError("review ledger is not append-only")
    current_matches = [line for line in current.splitlines(keepends=True) if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True) if line.startswith(prefix)]
    if current_matches != [*previous_matches, marker] \
            or marker in previous_matches:
        raise WorldAfterstateV2ExecutionError("review marker does not bind freeze")
    return marker


@dataclass(frozen=True)
class PipelineAdmissionV2:
    freeze_sha256: str
    source_git: str
    source_manifest_sha256: str
    review_commit: str
    review_marker_sha256: str
    evidence_root: str
    schema: str = ADMISSION_SCHEMA

    def payload(self) -> dict[str, Any]:
        _digest(self.freeze_sha256, "admission freeze SHA-256")
        _digest(self.source_manifest_sha256, "admission source manifest SHA-256")
        _digest(self.review_marker_sha256, "admission review marker SHA-256")
        _digest(self.source_git, "admission source Git", length=40)
        _digest(self.review_commit, "admission review commit", length=40)
        if self.schema != ADMISSION_SCHEMA or not isinstance(self.evidence_root, str):
            raise WorldAfterstateV2ExecutionError("admission schema/root drift")
        return {"schema": self.schema, "freeze_sha256": self.freeze_sha256,
                "source_git": self.source_git,
                "source_manifest_sha256": self.source_manifest_sha256,
                "review_commit": self.review_commit,
                "review_marker_sha256": self.review_marker_sha256,
                "evidence_root": self.evidence_root, "authority": dict(AUTHORITY)}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())

    def sha256(self) -> str:
        return _sha_bytes(self.canonical_bytes())


def build_admission(freeze: ExecutionFreezeV2, *, review_commit: str,
                    review_marker: bytes) -> PipelineAdmissionV2:
    validate_execution_freeze(freeze)
    expected = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(expected_review_claim(freeze))
    if type(review_marker) is not bytes or review_marker != expected:
        raise WorldAfterstateV2ExecutionError("admission review marker drift")
    result = PipelineAdmissionV2(freeze.sha256(), freeze.source_git,
        freeze.source_manifest_sha256, review_commit, _sha_bytes(review_marker),
        freeze.evidence_root)
    validate_admission(result, freeze=freeze, review_marker=review_marker)
    return result


def validate_admission(admission: PipelineAdmissionV2, *, freeze: ExecutionFreezeV2,
                       review_marker: bytes) -> None:
    if type(admission) is not PipelineAdmissionV2 or admission.payload()["authority"] != AUTHORITY \
            or admission.freeze_sha256 != freeze.sha256() \
            or admission.source_git != freeze.source_git \
            or admission.source_manifest_sha256 != freeze.source_manifest_sha256 \
            or admission.evidence_root != freeze.evidence_root:
        raise WorldAfterstateV2ExecutionError("admission identity drift")
    expected = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(expected_review_claim(freeze))
    if review_marker != expected or admission.review_marker_sha256 != _sha_bytes(review_marker):
        raise WorldAfterstateV2ExecutionError("admission marker drift")


def admission_from_bytes(raw: bytes, *, freeze: ExecutionFreezeV2,
                         review_marker: bytes) -> PipelineAdmissionV2:
    value = _strict(raw, "admission")
    required = {"schema", "freeze_sha256", "source_git", "source_manifest_sha256",
                "review_commit", "review_marker_sha256", "evidence_root", "authority"}
    if set(value) != required or value["authority"] != AUTHORITY:
        raise WorldAfterstateV2ExecutionError("admission field population drift")
    result = PipelineAdmissionV2(**{key: value[key] for key in required if key != "authority"})
    validate_admission(result, freeze=freeze, review_marker=review_marker)
    if result.canonical_bytes() != raw:
        raise WorldAfterstateV2ExecutionError("admission reconstruction drift")
    return result


pipeline_admission_from_bytes = admission_from_bytes


def consumption_tombstone_path(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute():
        raise WorldAfterstateV2ExecutionError("evidence root path drift")
    return root.parent / f".{root.name}.admission.tombstone"


def pipeline_consumption_tombstone_bytes(admission: PipelineAdmissionV2) -> bytes:
    if type(admission) is not PipelineAdmissionV2:
        raise WorldAfterstateV2ExecutionError("tombstone admission drift")
    return canonical_json_bytes({"schema": TOMBSTONE_SCHEMA,
        "admission_sha256": admission.sha256(), "freeze_sha256": admission.freeze_sha256,
        "review_commit": admission.review_commit, "evidence_root": admission.evidence_root,
        "initialization_consumed": True, "retry_authorized": False,
        "authority": dict(AUTHORITY)})


def validate_pipeline_consumption_tombstone(raw: bytes, *, admission: PipelineAdmissionV2) -> None:
    if type(raw) is not bytes or raw != pipeline_consumption_tombstone_bytes(admission):
        raise WorldAfterstateV2ExecutionError("tombstone drift")


def _refuse_source_bytecode(freeze: ExecutionFreezeV2, repo: Path) -> None:
    """Reject ignored bytecode before any bound source can be imported."""
    prefixes = {((repo / binding.path).parent).resolve()
                for binding in freeze.source_bindings}
    for extra in (repo / "server" / "shengji", repo / "server" / "scripts"):
        if extra.is_dir():
            prefixes.add(extra.resolve())
    for prefix in prefixes:
        if not prefix.is_dir():
            continue
        for current, dirs, files in os.walk(prefix, topdown=True, followlinks=False):
            dirs[:] = [name for name in dirs if name != ".git"]
            if "__pycache__" in dirs:
                raise WorldAfterstateV2ExecutionError(
                    "source bytecode artifact before admission")
            if any(name.endswith(".pyc") for name in files):
                raise WorldAfterstateV2ExecutionError(
                    "source bytecode artifact before admission")


def _verify_source_before_admission(
        freeze: ExecutionFreezeV2, repo: Path, *,
        verify_live_runtime: bool = True) -> None:
    _refuse_source_bytecode(freeze, repo)
    if freeze.runtime_sha256 != _sha(freeze.runtime_profile) \
            or (verify_live_runtime and (
                freeze.boot_identity != _boot_identity()
                or dict(freeze.runtime_profile) != live_runtime_profile())):
        raise WorldAfterstateV2ExecutionError("runtime identity drift before admission")
    try:
        source_is_ancestor = subprocess.run(
            ("git", "merge-base", "--is-ancestor", freeze.source_git, "HEAD"),
            cwd=repo, capture_output=True).returncode == 0
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError("source ancestry verification failed") from exc
    if not source_is_ancestor \
            or str(_git(repo, "status", "--porcelain", "--untracked-files=all")):
        raise WorldAfterstateV2ExecutionError("source checkout mutation before admission")
    if freeze.source_bindings and source_manifest_sha256(
            freeze.source_git, freeze.source_bindings) != freeze.source_manifest_sha256:
        raise WorldAfterstateV2ExecutionError("source manifest derivation drift")
    for binding in freeze.source_bindings:
        path = repo / binding.path
        if path.is_symlink() or not path.is_file():
            raise WorldAfterstateV2ExecutionError("source binding path drift")
        raw = path.read_bytes()
        committed = _git(repo, "show", f"{freeze.source_git}:{binding.path}", binary=True)
        if raw != committed or len(raw) != binding.byte_count or _sha_bytes(raw) != binding.sha256:
            raise WorldAfterstateV2ExecutionError("source checkout mutation before admission")


def verify_frozen_artifacts(freeze: ExecutionFreezeV2, *, root: Path,
                            base: Path | None = None) -> None:
    """Rehash optional frozen protocol/config artifacts before admission."""
    for name, relative, expected in freeze.artifact_bindings:
        _digest(expected, f"{name} artifact SHA-256")
        path = root / relative
        if not path.exists() and base is not None:
            path = base / relative
        if path.is_symlink() or not path.is_file():
            raise WorldAfterstateV2ExecutionError(f"{name} artifact missing")
        raw = path.read_bytes()
        if _sha_bytes(raw) != expected:
            raise WorldAfterstateV2ExecutionError(f"{name} artifact mutation before admission")


def initialize_admission(root: Path, *, freeze_raw: bytes, repo: Path,
                         review_commit: str, canonical_ref: str = "origin/main",
                         remote_url: str = CANONICAL_REMOTE_URL,
                         remote_ref: str = CANONICAL_REMOTE_REF) -> PipelineAdmissionV2:
    """Spend one admission, leaving a sibling tombstone that survives root deletion."""
    freeze = execution_freeze_from_bytes(freeze_raw)
    if Path(freeze.evidence_root).resolve() != root.resolve():
        raise WorldAfterstateV2ExecutionError("evidence root differs from freeze")
    try:
        _verify_source_before_admission(freeze, repo)
        verify_frozen_artifacts(freeze, root=root, base=repo)
        marker = authenticate_review_commit(freeze, repo=repo, review_commit=review_commit,
                                            canonical_ref=canonical_ref,
                                            remote_url=remote_url, remote_ref=remote_ref)
        admission = build_admission(freeze, review_commit=review_commit, review_marker=marker)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV2ExecutionError("admission source verification failed") from exc
    tombstone = consumption_tombstone_path(root)
    if tombstone.exists() or tombstone.is_symlink() or root.exists() or root.is_symlink():
        raise WorldAfterstateV2ExecutionError("one-admission namespace occupied")
    _write_once(tombstone, pipeline_consumption_tombstone_bytes(admission))
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write_once(root / "freeze.json", freeze.canonical_bytes())
    _write_once(root / "admission.json", admission.canonical_bytes())
    (root / "events").mkdir(mode=0o700)
    meta = {"schema": META_SCHEMA, "freeze_sha256": freeze.sha256(),
            "admission_sha256": admission.sha256(),
            "started_monotonic_ns": time.monotonic_ns(),
            "boot_identity": _boot_identity(), "authority": dict(AUTHORITY)}
    meta["meta_sha256"] = _sha(meta)
    _write_once(root / "supervisor-meta.json", canonical_json_bytes(meta))
    _fsync_dir(root)
    return admission


def reopen_admission(root: Path, *, freeze: ExecutionFreezeV2,
                     review_marker: bytes, repo: Path | None = None,
                     resource_closeout_only: bool = False) -> PipelineAdmissionV2:
    # A monotonic deadline is meaningful only on the same runtime image.  The
    # persisted boot witness below catches reboot; this profile check catches
    # interpreter/runtime replacement before any stage can resume.
    if type(resource_closeout_only) is not bool:
        raise WorldAfterstateV2ExecutionError("resource closeout mode drift")
    if type(freeze.runtime_profile) is not dict \
            or freeze.runtime_sha256 != _sha(freeze.runtime_profile) \
            or (not resource_closeout_only and (
                freeze.boot_identity != _boot_identity()
                or dict(freeze.runtime_profile) != live_runtime_profile())):
        raise WorldAfterstateV2ExecutionError("runtime identity drift on resume")
    if repo is not None:
        _verify_source_before_admission(
            freeze, repo, verify_live_runtime=not resource_closeout_only)
        verify_frozen_artifacts(freeze, root=root, base=repo)
    freeze_value = execution_freeze_from_bytes(_sealed(root / "freeze.json", "freeze"))
    if freeze_value != freeze:
        raise WorldAfterstateV2ExecutionError("frozen input drift")
    admission = admission_from_bytes(_sealed(root / "admission.json", "admission"),
                                     freeze=freeze, review_marker=review_marker)
    validate_pipeline_consumption_tombstone(
        _sealed(consumption_tombstone_path(root), "admission tombstone"), admission=admission)
    return admission


@dataclass(frozen=True)
class ProgressSnapshotV2:
    stage: str
    substage: str
    completed: int
    total: int
    active_workers: int
    active_threads: int
    cpu_utilization_ppm: int
    cgroup_memory_bytes: int
    peak_cgroup_memory_bytes: int
    elapsed_nanoseconds: int
    eta_nanoseconds: int | None
    deadline_headroom_nanoseconds: int
    sealed_shards: int
    sealed_checkpoints: int

    def payload(self) -> dict[str, Any]:
        if self.stage not in STAGE_ORDER or self.substage == "":
            raise WorldAfterstateV2ExecutionError("progress stage drift")
        if self.eta_nanoseconds is not None \
                and (type(self.eta_nanoseconds) is not int
                     or self.eta_nanoseconds < 0):
            raise WorldAfterstateV2ExecutionError("progress ETA drift")
        if any(type(value) is not int or value < 0 for value in (
                self.completed, self.total, self.active_workers, self.active_threads,
                self.cpu_utilization_ppm, self.cgroup_memory_bytes,
                self.peak_cgroup_memory_bytes, self.elapsed_nanoseconds,
                self.deadline_headroom_nanoseconds, self.sealed_shards,
                self.sealed_checkpoints)) or self.completed > self.total:
            raise WorldAfterstateV2ExecutionError("progress accounting drift")
        return {"schema": PROGRESS_SCHEMA, **self.__dict__, "authority": dict(AUTHORITY)}


class DurableProgressSinkV2:
    """Append-only, restart-safe operational progress under an evidence root.

    Progress is deliberately kept in its own namespace.  It is bound to the
    freeze and admission so an operator cannot accidentally combine telemetry
    from two runs, but it is not read by :class:`StageSupervisorV2` when
    reconstructing scientific stage state.
    """

    def __init__(self, root: Path, *, freeze: ExecutionFreezeV2,
                 admission: PipelineAdmissionV2) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise WorldAfterstateV2ExecutionError("progress root path drift")
        validate_execution_freeze(freeze)
        if (root.resolve() != Path(freeze.evidence_root).resolve()
                or type(admission) is not PipelineAdmissionV2
                or admission.freeze_sha256 != freeze.sha256()
                or admission.evidence_root != freeze.evidence_root):
            raise WorldAfterstateV2ExecutionError("progress admission identity drift")
        self.root = root
        self.freeze = freeze
        self.admission = admission
        # The root's immutable identity files are the authority for a
        # reopened sink.  This also refuses a foreign admission before any
        # progress event happens to exist.
        if (_sealed(root / "freeze.json", "progress freeze")
                != freeze.canonical_bytes()
                or _sealed(root / "admission.json", "progress admission")
                != admission.canonical_bytes()):
            raise WorldAfterstateV2ExecutionError("progress root identity drift")
        self.directory = root / PROGRESS_DIRECTORY
        if self.directory.exists() and (self.directory.is_symlink()
                                        or not self.directory.is_dir()):
            raise WorldAfterstateV2ExecutionError("progress directory drift")
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        self._event_index = self._validate_prefix()

    def _validate_prefix(self) -> int:
        paths = sorted(self.directory.iterdir())
        indices: list[int] = []
        for path in paths:
            if path.is_symlink() or not path.is_file() \
                    or path.suffix != ".json" or not path.stem.isdigit():
                raise WorldAfterstateV2ExecutionError("progress event path drift")
            if len(path.stem) != 8:
                raise WorldAfterstateV2ExecutionError("progress event index drift")
            indices.append(int(path.stem))
        if len(indices) > MAX_PROGRESS_EVENTS \
                or indices != list(range(len(indices))):
            raise WorldAfterstateV2ExecutionError("progress event prefix drift")
        for index, path in zip(indices, paths):
            raw = _sealed(path, "progress event")
            if len(raw) > MAX_PROGRESS_EVENT_BYTES:
                raise WorldAfterstateV2ExecutionError("progress event is too large")
            event = _strict(raw, "progress event")
            required = {"schema", "index", "freeze_sha256",
                        "admission_sha256", "snapshot", "authority",
                        "event_sha256"}
            if set(event) != required or event["schema"] != PROGRESS_EVENT_SCHEMA \
                    or type(event["index"]) is not int \
                    or event["index"] != index \
                    or event["freeze_sha256"] != self.freeze.sha256() \
                    or event["admission_sha256"] != self.admission.sha256() \
                    or event["authority"] != AUTHORITY \
                    or event["event_sha256"] != _sha({
                        key: value for key, value in event.items()
                        if key != "event_sha256"}):
                raise WorldAfterstateV2ExecutionError("progress event binding drift")
            self._validate_snapshot(event["snapshot"])
        return len(indices)

    @staticmethod
    def _validate_snapshot(snapshot: Any) -> dict[str, Any]:
        if type(snapshot) is not dict:
            raise WorldAfterstateV2ExecutionError("progress snapshot drift")
        required = {"schema", "stage", "substage", "completed", "total",
                    "active_workers", "active_threads", "cpu_utilization_ppm",
                    "cgroup_memory_bytes", "peak_cgroup_memory_bytes",
                    "elapsed_nanoseconds", "eta_nanoseconds",
                    "deadline_headroom_nanoseconds", "sealed_shards",
                    "sealed_checkpoints", "authority"}
        if set(snapshot) != required or snapshot.get("schema") != PROGRESS_SCHEMA \
                or snapshot.get("authority") != AUTHORITY:
            raise WorldAfterstateV2ExecutionError("progress snapshot binding drift")
        body = {key: value for key, value in snapshot.items()
                if key not in ("schema", "authority")}
        try:
            expected = ProgressSnapshotV2(**body).payload()
        except (TypeError, ValueError) as exc:
            raise WorldAfterstateV2ExecutionError("progress snapshot drift") from exc
        if expected != snapshot:
            raise WorldAfterstateV2ExecutionError("progress snapshot canonical drift")
        return snapshot

    @property
    def next_index(self) -> int:
        return self._event_index

    def __call__(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Durably append one canonical callback snapshot and return its event."""
        snapshot_value = self._validate_snapshot(dict(snapshot)
                                                 if isinstance(snapshot, Mapping)
                                                 else snapshot)
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            # Parent heartbeat and controller subprocess callbacks share this
            # sink.  Reopen the prefix while holding the directory lock rather
            # than trusting either process's stale local counter.
            self._event_index = self._validate_prefix()
            if self._event_index >= MAX_PROGRESS_EVENTS:
                raise WorldAfterstateV2ExecutionError(
                    "progress event bound exceeded")
            event = {"schema": PROGRESS_EVENT_SCHEMA,
                     "index": self._event_index,
                     "freeze_sha256": self.freeze.sha256(),
                     "admission_sha256": self.admission.sha256(),
                     "snapshot": snapshot_value,
                     "authority": dict(AUTHORITY)}
            event["event_sha256"] = _sha(event)
            raw = canonical_json_bytes(event)
            if len(raw) > MAX_PROGRESS_EVENT_BYTES:
                raise WorldAfterstateV2ExecutionError(
                    "progress event is too large")
            _write_once(
                self.directory / f"{self._event_index:08d}.json", raw)
            self._event_index += 1
            return event
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


# Short compatibility name for callers that treat this as a callback sink.
ProgressSinkV2 = DurableProgressSinkV2


@dataclass(frozen=True)
class StageStateV2:
    completed_stages: tuple[str, ...] = ()
    terminal_route: str | None = None
    audit_opened: bool = False
    reconstruction_completed: bool = False
    verified_shards: tuple[tuple[str, str], ...] = ()

    def payload(self) -> dict[str, Any]:
        if any(stage not in STAGE_ORDER for stage in self.completed_stages) \
                or len(set(self.completed_stages)) != len(self.completed_stages):
            raise WorldAfterstateV2ExecutionError("stage completion order drift")
        terminal_index = next((index for index, stage in enumerate(
            self.completed_stages) if stage in TERMINAL_STAGE_ORDER),
            len(self.completed_stages))
        work = self.completed_stages[:terminal_index]
        terminal = self.completed_stages[terminal_index:]
        if work != WORK_STAGE_ORDER[:len(work)] \
                or terminal not in ((), ("terminal",),
                                    ("terminal", "reconstruction")):
            raise WorldAfterstateV2ExecutionError("stage completion order drift")
        if self.terminal_route is not None and self.terminal_route not in TERMINAL_ROUTES:
            raise WorldAfterstateV2ExecutionError("terminal route drift")
        if self.audit_opened and "audit-attempt" not in self.completed_stages:
            # A crash after the marker fsync but while audit-label shards are
            # being built is a legitimate resumable state.  No earlier stage
            # may carry the marker, and no later stage may hide the incomplete
            # audit producer.
            if work != WORK_STAGE_ORDER[:-1] or terminal:
                raise WorldAfterstateV2ExecutionError("audit state drift")
        if self.reconstruction_completed != (
                "reconstruction" in self.completed_stages):
            raise WorldAfterstateV2ExecutionError("reconstruction state drift")
        if "terminal" in self.completed_stages \
                and self.terminal_route is None:
            raise WorldAfterstateV2ExecutionError("terminal stage route drift")
        if len({row[0] for row in self.verified_shards}) != len(self.verified_shards) \
                or any(type(row) is not tuple or len(row) != 2
                       or type(row[0]) is not str or not row[0]
                       or (type(row[1]) is not str or len(row[1]) != 64)
                       for row in self.verified_shards):
            raise WorldAfterstateV2ExecutionError("verified shard state drift")
        return {"schema": STATE_SCHEMA, "completed_stages": list(self.completed_stages),
                "terminal_route": self.terminal_route, "audit_opened": self.audit_opened,
                "reconstruction_completed": self.reconstruction_completed,
                "verified_shards": [list(row) for row in self.verified_shards],
                "authority": dict(AUTHORITY)}


def reopen_resource_incomplete_closeout(
        raw: bytes, *, freeze: ExecutionFreezeV2,
        admission: PipelineAdmissionV2) -> dict[str, Any]:
    """Reopen the receipt-only terminal route used after a hard stop."""
    value = _strict(raw, "resource-incomplete closeout")
    required = {"schema", "freeze_sha256", "admission_sha256", "decision",
                "resource_stage", "completed_stages", "audit_opened_count",
                "reconstruction_completed", "verified_shards",
                "prior_terminal_route",
                "original_boot_identity", "closeout_boot_identity",
                "cross_boot", "authority", "closeout_sha256"}
    body = {key: item for key, item in value.items()
            if key != "closeout_sha256"}
    if set(value) != required or value["schema"] != RESOURCE_CLOSEOUT_SCHEMA \
            or value["freeze_sha256"] != freeze.sha256() \
            or value["admission_sha256"] != admission.sha256() \
            or value["decision"] != "REFUSE_RESOURCE_INCOMPLETE" \
            or value["authority"] != AUTHORITY \
            or value["closeout_sha256"] != _sha(body):
        raise WorldAfterstateV2ExecutionError(
            "resource-incomplete closeout identity drift")
    if type(value["resource_stage"]) is not str \
            or value["resource_stage"] not in (*STAGE_ORDER, "unknown") \
            or type(value["audit_opened_count"]) is not int \
            or value["audit_opened_count"] not in (0, 1) \
            or type(value["cross_boot"]) is not bool \
            or type(value["original_boot_identity"]) is not str \
            or not value["original_boot_identity"] \
            or type(value["closeout_boot_identity"]) is not str \
            or not value["closeout_boot_identity"] \
            or value["cross_boot"] != (
                value["original_boot_identity"]
                != value["closeout_boot_identity"]):
        raise WorldAfterstateV2ExecutionError(
            "resource-incomplete closeout field drift")
    try:
        prior_route = value["prior_terminal_route"]
        if prior_route is not None and prior_route not in TERMINAL_ROUTES:
            raise ValueError("prior terminal route")
        state = StageStateV2(
            completed_stages=tuple(value["completed_stages"]),
            terminal_route=(prior_route or "REFUSE_RESOURCE_INCOMPLETE"),
            audit_opened=value["audit_opened_count"] == 1,
            reconstruction_completed=value["reconstruction_completed"],
            verified_shards=tuple(tuple(row)
                                   for row in value["verified_shards"]))
        state.payload()
    except (TypeError, ValueError) as exc:
        raise WorldAfterstateV2ExecutionError(
            "resource-incomplete closeout state drift") from exc
    return value


CONTROLLER_BINDINGS = {
    "population": ("collect_population_v2", "reopen_population_collection_v2"),
    "fit-select-labels": ("build_fit_select_continuations_v2",),
    "p0-labels-gates": ("evaluate_precision_label",),
    "optimizer-canary": ("run_optimizer_canary_v2",),
    "nested-curve": ("run_nested_curve_v2",),
    "block-1-natural": ("train_named_cohort",),
    "block-1-controls": ("train_named_cohort",),
    "block-2-natural": ("train_named_cohort",),
    "block-2-controls": ("train_named_cohort",),
    "precision-select-power": ("evaluate_precision_select_v2",),
    "audit-attempt": ("publish_audit_attempt",),
    "terminal": ("run_terminal_v2",),
    # run_terminal_v2 performs the one immediate reconstruction itself.  The
    # later stage only verifies that sealed receipt; it must never rescore.
    "reconstruction": ("verify_terminal_artifact_v2",),
}

TERMINAL_RESULT_RELATIVE = "terminal/terminal.json"
RECONSTRUCTION_RESULT_RELATIVE = "terminal/independent-reconstruction.json"
AUDIT_PREFLIGHT_RELATIVE = "audit-preflight.json"
AUDIT_PREFLIGHT_SCHEMA = "world-afterstate-v2-audit-preflight-v2"
AUDIT_PREFLIGHT_STAGES = STAGE_ORDER[:STAGE_ORDER.index("audit-attempt")]
AUDIT_UNOPENED_PATHS = (
    "audit-attempt.json", "audit-continuations", "terminal-inputs.json",
)
STAGE_ADAPTER_ABI = "world-afterstate-v2-stage-adapter-supervisor-shards-v1"
PRODUCTION_STAGE_ADAPTER_MODULES = frozenset({
    "shengji.rl.world_afterstate_v2_stage_adapters",
    "shengji.rl.world_afterstate_v2_training_stage_adapters",
    "shengji.rl.world_afterstate_v2_late_stage_adapters",
})


def _production_callable(name: str) -> Callable[..., Any] | None:
    """Resolve only callables imported from the existing V2 boundaries."""
    modules = {
        "collect_population_v2": "world_afterstate_v2_population_controller",
        "reopen_population_collection_v2": "world_afterstate_v2_population_controller",
        "build_fit_select_continuations_v2": "world_afterstate_v2_stage_adapters",
        "evaluate_precision_label": "world_afterstate_v2_label",
        "train_named_cohort": "world_afterstate_v2_training_controller",
        "run_terminal_v2": "world_afterstate_v2_terminal_controller",
        "verify_terminal_artifact_v2": "world_afterstate_v2_terminal_controller",
        # Early diagnostics are exposed through closed stage adapters.  Keep
        # the historical controller names in the execution ABI while binding
        # their producer identity to the reviewed producer functions.
        "run_optimizer_canary_v2": "world_afterstate_v2_diagnostic_producers",
        "run_nested_curve_v2": "world_afterstate_v2_diagnostic_producers",
        # These boundaries are intentionally exported by the closed adapter
        # module.  They are not available as direct low-level controllers.
        "evaluate_precision_select_v2": "world_afterstate_v2_stage_adapters",
        "publish_audit_attempt": "world_afterstate_v2_stage_adapters",
    }
    module_name = modules.get(name)
    if module_name is None:
        return None
    try:
        module = __import__(f"shengji.rl.{module_name}", fromlist=[name])
    except ImportError:
        # An unavailable reviewed boundary is a missing stage, not permission
        # to fall back to an untyped callback.
        return None
    aliases = {"run_optimizer_canary_v2": "produce_optimizer_canary_v2",
               "run_nested_curve_v2": "produce_nested_curve_v2"}
    value = getattr(module, aliases.get(name, name), None)
    return value if callable(value) else None


@dataclass(frozen=True)
class StageControllerV2:
    """Typed binding to one existing controller/artifact boundary.

    The supervisor accepts this wrapper rather than an unlabelled callback.
    Missing names (notably the not-yet-implemented nested curve) fail closed.
    """
    stage: str
    controller_name: str
    operation: Callable[..., Any]
    production: bool = False
    stage_payload: Mapping[str, Any] | None = None
    stage_payload_factory: Callable[[Any], Mapping[str, Any]] | None = None

    def validate(self) -> None:
        if self.stage not in STAGE_ORDER \
                or self.controller_name not in CONTROLLER_BINDINGS[self.stage] \
                or not callable(self.operation):
            raise MissingStageError(f"typed controller binding missing for {self.stage}")
        if self.production:
            # Low-level controllers are never accepted directly.  A composed
            # adapter must advertise the exact supervisor ABI and be supplied
            # by the closed production factory; callers cannot mint this by
            # renaming a lambda or by asserting a controller string.
            producer = getattr(self.operation, "producer", None)
            if (getattr(self.operation, "__world_afterstate_v2_stage_adapter__", None)
                    != STAGE_ADAPTER_ABI
                    or producer is not _production_callable(self.controller_name)
                    or type(self.operation).__module__
                    not in PRODUCTION_STAGE_ADAPTER_MODULES):
                raise MissingStageError(
                    f"stage adapter ABI unavailable for {self.stage}:"
                    f" {self.controller_name}")
            if self.stage == "audit-attempt":
                owner = getattr(self.stage_payload_factory, "__self__", None)
                if (self.stage_payload is not None
                        or not callable(self.stage_payload_factory)
                        or owner is not self.operation
                        or getattr(self.stage_payload_factory, "__name__", None)
                        != "prepare_stage_payload"):
                    raise MissingStageError(
                        "audit-attempt preflight producer unavailable")
            elif self.stage_payload_factory is not None:
                raise MissingStageError(
                    f"unexpected stage payload producer for {self.stage}")
        elif (getattr(self.operation, "__module__", "")
              != "world_afterstate_v2_test_adapter"):
            raise MissingStageError(f"typed controller binding missing for {self.stage}")


@dataclass(frozen=True)
class NonScientificStageControllerV2:
    """Test/integration adapter which is never executable by the supervisor."""
    stage: str
    controller_name: str
    operation: Callable[..., Any]


def bind_stage_controller(stage: str, operation: Callable[..., Any], *,
                          controller_name: str) -> NonScientificStageControllerV2:
    """Create an explicitly non-scientific adapter for guard tests only."""
    if stage not in STAGE_ORDER or controller_name not in CONTROLLER_BINDINGS[stage] \
            or not callable(operation):
        raise MissingStageError(f"non-scientific adapter binding missing for {stage}")
    return NonScientificStageControllerV2(stage, controller_name, operation)


def _closed_production_stage_adapter(stage: str, *, freeze: ExecutionFreezeV2,
                                     repo: Path) -> Callable[..., Any]:
    """Obtain a stage only through the reviewed, closed adapter factory."""
    try:
        from .world_afterstate_v2_stage_adapters import production_stage_adapter
    except ImportError as exc:
        raise MissingStageError(
            f"closed production stage factory unavailable for {stage}") from exc
    try:
        return production_stage_adapter(stage, freeze=freeze, repo=repo)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise MissingStageError(
            f"closed production stage adapter unavailable for {stage}") from exc


def _production_binding(stage: str, *, freeze: ExecutionFreezeV2,
                        repo: Path) -> StageControllerV2:
    names = CONTROLLER_BINDINGS.get(stage, ())
    if not names:
        raise MissingStageError(f"existing typed controller unavailable for {stage}")
    operation = _closed_production_stage_adapter(stage, freeze=freeze, repo=repo)
    try:
        producer = getattr(operation, "producer", None)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise MissingStageError(
            f"closed production stage adapter unavailable for {stage}") from exc
    for name in names:
        if producer is _production_callable(name):
            result = StageControllerV2(
                stage, name, operation, production=True,
                stage_payload_factory=getattr(
                    operation, "prepare_stage_payload", None),
            )
            result.validate()
            return result
    raise MissingStageError(f"existing typed controller unavailable for {stage}")


def bind_production_stage_controller(stage: str, *, freeze: ExecutionFreezeV2,
                                     repo: Path) -> StageControllerV2:
    """Bind one stage from the closed factory and frozen repository inputs."""
    if freeze is None or repo is None:
        raise TypeError("production stage binding requires freeze and repo")
    return _production_binding(stage, freeze=freeze, repo=repo)


def validate_production_stage_set(*, freeze: ExecutionFreezeV2,
                                  repo: Path) -> tuple[str, ...]:
    """Return absent reviewed stage producers without consuming admission."""
    if freeze is None or repo is None:
        raise TypeError("production stage set requires freeze and repo")
    missing = []
    for stage in STAGE_ORDER:
        try:
            _production_binding(stage, freeze=freeze, repo=repo)
        except (MissingStageError, ValueError):
            missing.append(f"{stage}:{CONTROLLER_BINDINGS[stage][0]}")
    return tuple(missing)


def production_stage_controllers(*, freeze: ExecutionFreezeV2,
                                 repo: Path) -> dict[str, StageControllerV2]:
    """Build the complete closed production set without consuming admission."""
    missing = validate_production_stage_set(freeze=freeze, repo=repo)
    if missing:
        raise MissingStageError("reviewed stage producer unavailable: " + ", ".join(missing))
    result = {stage: bind_production_stage_controller(stage, freeze=freeze, repo=repo)
              for stage in STAGE_ORDER}
    if tuple(result) != STAGE_ORDER:
        raise MissingStageError("production stage order binding drift")
    return result


@dataclass
class StageSupervisorV2:
    root: Path
    freeze: ExecutionFreezeV2
    admission: PipelineAdmissionV2
    clock: Callable[[], int] = time.monotonic_ns
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    resource_closeout_only: bool = False
    _started: int = field(default_factory=time.monotonic_ns, repr=False)
    _state: StageStateV2 = field(default_factory=StageStateV2, repr=False)
    _event_index: int = field(default=0, repr=False)
    _last_progress: int = field(default=0, repr=False)
    _peak_memory: int = field(default=0, repr=False)
    _telemetry_started: int = field(default=0, repr=False)
    _process_cpu_baseline: int | None = field(default=None, repr=False)
    _cgroup_directory: Path | None = field(default=None, repr=False)
    _cgroup_cpu_baseline: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.resource_closeout_only) is not bool:
            raise WorldAfterstateV2ExecutionError(
                "resource closeout mode drift")
        validate_execution_freeze(self.freeze)
        validate_admission(self.admission, freeze=self.freeze,
                           review_marker=REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(expected_review_claim(self.freeze)))
        if self.root.resolve() != Path(self.freeze.evidence_root).resolve():
            raise WorldAfterstateV2ExecutionError("supervisor root drift")
        meta = _strict(_sealed(self.root / "supervisor-meta.json", "supervisor metadata"),
                       "supervisor metadata")
        if set(meta) != {"schema", "freeze_sha256", "admission_sha256",
                         "started_monotonic_ns", "boot_identity", "authority",
                         "meta_sha256"} or meta["schema"] != META_SCHEMA \
                or meta["freeze_sha256"] != self.freeze.sha256() \
                or meta["admission_sha256"] != self.admission.sha256() \
                or meta["authority"] != AUTHORITY or meta["meta_sha256"] != _sha({
                    key: value for key, value in meta.items() if key != "meta_sha256"}):
            raise WorldAfterstateV2ExecutionError("supervisor metadata drift")
        if type(meta["started_monotonic_ns"]) is not int or meta["started_monotonic_ns"] < 0:
            raise WorldAfterstateV2ExecutionError("supervisor deadline metadata drift")
        if meta["boot_identity"] != _boot_identity() \
                and not self.resource_closeout_only:
            raise WorldAfterstateV2ExecutionError("cross-boot resume refused")
        self._started = meta["started_monotonic_ns"]
        # Telemetry is invocation-relative.  In particular, a reopened
        # supervisor must not divide process-lifetime CPU by its old deadline
        # elapsed time or trust a pre-existing cgroup counter as fresh work.
        self._telemetry_started = self.clock()
        self._process_cpu_baseline = _process_cpu_nanoseconds()
        self._cgroup_directory = _cgroup_v2_directory()
        self._cgroup_cpu_baseline = _cgroup_cpu_nanoseconds(
            self._cgroup_directory)
        # A process interruption is not a retry.  Reopen only immutable
        # complete events and verified shard bytes already present under this
        # admission.  An absent/malformed event is deliberately ignored here;
        # the next stage then fails closed on its ordering or dependency.
        events = self.root / "events"
        completed: list[str] = []
        terminal_route: str | None = None
        if events.is_dir() and not events.is_symlink():
            event_paths = sorted(events.glob("*.json"))
            event_indices = [int(path.stem) for path in event_paths
                             if path.stem.isdigit()]
            if len(event_indices) != len(event_paths) \
                    or event_indices != list(range(len(event_paths))):
                raise WorldAfterstateV2ExecutionError("stage event index drift")
            for path in event_paths:
                try:
                    event = _strict(_sealed(path, "stage event"), "stage event")
                    if event.get("freeze_sha256") != self.freeze.sha256() \
                            or event.get("admission_sha256") != self.admission.sha256():
                        raise WorldAfterstateV2ExecutionError("stage event identity drift")
                    if event.get("event_sha256") != _sha({
                            key: value for key, value in event.items()
                            if key != "event_sha256"}):
                        raise WorldAfterstateV2ExecutionError("stage event digest drift")
                    if event.get("status") == "complete" and event.get("stage") in (
                            "terminal", "reconstruction"):
                        artifact = event.get("payload") or {}
                        relative = (TERMINAL_RESULT_RELATIVE if event["stage"] == "terminal"
                                    else RECONSTRUCTION_RESULT_RELATIVE)
                        raw = _sealed(self.root / relative, "sealed terminal artifact")
                        if artifact.get("artifact_relative_path") != relative \
                                or artifact.get("artifact_sha256") != _sha_bytes(raw) \
                                or artifact.get("artifact_byte_count") != len(raw):
                            raise WorldAfterstateV2ExecutionError("terminal artifact binding drift")
                        if event["stage"] == "terminal" and artifact.get("terminal_route") != _terminal_route(raw):
                            raise WorldAfterstateV2ExecutionError("terminal route binding drift")
                        if event["stage"] == "reconstruction":
                            terminal_raw = _sealed(self.root / TERMINAL_RESULT_RELATIVE,
                                                   "terminal result")
                            _verify_reconstruction_binding(terminal_raw, raw)
                        if event["stage"] == "terminal":
                            decoded_route = _terminal_route(raw)
                            if terminal_route is not None and terminal_route != decoded_route:
                                raise WorldAfterstateV2ExecutionError("terminal route event drift")
                            terminal_route = decoded_route
                    if event.get("status") == "complete" and event.get("stage") in STAGE_ORDER:
                        completed.append(event["stage"])
                    if event.get("status") == "terminal-pending":
                        route = (event.get("payload") or {}).get("route")
                        if route not in TERMINAL_ROUTES or (
                                terminal_route is not None and terminal_route != route):
                            raise WorldAfterstateV2ExecutionError("terminal route event drift")
                        terminal_route = route
                except Exception as exc:
                    raise WorldAfterstateV2ExecutionError("stage event reopen refused") from exc
            self._event_index = len(event_paths)
        shard_rows: list[tuple[str, str]] = []
        shards = self.root / "shards"
        if shards.is_dir() and not shards.is_symlink():
            for stage_dir in sorted(shards.iterdir()):
                if stage_dir.is_symlink() or not stage_dir.is_dir() or stage_dir.name not in STAGE_ORDER:
                    raise WorldAfterstateV2ExecutionError("shard directory drift")
                for path in sorted(stage_dir.glob("*.bin")):
                    raw = _sealed(path, "verified shard")
                    shard_rows.append((f"{stage_dir.name}:{path.stem}", _sha_bytes(raw)))
        marker = self.root / "audit-attempt.json"
        try:
            StageStateV2(tuple(completed), terminal_route, marker.exists(),
                         "reconstruction" in completed, tuple(shard_rows)).payload()
        except Exception as exc:
            raise WorldAfterstateV2ExecutionError(
                "stage event prefix drift") from exc
        self._state = StageStateV2(
            tuple(completed), terminal_route, marker.exists(), "reconstruction" in completed,
            tuple(shard_rows))
        closeout_path = self.root / RESOURCE_CLOSEOUT_RELATIVE
        if closeout_path.exists() or closeout_path.is_symlink():
            if closeout_path.is_symlink() or not self.resource_closeout_only:
                raise WorldAfterstateV2ExecutionError(
                    "admission already resource-closed")
            reopen_resource_incomplete_closeout(
                _sealed(closeout_path, "resource-incomplete closeout"),
                freeze=self.freeze, admission=self.admission)

    @property
    def state(self) -> StageStateV2:
        return self._state

    def _deadline(self) -> None:
        if self.clock() - self._started >= self.freeze.deadline_seconds * 1_000_000_000:
            resource_stage = self.next_stage or "unknown"
            # A sealed terminal decision awaiting its mandatory immediate
            # reconstruction is immutable, but it is not independently
            # verified.  Preserve that prior route in the closeout receipt
            # instead of trying to rewrite the terminal event.
            if "terminal" not in self._state.completed_stages:
                self.terminal("REFUSE_RESOURCE_INCOMPLETE",
                              resource_stage=resource_stage)
            self._seal_resource_incomplete_closeout(resource_stage)
            raise WorldAfterstateV2ExecutionError("REFUSE_RESOURCE_INCOMPLETE")

    def _seal_resource_incomplete_closeout(
            self, resource_stage: str) -> dict[str, Any]:
        """Seal an outcome-blind terminal receipt after deadline/process loss."""
        if resource_stage not in (*STAGE_ORDER, "unknown"):
            raise WorldAfterstateV2ExecutionError(
                "resource closeout stage drift")
        meta = _strict(_sealed(
            self.root / "supervisor-meta.json", "supervisor metadata"),
            "supervisor metadata")
        body = {
            "schema": RESOURCE_CLOSEOUT_SCHEMA,
            "freeze_sha256": self.freeze.sha256(),
            "admission_sha256": self.admission.sha256(),
            "decision": "REFUSE_RESOURCE_INCOMPLETE",
            "resource_stage": resource_stage,
            "completed_stages": list(self._state.completed_stages),
            "audit_opened_count": int(self._state.audit_opened),
            "reconstruction_completed": self._state.reconstruction_completed,
            "verified_shards": [list(row)
                                 for row in self._state.verified_shards],
            "prior_terminal_route": (
                self._state.terminal_route
                if "terminal" in self._state.completed_stages else None),
            "original_boot_identity": meta["boot_identity"],
            "closeout_boot_identity": _boot_identity(),
            "cross_boot": meta["boot_identity"] != _boot_identity(),
            "authority": dict(AUTHORITY),
        }
        value = {**body, "closeout_sha256": _sha(body)}
        raw = canonical_json_bytes(value)
        path = self.root / RESOURCE_CLOSEOUT_RELATIVE
        if path.exists() or path.is_symlink():
            existing = reopen_resource_incomplete_closeout(
                _sealed(path, "resource-incomplete closeout"),
                freeze=self.freeze, admission=self.admission)
            if existing != value:
                raise WorldAfterstateV2ExecutionError(
                    "resource-incomplete closeout replacement refused")
            return existing
        _write_once(path, raw)
        return reopen_resource_incomplete_closeout(
            _sealed(path, "resource-incomplete closeout"),
            freeze=self.freeze, admission=self.admission)

    @property
    def next_stage(self) -> str | None:
        if "reconstruction" in self._state.completed_stages:
            return None
        if "terminal" in self._state.completed_stages:
            return "reconstruction"
        if self._state.terminal_route is not None:
            return "terminal"
        work_count = sum(stage in WORK_STAGE_ORDER
                         for stage in self._state.completed_stages)
        if work_count < len(WORK_STAGE_ORDER):
            return WORK_STAGE_ORDER[work_count]
        return "terminal"

    def _event(self, stage: str, *, status: str, split: str | None = None,
               payload: Mapping[str, Any] | None = None) -> None:
        event = {"schema": EVENT_SCHEMA, "index": self._event_index,
                 "stage": stage, "status": status, "split": split,
                 "freeze_sha256": self.freeze.sha256(),
                 "admission_sha256": self.admission.sha256(),
                 "payload": dict(payload or {}), "authority": dict(AUTHORITY)}
        event["event_sha256"] = _sha(event)
        _write_once(self.root / "events" / f"{self._event_index:08d}.json",
                    canonical_json_bytes(event))
        self._event_index += 1

    def emit_progress(self, *, stage: str, substage: str = "run", completed: int,
                      total: int, active_workers: int = 0, active_threads: int = 0,
                      sealed_shards: int = 0, sealed_checkpoints: int = 0,
                      force: bool = False) -> dict[str, Any]:
        now = self.clock()
        if not force and completed != total and completed * 100 < max(total, 1) * 99 \
                and now - self._last_progress < self.freeze.heartbeat_seconds * 1_000_000_000:
            return {}
        elapsed = max(0, now - self._started)
        eta = (elapsed * (total - completed) // completed) if completed else None
        telemetry_elapsed = max(0, now - self._telemetry_started)
        cpu_ppm, memory_bytes = _live_telemetry(
            telemetry_elapsed, process_cpu_baseline=self._process_cpu_baseline,
            cgroup_directory=self._cgroup_directory,
            cgroup_cpu_baseline=self._cgroup_cpu_baseline)
        self._peak_memory = max(getattr(self, "_peak_memory", 0), memory_bytes)
        snapshot = ProgressSnapshotV2(stage, substage, completed, total,
            active_workers, active_threads, cpu_ppm, memory_bytes, self._peak_memory, elapsed, eta,
            max(0, self.freeze.deadline_seconds * 1_000_000_000 - elapsed),
            sealed_shards, sealed_checkpoints).payload()
        self._last_progress = now
        if self.progress_callback is not None:
            self.progress_callback(snapshot)
        return snapshot

    def register_verified_shard(self, stage: str, shard_id: str, raw: bytes) -> None:
        if self.resource_closeout_only:
            raise WorldAfterstateV2ExecutionError(
                "resource closeout cannot publish scientific shards")
        """Seal one shard once; reopening verifies bytes and never regenerates it."""
        if stage not in STAGE_ORDER or type(shard_id) is not str or not shard_id or type(raw) is not bytes or not raw:
            raise WorldAfterstateV2ExecutionError("shard identity drift")
        digest = _sha_bytes(raw)
        path = self.root / "shards" / stage / f"{shard_id}.bin"
        if path.exists() or path.is_symlink():
            existing = _sealed(path, "verified shard")
            if existing != raw:
                raise WorldAfterstateV2ExecutionError("verified shard replacement refused")
            return
        _write_once(path, raw)
        self._state = StageStateV2(self._state.completed_stages,
            self._state.terminal_route, self._state.audit_opened,
            self._state.reconstruction_completed,
            tuple(sorted((*self._state.verified_shards, (f"{stage}:{shard_id}", digest)))))

    def verified_shards(self, stage: str) -> tuple[str, ...]:
        result = []
        for identity, digest in self._state.verified_shards:
            if identity.startswith(stage + ":"):
                shard_id = identity.split(":", 1)[1]
                raw = _sealed(self.root / "shards" / stage / f"{shard_id}.bin", "verified shard")
                if _sha_bytes(raw) != digest:
                    raise WorldAfterstateV2ExecutionError("verified shard digest drift")
                result.append(shard_id)
        return tuple(result)

    def run_stage(self, stage: str, *, split: str,
                  operation: StageControllerV2 | Callable[..., Any] | None,
                  total: int = 1, payload: Mapping[str, Any] | None = None) -> Any:
        if self.resource_closeout_only:
            raise WorldAfterstateV2ExecutionError(
                "resource closeout cannot run scientific stages")
        # The deadline applies to the whole admitted DAG.  An expired run may
        # seal only the receipt-only resource closeout; it may not start a
        # terminal scorer or the independent reconstruction.
        self._deadline()
        if self._state.terminal_route is not None \
                and stage not in TERMINAL_STAGE_ORDER:
            raise WorldAfterstateV2ExecutionError("terminal route already selected")
        if stage not in STAGE_ORDER or split not in ALLOWED_SPLITS.get(stage, ()):
            raise WorldAfterstateV2ExecutionError("stage split is not admitted")
        if self.next_stage != stage:
            raise WorldAfterstateV2ExecutionError("stage order drift")
        if stage == "audit-attempt":
            self._validate_audit_preflight(payload)
        # A boolean supplied by a caller is not deterministic evidence.  The
        # reviewed audit producer must exist at the exact production boundary
        # before the one-shot marker is ever published.
        if stage == "audit-attempt" \
                and _production_callable(CONTROLLER_BINDINGS[stage][0]) is None:
            raise MissingStageError(
                "audit-attempt:publish_audit_attempt production boundary unavailable")
        if not isinstance(operation, StageControllerV2) or not operation.production:
            raise MissingStageError(f"missing typed controller for {stage}")
        operation.validate()
        if operation.stage != stage:
            raise MissingStageError(f"typed controller stage mismatch for {stage}")
        if stage == "audit-attempt":
            self._open_audit_marker(payload)
        result = self._invoke_controller(operation.operation, stage, total)
        if stage == "terminal":
            raw = _sealed(self.root / TERMINAL_RESULT_RELATIVE, "terminal result")
            route = _terminal_route(raw)
            if self._state.terminal_route is not None \
                    and route != self._state.terminal_route:
                raise WorldAfterstateV2ExecutionError(
                    "terminal precedence drift")
            self._state = StageStateV2(self._state.completed_stages, route,
                self._state.audit_opened, self._state.reconstruction_completed,
                self._state.verified_shards)
        if stage == "reconstruction":
            reconstruction_raw = _sealed(self.root / RECONSTRUCTION_RESULT_RELATIVE,
                                         "reconstruction result")
            terminal_raw = _sealed(self.root / TERMINAL_RESULT_RELATIVE,
                                   "terminal result")
            _verify_reconstruction_binding(terminal_raw, reconstruction_raw)
        event_payload = dict(payload or {})
        if stage == "terminal":
            raw = _sealed(self.root / TERMINAL_RESULT_RELATIVE, "terminal result")
            route = _terminal_route(raw)
            event_payload.update({"artifact_relative_path": TERMINAL_RESULT_RELATIVE,
                                  "artifact_sha256": _sha_bytes(raw),
                                  "artifact_byte_count": len(raw), "terminal_route": route})
        if stage == "reconstruction":
            raw = _sealed(self.root / RECONSTRUCTION_RESULT_RELATIVE, "reconstruction result")
            event_payload.update({"artifact_relative_path": RECONSTRUCTION_RESULT_RELATIVE,
                                  "artifact_sha256": _sha_bytes(raw),
                                  "artifact_byte_count": len(raw)})
        self._event(stage, status="complete", split=split, payload=event_payload)
        completed = (*self._state.completed_stages, stage)
        self._state = StageStateV2(completed, self._state.terminal_route,
            self._state.audit_opened or stage == "audit-attempt",
            self._state.reconstruction_completed or stage == "reconstruction",
            self._state.verified_shards)
        self.emit_progress(stage=stage, completed=total, total=total, force=True)
        return result

    def run_cohort_training_wave(
            self, operations: Mapping[str, StageControllerV2],
            *, payloads: Mapping[str, Mapping[str, Any] | None] | None = None
            ) -> tuple[Any, ...]:
        """Run the capacity-selected cohort production schedule.

        ``block-1-controls`` owns three cohorts and ``block-2-natural`` owns
        the fourth.  A measured width of one executes the two stage
        controllers serially and seals each completed prefix for recovery.
        Width two or four retains the concurrent two-controller wave, with
        the controls adapter using the remaining measured slots internally.
        """
        if self.resource_closeout_only:
            raise WorldAfterstateV2ExecutionError(
                "resource closeout cannot run scientific stages")
        self._deadline()
        if self.next_stage != COHORT_TRAINING_WAVE[0] \
                or type(operations) is not dict \
                or tuple(operations) != COHORT_TRAINING_WAVE:
            raise WorldAfterstateV2ExecutionError(
                "cohort training wave order drift")
        payload_rows = dict(payloads or {})
        if set(payload_rows) - set(COHORT_TRAINING_WAVE):
            raise WorldAfterstateV2ExecutionError(
                "cohort training wave payload drift")
        for stage in COHORT_TRAINING_WAVE:
            operation = operations[stage]
            if (not isinstance(operation, StageControllerV2)
                    or not operation.production or operation.stage != stage
                    or "fit" not in ALLOWED_SPLITS[stage]):
                raise MissingStageError(
                    f"missing typed controller for {stage}")
            operation.validate()
        cohort_widths = {
            getattr(operations[stage].operation, "cohort_workers", None)
            for stage in COHORT_TRAINING_WAVE}
        if (len(cohort_widths) != 1
                or next(iter(cohort_widths)) not in (1, 2, 4)):
            raise WorldAfterstateV2ExecutionError(
                "cohort training wave resource drift")
        cohort_workers = next(iter(cohort_widths))
        if cohort_workers == 1:
            return tuple(self.run_stage(
                stage, split="fit", operation=operations[stage],
                payload=payload_rows.get(stage))
                for stage in COHORT_TRAINING_WAVE)
        results = self._invoke_controller_wave(tuple(
            (stage, operations[stage].operation)
            for stage in COHORT_TRAINING_WAVE))
        # _invoke_controller_wave refreshes every immutable child shard before
        # returning.  Publish the prefix-ordered completion events only now.
        for stage in COHORT_TRAINING_WAVE:
            self._event(stage, status="complete", split="fit",
                        payload=payload_rows.get(stage))
            self._state = StageStateV2(
                (*self._state.completed_stages, stage),
                self._state.terminal_route, self._state.audit_opened,
                self._state.reconstruction_completed,
                self._state.verified_shards)
            self.emit_progress(stage=stage, substage="cohort-wave",
                               completed=1, total=1, force=True)
        return tuple(results[stage] for stage in COHORT_TRAINING_WAVE)

    def _invoke_controller_wave(
            self, operations: tuple[tuple[str, Callable[..., Any]], ...]
            ) -> dict[str, Any]:
        """Run disjoint stage controllers concurrently under one deadline."""
        if tuple(stage for stage, _operation in operations) \
                != COHORT_TRAINING_WAVE:
            raise WorldAfterstateV2ExecutionError(
                "controller wave identity drift")
        context = _controller_context()
        entries: dict[str, tuple[Any, Any]] = {}
        messages: dict[str, tuple[str, Any]] = {}
        try:
            for stage, operation in operations:
                receive, send = context.Pipe(duplex=False)
                process = context.Process(
                    target=_controller_process_entry,
                    args=(operation, self,
                          tuple(self.verified_shards(stage)), send),
                    name=f"world-afterstate-v2-{stage}")
                process.start()
                send.close()
                entries[stage] = (process, receive)
            last_progress = time.monotonic()
            while len(messages) < len(entries):
                remaining = (self._started
                             + self.freeze.deadline_seconds * 1_000_000_000
                             - self.clock())
                if remaining <= 0:
                    for process, _receive in entries.values():
                        _terminate_process_group(process)
                    self._deadline()
                received = False
                for stage, (process, receive) in entries.items():
                    if stage in messages:
                        continue
                    if receive.poll(0.01):
                        try:
                            messages[stage] = receive.recv()
                        except EOFError as exc:
                            raise WorldAfterstateV2ExecutionError(
                                f"{stage} controller process result missing") from exc
                        received = True
                    elif not process.is_alive():
                        if receive.poll():
                            messages[stage] = receive.recv()
                            received = True
                        else:
                            raise WorldAfterstateV2ExecutionError(
                                f"{stage} controller process exited without result")
                    if stage in messages:
                        status, value = messages[stage]
                        if status == "error":
                            if isinstance(value, Exception):
                                raise value
                            raise WorldAfterstateV2ExecutionError(
                                f"{stage} controller process refusal drift")
                        if status != "result":
                            raise WorldAfterstateV2ExecutionError(
                                f"{stage} controller process result status drift")
                if (not received and time.monotonic() - last_progress
                        >= self.freeze.heartbeat_seconds):
                    self.emit_progress(
                        stage=COHORT_TRAINING_WAVE[0],
                        substage="cohort-wave", completed=0, total=2,
                        active_workers=2, active_threads=0, force=True)
                    last_progress = time.monotonic()
        finally:
            for stage, (process, receive) in entries.items():
                receive.close()
                if process.is_alive() and stage not in messages:
                    _terminate_process_group(process)
                process.join(timeout=2.0)
                if process.is_alive():
                    _terminate_process_group(process)
        verify_live_runtime_sha256(self.freeze.runtime_sha256)
        refreshed = StageSupervisorV2(
            self.root, self.freeze, self.admission, clock=self.clock,
            progress_callback=self.progress_callback)
        self._state = refreshed._state
        self._event_index = refreshed._event_index
        self._deadline()
        results: dict[str, Any] = {}
        for stage, (process, _receive) in entries.items():
            message = messages.get(stage)
            if type(message) is not tuple or len(message) != 2:
                raise WorldAfterstateV2ExecutionError(
                    f"{stage} controller process result envelope drift")
            status, value = message
            if status == "result":
                if process.exitcode != 0:
                    raise WorldAfterstateV2ExecutionError(
                        f"{stage} controller process exit drift")
                results[stage] = value
            elif status == "error":
                if isinstance(value, Exception):
                    raise value
                raise WorldAfterstateV2ExecutionError(
                    f"{stage} controller process refusal drift")
            else:
                raise WorldAfterstateV2ExecutionError(
                    f"{stage} controller process result status drift")
        return results

    def _invoke_controller(self, operation: Callable[..., Any], stage: str,
                           total: int) -> Any:
        """Run a controller in a killable group under the global deadline."""
        # Refuse before even creating the child.  The child repeats this check
        # immediately before invoking scientific code to close the spawn gap.
        self._deadline()
        context = _controller_context()
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=_controller_process_entry,
            args=(operation, self, tuple(self.verified_shards(stage)), send),
            name=f"world-afterstate-v2-{stage}")
        process.start()
        send.close()
        message: tuple[str, Any] | None = None
        try:
            while message is None:
                remaining = (self._started
                             + self.freeze.deadline_seconds * 1_000_000_000
                             - self.clock())
                if remaining <= 0:
                    _terminate_process_group(process)
                    self._deadline()
                wait = min(float(self.freeze.heartbeat_seconds),
                           remaining / 1_000_000_000)
                if receive.poll(max(0.001, wait)):
                    try:
                        message = receive.recv()
                    except EOFError as exc:
                        raise WorldAfterstateV2ExecutionError(
                            "controller process result missing") from exc
                    break
                if not process.is_alive():
                    if receive.poll():
                        message = receive.recv()
                        break
                    raise WorldAfterstateV2ExecutionError(
                        "controller process exited without result")
                self.emit_progress(
                    stage=stage, completed=0, total=total,
                    active_workers=1, active_threads=1, force=True)
        finally:
            receive.close()
            if process.is_alive() and message is None:
                _terminate_process_group(process)
            process.join(timeout=2.0)
            if process.is_alive():
                _terminate_process_group(process)
        verify_live_runtime_sha256(self.freeze.runtime_sha256)
        # Controllers publish only immutable shards/events.  Reopen those
        # child publications before the parent validates, seals the stage, or
        # snapshots a resource closeout at the wall.
        refreshed = StageSupervisorV2(
            self.root, self.freeze, self.admission, clock=self.clock,
            progress_callback=self.progress_callback)
        self._state = refreshed._state
        self._event_index = refreshed._event_index
        # Spawn and result transport are inside the admitted wall.  In
        # particular, convert a child's pre-operation expiry refusal into the
        # same durable receipt-only closeout instead of leaking a raw error.
        # This check follows the refresh so the receipt includes every
        # immutable child publication completed before termination.
        self._deadline()
        if type(message) is not tuple or len(message) != 2:
            raise WorldAfterstateV2ExecutionError(
                "controller process result envelope drift")
        status, value = message
        if status == "result":
            if process.exitcode != 0:
                raise WorldAfterstateV2ExecutionError(
                    "controller process exit drift")
            return value
        if status == "error":
            if isinstance(value, Exception):
                raise value
            raise WorldAfterstateV2ExecutionError(
                "controller process refusal drift")
        raise WorldAfterstateV2ExecutionError(
            "controller process result status drift")

    def _open_audit_marker(self, payload: Mapping[str, Any] | None) -> None:
        if self.next_stage != "audit-attempt":
            raise WorldAfterstateV2ExecutionError("audit opening order drift")
        marker = self.root / "audit-attempt.json"
        if self._state.audit_opened:
            value = reopen_audit_attempt_bytes(
                _sealed(marker, "audit attempt"),
                expected_freeze_sha256=self.freeze.sha256(),
                expected_admission_sha256=self.admission.sha256(),
            )
            if value["preflight"] != dict(payload or {}):
                raise WorldAfterstateV2ExecutionError(
                    "audit attempt preflight binding drift")
            return
        if marker.exists() or marker.is_symlink():
            raise WorldAfterstateV2ExecutionError("audit already opened")
        raw = build_audit_attempt_bytes(
            freeze_sha256=self.freeze.sha256(),
            admission_sha256=self.admission.sha256(),
            preflight=dict(payload or {}))
        _write_once(marker, raw)
        _fsync_dir(self.root)

    def _validate_audit_preflight(self, payload: Mapping[str, Any] | None) -> None:
        """Require a sealed producer receipt, never a caller boolean claim."""
        if type(payload) is not dict \
                or payload.get("preflight_relative_path") != AUDIT_PREFLIGHT_RELATIVE:
            raise MissingStageError(
                "audit deterministic pre-open checks are unavailable or incomplete")
        path = self.root / AUDIT_PREFLIGHT_RELATIVE
        raw = _sealed(path, "audit preflight")
        value = _strict(raw, "audit preflight")
        required = {"schema", "freeze_sha256", "admission_sha256",
                    "completed_stages", "upstream_receipt_sha256s",
                    "audit_paths_absent", "preflight_sha256"}
        if set(value) != required or value["schema"] != AUDIT_PREFLIGHT_SCHEMA \
                or value["freeze_sha256"] != self.freeze.sha256() \
                or value["admission_sha256"] != self.admission.sha256() \
                or value["completed_stages"] != list(AUDIT_PREFLIGHT_STAGES) \
                or tuple(self._state.completed_stages) != AUDIT_PREFLIGHT_STAGES \
                or value["audit_paths_absent"] != list(AUDIT_UNOPENED_PATHS):
            raise MissingStageError(
                "audit deterministic pre-open checks are unavailable or incomplete")
        expected_receipts = []
        for stage in AUDIT_PREFLIGHT_STAGES:
            if "receipt" not in self.verified_shards(stage):
                raise MissingStageError(
                    "audit deterministic pre-open checks are unavailable or incomplete")
            raw_receipt = _sealed(
                self.root / "shards" / stage / "receipt.bin",
                f"{stage} preflight receipt")
            expected_receipts.append([stage, _sha_bytes(raw_receipt)])
        if value["upstream_receipt_sha256s"] != expected_receipts:
            raise MissingStageError("audit preflight artifact binding drift")
        body = {key: item for key, item in value.items() if key != "preflight_sha256"}
        if value["preflight_sha256"] != _sha(body) \
                or payload.get("preflight_sha256") != value["preflight_sha256"]:
            raise MissingStageError("audit preflight artifact binding drift")
        if not self._state.audit_opened:
            for relative in AUDIT_UNOPENED_PATHS:
                target = self.root / relative
                if target.exists() or target.is_symlink():
                    raise MissingStageError(
                        "audit deterministic pre-open checks are unavailable or incomplete")
        else:
            attempt = reopen_audit_attempt_bytes(
                _sealed(self.root / "audit-attempt.json", "audit attempt"),
                expected_freeze_sha256=self.freeze.sha256(),
                expected_admission_sha256=self.admission.sha256(),
            )
            if attempt["preflight"] != dict(payload):
                raise MissingStageError("audit preflight artifact binding drift")

    def terminal(self, route: str, *, resource_stage: str | None = None) -> None:
        if route not in TERMINAL_ROUTES:
            raise WorldAfterstateV2ExecutionError("terminal route drift")
        if self._state.terminal_route is not None and self._state.terminal_route != route:
            raise WorldAfterstateV2ExecutionError("terminal precedence drift")
        if self._state.terminal_route == route:
            return
        self._event(self.next_stage or "terminal", status="terminal-pending",
                    payload={"route": route, "resource_stage": resource_stage})
        self._state = StageStateV2(self._state.completed_stages, route,
            self._state.audit_opened, self._state.reconstruction_completed,
            self._state.verified_shards)


def run_v2_pipeline(supervisor: StageSupervisorV2,
                    operations: Mapping[str, Callable[..., Any]]) -> StageStateV2:
    """Run only supplied typed stages; absent dependencies fail closed."""
    if type(operations) is not dict or any(
            not isinstance(operations.get(stage), StageControllerV2)
            or not operations[stage].production for stage in STAGE_ORDER):
        raise MissingStageError("scientific pipeline requires closed production adapters")
    while (stage := supervisor.next_stage) is not None:
        if stage == COHORT_TRAINING_WAVE[0]:
            wave = {name: operations[name] for name in COHORT_TRAINING_WAVE}
            wave_payloads = {}
            for name, controller in wave.items():
                payload = controller.stage_payload
                if controller.stage_payload_factory is not None:
                    payload = controller.stage_payload_factory(supervisor)
                wave_payloads[name] = payload
            supervisor.run_cohort_training_wave(
                wave, payloads=wave_payloads)
            continue
        if stage in TERMINAL_STAGE_ORDER:
            if supervisor.state.audit_opened:
                split = "audit"
            elif "precision-select-power" in supervisor.state.completed_stages:
                split = "select"
            else:
                split = "fit"
        else:
            split = ALLOWED_SPLITS[stage][0]
            if stage == "population":
                split = "fit"
        controller = operations[stage]
        payload = controller.stage_payload
        if controller.stage_payload_factory is not None:
            payload = controller.stage_payload_factory(supervisor)
        try:
            supervisor.run_stage(stage, split=split, operation=controller,
                                 payload=payload)
        except WorldAfterstateV2ExecutionError:
            if (supervisor.root / RESOURCE_CLOSEOUT_RELATIVE).is_file():
                return supervisor.state
            if supervisor.state.terminal_route == "REFUSE_RESOURCE_INCOMPLETE" \
                    and supervisor.next_stage == "terminal":
                continue
            raise
    return supervisor.state


def reopen_supervisor(root: Path, *, freeze: ExecutionFreezeV2,
                      admission: PipelineAdmissionV2,
                      review_marker: bytes, repo: Path | None = None,
                      progress_callback: Callable[[dict[str, Any]], None] | None = None
                      ) -> StageSupervisorV2:
    """Reopen immutable state; no controller, training, or continuation work."""
    reopen_admission(root, freeze=freeze, review_marker=review_marker, repo=repo)
    return StageSupervisorV2(root, freeze, admission,
                             progress_callback=progress_callback)


def seal_resource_incomplete_recovery(
        root: Path, *, freeze: ExecutionFreezeV2,
        admission: PipelineAdmissionV2, review_marker: bytes,
        repo: Path | None = None) -> dict[str, Any]:
    """Close a spent admission after reboot/process loss without science.

    This path may reopen only immutable identity/events/shards.  It cannot
    invoke a controller, open audit data, train, score, or reconstruct.
    """
    reopen_admission(
        root, freeze=freeze, review_marker=review_marker, repo=repo,
        resource_closeout_only=True)
    supervisor = StageSupervisorV2(
        root, freeze, admission, resource_closeout_only=True)
    path = root / RESOURCE_CLOSEOUT_RELATIVE
    if path.is_file() and not path.is_symlink():
        receipt = reopen_resource_incomplete_closeout(
            _sealed(path, "resource-incomplete closeout"),
            freeze=freeze, admission=admission)
        _validate_closeout_state(receipt, supervisor)
        return receipt
    resource_stage = supervisor.next_stage or "unknown"
    if "terminal" not in supervisor.state.completed_stages:
        supervisor.terminal(
            "REFUSE_RESOURCE_INCOMPLETE", resource_stage=resource_stage)
    receipt = supervisor._seal_resource_incomplete_closeout(resource_stage)
    _validate_closeout_state(receipt, supervisor)
    return receipt


def _validate_closeout_state(
        receipt: Mapping[str, Any], supervisor: StageSupervisorV2) -> None:
    state = supervisor.state
    expected_prior = (state.terminal_route
                      if "terminal" in state.completed_stages else None)
    if (tuple(receipt["completed_stages"]) != state.completed_stages
            or receipt["audit_opened_count"] != int(state.audit_opened)
            or receipt["reconstruction_completed"]
            != state.reconstruction_completed
            or tuple(tuple(row) for row in receipt["verified_shards"])
            != state.verified_shards
            or receipt["prior_terminal_route"] != expected_prior):
        raise WorldAfterstateV2ExecutionError(
            "resource-incomplete closeout filesystem drift")


def verify_resource_incomplete_recovery(
        root: Path, *, freeze: ExecutionFreezeV2,
        admission: PipelineAdmissionV2, review_marker: bytes,
        repo: Path | None = None) -> dict[str, Any]:
    """Receipt-only verification; never creates or replaces a closeout."""
    path = root / RESOURCE_CLOSEOUT_RELATIVE
    if path.is_symlink() or not path.is_file():
        raise WorldAfterstateV2ExecutionError(
            "resource-incomplete closeout missing")
    reopen_admission(
        root, freeze=freeze, review_marker=review_marker, repo=repo,
        resource_closeout_only=True)
    supervisor = StageSupervisorV2(
        root, freeze, admission, resource_closeout_only=True)
    receipt = reopen_resource_incomplete_closeout(
        _sealed(path, "resource-incomplete closeout"),
        freeze=freeze, admission=admission)
    _validate_closeout_state(receipt, supervisor)
    return receipt


verify_supervisor = reopen_supervisor


# Compatibility aliases for callers following the V1 naming.
ExecutionDesignV2 = ExecutionFreezeV2
PipelineAdmission = PipelineAdmissionV2
StageSupervisor = StageSupervisorV2
run_pipeline = run_v2_pipeline
build_pipeline_admission = build_admission
validate_pipeline_admission = validate_admission
pipeline_consumption_tombstone = pipeline_consumption_tombstone_bytes
validate_consumption_tombstone = validate_pipeline_consumption_tombstone
freeze_from_bytes = execution_freeze_from_bytes


__all__ = [name for name in globals() if not name.startswith("_")]
