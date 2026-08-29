"""Bounded eight-seed cohort orchestration for Value V1.

The controller runs one natural or named negative-control cohort at a time,
uses the same outcome-blind root schedule for all eight fresh seeds, selects
one common epoch, and seals a valid checkpoint set after a reviewed deadline
truncation.  It never opens audit/report outcomes and grants no run authority;
an eventual execution wrapper must authenticate the immutable freeze first.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_model import CAPACITY_SHAPES
from .world_afterstate_v1_checkpoint import (
    checkpoint_bytes, reopen_checkpoint)
from .world_afterstate_v1_controls import ControlledAdvantageV1
from .world_afterstate_v1_dataset import JoinedAdvantageV1
from .world_afterstate_v1_model import (
    new_world_afterstate_advantage_model)
from .world_afterstate_v1_schedule import (
    build_control_training_batches, build_training_batches,
    validate_schedule_receipt, validate_subsplit_manifest)
from .world_afterstate_v1_training import (
    COHORT_SIZE, SCHEDULE_SCHEMA as INTERNAL_SCHEDULE_SCHEMA,
    AdvantageCommonEpochV1, AdvantageEpochReceiptV1,
    AdvantageTrainingConfigV1, evaluate_selection_loss_nano,
    model_state_sha256, new_optimizer, select_common_epoch, train_epoch)


MANIFEST_SCHEMA = "world-afterstate-advantage-cohort-manifest-v1"
PROGRESS_SCHEMA = "world-afterstate-advantage-cohort-progress-v1"
TRAINING_COHORTS = (
    "natural", "identical-successor", "action-association-permutation",
    "label-permutation",
)
AUTHORITY = {
    "audit_opening_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1TrainingControllerError(ValueError):
    """A cohort identity, schedule, state chain, or checkpoint drifted."""


@dataclass(frozen=True)
class CohortTrainingBuildV1:
    manifest: dict[str, Any]
    selected_checkpoint_raws: tuple[bytes, ...]


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1TrainingControllerError(f"{label} drift")
    return value


def _config(payload: Mapping[str, Any]) -> AdvantageTrainingConfigV1:
    if type(payload) is not dict or set(payload) != {
            "schema", "learning_rate_ppb", "weight_decay_ppb",
            "gradient_norm_milli", "max_epochs", "early_stop_patience",
            "minimum_improvement_nanoloss"}:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort config payload drift")
    result = AdvantageTrainingConfigV1(
        learning_rate_ppb=payload["learning_rate_ppb"],
        weight_decay_ppb=payload["weight_decay_ppb"],
        gradient_norm_milli=payload["gradient_norm_milli"],
        max_epochs=payload["max_epochs"],
        early_stop_patience=payload["early_stop_patience"],
        minimum_improvement_nanoloss=payload[
            "minimum_improvement_nanoloss"],
        schema=payload["schema"])
    if result.payload() != payload:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort config reconstruction drift")
    return result


def _epoch_receipt(payload: object) -> AdvantageEpochReceiptV1:
    if type(payload) is not dict:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort epoch receipt drift")
    try:
        result = AdvantageEpochReceiptV1(
            epoch=payload.get("epoch"), batch_count=payload.get("batch_count"),
            pair_count=payload.get("pair_count"),
            root_count=payload.get("root_count"),
            mean_root_loss_nano=payload.get("mean_root_loss_nano"),
            config_sha256=payload.get("config_sha256"),
            population_sha256=payload.get("population_sha256"),
            schedule_sha256=payload.get("schedule_sha256"),
            model_state_sha256_before=payload.get(
                "model_state_sha256_before"),
            model_state_sha256_after=payload.get(
                "model_state_sha256_after"),
            schema=payload.get("schema"))
    except (TypeError, ValueError) as exc:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort epoch receipt drift") from exc
    if result.payload() != payload:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort epoch receipt reconstruction drift")
    return result


def _common_epoch(payload: object) -> AdvantageCommonEpochV1:
    if type(payload) is not dict:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort common epoch drift")
    try:
        result = AdvantageCommonEpochV1(
            selected_epoch=payload.get("selected_epoch"),
            stop_epoch=payload.get("stop_epoch"),
            cohort_mean_loss_nano=tuple(
                payload.get("cohort_mean_loss_nano", ())),
            stopped_for_patience=payload.get("stopped_for_patience"),
            config_sha256=payload.get("config_sha256"),
            schema=payload.get("schema"))
    except (TypeError, ValueError) as exc:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort common epoch drift") from exc
    if result.payload() != payload:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort common epoch reconstruction drift")
    return result


def _validated_schedule(value: object, label: str) -> None:
    try:
        validate_schedule_receipt(value)
    except ValueError as exc:
        raise WorldAfterstateV1TrainingControllerError(
            f"cohort {label} schedule drift") from exc


def _build_batches(
        cohort_name: str,
        values: Sequence[JoinedAdvantageV1 | ControlledAdvantageV1], *,
        subsplit_manifest: Mapping[str, Any], split: str,
        pair_cap: int, schedule_seed: int, epoch: int):
    if cohort_name == "natural":
        return build_training_batches(
            values, subsplit_manifest=subsplit_manifest, split=split,
            pair_cap=pair_cap, schedule_seed=schedule_seed, epoch=epoch)
    return build_control_training_batches(
        values, subsplit_manifest=subsplit_manifest, split=split,
        pair_cap=pair_cap, schedule_seed=schedule_seed, epoch=epoch)


def train_named_cohort(
        *, cohort_name: str,
        values: Sequence[JoinedAdvantageV1 | ControlledAdvantageV1],
        subsplit_manifest: Mapping[str, Any], freeze_sha256: str,
        shape_name: str, initialization_seeds: Sequence[int],
        config: AdvantageTrainingConfigV1, pair_cap: int,
        schedule_seed: int, wall_budget_nanoseconds: int,
        member_workers: int = 1,
        progress: Callable[[dict[str, Any]], None] | None = None) \
        -> CohortTrainingBuildV1:
    """Train and seal one complete natural/control cohort in memory."""
    validate_subsplit_manifest(subsplit_manifest)
    _digest(freeze_sha256, "cohort freeze SHA-256")
    config.validate()
    if cohort_name not in TRAINING_COHORTS or shape_name not in CAPACITY_SHAPES \
            or type(values) not in (list, tuple) or not values \
            or type(initialization_seeds) not in (list, tuple) \
            or len(initialization_seeds) != COHORT_SIZE \
            or len(set(initialization_seeds)) != COHORT_SIZE \
            or any(isinstance(seed, bool) or not isinstance(seed, int)
                   or not 0 <= seed < 2**63 for seed in initialization_seeds) \
            or isinstance(pair_cap, bool) or not isinstance(pair_cap, int) \
            or pair_cap <= 0 \
            or isinstance(schedule_seed, bool) \
            or not isinstance(schedule_seed, int) \
            or not 0 <= schedule_seed < 2**63 \
            or isinstance(wall_budget_nanoseconds, bool) \
            or not isinstance(wall_budget_nanoseconds, int) \
            or wall_budget_nanoseconds <= 0 \
            or isinstance(member_workers, bool) \
            or not isinstance(member_workers, int) \
            or not 1 <= member_workers <= COHORT_SIZE:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort request drift")
    expected_type = (JoinedAdvantageV1 if cohort_name == "natural"
                     else ControlledAdvantageV1)
    if any(type(value) is not expected_type for value in values) \
            or cohort_name != "natural" and any(
                value.control_name != cohort_name for value in values):
        raise WorldAfterstateV1TrainingControllerError(
            "cohort source population drift")
    seeds = tuple(initialization_seeds)
    models = [new_world_afterstate_advantage_model(
        seed, CAPACITY_SHAPES[shape_name]) for seed in seeds]
    optimizers = [new_optimizer(model, config) for model in models]
    receipts: list[list[dict[str, Any]]] = [[] for _ in seeds]
    losses: list[list[int]] = [[] for _ in seeds]
    snapshots: list[list[dict[str, Any]]] = [[] for _ in seeds]
    fit_schedules = []
    select_batches, select_schedule = _build_batches(
        cohort_name, values, subsplit_manifest=subsplit_manifest,
        split="select", pair_cap=pair_cap, schedule_seed=schedule_seed,
        epoch=1)
    _validated_schedule(select_schedule, "select")
    started = time.monotonic_ns()
    deadline = started + wall_budget_nanoseconds
    common = None
    truncated = False
    stop_reason = "max-epochs"
    last_now = started
    for epoch in range(1, config.max_epochs + 1):
        fit_batches, fit_schedule = _build_batches(
            cohort_name, values, subsplit_manifest=subsplit_manifest,
            split="fit", pair_cap=pair_cap, schedule_seed=schedule_seed,
            epoch=epoch)
        _validated_schedule(fit_schedule, "fit")
        fit_schedules.append(fit_schedule)
        def run_member(member):
            model = models[member]
            receipt = train_epoch(
                model, optimizers[member], fit_batches,
                epoch=epoch, config=config)
            loss = evaluate_selection_loss_nano(model, select_batches)
            return receipt.payload(), loss, copy.deepcopy(model.state_dict())

        if member_workers == 1:
            member_results = [run_member(member)
                              for member in range(COHORT_SIZE)]
        else:
            with ThreadPoolExecutor(max_workers=member_workers) as executor:
                futures = [executor.submit(run_member, member)
                           for member in range(COHORT_SIZE)]
                member_results = [future.result() for future in futures]
        for member, (receipt, loss, snapshot) in enumerate(member_results):
            receipts[member].append(receipt)
            losses[member].append(loss)
            snapshots[member].append(snapshot)
        common = select_common_epoch(
            tuple(tuple(row) for row in losses), config=config)
        last_now = time.monotonic_ns()
        completed = epoch * COHORT_SIZE
        total = config.max_epochs * COHORT_SIZE
        elapsed = last_now - started
        if progress is not None:
            remaining = max(total - completed, 0)
            eta = (elapsed * remaining + completed - 1) // completed
            progress({
                "schema": PROGRESS_SCHEMA, "cohort_name": cohort_name,
                "epoch": epoch, "completed_units": completed,
                "total_units": total,
                "percent_basis_points": completed * 10_000 // total,
                "elapsed_nanoseconds": elapsed,
                "estimated_remaining_nanoseconds": eta,
                "audit_rows_opened": False, "report_rows_opened": False,
                "authority": dict(AUTHORITY),
            })
        if common.stopped_for_patience:
            stop_reason = "early-stopping"
            break
        if epoch == config.max_epochs:
            break
        projected_next_epoch = (elapsed + epoch - 1) // epoch
        if last_now >= deadline or deadline - last_now < projected_next_epoch:
            truncated = True
            stop_reason = "deadline-truncation"
            break
    if common is None:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort produced no complete common epoch")
    population_shas = {
        receipt["population_sha256"]
        for member in receipts for receipt in member
    }
    if len(population_shas) != 1:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort training population drift")
    population_sha = next(iter(population_shas))
    selected_index = common.selected_epoch - 1
    common_sha = common.sha256()
    checkpoint_raws = []
    member_rows = []
    for member, (seed, model) in enumerate(zip(seeds, models, strict=True)):
        model.load_state_dict(snapshots[member][selected_index])
        raw = checkpoint_bytes(
            model, shape_name=shape_name, member_index=member,
            init_seed=seed, selected_epoch=common.selected_epoch,
            freeze_sha256=freeze_sha256, config_sha256=config.sha256(),
            subsplit_manifest_sha256=subsplit_manifest["manifest_sha256"],
            training_population_sha256=population_sha,
            common_epoch_sha256=common_sha)
        _reopened, metadata = reopen_checkpoint(raw)
        checkpoint_raws.append(raw)
        member_rows.append({
            "member_index": member, "initialization_seed": seed,
            "epoch_receipts": receipts[member],
            "selection_loss_nano": losses[member],
            "selected_checkpoint_external_sha256": _sha_bytes(raw),
            "selected_checkpoint_sha256": metadata["checkpoint_sha256"],
            "selected_model_state_sha256": metadata["model_state_sha256"],
        })
    body = {
        "schema": MANIFEST_SCHEMA, "cohort_name": cohort_name,
        "control_population": cohort_name != "natural",
        "freeze_sha256": freeze_sha256,
        "subsplit_manifest_sha256": subsplit_manifest["manifest_sha256"],
        "shape_name": shape_name, "config": config.payload(),
        "config_sha256": config.sha256(),
        "initialization_seeds": list(seeds), "member_count": COHORT_SIZE,
        "member_workers": member_workers,
        "pair_cap": pair_cap, "schedule_seed": schedule_seed,
        "epoch_count": common.stop_epoch,
        "fit_schedule_receipts": fit_schedules,
        "select_schedule_receipt": select_schedule,
        "training_population_sha256": population_sha,
        "wall_budget_nanoseconds": wall_budget_nanoseconds,
        "elapsed_nanoseconds": last_now - started,
        "truncated_by_deadline": truncated, "stop_reason": stop_reason,
        "common_epoch": common.payload(),
        "common_epoch_sha256": common_sha, "members": member_rows,
        "audit_rows_opened": False, "report_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    manifest = {**body, "manifest_sha256": _sha(body)}
    validate_cohort_manifest(manifest)
    return CohortTrainingBuildV1(
        manifest=manifest,
        selected_checkpoint_raws=tuple(checkpoint_raws))


def validate_cohort_manifest(value: object) -> None:
    required = {
        "schema", "cohort_name", "control_population", "freeze_sha256",
        "subsplit_manifest_sha256", "shape_name", "config",
        "config_sha256", "initialization_seeds", "member_count",
        "member_workers",
        "pair_cap", "schedule_seed", "epoch_count",
        "fit_schedule_receipts", "select_schedule_receipt",
        "training_population_sha256", "wall_budget_nanoseconds",
        "elapsed_nanoseconds", "truncated_by_deadline", "stop_reason",
        "common_epoch", "common_epoch_sha256", "members",
        "audit_rows_opened", "report_rows_opened", "authority",
        "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != MANIFEST_SCHEMA \
            or value.get("cohort_name") not in TRAINING_COHORTS \
            or value.get("control_population") \
            is not (value.get("cohort_name") != "natural") \
            or value.get("shape_name") not in CAPACITY_SHAPES \
            or value.get("member_count") != COHORT_SIZE \
            or isinstance(value.get("member_workers"), bool) \
            or not isinstance(value.get("member_workers"), int) \
            or not 1 <= value["member_workers"] <= COHORT_SIZE \
            or value.get("audit_rows_opened") is not False \
            or value.get("report_rows_opened") is not False \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort manifest identity drift")
    for key in (
            "freeze_sha256", "subsplit_manifest_sha256", "config_sha256",
            "training_population_sha256", "common_epoch_sha256",
            "manifest_sha256"):
        _digest(value.get(key), f"cohort {key}")
    config = _config(value.get("config"))
    common = _common_epoch(value.get("common_epoch"))
    seeds = value.get("initialization_seeds")
    members = value.get("members")
    schedules = value.get("fit_schedule_receipts")
    integers = (
        "pair_cap", "schedule_seed", "epoch_count",
        "wall_budget_nanoseconds", "elapsed_nanoseconds",
    )
    if config.sha256() != value["config_sha256"] \
            or common.config_sha256 != value["config_sha256"] \
            or common.sha256() != value["common_epoch_sha256"] \
            or common.stop_epoch != value.get("epoch_count") \
            or type(seeds) is not list or len(seeds) != COHORT_SIZE \
            or len(set(seeds)) != COHORT_SIZE \
            or any(isinstance(seed, bool) or not isinstance(seed, int)
                   or not 0 <= seed < 2**63 for seed in seeds) \
            or type(members) is not list or len(members) != COHORT_SIZE \
            or type(schedules) is not list \
            or len(schedules) != common.stop_epoch \
            or any(isinstance(value.get(key), bool)
                   or not isinstance(value.get(key), int) for key in integers) \
            or value["pair_cap"] <= 0 \
            or not 0 <= value["schedule_seed"] < 2**63 \
            or value["epoch_count"] <= 0 \
            or value["wall_budget_nanoseconds"] <= 0 \
            or value["elapsed_nanoseconds"] < 0 \
            or type(value.get("truncated_by_deadline")) is not bool \
            or value.get("stop_reason") not in (
                "early-stopping", "max-epochs", "deadline-truncation"):
        raise WorldAfterstateV1TrainingControllerError(
            "cohort manifest population drift")
    truncated = value["truncated_by_deadline"]
    reason = value["stop_reason"]
    if (reason == "deadline-truncation") is not truncated \
            or (reason == "early-stopping") \
            is not common.stopped_for_patience \
            or reason == "max-epochs" \
            and common.stop_epoch != config.max_epochs:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort manifest stop-reason drift")
    for epoch, schedule in enumerate(schedules, start=1):
        _validated_schedule(schedule, "fit")
        if schedule["split"] != "fit" or schedule["epoch"] != epoch \
                or schedule["pair_cap"] != value["pair_cap"] \
                or schedule["schedule_seed"] != value["schedule_seed"] \
                or schedule["subsplit_manifest_sha256"] \
                != value["subsplit_manifest_sha256"]:
            raise WorldAfterstateV1TrainingControllerError(
                "cohort fit schedule binding drift")
    select_schedule = value.get("select_schedule_receipt")
    _validated_schedule(select_schedule, "select")
    if select_schedule["split"] != "select" \
            or select_schedule["epoch"] != 1 \
            or select_schedule["pair_cap"] != value["pair_cap"] \
            or select_schedule["schedule_seed"] != value["schedule_seed"] \
            or select_schedule["subsplit_manifest_sha256"] \
            != value["subsplit_manifest_sha256"]:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort select schedule binding drift")
    selection_losses = []
    for member, row in enumerate(members):
        if type(row) is not dict or set(row) != {
                "member_index", "initialization_seed", "epoch_receipts",
                "selection_loss_nano",
                "selected_checkpoint_external_sha256",
                "selected_checkpoint_sha256",
                "selected_model_state_sha256"} \
                or row.get("member_index") != member \
                or row.get("initialization_seed") != seeds[member] \
                or type(row.get("epoch_receipts")) is not list \
                or len(row["epoch_receipts"]) != common.stop_epoch \
                or type(row.get("selection_loss_nano")) is not list \
                or len(row["selection_loss_nano"]) != common.stop_epoch \
                or any(isinstance(loss, bool) or not isinstance(loss, int)
                       or loss < 0 for loss in row["selection_loss_nano"]):
            raise WorldAfterstateV1TrainingControllerError(
                "cohort manifest member drift")
        for key in (
                "selected_checkpoint_external_sha256",
                "selected_checkpoint_sha256", "selected_model_state_sha256"):
            _digest(row.get(key), f"cohort member {key}")
        parsed = [_epoch_receipt(payload)
                  for payload in row["epoch_receipts"]]
        selection_losses.append(tuple(row["selection_loss_nano"]))
        initial = new_world_afterstate_advantage_model(
            seeds[member], CAPACITY_SHAPES[value["shape_name"]])
        if parsed[0].model_state_sha256_before != model_state_sha256(initial) \
                or any(receipt.epoch != epoch
                       or receipt.config_sha256 != value["config_sha256"]
                       or receipt.population_sha256
                       != value["training_population_sha256"]
                       or receipt.schedule_sha256 != _sha({
                           "schema": INTERNAL_SCHEDULE_SCHEMA,
                           "epoch": epoch,
                           "batch_pair_keys": schedules[
                               epoch - 1]["batch_pair_keys"],
                       }) for epoch, receipt in enumerate(parsed, start=1)) \
                or any(left.model_state_sha256_after
                       != right.model_state_sha256_before
                       for left, right in zip(parsed, parsed[1:])):
            raise WorldAfterstateV1TrainingControllerError(
                "cohort manifest state/schedule chain drift")
    rederived_common = select_common_epoch(
        tuple(selection_losses), config=config)
    if rederived_common.payload() != common.payload():
        raise WorldAfterstateV1TrainingControllerError(
            "cohort common epoch selection drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV1TrainingControllerError(
            "cohort manifest reconstruction drift")


def reopen_cohort_build(value: CohortTrainingBuildV1) \
        -> tuple[tuple[Any, ...], dict[str, Any]]:
    if type(value) is not CohortTrainingBuildV1:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort build type drift")
    validate_cohort_manifest(value.manifest)
    if type(value.selected_checkpoint_raws) is not tuple \
            or len(value.selected_checkpoint_raws) != COHORT_SIZE:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort checkpoint population drift")
    models = []
    for member, (raw, row) in enumerate(zip(
            value.selected_checkpoint_raws, value.manifest["members"],
            strict=True)):
        if type(raw) is not bytes \
                or _sha_bytes(raw) \
                != row["selected_checkpoint_external_sha256"]:
            raise WorldAfterstateV1TrainingControllerError(
                "cohort checkpoint external binding drift")
        model, metadata = reopen_checkpoint(raw)
        if metadata["member_index"] != member \
                or metadata["init_seed"] \
                != value.manifest["initialization_seeds"][member] \
                or metadata["selected_epoch"] \
                != value.manifest["common_epoch"]["selected_epoch"] \
                or metadata["freeze_sha256"] \
                != value.manifest["freeze_sha256"] \
                or metadata["config_sha256"] \
                != value.manifest["config_sha256"] \
                or metadata["subsplit_manifest_sha256"] \
                != value.manifest["subsplit_manifest_sha256"] \
                or metadata["training_population_sha256"] \
                != value.manifest["training_population_sha256"] \
                or metadata["common_epoch_sha256"] \
                != value.manifest["common_epoch_sha256"] \
                or metadata["checkpoint_sha256"] \
                != row["selected_checkpoint_sha256"] \
                or metadata["model_state_sha256"] \
                != row["selected_model_state_sha256"]:
            raise WorldAfterstateV1TrainingControllerError(
                "cohort checkpoint metadata binding drift")
        selected = value.manifest["common_epoch"]["selected_epoch"] - 1
        if row["epoch_receipts"][selected]["model_state_sha256_after"] \
                != metadata["model_state_sha256"]:
            raise WorldAfterstateV1TrainingControllerError(
                "cohort selected state binding drift")
        models.append(model)
    return tuple(models), value.manifest


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


def publish_cohort_build(target: Path, build: CohortTrainingBuildV1) -> None:
    """Publish one immutable cohort directory without overwriting a slot."""
    _models, manifest = reopen_cohort_build(build)
    if not isinstance(target, Path):
        raise WorldAfterstateV1TrainingControllerError(
            "cohort publication target drift")
    parent = target.resolve().parent
    resolved = parent / target.name
    partial = parent / f".{target.name}.partial"
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateV1TrainingControllerError(
            "cohort publication namespace occupied")
    partial.mkdir(mode=0o700)
    for member, raw in enumerate(build.selected_checkpoint_raws):
        _write_once(partial / "checkpoints" / f"member-{member:02d}.json",
                    raw)
    _write_once(partial / "manifest.json", canonical_json_bytes(manifest))
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


def _sealed_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateV1TrainingControllerError(
            "cohort artifact path is a symlink")
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
        raise WorldAfterstateV1TrainingControllerError(
            "cohort artifact is mutable")
    return raw


def reopen_cohort_directory(root: Path) \
        -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Reopen the exact immutable file population and every checkpoint."""
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateV1TrainingControllerError(
            "cohort root identity drift")
    manifest_raw = _sealed_read(root / "manifest.json")
    try:
        manifest = json.loads(manifest_raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort manifest is not JSON") from exc
    if canonical_json_bytes(manifest) != manifest_raw:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort manifest is not canonical JSON")
    checkpoint_raws = tuple(_sealed_read(
        root / "checkpoints" / f"member-{member:02d}.json")
        for member in range(COHORT_SIZE))
    expected = {root / "manifest.json"} | {
        root / "checkpoints" / f"member-{member:02d}.json"
        for member in range(COHORT_SIZE)
    }
    if {path for path in root.rglob("*") if path.is_file()} != expected:
        raise WorldAfterstateV1TrainingControllerError(
            "cohort file population drift")
    return reopen_cohort_build(CohortTrainingBuildV1(
        manifest=manifest, selected_checkpoint_raws=checkpoint_raws))


__all__ = [
    "AUTHORITY", "CohortTrainingBuildV1", "TRAINING_COHORTS",
    "WorldAfterstateV1TrainingControllerError", "publish_cohort_build",
    "reopen_cohort_build", "reopen_cohort_directory", "train_named_cohort",
    "validate_cohort_manifest",
]
