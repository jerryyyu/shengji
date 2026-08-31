"""Immutable filesystem artifacts for the Value-Afterstate V2 contracts.

This module is intentionally a small adapter around the typed V2 reopeners and
the strict artifact file primitives.  It owns no execution authority: a
published file is only an independently verifiable, content-addressed shard.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_checkpoint import (
    CONTROL_NAMES,
    MEMBERS_PER_BLOCK,
    reopen_checkpoint,
)
from .world_afterstate_v2_continuation import (
    ContinuationBundleV2,
    reopen_continuation_bundle_v2,
)
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_execution import verified_process_pool_kwargs


CONTINUATION_SCHEMA = "world-afterstate-v2-continuation-artifact-v1"
CHECKPOINT_SCHEMA = "world-afterstate-v2-checkpoint-artifact-v1"
CONTINUATION_MANIFEST_SCHEMA = "world-afterstate-v2-continuation-manifest-v1"
# Widths are a frozen reconstruction dimension, not an arbitrary host CPU
# count.  The preregistered 32-worker arm must round-trip at this boundary.
RECONSTRUCTION_WORKER_ARMS = (1, 4, 8, 16, 32)
CHECKPOINT_MANIFEST_SCHEMA = "world-afterstate-v2-checkpoint-manifest-v1"
CONTINUATION_DIRNAME = "continuations"
CHECKPOINT_DIRNAME = "checkpoints"
MANIFEST_NAME = "manifest.json"
AUTHORITY = {
    "data_collection_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "writer_authorized": False,
    "cli_authorized": False,
    "retry_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2ArtifactError(ValueError):
    """A V2 artifact path, shard, manifest, or population was refused."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise WorldAfterstateV2ArtifactError(f"{label} drift")
    return value


def _strict_nonnegative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorldAfterstateV2ArtifactError(f"{label} drift")
    return value


def _root(root: Path) -> Path:
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise WorldAfterstateV2ArtifactError("artifact root drift")
    return root


def _directory(path: Path, *, create: bool = False) -> Path:
    if path.is_symlink():
        raise WorldAfterstateV2ArtifactError("artifact directory is a symlink")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise WorldAfterstateV2ArtifactError(
                "artifact directory creation refused") from exc
    if path.is_symlink() or not path.is_dir():
        raise WorldAfterstateV2ArtifactError("artifact directory drift")
    return path


def _parent_directory(root: Path, path: Path, *, create: bool = False) -> Path:
    """Create/check each parent component without following a symlink."""
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise WorldAfterstateV2ArtifactError(
            "artifact parent escapes root") from exc
    cursor = root
    for part in parts:
        cursor = cursor / part
        _directory(cursor, create=create)
    return cursor


def _read(path: Path) -> bytes:
    try:
        return stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "immutable artifact stable read refused") from exc


def _hex(value: object, label: str) -> str:
    value = _digest(value, label)
    return value


def _continuation_path(root: Path, deal_sha256: str) -> Path:
    _root(root)
    _hex(deal_sha256, "deal SHA-256")
    return root / CONTINUATION_DIRNAME / f"deal-{deal_sha256}.bin"


def continuation_shard_path(root: Path, deal_sha256: str) -> Path:
    """Return the canonical absolute path for one deal shard."""
    return _continuation_path(root, deal_sha256)


def continuation_manifest_path(root: Path) -> Path:
    _root(root)
    return root / CONTINUATION_DIRNAME / MANIFEST_NAME


def _cohort(cohort: object) -> str:
    if type(cohort) is not str or cohort not in CONTROL_NAMES:
        raise WorldAfterstateV2ArtifactError("checkpoint cohort drift")
    return cohort


def _index(value: object, label: str, minimum: int = 0) -> int:
    value = _strict_nonnegative(value, label)
    if value < minimum:
        raise WorldAfterstateV2ArtifactError(f"{label} drift")
    return value


def checkpoint_shard_path(
        root: Path, cohort: str, seed_block: int | None = None,
        member_index: int | None = None, epoch: int | None = None, *,
        block: int | None = None, member: int | None = None,
        common_epoch: int | None = None) -> Path:
    """Return the canonical absolute path for one common-epoch member."""
    _root(root)
    cohort = _cohort(cohort)
    if seed_block is None:
        seed_block = block
    if member_index is None:
        member_index = member
    if epoch is None:
        epoch = common_epoch
    if seed_block is None or member_index is None or epoch is None:
        raise WorldAfterstateV2ArtifactError("checkpoint path metadata incomplete")
    seed_block = _index(seed_block, "checkpoint seed block")
    member_index = _index(member_index, "checkpoint member index")
    epoch = _index(epoch, "checkpoint epoch", minimum=1)
    return (root / CHECKPOINT_DIRNAME / cohort / f"block-{seed_block}"
            / f"epoch-{epoch}" / f"member-{member_index}.bin")


def checkpoint_manifest_path(
        root: Path, cohort: str, seed_block: int | None = None,
        epoch: int | None = None, *, block: int | None = None,
        common_epoch: int | None = None) -> Path:
    _root(root)
    cohort = _cohort(cohort)
    if seed_block is None:
        seed_block = block
    if epoch is None:
        epoch = common_epoch
    if seed_block is None or epoch is None:
        raise WorldAfterstateV2ArtifactError("checkpoint path metadata incomplete")
    seed_block = _index(seed_block, "checkpoint seed block")
    epoch = _index(epoch, "checkpoint epoch", minimum=1)
    return (root / CHECKPOINT_DIRNAME / cohort / f"block-{seed_block}"
            / f"epoch-{epoch}" / MANIFEST_NAME)


# Short aliases are useful at call sites that treat paths as the primary
# adapter surface.
continuation_path = continuation_shard_path
checkpoint_path = checkpoint_shard_path


def _relative(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise WorldAfterstateV2ArtifactError(
            "manifest path escapes artifact root") from exc
    text = relative.as_posix()
    if (not text or text.startswith("/") or "\\" in text
            or any(part in ("", ".", "..") for part in relative.parts)):
        raise WorldAfterstateV2ArtifactError("manifest relative path drift")
    return text


def _manifest_relative(value: object) -> str:
    if type(value) is not str or not value or value.startswith("/") \
            or "\\" in value:
        raise WorldAfterstateV2ArtifactError("manifest relative path drift")
    path = Path(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts) \
            or path.as_posix() != value:
        raise WorldAfterstateV2ArtifactError("manifest relative path drift")
    return value


def _safe_file(root: Path, relative: str) -> Path:
    relative = _manifest_relative(relative)
    path = root / Path(relative)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorldAfterstateV2ArtifactError(
            "manifest path escapes artifact root") from exc
    cursor = root
    for part in path.relative_to(root).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink() or not cursor.is_dir():
            raise WorldAfterstateV2ArtifactError(
                "manifest parent directory drift")
    return path


@dataclass(frozen=True)
class ContinuationShardV2:
    """A typed, immutable record for one published deal continuation."""

    relative_path: str
    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    byte_count: int
    sha256: str
    bundle_sha256: str
    bundle: ContinuationBundleV2
    schema: str = CONTINUATION_SCHEMA

    @property
    def path(self) -> str:
        return self.relative_path

    def row(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "relative_path": self.relative_path,
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "bundle_sha256": self.bundle_sha256,
        }


@dataclass(frozen=True)
class CheckpointShardV2:
    """A typed, immutable record for one common-epoch checkpoint."""

    relative_path: str
    cohort: str
    seed_block: int
    member_index: int
    epoch: int
    byte_count: int
    sha256: str
    checkpoint_sha256: str
    model_state_sha256: str
    freeze_sha256: str
    config_sha256: str
    population_sha256: str
    schedule_sha256: str
    common_epoch_sha256: str
    schema: str = CHECKPOINT_SCHEMA

    @property
    def path(self) -> str:
        return self.relative_path

    def row(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "relative_path": self.relative_path,
            "cohort": self.cohort,
            "seed_block": self.seed_block,
            "member_index": self.member_index,
            "epoch": self.epoch,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
            "checkpoint_sha256": self.checkpoint_sha256,
            "model_state_sha256": self.model_state_sha256,
            "freeze_sha256": self.freeze_sha256,
            "config_sha256": self.config_sha256,
            "population_sha256": self.population_sha256,
            "schedule_sha256": self.schedule_sha256,
            "common_epoch_sha256": self.common_epoch_sha256,
        }


def _validate_continuation(
        material: PopulationMaterialV2,
        bundle: ContinuationBundleV2) -> ContinuationBundleV2:
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2ArtifactError("continuation source type drift")
    try:
        if isinstance(bundle, ContinuationBundleV2):
            return reopen_continuation_bundle_v2(bundle, material)
        if type(bundle) is bytes:
            return reopen_continuation_bundle_v2(bundle, material)
        raise WorldAfterstateV2ArtifactError("continuation bundle type drift")
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "continuation/material typed reopen refused") from exc


def _validate_continuation_process(
        item: tuple[PopulationMaterialV2, bytes]) -> ContinuationBundleV2:
    """Process-pool spelling for one independently validated shard."""
    material, raw = item
    return _validate_continuation(material, raw)


def publish_continuation_shard(
        root: Path, material: PopulationMaterialV2,
        bundle: ContinuationBundleV2) -> ContinuationShardV2:
    """Validate and publish one deal continuation exactly once."""
    reopened = _validate_continuation(material, bundle)
    target = _continuation_path(root, material.deal_sha256)
    _parent_directory(root, target.parent, create=True)
    raw = reopened.canonical_bytes
    try:
        digest = publish_exclusive_bytes(target, raw)
        reread = _read(target)
        exact = _validate_continuation(material, reopened.__class__(
            deal_sha256=reopened.deal_sha256,
            slot_sha256=reopened.slot_sha256,
            state_sha256=reopened.state_sha256,
            candidate_set_sha256=reopened.candidate_set_sha256,
            candidates=reopened.candidates,
            labels=reopened.labels,
            canonical_bytes=reread,
            bundle_sha256=_sha(reread),
            schema=reopened.schema,
            authority=reopened.authority))
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "continuation shard publication/reopen refused") from exc
    if reread != raw or digest != _sha(raw) or exact.bundle_sha256 != digest:
        raise WorldAfterstateV2ArtifactError("continuation shard byte drift")
    relative = _relative(root, target)
    return ContinuationShardV2(
        relative_path=relative, deal_sha256=exact.deal_sha256,
        slot_sha256=exact.slot_sha256, state_sha256=exact.state_sha256,
        candidate_set_sha256=exact.candidate_set_sha256,
        byte_count=len(raw), sha256=digest, bundle_sha256=exact.bundle_sha256,
        bundle=exact)


def reopen_continuation_shard(
        root: Path, material: PopulationMaterialV2) -> ContinuationBundleV2:
    """Read and typed-reopen one deal shard against its exact material."""
    target = _continuation_path(root, material.deal_sha256)
    try:
        raw = _read(target)
        return _validate_continuation(material, raw)
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "continuation shard reopen refused") from exc


def _manifest_bytes(schema: str, rows: Sequence[dict[str, Any]]) -> bytes:
    body = {"schema": schema, "authority": dict(AUTHORITY), "rows": list(rows)}
    return canonical_json_bytes({
        **body, "manifest_sha256": _sha(canonical_json_bytes(body))})


def _parse_manifest(raw: bytes, schema: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2ArtifactError("manifest JSON drift") from exc
    keys = {"schema", "authority", "rows", "manifest_sha256"}
    if type(value) is not dict or set(value) != keys \
            or value["schema"] != schema or value["authority"] != AUTHORITY \
            or type(value["rows"]) is not list \
            or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2ArtifactError("manifest schema drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(canonical_json_bytes(body)):
        raise WorldAfterstateV2ArtifactError("manifest hash drift")
    _digest(value["manifest_sha256"], "manifest SHA-256")
    return value["rows"], value


def _publish_manifest(root: Path, path: Path, schema: str,
                      rows: Sequence[dict[str, Any]]) -> bytes:
    _root(root)
    _parent_directory(root, path.parent, create=True)
    if not rows or len({row["relative_path"] for row in rows}) != len(rows):
        raise WorldAfterstateV2ArtifactError("manifest row population drift")
    raw = _manifest_bytes(schema, rows)
    try:
        publish_exclusive_bytes(path, raw)
    except ValueError as exc:
        raise WorldAfterstateV2ArtifactError(
            "manifest publication refused") from exc
    return raw


def publish_continuation_manifest(
        root: Path, shards: Sequence[ContinuationShardV2],
        bundles: Sequence[ContinuationBundleV2] | None = None) -> dict[str, Any]:
    """Publish the exact aggregate manifest for already sealed deal shards."""
    if bundles is not None:
        if type(shards) not in (tuple, list) or type(bundles) not in (tuple, list) \
                or len(shards) != len(bundles):
            raise WorldAfterstateV2ArtifactError(
                "continuation manifest source population drift")
        # This convenience form still requires the shard files to have been
        # published by the caller; the material binding remains mandatory.
        rebuilt = []
        for material, bundle in zip(shards, bundles, strict=True):
            if type(material) is not PopulationMaterialV2 \
                    or type(bundle) is not ContinuationBundleV2:
                raise WorldAfterstateV2ArtifactError(
                    "continuation manifest source type drift")
            rebuilt.append(publish_continuation_shard(root, material, bundle))
        shards = tuple(rebuilt)
    if type(shards) not in (tuple, list) or not shards:
        raise WorldAfterstateV2ArtifactError("continuation manifest population drift")
    rows = []
    for shard in shards:
        if type(shard) is not ContinuationShardV2 \
                or shard.schema != CONTINUATION_SCHEMA:
            raise WorldAfterstateV2ArtifactError("continuation manifest row drift")
        for label, value in (
                ("continuation deal SHA-256", shard.deal_sha256),
                ("continuation slot SHA-256", shard.slot_sha256),
                ("continuation state SHA-256", shard.state_sha256),
                ("continuation candidate-set SHA-256",
                 shard.candidate_set_sha256),
                ("continuation shard SHA-256", shard.sha256),
                ("continuation bundle SHA-256", shard.bundle_sha256)):
            _digest(value, label)
        _strict_nonnegative(shard.byte_count, "continuation byte count")
        if (shard.deal_sha256, shard.slot_sha256, shard.state_sha256,
                shard.candidate_set_sha256, shard.bundle_sha256) != (
                    shard.bundle.deal_sha256, shard.bundle.slot_sha256,
                    shard.bundle.state_sha256,
                    shard.bundle.candidate_set_sha256,
                    shard.bundle.bundle_sha256):
            raise WorldAfterstateV2ArtifactError(
                "continuation shard semantic drift")
        path = _safe_file(root, shard.relative_path)
        if path != _continuation_path(root, shard.deal_sha256):
            raise WorldAfterstateV2ArtifactError("continuation manifest path drift")
        raw = _read(path)
        if (shard.byte_count != len(shard.bundle.canonical_bytes)
                or shard.sha256 != _sha(shard.bundle.canonical_bytes)
                or shard.bundle_sha256 != shard.bundle.bundle_sha256
                or raw != shard.bundle.canonical_bytes):
            raise WorldAfterstateV2ArtifactError("continuation shard record drift")
        shard.bundle.validate()
        rows.append(shard.row())
    raw = _publish_manifest(
        root, continuation_manifest_path(root), CONTINUATION_MANIFEST_SCHEMA,
        rows)
    return json.loads(raw.decode("ascii"))


def _expected_continuation_files(root: Path, rows: Sequence[dict[str, Any]]) -> set[str]:
    expected = {MANIFEST_NAME}
    for row in rows:
        relative = _manifest_relative(row.get("relative_path"))
        path = _safe_file(root, relative)
        if path.parent != root / CONTINUATION_DIRNAME:
            raise WorldAfterstateV2ArtifactError("continuation path identity drift")
        expected.add(Path(relative).name)
    return expected


def reopen_continuation_manifest(
        root: Path, materials: Mapping[str, PopulationMaterialV2]
        | Sequence[PopulationMaterialV2], *, workers: int = 1) \
        -> tuple[ContinuationBundleV2, ...]:
    """Reopen every deal in an aggregate, refusing drops and extras."""
    root = _root(root)
    if isinstance(workers, bool) or not isinstance(workers, int) \
            or workers not in RECONSTRUCTION_WORKER_ARMS:
        raise WorldAfterstateV2ArtifactError(
            "continuation reopen worker population drift")
    directory = _directory(root / CONTINUATION_DIRNAME)
    try:
        rows, _ = _parse_manifest(
            _read(directory / MANIFEST_NAME),
            CONTINUATION_MANIFEST_SCHEMA)
    except ValueError as exc:
        raise WorldAfterstateV2ArtifactError(
            "continuation aggregate manifest refused") from exc
    if isinstance(materials, Mapping):
        material_map = dict(materials)
    elif type(materials) in (tuple, list):
        material_map = {item.deal_sha256: item for item in materials}
    else:
        raise WorldAfterstateV2ArtifactError("continuation material population drift")
    if len(material_map) != len(rows):
        raise WorldAfterstateV2ArtifactError("continuation deal drop/extra")
    if {path.name for path in directory.iterdir()} != _expected_continuation_files(root, rows):
        raise WorldAfterstateV2ArtifactError("continuation file population drift")
    result = []
    pending: list[tuple[PopulationMaterialV2, bytes]] = []
    pending_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {
        "schema", "relative_path", "deal_sha256", "slot_sha256",
        "state_sha256", "candidate_set_sha256", "byte_count", "sha256",
        "bundle_sha256",
    }
    for row in rows:
        if type(row) is not dict or set(row) != required \
                or row["schema"] != CONTINUATION_SCHEMA:
            raise WorldAfterstateV2ArtifactError("continuation manifest row drift")
        deal = _digest(row["deal_sha256"], "manifest deal SHA-256")
        if deal in seen or deal not in material_map:
            raise WorldAfterstateV2ArtifactError("continuation deal drop/duplicate")
        seen.add(deal)
        path = _safe_file(root, row["relative_path"])
        if row["relative_path"] != _relative(root, path) \
                or path.name != f"deal-{deal}.bin" \
                or path.parent != directory:
            raise WorldAfterstateV2ArtifactError("continuation manifest path drift")
        raw = _read(path)
        if row["byte_count"] != len(raw) or row["sha256"] != _sha(raw) \
                or row["bundle_sha256"] != _sha(raw):
            raise WorldAfterstateV2ArtifactError("continuation manifest byte drift")
        pending.append((material_map[deal], raw))
        pending_rows.append(row)
    try:
        if workers == 1:
            result = [_validate_continuation_process(item) for item in pending]
        else:
            with ProcessPoolExecutor(
                    max_workers=workers, **verified_process_pool_kwargs()) as pool:
                result = list(pool.map(_validate_continuation_process, pending))
    except Exception as exc:
        raise WorldAfterstateV2ArtifactError(
            "continuation shard process reopen refused") from exc
    for row, bundle in zip(pending_rows, result, strict=True):
        if (row["slot_sha256"], row["state_sha256"],
                row["candidate_set_sha256"]) != (
                    bundle.slot_sha256, bundle.state_sha256,
                    bundle.candidate_set_sha256):
            raise WorldAfterstateV2ArtifactError(
                "continuation manifest semantic drift")
    if seen != set(material_map):
        raise WorldAfterstateV2ArtifactError("continuation deal drop/extra")
    return tuple(result)


def publish_checkpoint_shard(
        root: Path, raw: bytes, cohort: str | None = None,
        seed_block: int | None = None, member_index: int | None = None,
        epoch: int | None = None, *, block: int | None = None,
        member: int | None = None, common_epoch: int | None = None) \
        -> CheckpointShardV2:
    """Validate metadata-bound checkpoint bytes and publish once."""
    if seed_block is None:
        seed_block = block
    elif block is not None and block != seed_block:
        raise WorldAfterstateV2ArtifactError("checkpoint block binding drift")
    if member_index is None:
        member_index = member
    elif member is not None and member != member_index:
        raise WorldAfterstateV2ArtifactError("checkpoint member binding drift")
    if epoch is None:
        epoch = common_epoch
    elif common_epoch is not None and common_epoch != epoch:
        raise WorldAfterstateV2ArtifactError("checkpoint epoch binding drift")
    if cohort is None or seed_block is None or member_index is None or epoch is None:
        raise WorldAfterstateV2ArtifactError("checkpoint metadata is incomplete")
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2ArtifactError("checkpoint bytes drift")
    cohort = _cohort(cohort)
    seed_block = _index(seed_block, "checkpoint seed block")
    member_index = _index(member_index, "checkpoint member index")
    epoch = _index(epoch, "checkpoint epoch", minimum=1)
    try:
        _model, metadata = reopen_checkpoint(raw)
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "checkpoint typed reopen refused") from exc
    if (metadata["control_name"], metadata["seed_block"],
            metadata["member_index"], metadata["selected_epoch"]) != (
                cohort, seed_block, member_index, epoch):
        raise WorldAfterstateV2ArtifactError("checkpoint metadata binding drift")
    target = checkpoint_shard_path(
        root, cohort, seed_block, member_index, epoch)
    _parent_directory(root, target.parent, create=True)
    try:
        digest = publish_exclusive_bytes(target, raw)
        reread = _read(target)
        _model, reopened = reopen_checkpoint(reread)
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "checkpoint shard publication/reopen refused") from exc
    if reread != raw or digest != _sha(raw) or reopened != metadata:
        raise WorldAfterstateV2ArtifactError("checkpoint shard byte/metadata drift")
    return CheckpointShardV2(
        relative_path=_relative(root, target), cohort=cohort,
        seed_block=seed_block, member_index=member_index, epoch=epoch,
        byte_count=len(raw), sha256=digest,
        checkpoint_sha256=metadata["checkpoint_sha256"],
        model_state_sha256=metadata["model_state_sha256"],
        freeze_sha256=metadata["freeze_sha256"],
        config_sha256=metadata["config_sha256"],
        population_sha256=metadata["population_sha256"],
        schedule_sha256=metadata["schedule_sha256"],
        common_epoch_sha256=metadata["common_epoch_sha256"])


def reopen_checkpoint_shard(
        root: Path, cohort: str | None = None, seed_block: int | None = None,
        member_index: int | None = None, epoch: int | None = None, *,
        block: int | None = None, member: int | None = None,
        common_epoch: int | None = None) -> tuple[Any, dict[str, Any]]:
    """Read one checkpoint shard and return the typed model plus metadata."""
    if seed_block is None:
        seed_block = block
    if member_index is None:
        member_index = member
    if epoch is None:
        epoch = common_epoch
    if cohort is None or seed_block is None or member_index is None or epoch is None:
        raise WorldAfterstateV2ArtifactError("checkpoint metadata is incomplete")
    target = checkpoint_shard_path(
        root, cohort, seed_block, member_index, epoch)
    try:
        raw = _read(target)
        model, metadata = reopen_checkpoint(raw)
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2ArtifactError(
            "checkpoint shard reopen refused") from exc
    if (metadata["control_name"], metadata["seed_block"],
            metadata["member_index"], metadata["selected_epoch"]) != (
                cohort, seed_block, member_index, epoch):
        raise WorldAfterstateV2ArtifactError("checkpoint metadata binding drift")
    return model, metadata


def publish_checkpoint_manifest(
        root: Path, shards: Sequence[CheckpointShardV2]) -> dict[str, Any]:
    """Publish one exact aggregate for a cohort/common epoch."""
    if type(shards) not in (tuple, list) or not shards:
        raise WorldAfterstateV2ArtifactError("checkpoint manifest population drift")
    first = shards[0]
    if type(first) is not CheckpointShardV2:
        raise WorldAfterstateV2ArtifactError("checkpoint manifest row drift")
    if any(type(shard) is not CheckpointShardV2
           or (shard.cohort, shard.seed_block, shard.epoch) !=
           (first.cohort, first.seed_block, first.epoch) for shard in shards):
        raise WorldAfterstateV2ArtifactError("checkpoint cohort/epoch mixing")
    shared_identity = (first.freeze_sha256, first.config_sha256,
                       first.population_sha256,
                       first.common_epoch_sha256)
    if any((shard.freeze_sha256, shard.config_sha256,
            shard.population_sha256, shard.common_epoch_sha256)
           != shared_identity for shard in shards):
        raise WorldAfterstateV2ArtifactError(
            "checkpoint immutable identity mixing")
    member_population = tuple(shard.member_index for shard in shards)
    if member_population != tuple(range(MEMBERS_PER_BLOCK)):
        raise WorldAfterstateV2ArtifactError(
            "checkpoint member population/order drift")
    rows = []
    for shard in shards:
        if shard.schema != CHECKPOINT_SCHEMA:
            raise WorldAfterstateV2ArtifactError("checkpoint manifest row drift")
        for label, value in (
                ("checkpoint shard SHA-256", shard.sha256),
                ("checkpoint payload SHA-256", shard.checkpoint_sha256),
                ("checkpoint model-state SHA-256",
                 shard.model_state_sha256)):
            _digest(value, label)
        _strict_nonnegative(shard.byte_count, "checkpoint byte count")
        path = _safe_file(root, shard.relative_path)
        if path != checkpoint_shard_path(
                root, shard.cohort, shard.seed_block,
                shard.member_index, shard.epoch):
            raise WorldAfterstateV2ArtifactError("checkpoint manifest path drift")
        raw = _read(path)
        if shard.byte_count != len(raw) or shard.sha256 != _sha(raw):
            raise WorldAfterstateV2ArtifactError("checkpoint shard record drift")
        try:
            _model, metadata = reopen_checkpoint(raw)
        except (ValueError, TypeError) as exc:
            raise WorldAfterstateV2ArtifactError(
                "checkpoint manifest source reopen refused") from exc
        if (metadata["control_name"], metadata["seed_block"],
                metadata["member_index"], metadata["selected_epoch"],
                metadata["checkpoint_sha256"], metadata["model_state_sha256"],
                metadata["freeze_sha256"], metadata["config_sha256"],
                metadata["population_sha256"], metadata["schedule_sha256"],
                metadata["common_epoch_sha256"]) != (
                    shard.cohort, shard.seed_block, shard.member_index,
                    shard.epoch, shard.checkpoint_sha256,
                    shard.model_state_sha256, shard.freeze_sha256,
                    shard.config_sha256, shard.population_sha256,
                    shard.schedule_sha256, shard.common_epoch_sha256):
            raise WorldAfterstateV2ArtifactError("checkpoint shard record drift")
        rows.append(shard.row())
    raw = _publish_manifest(
        root, checkpoint_manifest_path(
            root, first.cohort, first.seed_block, first.epoch),
        CHECKPOINT_MANIFEST_SCHEMA, rows)
    return json.loads(raw.decode("ascii"))


def reopen_checkpoint_manifest(
        root: Path, *, cohort: str, seed_block: int,
        epoch: int, expected_freeze_sha256: str,
        expected_config_sha256: str, expected_population_sha256: str,
        expected_schedule_sha256s: Sequence[str],
        expected_common_epoch_sha256: str,
        members: Sequence[int] | None = None) \
        -> tuple[tuple[Any, dict[str, Any]], ...]:
    """Reopen every exact member named by a common-epoch manifest."""
    cohort = _cohort(cohort)
    seed_block = _index(seed_block, "checkpoint seed block")
    epoch = _index(epoch, "checkpoint epoch", minimum=1)
    expected_freeze_sha256 = _digest(
        expected_freeze_sha256, "expected checkpoint freeze SHA-256")
    expected_config_sha256 = _digest(
        expected_config_sha256, "expected checkpoint config SHA-256")
    expected_population_sha256 = _digest(
        expected_population_sha256,
        "expected checkpoint population SHA-256")
    expected_common_epoch_sha256 = _digest(
        expected_common_epoch_sha256,
        "expected checkpoint common-epoch SHA-256")
    if type(expected_schedule_sha256s) not in (tuple, list) \
            or len(expected_schedule_sha256s) != MEMBERS_PER_BLOCK:
        raise WorldAfterstateV2ArtifactError(
            "expected checkpoint schedule population drift")
    expected_schedules = tuple(_digest(
        value, "expected checkpoint schedule SHA-256")
        for value in expected_schedule_sha256s)
    manifest = checkpoint_manifest_path(root, cohort, seed_block, epoch)
    directory = _parent_directory(root, manifest.parent)
    try:
        rows, _ = _parse_manifest(
            _read(manifest), CHECKPOINT_MANIFEST_SCHEMA)
    except ValueError as exc:
        raise WorldAfterstateV2ArtifactError(
            "checkpoint aggregate manifest refused") from exc
    # Every scientific cohort is exactly four members.  This is not a caller
    # option: permitting a named subset lets a coordinated manifest rehash
    # turn a dropped cohort member into a valid aggregate.
    if members is not None:
        raise WorldAfterstateV2ArtifactError(
            "checkpoint member population is not caller-selectable")
    expected_members = tuple(range(MEMBERS_PER_BLOCK))
    required = {
        "schema", "relative_path", "cohort", "seed_block", "member_index",
        "epoch", "byte_count", "sha256", "checkpoint_sha256",
        "model_state_sha256", "freeze_sha256", "config_sha256",
        "population_sha256", "schedule_sha256", "common_epoch_sha256",
    }
    if len(rows) != len(expected_members):
        raise WorldAfterstateV2ArtifactError("checkpoint member drop/extra")
    expected_names = {MANIFEST_NAME}
    result = []
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != required \
                or row["schema"] != CHECKPOINT_SCHEMA \
                or (row["cohort"], row["seed_block"], row["epoch"]) != (
                    cohort, seed_block, epoch) \
                or row["member_index"] not in expected_members \
                or row["member_index"] in seen:
            raise WorldAfterstateV2ArtifactError("checkpoint manifest row drift")
        member = row["member_index"]
        seen.add(member)
        path = _safe_file(root, row["relative_path"])
        if path != checkpoint_shard_path(
                root, cohort, seed_block, member, epoch):
            raise WorldAfterstateV2ArtifactError("checkpoint manifest path drift")
        expected_names.add(path.name)
        raw = _read(path)
        if row["byte_count"] != len(raw) or row["sha256"] != _sha(raw):
            raise WorldAfterstateV2ArtifactError("checkpoint manifest byte drift")
        try:
            _model, metadata = reopen_checkpoint(raw)
        except (ValueError, TypeError) as exc:
            raise WorldAfterstateV2ArtifactError(
                "checkpoint manifest typed reopen refused") from exc
        if (metadata["control_name"], metadata["seed_block"],
                metadata["member_index"], metadata["selected_epoch"],
                metadata["checkpoint_sha256"], metadata["model_state_sha256"],
                metadata["freeze_sha256"], metadata["config_sha256"],
                metadata["population_sha256"], metadata["schedule_sha256"],
                metadata["common_epoch_sha256"]) != (
                    cohort, seed_block, member, epoch,
                    row["checkpoint_sha256"], row["model_state_sha256"],
                    row["freeze_sha256"], row["config_sha256"],
                    row["population_sha256"], row["schedule_sha256"],
                    row["common_epoch_sha256"]):
            raise WorldAfterstateV2ArtifactError(
                "checkpoint manifest semantic drift")
        if (metadata["freeze_sha256"], metadata["config_sha256"],
                metadata["population_sha256"], metadata["schedule_sha256"],
                metadata["common_epoch_sha256"]) != (
                    expected_freeze_sha256, expected_config_sha256,
                    expected_population_sha256, expected_schedules[member],
                    expected_common_epoch_sha256):
            raise WorldAfterstateV2ArtifactError(
                "checkpoint manifest external identity drift")
        result.append((_model, metadata))
    shared = {(metadata["freeze_sha256"], metadata["config_sha256"],
               metadata["population_sha256"],
               metadata["common_epoch_sha256"])
              for _, metadata in result}
    if len(shared) != 1:
        raise WorldAfterstateV2ArtifactError(
            "checkpoint immutable identity mixing")
    if seen != set(expected_members) or {
            path.name for path in directory.iterdir()} != expected_names:
        raise WorldAfterstateV2ArtifactError("checkpoint file population drift")
    return tuple(result)


# Explicit aggregate aliases make the boundary discoverable to callers that
# distinguish a manifest from its individual shard.
publish_continuation_aggregate_manifest = publish_continuation_manifest
reopen_continuation_aggregate_manifest = reopen_continuation_manifest
publish_checkpoint_aggregate_manifest = publish_checkpoint_manifest
reopen_checkpoint_aggregate_manifest = reopen_checkpoint_manifest


__all__ = [
    "AUTHORITY", "CHECKPOINT_DIRNAME", "CHECKPOINT_MANIFEST_SCHEMA",
    "CHECKPOINT_SCHEMA", "CONTINUATION_DIRNAME",
    "CONTINUATION_MANIFEST_SCHEMA", "CONTINUATION_SCHEMA",
    "MANIFEST_NAME", "RECONSTRUCTION_WORKER_ARMS",
    "CheckpointShardV2", "ContinuationShardV2",
    "WorldAfterstateV2ArtifactError", "checkpoint_manifest_path",
    "checkpoint_path", "checkpoint_shard_path", "continuation_manifest_path",
    "continuation_path", "continuation_shard_path",
    "publish_checkpoint_aggregate_manifest",
    "publish_checkpoint_manifest", "publish_checkpoint_shard",
    "publish_continuation_aggregate_manifest",
    "publish_continuation_manifest", "publish_continuation_shard",
    "reopen_checkpoint_aggregate_manifest", "reopen_checkpoint_manifest",
    "reopen_checkpoint_shard", "reopen_continuation_aggregate_manifest",
    "reopen_continuation_manifest", "reopen_continuation_shard",
]
