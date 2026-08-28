"""Deterministic, non-launching mechanics for ``V_world_after`` training.

This module consumes only already-authenticated examples and explicit split
labels.  It owns one CPU-float32 AdamW epoch, calibration loss evaluation,
state hashing, and one common-epoch decision across an eight-member cohort.
It does not select a population, read or write artifacts, generate outcomes,
open a report/test split, choose hyperparameters, or authorize execution.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import (OUTCOME_CLASSES, WorldAfterstateError,
                               WorldAfterstateExampleV0)
from .world_afterstate_model import (
    WorldAfterstateValueV0, collate_world_afterstates,
    distributional_value_loss, proper_score_rows)


BATCH_SCHEMA = "world-afterstate-training-batch-v0"
CONFIG_SCHEMA = "world-afterstate-training-config-v0"
EPOCH_RECEIPT_SCHEMA = "world-afterstate-training-epoch-receipt-v0"
STATE_SCHEMA = "world-afterstate-value-state-v0"
POPULATION_SCHEMA = "world-afterstate-training-population-v0"
SCHEDULE_SCHEMA = "world-afterstate-training-schedule-v0"
COMMON_EPOCH_SCHEMA = "world-afterstate-common-epoch-v0"
LOSS_SCALE = 1_000_000_000
COHORT_SIZE = 8
TRAINING_AUTHORITY = {
    "population_generation_authorized": False,
    "continuation_authorized": False,
    "training_execution_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateTrainingError(WorldAfterstateError):
    """A batch, optimizer, epoch, calibration score, or state drifted."""


def _sha(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class WorldAfterstateTrainingConfigV0:
    """Explicit mechanics values; a later reviewed design must freeze them."""

    learning_rate_ppb: int
    weight_decay_ppb: int
    gradient_norm_milli: int
    max_epochs: int
    early_stop_patience: int
    minimum_improvement_nanonats: int
    schema: str = CONFIG_SCHEMA

    def validate(self) -> None:
        values = (
            self.learning_rate_ppb, self.weight_decay_ppb,
            self.gradient_norm_milli, self.max_epochs,
            self.early_stop_patience,
            self.minimum_improvement_nanonats,
        )
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in values) \
                or not 1 <= self.learning_rate_ppb <= 1_000_000_000 \
                or not 0 <= self.weight_decay_ppb <= 1_000_000_000 \
                or not 1 <= self.gradient_norm_milli <= 1_000_000 \
                or not 1 <= self.max_epochs <= 10_000 \
                or not 1 <= self.early_stop_patience <= self.max_epochs \
                or not 0 <= self.minimum_improvement_nanonats <= LOSS_SCALE:
            raise WorldAfterstateTrainingError(
                "world-afterstate training config drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "learning_rate_ppb": self.learning_rate_ppb,
            "weight_decay_ppb": self.weight_decay_ppb,
            "gradient_norm_milli": self.gradient_norm_milli,
            "max_epochs": self.max_epochs,
            "early_stop_patience": self.early_stop_patience,
            "minimum_improvement_nanonats":
                self.minimum_improvement_nanonats,
        }

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class WorldAfterstateTrainingBatchV0:
    example_keys: tuple[str, ...]
    successor_sha256s: tuple[str, ...]
    split: str
    public: torch.Tensor
    history: torch.Tensor
    history_lengths: torch.Tensor
    world: torch.Tensor
    perspective: torch.Tensor
    labels: torch.Tensor
    schema: str = BATCH_SCHEMA

    def validate(self) -> None:
        batch = len(self.example_keys)
        if self.schema != BATCH_SCHEMA or batch <= 0 \
                or type(self.example_keys) is not tuple \
                or any(type(key) is not str or not key or not key.isascii()
                       for key in self.example_keys) \
                or len(set(self.example_keys)) != batch \
                or type(self.successor_sha256s) is not tuple \
                or len(self.successor_sha256s) != batch \
                or any(type(value) is not str or len(value) != 64
                       or any(char not in "0123456789abcdef" for char in value)
                       for value in self.successor_sha256s) \
                or self.split not in (
                    "train", "calibration", "report", "provider-audit"):
            raise WorldAfterstateTrainingError(
                "world-afterstate training batch identity drift")
        if self.public.device.type != "cpu" \
                or self.history.device.type != "cpu" \
                or self.history_lengths.device.type != "cpu" \
                or self.world.device.type != "cpu" \
                or self.perspective.device.type != "cpu" \
                or self.labels.device.type != "cpu":
            raise WorldAfterstateTrainingError(
                "world-afterstate training batch device drift")
        if self.public.shape[0] != batch \
                or self.history.shape[0] != batch \
                or self.history_lengths.shape != (batch,) \
                or self.world.shape[0] != batch \
                or self.perspective.shape[0] != batch \
                or self.labels.shape != (batch,) \
                or self.labels.dtype != torch.long \
                or bool(torch.any(self.labels < 0)) \
                or bool(torch.any(self.labels >= OUTCOME_CLASSES)):
            raise WorldAfterstateTrainingError(
                "world-afterstate training batch tensor drift")


def collate_training_examples(
        example_keys: Sequence[str],
        examples: Sequence[WorldAfterstateExampleV0], *, split: str) \
        -> WorldAfterstateTrainingBatchV0:
    if type(example_keys) not in (list, tuple) \
            or type(examples) not in (list, tuple) \
            or not examples or len(example_keys) != len(examples) \
            or any(type(example) is not WorldAfterstateExampleV0
                   for example in examples):
        raise WorldAfterstateTrainingError(
            "world-afterstate example population drift")
    for example in examples:
        example.validate()
    public, history, lengths, world, perspective, labels = \
        collate_world_afterstates(examples)
    batch = WorldAfterstateTrainingBatchV0(
        example_keys=tuple(example_keys),
        successor_sha256s=tuple(
            example.successor_sha256 for example in examples),
        split=split, public=public, history=history,
        history_lengths=lengths, world=world, perspective=perspective,
        labels=labels)
    batch.validate()
    return batch


def model_state_sha256(model: WorldAfterstateValueV0) -> str:
    """Hash ordered little-endian CPU float32 state bytes."""
    if type(model) is not WorldAfterstateValueV0 \
            or any(parameter.device.type != "cpu"
                   or parameter.dtype != torch.float32
                   for parameter in model.parameters()):
        raise WorldAfterstateTrainingError(
            "world-afterstate model state device/dtype drift")
    digest = hashlib.sha256(canonical_json_bytes({
        "schema": STATE_SCHEMA,
        "parameter_names": [name for name, _ in model.named_parameters()],
    }))
    for name, parameter in model.named_parameters():
        array = parameter.detach().contiguous().numpy().astype("<f4", copy=False)
        raw = array.tobytes(order="C")
        header = canonical_json_bytes({
            "name": name, "shape": list(array.shape),
            "dtype": "little-endian-float32", "byte_count": len(raw),
        })
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def new_optimizer(
        model: WorldAfterstateValueV0,
        config: WorldAfterstateTrainingConfigV0) -> torch.optim.AdamW:
    config.validate()
    _ = model_state_sha256(model)
    return torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate_ppb / LOSS_SCALE,
        weight_decay=config.weight_decay_ppb / LOSS_SCALE,
        foreach=False, fused=False)


def _validate_optimizer(
        model: WorldAfterstateValueV0, optimizer: torch.optim.Optimizer,
        config: WorldAfterstateTrainingConfigV0) -> None:
    config.validate()
    if type(optimizer) is not torch.optim.AdamW \
            or len(optimizer.param_groups) != 1:
        raise WorldAfterstateTrainingError(
            "world-afterstate optimizer identity drift")
    group = optimizer.param_groups[0]
    if group["lr"] != config.learning_rate_ppb / LOSS_SCALE \
            or group["weight_decay"] != config.weight_decay_ppb / LOSS_SCALE \
            or group["foreach"] is not False or group["fused"] is not False \
            or len(group["params"]) != len(tuple(model.parameters())) \
            or any(left is not right for left, right in zip(
                group["params"], model.parameters(), strict=True)):
        raise WorldAfterstateTrainingError(
            "world-afterstate optimizer configuration drift")


def _batch_bindings(
        batches: tuple[WorldAfterstateTrainingBatchV0, ...], *, epoch: int,
        required_split: str) -> tuple[str, str, int]:
    if type(epoch) is not int or epoch <= 0 \
            or type(batches) is not tuple or not batches \
            or any(type(batch) is not WorldAfterstateTrainingBatchV0
                   for batch in batches):
        raise WorldAfterstateTrainingError(
            "world-afterstate epoch batch population drift")
    keys: list[str] = []
    successor_rows: list[dict[str, str]] = []
    schedule: list[list[str]] = []
    for batch in batches:
        batch.validate()
        if batch.split != required_split:
            raise WorldAfterstateTrainingError(
                "world-afterstate epoch split drift")
        keys.extend(batch.example_keys)
        successor_rows.extend({"key": key, "successor_sha256": successor}
                              for key, successor in zip(
                                  batch.example_keys,
                                  batch.successor_sha256s, strict=True))
        schedule.append(list(batch.example_keys))
    if len(keys) != len(set(keys)):
        raise WorldAfterstateTrainingError(
            "world-afterstate epoch duplicate example")
    population_sha = _sha({
        "schema": POPULATION_SCHEMA,
        "example_count": len(keys),
        "examples": sorted(successor_rows, key=lambda row: row["key"]),
    })
    schedule_sha = _sha({
        "schema": SCHEDULE_SCHEMA, "epoch": epoch,
        "batch_example_keys": schedule,
    })
    return population_sha, schedule_sha, len(keys)


@dataclass(frozen=True)
class WorldAfterstateEpochReceiptV0:
    epoch: int
    batch_count: int
    example_count: int
    mean_loss_nanonats: int
    config_sha256: str
    population_sha256: str
    schedule_sha256: str
    model_state_sha256_before: str
    model_state_sha256_after: str
    schema: str = EPOCH_RECEIPT_SCHEMA

    def validate(self) -> None:
        integer_fields = (
            self.epoch, self.batch_count, self.example_count,
            self.mean_loss_nanonats,
        )
        digests = (
            self.config_sha256, self.population_sha256,
            self.schedule_sha256, self.model_state_sha256_before,
            self.model_state_sha256_after,
        )
        if self.schema != EPOCH_RECEIPT_SCHEMA \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       for value in integer_fields) \
                or self.epoch <= 0 or self.batch_count <= 0 \
                or self.example_count <= 0 or self.mean_loss_nanonats < 0 \
                or any(type(value) is not str or len(value) != 64
                       or any(char not in "0123456789abcdef" for char in value)
                       for value in digests) \
                or self.model_state_sha256_before \
                == self.model_state_sha256_after:
            raise WorldAfterstateTrainingError(
                "world-afterstate epoch receipt drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema, "epoch": self.epoch,
            "batch_count": self.batch_count,
            "example_count": self.example_count,
            "mean_loss_nanonats": self.mean_loss_nanonats,
            "config_sha256": self.config_sha256,
            "population_sha256": self.population_sha256,
            "schedule_sha256": self.schedule_sha256,
            "model_state_sha256_before": self.model_state_sha256_before,
            "model_state_sha256_after": self.model_state_sha256_after,
            "privileged_outcomes_consumed": True,
            "checkpoint_written": False,
            "runtime_artifact": False,
            "authority": dict(TRAINING_AUTHORITY),
        }

    def sha256(self) -> str:
        return _sha(self.payload())


def train_epoch(
        model: WorldAfterstateValueV0, optimizer: torch.optim.Optimizer,
        batches: tuple[WorldAfterstateTrainingBatchV0, ...], *, epoch: int,
        config: WorldAfterstateTrainingConfigV0) \
        -> WorldAfterstateEpochReceiptV0:
    if not 1 <= epoch <= config.max_epochs:
        raise WorldAfterstateTrainingError(
            "world-afterstate training epoch drift")
    _validate_optimizer(model, optimizer, config)
    population_sha, schedule_sha, count = _batch_bindings(
        batches, epoch=epoch, required_split="train")
    before = model_state_sha256(model)
    model.train(True)
    loss_sum = 0.0
    for batch in batches:
        optimizer.zero_grad(set_to_none=True)
        logits = model(
            batch.public, batch.history, batch.history_lengths,
            batch.world, batch.perspective)
        loss = distributional_value_loss(logits, batch.labels)
        if loss.ndim != 0 or not bool(torch.isfinite(loss)):
            raise WorldAfterstateTrainingError(
                "world-afterstate training loss drift")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), config.gradient_norm_milli / 1000,
            error_if_nonfinite=True)
        if not bool(torch.isfinite(norm)):
            raise WorldAfterstateTrainingError(
                "world-afterstate training gradient drift")
        optimizer.step()
        loss_sum += float(loss.detach()) * len(batch.example_keys)
    mean_loss = round(loss_sum / count * LOSS_SCALE)
    if type(mean_loss) is not int or mean_loss < 0 \
            or not math.isfinite(loss_sum):
        raise WorldAfterstateTrainingError(
            "world-afterstate training loss receipt drift")
    return WorldAfterstateEpochReceiptV0(
        epoch=epoch, batch_count=len(batches), example_count=count,
        mean_loss_nanonats=mean_loss, config_sha256=config.sha256(),
        population_sha256=population_sha, schedule_sha256=schedule_sha,
        model_state_sha256_before=before,
        model_state_sha256_after=model_state_sha256(model))


def evaluate_calibration_nll_nanonats(
        model: WorldAfterstateValueV0,
        batches: tuple[WorldAfterstateTrainingBatchV0, ...]) -> int:
    """Return mean calibration NLL without mutating model state."""
    _, _, count = _batch_bindings(
        batches, epoch=1, required_split="calibration")
    before = model_state_sha256(model)
    was_training = model.training
    model.eval()
    total = 0.0
    try:
        with torch.no_grad():
            for batch in batches:
                logits = model(
                    batch.public, batch.history, batch.history_lengths,
                    batch.world, batch.perspective)
                nll, _brier, _utility_error = proper_score_rows(
                    logits, batch.labels)
                if not bool(torch.all(torch.isfinite(nll))):
                    raise WorldAfterstateTrainingError(
                        "world-afterstate calibration score drift")
                total += float(nll.sum())
    finally:
        model.train(was_training)
    if model_state_sha256(model) != before or not math.isfinite(total):
        raise WorldAfterstateTrainingError(
            "world-afterstate calibration mutated model")
    value = round(total / count * LOSS_SCALE)
    if type(value) is not int or value < 0:
        raise WorldAfterstateTrainingError(
            "world-afterstate calibration receipt drift")
    return value


@dataclass(frozen=True)
class WorldAfterstateCommonEpochV0:
    selected_epoch: int
    stop_epoch: int
    cohort_mean_loss_nanonats: tuple[int, ...]
    stopped_for_patience: bool
    config_sha256: str
    schema: str = COMMON_EPOCH_SCHEMA

    def validate(self) -> None:
        if self.schema != COMMON_EPOCH_SCHEMA \
                or isinstance(self.selected_epoch, bool) \
                or not isinstance(self.selected_epoch, int) \
                or isinstance(self.stop_epoch, bool) \
                or not isinstance(self.stop_epoch, int) \
                or not 1 <= self.selected_epoch <= self.stop_epoch \
                or type(self.cohort_mean_loss_nanonats) is not tuple \
                or len(self.cohort_mean_loss_nanonats) != self.stop_epoch \
                or any(type(value) is not int or value < 0
                       for value in self.cohort_mean_loss_nanonats) \
                or type(self.stopped_for_patience) is not bool \
                or type(self.config_sha256) is not str \
                or len(self.config_sha256) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in self.config_sha256):
            raise WorldAfterstateTrainingError(
                "world-afterstate common epoch receipt drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "selected_epoch": self.selected_epoch,
            "stop_epoch": self.stop_epoch,
            "cohort_mean_loss_nanonats":
                list(self.cohort_mean_loss_nanonats),
            "stopped_for_patience": self.stopped_for_patience,
            "config_sha256": self.config_sha256,
            "authority": dict(TRAINING_AUTHORITY),
        }

    def sha256(self) -> str:
        return _sha(self.payload())


def select_common_epoch(
        loss_nanonats_by_member: tuple[tuple[int, ...], ...], *,
        config: WorldAfterstateTrainingConfigV0) \
        -> WorldAfterstateCommonEpochV0:
    """Choose one cohort-mean epoch; never a best epoch per member."""
    config.validate()
    if type(loss_nanonats_by_member) is not tuple \
            or len(loss_nanonats_by_member) != COHORT_SIZE \
            or any(type(row) is not tuple for row in loss_nanonats_by_member):
        raise WorldAfterstateTrainingError(
            "world-afterstate calibration cohort drift")
    lengths = {len(row) for row in loss_nanonats_by_member}
    if len(lengths) != 1:
        raise WorldAfterstateTrainingError(
            "world-afterstate calibration epoch count drift")
    epoch_count = next(iter(lengths))
    if not 1 <= epoch_count <= config.max_epochs \
            or any(type(value) is not int or value < 0
                   for row in loss_nanonats_by_member for value in row):
        raise WorldAfterstateTrainingError(
            "world-afterstate calibration loss drift")
    sums = tuple(sum(row[index] for row in loss_nanonats_by_member)
                 for index in range(epoch_count))
    means = tuple(value // COHORT_SIZE for value in sums)
    selected = 1
    best = sums[0]
    stale = 0
    stop = epoch_count
    stopped = False
    threshold = config.minimum_improvement_nanonats * COHORT_SIZE
    for index in range(1, epoch_count):
        if best - sums[index] >= threshold:
            best = sums[index]
            selected = index + 1
            stale = 0
        else:
            stale += 1
            if stale == config.early_stop_patience:
                stop = index + 1
                stopped = True
                break
    result = WorldAfterstateCommonEpochV0(
        selected_epoch=selected, stop_epoch=stop,
        cohort_mean_loss_nanonats=means[:stop],
        stopped_for_patience=stopped, config_sha256=config.sha256())
    result.validate()
    return result


__all__ = [
    "COHORT_SIZE", "TRAINING_AUTHORITY", "WorldAfterstateCommonEpochV0",
    "WorldAfterstateEpochReceiptV0", "WorldAfterstateTrainingBatchV0",
    "WorldAfterstateTrainingConfigV0", "WorldAfterstateTrainingError",
    "collate_training_examples", "evaluate_calibration_nll_nanonats",
    "model_state_sha256", "new_optimizer", "select_common_epoch",
    "train_epoch",
]
