"""Closed supervisor adapters for the Value-Afterstate V2 training stages.

The adapters in this module are intentionally composition only.  Training,
control construction, inference, evaluation, checkpoint validation, and
filesystem publication remain owned by their reviewed modules.  A supervisor
gets a fixed producer identity and this module supplies the frozen inputs and
the immutable progress/recovery seams around it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_artifacts import (
    AUTHORITY as CHECKPOINT_AUTHORITY, CheckpointShardV2,
    CHECKPOINT_MANIFEST_SCHEMA, checkpoint_manifest_path,
    publish_checkpoint_manifest,
    publish_checkpoint_shard, reopen_checkpoint_manifest, reopen_checkpoint_shard,
)
from .world_afterstate_v2_checkpoint import reopen_checkpoint
from .world_afterstate_v2_controls import (
    action_association_permutation, complete_world_shuffle,
    control_training_examples, label_permutation, validate_control_evidence,
)
from .world_afterstate_v2_diagnostic_producers import (
    NestedCurveInputV2, produce_nested_curve_v2,
)
from .world_afterstate_v2_evaluation import evaluate_nested_curve_v2
from .world_afterstate_v2_inference import (
    ValueInferenceRootV2, build_inference_root_v2, nested_curve_prediction_manifest_v2,
    predict_nested_curve_v2, predict_roots_v2, prediction_population_manifest_v2,
    reopen_prediction_population_manifest_v2,
)
from .world_afterstate_v2_metrics import build_natural_fit_prior
from .world_afterstate_v2_label import ContinuationOutcomeV2
from .world_afterstate_v2_population_artifacts import reopen_population_manifest
from .world_afterstate_v2_prediction_artifacts import (
    prediction_population_manifest_path, publish_prediction_population_manifest,
    reopen_prediction_population_artifact,
)
from .world_afterstate_v2_schedule import derive_nested_prefixes, training_epoch_batches
from .world_afterstate_v2_training_controller import (
    CohortTrainingBuildV2, SingleMemberTrainingBuildV2, reopen_cohort_build,
    reopen_member_build, train_named_cohort, train_named_member,
    validate_cohort_manifest,
)
from .world_afterstate_v2_training import model_state_sha256
from .world_afterstate_v2_training_recovery_store import (
    RecoveryStoreBindingV2, WorldAfterstateV2RecoveryStore,
)
from .world_afterstate_v2_training_stage_inputs import build_training_stage_inputs


ABI = "world-afterstate-v2-stage-adapter-supervisor-shards-v1"
SCHEMA = "world-afterstate-v2-training-stage-adapter-receipt-v1"
HEADROOM_SECONDS = 60
MAX_STAGE_SECONDS = 6 * 60 * 60

# The two seed blocks deliberately have different control populations, but
# both include the complete-world-shuffle contrast.  Keep this mapping
# closed so a missing or misclassified cohort cannot silently become a valid
# stage composition.
_EXPECTED_STAGE_COHORTS = {
    "block-1-natural": ("natural",),
    "block-1-controls": (
        "action-association-permutation", "label-permutation",
        "complete-world-shuffle"),
    "block-2-natural": ("natural",),
    "block-2-controls": ("complete-world-shuffle",),
}


class TrainingStageAdapterUnavailable(ValueError):
    """A frozen training-stage dependency or publication was refused."""


# Keep the short error name used by the population/early-stage adapter ABI.
StageAdapterUnavailable = TrainingStageAdapterUnavailable


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise TrainingStageAdapterUnavailable(f"{label} drift")
    return value


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrainingStageAdapterUnavailable("training receipt JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise TrainingStageAdapterUnavailable("training receipt canonical drift")
    return value


def _freeze_sha(freeze: Any) -> str:
    try:
        return _digest(freeze.sha256(), "freeze SHA-256")
    except Exception as exc:
        raise TrainingStageAdapterUnavailable("freeze identity unavailable") from exc


def _admission_sha(supervisor: Any) -> str:
    try:
        return _digest(supervisor.admission.sha256(), "admission SHA-256")
    except Exception as exc:
        raise TrainingStageAdapterUnavailable("admission identity unavailable") from exc


def _elapsed(supervisor: Any) -> int:
    clock = getattr(supervisor, "clock", None)
    try:
        now = clock() if callable(clock) else time.monotonic_ns()
        started = getattr(supervisor, "_started", now)
        return max(0, int(now) - int(started))
    except (TypeError, ValueError, AttributeError):
        return 0


def _budget(freeze: Any, supervisor: Any) -> int:
    try:
        total = int(freeze.deadline_seconds) * 1_000_000_000
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrainingStageAdapterUnavailable("training deadline unavailable") from exc
    remaining = total - _elapsed(supervisor) - HEADROOM_SECONDS * 1_000_000_000
    if remaining <= 0:
        raise TrainingStageAdapterUnavailable("global deadline headroom exhausted")
    return min(MAX_STAGE_SECONDS * 1_000_000_000, remaining)


def _progress(supervisor: Any, stage: str) -> Callable[[dict[str, Any]], None]:
    def report(value: dict[str, Any]) -> None:
        if type(value) is not dict:
            raise TrainingStageAdapterUnavailable("training progress drift")
        try:
            completed = value["completed_units"]
            total = value["total_units"]
            supervisor.emit_progress(
                stage=stage, substage="training", completed=completed, total=total,
                active_workers=value["active_workers"], active_threads=0,
                sealed_checkpoints=value.get("completed_units", 0) // 4)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise TrainingStageAdapterUnavailable("training progress publication refused") from exc
    return report


def _completed(supervisor: Any, *stages: str) -> None:
    state = getattr(supervisor, "state", None)
    completed = set(getattr(state, "completed_stages", ()) if state is not None else ())
    missing = [stage for stage in stages if stage not in completed]
    if missing:
        raise TrainingStageAdapterUnavailable(
            "training stage requires completed prior stage: " + ",".join(missing))


def _publish(supervisor: Any, stage: str, shard: str, raw: bytes) -> None:
    try:
        supervisor.register_verified_shard(stage, shard, raw)
    except Exception as exc:
        raise TrainingStageAdapterUnavailable(
            f"{stage} {shard} publication refused") from exc


def _root_file(root: Path, relative: str, label: str) -> Path:
    """Resolve a root-contained file without traversing a symlink."""
    if (type(relative) is not str or not relative
            or Path(relative).is_absolute() or "\\" in relative
            or Path(relative).as_posix() != relative
            or any(part in ("", ".", "..") for part in Path(relative).parts)):
        raise TrainingStageAdapterUnavailable(f"{label} path drift")
    target = root / relative
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise TrainingStageAdapterUnavailable(f"{label} escapes supervisor root") from exc
    cursor = root
    for part in Path(relative).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise TrainingStageAdapterUnavailable(f"{label} symlink parent")
    return target


def _read_root_file(root: Path, relative: str, label: str) -> tuple[Path, bytes]:
    path = _root_file(root, relative, label)
    if path.is_symlink() or not path.is_file():
        raise TrainingStageAdapterUnavailable(f"{label} missing")
    try:
        return path, stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise TrainingStageAdapterUnavailable(f"{label} stable read refused") from exc


def _check_directory_chain(root: Path, directory: Path, label: str) -> None:
    """Check a root-contained directory without following symlinks."""
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise TrainingStageAdapterUnavailable(f"{label} root drift")
    try:
        parts = directory.relative_to(root).parts
    except ValueError as exc:
        raise TrainingStageAdapterUnavailable(f"{label} escapes supervisor root") from exc
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise TrainingStageAdapterUnavailable(f"{label} symlink parent")
        if cursor.exists() and not cursor.is_dir():
            raise TrainingStageAdapterUnavailable(f"{label} parent is not a directory")


def _ensure_directory_chain(root: Path, directory: Path, label: str) -> None:
    """Create a checked directory chain after artifact preflight succeeds."""
    _check_directory_chain(root, directory, label)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TrainingStageAdapterUnavailable(f"{label} directory creation refused") from exc
    _check_directory_chain(root, directory, label)


def _existing_artifact(path: Path, label: str) -> bytes | None:
    """Return an existing final artifact, refusing partial/symlink slots."""
    if path.is_symlink():
        raise TrainingStageAdapterUnavailable(f"{label} symlink")
    partial = path.with_name(path.name + ".partial")
    if partial.is_symlink() or partial.exists():
        raise TrainingStageAdapterUnavailable(f"{label} partial")
    if not path.exists():
        return None
    if not path.is_file():
        raise TrainingStageAdapterUnavailable(f"{label} is not a regular file")
    try:
        return stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise TrainingStageAdapterUnavailable(f"{label} stable read refused") from exc


def _exact_directory_population(
        directory: Path, expected_names: set[str], label: str) -> None:
    """Reject foreign files, directories, and partials in one artifact set."""
    if not directory.exists():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise TrainingStageAdapterUnavailable(f"{label} directory drift")
    try:
        names = {entry.name for entry in directory.iterdir()}
    except OSError as exc:
        raise TrainingStageAdapterUnavailable(f"{label} population unreadable") from exc
    if not names <= expected_names:
        raise TrainingStageAdapterUnavailable(f"{label} extra or mixed population")


def _directory_children_are_directories(directory: Path, label: str) -> None:
    """Reject stray files/symlinks in a namespace containing cohort dirs."""
    if not directory.exists():
        return
    if directory.is_symlink() or not directory.is_dir():
        raise TrainingStageAdapterUnavailable(f"{label} directory drift")
    try:
        children = tuple(directory.iterdir())
    except OSError as exc:
        raise TrainingStageAdapterUnavailable(f"{label} population unreadable") from exc
    if any(child.is_symlink() or not child.is_dir() for child in children):
        raise TrainingStageAdapterUnavailable(f"{label} extra or mixed population")


def _checkpoint_descriptor(
        root: Path, raw: bytes, *, cohort: str, seed_block: int,
        member_index: int, epoch: int) -> tuple[CheckpointShardV2, dict[str, Any]]:
    """Build the reviewed artifact row without publishing its bytes."""
    try:
        _model, metadata = reopen_checkpoint(raw)
        # Keep this preflight path computation usable before the optional
        # ``checkpoints/`` root has been created.  Reviewed path/reopen
        # functions are still used for every published or existing shard.
        target = (root / "checkpoints" / cohort / f"block-{seed_block}"
                  / f"epoch-{epoch}" / f"member-{member_index}.bin")
        if (metadata["control_name"], metadata["seed_block"],
                metadata["member_index"], metadata["selected_epoch"]) != (
                    cohort, seed_block, member_index, epoch):
            raise ValueError("checkpoint metadata binding")
        relative = target.relative_to(root).as_posix()
        descriptor = CheckpointShardV2(
            relative_path=relative, cohort=cohort, seed_block=seed_block,
            member_index=member_index, epoch=epoch, byte_count=len(raw),
            sha256=_sha(raw), checkpoint_sha256=metadata["checkpoint_sha256"],
            model_state_sha256=metadata["model_state_sha256"],
            freeze_sha256=metadata["freeze_sha256"],
            config_sha256=metadata["config_sha256"],
            population_sha256=metadata["population_sha256"],
            schedule_sha256=metadata["schedule_sha256"],
            common_epoch_sha256=metadata["common_epoch_sha256"])
        return descriptor, metadata
    except (KeyError, ValueError, TypeError) as exc:
        raise TrainingStageAdapterUnavailable(
            "cohort checkpoint descriptor refused") from exc


def _checkpoint_manifest_bytes(shards: Sequence[CheckpointShardV2]) -> bytes:
    body = {"schema": CHECKPOINT_MANIFEST_SCHEMA,
            "authority": dict(CHECKPOINT_AUTHORITY),
            "rows": [shard.row() for shard in shards]}
    return canonical_json_bytes({
        **body, "manifest_sha256": _sha(canonical_json_bytes(body))})


def _publish_cohort_artifacts(
        supervisor: Any, name: str, seed_block: int,
        build: CohortTrainingBuildV2) -> dict[str, Any]:
    """Publish canonical artifacts, reopening exact crash-resume prefixes."""
    try:
        _models, manifest = reopen_cohort_build(build)
        validate_cohort_manifest(manifest)
        if (manifest.get("cohort_name"), manifest.get("seed_block")) != (
                name, seed_block):
            raise ValueError("cohort manifest identity")
        raws = build.selected_checkpoint_raws
        selected_epoch = manifest["common_epoch"]["selected_epoch"]
        if type(raws) is not tuple or len(raws) != 4:
            raise ValueError("cohort checkpoint population")
        root = supervisor.root
        manifest_relative = f"cohort-manifests/{name}/manifest.json"
        manifest_path = _root_file(root, manifest_relative, "cohort manifest")
        manifest_raw = canonical_json_bytes(manifest)
        _check_directory_chain(root, manifest_path.parent, "cohort manifest")
        _exact_directory_population(
            manifest_path.parent, {manifest_path.name}, "cohort manifest")
        existing_cohort_manifest = _existing_artifact(
            manifest_path, "cohort manifest")
        if existing_cohort_manifest is not None:
            if existing_cohort_manifest != manifest_raw:
                raise ValueError("cohort manifest byte drift")
            reopened_manifest = _strict_json(existing_cohort_manifest)
            validate_cohort_manifest(reopened_manifest)
            if reopened_manifest != manifest:
                raise ValueError("cohort manifest metadata drift")

        # The terminal path contract passes ``checkpoint_root`` as the
        # artifact root to ``checkpoint_manifest_path``.  Keep the reviewed
        # artifact module's own ``checkpoints/`` namespace below that root so
        # terminal reopening resolves the same immutable files.
        checkpoint_artifact_root = root / "checkpoints"
        _check_directory_chain(
            root, checkpoint_artifact_root, "checkpoint artifact root")
        _exact_directory_population(
            checkpoint_artifact_root, {"checkpoints"},
            "checkpoint artifact root population")
        _directory_children_are_directories(
            checkpoint_artifact_root / "checkpoints",
            "checkpoint cohort namespace")
        expected_shards = tuple(
            _checkpoint_descriptor(
                checkpoint_artifact_root, raw, cohort=name,
                seed_block=seed_block, member_index=index,
                epoch=selected_epoch)
            for index, raw in enumerate(raws))
        expected_descriptors = tuple(item[0] for item in expected_shards)
        checkpoint_path = (checkpoint_artifact_root / "checkpoints" / name
                           / f"block-{seed_block}" / f"epoch-{selected_epoch}"
                           / "manifest.json")
        checkpoint_dir = checkpoint_path.parent
        checkpoint_block_dir = checkpoint_dir.parent
        _check_directory_chain(root, checkpoint_block_dir, "checkpoint artifact")
        if existing_cohort_manifest is None and checkpoint_block_dir.exists():
            raise ValueError("cohort/checkpoint mixed partial population")
        if checkpoint_block_dir.exists():
            expected_epoch_name = checkpoint_dir.name
            _exact_directory_population(
                checkpoint_block_dir, {expected_epoch_name},
                "checkpoint epoch population")
        _exact_directory_population(
            checkpoint_dir,
            {checkpoint_path.name, *(f"member-{index}.bin" for index in range(4))},
            "checkpoint artifact population")

        existing_shards = []
        for index, (raw, (descriptor, metadata)) in enumerate(
                zip(raws, expected_shards, strict=True)):
            target = (checkpoint_artifact_root / "checkpoints" / name
                      / f"block-{seed_block}" / f"epoch-{selected_epoch}"
                      / f"member-{index}.bin")
            existing = _existing_artifact(target, f"checkpoint shard {index}")
            if existing is None:
                existing_shards.append(False)
                continue
            if existing != raw:
                raise ValueError(f"checkpoint shard {index} byte drift")
            try:
                _model, reopened = reopen_checkpoint_shard(
                    checkpoint_artifact_root, cohort=name, seed_block=seed_block,
                    member_index=index, epoch=selected_epoch)
            except Exception as exc:
                raise ValueError(f"checkpoint shard {index} reopen refused") from exc
            if reopened != metadata:
                raise ValueError(f"checkpoint shard {index} metadata drift")
            existing_shards.append(True)

        existing_checkpoint_manifest = _existing_artifact(
            checkpoint_path, "checkpoint manifest")
        expected_checkpoint_raw = _checkpoint_manifest_bytes(expected_descriptors)
        if existing_checkpoint_manifest is not None:
            # A manifest is only acceptable once every member exists.  This
            # keeps a foreign/mixed aggregate from becoming a valid prefix.
            if not all(existing_shards):
                raise ValueError("checkpoint manifest mixed partial population")
            if existing_checkpoint_manifest != expected_checkpoint_raw:
                raise ValueError("checkpoint manifest byte drift")

        # Every refusal above occurs before any new publication.  Creation and
        # publication below therefore only fills genuinely missing slots.  A
        # missing aggregate manifest with exact existing members is the
        # expected crash-resume state.
        _ensure_directory_chain(root, manifest_path.parent, "cohort manifest")
        if existing_cohort_manifest is None:
            if _existing_artifact(manifest_path, "cohort manifest") is None:
                publish_exclusive_bytes(manifest_path, manifest_raw)
            if stable_read_bytes(manifest_path) != manifest_raw:
                raise ValueError("cohort manifest byte drift")
        _ensure_directory_chain(
            root, checkpoint_dir, "checkpoint artifact")
        shards = []
        for index, (raw, (descriptor, _metadata)) in enumerate(
                zip(raws, expected_shards, strict=True)):
            if existing_shards[index]:
                shards.append(descriptor)
                continue
            published = publish_checkpoint_shard(
                checkpoint_artifact_root, raw, cohort=name, seed_block=seed_block,
                member_index=index, epoch=selected_epoch)
            if published != descriptor:
                raise ValueError(f"checkpoint shard {index} metadata drift")
            shards.append(published)
        shards = tuple(shards)
        if existing_checkpoint_manifest is None:
            publish_checkpoint_manifest(checkpoint_artifact_root, shards)
        schedules = tuple(
            member["epoch_receipts"][selected_epoch - 1]["schedule_sha256"]
            for member in manifest["members"])
        reopened = reopen_checkpoint_manifest(
            checkpoint_artifact_root, cohort=name, seed_block=seed_block, epoch=selected_epoch,
            expected_freeze_sha256=manifest["freeze_sha256"],
            expected_config_sha256=manifest["config_sha256"],
            expected_population_sha256=manifest["training_population_sha256"],
            expected_schedule_sha256s=schedules,
            expected_common_epoch_sha256=manifest["common_epoch_sha256"])
        checkpoint_raw = stable_read_bytes(checkpoint_path)
        if len(reopened) != 4:
            raise ValueError("checkpoint aggregate digest")
        checkpoint_relative = checkpoint_path.relative_to(root).as_posix()
        checkpoint_root = checkpoint_artifact_root.relative_to(root).as_posix()
        return {
            "cohort_manifest_path": manifest_relative,
            "cohort_manifest_sha256": _sha(manifest_raw),
            "checkpoint_root": checkpoint_root,
            "checkpoint_manifest_path": checkpoint_relative,
            "checkpoint_manifest_sha256": _sha(checkpoint_raw),
            "checkpoint_shard_sha256s": [_sha(raw) for raw in raws],
        }
    except TrainingStageAdapterUnavailable:
        raise
    except Exception as exc:
        raise TrainingStageAdapterUnavailable(
            f"{name} canonical cohort artifacts refused: {exc}") from exc


def _validate_artifact_metadata(value: Mapping[str, Any]) -> None:
    required = {
        "cohort_manifest_path", "cohort_manifest_sha256", "checkpoint_root",
        "checkpoint_manifest_path", "checkpoint_manifest_sha256",
        "checkpoint_shard_sha256s",
    }
    if type(value) is not dict or set(value) != required:
        raise TrainingStageAdapterUnavailable("training cohort artifact metadata drift")
    for key in ("cohort_manifest_sha256", "checkpoint_manifest_sha256"):
        _digest(value[key], f"{key} SHA-256")
    if type(value["checkpoint_shard_sha256s"]) is not list:
        raise TrainingStageAdapterUnavailable("checkpoint shard digest population drift")
    if len(value["checkpoint_shard_sha256s"]) != 4:
        raise TrainingStageAdapterUnavailable("checkpoint shard population drift")
    for digest in value["checkpoint_shard_sha256s"]:
        _digest(digest, "checkpoint shard SHA-256")
    for key in ("cohort_manifest_path", "checkpoint_root",
                "checkpoint_manifest_path"):
        _root_file(Path("/"), value[key], key)


def _validate_cohort_artifacts(
        supervisor: Any, row: Mapping[str, Any], *, expected_name: str,
        expected_seed_block: int) -> None:
    """Reopen and authenticate one receipt's root-contained artifact set."""
    required = (
        "cohort_manifest_path", "cohort_manifest_sha256", "checkpoint_root",
        "checkpoint_manifest_path", "checkpoint_manifest_sha256",
        "checkpoint_shard_sha256s")
    if any(key not in row for key in required):
        raise TrainingStageAdapterUnavailable("training cohort artifact fields missing")
    root = supervisor.root
    manifest_path, manifest_raw = _read_root_file(
        root, row["cohort_manifest_path"], "cohort manifest")
    if _sha(manifest_raw) != row["cohort_manifest_sha256"]:
        raise TrainingStageAdapterUnavailable("cohort manifest digest drift")
    manifest = _strict_json(manifest_raw)
    try:
        validate_cohort_manifest(manifest)
    except Exception as exc:
        raise TrainingStageAdapterUnavailable("cohort manifest reopen refused") from exc
    if (manifest["cohort_name"], manifest["seed_block"]) != (
            expected_name, expected_seed_block):
        raise TrainingStageAdapterUnavailable("cohort manifest identity drift")
    if row["cohort_manifest_path"] != (
            f"cohort-manifests/{expected_name}/manifest.json"):
        raise TrainingStageAdapterUnavailable("cohort manifest path drift")
    if canonical_json_bytes(manifest) != canonical_json_bytes(row.get("manifest")):
        raise TrainingStageAdapterUnavailable("cohort manifest receipt binding drift")
    selected_epoch = manifest["common_epoch"]["selected_epoch"]
    checkpoint_root = _root_file(root, row["checkpoint_root"], "checkpoint root")
    if checkpoint_root.is_symlink() or not checkpoint_root.is_dir():
        raise TrainingStageAdapterUnavailable("checkpoint root missing")
    checkpoint_path, checkpoint_raw = _read_root_file(
        root, row["checkpoint_manifest_path"], "checkpoint manifest")
    expected_checkpoint_path = checkpoint_manifest_path(
        checkpoint_root, expected_name, expected_seed_block, selected_epoch)
    if checkpoint_path != expected_checkpoint_path:
        raise TrainingStageAdapterUnavailable("checkpoint manifest path drift")
    try:
        checkpoint_path.relative_to(checkpoint_root)
    except ValueError as exc:
        raise TrainingStageAdapterUnavailable(
            "checkpoint root binding drift") from exc
    if _sha(checkpoint_raw) != row["checkpoint_manifest_sha256"]:
        raise TrainingStageAdapterUnavailable("checkpoint manifest digest drift")
    schedules = tuple(
        member["epoch_receipts"][selected_epoch - 1]["schedule_sha256"]
        for member in manifest["members"])
    reopened = reopen_checkpoint_manifest(
        checkpoint_root, cohort=expected_name, seed_block=expected_seed_block,
        epoch=selected_epoch,
        expected_freeze_sha256=manifest["freeze_sha256"],
        expected_config_sha256=manifest["config_sha256"],
        expected_population_sha256=manifest["training_population_sha256"],
        expected_schedule_sha256s=schedules,
        expected_common_epoch_sha256=manifest["common_epoch_sha256"])
    checkpoint_value = _strict_json(checkpoint_raw)
    checkpoint_rows = checkpoint_value.get("rows")
    if (len(reopened) != 4 or type(row["checkpoint_shard_sha256s"]) is not list
            or type(checkpoint_rows) is not list
            or tuple(row["checkpoint_shard_sha256s"]) != tuple(
                item.get("sha256") for item in checkpoint_rows)):
        raise TrainingStageAdapterUnavailable("checkpoint shard digest drift")


def _reopen_receipt(supervisor: Any, stage: str) -> dict[str, Any] | None:
    try:
        shards = tuple(supervisor.verified_shards(stage))
        if "receipt" not in shards:
            return None
        path = supervisor.root / "shards" / stage / "receipt.bin"
        value = _strict_json(stable_read_bytes(path))
        receipt_sha = value.get("receipt_sha256")
        if value.get("schema") != SCHEMA or value.get("stage") != stage \
                or type(receipt_sha) is not str:
            raise TrainingStageAdapterUnavailable(
                f"{stage} sealed receipt identity drift")
        body = {key: item for key, item in value.items()
                if key != "receipt_sha256"}
        if receipt_sha != _sha(canonical_json_bytes(body)):
            raise TrainingStageAdapterUnavailable(
                f"{stage} sealed receipt digest drift")
        # Control dose is part of the immutable stage DAG.  Reopen and
        # authenticate both the typed payload and its separately named shard;
        # a caller must not be able to alter a receipt while retaining its
        # outer digest.
        evidence_rows = value.get("control_evidence", [])
        if type(evidence_rows) is not list:
            raise TrainingStageAdapterUnavailable(
                f"{stage} control evidence population drift")
        cohorts = value.get("cohorts", [])
        cohort_names = {
            row.get("name") for row in cohorts
            if type(row) is dict and type(row.get("name")) is str
        }
        if type(cohorts) is not list or len(cohort_names) != len(cohorts):
            raise TrainingStageAdapterUnavailable(
                f"{stage} cohort receipt population drift")
        if stage in ("block-1-natural", "block-1-controls", "block-2-natural",
                     "block-2-controls"):
            expected_block = 1 if stage.startswith("block-1") else 2
            for cohort in cohorts:
                if type(cohort) is not dict:
                    raise TrainingStageAdapterUnavailable(
                        f"{stage} cohort receipt row drift")
                _validate_cohort_artifacts(
                    supervisor, cohort, expected_name=cohort["name"],
                    expected_seed_block=expected_block)
        evidence_names = []
        for evidence in evidence_rows:
            try:
                validate_control_evidence(evidence)
                name = evidence["control_name"]
                if name == "natural" or name not in cohort_names:
                    raise ValueError("control evidence/cohort binding")
                evidence_names.append(name)
                shard = f"control-evidence-{name}"
                if shard not in supervisor.verified_shards(stage):
                    raise ValueError("control evidence shard missing")
                sealed = stable_read_bytes(
                    supervisor.root / "shards" / stage / f"{shard}.bin")
                if sealed != canonical_json_bytes(evidence):
                    raise ValueError("control evidence shard drift")
            except Exception as exc:
                raise TrainingStageAdapterUnavailable(
                    f"{stage} control evidence reopen refused") from exc
        if len(evidence_names) != len(set(evidence_names)):
            raise TrainingStageAdapterUnavailable(
                f"{stage} control evidence duplicate")
        expected_names = cohort_names - {"natural"}
        if set(evidence_names) != expected_names:
            raise TrainingStageAdapterUnavailable(
                f"{stage} control evidence/cohort population drift")
        return value
    except (OSError, ValueError, AttributeError) as exc:
        raise TrainingStageAdapterUnavailable(
            f"{stage} sealed receipt reopen refused") from exc


def _training_roots(values: Sequence[Any]) -> tuple[ValueInferenceRootV2, ...]:
    """Rebuild target-free roots from the already sealed training rows."""
    groups: dict[str, list[Any]] = {}
    for row in values:
        groups.setdefault(row.root_key, []).append(row)
    result = []
    # ``build_inference_root_v2`` is preferred for population material; this
    # fallback is solely the typed row-to-root projection used after inputs
    # have already authenticated every tensor and identity field.
    from .world_afterstate_v2_inference import _tensor_sha256
    from .world_afterstate_v2_model import collate_world_afterstate_tensors
    for rows in sorted(groups.values(), key=lambda group: group[0].root_key):
        rows = sorted(rows, key=lambda row: (row.candidate_index, row.replica))
        by_candidate: dict[int, Any] = {}
        for row in rows:
            by_candidate.setdefault(row.candidate_index, row)
        candidates = sorted(by_candidate)
        if candidates != list(range(len(candidates))):
            raise TrainingStageAdapterUnavailable("training root candidate numbering drift")
        first = rows[0]
        tensors = tuple(by_candidate[index].tensors for index in candidates)
        root = ValueInferenceRootV2(
            deal_sha256=first.deal_sha256, slot_sha256=first.slot_sha256,
            state_sha256=first.state_sha256,
            candidate_set_sha256=first.candidate_set_sha256,
            split=first.split, source=first.source, role=first.role,
            phase=first.phase, position=first.position, trump_rank=first.trump_rank,
            trump_mode=first.trump_mode, select_subfold=None,
            points_bucket=first.points_bucket,
            successor_sha256s=tuple(by_candidate[index].successor_sha256 for index in candidates),
            tensor_sha256s=tuple(_tensor_sha256(item) for item in tensors),
            tensors=collate_world_afterstate_tensors(tensors))
        root.validate()
        result.append(root)
    return tuple(result)


def _training_outcomes(
        values: Sequence[Any]) -> tuple[ContinuationOutcomeV2, ...]:
    """Project authenticated training examples back to typed outcome rows."""
    result = []
    for row in values:
        try:
            outcome = ContinuationOutcomeV2(
                deal_sha256=row.deal_sha256,
                slot_sha256=row.slot_sha256,
                state_sha256=row.state_sha256,
                candidate_set_sha256=row.candidate_set_sha256,
                source=row.source, split=row.split, role=row.role,
                phase=row.phase, position=row.position,
                trump_rank=row.trump_rank, trump_mode=row.trump_mode,
                points_bucket=row.points_bucket,
                candidate_index=row.candidate_index,
                protected_incumbent=row.protected_incumbent,
                successor_sha256=row.successor_sha256,
                continuation_sha256=row.continuation_sha256,
                replica=row.replica,
                signed_level_category=row.signed_level_category)
            outcome.validate()
        except Exception as exc:
            raise TrainingStageAdapterUnavailable(
                "nested curve outcome projection refused") from exc
        result.append(outcome)
    return tuple(result)


def _nested_score(
        supervisor: Any, stage: str, model: Any,
        roots: Sequence[ValueInferenceRootV2],
        outcomes: Sequence[ContinuationOutcomeV2], *, split: str,
        fraction_ppm: int, inference_batch_cap: int = 256):
    """Predict, seal, and score one actual nested-curve point."""
    try:
        predictions = predict_nested_curve_v2(
            model, roots, split=split, fraction_ppm=fraction_ppm,
            inference_batch_cap=inference_batch_cap)
        manifest = nested_curve_prediction_manifest_v2(
            roots, predictions, split=split, fraction_ppm=fraction_ppm)
        _publish(
            supervisor, stage,
            f"prediction-natural-1-{split}-{fraction_ppm}",
            canonical_json_bytes(manifest))
        return evaluate_nested_curve_v2(
            manifest, outcomes, fraction_ppm=fraction_ppm)
    except TrainingStageAdapterUnavailable:
        raise
    except Exception as exc:
        raise TrainingStageAdapterUnavailable(
            "nested curve prediction/evaluation refused") from exc


def _authenticate_prediction_manifest(
        manifest: Mapping[str, Any], models: Sequence[Any],
        roots: Sequence[ValueInferenceRootV2], *, split: str,
        control_name: str, seed_block: int) -> None:
    """Bind a reopened immutable manifest to this exact inference input set."""
    try:
        if (manifest.get("split"), manifest.get("control_name"),
                manifest.get("seed_block")) != (split, control_name, seed_block):
            raise ValueError("prediction manifest identity")
        if type(roots) not in (tuple, list) or not roots:
            raise ValueError("prediction root population")
        current_bindings = []
        for root in roots:
            if type(root) is not ValueInferenceRootV2:
                raise ValueError("prediction root type")
            root.validate()
            current_bindings.append({
                **root.target_free_body(), "root_sha256": root.root_sha256})
        current_bindings.sort(key=lambda item: item["root_sha256"])
        if (manifest.get("root_count"), manifest.get("candidate_count"),
                manifest.get("root_bindings")) != (
                    len(current_bindings),
                    sum(len(root.successor_sha256s) for root in roots),
                    current_bindings):
            raise ValueError("prediction root binding")
        if type(models) not in (tuple, list) or len(models) != 4:
            raise ValueError("prediction model population")
        expected_states = tuple(model_state_sha256(model) for model in models)
        predictions = reopen_prediction_population_manifest_v2(manifest)
        for member, expected_state in enumerate(expected_states):
            observed = {
                row.model_state_sha256 for row in predictions
                if row.member_index == member}
            if observed != {expected_state}:
                raise ValueError("prediction model state binding")
    except TrainingStageAdapterUnavailable:
        raise
    except Exception as exc:
        raise TrainingStageAdapterUnavailable(
            "prediction manifest current-input binding refused") from exc


def _prediction_receipts(
        supervisor: Any, stage: str, models: Sequence[Any], roots: Sequence[ValueInferenceRootV2],
        *, split: str, control_name: str, seed_block: int,
        nested_fraction_ppm: int | None = None,
        inference_batch_cap: int = 256) -> tuple[dict[str, Any], ...]:
    if not models or not roots:
        raise TrainingStageAdapterUnavailable("prediction population is empty")
    subfold = "epoch-select" if split == "select" else None
    artifact = None
    if nested_fraction_ppm is None:
        resumed = False
        if isinstance(getattr(supervisor, "root", None), Path):
            try:
                manifest_path = prediction_population_manifest_path(
                    supervisor.root, control_name, seed_block, split, subfold)
                # Check the full parent chain before deciding that no
                # publication exists.  This prevents a symlinked/aliased
                # namespace from being treated as a fresh run and later
                # receiving a publication.
                _check_directory_chain(
                    supervisor.root, manifest_path.parent,
                    f"{stage} prediction artifact")
                if manifest_path.is_symlink() or manifest_path.exists():
                    if manifest_path.is_symlink():
                        raise TrainingStageAdapterUnavailable(
                            f"{stage} prediction manifest symlink")
                    manifest, artifact = reopen_prediction_population_artifact(
                        supervisor.root, control_name=control_name,
                        seed_block=seed_block, split=split, subfold=subfold)
                    _authenticate_prediction_manifest(
                        manifest, models, roots, split=split,
                        control_name=control_name, seed_block=seed_block)
                    resumed = True
            except TrainingStageAdapterUnavailable:
                raise
            except Exception as exc:
                raise TrainingStageAdapterUnavailable(
                    f"{stage} prediction publication/reopen refused") from exc
        if not resumed:
            predictions = tuple(
                row for member, model in enumerate(models)
                for row in predict_roots_v2(
                    model, roots, seed_block=seed_block, member_index=member,
                    control_name=control_name,
                    inference_batch_cap=inference_batch_cap))
            manifest = prediction_population_manifest_v2(
                roots, predictions, split=split, control_name=control_name,
                seed_block=seed_block)
            try:
                artifact = publish_prediction_population_manifest(
                    supervisor.root, manifest, control_name=control_name,
                    seed_block=seed_block, split=split, subfold=subfold)
            except TrainingStageAdapterUnavailable:
                raise
            except Exception as exc:
                raise TrainingStageAdapterUnavailable(
                    f"{stage} prediction publication/reopen refused") from exc
    else:
        predictions = tuple(
            predict_nested_curve_v2(
                models[0], roots, split=split,
                fraction_ppm=nested_fraction_ppm,
                inference_batch_cap=inference_batch_cap))
        manifest = nested_curve_prediction_manifest_v2(
            roots, predictions, split=split, fraction_ppm=nested_fraction_ppm)
    # Keep a supervisor-visible receipt as well as the content-addressed
    # prediction manifest.  Reopening the shard is therefore enough to prove
    # that the prediction publication was part of this stage's immutable DAG.
    _publish(supervisor, stage,
             f"prediction-{control_name}-{seed_block}-{split}-"
             f"{nested_fraction_ppm or 0}", canonical_json_bytes(manifest))
    return ({"split": split, "control_name": control_name,
             "seed_block": seed_block,
             "fraction_ppm": nested_fraction_ppm,
             "manifest_sha256": manifest["manifest_sha256"],
             "artifact_path": (artifact.relative_path if artifact is not None else None),
             "artifact_sha256": (artifact.sha256 if artifact is not None else None)},)


def _recovery_store(supervisor: Any, stage: str, *, freeze_sha: str,
                    admission_sha: str, cohort_name: str, seed_block: int,
                    population_sha: str, selection_sha: str, config_sha: str,
                    member_count: int = 4) -> WorldAfterstateV2RecoveryStore:
    try:
        binding = RecoveryStoreBindingV2(
            freeze_sha256=freeze_sha, admission_sha256=admission_sha,
            cohort_name=cohort_name, seed_block=seed_block,
            population_sha256=population_sha,
            selection_population_sha256=selection_sha,
            config_sha256=config_sha, member_count=member_count)
        return WorldAfterstateV2RecoveryStore(
            supervisor.root / "recovery" / stage, binding=binding)
    except Exception as exc:
        raise TrainingStageAdapterUnavailable(
            f"{stage} recovery store binding refused") from exc


def _build_receipt(stage: str, build_rows: Sequence[tuple[Any, ...]],
                   prediction_rows: Sequence[Mapping[str, Any]]) -> bytes:
    cohorts = []
    checkpoints = []
    control_evidence = []
    for row in build_rows:
        if type(row) not in (tuple, list) or len(row) not in (2, 3, 4):
            raise TrainingStageAdapterUnavailable("training receipt cohort row drift")
        name, build = row[:2]
        evidence = row[2] if len(row) >= 3 else None
        artifacts = row[3] if len(row) == 4 else None
        manifest = build.manifest
        raw_checkpoints = (build.selected_checkpoint_raws
                           if hasattr(build, "selected_checkpoint_raws")
                           else (build.selected_checkpoint_raw,))
        if type(artifacts) is not dict:
            raise TrainingStageAdapterUnavailable(
                "training cohort canonical artifact metadata missing")
        _validate_artifact_metadata(artifacts)
        cohorts.append({"name": name, "manifest": manifest,
                        "checkpoint_shards": [f"checkpoint-{name}-{index}"
                                               for index in range(len(raw_checkpoints))],
                        **artifacts})
        checkpoints.extend(_sha(raw) for raw in raw_checkpoints)
        if evidence is not None:
            try:
                validate_control_evidence(evidence)
                if evidence.get("control_name") != name or name == "natural":
                    raise ValueError("control evidence/cohort binding")
            except Exception as exc:
                raise TrainingStageAdapterUnavailable(
                    "training control evidence validation refused") from exc
            control_evidence.append(dict(evidence))
    body = {"schema": SCHEMA, "stage": stage, "cohorts": cohorts,
            "checkpoint_sha256s": checkpoints,
            "predictions": [dict(item) for item in prediction_rows],
            "control_evidence": control_evidence,
            "audit_rows_opened": False, "report_rows_opened": False,
            "authority": {"training_authorized": False,
                          "audit_opening_authorized": False}}
    return canonical_json_bytes({**body, "receipt_sha256": _sha(canonical_json_bytes(body))})


@dataclass(frozen=True)
class _CohortAdapter:
    freeze: Any
    repo: Path
    stage: str
    cohort_name: str
    seed_block: int
    control_names: tuple[str, ...] = ()
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self) -> Callable[..., Any]:
        return train_named_cohort

    def _control_values(self, values: Sequence[Any], name: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        transforms = {
            "action-association-permutation": action_association_permutation,
            "label-permutation": label_permutation,
            "complete-world-shuffle": complete_world_shuffle,
        }
        try:
            controlled, evidence = transforms[name](values)
            validate_control_evidence(evidence, natural=values, controlled=controlled)
            return control_training_examples(controlled), evidence
        except Exception as exc:
            raise TrainingStageAdapterUnavailable(
                f"{self.stage} control {name} refused") from exc

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        prior = _reopen_receipt(supervisor, self.stage)
        if prior is not None:
            return prior
        expected = _EXPECTED_STAGE_COHORTS.get(self.stage)
        actual = self.control_names or ("natural",)
        if expected is None or actual != expected:
            raise TrainingStageAdapterUnavailable(
                f"{self.stage} cohort mapping drift")
        if self.stage == "block-1-natural":
            _completed(supervisor, "fit-select-labels", "optimizer-canary")
        elif self.stage == "block-1-controls":
            _completed(supervisor, "block-1-natural")
        elif self.stage == "block-2-natural":
            _completed(supervisor, "block-1-controls")
        elif self.stage == "block-2-controls":
            _completed(supervisor, "block-2-natural")
        try:
            inputs = build_training_stage_inputs(
                self.freeze, self.repo, supervisor=supervisor)
            inputs.validate()
            freeze_sha, admission_sha = _freeze_sha(self.freeze), _admission_sha(supervisor)
            values = inputs.training_examples
            natural = values
            if self.control_names:
                rows = tuple(self._control_values(values, name) for name in self.control_names)
            else:
                rows = ((values, {}),)
            builds = []
            prediction_rows = []
            for (item, evidence), name in zip(rows, self.control_names or ("natural",), strict=True):
                schedule, _ = training_epoch_batches(
                    item, epoch=1, data_order_seed=0,
                    cohort="primary" if name == "natural" else "control",
                    control_name=name, batch_example_cap=inputs.batch_example_cap)
                store = _recovery_store(
                    supervisor, f"{self.stage}-{name}", freeze_sha=freeze_sha,
                    admission_sha=admission_sha, cohort_name=name,
                    seed_block=self.seed_block, population_sha=schedule.population_sha256,
                    selection_sha=inputs.epoch_select.population_sha256,
                    config_sha=inputs.config.sha256())
                history = store.reopen_history()
                def recover(bundle: tuple[bytes, ...], *, store=store) -> None:
                    store.publish_epoch(len(store.reopen_history()) + 1, bundle)
                build = train_named_cohort(
                    cohort_name=name, values=item, natural_values=(natural if name != "natural" else None),
                    freeze_sha256=freeze_sha, config=inputs.config,
                    selection_population=inputs.epoch_select, seed_block=self.seed_block,
                    member_workers=inputs.member_workers, torch_threads=inputs.torch_threads,
                    wall_budget_nanoseconds=_budget(self.freeze, supervisor),
                    batch_example_cap=inputs.batch_example_cap,
                    progress=_progress(supervisor, self.stage),
                    recovery_history=history, recovery_callback=recover)
                artifacts = _publish_cohort_artifacts(
                    supervisor, name, self.seed_block, build)
                if evidence:
                    _publish(
                        supervisor, self.stage, f"control-evidence-{name}",
                        canonical_json_bytes(evidence))
                    builds.append((name, build, evidence, artifacts))
                else:
                    builds.append((name, build, None, artifacts))
                raw_checkpoints = (build.selected_checkpoint_raws
                                   if hasattr(build, "selected_checkpoint_raws")
                                   else (build.selected_checkpoint_raw,))
                for index, raw in enumerate(raw_checkpoints):
                    _publish(supervisor, self.stage, f"checkpoint-{name}-{index}", raw)
                models, _manifest = reopen_cohort_build(build)
                fit_roots = _training_roots(item)
                select_roots = inputs.epoch_select.roots
                prediction_rows.extend(_prediction_receipts(
                    supervisor, self.stage, models, fit_roots, split="fit",
                    control_name=name, seed_block=self.seed_block,
                    inference_batch_cap=inputs.inference_batch_cap))
                prediction_rows.extend(_prediction_receipts(
                    supervisor, self.stage, models, select_roots, split="select",
                    control_name=name, seed_block=self.seed_block,
                    inference_batch_cap=inputs.inference_batch_cap))
            raw = _build_receipt(self.stage, builds, prediction_rows)
            _publish(supervisor, self.stage, "receipt", raw)
            return _strict_json(raw)
        except TrainingStageAdapterUnavailable:
            raise
        except Exception as exc:
            raise TrainingStageAdapterUnavailable(
                f"{self.stage} training composition refused") from exc


@dataclass(frozen=True)
class NestedCurveTrainingAdapterV2:
    freeze: Any
    repo: Path
    stage: str = "nested-curve"
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self) -> Callable[..., Any]:
        return produce_nested_curve_v2

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        prior = _reopen_receipt(supervisor, self.stage)
        if prior is not None:
            return prior
        _completed(supervisor, "block-1-natural")
        try:
            freeze_sha, admission_sha = _freeze_sha(self.freeze), _admission_sha(supervisor)
            # Validate and retain the exact prior member-0 checkpoint before
            # spending any nested 25/50 work.  A missing or mismatched prior
            # stage is a refusal, never permission to retrain the 100% point.
            prior_block = _reopen_receipt(supervisor, "block-1-natural")
            if prior_block is None:
                raise TrainingStageAdapterUnavailable(
                    "nested100 requires sealed block-1-natural checkpoint")
            try:
                cohorts = prior_block["cohorts"]
                if type(cohorts) is not list or len(cohorts) != 1 \
                        or cohorts[0].get("name") != "natural":
                    raise ValueError("nested100 cohort population")
                member = cohorts[0]
                prior_sha = member["manifest"]["members"][0][
                    "selected_checkpoint_external_sha256"]
                shard_names = member["checkpoint_shards"]
                if shard_names != [f"checkpoint-natural-{index}"
                                    for index in range(4)]:
                    raise ValueError("nested100 checkpoint population")
                checkpoint_raws = tuple(stable_read_bytes(
                    supervisor.root / "shards" / "block-1-natural"
                    / f"{name}.bin") for name in shard_names)
                full_build = CohortTrainingBuildV2(
                    member["manifest"], checkpoint_raws)
                full_models, full_manifest = reopen_cohort_build(full_build)
                if (_sha(checkpoint_raws[0]) != prior_sha
                        or full_manifest["members"][0][
                            "selected_checkpoint_external_sha256"] != prior_sha):
                    raise ValueError("nested100 checkpoint digest")
            except Exception as exc:
                raise TrainingStageAdapterUnavailable(
                    "nested100 prior checkpoint reopen refused") from exc
            inputs = build_training_stage_inputs(
                self.freeze, self.repo, supervisor=supervisor)
            inputs.validate()
            prefixes = derive_nested_prefixes(inputs.training_examples)
            points: list[NestedCurveInputV2] = []
            for fraction, label in ((0.25, "nested-curve-25"), (0.5, "nested-curve-50")):
                schedule, _ = training_epoch_batches(
                    prefixes[fraction], epoch=1, data_order_seed=0,
                    cohort="primary", control_name="natural",
                    batch_example_cap=inputs.batch_example_cap)
                store = _recovery_store(
                    supervisor, label, freeze_sha=freeze_sha, admission_sha=admission_sha,
                    cohort_name="natural", seed_block=1,
                    population_sha=schedule.population_sha256,
                    selection_sha=inputs.epoch_select.population_sha256,
                    config_sha=inputs.config.sha256(), member_count=1)
                build = train_named_member(
                    values=inputs.training_examples, data_fraction=fraction,
                    member_name=label, freeze_sha256=freeze_sha, config=inputs.config,
                    selection_population=inputs.epoch_select,
                    member_workers=1, torch_threads=inputs.torch_threads,
                    wall_budget_nanoseconds=_budget(self.freeze, supervisor),
                    batch_example_cap=inputs.batch_example_cap,
                    progress=_progress(supervisor, self.stage),
                    recovery_history=store.reopen_history(),
                    recovery_callback=lambda raw, store=store: store.publish_epoch(
                        len(store.reopen_history()) + 1, raw))
                _publish(supervisor, self.stage, f"checkpoint-{label}", build.selected_checkpoint_raw)
                model, _manifest = reopen_member_build(build)
                nested_roots = _training_roots(prefixes[fraction])
                fraction_ppm = 250_000 if fraction == 0.25 else 500_000
                fit_score = _nested_score(
                    supervisor, self.stage, model, nested_roots,
                    _training_outcomes(prefixes[fraction]), split="fit",
                    fraction_ppm=fraction_ppm,
                    inference_batch_cap=inputs.inference_batch_cap)
                select_score = _nested_score(
                    supervisor, self.stage, model, inputs.epoch_select.roots,
                    inputs.epoch_select.outcomes, split="select",
                    fraction_ppm=fraction_ppm,
                    inference_batch_cap=inputs.inference_batch_cap)
                points.append(NestedCurveInputV2(
                    independent_deal_count=fit_score.deal_count,
                    fit=fit_score, select=select_score,
                    checkpoint_build=build,
                    ensemble_member_eligible=False))
            full_fit_roots = _training_roots(prefixes[1.0])
            full_fit_score = _nested_score(
                supervisor, self.stage, full_models[0], full_fit_roots,
                _training_outcomes(prefixes[1.0]), split="fit",
                fraction_ppm=1_000_000,
                inference_batch_cap=inputs.inference_batch_cap)
            full_select_score = _nested_score(
                supervisor, self.stage, full_models[0],
                inputs.epoch_select.roots, inputs.epoch_select.outcomes,
                split="select", fraction_ppm=1_000_000,
                inference_batch_cap=inputs.inference_batch_cap)
            points.append(NestedCurveInputV2(
                independent_deal_count=full_fit_score.deal_count,
                fit=full_fit_score, select=full_select_score,
                checkpoint_build=full_build,
                ensemble_member_eligible=True))
            curve = produce_nested_curve_v2(
                tuple(points),
                full_fit_population_sha256=full_fit_score.population_sha256,
                primary_member0_checkpoint_sha256=prior_sha)
            receipt = {
                "schema": SCHEMA, "stage": self.stage,
                "nested_curve": curve.payload(),
                "nested_member_checkpoint_sha256s": [
                    point.checkpoint_sha256 for point in curve.points[:2]],
                "nested100_reused_checkpoint_sha256": prior_sha,
                "cohorts": [], "control_evidence": [],
                "audit_rows_opened": False, "report_rows_opened": False,
                "authority": {"training_authorized": False,
                              "audit_opening_authorized": False}}
            raw = canonical_json_bytes({
                **receipt,
                "receipt_sha256": _sha(canonical_json_bytes(receipt))})
            _publish(supervisor, self.stage, "receipt", raw)
            return _strict_json(raw)
        except TrainingStageAdapterUnavailable:
            raise
        except Exception as exc:
            raise TrainingStageAdapterUnavailable(
                "nested curve training composition refused") from exc


def block_1_natural_adapter(*, freeze: Any, repo: Path) -> _CohortAdapter:
    return _CohortAdapter(freeze, repo, "block-1-natural", "natural", 1)


def block_1_controls_adapter(*, freeze: Any, repo: Path) -> _CohortAdapter:
    return _CohortAdapter(
        freeze, repo, "block-1-controls", "control", 1,
        ("action-association-permutation", "label-permutation",
         "complete-world-shuffle"))


def block_2_natural_adapter(*, freeze: Any, repo: Path) -> _CohortAdapter:
    return _CohortAdapter(freeze, repo, "block-2-natural", "natural", 2)


def block_2_controls_adapter(*, freeze: Any, repo: Path) -> _CohortAdapter:
    return _CohortAdapter(
        freeze, repo, "block-2-controls", "control", 2,
        ("complete-world-shuffle",))


def nested_curve_training_adapter(*, freeze: Any, repo: Path) -> NestedCurveTrainingAdapterV2:
    return NestedCurveTrainingAdapterV2(freeze, repo)


# Public names mirror the other V2 adapter module's class/factory naming and
# keep the stage ABI discoverable to execution-side importers.
Block1NaturalAdapterV2 = _CohortAdapter
Block1ControlsAdapterV2 = _CohortAdapter
Block2NaturalAdapterV2 = _CohortAdapter
Block2ControlsAdapterV2 = _CohortAdapter
Block1NaturalTrainingAdapterV2 = _CohortAdapter
Block1ControlsTrainingAdapterV2 = _CohortAdapter
Block2NaturalTrainingAdapterV2 = _CohortAdapter
Block2ControlsTrainingAdapterV2 = _CohortAdapter
NestedCurveAdapterV2 = NestedCurveTrainingAdapterV2


block1_natural_adapter = block_1_natural_adapter
block1_controls_adapter = block_1_controls_adapter
block2_natural_adapter = block_2_natural_adapter
block2_controls_adapter = block_2_controls_adapter
block_1_natural_training_adapter = block_1_natural_adapter
block_1_controls_training_adapter = block_1_controls_adapter
block_2_natural_training_adapter = block_2_natural_adapter
block_2_controls_training_adapter = block_2_controls_adapter
nested_curve_adapter = nested_curve_training_adapter
block1_natural_training_stage_adapter = block_1_natural_adapter
block1_controls_training_stage_adapter = block_1_controls_adapter
block2_natural_training_stage_adapter = block_2_natural_adapter
block2_controls_training_stage_adapter = block_2_controls_adapter
nested_curve_stage_adapter = nested_curve_training_adapter


def training_stage_adapter(stage: str, *, freeze: Any, repo: Path) -> Any:
    factories = {
        "block-1-natural": block_1_natural_adapter,
        "nested-curve": nested_curve_training_adapter,
        "block-1-controls": block_1_controls_adapter,
        "block-2-natural": block_2_natural_adapter,
        "block-2-controls": block_2_controls_adapter,
    }
    if type(stage) is not str or stage not in factories:
        raise TrainingStageAdapterUnavailable("training stage is unavailable")
    if not isinstance(repo, Path):
        raise TrainingStageAdapterUnavailable("training repository drift")
    return factories[stage](freeze=freeze, repo=repo)


production_training_stage_adapter = training_stage_adapter
production_stage_adapter = training_stage_adapter


__all__ = [
    "ABI", "SCHEMA", "TrainingStageAdapterUnavailable",
    "StageAdapterUnavailable",
    "NestedCurveTrainingAdapterV2", "block_1_natural_adapter",
    "block_1_controls_adapter", "block_2_natural_adapter",
    "block_2_controls_adapter", "nested_curve_training_adapter",
    "training_stage_adapter", "production_training_stage_adapter",
    "production_stage_adapter",
    "Block1NaturalAdapterV2", "Block1ControlsAdapterV2",
    "Block2NaturalAdapterV2", "Block2ControlsAdapterV2",
    "Block1NaturalTrainingAdapterV2", "Block1ControlsTrainingAdapterV2",
    "Block2NaturalTrainingAdapterV2", "Block2ControlsTrainingAdapterV2",
    "NestedCurveAdapterV2", "block1_natural_adapter",
    "block1_controls_adapter", "block2_natural_adapter",
    "block2_controls_adapter", "block_1_natural_training_adapter",
    "block_1_controls_training_adapter", "block_2_natural_training_adapter",
    "block_2_controls_training_adapter", "nested_curve_adapter",
    "block1_natural_training_stage_adapter",
    "block1_controls_training_stage_adapter",
    "block2_natural_training_stage_adapter",
    "block2_controls_training_stage_adapter", "nested_curve_stage_adapter",
]
