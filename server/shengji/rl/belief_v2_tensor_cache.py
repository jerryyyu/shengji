"""Opt-in hash-bound tensor cache for BELIEF-V1 V2 training batches.

The V2 design's performance plan anticipated this artifact: when canonical-row
parsing dominates, "publish a hash-bound train/calibration tensor cache that
contains actor features only and proves split/target isolation," keeping
privileged labels "in a separately bound artifact" and never materializing
test tensors before the sole test opening.

This module implements exactly that contract, additively.  Building the cache
serializes each already-collated batch as TWO separately hashed files — an
actor file (model inputs and constraint bounds, all actor-visible) and a
privileged file (``count_labels`` and ``active_mask``, the supervision) — plus
one canonical manifest binding split, batch order, decision keys, and both
hashes per batch.  Loading verifies every byte against the manifest before a
batch is reconstructed, refuses tampering, reordering, missing or extra
files, and refuses the ``test`` split at both build and load time.

Byte identity across rebuilds is deliberately NOT claimed (torch serialization
is not specified to be byte-stable); the load-bearing claims are content
parity — reloaded batches train byte-identically to freshly built ones — and
the manifest binding of the artifact as built.  R4 wires the cache into device
qualification, cohort training, and independent calibration re-scoring only
after the cache controller has reopened every byte.  No cache artifact grants
execution, test-opening, strength, or deployment authority.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import torch

from .belief_contract import canonical_json_bytes
from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_training import BeliefTrainingBatchV1


TENSOR_CACHE_SCHEMA = "belief-v1-v2-training-tensor-cache-v2"
LABEL_OVERLAY_SCHEMA = "belief-v1-v2-training-label-overlay-v1"
SPARSE_EVENTS_SCHEMA = "belief-v1-v2-lossless-sparse-events-v1"
MANIFEST_FILENAME = "manifest.json"
LABEL_MANIFEST_FILENAME = "labels-manifest.json"
CACHEABLE_SPLITS = ("train", "calibration")
PRIVILEGED_TENSOR_FIELDS = ("count_labels", "active_mask")
ACTOR_TENSOR_FIELDS = (
    "events", "event_lengths", "global_features", "card_features",
    "receiver_features", "receiver_mask", "unseen_mask",
    "count_minimums", "count_maximums")
_STATIC_FIELDS = (
    "split", "history_transform", "label_transform", "control_kind",
    "privileged_targets_consumed", "runtime_artifact", "schema")
_LABEL_STATIC_FIELDS = ("label_transform", "control_kind", "schema")
_CACHE_MANIFEST_KEYS = {
    "schema", "binding", "cache_id", "split", "batch_count", "batches",
    "actor_features_only_in_actor_files",
    "privileged_labels_separately_bound", "test_split_cached",
    "runtime_artifact", "training_authorized", "test_open_authorized",
    "strength_claim_authorized", "deployment_authorized",
}
_CACHE_BATCH_KEYS = {
    "index", "decision_keys", "actor_file", "actor_sha256",
    "privileged_file", "privileged_sha256", "static",
}
_OVERLAY_MANIFEST_KEYS = {
    "schema", "binding", "overlay_id", "actor_manifest_sha256",
    "batch_count", "batches", "contains_actor_tensors",
    "contains_privileged_labels", "test_split_cached", "runtime_artifact",
    "training_authorized", "test_open_authorized",
    "strength_claim_authorized", "deployment_authorized",
}
_OVERLAY_BATCH_KEYS = {
    "index", "decision_keys", "privileged_file", "privileged_sha256",
    "static",
}


class BeliefV2TensorCacheError(ValueError):
    """The tensor cache was misused, tampered with, or split-unsafe."""


@dataclass(frozen=True)
class V2TensorCacheBindingV1:
    cache_id: str
    split: str
    decision_population_sha256: str
    batch_schedule_sha256: str
    source_index_sha256: str
    runtime_profile_sha256: str
    expected_decision_count: int
    expected_batch_count: int
    storage_cap_bytes: int

    def to_dict(self) -> dict[str, Any]:
        _validate_binding(self)
        return {
            "cache_id": self.cache_id,
            "split": self.split,
            "decision_population_sha256": (
                self.decision_population_sha256),
            "batch_schedule_sha256": self.batch_schedule_sha256,
            "source_index_sha256": self.source_index_sha256,
            "runtime_profile_sha256": self.runtime_profile_sha256,
            "expected_decision_count": self.expected_decision_count,
            "expected_batch_count": self.expected_batch_count,
            "storage_cap_bytes": self.storage_cap_bytes,
        }


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _validate_binding(binding: V2TensorCacheBindingV1) -> None:
    if type(binding) is not V2TensorCacheBindingV1 \
            or type(binding.cache_id) is not str or not binding.cache_id \
            or binding.split not in CACHEABLE_SPLITS \
            or any(not _is_sha256(value) for value in (
                binding.decision_population_sha256,
                binding.batch_schedule_sha256,
                binding.source_index_sha256,
                binding.runtime_profile_sha256)) \
            or type(binding.expected_decision_count) is not int \
            or binding.expected_decision_count <= 0 \
            or type(binding.expected_batch_count) is not int \
            or binding.expected_batch_count <= 0 \
            or type(binding.storage_cap_bytes) is not int \
            or binding.storage_cap_bytes <= 0:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache binding drift")


def _require_cacheable_split(split: str) -> None:
    if split not in CACHEABLE_SPLITS:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache refuses non-train/calibration split")


def _serialize(value: Any) -> bytes:
    buffer = io.BytesIO()
    torch.save(value, buffer)
    return buffer.getvalue()


def _deserialize(raw: bytes) -> Any:
    return torch.load(io.BytesIO(raw), map_location="cpu",
                      weights_only=True)


def _encode_actor_tensors(batch: BeliefTrainingBatchV1) -> dict[str, Any]:
    events = batch.events
    if type(events) is not torch.Tensor or events.device.type != "cpu" \
            or events.dtype != torch.float32 or events.ndim != 3 \
            or not events.is_contiguous() or events.numel() >= 2**31:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache event tensor drift")
    flat = events.view(-1)
    indices = torch.nonzero(flat, as_tuple=False).view(-1).to(
        dtype=torch.int32)
    values = flat.index_select(0, indices.to(dtype=torch.int64))
    if values.numel():
        table, inverse = torch.unique(
            values, sorted=True, return_inverse=True)
        if len(table) > 256:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache sparse event alphabet overflow")
        codes = inverse.to(dtype=torch.uint8)
    else:
        table = torch.empty((0,), dtype=torch.float32)
        codes = torch.empty((0,), dtype=torch.uint8)
    return {
        "schema": SPARSE_EVENTS_SCHEMA,
        "shape": tuple(events.shape),
        "flat_indices_int32": indices,
        "value_table_float32": table,
        "value_codes_uint8": codes,
        "other_actor_tensors": {
            name: getattr(batch, name)
            for name in ACTOR_TENSOR_FIELDS if name != "events"
        },
    }


def _decode_actor_tensors(raw: bytes) -> dict[str, torch.Tensor]:
    try:
        payload = _deserialize(raw)
    except (RuntimeError, ValueError, EOFError) as exc:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache actor payload refused") from exc
    if type(payload) is not dict or set(payload) != {
            "schema", "shape", "flat_indices_int32",
            "value_table_float32", "value_codes_uint8",
            "other_actor_tensors"} \
            or payload["schema"] != SPARSE_EVENTS_SCHEMA \
            or type(payload["shape"]) is not tuple \
            or len(payload["shape"]) != 3 \
            or any(type(value) is not int or value <= 0
                   for value in payload["shape"]) \
            or type(payload["other_actor_tensors"]) is not dict \
            or set(payload["other_actor_tensors"]) \
            != set(ACTOR_TENSOR_FIELDS) - {"events"}:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache sparse event schema drift")
    indices = payload["flat_indices_int32"]
    table = payload["value_table_float32"]
    codes = payload["value_codes_uint8"]
    size = 1
    for value in payload["shape"]:
        size *= value
    if type(indices) is not torch.Tensor or indices.device.type != "cpu" \
            or indices.dtype != torch.int32 or indices.ndim != 1 \
            or type(table) is not torch.Tensor or table.device.type != "cpu" \
            or table.dtype != torch.float32 or table.ndim != 1 \
            or type(codes) is not torch.Tensor or codes.device.type != "cpu" \
            or codes.dtype != torch.uint8 or codes.ndim != 1 \
            or len(indices) != len(codes) \
            or len(table) > 256 \
            or bool(torch.any(table == 0)) \
            or (len(table) > 1 and bool(torch.any(table[1:] <= table[:-1]))) \
            or len(indices) and (
                int(indices[0]) < 0 or int(indices[-1]) >= size
                or len(indices) > 1
                and bool(torch.any(indices[1:] <= indices[:-1]))) \
            or len(codes) and (
                not len(table) or int(codes.max()) >= len(table)):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache sparse event value drift")
    events = torch.zeros(payload["shape"], dtype=torch.float32)
    if len(indices):
        events.view(-1).index_copy_(
            0, indices.to(dtype=torch.int64),
            table.index_select(0, codes.to(dtype=torch.int64)))
    return {"events": events, **payload["other_actor_tensors"]}


def _partial_path(directory: Path) -> Path:
    return directory.with_name(directory.name + ".partial")


def _publish_cache_file(path: Path, raw: bytes) -> None:
    try:
        publish_exclusive_bytes(path, raw)
    except ValueError as exc:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache publication refused") from exc


def _discard_incomplete_atomic_write(path: Path) -> None:
    partial = path.with_name(path.name + ".partial")
    if not partial.exists() and not partial.is_symlink():
        return
    if path.exists() or path.is_symlink() or partial.is_symlink() \
            or not partial.is_file():
        raise BeliefV2TensorCacheError(
            "V2 tensor cache incomplete publication drift")
    partial.unlink()


def _actor_file_content_matches(
        raw: bytes, batch: BeliefTrainingBatchV1) -> bool:
    try:
        decoded = _decode_actor_tensors(raw)
    except ValueError:
        return False
    return set(decoded) == set(ACTOR_TENSOR_FIELDS) \
        and all(torch.equal(decoded[name], getattr(batch, name))
                for name in ACTOR_TENSOR_FIELDS)


def _privileged_file_content_matches(
        raw: bytes, batch: BeliefTrainingBatchV1) -> bool:
    try:
        decoded = _deserialize(raw)
    except (RuntimeError, ValueError, EOFError):
        return False
    return type(decoded) is dict \
        and set(decoded) == set(PRIVILEGED_TENSOR_FIELDS) \
        and all(torch.equal(decoded[name], getattr(batch, name))
                for name in PRIVILEGED_TENSOR_FIELDS)


def _reuse_or_publish_batch_file(
        path: Path, raw: bytes, *, batch: BeliefTrainingBatchV1,
        privileged: bool) -> tuple[bytes, bool]:
    _discard_incomplete_atomic_write(path)
    if path.exists() or path.is_symlink():
        existing = stable_read_bytes(path)
        matches = (_privileged_file_content_matches(existing, batch)
                   if privileged else
                   _actor_file_content_matches(existing, batch))
        if not matches:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache resumed batch content drift")
        return existing, True
    _publish_cache_file(path, raw)
    return raw, False


def _reuse_or_publish_exact_file(path: Path, raw: bytes) -> bool:
    _discard_incomplete_atomic_write(path)
    if path.exists() or path.is_symlink():
        if stable_read_bytes(path) != raw:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache resumed manifest drift")
        return True
    _publish_cache_file(path, raw)
    return False


def _finish_directory(partial: Path, final: Path) -> None:
    os.rename(partial, final)
    descriptor = os.open(final.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build_tensor_cache(
        directory: Path, *, batches: Callable[[], Any],
        binding: V2TensorCacheBindingV1,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> dict[str, Any]:
    """Serialize one batch stream into a fresh hash-bound cache directory."""
    if not isinstance(directory, Path) or not callable(batches):
        raise BeliefV2TensorCacheError("V2 tensor cache build inputs drift")
    _validate_binding(binding)
    if (deadline_check is not None and not callable(deadline_check)) \
            or (progress is not None and not callable(progress)):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache callback drift")
    split = binding.split
    partial = _partial_path(directory)
    if directory.exists() or directory.is_symlink():
        raise BeliefV2TensorCacheError(
            "V2 tensor cache directory already exists")
    if partial.is_symlink() \
            or partial.exists() and not partial.is_dir():
        raise BeliefV2TensorCacheError(
            "V2 tensor cache partial drift")
    partial.mkdir(parents=True, mode=0o700, exist_ok=True)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    if progress is not None:
        progress(0, binding.expected_batch_count, binding.cache_id)
    for index, batch in enumerate(batches()):
        if deadline_check is not None:
            deadline_check("before-unit", index)
        if type(batch) is not BeliefTrainingBatchV1:
            raise BeliefV2TensorCacheError("V2 tensor cache batch type drift")
        if batch.split != split:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache batch split drift")
        if not batch.decision_keys \
                or any(key in seen for key in batch.decision_keys):
            raise BeliefV2TensorCacheError(
                "V2 tensor cache duplicate decision")
        seen.update(batch.decision_keys)
        actor_candidate = _serialize(_encode_actor_tensors(batch))
        privileged_candidate = _serialize(
            {name: getattr(batch, name)
             for name in PRIVILEGED_TENSOR_FIELDS})
        actor_name = f"batch-{index:05d}.actor.pt"
        privileged_name = f"batch-{index:05d}.labels.pt"
        actor_raw, _ = _reuse_or_publish_batch_file(
            partial / actor_name, actor_candidate, batch=batch,
            privileged=False)
        privileged_raw, _ = _reuse_or_publish_batch_file(
            partial / privileged_name, privileged_candidate, batch=batch,
            privileged=True)
        total_bytes += len(actor_raw) + len(privileged_raw)
        if total_bytes > binding.storage_cap_bytes:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache storage cap exceeded")
        rows.append({
            "index": index,
            "decision_keys": list(batch.decision_keys),
            "actor_file": actor_name,
            "actor_sha256": _sha256(actor_raw),
            "privileged_file": privileged_name,
            "privileged_sha256": _sha256(privileged_raw),
            "static": {name: getattr(batch, name)
                       for name in _STATIC_FIELDS},
        })
        if deadline_check is not None:
            deadline_check("after-unit", index + 1)
        if progress is not None:
            progress(index + 1, binding.expected_batch_count,
                     binding.cache_id)
    if not rows:
        raise BeliefV2TensorCacheError("V2 tensor cache is empty")
    if len(rows) != binding.expected_batch_count \
            or len(seen) != binding.expected_decision_count:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache bound population drift")
    manifest = {
        "schema": TENSOR_CACHE_SCHEMA,
        "binding": binding.to_dict(),
        "cache_id": binding.cache_id,
        "split": split,
        "batch_count": len(rows),
        "batches": rows,
        "actor_features_only_in_actor_files": True,
        "privileged_labels_separately_bound": True,
        "test_split_cached": False,
        "runtime_artifact": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    raw_manifest = canonical_json_bytes(manifest)
    if total_bytes + len(raw_manifest) > binding.storage_cap_bytes:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache storage cap exceeded")
    if deadline_check is not None:
        deadline_check("before-seal", binding.expected_batch_count)
    expected_files = {MANIFEST_FILENAME, *(
        name for row in rows
        for name in (row["actor_file"], row["privileged_file"]))}
    if {path.name for path in partial.iterdir()} - {MANIFEST_FILENAME} \
            != expected_files - {MANIFEST_FILENAME}:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache resumed file population drift")
    _reuse_or_publish_exact_file(partial / MANIFEST_FILENAME, raw_manifest)
    _finish_directory(partial, directory)
    return {"manifest_sha256": _sha256(raw_manifest),
            "batch_count": len(rows), "decision_count": len(seen),
            "artifact_bytes": total_bytes + len(raw_manifest)}


def _load_manifest(
        directory: Path, expected_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    _validate_binding(binding)
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir():
        raise BeliefV2TensorCacheError(
            "V2 tensor cache directory drift")
    raw = stable_read_bytes(directory / MANIFEST_FILENAME)
    if _sha256(raw) != expected_manifest_sha256:
        raise BeliefV2TensorCacheError("V2 tensor cache manifest drift")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache manifest is not JSON") from exc
    if type(manifest) is not dict \
            or set(manifest) != _CACHE_MANIFEST_KEYS \
            or canonical_json_bytes(manifest) != raw \
            or manifest.get("schema") != TENSOR_CACHE_SCHEMA \
            or manifest.get("binding") != binding.to_dict() \
            or manifest.get("cache_id") != binding.cache_id \
            or manifest.get("split") != binding.split \
            or manifest.get("actor_features_only_in_actor_files") is not True \
            or manifest.get("privileged_labels_separately_bound") is not True \
            or manifest.get("test_split_cached") is not False \
            or type(manifest.get("batches")) is not list \
            or type(manifest.get("batch_count")) is not int \
            or any(manifest.get(key) is not False for key in (
                "runtime_artifact", "training_authorized",
                "test_open_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache manifest schema/authority drift")
    _require_cacheable_split(manifest["split"])
    rows = manifest["batches"]
    if manifest["batch_count"] != len(rows) \
            or manifest["batch_count"] != binding.expected_batch_count \
            or any(type(row) is not dict or set(row) != _CACHE_BATCH_KEYS
                   for row in rows) \
            or [row["index"] for row in rows] \
            != list(range(manifest["batch_count"])) \
            or any(type(row["decision_keys"]) is not list
                   or not row["decision_keys"]
                   or any(type(key) is not str or not key
                          for key in row["decision_keys"])
                   or row["actor_file"] != (
                       f"batch-{row['index']:05d}.actor.pt")
                   or row["privileged_file"] != (
                       f"batch-{row['index']:05d}.labels.pt")
                   or not _is_sha256(row["actor_sha256"])
                   or not _is_sha256(row["privileged_sha256"])
                   or type(row["static"]) is not dict
                   or set(row["static"]) != set(_STATIC_FIELDS)
                   for row in rows):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache manifest population drift")
    keys = tuple(key for row in rows
                 for key in row["decision_keys"])
    if len(keys) != binding.expected_decision_count \
            or len(keys) != len(set(keys)):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache manifest duplicate/population drift")
    expected_files = {MANIFEST_FILENAME}
    for row in rows:
        expected_files.add(row["actor_file"])
        expected_files.add(row["privileged_file"])
    actual_files = {path.name for path in directory.iterdir()}
    if actual_files != expected_files:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache file population drift")
    return manifest


def reopen_tensor_cache(
        directory: Path, *, expected_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    """Reopen and hash every byte of one completed actor/label cache."""
    manifest = _load_manifest(
        directory, expected_manifest_sha256, binding)
    total_bytes = len(stable_read_bytes(directory / MANIFEST_FILENAME))
    for row in manifest["batches"]:
        actor_raw = stable_read_bytes(directory / row["actor_file"])
        label_raw = stable_read_bytes(directory / row["privileged_file"])
        if _sha256(actor_raw) != row["actor_sha256"] \
                or _sha256(label_raw) != row["privileged_sha256"]:
            raise BeliefV2TensorCacheError(
                f"V2 tensor cache batch {row['index']} byte drift")
        total_bytes += len(actor_raw) + len(label_raw)
    if total_bytes > binding.storage_cap_bytes:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache storage cap exceeded")
    return {
        "manifest_sha256": expected_manifest_sha256,
        "batch_count": manifest["batch_count"],
        "decision_count": sum(
            len(row["decision_keys"]) for row in manifest["batches"]),
        "artifact_bytes": total_bytes,
    }


def _tensors_equal(
        batch: BeliefTrainingBatchV1,
        expected: dict[str, torch.Tensor]) -> bool:
    return set(expected) == set(ACTOR_TENSOR_FIELDS) \
        and all(torch.equal(getattr(batch, name), expected[name])
                for name in ACTOR_TENSOR_FIELDS)


def build_label_overlay(
        directory: Path, *, batches: Callable[[], Any],
        actor_directory: Path, actor_manifest_sha256: str,
        binding: V2TensorCacheBindingV1, overlay_id: str,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> dict[str, Any]:
    """Publish alternate labels over one exact shared actor cache.

    The builder compares every actor tensor and ordered decision key against
    the already sealed actor cache.  Therefore a label-control cohort can
    share the approximately 97.5% actor payload without gaining a second
    actor representation or a schedule-dependent ambiguity.
    """
    if not isinstance(directory, Path) or not callable(batches) \
            or not _is_sha256(overlay_id) \
            or (deadline_check is not None and not callable(deadline_check)) \
            or (progress is not None and not callable(progress)):
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay build inputs drift")
    actor_manifest = _load_manifest(
        actor_directory, actor_manifest_sha256, binding)
    partial = _partial_path(directory)
    if directory.exists() or directory.is_symlink():
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay directory already exists")
    if partial.is_symlink() \
            or partial.exists() and not partial.is_dir():
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay partial drift")
    partial.mkdir(parents=True, mode=0o700, exist_ok=True)
    rows = []
    seen: set[str] = set()
    total_bytes = 0
    iterator = iter(batches())
    if progress is not None:
        progress(0, binding.expected_batch_count, overlay_id)
    for actor_row in actor_manifest["batches"]:
        if deadline_check is not None:
            deadline_check("before-unit", actor_row["index"])
        try:
            batch = next(iterator)
        except StopIteration as exc:
            raise BeliefV2TensorCacheError(
                "V2 tensor label overlay batch population drift") from exc
        if type(batch) is not BeliefTrainingBatchV1 \
                or batch.split != binding.split \
                or tuple(actor_row["decision_keys"]) != batch.decision_keys \
                or any(key in seen for key in batch.decision_keys):
            raise BeliefV2TensorCacheError(
                "V2 tensor label overlay identity drift")
        actor = _decode_actor_tensors(stable_read_bytes(
            actor_directory / actor_row["actor_file"]))
        if not _tensors_equal(batch, actor) \
                or any(getattr(batch, name) != actor_row["static"][name]
                       for name in _STATIC_FIELDS
                       if name not in _LABEL_STATIC_FIELDS):
            raise BeliefV2TensorCacheError(
                "V2 tensor label overlay actor drift")
        seen.update(batch.decision_keys)
        candidate = _serialize({name: getattr(batch, name)
                                for name in PRIVILEGED_TENSOR_FIELDS})
        name = f"batch-{actor_row['index']:05d}.labels.pt"
        raw, _ = _reuse_or_publish_batch_file(
            partial / name, candidate, batch=batch, privileged=True)
        total_bytes += len(raw)
        if total_bytes > binding.storage_cap_bytes:
            raise BeliefV2TensorCacheError(
                "V2 tensor label overlay storage cap exceeded")
        rows.append({
            "index": actor_row["index"],
            "decision_keys": list(batch.decision_keys),
            "privileged_file": name,
            "privileged_sha256": _sha256(raw),
            "static": {field: getattr(batch, field)
                       for field in _LABEL_STATIC_FIELDS},
        })
        if deadline_check is not None:
            deadline_check("after-unit", actor_row["index"] + 1)
        if progress is not None:
            progress(actor_row["index"] + 1,
                     binding.expected_batch_count, overlay_id)
    try:
        next(iterator)
    except StopIteration:
        pass
    else:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay batch population drift")
    if len(rows) != binding.expected_batch_count \
            or len(seen) != binding.expected_decision_count:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay bound population drift")
    manifest = {
        "schema": LABEL_OVERLAY_SCHEMA,
        "binding": binding.to_dict(),
        "overlay_id": overlay_id,
        "actor_manifest_sha256": actor_manifest_sha256,
        "batch_count": len(rows),
        "batches": rows,
        "contains_actor_tensors": False,
        "contains_privileged_labels": True,
        "test_split_cached": False,
        "runtime_artifact": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    raw = canonical_json_bytes(manifest)
    if total_bytes + len(raw) > binding.storage_cap_bytes:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay storage cap exceeded")
    if deadline_check is not None:
        deadline_check("before-seal", binding.expected_batch_count)
    expected_files = {LABEL_MANIFEST_FILENAME, *(
        row["privileged_file"] for row in rows)}
    if {path.name for path in partial.iterdir()} \
            - {LABEL_MANIFEST_FILENAME} \
            != expected_files - {LABEL_MANIFEST_FILENAME}:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay resumed file population drift")
    _reuse_or_publish_exact_file(partial / LABEL_MANIFEST_FILENAME, raw)
    _finish_directory(partial, directory)
    return {
        "manifest_sha256": _sha256(raw),
        "batch_count": len(rows), "decision_count": len(seen),
        "artifact_bytes": total_bytes + len(raw),
    }


def _load_label_overlay(
        directory: Path, *, expected_manifest_sha256: str,
        actor_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir():
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay directory drift")
    raw = stable_read_bytes(directory / LABEL_MANIFEST_FILENAME)
    if _sha256(raw) != expected_manifest_sha256:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay manifest drift")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay manifest is not JSON") from exc
    if type(manifest) is not dict \
            or set(manifest) != _OVERLAY_MANIFEST_KEYS \
            or canonical_json_bytes(manifest) != raw \
            or manifest.get("schema") != LABEL_OVERLAY_SCHEMA \
            or manifest.get("binding") != binding.to_dict() \
            or not _is_sha256(manifest.get("overlay_id")) \
            or manifest.get("actor_manifest_sha256") \
            != actor_manifest_sha256 \
            or type(manifest.get("batches")) is not list \
            or type(manifest.get("batch_count")) is not int \
            or manifest.get("batch_count") != binding.expected_batch_count \
            or manifest.get("contains_actor_tensors") is not False \
            or manifest.get("contains_privileged_labels") is not True \
            or manifest.get("test_split_cached") is not False \
            or any(manifest.get(key) is not False for key in (
                "runtime_artifact", "training_authorized",
                "test_open_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay schema/binding drift")
    rows = manifest["batches"]
    if any(type(row) is not dict or set(row) != _OVERLAY_BATCH_KEYS
           or type(row["decision_keys"]) is not list
           or not row["decision_keys"]
           or any(type(key) is not str or not key
                  for key in row["decision_keys"])
           or row["privileged_file"] != (
               f"batch-{row['index']:05d}.labels.pt")
           or not _is_sha256(row["privileged_sha256"])
           or type(row["static"]) is not dict
           or set(row["static"]) != set(_LABEL_STATIC_FIELDS)
           for row in rows):
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay population drift")
    keys = tuple(key for row in rows for key in row["decision_keys"])
    expected_files = {LABEL_MANIFEST_FILENAME, *(
        row["privileged_file"] for row in rows)}
    if [row["index"] for row in rows] \
            != list(range(binding.expected_batch_count)) \
            or len(keys) != binding.expected_decision_count \
            or len(keys) != len(set(keys)) \
            or {path.name for path in directory.iterdir()} != expected_files:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay population drift")
    return manifest


def reopen_label_overlay(
        directory: Path, *, expected_manifest_sha256: str,
        actor_manifest_sha256: str,
        binding: V2TensorCacheBindingV1) -> dict[str, Any]:
    """Reopen and hash every byte of one completed label-only overlay."""
    manifest = _load_label_overlay(
        directory, expected_manifest_sha256=expected_manifest_sha256,
        actor_manifest_sha256=actor_manifest_sha256, binding=binding)
    total_bytes = len(stable_read_bytes(
        directory / LABEL_MANIFEST_FILENAME))
    for row in manifest["batches"]:
        raw = stable_read_bytes(directory / row["privileged_file"])
        if _sha256(raw) != row["privileged_sha256"]:
            raise BeliefV2TensorCacheError(
                f"V2 tensor label overlay batch {row['index']} byte drift")
        total_bytes += len(raw)
    if total_bytes > binding.storage_cap_bytes:
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay storage cap exceeded")
    return {
        "manifest_sha256": expected_manifest_sha256,
        "batch_count": manifest["batch_count"],
        "decision_count": sum(
            len(row["decision_keys"]) for row in manifest["batches"]),
        "artifact_bytes": total_bytes,
    }


def cached_batch_factory(
        directory: Path, *,
        expected_manifest_sha256: str,
        binding: V2TensorCacheBindingV1,
        label_overlay_directory: Path | None = None,
        expected_label_overlay_sha256: str | None = None) \
        -> Callable[[], Iterator[Any]]:
    """Return a trainer-compatible factory that replays the verified cache.

    Composes with ``pipelined_batches``: wrap the returned factory to overlap
    cache deserialization with the member step.
    """
    if not isinstance(directory, Path) \
            or not _is_sha256(expected_manifest_sha256):
        raise BeliefV2TensorCacheError("V2 tensor cache load inputs drift")
    _validate_binding(binding)
    if (label_overlay_directory is None) \
            != (expected_label_overlay_sha256 is None) \
            or expected_label_overlay_sha256 is not None \
            and not _is_sha256(expected_label_overlay_sha256):
        raise BeliefV2TensorCacheError(
            "V2 tensor label overlay load inputs drift")

    def factory() -> Iterator[BeliefTrainingBatchV1]:
        manifest = _load_manifest(
            directory, expected_manifest_sha256, binding)
        overlay = (None if label_overlay_directory is None else
                   _load_label_overlay(
                       label_overlay_directory,
                       expected_manifest_sha256=(
                           expected_label_overlay_sha256),
                       actor_manifest_sha256=expected_manifest_sha256,
                       binding=binding))
        overlay_rows = (manifest["batches"] if overlay is None
                        else overlay["batches"])
        for row, label_row in zip(
                manifest["batches"], overlay_rows, strict=True):
            if row["index"] != label_row["index"] \
                    or row["decision_keys"] != label_row["decision_keys"]:
                raise BeliefV2TensorCacheError(
                    "V2 tensor label overlay/actor order drift")
            actor_raw = stable_read_bytes(directory / row["actor_file"])
            privileged_raw = stable_read_bytes(
                (directory if overlay is None
                 else label_overlay_directory)
                / label_row["privileged_file"])
            if _sha256(actor_raw) != row["actor_sha256"] \
                    or _sha256(privileged_raw) \
                    != label_row["privileged_sha256"]:
                raise BeliefV2TensorCacheError(
                    f"V2 tensor cache batch {row['index']} byte drift")
            actor = _decode_actor_tensors(actor_raw)
            privileged = _deserialize(privileged_raw)
            if set(actor) != set(ACTOR_TENSOR_FIELDS) \
                    or set(privileged) != set(PRIVILEGED_TENSOR_FIELDS):
                raise BeliefV2TensorCacheError(
                    f"V2 tensor cache batch {row['index']} field drift")
            yield BeliefTrainingBatchV1(
                decision_keys=tuple(row["decision_keys"]),
                **{**row["static"], **label_row["static"]},
                **actor, **privileged)

    return factory
