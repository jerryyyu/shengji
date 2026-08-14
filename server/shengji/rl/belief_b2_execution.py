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
import json
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
    REFERENCE_BYTE_CAP,
    REFERENCE_CORE_HOUR_CAP,
    REFERENCE_WALL_SECOND_CAP,
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
ADMISSION_SCHEMA = "belief-v1-b2-offline-pipeline-admission-v1"
REVIEW_PREFIX = "BELIEF_V1_B2_OFFLINE_EXECUTION_V1_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
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
    "server/pyproject.toml",
    "server/setup.py",
    "server/uv.lock",
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


def _reject_number(value: str) -> None:
    raise BeliefB2ExecutionError(
        f"execution design contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefB2ExecutionError(
                "execution design has duplicate JSON key")
        result[key] = value
    return result


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
                "reference_core_hours": REFERENCE_CORE_HOUR_CAP,
                "reference_wall_seconds": REFERENCE_WALL_SECOND_CAP,
                "reference_bytes": REFERENCE_BYTE_CAP,
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


@dataclass(frozen=True)
class B2PipelineAdmissionV1:
    design_sha256: str
    execution_git: str
    source_manifest_sha256: str
    review_commit: str
    review_marker_sha256: str
    evidence_root: str
    schema: str = ADMISSION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": RUN_ID,
            "protocol_sha256": protocol_sha256(),
            "design_sha256": self.design_sha256,
            "execution_git": self.execution_git,
            "source_manifest_sha256": self.source_manifest_sha256,
            "review_commit": self.review_commit,
            "review_marker_sha256": self.review_marker_sha256,
            "evidence_root": self.evidence_root,
            "authority": {
                "capture_authorized": True,
                "reference_generation_authorized": True,
                "training_authorized": True,
                "one_test_split_open_authorized": True,
                "terminal_reconstruction_authorized": True,
                "retry_authorized": False,
                "sampler_implementation_authorized": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False,
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

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
    if torch.get_num_threads() != 1 \
            or not torch.are_deterministic_algorithms_enabled():
        raise BeliefB2ExecutionError("runtime numerical mode drift")
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
        torch_version=str(torch.__version__),
        torch_config_sha256=_sha256(torch.__config__.show().encode()),
        numpy_version=str(np.__version__), native_path=str(native_path),
        native_sha256=_sha256(native_path.read_bytes()),
        required_environment=environment)
    validate_runtime_profile(profile)
    return profile


def configure_numerical_runtime() -> None:
    """Select the exact deterministic CPU numerical mode used by every stage."""
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.get_num_threads() != 1 \
            or not torch.are_deterministic_algorithms_enabled():
        raise BeliefB2ExecutionError("runtime numerical mode drift")


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
                or type(row.byte_count) is not int or row.byte_count < 0 \
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


def execution_design_from_bytes(raw: bytes) -> B2ExecutionDesignV1:
    """Strictly reconstruct the exact reviewed design file bytes."""
    if type(raw) is not bytes or not raw:
        raise BeliefB2ExecutionError("execution design bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefB2ExecutionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefB2ExecutionError(
            "execution design is not strict JSON") from exc
    expected = {
        "schema", "run_id", "protocol_sha256", "execution_git",
        "source_manifest_sha256", "source_bindings", "runtime",
        "evidence_root", "population", "resource_caps", "review",
        "authority",
    }
    if type(payload) is not dict or set(payload) != expected \
            or canonical_json_bytes(payload) != raw \
            or type(payload["source_bindings"]) is not list:
        raise BeliefB2ExecutionError(
            "execution design field/canonical population drift")
    bindings = []
    for row in payload["source_bindings"]:
        if type(row) is not dict or set(row) != {
                "schema", "path", "byte_count", "sha256"}:
            raise BeliefB2ExecutionError("source binding field drift")
        bindings.append(SourceBindingV1(
            schema=row["schema"], path=row["path"],
            byte_count=row["byte_count"], sha256=row["sha256"]))
    runtime = payload["runtime"]
    if type(runtime) is not dict or set(runtime) != {
            "schema", "hostname", "operating_system", "machine",
            "cpu_count", "memory_bytes", "python", "torch",
            "numpy_version", "native", "required_environment"} \
            or type(runtime["python"]) is not dict \
            or set(runtime["python"]) != {
                "executable", "resolved_executable", "executable_sha256",
                "version"} \
            or type(runtime["torch"]) is not dict \
            or set(runtime["torch"]) != {
                "version", "config_sha256", "num_threads",
                "deterministic_algorithms", "device"} \
            or type(runtime["native"]) is not dict \
            or set(runtime["native"]) != {
                "available", "path", "sha256"} \
            or runtime["native"]["available"] is not True \
            or type(runtime["required_environment"]) is not dict:
        raise BeliefB2ExecutionError("runtime profile field drift")
    python = runtime["python"]
    torch_row = runtime["torch"]
    native = runtime["native"]
    profile = RuntimeProfileV1(
        schema=runtime["schema"], hostname=runtime["hostname"],
        operating_system=runtime["operating_system"],
        machine=runtime["machine"], cpu_count=runtime["cpu_count"],
        memory_bytes=runtime["memory_bytes"],
        python_executable=python["executable"],
        python_resolved_executable=python["resolved_executable"],
        python_executable_sha256=python["executable_sha256"],
        python_version=python["version"],
        torch_version=torch_row["version"],
        torch_config_sha256=torch_row["config_sha256"],
        numpy_version=runtime["numpy_version"],
        native_path=native["path"], native_sha256=native["sha256"],
        required_environment=tuple(
            runtime["required_environment"].items()),
        torch_num_threads=torch_row["num_threads"],
        torch_deterministic_algorithms=(
            torch_row["deterministic_algorithms"]),
        device=torch_row["device"])
    design = B2ExecutionDesignV1(
        schema=payload["schema"], execution_git=payload["execution_git"],
        source_bindings=tuple(bindings), runtime=profile,
        evidence_root=payload["evidence_root"])
    validate_execution_design(design)
    if design.canonical_bytes() != raw \
            or payload["source_manifest_sha256"] \
            != design.source_manifest_sha256:
        raise BeliefB2ExecutionError(
            "execution design reconstruction drift")
    return design


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


def validate_live_execution(
        design: B2ExecutionDesignV1, *, repo: Path) -> None:
    """Recompute exact source and runtime identity before every stage."""
    validate_execution_design(design)
    if build_source_bindings(repo, expected_git=design.execution_git) \
            != design.source_bindings \
            or build_runtime_profile() != design.runtime:
        raise BeliefB2ExecutionError("live execution identity drift")


def authenticate_review_commit(
        design: B2ExecutionDesignV1, *, repo: Path, review_commit: str,
        canonical_ref: str = "origin/main") -> bytes:
    """Authenticate the sole independently introduced pipeline marker."""
    validate_execution_design(design)
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_git_sha(review_commit) \
            or type(canonical_ref) is not str or not canonical_ref:
        raise BeliefB2ExecutionError("execution review input drift")
    try:
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 canonical_ref), cwd=repo, capture_output=True).returncode != 0:
            raise BeliefB2ExecutionError(
                "execution review is not on canonical main")
        parents = str(_git(
            repo, "show", "-s", "--format=%P", review_commit)).split()
        if len(parents) != 1:
            raise BeliefB2ExecutionError(
                "execution review commit parent drift")
        parent = parents[0]
        identity = tuple(_git(
            repo, "show", "-s", f"--format={field}", review_commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (
                REVIEWER_NAME, REVIEWER_EMAIL,
                REVIEWER_NAME, REVIEWER_EMAIL):
            raise BeliefB2ExecutionError(
                "execution review actor drift")
        message = str(_git(
            repo, "show", "-s", "--format=%B", review_commit))
        if REVIEWER_SESSION_TRAILER not in message:
            raise BeliefB2ExecutionError(
                "execution review session provenance drift")
        changed = str(_git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit)).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise BeliefB2ExecutionError(
                "execution review changed files beyond the ledger")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parent}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefB2ExecutionError(
            "execution review Git authentication failed") from exc
    if not isinstance(current, bytes) or not isinstance(previous, bytes) \
            or not current.startswith(previous):
        raise BeliefB2ExecutionError(
            "execution review ledger is not append-only")
    marker = REVIEW_PREFIX.encode() + canonical_json_bytes(
        expected_review_claim(design))
    prefix = REVIEW_PREFIX.encode()
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix)]
    if current_matches != [marker] or previous_matches:
        raise BeliefB2ExecutionError(
            "execution review marker introduction drift")
    return marker


def build_pipeline_admission(
        design: B2ExecutionDesignV1, *, review_commit: str,
        review_marker: bytes) -> B2PipelineAdmissionV1:
    """Build the single admission consumed by the complete offline run."""
    validate_execution_design(design)
    if not _is_git_sha(review_commit) or type(review_marker) is not bytes \
            or review_marker != REVIEW_PREFIX.encode() \
            + canonical_json_bytes(expected_review_claim(design)):
        raise BeliefB2ExecutionError("pipeline admission review drift")
    result = B2PipelineAdmissionV1(
        design_sha256=design.sha256(), execution_git=design.execution_git,
        source_manifest_sha256=design.source_manifest_sha256,
        review_commit=review_commit,
        review_marker_sha256=_sha256(review_marker),
        evidence_root=design.evidence_root)
    validate_pipeline_admission(design, result, review_marker=review_marker)
    return result


def validate_pipeline_admission(
        design: B2ExecutionDesignV1, admission: B2PipelineAdmissionV1, *,
        review_marker: bytes) -> None:
    if type(admission) is not B2PipelineAdmissionV1 \
            or admission.schema != ADMISSION_SCHEMA \
            or admission.design_sha256 != design.sha256() \
            or admission.execution_git != design.execution_git \
            or admission.source_manifest_sha256 \
            != design.source_manifest_sha256 \
            or not _is_git_sha(admission.review_commit) \
            or admission.review_marker_sha256 != _sha256(review_marker) \
            or admission.evidence_root != design.evidence_root \
            or review_marker != REVIEW_PREFIX.encode() \
            + canonical_json_bytes(expected_review_claim(design)):
        raise BeliefB2ExecutionError("pipeline admission identity drift")


def pipeline_admission_from_bytes(
        raw: bytes, *, design: B2ExecutionDesignV1,
        review_marker: bytes) -> B2PipelineAdmissionV1:
    """Strictly reopen and fully rederive the one consumed admission."""
    if type(raw) is not bytes or not raw:
        raise BeliefB2ExecutionError("pipeline admission bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefB2ExecutionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefB2ExecutionError(
            "pipeline admission is not strict JSON") from exc
    expected = {
        "schema", "run_id", "protocol_sha256", "design_sha256",
        "execution_git", "source_manifest_sha256", "review_commit",
        "review_marker_sha256", "evidence_root", "authority"}
    if type(payload) is not dict or set(payload) != expected \
            or canonical_json_bytes(payload) != raw:
        raise BeliefB2ExecutionError(
            "pipeline admission field/canonical drift")
    admission = B2PipelineAdmissionV1(
        schema=payload["schema"],
        design_sha256=payload["design_sha256"],
        execution_git=payload["execution_git"],
        source_manifest_sha256=payload["source_manifest_sha256"],
        review_commit=payload["review_commit"],
        review_marker_sha256=payload["review_marker_sha256"],
        evidence_root=payload["evidence_root"])
    validate_pipeline_admission(
        design, admission, review_marker=review_marker)
    if admission.canonical_bytes() != raw:
        raise BeliefB2ExecutionError(
            "pipeline admission reconstruction drift")
    return admission


def pipeline_admission_review_commit(raw: bytes) -> str:
    """Extract only the closed full review SHA needed to authenticate first."""
    if type(raw) is not bytes or not raw:
        raise BeliefB2ExecutionError("pipeline admission bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefB2ExecutionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefB2ExecutionError(
            "pipeline admission is not strict JSON") from exc
    expected = {
        "schema", "run_id", "protocol_sha256", "design_sha256",
        "execution_git", "source_manifest_sha256", "review_commit",
        "review_marker_sha256", "evidence_root", "authority"}
    if type(payload) is not dict or set(payload) != expected \
            or canonical_json_bytes(payload) != raw \
            or not _is_git_sha(payload["review_commit"]):
        raise BeliefB2ExecutionError(
            "pipeline admission review-commit field drift")
    return payload["review_commit"]
