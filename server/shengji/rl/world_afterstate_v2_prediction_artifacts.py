"""Immutable filesystem publication for target-free V2 prediction manifests.

The inference module owns the typed prediction-population contract.  This
module only gives that contract a strict JSON and immutable filesystem seam;
it does not run inference, open labels, or select actions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_inference import (
    CONTROL_NAMES,
    POPULATION_SCHEMA,
    SEED_BLOCKS,
    validate_prediction_population_manifest_v2,
)


PREDICTION_DIRNAME = "predictions"
MANIFEST_NAME = "manifest.json"
MAIN_SUBFOLD = "main"
SELECT_SUBFOLDS = ("epoch-select", "precision-select")


class WorldAfterstateV2PredictionArtifactError(ValueError):
    """A prediction manifest, path, or immutable publication drifted."""


WorldAfterstateV2PredictionArtifactsError = \
    WorldAfterstateV2PredictionArtifactError


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2PredictionArtifactError(f"{label} drift")
    return value


def _root(root: Path) -> Path:
    # The root is deliberately caller-provided and must already exist.  This
    # prevents a typo from silently creating a new publication namespace.
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise WorldAfterstateV2PredictionArtifactError("artifact root drift")
    return root


def _directory(path: Path, *, create: bool = False) -> Path:
    if path.is_symlink():
        raise WorldAfterstateV2PredictionArtifactError(
            "artifact directory is a symlink")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise WorldAfterstateV2PredictionArtifactError(
                "artifact directory creation refused") from exc
    if path.is_symlink() or not path.is_dir():
        raise WorldAfterstateV2PredictionArtifactError(
            "artifact directory drift")
    return path


def _parent_directory(root: Path, path: Path, *, create: bool = False) -> None:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise WorldAfterstateV2PredictionArtifactError(
            "artifact path escapes root") from exc
    cursor = root
    for part in parts:
        cursor = cursor / part
        _directory(cursor, create=create)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorldAfterstateV2PredictionArtifactError(f"{label} drift")
    return value


def _identity(
        control_name: object, seed_block: object, split: object,
        subfold: object) -> tuple[str, int, str, str]:
    if type(control_name) is not str or control_name not in CONTROL_NAMES:
        raise WorldAfterstateV2PredictionArtifactError("prediction cohort drift")
    seed_block = _integer(seed_block, "prediction seed block")
    if seed_block not in SEED_BLOCKS:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction seed block drift")
    if split not in ("fit", "select", "audit"):
        raise WorldAfterstateV2PredictionArtifactError("prediction split drift")
    if split == "select":
        if subfold not in SELECT_SUBFOLDS:
            raise WorldAfterstateV2PredictionArtifactError(
                "prediction select subfold drift")
        path_subfold = subfold
    else:
        if subfold is not None:
            raise WorldAfterstateV2PredictionArtifactError(
                "prediction non-select subfold drift")
        path_subfold = MAIN_SUBFOLD
    return control_name, seed_block, split, path_subfold


def _manifest_subfold(manifest: Mapping[str, Any]) -> str | None:
    split = manifest.get("split")
    bindings = manifest.get("root_bindings")
    if type(bindings) is not list or not bindings:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction root binding population drift")
    subfolds = [binding.get("select_subfold")
                for binding in bindings if type(binding) is dict]
    if not subfolds or any(item != subfolds[0] for item in subfolds):
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction subfold population drift")
    subfold = subfolds[0]
    if split == "select":
        if subfold not in SELECT_SUBFOLDS:
            raise WorldAfterstateV2PredictionArtifactError(
                "prediction select subfold drift")
        return subfold
    if subfold is not None:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction non-select subfold drift")
    return None


def prediction_population_manifest_path(
        root: Path, control_name: str, seed_block: int, split: str,
        subfold: str | None = None) -> Path:
    """Return the canonical path for one cohort/block/split manifest."""
    root = _root(root)
    control_name, seed_block, split, path_subfold = _identity(
        control_name, seed_block, split, subfold)
    return (root / PREDICTION_DIRNAME / control_name
            / f"block-{seed_block}" / split / path_subfold / MANIFEST_NAME)


prediction_manifest_path = prediction_population_manifest_path


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WorldAfterstateV2PredictionArtifactError(
                "prediction manifest JSON has duplicate key")
        value[key] = item
    return value


def _reject_number(value: str) -> None:
    raise WorldAfterstateV2PredictionArtifactError(
        f"prediction manifest contains invalid number {value}")


def _strict_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest is empty")
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except WorldAfterstateV2PredictionArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest is not canonical JSON")
    return value


def _typed_manifest(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest type drift")
    try:
        validate_prediction_population_manifest_v2(value)
    except (TypeError, ValueError) as exc:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest validation refused") from exc
    if value.get("schema") != POPULATION_SCHEMA:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest schema drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    _digest(value.get("manifest_sha256"), "prediction manifest SHA-256")
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest hash drift")
    _manifest_subfold(value)
    return value


def _check_identity(
        manifest: Mapping[str, Any], *, control_name: str, seed_block: int,
        split: str, subfold: str | None) -> None:
    expected_subfold = _manifest_subfold(manifest)
    if (manifest.get("control_name"), manifest.get("seed_block"),
            manifest.get("split"), expected_subfold) != (
                control_name, seed_block, split, subfold):
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest path identity drift")


@dataclass(frozen=True)
class PredictionPopulationArtifactV2:
    """Immutable receipt for one published prediction population."""

    relative_path: str
    byte_count: int
    sha256: str
    manifest_sha256: str

    @property
    def path(self) -> str:
        """Compatibility view used by the other V2 artifact receipts."""
        return self.relative_path

    def validate(self) -> None:
        relative = Path(self.relative_path) if type(self.relative_path) is str \
            else None
        if (relative is None or not self.relative_path or relative.is_absolute()
                or relative.as_posix() != self.relative_path
                or any(part in ("", ".", "..") for part in relative.parts)):
            raise WorldAfterstateV2PredictionArtifactError(
                "prediction artifact path drift")
        if isinstance(self.byte_count, bool) or not isinstance(self.byte_count, int) \
                or self.byte_count <= 0:
            raise WorldAfterstateV2PredictionArtifactError(
                "prediction artifact byte count drift")
        _digest(self.sha256, "prediction artifact SHA-256")
        _digest(self.manifest_sha256, "prediction manifest SHA-256")


PredictionManifestArtifactV2 = PredictionPopulationArtifactV2
PredictionPopulationManifestRecordV2 = PredictionPopulationArtifactV2


def _record(root: Path, path: Path, raw: bytes, manifest: Mapping[str, Any]) \
        -> PredictionPopulationArtifactV2:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction artifact path escapes root") from exc
    result = PredictionPopulationArtifactV2(
        relative_path=relative, byte_count=len(raw), sha256=_sha_bytes(raw),
        manifest_sha256=manifest["manifest_sha256"])
    result.validate()
    return result


def publish_prediction_population_manifest(
        root: Path, manifest: Mapping[str, Any], *,
        control_name: str | None = None, seed_block: int | None = None,
        split: str | None = None, subfold: str | None = None
        ) -> PredictionPopulationArtifactV2:
    """Validate and exclusively publish one canonical population manifest."""
    root = _root(root)
    value = _typed_manifest(manifest)
    actual_subfold = _manifest_subfold(value)
    if control_name is None:
        control_name = value["control_name"]
    if seed_block is None:
        seed_block = value["seed_block"]
    if split is None:
        split = value["split"]
    if subfold is None and split == "select":
        subfold = actual_subfold
    control_name, seed_block, split, path_subfold = _identity(
        control_name, seed_block, split, subfold)
    _check_identity(value, control_name=control_name, seed_block=seed_block,
                    split=split,
                    subfold=(path_subfold if split == "select" else None))
    raw = canonical_json_bytes(value)
    path = prediction_population_manifest_path(
        root, control_name, seed_block, split, actual_subfold)
    _parent_directory(root, path.parent, create=True)
    try:
        digest = publish_exclusive_bytes(path, raw)
        reread = stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest publication refused") from exc
    if reread != raw or digest != _sha_bytes(raw):
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest publication byte drift")
    reopened = _typed_manifest(_strict_json(reread))
    _check_identity(reopened, control_name=control_name,
                    seed_block=seed_block, split=split, subfold=actual_subfold)
    return _record(root, path, reread, reopened)


publish_prediction_manifest = publish_prediction_population_manifest


def reopen_prediction_population_manifest(
        root: Path, *, control_name: str, seed_block: int, split: str,
        subfold: str | None = None, expected_sha256: str | None = None,
        expected_manifest_sha256: str | None = None
        ) -> dict[str, Any]:
    """Stable-read and typed-reopen the exact manifest for one identity."""
    root = _root(root)
    control_name, seed_block, split, _ = _identity(
        control_name, seed_block, split, subfold)
    path = prediction_population_manifest_path(
        root, control_name, seed_block, split, subfold)
    _parent_directory(root, path.parent, create=False)
    try:
        raw = stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest stable read refused") from exc
    value = _typed_manifest(_strict_json(raw))
    _check_identity(value, control_name=control_name, seed_block=seed_block,
                    split=split, subfold=subfold)
    digest = _sha_bytes(raw)
    if expected_sha256 is not None and digest != _digest(
            expected_sha256, "expected prediction artifact SHA-256"):
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest byte hash drift")
    if expected_manifest_sha256 is not None and value["manifest_sha256"] != \
            _digest(expected_manifest_sha256,
                    "expected prediction manifest SHA-256"):
        raise WorldAfterstateV2PredictionArtifactError(
            "prediction manifest hash drift")
    return value


reopen_prediction_manifest = reopen_prediction_population_manifest
reopen_prediction_population_manifest_artifact = \
    reopen_prediction_population_manifest


def reopen_prediction_population_artifact(
        root: Path, *, control_name: str, seed_block: int, split: str,
        subfold: str | None = None) -> tuple[dict[str, Any], PredictionPopulationArtifactV2]:
    """Reopen a manifest and return its exact immutable publication receipt."""
    value = reopen_prediction_population_manifest(
        root, control_name=control_name, seed_block=seed_block, split=split,
        subfold=subfold)
    path = prediction_population_manifest_path(
        root, control_name, seed_block, split, subfold)
    raw = stable_read_bytes(path)
    return value, _record(root, path, raw, value)


__all__ = [
    "MANIFEST_NAME", "MAIN_SUBFOLD", "PREDICTION_DIRNAME",
    "PredictionManifestArtifactV2", "PredictionPopulationArtifactV2",
    "PredictionPopulationManifestRecordV2",
    "SELECT_SUBFOLDS", "WorldAfterstateV2PredictionArtifactError",
    "WorldAfterstateV2PredictionArtifactsError",
    "prediction_manifest_path", "prediction_population_manifest_path",
    "publish_prediction_manifest", "publish_prediction_population_manifest",
    "reopen_prediction_manifest", "reopen_prediction_population_artifact",
    "reopen_prediction_population_manifest",
    "reopen_prediction_population_manifest_artifact",
]
