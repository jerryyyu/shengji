"""Authenticate one reviewed, immutable V2 tensor-cache import source.

The import is deliberately narrow.  It does not resume or relabel the spent
source admission, and it never copies, links, or mutates its files.  A fresh
pipeline may reference the individually sealed non-test cache components only
when its exact evidence root matches the tracked import specification and all
source identity, consumption, runtime, index, ownership, and byte bindings
reopen independently.
"""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_freeze import (
    V2ExecutionFreezeV1,
    execution_freeze_from_bytes,
    pipeline_admission_from_bytes,
    validate_pipeline_consumption_tombstone,
)


CACHE_IMPORT_SPEC_SCHEMA = "belief-v1-v2-tensor-cache-import-spec-v1"
CACHE_IMPORT_SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts" / "belief_v2_r5_cache_import.v1.json")
CACHE_IMPORT_SOURCE_PATH = "server/scripts/belief_v2_r5_cache_import.v1.json"
EXPECTED_CACHE_DIRECTORIES = {
    "cache-common-calibration",
    "cache-human-mixture",
    "cache-synthetic-primary",
    "cache-synthetic-scale-50",
    "overlay-hard-geometry-label-permutation",
}


class BeliefV2CacheImportError(ValueError):
    """A reusable cache source or its spent-attempt binding drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _reject_number(value: str) -> None:
    raise BeliefV2CacheImportError(
        f"V2 cache import contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefV2CacheImportError(
                "V2 cache import contains a duplicate key")
        result[key] = value
    return result


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefV2CacheImportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2CacheImportError(
            "V2 cache import spec is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise BeliefV2CacheImportError(
            "V2 cache import spec is not canonical JSON")
    return value


def _require_directory(path: Path, *, uid: int) -> None:
    if path.is_symlink() or not path.is_dir():
        raise BeliefV2CacheImportError(
            "V2 cache import directory identity drift")
    info = path.stat()
    if info.st_uid != uid or not stat.S_ISDIR(info.st_mode) \
            or info.st_mode & 0o077:
        raise BeliefV2CacheImportError(
            "V2 cache import directory ownership/mode drift")


@dataclass(frozen=True)
class V2TensorCacheImportSpecV1:
    destination_evidence_root: Path
    source_evidence_root: Path
    source_cache_root: Path
    source_execution_git: str
    source_freeze_sha256: str
    source_admission_sha256: str
    source_review_marker_sha256: str
    source_consumption_tombstone_sha256: str
    source_input_index_sha256: str
    source_input_index_manifest_sha256: str
    source_runtime_profile_sha256: str
    source_stage_start_sha256: str
    child_manifest_sha256s: tuple[tuple[str, str], ...]
    required_uid: int
    spec_sha256: str

    def child_manifest_sha256(self, directory: str) -> str:
        matches = [value for name, value in self.child_manifest_sha256s
                   if name == directory]
        if len(matches) != 1:
            raise BeliefV2CacheImportError(
                "V2 cache import child manifest population drift")
        return matches[0]


def load_tensor_cache_import_spec(
        freeze: V2ExecutionFreezeV1) -> V2TensorCacheImportSpecV1 | None:
    """Return the exact import only for its named fresh evidence root."""
    try:
        spec_raw = CACHE_IMPORT_SPEC_PATH.read_bytes()
        payload = _strict_json(spec_raw)
    except (OSError, ValueError) as exc:
        raise BeliefV2CacheImportError(
            "V2 cache import spec reopen refused") from exc
    keys = {
        "schema", "destination_evidence_root", "source_evidence_root",
        "source_cache_root", "source_execution_git",
        "source_freeze_sha256", "source_admission_sha256",
        "source_review_marker_sha256",
        "source_consumption_tombstone_sha256",
        "source_input_index_sha256",
        "source_input_index_manifest_sha256",
        "source_runtime_profile_sha256", "source_stage_start_sha256",
        "child_manifest_sha256s", "required_uid", "authority",
    }
    authority = payload.get("authority")
    if set(payload) != keys or payload.get("schema") \
            != CACHE_IMPORT_SPEC_SCHEMA or type(authority) is not dict \
            or authority != {
                "retry_authorized": False,
                "test_split_cached": False,
                "test_split_open_authorized": False,
                "training_authorized_by_source_artifact": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "deployment_authorized": False,
            }:
        raise BeliefV2CacheImportError(
            "V2 cache import spec field/authority drift")
    if type(payload.get("destination_evidence_root")) is not str:
        raise BeliefV2CacheImportError(
            "V2 cache import destination field drift")
    destination = Path(payload["destination_evidence_root"])
    if destination != Path(freeze.evidence_root):
        return None
    source_bindings = tuple(
        row for row in freeze.source_bindings
        if row.path == CACHE_IMPORT_SOURCE_PATH)
    if len(source_bindings) != 1 \
            or source_bindings[0].byte_count != len(spec_raw) \
            or source_bindings[0].sha256 != _sha256(spec_raw):
        raise BeliefV2CacheImportError(
            "V2 cache import parsed bytes are not freeze-bound")
    if type(payload.get("source_evidence_root")) is not str \
            or type(payload.get("source_cache_root")) is not str:
        raise BeliefV2CacheImportError(
            "V2 cache import source path field drift")
    source = Path(payload["source_evidence_root"])
    cache_root = Path(payload["source_cache_root"])
    child = payload.get("child_manifest_sha256s")
    uid = payload.get("required_uid")
    sha_values = (
        payload.get("source_freeze_sha256"),
        payload.get("source_admission_sha256"),
        payload.get("source_review_marker_sha256"),
        payload.get("source_consumption_tombstone_sha256"),
        payload.get("source_input_index_sha256"),
        payload.get("source_input_index_manifest_sha256"),
        payload.get("source_runtime_profile_sha256"),
        payload.get("source_stage_start_sha256"),
    )
    if not destination.is_absolute() or not source.is_absolute() \
            or not cache_root.is_absolute() \
            or cache_root != (source / "training-tensor-cache"
                              / "result.partial") \
            or type(payload.get("source_execution_git")) is not str \
            or len(payload["source_execution_git"]) != 40 \
            or not all(char in "0123456789abcdef"
                       for char in payload["source_execution_git"]) \
            or any(not _is_sha256(value) for value in sha_values) \
            or type(uid) is not int or uid < 0 or type(child) is not dict \
            or set(child) != EXPECTED_CACHE_DIRECTORIES \
            or any(not _is_sha256(value) for value in child.values()):
        raise BeliefV2CacheImportError(
            "V2 cache import identity field drift")

    _require_directory(source, uid=uid)
    _require_directory(source / "training-tensor-cache", uid=uid)
    _require_directory(cache_root, uid=uid)
    for name in EXPECTED_CACHE_DIRECTORIES:
        _require_directory(cache_root / name, uid=uid)
    if {path.name for path in cache_root.iterdir()} \
            != EXPECTED_CACHE_DIRECTORIES | {"stage-start.json"} \
            or {path.name for path in (source / "training-tensor-cache")
                .iterdir()} != {"result.partial"} \
            or (source / "training-tensor-cache" / "result").exists() \
            or (cache_root / "manifest.json").exists() \
            or (cache_root / "resource-refusal.json").exists():
        raise BeliefV2CacheImportError(
            "V2 cache import source population drift")

    freeze_raw = stable_read_bytes(source / "freeze.json")
    review_raw = stable_read_bytes(source / "review.md")
    admission_raw = stable_read_bytes(source / "admission.json")
    tombstone_raw = stable_read_bytes(
        source.with_name(source.name + ".consumed.json"))
    index_raw = stable_read_bytes(
        source / "training-input-index" / "result" / "index.json")
    index_manifest_raw = stable_read_bytes(
        source / "training-input-index" / "result" / "manifest.json")
    start_raw = stable_read_bytes(cache_root / "stage-start.json")
    actual = (
        _sha256(freeze_raw), _sha256(admission_raw), _sha256(review_raw),
        _sha256(tombstone_raw), _sha256(index_raw),
        _sha256(index_manifest_raw), _sha256(start_raw),
    )
    expected = (
        payload["source_freeze_sha256"],
        payload["source_admission_sha256"],
        payload["source_review_marker_sha256"],
        payload["source_consumption_tombstone_sha256"],
        payload["source_input_index_sha256"],
        payload["source_input_index_manifest_sha256"],
        payload["source_stage_start_sha256"],
    )
    if actual != expected:
        raise BeliefV2CacheImportError(
            "V2 cache import source byte binding drift")
    try:
        old_freeze = execution_freeze_from_bytes(freeze_raw)
        old_admission = pipeline_admission_from_bytes(
            admission_raw, freeze=old_freeze, review_marker=review_raw)
        validate_pipeline_consumption_tombstone(
            tombstone_raw, admission=old_admission)
    except ValueError as exc:
        raise BeliefV2CacheImportError(
            "V2 cache import spent admission reopen refused") from exc
    try:
        start_payload = _strict_json(start_raw)
    except ValueError as exc:
        raise BeliefV2CacheImportError(
            "V2 cache import source stage start refused") from exc
    started = start_payload.get("started_monotonic_nanoseconds")
    if type(started) is not int or started <= 0 or start_payload != {
            "schema": "belief-v1-v2-training-tensor-cache-start-v1",
            "freeze_sha256": old_freeze.sha256(),
            "admission_sha256": old_admission.sha256(),
            "training_input_index_sha256": (
                payload["source_input_index_sha256"]),
            "boot_identity": old_freeze.runtime.boot_identity,
            "started_monotonic_nanoseconds": started,
            "retry_authorized": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
            }:
        raise BeliefV2CacheImportError(
            "V2 cache import source stage start drift")
    runtime_sha256 = _sha256(canonical_json_bytes(
        old_freeze.runtime.to_dict()))
    old_portable_runtime = old_freeze.runtime.to_dict()
    current_portable_runtime = freeze.runtime.to_dict()
    del old_portable_runtime["boot_identity"]
    del current_portable_runtime["boot_identity"]
    if old_freeze.execution_git != payload["source_execution_git"] \
            or old_freeze.evidence_root != str(source) \
            or old_admission.evidence_root != str(source) \
            or old_freeze.sha256() != payload["source_freeze_sha256"] \
            or old_admission.sha256() != payload["source_admission_sha256"] \
            or runtime_sha256 != payload["source_runtime_profile_sha256"] \
            or current_portable_runtime != old_portable_runtime \
            or freeze.resource_caps.training_bytes \
            != old_freeze.resource_caps.training_bytes:
        raise BeliefV2CacheImportError(
            "V2 cache import source runtime/cap identity drift")
    return V2TensorCacheImportSpecV1(
        destination_evidence_root=destination,
        source_evidence_root=source,
        source_cache_root=cache_root,
        source_execution_git=payload["source_execution_git"],
        source_freeze_sha256=payload["source_freeze_sha256"],
        source_admission_sha256=payload["source_admission_sha256"],
        source_review_marker_sha256=(
            payload["source_review_marker_sha256"]),
        source_consumption_tombstone_sha256=(
            payload["source_consumption_tombstone_sha256"]),
        source_input_index_sha256=payload["source_input_index_sha256"],
        source_input_index_manifest_sha256=(
            payload["source_input_index_manifest_sha256"]),
        source_runtime_profile_sha256=(
            payload["source_runtime_profile_sha256"]),
        source_stage_start_sha256=payload["source_stage_start_sha256"],
        child_manifest_sha256s=tuple(sorted(child.items())),
        required_uid=uid, spec_sha256=_sha256(spec_raw))
