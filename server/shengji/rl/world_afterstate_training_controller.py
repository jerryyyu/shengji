"""Eight-seed cohort orchestration and immutable selected checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_checkpoint import checkpoint_bytes, reopen_checkpoint
from .world_afterstate_dataset import ReopenedDatasetRowV0
from .world_afterstate_model import CAPACITY_SHAPES, new_world_afterstate_model
from .world_afterstate_training import (
    COHORT_SIZE, WorldAfterstateCommonEpochV0,
    WorldAfterstateEpochReceiptV0, WorldAfterstateTrainingConfigV0,
    collate_training_examples, evaluate_calibration_nll_nanonats,
    model_state_sha256, new_optimizer, select_common_epoch, train_epoch)


TRAINING_MANIFEST_SCHEMA = "world-afterstate-e4-training-manifest-v0"
TRAINING_MANIFEST_NAME = "manifest.json"
TRAINING_AUTHORITY = {
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "warm_start_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateTrainingControllerError(ValueError):
    """A cohort schedule, state chain, checkpoint, or publication drifted."""


@dataclass(frozen=True)
class TrainingBuildV0:
    manifest: dict[str, Any]
    selected_checkpoint_raws: tuple[bytes, ...]


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateTrainingControllerError(f"{label} drift")
    return value


def _config(payload: Mapping[str, Any]) -> WorldAfterstateTrainingConfigV0:
    if type(payload) is not dict or set(payload) != {
            "schema", "learning_rate_ppb", "weight_decay_ppb",
            "gradient_norm_milli", "max_epochs", "early_stop_patience",
            "minimum_improvement_nanonats"}:
        raise WorldAfterstateTrainingControllerError(
            "training config payload drift")
    result = WorldAfterstateTrainingConfigV0(
        learning_rate_ppb=payload["learning_rate_ppb"],
        weight_decay_ppb=payload["weight_decay_ppb"],
        gradient_norm_milli=payload["gradient_norm_milli"],
        max_epochs=payload["max_epochs"],
        early_stop_patience=payload["early_stop_patience"],
        minimum_improvement_nanonats=payload[
            "minimum_improvement_nanonats"])
    if result.payload() != payload:
        raise WorldAfterstateTrainingControllerError(
            "training config reconstruction drift")
    return result


def _batches(
        rows: Sequence[tuple[Mapping[str, Any], ReopenedDatasetRowV0]], *,
        split: str, batch_size: int, seed: int, epoch: int) -> tuple:
    if type(rows) not in (list, tuple) or not rows \
            or isinstance(batch_size, bool) or not isinstance(batch_size, int) \
            or batch_size <= 0:
        raise WorldAfterstateTrainingControllerError(
            "training batch request drift")
    keyed = []
    for binding, reopened in rows:
        if type(binding) is not dict \
                or type(reopened) is not ReopenedDatasetRowV0 \
                or binding.get("fold") != split \
                or reopened.row_sha256 != binding.get("row_sha256"):
            raise WorldAfterstateTrainingControllerError(
                "training row binding drift")
        key = binding["external_sha256"]
        ordering = hashlib.sha256(canonical_json_bytes({
            "namespace": "world-afterstate-e4-training-order-v0",
            "seed": seed, "epoch": epoch, "row": key,
        })).hexdigest()
        keyed.append((ordering, key, reopened.example))
    keyed.sort()
    result = []
    for start in range(0, len(keyed), batch_size):
        chunk = keyed[start:start + batch_size]
        result.append(collate_training_examples(
            [row[1] for row in chunk], [row[2] for row in chunk],
            split=split))
    return tuple(result)


def train_eight_seed_cohort(
        *, freeze: Mapping[str, Any], dataset_manifest_sha256: str,
        train_rows: Sequence[tuple[Mapping[str, Any], ReopenedDatasetRowV0]],
        calibration_rows: Sequence[
            tuple[Mapping[str, Any], ReopenedDatasetRowV0]],
        wall_budget_nanoseconds: int,
        progress: Callable[[int, int, int], None] | None = None) \
        -> TrainingBuildV0:
    _digest(dataset_manifest_sha256, "training dataset manifest SHA-256")
    if type(freeze) is not dict:
        raise WorldAfterstateTrainingControllerError(
            "training freeze identity drift")
    learner = freeze.get("learner")
    freeze_sha = freeze.get("freeze_sha256")
    _digest(freeze_sha, "training freeze SHA-256")
    if type(learner) is not dict or learner.get("member_count") != COHORT_SIZE \
            or learner.get("fresh_initialization") is not True \
            or learner.get("common_epoch_selection") is not True \
            or learner.get("member_drop_allowed") is not False \
            or learner.get("shape") not in CAPACITY_SHAPES \
            or type(learner.get("initialization_seeds")) is not list \
            or len(learner["initialization_seeds"]) != COHORT_SIZE \
            or len(set(learner["initialization_seeds"])) != COHORT_SIZE:
        raise WorldAfterstateTrainingControllerError(
            "training learner identity drift")
    config = _config(learner["config"])
    if isinstance(wall_budget_nanoseconds, bool) \
            or not isinstance(wall_budget_nanoseconds, int) \
            or wall_budget_nanoseconds <= 0:
        raise WorldAfterstateTrainingControllerError(
            "training wall budget drift")
    batch_size = learner["batch_size"]
    shape_name = learner["shape"]
    seeds = tuple(learner["initialization_seeds"])
    models = [new_world_afterstate_model(seed, CAPACITY_SHAPES[shape_name])
              for seed in seeds]
    optimizers = [new_optimizer(model, config) for model in models]
    receipts: list[list[dict[str, Any]]] = [[] for _ in seeds]
    losses: list[list[int]] = [[] for _ in seeds]
    checkpoints: list[list[bytes]] = [[] for _ in seeds]
    total = config.max_epochs * COHORT_SIZE
    common = None
    started = time.monotonic_ns()
    deadline = started + wall_budget_nanoseconds
    truncated_by_deadline = False
    stop_reason = "max-epochs"
    for epoch in range(1, config.max_epochs + 1):
        # Never begin another eight-member epoch when the measured pace says
        # that the cohort cannot finish it inside the reviewed wall budget.
        # Epoch one is always allowed so a valid common checkpoint can exist.
        if epoch > 1:
            now = time.monotonic_ns()
            elapsed = now - started
            completed_epochs = epoch - 1
            projected_next_epoch = (
                elapsed + completed_epochs - 1) // completed_epochs
            if now >= deadline or deadline - now < projected_next_epoch:
                truncated_by_deadline = True
                stop_reason = "deadline-truncation"
                break
        for member, (seed, model, optimizer) in enumerate(zip(
                seeds, models, optimizers, strict=True)):
            train_batches = _batches(
                train_rows, split="train", batch_size=batch_size,
                seed=seed, epoch=epoch)
            calibration_batches = _batches(
                calibration_rows, split="calibration",
                batch_size=batch_size, seed=seed, epoch=0)
            receipt = train_epoch(
                model, optimizer, train_batches, epoch=epoch, config=config)
            loss = evaluate_calibration_nll_nanonats(
                model, calibration_batches)
            raw = checkpoint_bytes(
                model, shape_name=shape_name, init_seed=seed,
                selected_epoch=epoch, freeze_sha256=freeze_sha,
                config_sha256=config.sha256())
            receipts[member].append(receipt.payload())
            losses[member].append(loss)
            checkpoints[member].append(raw)
            if progress is not None:
                progress(epoch, (epoch - 1) * COHORT_SIZE + member + 1,
                         total)
        common = select_common_epoch(
            tuple(tuple(row) for row in losses), config=config)
        if common.stopped_for_patience:
            stop_reason = "early-stopping"
            break
        if time.monotonic_ns() >= deadline:
            truncated_by_deadline = True
            stop_reason = "deadline-truncation"
            break
    if common is None:
        raise WorldAfterstateTrainingControllerError(
            "training produced no complete common epoch")
    elapsed_nanoseconds = time.monotonic_ns() - started
    selected = common.selected_epoch - 1
    selected_raws = tuple(row[selected] for row in checkpoints)
    member_rows = []
    for member, (seed, member_receipts, member_losses, raw) in enumerate(zip(
            seeds, receipts, losses, selected_raws, strict=True)):
        model, checkpoint = reopen_checkpoint(raw)
        if checkpoint["selected_epoch"] != common.selected_epoch \
                or checkpoint["init_seed"] != seed:
            raise WorldAfterstateTrainingControllerError(
                "selected checkpoint identity drift")
        for left, right in zip(member_receipts, member_receipts[1:]):
            if left["model_state_sha256_after"] \
                    != right["model_state_sha256_before"]:
                raise WorldAfterstateTrainingControllerError(
                    "training epoch state chain drift")
        member_rows.append({
            "member_index": member, "initialization_seed": seed,
            "epoch_receipts": member_receipts,
            "epoch_receipt_sha256s": [_sha(row)
                                      for row in member_receipts],
            "calibration_loss_nanonats": member_losses,
            "selected_checkpoint_relative_path":
                f"checkpoints/member-{member:02d}.json",
            "selected_checkpoint_external_sha256": _sha_bytes(raw),
            "selected_checkpoint_sha256": checkpoint["checkpoint_sha256"],
            "selected_model_state_sha256": checkpoint["model_state_sha256"],
        })
        del model
    body = {
        "schema": TRAINING_MANIFEST_SCHEMA,
        "freeze_sha256": freeze_sha,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "shape": shape_name, "batch_size": batch_size,
        "config": config.payload(), "config_sha256": config.sha256(),
        "initialization_seeds": list(seeds),
        "member_count": COHORT_SIZE,
        "epoch_count": common.stop_epoch,
        "wall_budget_nanoseconds": wall_budget_nanoseconds,
        "elapsed_nanoseconds": elapsed_nanoseconds,
        "truncated_by_deadline": truncated_by_deadline,
        "stop_reason": stop_reason,
        "common_epoch": common.payload(),
        "common_epoch_sha256": common.sha256(),
        "members": member_rows,
        "report_rows_opened": False,
        "provider_audit_rows_opened": False,
        "authority": dict(TRAINING_AUTHORITY),
    }
    manifest = {**body, "manifest_sha256": _sha(body)}
    validate_training_manifest(manifest)
    return TrainingBuildV0(
        manifest=manifest, selected_checkpoint_raws=selected_raws)


def validate_training_manifest(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "freeze_sha256", "dataset_manifest_sha256", "shape",
        "batch_size", "config", "config_sha256", "initialization_seeds",
        "member_count", "epoch_count", "wall_budget_nanoseconds",
        "elapsed_nanoseconds", "truncated_by_deadline", "stop_reason",
        "common_epoch",
        "common_epoch_sha256", "members", "report_rows_opened",
        "provider_audit_rows_opened", "authority", "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != TRAINING_MANIFEST_SCHEMA \
            or value.get("authority") != TRAINING_AUTHORITY \
            or value.get("report_rows_opened") is not False \
            or value.get("provider_audit_rows_opened") is not False \
            or value.get("shape") not in CAPACITY_SHAPES \
            or value.get("member_count") != COHORT_SIZE:
        raise WorldAfterstateTrainingControllerError(
            "training manifest identity drift")
    for key in ("freeze_sha256", "dataset_manifest_sha256", "config_sha256",
                "common_epoch_sha256", "manifest_sha256"):
        _digest(value.get(key), key)
    config = _config(value["config"])
    members = value.get("members")
    seeds = value.get("initialization_seeds")
    epoch_count = value.get("epoch_count")
    wall_budget = value.get("wall_budget_nanoseconds")
    elapsed = value.get("elapsed_nanoseconds")
    truncated = value.get("truncated_by_deadline")
    stop_reason = value.get("stop_reason")
    common = value.get("common_epoch")
    try:
        common_receipt = WorldAfterstateCommonEpochV0(
            selected_epoch=common.get("selected_epoch"),
            stop_epoch=common.get("stop_epoch"),
            cohort_mean_loss_nanonats=tuple(
                common.get("cohort_mean_loss_nanonats", ())),
            stopped_for_patience=common.get("stopped_for_patience"),
            config_sha256=common.get("config_sha256"),
            schema=common.get("schema")) if type(common) is dict else None
    except (TypeError, ValueError) as exc:
        raise WorldAfterstateTrainingControllerError(
            "training manifest common epoch drift") from exc
    if config.sha256() != value["config_sha256"] \
            or type(seeds) is not list or len(seeds) != COHORT_SIZE \
            or len(set(seeds)) != COHORT_SIZE \
            or type(members) is not list or len(members) != COHORT_SIZE \
            or isinstance(epoch_count, bool) or not isinstance(epoch_count, int) \
            or not 1 <= epoch_count <= config.max_epochs \
            or isinstance(wall_budget, bool) \
            or not isinstance(wall_budget, int) or wall_budget <= 0 \
            or isinstance(elapsed, bool) or not isinstance(elapsed, int) \
            or elapsed < 0 or type(truncated) is not bool \
            or stop_reason not in (
                "early-stopping", "max-epochs", "deadline-truncation") \
            or type(common) is not dict \
            or common.get("stop_epoch") != epoch_count \
            or common_receipt is None \
            or common_receipt.payload() != common \
            or common_receipt.sha256() != value["common_epoch_sha256"]:
        raise WorldAfterstateTrainingControllerError(
            "training manifest cohort drift")
    if (stop_reason == "deadline-truncation") is not truncated \
            or (stop_reason == "early-stopping") \
            is not common_receipt.stopped_for_patience \
            or stop_reason == "max-epochs" \
            and epoch_count != config.max_epochs:
        raise WorldAfterstateTrainingControllerError(
            "training manifest stop reason drift")
    for index, row in enumerate(members):
        if type(row) is not dict or set(row) != {
                "member_index", "initialization_seed", "epoch_receipts",
                "epoch_receipt_sha256s", "calibration_loss_nanonats",
                "selected_checkpoint_relative_path",
                "selected_checkpoint_external_sha256",
                "selected_checkpoint_sha256",
                "selected_model_state_sha256"} \
                or row["member_index"] != index \
                or row["initialization_seed"] != seeds[index] \
                or row["selected_checkpoint_relative_path"] \
                != f"checkpoints/member-{index:02d}.json" \
                or type(row["epoch_receipts"]) is not list \
                or len(row["epoch_receipts"]) != epoch_count \
                or type(row["calibration_loss_nanonats"]) is not list \
                or len(row["calibration_loss_nanonats"]) != epoch_count \
                or row["epoch_receipt_sha256s"] \
                != [_sha(item) for item in row["epoch_receipts"]]:
            raise WorldAfterstateTrainingControllerError(
                "training manifest member drift")
        for key in ("selected_checkpoint_external_sha256",
                    "selected_checkpoint_sha256",
                    "selected_model_state_sha256"):
            _digest(row.get(key), key)
        for left, right in zip(
                row["epoch_receipts"], row["epoch_receipts"][1:]):
            if left.get("model_state_sha256_after") \
                    != right.get("model_state_sha256_before"):
                raise WorldAfterstateTrainingControllerError(
                    "training manifest state chain drift")
        receipts = []
        for epoch, payload in enumerate(row["epoch_receipts"], start=1):
            if type(payload) is not dict:
                raise WorldAfterstateTrainingControllerError(
                    "training manifest epoch receipt drift")
            try:
                receipt = WorldAfterstateEpochReceiptV0(
                    epoch=payload.get("epoch"),
                    batch_count=payload.get("batch_count"),
                    example_count=payload.get("example_count"),
                    mean_loss_nanonats=payload.get("mean_loss_nanonats"),
                    config_sha256=payload.get("config_sha256"),
                    population_sha256=payload.get("population_sha256"),
                    schedule_sha256=payload.get("schedule_sha256"),
                    model_state_sha256_before=payload.get(
                        "model_state_sha256_before"),
                    model_state_sha256_after=payload.get(
                        "model_state_sha256_after"),
                    schema=payload.get("schema"))
            except (TypeError, ValueError) as exc:
                raise WorldAfterstateTrainingControllerError(
                    "training manifest epoch receipt drift") from exc
            if receipt.payload() != payload or receipt.epoch != epoch \
                    or receipt.config_sha256 != value["config_sha256"]:
                raise WorldAfterstateTrainingControllerError(
                    "training manifest epoch receipt drift")
            receipts.append(receipt)
        initial_model = new_world_afterstate_model(
            seeds[index], CAPACITY_SHAPES[value["shape"]])
        if receipts[0].model_state_sha256_before \
                != model_state_sha256(initial_model) \
                or receipts[common_receipt.selected_epoch - 1].\
                model_state_sha256_after != row["selected_model_state_sha256"]:
            raise WorldAfterstateTrainingControllerError(
                "training manifest selected state binding drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateTrainingControllerError(
            "training manifest reconstruction drift")


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


def publish_training_build(target: Path, build: TrainingBuildV0) -> None:
    validate_training_manifest(build.manifest)
    if not isinstance(target, Path) \
            or len(build.selected_checkpoint_raws) != COHORT_SIZE:
        raise WorldAfterstateTrainingControllerError(
            "training publication request drift")
    parent = target.resolve().parent
    resolved = parent / target.name
    partial = parent / f".{target.name}.partial"
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateTrainingControllerError(
            "training publication namespace occupied")
    partial.mkdir(mode=0o700)
    try:
        selected_epoch = build.manifest["common_epoch"]["selected_epoch"]
        for row, raw in zip(
                build.manifest["members"], build.selected_checkpoint_raws,
                strict=True):
            _model, checkpoint = reopen_checkpoint(raw)
            if _sha_bytes(raw) \
                    != row["selected_checkpoint_external_sha256"] \
                    or checkpoint["checkpoint_sha256"] \
                    != row["selected_checkpoint_sha256"] \
                    or checkpoint["selected_epoch"] != selected_epoch \
                    or checkpoint["freeze_sha256"] \
                    != build.manifest["freeze_sha256"] \
                    or checkpoint["config_sha256"] \
                    != build.manifest["config_sha256"] \
                    or checkpoint["model_state_sha256"] \
                    != row["selected_model_state_sha256"]:
                raise WorldAfterstateTrainingControllerError(
                    "training publication checkpoint drift")
            _write_once(
                partial / row["selected_checkpoint_relative_path"], raw)
        _write_once(partial / TRAINING_MANIFEST_NAME,
                    canonical_json_bytes(build.manifest))
        for directory in sorted(
                (path for path in partial.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts), reverse=True):
            os.chmod(directory, 0o500)
            _fsync_directory(directory)
        _fsync_directory(partial)
        os.rename(partial, resolved)
        os.chmod(resolved, 0o500)
        _fsync_directory(resolved)
        _fsync_directory(parent)
    except BaseException:
        raise


def _sealed_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateTrainingControllerError(
            "training artifact path is a symlink")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read()
        after = os.fstat(handle.fileno())
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or before.st_size != len(raw) \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateTrainingControllerError(
            "training artifact is mutable")
    return raw


def reopen_training_build(root: Path):
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateTrainingControllerError(
            "training root identity drift")
    raw = _sealed_read(root / TRAINING_MANIFEST_NAME)
    try:
        manifest = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateTrainingControllerError(
            "training manifest is not JSON") from exc
    if canonical_json_bytes(manifest) != raw:
        raise WorldAfterstateTrainingControllerError(
            "training manifest is not canonical JSON")
    validate_training_manifest(manifest)
    models = []
    selected_epoch = manifest["common_epoch"]["selected_epoch"]
    expected = {root / TRAINING_MANIFEST_NAME}
    for row in manifest["members"]:
        path = root / row["selected_checkpoint_relative_path"]
        expected.add(path)
        checkpoint_raw = _sealed_read(path)
        model, checkpoint = reopen_checkpoint(checkpoint_raw)
        if _sha_bytes(checkpoint_raw) \
                != row["selected_checkpoint_external_sha256"] \
                or checkpoint["checkpoint_sha256"] \
                != row["selected_checkpoint_sha256"] \
                or checkpoint["model_state_sha256"] \
                != row["selected_model_state_sha256"] \
                or checkpoint["selected_epoch"] != selected_epoch \
                or checkpoint["init_seed"] != row["initialization_seed"] \
                or checkpoint["freeze_sha256"] \
                != manifest["freeze_sha256"] \
                or checkpoint["config_sha256"] \
                != manifest["config_sha256"]:
            raise WorldAfterstateTrainingControllerError(
                "training checkpoint binding drift")
        models.append(model)
    if {path for path in root.rglob("*") if path.is_file()} != expected:
        raise WorldAfterstateTrainingControllerError(
            "training file population drift")
    return manifest, tuple(models)


__all__ = [
    "TRAINING_AUTHORITY", "TRAINING_MANIFEST_SCHEMA", "TrainingBuildV0",
    "WorldAfterstateTrainingControllerError", "publish_training_build",
    "reopen_training_build", "train_eight_seed_cohort",
    "validate_training_manifest",
]
