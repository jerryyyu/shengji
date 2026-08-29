"""Durable one-admission stage ledger for the Value V1 P1 pilot.

Each cohort and each held-out-data boundary has its own one-shot attempt.  A
finished cohort can therefore remain sealed across later stages without
turning a failed process into an implicit retry or an all-or-nothing run.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1_admission import (
    ADMISSION_AUTHORITY, build_admission, reauthenticate_admission,
    validate_admission)
from .world_afterstate_v1_capacity import (
    ARTIFACT_PATHS, CapacityBuildV1, reopen_capacity_build)
from .world_afterstate_v1_experiment import validate_experiment_freeze


ROOT_SCHEMA = "world-afterstate-v1-p1-scientific-root-v1"
ATTEMPT_SCHEMA = "world-afterstate-v1-p1-stage-attempt-v1"
STAGES = (
    "train-natural", "train-identical-successor",
    "train-action-association-permutation", "train-label-permutation",
    "seal-target-free-predictions", "open-calibration-labels",
    "independent-reconstruction",
)
ROOT_AUTHORITY = {
    "scientific_execution_authorized": False,
    "calibration_opening_authorized": False,
    "report_opening_authorized": False,
    "provider_audit_opening_authorized": False,
    "p2_execution_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1ScientificError(ValueError):
    """A root input, durable attempt, review, or file population drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1ScientificError(f"{label} drift")
    return value


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1ScientificError(f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1ScientificError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1ScientificError(
            f"{label} is not canonical JSON")
    return value


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sealed_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateV1ScientificError(
            "scientific artifact path is a symlink")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstateV1ScientificError(
            "scientific artifact cannot be read") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or before.st_size != len(raw) \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateV1ScientificError(
            "scientific artifact is mutable or changed while read")
    return raw


def lock_root_for(root: Path) -> Path:
    if not isinstance(root, Path):
        raise WorldAfterstateV1ScientificError(
            "scientific root path drift")
    resolved = root.resolve()
    return resolved.with_name(f".{resolved.name}.admission-lock")


def _capacity_files(build: CapacityBuildV1) -> dict[str, bytes]:
    build = reopen_capacity_build(build)
    result = {"capacity/receipt.json": canonical_json_bytes(build.receipt)}
    for relative, raw in build.files:
        result[f"capacity/artifacts/{relative}"] = raw
    return result


def _root_manifest(files: Mapping[str, bytes], freeze: Mapping[str, Any],
                   admission: Mapping[str, Any]) -> dict[str, Any]:
    rows = [{
        "relative_path": path, "byte_count": len(raw),
        "sha256": _sha_bytes(raw),
    } for path, raw in sorted(files.items())]
    body = {
        "schema": ROOT_SCHEMA,
        "freeze_sha256": freeze["freeze_sha256"],
        "admission_sha256": admission["admission_sha256"],
        "file_count": len(rows), "files": rows,
        "authority": dict(ROOT_AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def initialize_scientific_root(
        root: Path, *, freeze_raw: bytes, capacity_build: CapacityBuildV1,
        repo: Path, review_commit: str) -> dict[str, Any]:
    """Spend one reviewed admission before any scientific row can open."""
    freeze = _canonical(freeze_raw, "scientific freeze")
    try:
        capacity_build = reopen_capacity_build(capacity_build)
        validate_experiment_freeze(freeze, capacity_build)
        admission = build_admission(
            freeze, repo=repo, review_commit=review_commit)
        marker = reauthenticate_admission(
            admission, freeze=freeze, repo=repo)
        validate_admission(admission, freeze=freeze, review_marker=marker)
    except ValueError as exc:
        raise WorldAfterstateV1ScientificError(
            "scientific admission input drift") from exc
    admission_raw = canonical_json_bytes(admission)
    inputs = {
        "freeze.json": freeze_raw,
        "admission.json": admission_raw,
        **_capacity_files(capacity_build),
    }
    manifest = _root_manifest(inputs, freeze, admission)

    resolved = root.resolve()
    if str(resolved) != freeze.get("scientific_root"):
        raise WorldAfterstateV1ScientificError(
            "scientific root differs from reviewed freeze")
    parent = resolved.parent
    partial = parent / f".{resolved.name}.partial"
    lock = lock_root_for(resolved)
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink() \
            or lock.exists() or lock.is_symlink():
        raise WorldAfterstateV1ScientificError(
            "scientific admission namespace occupied")

    lock.mkdir(mode=0o700)
    initialization = {
        "schema": "world-afterstate-v1-p1-initialization-attempt-v1",
        "freeze_sha256": freeze["freeze_sha256"],
        "admission_sha256": admission["admission_sha256"],
        "started_monotonic_ns": time.monotonic_ns(),
        "retry_authorized": False,
    }
    initialization["attempt_sha256"] = _sha(initialization)
    _write_once(lock / "initialize.json",
                canonical_json_bytes(initialization))
    _fsync_directory(lock)
    _fsync_directory(parent)

    partial.mkdir(mode=0o700)
    input_root = partial / "inputs"
    output_root = partial / "outputs"
    output_root.mkdir(parents=True, mode=0o700)
    for relative, raw in inputs.items():
        _write_once(input_root / relative, raw)
    _write_once(input_root / "manifest.json", canonical_json_bytes(manifest))
    for directory in sorted(
            (path for path in input_root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True):
        os.chmod(directory, 0o500)
        _fsync_directory(directory)
    os.chmod(input_root, 0o500)
    _fsync_directory(input_root)
    _fsync_directory(output_root)
    _fsync_directory(partial)
    os.rename(partial, resolved)
    os.chmod(resolved, 0o500)
    _fsync_directory(resolved)
    _fsync_directory(parent)
    return manifest


def reopen_scientific_root(root: Path, *, repo: Path):
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateV1ScientificError(
            "scientific root identity drift")
    inputs = root / "inputs"
    manifest_raw = _sealed_read(inputs / "manifest.json")
    manifest = _canonical(manifest_raw, "scientific root manifest")
    rows = manifest.get("files")
    if type(rows) is not list:
        raise WorldAfterstateV1ScientificError(
            "scientific root file population drift")
    raw_by_path = {}
    expected_paths = {inputs / "manifest.json"}
    for row in rows:
        if type(row) is not dict or set(row) != {
                "relative_path", "byte_count", "sha256"}:
            raise WorldAfterstateV1ScientificError(
                "scientific root file row drift")
        path = Path(row["relative_path"])
        if path.is_absolute() or ".." in path.parts:
            raise WorldAfterstateV1ScientificError(
                "scientific root file row drift")
        raw = _sealed_read(inputs / path)
        expected_paths.add(inputs / path)
        if len(raw) != row["byte_count"] \
                or _sha_bytes(raw) != row["sha256"]:
            raise WorldAfterstateV1ScientificError(
                "scientific root file binding drift")
        raw_by_path[row["relative_path"]] = raw
    if {path for path in inputs.rglob("*") if path.is_file()} \
            != expected_paths:
        raise WorldAfterstateV1ScientificError(
            "scientific root file population drift")
    freeze = _canonical(raw_by_path["freeze.json"], "scientific freeze")
    if str(root.resolve()) != freeze.get("scientific_root"):
        raise WorldAfterstateV1ScientificError(
            "scientific root differs from reviewed freeze")
    admission = _canonical(
        raw_by_path["admission.json"], "scientific admission")
    receipt = _canonical(
        raw_by_path["capacity/receipt.json"], "scientific capacity receipt")
    artifacts = tuple((relative, raw_by_path[
        f"capacity/artifacts/{relative}"]) for relative in ARTIFACT_PATHS)
    capacity = CapacityBuildV1(receipt=receipt, files=artifacts)
    try:
        capacity = reopen_capacity_build(capacity)
        validate_experiment_freeze(freeze, capacity)
        marker = reauthenticate_admission(
            admission, freeze=freeze, repo=repo)
        validate_admission(admission, freeze=freeze, review_marker=marker)
    except ValueError as exc:
        raise WorldAfterstateV1ScientificError(
            "scientific root component drift") from exc
    expected = _root_manifest(
        {key: raw_by_path[key] for key in raw_by_path}, freeze, admission)
    if canonical_json_bytes(manifest) != canonical_json_bytes(expected):
        raise WorldAfterstateV1ScientificError(
            "scientific root reconstruction drift")
    lock = lock_root_for(root)
    initialization = _canonical(
        _sealed_read(lock / "initialize.json"),
        "scientific initialization attempt")
    body = {key: item for key, item in initialization.items()
            if key != "attempt_sha256"}
    if initialization.get("freeze_sha256") != freeze["freeze_sha256"] \
            or initialization.get("admission_sha256") \
            != admission["admission_sha256"] \
            or initialization.get("retry_authorized") is not False \
            or initialization.get("attempt_sha256") != _sha(body):
        raise WorldAfterstateV1ScientificError(
            "scientific initialization reconstruction drift")
    return freeze, capacity, admission, manifest


def consume_stage_attempt(
        root: Path, *, stage: str, freeze_sha256: str,
        admission_sha256: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if stage not in STAGES or type(inputs) is not dict:
        raise WorldAfterstateV1ScientificError(
            "scientific stage attempt request drift")
    _digest(freeze_sha256, "stage freeze SHA-256")
    _digest(admission_sha256, "stage admission SHA-256")
    lock = lock_root_for(root)
    if not lock.is_dir() or lock.is_symlink():
        raise WorldAfterstateV1ScientificError(
            "scientific admission lock drift")
    target = lock / f"{stage}.json"
    if target.exists() or target.is_symlink():
        raise WorldAfterstateV1ScientificError(
            "scientific stage attempt already consumed")
    body = {
        "schema": ATTEMPT_SCHEMA,
        "stage": stage, "freeze_sha256": freeze_sha256,
        "admission_sha256": admission_sha256,
        "inputs": dict(inputs), "started_monotonic_ns": time.monotonic_ns(),
        "retry_authorized": False,
        "admission_authority": dict(ADMISSION_AUTHORITY),
        "authority": dict(ROOT_AUTHORITY),
    }
    attempt = {**body, "attempt_sha256": _sha(body)}
    _write_once(target, canonical_json_bytes(attempt))
    _fsync_directory(lock)
    _fsync_directory(lock.parent)
    return attempt


__all__ = [
    "ATTEMPT_SCHEMA", "ROOT_AUTHORITY", "ROOT_SCHEMA", "STAGES",
    "WorldAfterstateV1ScientificError", "consume_stage_attempt",
    "initialize_scientific_root", "lock_root_for",
    "reopen_scientific_root",
]
