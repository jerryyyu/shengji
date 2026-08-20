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
the manifest binding of the artifact as built.  Nothing here is wired into any
reviewed path; adoption is a V3 design decision.  No execution authority.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Callable, Iterator

import torch

from .belief_contract import canonical_json_bytes
from .belief_training import BeliefTrainingBatchV1


TENSOR_CACHE_SCHEMA = "belief-v1-v2-training-tensor-cache-v1"
MANIFEST_FILENAME = "manifest.json"
CACHEABLE_SPLITS = ("train", "calibration")
PRIVILEGED_TENSOR_FIELDS = ("count_labels", "active_mask")
ACTOR_TENSOR_FIELDS = (
    "events", "event_lengths", "global_features", "card_features",
    "receiver_features", "receiver_mask", "unseen_mask",
    "count_minimums", "count_maximums")
_STATIC_FIELDS = (
    "split", "history_transform", "label_transform", "control_kind",
    "privileged_targets_consumed", "runtime_artifact", "schema")


class BeliefV2TensorCacheError(ValueError):
    """The tensor cache was misused, tampered with, or split-unsafe."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_cacheable_split(split: str) -> None:
    if split not in CACHEABLE_SPLITS:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache refuses non-train/calibration split")


def _serialize(tensors: dict[str, torch.Tensor]) -> bytes:
    buffer = io.BytesIO()
    torch.save(tensors, buffer)
    return buffer.getvalue()


def _deserialize(raw: bytes) -> dict[str, torch.Tensor]:
    return torch.load(io.BytesIO(raw), map_location="cpu",
                      weights_only=True)


def build_tensor_cache(
        directory: Path, *, batches: Callable[[], Any],
        cache_id: str, split: str) -> dict[str, Any]:
    """Serialize one batch stream into a fresh hash-bound cache directory."""
    if not isinstance(directory, Path) or not callable(batches) \
            or type(cache_id) is not str or not cache_id:
        raise BeliefV2TensorCacheError("V2 tensor cache build inputs drift")
    _require_cacheable_split(split)
    if directory.exists():
        raise BeliefV2TensorCacheError(
            "V2 tensor cache directory already exists")
    directory.mkdir(parents=True, mode=0o700)
    rows: list[dict[str, Any]] = []
    for index, batch in enumerate(batches()):
        if type(batch) is not BeliefTrainingBatchV1:
            raise BeliefV2TensorCacheError("V2 tensor cache batch type drift")
        if batch.split != split:
            raise BeliefV2TensorCacheError(
                "V2 tensor cache batch split drift")
        actor_raw = _serialize(
            {name: getattr(batch, name) for name in ACTOR_TENSOR_FIELDS})
        privileged_raw = _serialize(
            {name: getattr(batch, name)
             for name in PRIVILEGED_TENSOR_FIELDS})
        actor_name = f"batch-{index:05d}.actor.pt"
        privileged_name = f"batch-{index:05d}.labels.pt"
        (directory / actor_name).write_bytes(actor_raw)
        (directory / privileged_name).write_bytes(privileged_raw)
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
    if not rows:
        raise BeliefV2TensorCacheError("V2 tensor cache is empty")
    manifest = {
        "schema": TENSOR_CACHE_SCHEMA,
        "cache_id": cache_id,
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
    (directory / MANIFEST_FILENAME).write_bytes(raw_manifest)
    return {"manifest_sha256": _sha256(raw_manifest),
            "batch_count": len(rows)}


def _load_manifest(directory: Path,
                   expected_manifest_sha256: str) -> dict[str, Any]:
    raw = (directory / MANIFEST_FILENAME).read_bytes()
    if _sha256(raw) != expected_manifest_sha256:
        raise BeliefV2TensorCacheError("V2 tensor cache manifest drift")
    manifest = json.loads(raw)
    if manifest.get("schema") != TENSOR_CACHE_SCHEMA \
            or manifest.get("test_split_cached") is not False \
            or any(manifest.get(key) is not False for key in (
                "runtime_artifact", "training_authorized",
                "test_open_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache manifest schema/authority drift")
    _require_cacheable_split(manifest["split"])
    if manifest["batch_count"] != len(manifest["batches"]) \
            or [row["index"] for row in manifest["batches"]] \
            != list(range(manifest["batch_count"])):
        raise BeliefV2TensorCacheError(
            "V2 tensor cache manifest population drift")
    expected_files = {MANIFEST_FILENAME}
    for row in manifest["batches"]:
        expected_files.add(row["actor_file"])
        expected_files.add(row["privileged_file"])
    actual_files = {path.name for path in directory.iterdir()}
    if actual_files != expected_files:
        raise BeliefV2TensorCacheError(
            "V2 tensor cache file population drift")
    return manifest


def cached_batch_factory(
        directory: Path, *,
        expected_manifest_sha256: str) -> Callable[[], Iterator[Any]]:
    """Return a trainer-compatible factory that replays the verified cache.

    Composes with ``pipelined_batches``: wrap the returned factory to overlap
    cache deserialization with the member step.
    """
    if not isinstance(directory, Path) \
            or type(expected_manifest_sha256) is not str \
            or len(expected_manifest_sha256) != 64:
        raise BeliefV2TensorCacheError("V2 tensor cache load inputs drift")

    def factory() -> Iterator[BeliefTrainingBatchV1]:
        manifest = _load_manifest(directory, expected_manifest_sha256)
        for row in manifest["batches"]:
            actor_raw = (directory / row["actor_file"]).read_bytes()
            privileged_raw = (
                directory / row["privileged_file"]).read_bytes()
            if _sha256(actor_raw) != row["actor_sha256"] \
                    or _sha256(privileged_raw) != row["privileged_sha256"]:
                raise BeliefV2TensorCacheError(
                    f"V2 tensor cache batch {row['index']} byte drift")
            actor = _deserialize(actor_raw)
            privileged = _deserialize(privileged_raw)
            if set(actor) != set(ACTOR_TENSOR_FIELDS) \
                    or set(privileged) != set(PRIVILEGED_TENSOR_FIELDS):
                raise BeliefV2TensorCacheError(
                    f"V2 tensor cache batch {row['index']} field drift")
            yield BeliefTrainingBatchV1(
                decision_keys=tuple(row["decision_keys"]),
                **row["static"], **actor, **privileged)

    return factory
