"""Resumable, all-core continuation-label stages for Value-Afterstate V2.

Population collection deliberately seals score-free states.  This controller
is the separate label boundary: it runs the frozen continuation mechanic, then
publishes one immutable shard per independent deal and one exact aggregate
manifest.  A restart reopens verified shards and computes only missing deals.

The caller decides which already-frozen split is admitted.  In production the
fit/select adapter calls this before training, while the audit adapter calls it
only after the durable audit-attempt marker exists.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from pathlib import Path
import time
from typing import Any, Callable, Sequence

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_artifacts import (
    CONTINUATION_DIRNAME,
    ContinuationShardV2,
    continuation_manifest_path,
    continuation_shard_path,
    publish_continuation_manifest,
    publish_continuation_shard,
    reopen_continuation_manifest,
    reopen_continuation_shard,
)
from .world_afterstate_v2_execution import verified_process_pool_kwargs
from .world_afterstate_v2_population_artifacts import material_sha256
from .world_afterstate_v2_continuation import (
    ContinuationBundleV2,
    build_continuation_bundle_v2,
)
from .world_afterstate_v2_population import PopulationMaterialV2


SCHEMA = "world-afterstate-v2-label-controller-receipt-v1"
PROGRESS_SCHEMA = "world-afterstate-v2-label-controller-progress-v1"
AUTHORITY = {
    "population_collection_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "retry_authorized": False,
    "deployment_authorized": False,
}
# Continuation workers are selected from the preregistered capacity grid;
# host CPU count is telemetry, not permission to invent a new width.
CONTINUATION_WORKER_ARMS = (1, 2, 4, 8, 12, 16, 32)


class WorldAfterstateV2LabelControllerError(ValueError):
    """A label-stage population, shard, deadline, or receipt drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2LabelControllerError(f"{label} drift")
    return value


def _build_one(material: PopulationMaterialV2) -> ContinuationBundleV2:
    """Pickle-safe process worker over one already-validated deal."""
    return build_continuation_bundle_v2(material)


def _material_population(
        materials: Sequence[PopulationMaterialV2], *, split: str) \
        -> tuple[PopulationMaterialV2, ...]:
    if split not in ("fit-select", "audit") \
            or type(materials) not in (tuple, list) or not materials:
        raise WorldAfterstateV2LabelControllerError(
            "label material population drift")
    values = tuple(materials)
    expected_splits = {"fit", "select"} if split == "fit-select" else {"audit"}
    for material in values:
        if type(material) is not PopulationMaterialV2:
            raise WorldAfterstateV2LabelControllerError(
                "label material type drift")
        try:
            material.validate()
        except Exception as exc:
            raise WorldAfterstateV2LabelControllerError(
                "label material validation refused") from exc
        if material.state.split not in expected_splits:
            raise WorldAfterstateV2LabelControllerError(
                "label split population drift")
    deals = tuple(material.deal_sha256 for material in values)
    slots = tuple(material.state.slot_sha256 for material in values)
    if len(set(deals)) != len(deals) or len(set(slots)) != len(slots):
        raise WorldAfterstateV2LabelControllerError(
            "label deal/slot population drift")
    return values


def _reopened_shard(root: Path, material: PopulationMaterialV2) \
        -> ContinuationShardV2:
    try:
        bundle = reopen_continuation_shard(root, material)
        path = continuation_shard_path(root, material.deal_sha256)
        raw = stable_read_bytes(path)
        digest = _sha_bytes(raw)
        if raw != bundle.canonical_bytes or digest != bundle.bundle_sha256:
            raise WorldAfterstateV2LabelControllerError(
                "reopened continuation shard binding drift")
    except WorldAfterstateV2LabelControllerError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2LabelControllerError(
            "reopened continuation shard refused") from exc
    return ContinuationShardV2(
        relative_path=path.relative_to(root).as_posix(),
        deal_sha256=bundle.deal_sha256,
        slot_sha256=bundle.slot_sha256,
        state_sha256=bundle.state_sha256,
        candidate_set_sha256=bundle.candidate_set_sha256,
        byte_count=len(raw), sha256=digest,
        bundle_sha256=bundle.bundle_sha256, bundle=bundle)


def _reuse_source(
        root: Path, values: tuple[PopulationMaterialV2, ...],
        reuse_root: Path | None,
        reuse_materials: Sequence[PopulationMaterialV2] | None
        ) -> dict[str, ContinuationBundleV2]:
    """Preflight a complete immutable source population for target reuse."""
    if reuse_root is None and reuse_materials is None:
        return {}
    if (not isinstance(reuse_root, Path)
            or reuse_root.is_symlink() or not reuse_root.is_dir()
            or reuse_materials is None
            or type(reuse_materials) not in (tuple, list)
            or not reuse_materials):
        raise WorldAfterstateV2LabelControllerError(
            "label reuse source binding drift")
    try:
        if reuse_root.resolve(strict=True) == root.resolve(strict=True):
            raise WorldAfterstateV2LabelControllerError(
                "label reuse source/target path collision")
    except OSError as exc:
        raise WorldAfterstateV2LabelControllerError(
            "label reuse source binding drift") from exc
    source_values = tuple(reuse_materials)
    _material_population(source_values, split="fit-select")
    by_deal = {material.deal_sha256: material for material in values}
    if (len(source_values) != len(set(material.deal_sha256
                                      for material in source_values))
            or any(material.deal_sha256 not in by_deal
                   for material in source_values)):
        raise WorldAfterstateV2LabelControllerError(
            "label reuse material population drift")
    # A continuation bundle does not contain every private material field.
    # Bind source and target to the exact sealed material bytes as well as to
    # the typed continuation identities before copying anything.
    try:
        for source in source_values:
            if material_sha256(source) != material_sha256(
                    by_deal[source.deal_sha256]):
                raise WorldAfterstateV2LabelControllerError(
                    "label reuse source/material binding drift")
        bundles = reopen_continuation_manifest(reuse_root, source_values)
    except WorldAfterstateV2LabelControllerError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2LabelControllerError(
            "label reuse source manifest refused") from exc
    if len(bundles) != len(source_values):
        raise WorldAfterstateV2LabelControllerError(
            "label reuse source manifest population drift")
    bundle_map = {bundle.deal_sha256: bundle for bundle in bundles}
    if set(bundle_map) != {material.deal_sha256 for material in source_values}:
        raise WorldAfterstateV2LabelControllerError(
            "label reuse source manifest identity drift")
    return bundle_map


@dataclass(frozen=True)
class LabelStageReceiptV2:
    split: str
    population_sha256: str
    manifest_sha256: str
    material_count: int
    continuation_outcome_count: int
    worker_count: int
    reused_shard_count: int
    built_shard_count: int
    elapsed_nanoseconds: int
    artifact_bytes: int
    schema: str = SCHEMA

    def payload(self) -> dict[str, Any]:
        if self.schema != SCHEMA or self.split not in ("fit-select", "audit"):
            raise WorldAfterstateV2LabelControllerError(
                "label receipt identity drift")
        _digest(self.population_sha256, "label population SHA-256")
        _digest(self.manifest_sha256, "label manifest SHA-256")
        integers = (
            self.material_count, self.continuation_outcome_count,
            self.worker_count, self.reused_shard_count,
            self.built_shard_count, self.elapsed_nanoseconds,
            self.artifact_bytes)
        if (any(isinstance(value, bool) or not isinstance(value, int)
                or value < 0 for value in integers)
                or self.material_count < 1 or self.worker_count < 1
                or self.continuation_outcome_count < self.material_count * 16
                or self.reused_shard_count + self.built_shard_count
                != self.material_count or self.artifact_bytes < 1):
            raise WorldAfterstateV2LabelControllerError(
                "label receipt count drift")
        body = {
            "schema": self.schema, "split": self.split,
            "population_sha256": self.population_sha256,
            "manifest_sha256": self.manifest_sha256,
            "material_count": self.material_count,
            "continuation_outcome_count": self.continuation_outcome_count,
            "worker_count": self.worker_count,
            "reused_shard_count": self.reused_shard_count,
            "built_shard_count": self.built_shard_count,
            "elapsed_nanoseconds": self.elapsed_nanoseconds,
            "artifact_bytes": self.artifact_bytes,
            "authority": dict(AUTHORITY),
        }
        return {**body, "receipt_sha256": _sha(body)}


def reopen_label_stage_receipt(value: object) -> LabelStageReceiptV2:
    required = {
        "schema", "split", "population_sha256", "manifest_sha256",
        "material_count", "continuation_outcome_count", "worker_count",
        "reused_shard_count", "built_shard_count", "elapsed_nanoseconds",
        "artifact_bytes", "authority", "receipt_sha256",
    }
    if (type(value) is not dict or set(value) != required
            or value.get("authority") != AUTHORITY):
        raise WorldAfterstateV2LabelControllerError(
            "label receipt schema drift")
    body = {key: item for key, item in value.items()
            if key != "receipt_sha256"}
    if value["receipt_sha256"] != _sha(body):
        raise WorldAfterstateV2LabelControllerError(
            "label receipt reconstruction drift")
    receipt = LabelStageReceiptV2(**{
        key: value[key] for key in LabelStageReceiptV2.__dataclass_fields__})
    if receipt.payload() != value:
        raise WorldAfterstateV2LabelControllerError(
            "label receipt canonical drift")
    return receipt


def _existing_manifest_receipt(
        root: Path, materials: tuple[PopulationMaterialV2, ...], *,
        split: str, workers: int) -> LabelStageReceiptV2:
    bundles = reopen_continuation_manifest(root, materials)
    raw = stable_read_bytes(continuation_manifest_path(root))
    value = __import__("json").loads(raw.decode("ascii"))
    outcomes = sum(len(bundle.candidates) for bundle in bundles)
    artifacts = len(raw) + sum(
        continuation_shard_path(root, material.deal_sha256).stat().st_size
        for material in materials)
    return LabelStageReceiptV2(
        split=split,
        population_sha256=_sha([
            (material.deal_sha256, material.state.slot_sha256)
            for material in materials]),
        manifest_sha256=_digest(value.get("manifest_sha256"),
                                "label manifest SHA-256"),
        material_count=len(materials),
        continuation_outcome_count=outcomes, worker_count=workers,
        reused_shard_count=len(materials), built_shard_count=0,
        elapsed_nanoseconds=0, artifact_bytes=artifacts)


def build_continuation_population_v2(
        root: Path, materials: Sequence[PopulationMaterialV2], *,
        split: str, workers: int, deadline_monotonic_ns: int,
        progress: Callable[[dict[str, Any]], None] | None = None,
        reuse_root: Path | None = None,
        reuse_materials: Sequence[PopulationMaterialV2] | None = None) \
        -> LabelStageReceiptV2:
    """Build/reopen one complete fit-select or audit continuation population."""
    values = _material_population(materials, split=split)
    if (not isinstance(root, Path) or root.is_symlink()
            or isinstance(workers, bool) or not isinstance(workers, int)
            or workers not in CONTINUATION_WORKER_ARMS
            or isinstance(deadline_monotonic_ns, bool)
            or not isinstance(deadline_monotonic_ns, int)
            or deadline_monotonic_ns < 1):
        raise WorldAfterstateV2LabelControllerError(
            "label resource request drift")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise WorldAfterstateV2LabelControllerError("label root drift")
    manifest = continuation_manifest_path(root)
    if manifest.exists() or manifest.is_symlink():
        return _existing_manifest_receipt(
            root, values, split=split, workers=workers)

    source_bundles = _reuse_source(
        root, values, reuse_root, reuse_materials)

    started = time.monotonic_ns()
    shards: dict[str, ContinuationShardV2] = {}
    missing: list[PopulationMaterialV2] = []
    target_directory = root / CONTINUATION_DIRNAME
    if target_directory.is_symlink() or (
            target_directory.exists() and not target_directory.is_dir()):
        raise WorldAfterstateV2LabelControllerError(
            "label target continuation directory drift")
    if target_directory.exists():
        expected_names = {
            f"deal-{material.deal_sha256}.bin" for material in values}
        try:
            entries = tuple(target_directory.iterdir())
        except OSError as exc:
            raise WorldAfterstateV2LabelControllerError(
                "label target continuation directory unreadable") from exc
        if any(entry.name not in expected_names for entry in entries):
            raise WorldAfterstateV2LabelControllerError(
                "label target continuation file population drift")
    # Preflight every existing target shard before publishing either a copied
    # source shard or a newly computed one.  This makes a tampered later shard
    # fail without leaving a newly published prefix behind.
    for material in values:
        path = continuation_shard_path(root, material.deal_sha256)
        if path.is_symlink():
            raise WorldAfterstateV2LabelControllerError(
                "label target shard symlink refused")
        if path.exists():
            shards[material.deal_sha256] = _reopened_shard(root, material)
    missing = [material for material in values
               if material.deal_sha256 not in shards]
    reused = len(shards)

    def emit() -> None:
        if progress is None:
            return
        completed = len(shards)
        elapsed = max(0, time.monotonic_ns() - started)
        remaining = len(values) - completed
        eta = (elapsed * remaining + completed - 1) // completed \
            if completed else 0
        progress({
            "schema": PROGRESS_SCHEMA, "split": split,
            "completed_deals": completed, "total_deals": len(values),
            "percent_basis_points": completed * 10_000 // len(values),
            "active_workers": min(workers, remaining),
            "elapsed_nanoseconds": elapsed,
            "estimated_remaining_nanoseconds": eta,
            "deadline_headroom_nanoseconds": max(
                0, deadline_monotonic_ns - time.monotonic_ns()),
            "immutable_shards": completed,
            "authority": dict(AUTHORITY),
        })

    def accept(material: PopulationMaterialV2,
               bundle: ContinuationBundleV2, *, copied: bool = False) -> None:
        if time.monotonic_ns() >= deadline_monotonic_ns:
            raise WorldAfterstateV2LabelControllerError(
                "label deadline before shard publication")
        shard = publish_continuation_shard(root, material, bundle)
        shards[material.deal_sha256] = shard
        nonlocal reused
        if copied:
            reused += 1
        emit()

    # Copy the sealed P0 prefix first.  These are immutable publications, not
    # engine calls, and remain resumable if the process dies mid-prefix.
    source_missing = [material for material in missing
                      if material.deal_sha256 in source_bundles]
    for material in source_missing:
        if time.monotonic_ns() >= deadline_monotonic_ns:
            raise WorldAfterstateV2LabelControllerError(
                "label deadline before shard publication")
        accept(material, source_bundles[material.deal_sha256], copied=True)

    built_missing = [material for material in missing
                     if material.deal_sha256 not in source_bundles]
    if workers == 1:
        for material in built_missing:
            if time.monotonic_ns() >= deadline_monotonic_ns:
                raise WorldAfterstateV2LabelControllerError(
                    "label deadline before continuation")
            accept(material, _build_one(material))
    elif built_missing:
        pool = ProcessPoolExecutor(
            max_workers=workers, **verified_process_pool_kwargs())
        try:
            futures = {pool.submit(_build_one, material): material
                       for material in built_missing}
            for future in as_completed(futures):
                accept(futures[future], future.result())
        except Exception:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

    if len(shards) != len(values):
        raise WorldAfterstateV2LabelControllerError(
            "label shard population incomplete")
    ordered = tuple(shards[material.deal_sha256] for material in values)
    manifest_value = publish_continuation_manifest(root, ordered)
    reopened = reopen_continuation_manifest(root, values)
    if len(reopened) != len(values):
        raise WorldAfterstateV2LabelControllerError(
            "label aggregate reopen incomplete")
    raw = stable_read_bytes(continuation_manifest_path(root))
    artifacts = len(raw) + sum(shard.byte_count for shard in ordered)
    receipt = LabelStageReceiptV2(
        split=split,
        population_sha256=_sha([
            (material.deal_sha256, material.state.slot_sha256)
            for material in values]),
        manifest_sha256=_digest(manifest_value.get("manifest_sha256"),
                                "label manifest SHA-256"),
        material_count=len(values),
        continuation_outcome_count=sum(
            len(bundle.candidates) for bundle in reopened),
        worker_count=workers, reused_shard_count=reused,
        built_shard_count=len(values) - reused,
        elapsed_nanoseconds=max(0, time.monotonic_ns() - started),
        artifact_bytes=artifacts)
    receipt.payload()
    return receipt


__all__ = [
    "AUTHORITY", "LabelStageReceiptV2", "PROGRESS_SCHEMA", "SCHEMA",
    "WorldAfterstateV2LabelControllerError",
    "build_continuation_population_v2", "reopen_label_stage_receipt",
]
