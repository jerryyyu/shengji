"""Durable admission and one-shot stage tombstones for Value V0.

The scientific evidence tree and its lock directory are siblings.  Deleting
or damaging the evidence tree therefore cannot silently recreate an unused
admission: the separate lock retains initialization and stage attempts.  This
module performs no continuations, training, report scoring, or deployment.
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
from .world_afterstate_admission import (
    build_admission, reauthenticate_admission, validate_admission)
from .world_afterstate_experiment import (
    validate_experiment_freeze)


ROOT_SCHEMA = "world-afterstate-e3-e4-scientific-root-v0"
ATTEMPT_SCHEMA = "world-afterstate-e3-e4-stage-attempt-v0"
ROOT_FILES = {
    "freeze": "freeze.json",
    "capacity": "capacity.json",
    "population_packet": "population-packet.json",
    "admission": "admission.json",
    "manifest": "manifest.json",
}
STAGES = ("dataset", "training", "report", "independent-verification")
SCIENTIFIC_ROOT_AUTHORITY = {
    "retry_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateScientificError(ValueError):
    """The scientific root, lock, stage attempt, or input drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateScientificError(f"{label} drift")
    return value


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (AttributeError, UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateScientificError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateScientificError(
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
        raise WorldAfterstateScientificError(
            "scientific artifact path is a symlink")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstateScientificError(
            "scientific artifact cannot be read") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or before.st_size != len(raw) \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateScientificError(
            "scientific artifact is mutable or changed while read")
    return raw


def lock_root_for(root: Path) -> Path:
    if not isinstance(root, Path):
        raise WorldAfterstateScientificError(
            "scientific root path drift")
    resolved = root.resolve()
    return resolved.with_name(f".{resolved.name}.admission-lock")


def _root_manifest(
        *, freeze_raw: bytes, capacity_raw: bytes,
        population_packet_raw: bytes, admission_raw: bytes) -> dict[str, Any]:
    body = {
        "schema": ROOT_SCHEMA,
        "files": {
            ROOT_FILES["freeze"]: _sha_bytes(freeze_raw),
            ROOT_FILES["capacity"]: _sha_bytes(capacity_raw),
            ROOT_FILES["population_packet"]:
                _sha_bytes(population_packet_raw),
            ROOT_FILES["admission"]: _sha_bytes(admission_raw),
        },
        "authority": dict(SCIENTIFIC_ROOT_AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def initialize_scientific_root(
        root: Path, *, freeze_raw: bytes, capacity_raw: bytes,
        population_packet_raw: bytes, repo: Path,
        review_commit: str) -> dict[str, Any]:
    """Spend one admission before publishing any reusable scientific root."""
    freeze = _canonical(freeze_raw, "scientific freeze")
    _ = _canonical(capacity_raw, "scientific capacity")
    _ = _canonical(population_packet_raw, "scientific population packet")
    validate_experiment_freeze(
        freeze, capacity_raw, population_packet_raw)
    admission = build_admission(
        freeze, repo=repo, review_commit=review_commit)
    marker = reauthenticate_admission(
        admission, freeze=freeze, repo=repo)
    validate_admission(
        admission, freeze=freeze, review_marker=marker)
    admission_raw = canonical_json_bytes(admission)
    manifest = _root_manifest(
        freeze_raw=freeze_raw, capacity_raw=capacity_raw,
        population_packet_raw=population_packet_raw,
        admission_raw=admission_raw)

    resolved = root.resolve()
    parent = resolved.parent
    partial = parent / f".{resolved.name}.partial"
    lock = lock_root_for(resolved)
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink() \
            or lock.exists() or lock.is_symlink():
        raise WorldAfterstateScientificError(
            "scientific admission namespace occupied")

    # The sibling lock is deliberately published first.  Any later failure
    # consumes the admission and cannot be hidden by deleting the root.
    lock.mkdir(mode=0o700)
    initialization = {
        "schema": "world-afterstate-e3-e4-initialization-attempt-v0",
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
    try:
        for name, raw in (
                (ROOT_FILES["freeze"], freeze_raw),
                (ROOT_FILES["capacity"], capacity_raw),
                (ROOT_FILES["population_packet"], population_packet_raw),
                (ROOT_FILES["admission"], admission_raw),
                (ROOT_FILES["manifest"], canonical_json_bytes(manifest))):
            _write_once(partial / name, raw)
        (partial / "artifacts").mkdir(mode=0o700)
        _fsync_directory(partial / "artifacts")
        _fsync_directory(partial)
        os.rename(partial, resolved)
        os.chmod(resolved, 0o500)
        _fsync_directory(resolved)
        _fsync_directory(parent)
    except BaseException:
        raise
    return manifest


def reopen_scientific_root(root: Path, *, repo: Path):
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateScientificError(
            "scientific root identity drift")
    raws = {key: _sealed_read(root / name)
            for key, name in ROOT_FILES.items() if key != "manifest"}
    manifest_raw = _sealed_read(root / ROOT_FILES["manifest"])
    freeze = _canonical(raws["freeze"], "scientific freeze")
    capacity = _canonical(raws["capacity"], "scientific capacity")
    population_packet = _canonical(
        raws["population_packet"], "scientific population packet")
    admission = _canonical(raws["admission"], "scientific admission")
    manifest = _canonical(manifest_raw, "scientific manifest")
    validate_experiment_freeze(
        freeze, raws["capacity"], raws["population_packet"])
    marker = reauthenticate_admission(
        admission, freeze=freeze, repo=repo)
    validate_admission(admission, freeze=freeze, review_marker=marker)
    expected = _root_manifest(
        freeze_raw=raws["freeze"], capacity_raw=raws["capacity"],
        population_packet_raw=raws["population_packet"],
        admission_raw=raws["admission"])
    if canonical_json_bytes(manifest) != canonical_json_bytes(expected):
        raise WorldAfterstateScientificError(
            "scientific manifest reconstruction drift")
    lock = lock_root_for(root)
    initialize_raw = _sealed_read(lock / "initialize.json")
    initialize = _canonical(
        initialize_raw, "scientific initialization attempt")
    body = {key: item for key, item in initialize.items()
            if key != "attempt_sha256"}
    if initialize.get("freeze_sha256") != freeze["freeze_sha256"] \
            or initialize.get("admission_sha256") \
            != admission["admission_sha256"] \
            or initialize.get("retry_authorized") is not False \
            or initialize.get("attempt_sha256") != _sha(body):
        raise WorldAfterstateScientificError(
            "scientific initialization reconstruction drift")
    return freeze, capacity, population_packet, admission, manifest


def consume_stage_attempt(
        root: Path, *, stage: str, freeze_sha256: str,
        admission_sha256: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if stage not in STAGES or type(inputs) is not dict:
        raise WorldAfterstateScientificError(
            "scientific stage attempt request drift")
    _digest(freeze_sha256, "stage freeze SHA-256")
    _digest(admission_sha256, "stage admission SHA-256")
    lock = lock_root_for(root)
    if not lock.is_dir() or lock.is_symlink():
        raise WorldAfterstateScientificError(
            "scientific admission lock drift")
    target = lock / f"{stage}.json"
    if target.exists() or target.is_symlink():
        raise WorldAfterstateScientificError(
            "scientific stage attempt already consumed")
    body = {
        "schema": ATTEMPT_SCHEMA,
        "stage": stage,
        "freeze_sha256": freeze_sha256,
        "admission_sha256": admission_sha256,
        "inputs": dict(inputs),
        "started_monotonic_ns": time.monotonic_ns(),
        "retry_authorized": False,
        "authority": dict(SCIENTIFIC_ROOT_AUTHORITY),
    }
    attempt = {**body, "attempt_sha256": _sha(body)}
    _write_once(target, canonical_json_bytes(attempt))
    _fsync_directory(lock)
    _fsync_directory(lock.parent)
    return attempt


__all__ = [
    "ATTEMPT_SCHEMA", "ROOT_SCHEMA", "SCIENTIFIC_ROOT_AUTHORITY",
    "STAGES", "WorldAfterstateScientificError",
    "consume_stage_attempt", "initialize_scientific_root",
    "lock_root_for", "reopen_scientific_root",
]
