"""Immutable filesystem seam for exact V2 training recovery histories.

This module stores only recovery bundles produced by the in-memory training
controller.  A complete epoch is visible through its manifest only after all
member files have been published, reread, and typed-reopened.  There is no
overwrite, deletion, or regeneration operation here; a failed next epoch can
only be resumed by exact reuse of its immutable durable member bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_checkpoint import CONTROL_NAMES
from .world_afterstate_v2_recovery import reopen_recovery


STORE_SCHEMA = "world-afterstate-v2-training-recovery-store-v1"
EPOCH_MANIFEST_SCHEMA = "world-afterstate-v2-training-recovery-epoch-v1"
MANIFEST_NAME = "manifest.json"
EPOCHS_DIRNAME = "epochs"
AUTHORITY = {
    "training_authorized": False,
    "audit_opening_authorized": False,
    "report_rows_opened": False,
    "retry_authorized": False,
    "deletion_authorized": False,
}


class WorldAfterstateV2RecoveryStoreError(ValueError):
    """A recovery-store path, binding, or immutable epoch was refused."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2RecoveryStoreError(f"{label} drift")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2RecoveryStoreError(f"{label} drift")
    return value


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise WorldAfterstateV2RecoveryStoreError(
                    f"{label} duplicate key")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs,
                           parse_constant=lambda item: (_ for _ in ()).throw(
                               ValueError(item)))
    except WorldAfterstateV2RecoveryStoreError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2RecoveryStoreError(f"{label} JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2RecoveryStoreError(f"{label} canonical drift")
    return value


def _directory(path: Path, *, create: bool = False) -> Path:
    if not isinstance(path, Path) or path.is_symlink():
        raise WorldAfterstateV2RecoveryStoreError("recovery store symlink")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery store directory creation refused") from exc
    if path.is_symlink() or not path.is_dir():
        raise WorldAfterstateV2RecoveryStoreError("recovery store directory drift")
    return path


def _read(path: Path) -> bytes:
    try:
        return stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2RecoveryStoreError(
            "recovery store stable read refused") from exc


@dataclass(frozen=True)
class RecoveryStoreBindingV2:
    """The stage/admission identity bound into every epoch manifest."""

    freeze_sha256: str
    admission_sha256: str
    cohort_name: str
    seed_block: int
    population_sha256: str
    selection_population_sha256: str
    config_sha256: str
    member_count: int = 4

    def validate(self) -> None:
        for key in ("freeze_sha256", "admission_sha256", "population_sha256",
                    "selection_population_sha256", "config_sha256"):
            _digest(getattr(self, key), f"recovery store {key}")
        if self.cohort_name not in CONTROL_NAMES:
            raise WorldAfterstateV2RecoveryStoreError("recovery store cohort drift")
        _integer(self.seed_block, "recovery store seed block", 1)
        if self.seed_block not in (1, 2) \
                or isinstance(self.member_count, bool) \
                or self.member_count not in (1, 4):
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery store member/seed identity drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "freeze_sha256": self.freeze_sha256,
            "admission_sha256": self.admission_sha256,
            "cohort_name": self.cohort_name,
            "seed_block": self.seed_block,
            "population_sha256": self.population_sha256,
            "selection_population_sha256": self.selection_population_sha256,
            "config_sha256": self.config_sha256,
            "member_count": self.member_count,
        }


@dataclass(frozen=True)
class RecoveryEpochReceiptV2:
    """Receipt returned only after one complete epoch is manifest-visible."""

    epoch: int
    member_count: int
    manifest_relative_path: str
    member_sha256s: tuple[str, ...]
    completed_epoch_count: int
    schema: str = EPOCH_MANIFEST_SCHEMA

    def validate(self) -> None:
        _integer(self.epoch, "recovery epoch", 1)
        if self.member_count not in (1, 4) \
                or type(self.member_sha256s) is not tuple \
                or len(self.member_sha256s) != self.member_count \
                or any(type(value) is not str or len(value) != 64
                       for value in self.member_sha256s) \
                or not self.manifest_relative_path \
                or self.schema != EPOCH_MANIFEST_SCHEMA:
            raise WorldAfterstateV2RecoveryStoreError("recovery receipt drift")
        _integer(self.completed_epoch_count, "completed recovery epoch count", 0)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema, "epoch": self.epoch,
            "member_count": self.member_count,
            "manifest_relative_path": self.manifest_relative_path,
            "member_sha256s": list(self.member_sha256s),
            "completed_epoch_count": self.completed_epoch_count,
        }


class WorldAfterstateV2RecoveryStore:
    """A one-shot, immutable store for one controller recovery history."""

    def __init__(self, root: Path, binding: RecoveryStoreBindingV2 | None = None,
                 *, freeze_sha256: str | None = None,
                 admission_sha256: str | None = None,
                 cohort_name: str | None = None, seed_block: int | None = None,
                 population_sha256: str | None = None,
                 training_population_sha256: str | None = None,
                 selection_population_sha256: str | None = None,
                 config_sha256: str | None = None,
                 member_count: int = 4) -> None:
        if binding is None:
            if population_sha256 is None:
                population_sha256 = training_population_sha256
            elif training_population_sha256 is not None \
                    and training_population_sha256 != population_sha256:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery store population alias drift")
            fields = (freeze_sha256, admission_sha256, cohort_name, seed_block,
                      population_sha256, selection_population_sha256, config_sha256)
            if any(item is None for item in fields):
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery store binding incomplete")
            binding = RecoveryStoreBindingV2(
                freeze_sha256=freeze_sha256, admission_sha256=admission_sha256,
                cohort_name=cohort_name, seed_block=seed_block,
                population_sha256=population_sha256,
                selection_population_sha256=selection_population_sha256,
                config_sha256=config_sha256, member_count=member_count)
        if type(binding) is not RecoveryStoreBindingV2:
            raise WorldAfterstateV2RecoveryStoreError("recovery store binding type drift")
        binding.validate()
        if not isinstance(root, Path) or root.is_symlink():
            raise WorldAfterstateV2RecoveryStoreError("recovery store root drift")
        _directory(root, create=True)
        self.root = root
        self.binding = binding
        self._epochs = _directory(root / EPOCHS_DIRNAME, create=True)

    @property
    def member_count(self) -> int:
        return self.binding.member_count

    def _expected_control(self) -> str:
        return self.binding.cohort_name

    def _validate_bundles(self, epoch: int, bundles: tuple[bytes, ...]) -> tuple:
        if type(bundles) is not tuple or len(bundles) != self.member_count \
                or any(type(raw) is not bytes or not raw for raw in bundles):
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch member drop/duplicate")
        opened = []
        for member, raw in enumerate(bundles):
            opened.append(self._validate_bundle(epoch, member, raw))
        return tuple(opened)

    def _validate_bundle(self, epoch: int, member: int, raw: bytes):
        try:
            item = reopen_recovery(
                raw, expected_freeze_sha256=self.binding.freeze_sha256,
                expected_selection_population_sha256=
                self.binding.selection_population_sha256)
        except Exception as exc:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery bundle reopen refused") from exc
        metadata = item.metadata
        if (metadata["completed_epoch"] != epoch
                or metadata["seed_block"] != self.binding.seed_block
                or metadata["member_index"] != member
                or metadata["control_name"] != self._expected_control()
                or metadata["freeze_sha256"] != self.binding.freeze_sha256
                or metadata["config_sha256"] != self.binding.config_sha256
                or metadata["population_sha256"] != self.binding.population_sha256
                or metadata["selection_population_sha256"] !=
                self.binding.selection_population_sha256):
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery bundle identity drift")
        return item

    def _manifest_path(self, epoch: int) -> Path:
        _integer(epoch, "recovery epoch", 1)
        return self._epochs / f"epoch-{epoch}" / MANIFEST_NAME

    def _partial_path(self, epoch: int) -> Path:
        _integer(epoch, "recovery epoch", 1)
        return self._epochs / f"epoch-{epoch}.partial"

    def _read_partial_members(self, epoch: int, directory: Path) \
            -> tuple[dict[int, bytes], tuple[dict[str, Any], tuple[bytes, ...]] | None]:
        """Validate one next-epoch partial without making it visible."""
        _directory(directory)
        expected_members = {
            f"member-{member}.bin" for member in range(self.member_count)}
        try:
            names = {item.name for item in directory.iterdir()}
        except OSError as exc:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery partial directory read refused") from exc
        if not names <= expected_members | {MANIFEST_NAME}:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery partial/extra file")
        members: dict[int, bytes] = {}
        for member in range(self.member_count):
            name = f"member-{member}.bin"
            if name not in names:
                continue
            path = directory / name
            raw = _read(path)
            self._validate_bundle(epoch, member, raw)
            members[member] = raw
        manifest_state = None
        if MANIFEST_NAME in names:
            manifest_state = self._read_manifest_at(directory, epoch)
            if len(members) != self.member_count:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery partial manifest member drop")
            if tuple(members[member] for member in range(self.member_count)) \
                    != manifest_state[1]:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery partial manifest member drift")
        return members, manifest_state

    def publish_epoch(
        self, epoch: int, bundles: tuple[bytes, ...], *,
            callback: Callable[[tuple[bytes, ...]], None] | None = None
            ) -> RecoveryEpochReceiptV2:
        """Publish one complete epoch through an immutable next-epoch partial."""
        _integer(epoch, "recovery epoch", 1)
        if callback is not None and not callable(callback):
            raise WorldAfterstateV2RecoveryStoreError("recovery callback drift")
        if self.member_count == 1 and type(bundles) is bytes:
            bundles = (bundles,)
        self._validate_bundles(epoch, bundles)
        existing = self._complete_manifests()
        if epoch != len(existing) + 1:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch is noncontiguous")
        directory = self._epochs / f"epoch-{epoch}"
        partial = self._partial_path(epoch)
        if os.path.lexists(directory):
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch output slot occupied")
        if os.path.lexists(partial):
            if partial.is_symlink() or not partial.is_dir():
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery partial directory drift")
        else:
            try:
                partial.mkdir(mode=0o700)
            except OSError as exc:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery partial directory creation refused") from exc
        prior_members, prior_manifest = self._read_partial_members(
            epoch, partial)
        paths = tuple(partial / f"member-{member}.bin"
                      for member in range(self.member_count))
        try:
            for member, (path, raw) in enumerate(zip(paths, bundles, strict=True)):
                if member in prior_members:
                    if prior_members[member] != raw:
                        raise WorldAfterstateV2RecoveryStoreError(
                            "recovery partial member mismatch")
                    continue
                digest = publish_exclusive_bytes(path, raw)
                if digest != _sha_bytes(raw) or _read(path) != raw:
                    raise WorldAfterstateV2RecoveryStoreError(
                        "recovery member publication drift")
            # Reopen again from the exact durable bytes, not the caller's
            # in-memory object, before exposing the epoch manifest.
            durable_bundles = tuple(_read(path) for path in paths)
            opened = self._validate_bundles(epoch, durable_bundles)
        except (OSError, ValueError) as exc:
            if isinstance(exc, WorldAfterstateV2RecoveryStoreError):
                raise
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery member publication refused") from exc
        if callback is not None:
            try:
                callback(durable_bundles)
            except Exception as exc:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery callback refused") from exc
        durable_bundles = tuple(_read(path) for path in paths)
        opened = self._validate_bundles(epoch, durable_bundles)
        if prior_manifest is not None:
            manifest, manifest_bundles = self._read_manifest_at(partial, epoch)
            if manifest_bundles != durable_bundles:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery partial manifest member drift")
        else:
            rows = [{
                "member_index": member,
                "relative_path": f"{EPOCHS_DIRNAME}/epoch-{epoch}/member-{member}.bin",
                "byte_count": len(raw), "sha256": _sha_bytes(raw),
                "completed_epoch": item.metadata["completed_epoch"],
                "common_epoch_sha256": item.metadata["common_epoch_sha256"],
            } for member, (raw, item) in enumerate(
                zip(durable_bundles, opened, strict=True))]
            body = {
                "schema": EPOCH_MANIFEST_SCHEMA, "store_schema": STORE_SCHEMA,
                "authority": dict(AUTHORITY), "binding": self.binding.payload(),
                "epoch": epoch, "member_count": self.member_count,
                "members": rows,
            }
            manifest = {**body, "manifest_sha256": _sha(body)}
            manifest_raw = canonical_json_bytes(manifest)
            manifest_path = partial / MANIFEST_NAME
            try:
                publish_exclusive_bytes(manifest_path, manifest_raw)
                if _read(manifest_path) != manifest_raw:
                    raise WorldAfterstateV2RecoveryStoreError(
                        "recovery manifest publication drift")
            except (OSError, ValueError) as exc:
                if isinstance(exc, WorldAfterstateV2RecoveryStoreError):
                    raise
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery manifest publication refused") from exc
            # The manifest itself must be typed-reopened from the partial
            # directory before it can be promoted.
            manifest, manifest_bundles = self._read_manifest_at(partial, epoch)
            if manifest_bundles != durable_bundles:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery manifest member drift")
        rows = manifest["members"]
        try:
            descriptor = os.open(partial, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if os.path.lexists(directory):
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery epoch output slot occupied")
            os.rename(partial, directory)
            descriptor = os.open(self._epochs, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except (OSError, ValueError) as exc:
            if isinstance(exc, WorldAfterstateV2RecoveryStoreError):
                raise
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch promotion refused") from exc
        receipt = RecoveryEpochReceiptV2(
            epoch=epoch, member_count=self.member_count,
            manifest_relative_path=(
                f"{EPOCHS_DIRNAME}/epoch-{epoch}/{MANIFEST_NAME}"),
            member_sha256s=tuple(row["sha256"] for row in rows),
            completed_epoch_count=epoch)
        receipt.validate()
        return receipt

    def _read_manifest_at(self, directory: Path, epoch: int) \
            -> tuple[dict[str, Any], tuple[bytes, ...]]:
        _directory(directory)
        path = directory / MANIFEST_NAME
        raw = _read(path)
        value = _strict_json(raw, "recovery epoch manifest")
        required = {"schema", "store_schema", "authority", "binding", "epoch",
                    "member_count", "members", "manifest_sha256"}
        if set(value) != required or value["schema"] != EPOCH_MANIFEST_SCHEMA \
                or value["store_schema"] != STORE_SCHEMA \
                or value["authority"] != AUTHORITY:
            raise WorldAfterstateV2RecoveryStoreError("recovery manifest schema drift")
        body = {key: item for key, item in value.items()
                if key != "manifest_sha256"}
        if value["manifest_sha256"] != _sha(body):
            raise WorldAfterstateV2RecoveryStoreError("recovery manifest rehash drift")
        if value["epoch"] != epoch or value["member_count"] != self.member_count \
                or value["binding"] != self.binding.payload():
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery manifest identity drift")
        rows = value["members"]
        if type(rows) is not list or len(rows) != self.member_count:
            raise WorldAfterstateV2RecoveryStoreError("recovery manifest member drop")
        expected_names = {MANIFEST_NAME, *(f"member-{member}.bin"
                                            for member in range(self.member_count))}
        try:
            names = {item.name for item in directory.iterdir()}
        except OSError as exc:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch directory read refused") from exc
        if names != expected_names:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch partial/extra file")
        bundles: list[bytes] = []
        for member, row in enumerate(rows):
            if type(row) is not dict or set(row) != {
                    "member_index", "relative_path", "byte_count", "sha256",
                    "completed_epoch", "common_epoch_sha256"} \
                    or row["member_index"] != member \
                    or row["relative_path"] != (
                        f"{EPOCHS_DIRNAME}/epoch-{epoch}/member-{member}.bin") \
                    or row["completed_epoch"] != epoch:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery manifest member identity drift")
            _digest(row["sha256"], "recovery member SHA-256")
            _digest(row["common_epoch_sha256"], "recovery common epoch SHA-256")
            path = directory / f"member-{member}.bin"
            raw = _read(path)
            if row["byte_count"] != len(raw) or row["sha256"] != _sha_bytes(raw):
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery member rehash drift")
            bundles.append(raw)
        self._validate_bundles(epoch, tuple(bundles))
        for row, raw in zip(rows, bundles, strict=True):
            item = reopen_recovery(
                raw, expected_freeze_sha256=self.binding.freeze_sha256,
                expected_selection_population_sha256=
                self.binding.selection_population_sha256)
            if row["common_epoch_sha256"] != item.metadata["common_epoch_sha256"]:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery common epoch identity drift")
        return value, tuple(bundles)

    def _read_manifest(self, epoch: int) -> tuple[dict[str, Any], tuple[bytes, ...]]:
        return self._read_manifest_at(self._epochs / f"epoch-{epoch}", epoch)

    def _complete_manifests(self) -> list[dict[str, Any]]:
        _directory(self.root)
        _directory(self._epochs)
        try:
            root_names = {item.name for item in self.root.iterdir()}
        except OSError as exc:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery store root listing refused") from exc
        if root_names != {EPOCHS_DIRNAME}:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery store extra file")
        try:
            entries = tuple(self._epochs.iterdir())
        except OSError as exc:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch listing refused") from exc
        epochs: list[int] = []
        partials: list[tuple[int, Path]] = []
        for entry in entries:
            if entry.is_symlink() or not entry.is_dir():
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery epoch symlink/partial drift")
            match = re.fullmatch(r"epoch-([1-9][0-9]*)", entry.name)
            if match is not None:
                epochs.append(int(match.group(1)))
                continue
            match = re.fullmatch(r"epoch-([1-9][0-9]*)\.partial", entry.name)
            if match is not None:
                partials.append((int(match.group(1)), entry))
                continue
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epoch name drift")
        epochs.sort()
        if epochs != list(range(1, len(epochs) + 1)):
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery epochs are noncontiguous")
        if len(partials) > 1:
            raise WorldAfterstateV2RecoveryStoreError(
                "recovery partial epoch population drift")
        manifests = []
        for epoch in epochs:
            manifest, _bundles = self._read_manifest(epoch)
            manifests.append(manifest)
        if partials:
            partial_epoch, partial = partials[0]
            if partial_epoch != len(epochs) + 1:
                raise WorldAfterstateV2RecoveryStoreError(
                    "recovery partial epoch is non-next")
            self._read_partial_members(partial_epoch, partial)
        return manifests

    def reopen_history(self):
        """Return the exact tuple shape consumed by the training controller."""
        manifests = self._complete_manifests()
        result = []
        for epoch, _manifest in enumerate(manifests, 1):
            _manifest, bundles = self._read_manifest(epoch)
            result.append(bundles if self.member_count == 4 else bundles[0])
        return tuple(result)

    history = reopen_history
    read_history = reopen_history
    append_epoch = publish_epoch


__all__ = [
    "AUTHORITY", "EPOCH_MANIFEST_SCHEMA", "RecoveryEpochReceiptV2",
    "RecoveryStoreBindingV2", "STORE_SCHEMA",
    "WorldAfterstateV2RecoveryStore", "WorldAfterstateV2RecoveryStoreError",
]
