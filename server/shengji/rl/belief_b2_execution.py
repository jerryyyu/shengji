"""One-review execution design for the bounded BELIEF-V1 B2 pipeline.

The design binds one exact clean Git tree, every tracked runtime source byte,
the concrete Python/Torch/NumPy/native runtime, the external evidence root,
and all resource and population constants.  Capture, reference generation,
training, the one test opening, and terminal reconstruction may later consume
this same reviewed design; no per-stage packet or self-authored admission is
introduced.

This module builds and validates the design only.  It has no gameplay,
training, sampler, result opening, subprocess launch, or deployment surface.
"""

from __future__ import annotations

import hashlib
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
from .belief_b2_protocol import (
    B2_CAPTURE_LANES,
    B2_ROUND_COUNT,
    CAPTURE_BYTE_CAP,
    CAPTURE_CORE_HOUR_CAP,
    CAPTURE_WALL_SECOND_CAP,
    TRAIN_BYTE_CAP,
    TRAIN_DEVICE_HOUR_CAP,
    TRAIN_WALL_SECOND_CAP,
    protocol_sha256,
)
from .belief_contract import canonical_json_bytes


DESIGN_SCHEMA = "belief-v1-b2-offline-execution-design-v1"
SOURCE_SCHEMA = "belief-v1-b2-source-binding-v1"
RUNTIME_SCHEMA = "belief-v1-b2-runtime-profile-v1"
REVIEW_SCHEMA = "belief-v1-b2-offline-execution-review-v1"
REVIEW_PREFIX = "BELIEF_V1_B2_OFFLINE_EXECUTION_V1_REVIEW "
RUN_ID = "belief-v1-b2-open-dev-offline-v1"
REQUIRED_ENVIRONMENT = (
    ("PYTHONDONTWRITEBYTECODE", "1"),
    ("PYTHONHASHSEED", "0"),
    ("SHENGJI_FAST", "1"),
    ("SHENGJI_REQUIRE_VOIDS", "1"),
)
REQUIRED_EXACT_PATHS = (
    "BELIEF_V1_B2_DESIGN.md",
    "BELIEF_V1_SPEC.md",
    "pyproject.toml",
    "uv.lock",
    "server/scripts/belief_v1_b2.py",
)
REQUIRED_PREFIXES = ("server/shengji/",)


class BeliefB2ExecutionError(ValueError):
    """The exact reviewed B2 execution identity drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _is_git_sha(value: Any) -> bool:
    return (type(value) is str and len(value) == 40
            and all(char in "0123456789abcdef" for char in value))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SourceBindingV1:
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
class RuntimeProfileV1:
    hostname: str
    operating_system: str
    machine: str
    cpu_count: int
    memory_bytes: int
    python_executable: str
    python_resolved_executable: str
    python_executable_sha256: str
    python_version: str
    torch_version: str
    torch_config_sha256: str
    numpy_version: str
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
            "python": {
                "executable": self.python_executable,
                "resolved_executable": self.python_resolved_executable,
                "executable_sha256": self.python_executable_sha256,
                "version": self.python_version,
            },
            "torch": {
                "version": self.torch_version,
                "config_sha256": self.torch_config_sha256,
                "num_threads": self.torch_num_threads,
                "deterministic_algorithms": (
                    self.torch_deterministic_algorithms),
                "device": self.device,
            },
            "numpy_version": self.numpy_version,
            "native": {
                "available": True,
                "path": self.native_path,
                "sha256": self.native_sha256,
            },
            "required_environment": dict(self.required_environment),
        }


@dataclass(frozen=True)
class B2ExecutionDesignV1:
    execution_git: str
    source_bindings: tuple[SourceBindingV1, ...]
    runtime: RuntimeProfileV1
    evidence_root: str
    schema: str = DESIGN_SCHEMA

    @property
    def source_manifest_sha256(self) -> str:
        return _sha256(canonical_json_bytes({
            "schema": "belief-v1-b2-complete-source-manifest-v1",
            "execution_git": self.execution_git,
            "files": [row.to_dict() for row in self.source_bindings],
        }))

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_dict_base()
        payload["review"] = {
            "one_consolidated_external_review_required": True,
            "review_schema": REVIEW_SCHEMA,
            "review_prefix": REVIEW_PREFIX,
        }
        return payload

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_dict_base(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": RUN_ID,
            "protocol_sha256": protocol_sha256(),
            "execution_git": self.execution_git,
            "source_manifest_sha256": self.source_manifest_sha256,
            "source_bindings": [
                row.to_dict() for row in self.source_bindings],
            "runtime": self.runtime.to_dict(),
            "evidence_root": self.evidence_root,
            "population": {
                "round_count": B2_ROUND_COUNT,
                "capture_lanes": B2_CAPTURE_LANES,
                "retry_count": 0,
                "drop_count": 0,
            },
            "resource_caps": {
                "capture_core_hours": CAPTURE_CORE_HOUR_CAP,
                "capture_wall_seconds": CAPTURE_WALL_SECOND_CAP,
                "capture_bytes": CAPTURE_BYTE_CAP,
                "training_device_hours": TRAIN_DEVICE_HOUR_CAP,
                "training_wall_seconds": TRAIN_WALL_SECOND_CAP,
                "training_bytes": TRAIN_BYTE_CAP,
            },
            "authority": {
                "design_freeze_authorized": True,
                "offline_pipeline_execution_authorized": False,
                "test_split_open_authorized": False,
                "sampler_implementation_authorized": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False,
            },
        }

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def _git(repo: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ("git", *arguments), cwd=repo, check=True,
        capture_output=True, text=not binary)
    return result.stdout if binary else result.stdout.strip()


def build_source_bindings(
        repo: Path, *, expected_git: str) -> tuple[SourceBindingV1, ...]:
    """Bind every tracked runtime source from one exact clean checkout."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_git_sha(expected_git):
        raise BeliefB2ExecutionError("source binding input drift")
    try:
        head = _git(repo, "rev-parse", "HEAD")
        status = _git(repo, "status", "--porcelain", "--untracked-files=all")
        tracked_raw = _git(repo, "ls-files", "-z", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefB2ExecutionError("source Git authentication failed") \
            from exc
    if head != expected_git or status:
        raise BeliefB2ExecutionError("source checkout is not exact and clean")
    tracked = tuple(path.decode("utf-8") for path in tracked_raw.split(b"\0")
                    if path)
    selected = tuple(sorted(path for path in tracked if (
        path in REQUIRED_EXACT_PATHS
        or any(path.startswith(prefix) for prefix in REQUIRED_PREFIXES))))
    if any(path not in selected for path in REQUIRED_EXACT_PATHS) \
            or not selected:
        raise BeliefB2ExecutionError("source manifest path closure drift")
    rows = []
    for relative in selected:
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            raise BeliefB2ExecutionError("source manifest file shape drift")
        raw = path.read_bytes()
        try:
            committed = _git(
                repo, "show", f"{expected_git}:{relative}", binary=True)
        except subprocess.CalledProcessError as exc:
            raise BeliefB2ExecutionError(
                "source committed-byte lookup failed") from exc
        if raw != committed:
            raise BeliefB2ExecutionError("source byte differs from Git")
        rows.append(SourceBindingV1(
            path=relative, byte_count=len(raw), sha256=_sha256(raw)))
    return tuple(rows)


def _memory_bytes() -> int:
    if sys.platform == "darwin":
        try:
            return int(subprocess.run(
                ("sysctl", "-n", "hw.memsize"), check=True,
                capture_output=True, text=True).stdout.strip())
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            raise BeliefB2ExecutionError("runtime memory probe failed") \
                from exc
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError) as exc:
        raise BeliefB2ExecutionError("runtime memory probe failed") from exc
    return int(pages) * int(page_size)


def build_runtime_profile() -> RuntimeProfileV1:
    """Capture the exact deterministic CPU runtime before a design review."""
    if fast.HAVE_FAST is not True or fast._fast is None:
        raise BeliefB2ExecutionError("compiled runtime is unavailable")
    native_path = Path(fast._fast.__file__).resolve()
    python_path = Path(sys.executable)
    resolved_python = python_path.resolve()
    if not native_path.is_file() or not resolved_python.is_file():
        raise BeliefB2ExecutionError("runtime binary path drift")
    environment = tuple((name, os.environ.get(name, ""))
                        for name, _ in REQUIRED_ENVIRONMENT)
    if environment != REQUIRED_ENVIRONMENT:
        raise BeliefB2ExecutionError("runtime environment drift")
    profile = RuntimeProfileV1(
        hostname=platform.node(), operating_system=platform.platform(),
        machine=platform.machine(), cpu_count=os.cpu_count() or 0,
        memory_bytes=_memory_bytes(), python_executable=str(python_path),
        python_resolved_executable=str(resolved_python),
        python_executable_sha256=_sha256(resolved_python.read_bytes()),
        python_version=platform.python_version(),
        torch_version=torch.__version__,
        torch_config_sha256=_sha256(torch.__config__.show().encode()),
        numpy_version=np.__version__, native_path=str(native_path),
        native_sha256=_sha256(native_path.read_bytes()),
        required_environment=environment)
    validate_runtime_profile(profile)
    return profile


def validate_runtime_profile(profile: RuntimeProfileV1) -> None:
    if type(profile) is not RuntimeProfileV1 \
            or profile.schema != RUNTIME_SCHEMA \
            or any(type(value) is not str or not value for value in (
                profile.hostname, profile.operating_system, profile.machine,
                profile.python_executable,
                profile.python_resolved_executable, profile.python_version,
                profile.torch_version, profile.numpy_version,
                profile.native_path)) \
            or any(not _is_sha256(value) for value in (
                profile.python_executable_sha256,
                profile.torch_config_sha256, profile.native_sha256)) \
            or type(profile.cpu_count) is not int \
            or profile.cpu_count <= 0 \
            or type(profile.memory_bytes) is not int \
            or profile.memory_bytes <= 0 \
            or profile.required_environment != REQUIRED_ENVIRONMENT \
            or profile.torch_num_threads != 1 \
            or profile.torch_deterministic_algorithms is not True \
            or profile.device != "cpu":
        raise BeliefB2ExecutionError("runtime profile identity drift")


def validate_execution_design(design: B2ExecutionDesignV1) -> None:
    if type(design) is not B2ExecutionDesignV1 \
            or design.schema != DESIGN_SCHEMA \
            or not _is_git_sha(design.execution_git) \
            or type(design.source_bindings) is not tuple \
            or not design.source_bindings \
            or tuple(row.path for row in design.source_bindings) \
            != tuple(sorted(row.path for row in design.source_bindings)) \
            or len({row.path for row in design.source_bindings}) \
            != len(design.source_bindings) \
            or type(design.evidence_root) is not str \
            or not Path(design.evidence_root).is_absolute():
        raise BeliefB2ExecutionError("execution design identity drift")
    for row in design.source_bindings:
        if type(row) is not SourceBindingV1 or row.schema != SOURCE_SCHEMA \
                or type(row.path) is not str or not row.path \
                or row.path.startswith("/") or ".." in Path(row.path).parts \
                or type(row.byte_count) is not int or row.byte_count <= 0 \
                or not _is_sha256(row.sha256):
            raise BeliefB2ExecutionError("source binding row drift")
    if any(path not in {row.path for row in design.source_bindings}
           for path in REQUIRED_EXACT_PATHS):
        raise BeliefB2ExecutionError("execution design source closure drift")
    validate_runtime_profile(design.runtime)
    payload = design.canonical_bytes()
    if canonical_json_bytes(design.to_dict()) != payload \
            or not _is_sha256(design.sha256()):
        raise BeliefB2ExecutionError("execution design digest closure drift")


def expected_review_claim(design: B2ExecutionDesignV1) -> dict[str, Any]:
    """Return the sole external-review claim needed for the whole B2 run."""
    validate_execution_design(design)
    return {
        "schema": REVIEW_SCHEMA,
        "design_sha256": design.sha256(),
        "execution_git": design.execution_git,
        "protocol_sha256": protocol_sha256(),
        "source_manifest_sha256": design.source_manifest_sha256,
        "evidence_root": design.evidence_root,
        "capture_reference_training_and_one_test_open_authorized": True,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }
