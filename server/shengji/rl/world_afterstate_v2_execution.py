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
import os
import platform
import resource
import stat
import subprocess
import sys
import time
from concurrent.futures import TimeoutError as FutureTimeout, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_audit_attempt import (
    build_audit_attempt_bytes, reopen_audit_attempt_bytes,
)


SCHEMA = "world-afterstate-v2-absolute-leaf-execution-v1"
FREEZE_SCHEMA = "world-afterstate-v2-absolute-leaf-freeze-v2"
ADMISSION_SCHEMA = "world-afterstate-v2-absolute-leaf-admission-v1"
TOMBSTONE_SCHEMA = "world-afterstate-v2-absolute-leaf-consumption-tombstone-v1"
STATE_SCHEMA = "world-afterstate-v2-stage-state-v1"
EVENT_SCHEMA = "world-afterstate-v2-stage-event-v1"
PROGRESS_SCHEMA = "world-afterstate-v2-progress-v1"
META_SCHEMA = "world-afterstate-v2-supervisor-meta-v1"
REVIEW_PREFIX = "WORLD_AFTERSTATE_V2_ABSOLUTE_LEAF_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
MAX_DEADLINE_SECONDS = 12 * 60 * 60

# The names are part of the protocol.  A stage may consume only the listed
# split; in particular no helper can accidentally label audit rows early.
STAGE_ORDER = (
    "population", "p0-labels-gates", "optimizer-canary", "fit-select-labels",
    "block-1-natural", "nested-curve", "block-1-controls", "block-2-natural",
    "block-2-controls", "precision-select-power", "audit-attempt",
    "terminal", "reconstruction",
)
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
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _live_telemetry(elapsed_nanoseconds: int) -> tuple[int, int]:
    """Return process CPU utilization and current cgroup/RSS memory."""
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError as exc:
        raise WorldAfterstateV2ExecutionError("process CPU telemetry unavailable") from exc
    cpu_ns = (usage.ru_utime + usage.ru_stime) * 1_000_000_000
    # This is aggregate process CPU; values above one core are meaningful
    # when a controller has active workers and are intentionally not capped.
    cpu_ppm = int(cpu_ns * 1_000_000 // max(elapsed_nanoseconds, 1))
    cgroup = Path("/sys/fs/cgroup/memory.current")
    if cgroup.is_file():
        try:
            return cpu_ppm, int(cgroup.read_text(encoding="ascii").strip())
        except (OSError, ValueError) as exc:
            raise WorldAfterstateV2ExecutionError("cgroup memory telemetry unavailable") from exc
    # Older Linux hosts have no cgroup v2; /proc gives current RSS rather than
    # the historical high-water mark returned by getrusage.
    statm = Path("/proc/self/statm")
    if statm.is_file():
        try:
            rss_pages = int(statm.read_text(encoding="ascii").split()[1])
            return cpu_ppm, rss_pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, IndexError, ValueError) as exc:
            raise WorldAfterstateV2ExecutionError(
                "process memory telemetry unavailable") from exc
    # macOS exposes only the process high-water mark through this stdlib API;
    # it remains a live nonzero witness and is tracked independently as peak.
    rss = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return cpu_ppm, rss
    return cpu_ppm, rss * 1024


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
    return {"python": sys.version, "python_executable": str(executable),
            "python_executable_sha256": executable_sha,
            "platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "torch_threads": _torch_threads(),
            "torch_version": torch_version, "torch_config_sha256": torch_config_sha,
            "numpy_version": numpy_version,
            "shengji_native_extension": native,
            "boot_identity": _boot_identity()}


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


def _native_extension_profile() -> dict[str, str]:
    for name in ("shengji.engine._fast", "shengji._native", "shengji.engine._native"):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ModuleNotFoundError, ValueError):
            spec = None
        origin = None if spec is None else spec.origin
        if origin and origin not in ("built-in", "frozen") and Path(origin).is_file():
            try:
                return {"status": "present", "path": str(Path(origin).resolve()),
                        "sha256": _sha_bytes(Path(origin).read_bytes())}
            except OSError as exc:
                raise WorldAfterstateV2ExecutionError(
                    "native extension telemetry unavailable") from exc
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
        if type(self.runtime_profile) is not dict \
                or self.runtime_sha256 != _sha(self.runtime_profile):
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


def _verify_source_before_admission(freeze: ExecutionFreezeV2, repo: Path) -> None:
    _refuse_source_bytecode(freeze, repo)
    if freeze.runtime_sha256 != _sha(freeze.runtime_profile) \
            or freeze.boot_identity != _boot_identity() \
            or dict(freeze.runtime_profile) != live_runtime_profile():
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
                     review_marker: bytes, repo: Path | None = None) -> PipelineAdmissionV2:
    # A monotonic deadline is meaningful only on the same runtime image.  The
    # persisted boot witness below catches reboot; this profile check catches
    # interpreter/runtime replacement before any stage can resume.
    if type(freeze.runtime_profile) is not dict \
            or freeze.runtime_sha256 != _sha(freeze.runtime_profile) \
            or freeze.boot_identity != _boot_identity() \
            or dict(freeze.runtime_profile) != live_runtime_profile():
        raise WorldAfterstateV2ExecutionError("runtime identity drift on resume")
    if repo is not None:
        _verify_source_before_admission(freeze, repo)
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
        if any(type(value) is not int or value < 0 for value in (
                self.completed, self.total, self.active_workers, self.active_threads,
                self.cpu_utilization_ppm, self.cgroup_memory_bytes,
                self.peak_cgroup_memory_bytes, self.elapsed_nanoseconds,
                self.deadline_headroom_nanoseconds, self.sealed_shards,
                self.sealed_checkpoints)) or self.completed > self.total:
            raise WorldAfterstateV2ExecutionError("progress accounting drift")
        return {"schema": PROGRESS_SCHEMA, **self.__dict__, "authority": dict(AUTHORITY)}


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
    _started: int = field(default_factory=time.monotonic_ns, repr=False)
    _state: StageStateV2 = field(default_factory=StageStateV2, repr=False)
    _event_index: int = field(default=0, repr=False)
    _last_progress: int = field(default=0, repr=False)
    _peak_memory: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
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
        if meta["boot_identity"] != _boot_identity():
            raise WorldAfterstateV2ExecutionError("cross-boot resume refused")
        self._started = meta["started_monotonic_ns"]
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

    @property
    def state(self) -> StageStateV2:
        return self._state

    def _deadline(self) -> None:
        if self.clock() - self._started >= self.freeze.deadline_seconds * 1_000_000_000:
            self.terminal("REFUSE_RESOURCE_INCOMPLETE", resource_stage=self.next_stage or "unknown")
            raise WorldAfterstateV2ExecutionError("REFUSE_RESOURCE_INCOMPLETE")

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
                and now - self._last_progress < 60 * 1_000_000_000:
            return {}
        elapsed = max(0, now - self._started)
        eta = (elapsed * (total - completed) // completed) if completed else None
        cpu_ppm, memory_bytes = _live_telemetry(elapsed)
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
        # Terminal sealing and its receipt-only reconstruction are allowed to
        # finish after the scientific compute deadline.  Otherwise an expiry
        # would prevent the fail-closed route from ever becoming durable.
        if stage not in TERMINAL_STAGE_ORDER:
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

    def _invoke_controller(self, operation: Callable[..., Any], stage: str,
                           total: int) -> Any:
        """Run a controller with a mandatory <=60s heartbeat monitor."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(operation, self, tuple(self.verified_shards(stage)))
            while True:
                try:
                    return future.result(timeout=60)
                except FutureTimeout:
                    self.emit_progress(stage=stage, completed=0, total=total,
                                       active_workers=1, active_threads=1, force=True)

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
            if supervisor.state.terminal_route == "REFUSE_RESOURCE_INCOMPLETE" \
                    and supervisor.next_stage == "terminal":
                continue
            raise
    return supervisor.state


def reopen_supervisor(root: Path, *, freeze: ExecutionFreezeV2,
                      admission: PipelineAdmissionV2,
                      review_marker: bytes, repo: Path | None = None) -> StageSupervisorV2:
    """Reopen immutable state; no controller, training, or continuation work."""
    reopen_admission(root, freeze=freeze, review_marker=review_marker, repo=repo)
    return StageSupervisorV2(root, freeze, admission)


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
