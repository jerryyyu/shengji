"""Exact live source and numerical-runtime identity for BELIEF-V1 V2.

The V2 capacity receipt is evidence about one host, but a digest of that
receipt is not by itself a live execution gate.  This module defines the
source/runtime object embedded in the later execution freeze and recomputed
at every stage entry.  It opens no corpus, starts no worker, and grants no
execution authority.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from ..engine import fast
from .belief_contract import canonical_json_bytes


SOURCE_SCHEMA = "belief-v1-v2-source-binding-v1"
RUNTIME_SCHEMA = "belief-v1-v2-live-runtime-profile-v1"
PACKAGE_SCHEMA = "belief-v1-v2-installed-distribution-binding-v1"
SOURCE_MANIFEST_SCHEMA = "belief-v1-v2-complete-source-manifest-v1"
REQUIRED_ENVIRONMENT = (
    ("PYTHONDONTWRITEBYTECODE", "1"),
    ("PYTHONHASHSEED", "0"),
    ("SHENGJI_FAST", "1"),
    ("SHENGJI_REQUIRE_VOIDS", "1"),
)
REQUIRED_EXACT_PATHS = (
    "BELIEF_V1_SPEC.md",
    "BELIEF_V1_V2_DESIGN.md",
    "server/pyproject.toml",
    "server/setup.py",
    "server/uv.lock",
)
REQUIRED_PREFIXES = (
    "server/shengji/",
    "server/scripts/belief_v2_",
)
LOADABLE_SUFFIXES = (".py", ".pyc", ".pyo", ".so", ".dylib", ".pyd")


class BeliefV2ExecutionIdentityError(ValueError):
    """The live V2 source, host, or numerical runtime drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _is_git_sha(value: Any) -> bool:
    return (type(value) is str and len(value) == 40
            and all(char in "0123456789abcdef" for char in value))


def _git(repo: Path, *arguments: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ("git", *arguments), cwd=repo, check=True,
            capture_output=True, text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefV2ExecutionIdentityError(
            "V2 source Git authentication failed") from exc
    return result.stdout if binary else result.stdout.strip()


@dataclass(frozen=True)
class V2SourceBindingV1:
    path: str
    byte_count: int
    sha256: str
    schema: str = SOURCE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "path": self.path,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class V2InstalledDistributionV1:
    name: str
    version: str
    root: str
    file_count: int
    payload_sha256: str
    schema: str = PACKAGE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "version": self.version,
            "root": self.root,
            "file_count": self.file_count,
            "payload_sha256": self.payload_sha256,
        }


@dataclass(frozen=True)
class V2RuntimeProfileV1:
    hostname: str
    operating_system: str
    machine: str
    cpu_count: int
    memory_bytes: int
    boot_identity: str
    python_executable: str
    python_executable_sha256: str
    python_version: str
    torch: V2InstalledDistributionV1
    torch_config_sha256: str
    numpy: V2InstalledDistributionV1
    native_path: str
    native_sha256: str
    required_environment: tuple[tuple[str, str], ...]
    torch_num_threads: int = 1
    torch_deterministic_algorithms: bool = True
    device: str = "cpu"
    schema: str = RUNTIME_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "hostname": self.hostname,
            "operating_system": self.operating_system,
            "machine": self.machine,
            "cpu_count": self.cpu_count,
            "memory_bytes": self.memory_bytes,
            "boot_identity": self.boot_identity,
            "python": {
                "executable": self.python_executable,
                "executable_sha256": self.python_executable_sha256,
                "version": self.python_version,
            },
            "torch": {
                "distribution": self.torch.to_dict(),
                "config_sha256": self.torch_config_sha256,
                "num_threads": self.torch_num_threads,
                "deterministic_algorithms": (
                    self.torch_deterministic_algorithms),
                "device": self.device,
            },
            "numpy": self.numpy.to_dict(),
            "native": {
                "path": self.native_path,
                "sha256": self.native_sha256,
            },
            "required_environment": dict(self.required_environment),
        }


def validate_source_bindings(
        rows: tuple[V2SourceBindingV1, ...]) -> None:
    if type(rows) is not tuple or not rows \
            or tuple(row.path for row in rows) \
            != tuple(sorted(row.path for row in rows)) \
            or len({row.path for row in rows}) != len(rows):
        raise BeliefV2ExecutionIdentityError(
            "V2 source binding population drift")
    paths = set()
    for row in rows:
        if type(row) is not V2SourceBindingV1 \
                or row.schema != SOURCE_SCHEMA \
                or type(row.path) is not str or not row.path \
                or Path(row.path).is_absolute() \
                or ".." in Path(row.path).parts \
                or type(row.byte_count) is not int or row.byte_count < 0 \
                or not _is_sha256(row.sha256):
            raise BeliefV2ExecutionIdentityError(
                "V2 source binding row drift")
        paths.add(row.path)
    if any(path not in paths for path in REQUIRED_EXACT_PATHS) \
            or not any(path.startswith("server/shengji/") for path in paths) \
            or not any(path.startswith("server/scripts/belief_v2_")
                       for path in paths):
        raise BeliefV2ExecutionIdentityError(
            "V2 source binding closure drift")


def source_manifest_sha256(
        execution_git: str,
        rows: tuple[V2SourceBindingV1, ...]) -> str:
    if not _is_git_sha(execution_git):
        raise BeliefV2ExecutionIdentityError("V2 source Git identity drift")
    validate_source_bindings(rows)
    return _sha256(canonical_json_bytes({
        "schema": SOURCE_MANIFEST_SCHEMA,
        "execution_git": execution_git,
        "files": [row.to_dict() for row in rows],
    }))


def _refuse_loadable_shadows(
        repo: Path, *, tracked: set[str], native_path: Path) -> None:
    server = repo / "server"
    if not server.is_dir():
        raise BeliefV2ExecutionIdentityError("V2 server source root is absent")
    native = native_path.resolve()
    for path in server.rglob("*"):
        if path.is_dir():
            if path.name == "__pycache__":
                raise BeliefV2ExecutionIdentityError(
                    "V2 runtime contains a bytecode cache")
            continue
        relative = path.relative_to(repo).as_posix()
        if path.suffix.lower() not in LOADABLE_SUFFIXES:
            continue
        if relative in tracked or path.resolve() == native:
            continue
        raise BeliefV2ExecutionIdentityError(
            "V2 runtime contains an untracked loadable shadow")


def build_source_bindings(
        repo: Path, *, expected_git: str,
        native_path: Path | None = None) -> tuple[V2SourceBindingV1, ...]:
    """Bind every tracked V2 runtime source and refuse loadable shadows."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_git_sha(expected_git):
        raise BeliefV2ExecutionIdentityError("V2 source binding input drift")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    tracked_raw = _git(repo, "ls-files", "-z", binary=True)
    if head != expected_git or status:
        raise BeliefV2ExecutionIdentityError(
            "V2 source checkout is not exact and clean")
    tracked = tuple(path.decode("utf-8") for path in tracked_raw.split(b"\0")
                    if path)
    tracked_set = set(tracked)
    selected = tuple(sorted(path for path in tracked if (
        path in REQUIRED_EXACT_PATHS
        or any(path.startswith(prefix) for prefix in REQUIRED_PREFIXES))))
    if any(path not in selected for path in REQUIRED_EXACT_PATHS):
        raise BeliefV2ExecutionIdentityError(
            "V2 source manifest path closure drift")
    active_native = native_path
    if active_native is None:
        native_file = getattr(getattr(fast, "_fast", None), "__file__", None)
        if type(native_file) is not str:
            raise BeliefV2ExecutionIdentityError(
                "V2 active native extension is unavailable")
        active_native = Path(native_file)
    _refuse_loadable_shadows(
        repo, tracked=tracked_set, native_path=active_native)
    rows = []
    for relative in selected:
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            raise BeliefV2ExecutionIdentityError(
                "V2 source manifest file shape drift")
        raw = path.read_bytes()
        committed = _git(
            repo, "show", f"{expected_git}:{relative}", binary=True)
        if raw != committed:
            raise BeliefV2ExecutionIdentityError(
                "V2 source byte differs from Git")
        rows.append(V2SourceBindingV1(
            path=relative, byte_count=len(raw), sha256=_sha256(raw)))
    result = tuple(rows)
    validate_source_bindings(result)
    return result


def _memory_bytes() -> int:
    if sys.platform == "darwin":
        try:
            return int(subprocess.run(
                ("sysctl", "-n", "hw.memsize"), check=True,
                capture_output=True, text=True).stdout.strip())
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            raise BeliefV2ExecutionIdentityError(
                "V2 runtime memory probe failed") from exc
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) \
            * int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError) as exc:
        raise BeliefV2ExecutionIdentityError(
            "V2 runtime memory probe failed") from exc


def _boot_identity() -> str:
    linux = Path("/proc/sys/kernel/random/boot_id")
    if linux.is_file():
        value = linux.read_text(encoding="ascii").strip()
    else:
        try:
            value = subprocess.run(
                ("sysctl", "-n", "kern.boottime"), check=True,
                capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BeliefV2ExecutionIdentityError(
                "V2 runtime boot probe failed") from exc
    if not value:
        raise BeliefV2ExecutionIdentityError(
            "V2 runtime boot probe failed")
    return _sha256(value.encode("ascii"))


def _distribution_binding(name: str) -> V2InstalledDistributionV1:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise BeliefV2ExecutionIdentityError(
            "V2 numerical distribution is absent") from exc
    files = distribution.files
    if files is None or not files:
        raise BeliefV2ExecutionIdentityError(
            "V2 numerical distribution file population is absent")
    digest = hashlib.sha256()
    root = Path(distribution.locate_file("")).resolve()
    rows_by_path: dict[str, tuple[int, str]] = {}
    for member in sorted(files, key=str):
        relative = str(member)
        path = Path(distribution.locate_file(member))
        if path.is_symlink() or not path.is_file():
            raise BeliefV2ExecutionIdentityError(
                "V2 numerical distribution file shape drift")
        raw = path.read_bytes()
        rows_by_path[relative] = (len(raw), _sha256(raw))
    # RECORD does not normally list interpreter-generated bytecode.  Existing
    # bytecode can still be imported under ``-B``, so bind every extra
    # loadable file below the actual top-level package as well.
    package_root = root / name.replace("-", "_")
    if not package_root.is_dir():
        raise BeliefV2ExecutionIdentityError(
            "V2 numerical distribution package root is absent")
    for path in package_root.rglob("*"):
        if path.is_dir() or path.suffix.lower() not in LOADABLE_SUFFIXES:
            continue
        if path.is_symlink() or not path.is_file():
            raise BeliefV2ExecutionIdentityError(
                "V2 numerical distribution loadable shape drift")
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        rows_by_path[relative] = (len(raw), _sha256(raw))
    rows = [(relative, *rows_by_path[relative])
            for relative in sorted(rows_by_path)]
    for relative, size, sha in rows:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(sha))
    result = V2InstalledDistributionV1(
        name=name, version=distribution.version, root=str(root),
        file_count=len(rows), payload_sha256=digest.hexdigest())
    validate_distribution(result)
    return result


def validate_distribution(value: V2InstalledDistributionV1) -> None:
    if type(value) is not V2InstalledDistributionV1 \
            or value.schema != PACKAGE_SCHEMA \
            or type(value.name) is not str or not value.name \
            or type(value.version) is not str or not value.version \
            or type(value.root) is not str or not Path(value.root).is_absolute() \
            or type(value.file_count) is not int or value.file_count <= 0 \
            or not _is_sha256(value.payload_sha256):
        raise BeliefV2ExecutionIdentityError(
            "V2 numerical distribution identity drift")


def configure_numerical_runtime() -> None:
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.get_num_threads() != 1 \
            or not torch.are_deterministic_algorithms_enabled():
        raise BeliefV2ExecutionIdentityError(
            "V2 deterministic numerical mode drift")


def build_runtime_profile() -> V2RuntimeProfileV1:
    """Recompute the exact host, interpreter, packages, and native engine."""
    if not sys.flags.safe_path or not sys.dont_write_bytecode \
            or os.environ.get("PYTHONPATH"):
        raise BeliefV2ExecutionIdentityError(
            "V2 runtime requires -P -B and no PYTHONPATH")
    if tuple((key, os.environ.get(key, ""))
             for key, _ in REQUIRED_ENVIRONMENT) != REQUIRED_ENVIRONMENT:
        raise BeliefV2ExecutionIdentityError("V2 runtime environment drift")
    if torch.get_num_threads() != 1 \
            or not torch.are_deterministic_algorithms_enabled():
        raise BeliefV2ExecutionIdentityError(
            "V2 numerical mode is not configured")
    if fast.HAVE_FAST is not True or fast._fast is None:
        raise BeliefV2ExecutionIdentityError(
            "V2 compiled native engine is unavailable")
    python_path = Path(sys.executable).resolve()
    native_path = Path(fast._fast.__file__).resolve()
    if not python_path.is_file() or not native_path.is_file():
        raise BeliefV2ExecutionIdentityError("V2 runtime binary drift")
    profile = V2RuntimeProfileV1(
        hostname=platform.node(), operating_system=platform.platform(),
        machine=platform.machine(), cpu_count=os.cpu_count() or 0,
        memory_bytes=_memory_bytes(), boot_identity=_boot_identity(),
        python_executable=str(python_path),
        python_executable_sha256=_sha256(python_path.read_bytes()),
        python_version=platform.python_version(),
        torch=_distribution_binding("torch"),
        torch_config_sha256=_sha256(torch.__config__.show().encode()),
        numpy=_distribution_binding("numpy"),
        native_path=str(native_path),
        native_sha256=_sha256(native_path.read_bytes()),
        required_environment=REQUIRED_ENVIRONMENT)
    validate_runtime_profile(profile)
    return profile


def validate_runtime_profile(profile: V2RuntimeProfileV1) -> None:
    if type(profile) is not V2RuntimeProfileV1 \
            or profile.schema != RUNTIME_SCHEMA \
            or any(type(value) is not str or not value for value in (
                profile.hostname, profile.operating_system, profile.machine,
                profile.python_executable, profile.python_version,
                profile.native_path)) \
            or type(profile.cpu_count) is not int or profile.cpu_count <= 0 \
            or type(profile.memory_bytes) is not int \
            or profile.memory_bytes <= 0 \
            or not _is_sha256(profile.boot_identity) \
            or not _is_sha256(profile.python_executable_sha256) \
            or not _is_sha256(profile.torch_config_sha256) \
            or not _is_sha256(profile.native_sha256) \
            or profile.required_environment != REQUIRED_ENVIRONMENT \
            or profile.torch_num_threads != 1 \
            or profile.torch_deterministic_algorithms is not True \
            or profile.device != "cpu":
        raise BeliefV2ExecutionIdentityError("V2 runtime profile drift")
    validate_distribution(profile.torch)
    validate_distribution(profile.numpy)


def validate_live_execution(
        *, repo: Path, execution_git: str,
        source_bindings: tuple[V2SourceBindingV1, ...],
        runtime: V2RuntimeProfileV1) -> None:
    """Require exact source and runtime identity at every stage entry."""
    validate_source_bindings(source_bindings)
    validate_runtime_profile(runtime)
    if _boot_identity() != runtime.boot_identity:
        raise BeliefV2ExecutionIdentityError(
            "V2 live boot identity drift")
    native_path = Path(runtime.native_path)
    if build_source_bindings(
            repo, expected_git=execution_git,
            native_path=native_path) != source_bindings \
            or build_runtime_profile() != runtime:
        raise BeliefV2ExecutionIdentityError(
            "V2 live execution identity drift")
