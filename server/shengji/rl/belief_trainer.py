"""Deterministic CPU training mechanics and checkpoint identity for B2.

This module owns the exact AdamW step shared by the candidate and negative
controls.  It accepts only already-authenticated, scheduled batches, pins CPU
float32 model state, uses no stochastic layer, and hashes parameters through a
canonical name/shape/dtype/byte stream.  It has no corpus reader, checkpoint
writer, epoch selection, test opening, policy, sampler, or execution surface.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Iterable

import torch

from .belief_b2_protocol import (
    TRAIN_GRADIENT_NORM_CAP,
    TRAIN_LEARNING_RATE,
    TRAIN_WEIGHT_DECAY,
)
from .belief_contract import canonical_json_bytes
from .belief_cohort import COHORT_SEEDS
from .belief_model import HistoryOwnershipModelV1
from .belief_training import (
    HISTORY_ABLATION_CONTROL,
    BeliefTrainingBatchV1,
    BeliefTrainingError,
    training_batch_loss,
)


OPTIMIZER_SCHEMA = "belief-v1-b2-adamw-optimizer-v1"
EPOCH_RECEIPT_SCHEMA = "belief-v1-b2-training-epoch-receipt-v2"
EPOCH_POPULATION_SCHEMA = "belief-v1-b2-training-decision-population-v1"
EPOCH_SCHEDULE_SCHEMA = "belief-v1-b2-training-batch-schedule-v1"
CHECKPOINT_SCHEMA = "belief-v1-history-ownership-state-dict-v1"
LOSS_SCALE = 1_000_000_000


class BeliefTrainerError(ValueError):
    """The exact B2 optimizer, batch, gradient, or checkpoint drifted."""


@dataclass(frozen=True)
class EpochTrainingReceiptV1:
    epoch: int
    batch_count: int
    decision_count: int
    active_label_count: int
    mean_loss_nanonats: int
    batch_schema: str
    history_transform: str
    label_transform: str
    control_kind: str
    decision_population_sha256: str
    batch_schedule_sha256: str
    model_state_sha256_before: str
    model_state_sha256_after: str
    schema: str = EPOCH_RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "epoch": self.epoch,
            "batch_count": self.batch_count,
            "decision_count": self.decision_count,
            "active_label_count": self.active_label_count,
            "mean_loss_nanonats": self.mean_loss_nanonats,
            "batch_schema": self.batch_schema,
            "history_transform": self.history_transform,
            "label_transform": self.label_transform,
            "control_kind": self.control_kind,
            "decision_population_sha256": self.decision_population_sha256,
            "batch_schedule_sha256": self.batch_schedule_sha256,
            "model_state_sha256_before": self.model_state_sha256_before,
            "model_state_sha256_after": self.model_state_sha256_after,
            "privileged_targets_consumed": True,
            "checkpoint_written": False,
            "runtime_artifact": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def model_state_sha256(model: HistoryOwnershipModelV1) -> str:
    """Hash exact ordered CPU float32 parameter names, shapes, and bytes."""
    if type(model) is not HistoryOwnershipModelV1 \
            or any(parameter.device.type != "cpu"
                   or parameter.dtype != torch.float32
                   for parameter in model.parameters()):
        raise BeliefTrainerError("checkpoint model device/dtype drift")
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({
        "schema": CHECKPOINT_SCHEMA,
        "parameter_names": [name for name, _ in model.named_parameters()],
    }))
    for name, parameter in model.named_parameters():
        value = parameter.detach().contiguous()
        header = canonical_json_bytes({
            "name": name,
            "shape": list(value.shape),
            "dtype": "float32",
            "byte_count": value.numel() * value.element_size(),
        })
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        raw = value.view(torch.uint8).numpy().tobytes(order="C")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def new_b2_optimizer(model: HistoryOwnershipModelV1) -> torch.optim.AdamW:
    if type(model) is not HistoryOwnershipModelV1 \
            or any(parameter.device.type != "cpu"
                   or parameter.dtype != torch.float32
                   for parameter in model.parameters()):
        raise BeliefTrainerError("optimizer model device/dtype drift")
    return torch.optim.AdamW(
        model.parameters(), lr=float(TRAIN_LEARNING_RATE),
        weight_decay=float(TRAIN_WEIGHT_DECAY), foreach=False,
        fused=False)


def _validate_optimizer(
        model: HistoryOwnershipModelV1,
        optimizer: torch.optim.Optimizer) -> None:
    if type(optimizer) is not torch.optim.AdamW \
            or len(optimizer.param_groups) != 1:
        raise BeliefTrainerError("optimizer identity drift")
    group = optimizer.param_groups[0]
    if group["lr"] != float(TRAIN_LEARNING_RATE) \
            or group["weight_decay"] != float(TRAIN_WEIGHT_DECAY) \
            or group["foreach"] is not False \
            or group["fused"] is not False \
            or len(group["params"]) != len(tuple(model.parameters())) \
            or any(left is not right for left, right in zip(
                group["params"], model.parameters(), strict=True)):
        raise BeliefTrainerError("optimizer parameter/configuration drift")


def _validate_batches(
        batches: tuple[BeliefTrainingBatchV1, ...], *,
        for_training: bool) -> None:
    if type(batches) is not tuple or not batches \
            or any(type(batch) is not BeliefTrainingBatchV1
                   for batch in batches):
        raise BeliefTrainerError("training epoch batch population drift")
    keys = tuple(key for batch in batches for key in batch.decision_keys)
    if len(keys) != len(set(keys)):
        raise BeliefTrainerError("training epoch duplicate decision")
    identities = {(batch.schema, batch.history_transform,
                   batch.label_transform, batch.control_kind)
                  for batch in batches}
    if len(identities) != 1:
        raise BeliefTrainerError("training epoch mixed candidate/control batch")
    if for_training and batches[0].control_kind == HISTORY_ABLATION_CONTROL:
        raise BeliefTrainerError(
            "history chronology ablation is inference-only")
    if any(batch.split != "train" \
           or batch.privileged_targets_consumed is not True \
           or batch.runtime_artifact is not False for batch in batches):
        raise BeliefTrainerError("training epoch batch authority/split drift")


def _epoch_input_digests(
        batch_decision_keys: tuple[tuple[str, ...], ...], *, epoch: int) \
        -> tuple[str, str]:
    """Bind both the exact decision set and its ordered batch realization."""
    if type(epoch) is not int or epoch <= 0 \
            or type(batch_decision_keys) is not tuple \
            or not batch_decision_keys \
            or any(type(batch) is not tuple or not batch
                   or any(type(key) is not str or not key for key in batch)
                   for batch in batch_decision_keys):
        raise BeliefTrainerError("training epoch input binding drift")
    flattened = tuple(key for batch in batch_decision_keys for key in batch)
    if len(flattened) != len(set(flattened)):
        raise BeliefTrainerError("training epoch duplicate decision")
    population = hashlib.sha256(canonical_json_bytes({
        "schema": EPOCH_POPULATION_SCHEMA,
        "decision_count": len(flattened),
        "decision_keys": sorted(flattened),
    })).hexdigest()
    schedule = hashlib.sha256(canonical_json_bytes({
        "schema": EPOCH_SCHEDULE_SCHEMA,
        "epoch": epoch,
        "batch_count": len(batch_decision_keys),
        "batch_decision_keys": [list(batch) for batch in batch_decision_keys],
    })).hexdigest()
    return population, schedule


def train_epoch(
        model: HistoryOwnershipModelV1,
        optimizer: torch.optim.Optimizer,
        batches: tuple[BeliefTrainingBatchV1, ...], *,
        epoch: int) -> EpochTrainingReceiptV1:
    """Apply one exact scheduled epoch and return a score-free receipt."""
    if type(epoch) is not int or epoch <= 0:
        raise BeliefTrainerError("training epoch is invalid")
    _validate_optimizer(model, optimizer)
    _validate_batches(batches, for_training=True)
    before = model_state_sha256(model)
    population_sha, schedule_sha = _epoch_input_digests(
        tuple(batch.decision_keys for batch in batches), epoch=epoch)
    model.train(True)
    weighted_loss = 0.0
    active_total = 0
    for batch in batches:
        optimizer.zero_grad(set_to_none=True)
        try:
            loss = training_batch_loss(model, batch)
        except (BeliefTrainingError, ValueError) as exc:
            raise BeliefTrainerError("training batch loss refused") from exc
        if loss.ndim != 0 or not bool(torch.isfinite(loss)):
            raise BeliefTrainerError("training loss is nonfinite")
        active = int(batch.active_mask.sum().item())
        if active <= 0:
            raise BeliefTrainerError("training batch has no active labels")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), float(TRAIN_GRADIENT_NORM_CAP),
            error_if_nonfinite=True)
        if not bool(torch.isfinite(norm)):
            raise BeliefTrainerError("training gradient norm is nonfinite")
        optimizer.step()
        weighted_loss += float(loss.detach()) * active
        active_total += active
    mean_nanonats = round(weighted_loss / active_total * LOSS_SCALE)
    if type(mean_nanonats) is not int or mean_nanonats < 0 \
            or not math.isfinite(weighted_loss):
        raise BeliefTrainerError("training epoch loss receipt is invalid")
    return EpochTrainingReceiptV1(
        epoch=epoch, batch_count=len(batches),
        decision_count=sum(len(batch.decision_keys) for batch in batches),
        active_label_count=active_total,
        mean_loss_nanonats=mean_nanonats,
        batch_schema=batches[0].schema,
        history_transform=batches[0].history_transform,
        label_transform=batches[0].label_transform,
        control_kind=batches[0].control_kind,
        decision_population_sha256=population_sha,
        batch_schedule_sha256=schedule_sha,
        model_state_sha256_before=before,
        model_state_sha256_after=model_state_sha256(model),
    )


def train_epoch_stream(
        model: HistoryOwnershipModelV1,
        optimizer: torch.optim.Optimizer,
        batches: Iterable[BeliefTrainingBatchV1], *,
        epoch: int) -> EpochTrainingReceiptV1:
    """Apply one exact epoch without retaining the full corpus in memory."""
    if type(epoch) is not int or epoch <= 0:
        raise BeliefTrainerError("training epoch is invalid")
    _validate_optimizer(model, optimizer)
    try:
        iterator = iter(batches)
    except TypeError as exc:
        raise BeliefTrainerError(
            "training epoch batch population drift") from exc
    before = model_state_sha256(model)
    model.train(True)
    weighted_loss = 0.0
    active_total = 0
    batch_count = 0
    decision_count = 0
    identity: tuple[str, str, str, str] | None = None
    seen: set[str] = set()
    scheduled_batches: list[tuple[str, ...]] = []
    for batch in iterator:
        if type(batch) is not BeliefTrainingBatchV1:
            raise BeliefTrainerError(
                "training epoch batch population drift")
        current = (batch.schema, batch.history_transform,
                   batch.label_transform, batch.control_kind)
        if identity is None:
            identity = current
        elif current != identity:
            raise BeliefTrainerError(
                "training epoch mixed candidate/control batch")
        if batch.control_kind == HISTORY_ABLATION_CONTROL:
            raise BeliefTrainerError(
                "history chronology ablation is inference-only")
        if batch.split != "train" \
                or batch.privileged_targets_consumed is not True \
                or batch.runtime_artifact is not False:
            raise BeliefTrainerError(
                "training epoch batch authority/split drift")
        if any(key in seen for key in batch.decision_keys) \
                or len(batch.decision_keys) != len(set(batch.decision_keys)):
            raise BeliefTrainerError("training epoch duplicate decision")
        seen.update(batch.decision_keys)
        scheduled_batches.append(batch.decision_keys)
        optimizer.zero_grad(set_to_none=True)
        try:
            loss = training_batch_loss(model, batch)
        except (BeliefTrainingError, ValueError) as exc:
            raise BeliefTrainerError("training batch loss refused") from exc
        if loss.ndim != 0 or not bool(torch.isfinite(loss)):
            raise BeliefTrainerError("training loss is nonfinite")
        active = int(batch.active_mask.sum().item())
        if active <= 0:
            raise BeliefTrainerError("training batch has no active labels")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), float(TRAIN_GRADIENT_NORM_CAP),
            error_if_nonfinite=True)
        if not bool(torch.isfinite(norm)):
            raise BeliefTrainerError("training gradient norm is nonfinite")
        optimizer.step()
        weighted_loss += float(loss.detach()) * active
        active_total += active
        batch_count += 1
        decision_count += len(batch.decision_keys)
    if batch_count == 0 or identity is None or active_total <= 0:
        raise BeliefTrainerError("training epoch batch population drift")
    mean_nanonats = round(weighted_loss / active_total * LOSS_SCALE)
    if type(mean_nanonats) is not int or mean_nanonats < 0 \
            or not math.isfinite(weighted_loss):
        raise BeliefTrainerError("training epoch loss receipt is invalid")
    population_sha, schedule_sha = _epoch_input_digests(
        tuple(scheduled_batches), epoch=epoch)
    return EpochTrainingReceiptV1(
        epoch=epoch, batch_count=batch_count,
        decision_count=decision_count,
        active_label_count=active_total,
        mean_loss_nanonats=mean_nanonats,
        batch_schema=identity[0], history_transform=identity[1],
        label_transform=identity[2], control_kind=identity[3],
        decision_population_sha256=population_sha,
        batch_schedule_sha256=schedule_sha,
        model_state_sha256_before=before,
        model_state_sha256_after=model_state_sha256(model),
    )


def evaluate_calibration_loss_nanonats(
        model: HistoryOwnershipModelV1,
        batches: tuple[BeliefTrainingBatchV1, ...]) -> int:
    """Return active-cell-weighted calibration loss without mutation."""
    if type(model) is not HistoryOwnershipModelV1:
        raise BeliefTrainerError("calibration model identity drift")
    if type(batches) is not tuple or not batches \
            or any(type(batch) is not BeliefTrainingBatchV1
                   or batch.split != "calibration" for batch in batches):
        raise BeliefTrainerError("calibration batch population/split drift")
    before = model_state_sha256(model)
    was_training = model.training
    model.eval()
    weighted_loss = 0.0
    active_total = 0
    try:
        with torch.no_grad():
            for batch in batches:
                loss = training_batch_loss(model, batch)
                if loss.ndim != 0 or not bool(torch.isfinite(loss)):
                    raise BeliefTrainerError("calibration loss is nonfinite")
                active = int(batch.active_mask.sum().item())
                weighted_loss += float(loss) * active
                active_total += active
    finally:
        model.train(was_training)
    if active_total <= 0 or model_state_sha256(model) != before:
        raise BeliefTrainerError("calibration evaluation mutated model")
    value = round(weighted_loss / active_total * LOSS_SCALE)
    if type(value) is not int or value < 0 or not math.isfinite(weighted_loss):
        raise BeliefTrainerError("calibration loss receipt is invalid")
    return value


def evaluate_calibration_stream_nanonats(
        model: HistoryOwnershipModelV1,
        batches: Iterable[BeliefTrainingBatchV1]) -> int:
    """Evaluate calibration while retaining at most one batch at a time."""
    if type(model) is not HistoryOwnershipModelV1:
        raise BeliefTrainerError("calibration model identity drift")
    try:
        iterator = iter(batches)
    except TypeError as exc:
        raise BeliefTrainerError(
            "calibration batch population/split drift") from exc
    before = model_state_sha256(model)
    was_training = model.training
    weighted_loss = 0.0
    active_total = 0
    batch_count = 0
    identity: tuple[str, str, str, str] | None = None
    seen: set[str] = set()
    model.eval()
    try:
        with torch.no_grad():
            for batch in iterator:
                if type(batch) is not BeliefTrainingBatchV1 \
                        or batch.split != "calibration" \
                        or batch.privileged_targets_consumed is not True \
                        or batch.runtime_artifact is not False:
                    raise BeliefTrainerError(
                        "calibration batch population/split drift")
                current = (batch.schema, batch.history_transform,
                           batch.label_transform, batch.control_kind)
                if identity is None:
                    identity = current
                elif current != identity:
                    raise BeliefTrainerError(
                        "calibration mixed candidate/control batch")
                if any(key in seen for key in batch.decision_keys) \
                        or len(batch.decision_keys) \
                        != len(set(batch.decision_keys)):
                    raise BeliefTrainerError(
                        "calibration duplicate decision")
                seen.update(batch.decision_keys)
                try:
                    loss = training_batch_loss(model, batch)
                except (BeliefTrainingError, ValueError) as exc:
                    raise BeliefTrainerError(
                        "calibration batch loss refused") from exc
                if loss.ndim != 0 or not bool(torch.isfinite(loss)):
                    raise BeliefTrainerError(
                        "calibration loss is nonfinite")
                active = int(batch.active_mask.sum().item())
                if active <= 0:
                    raise BeliefTrainerError(
                        "calibration batch has no active labels")
                weighted_loss += float(loss) * active
                active_total += active
                batch_count += 1
    finally:
        model.train(was_training)
    if batch_count == 0 or identity is None or active_total <= 0 \
            or model_state_sha256(model) != before:
        raise BeliefTrainerError("calibration evaluation mutated model")
    value = round(weighted_loss / active_total * LOSS_SCALE)
    if type(value) is not int or value < 0 or not math.isfinite(weighted_loss):
        raise BeliefTrainerError("calibration loss receipt is invalid")
    return value


def train_cohort_epoch_stream(
        models: tuple[HistoryOwnershipModelV1, ...],
        optimizers: tuple[torch.optim.Optimizer, ...],
        batches: Iterable[BeliefTrainingBatchV1], *, epoch: int) \
        -> tuple[EpochTrainingReceiptV1, ...]:
    """Stream each batch once and apply it to every fixed cohort member."""
    if type(models) is not tuple or len(models) != len(COHORT_SEEDS) \
            or any(type(model) is not HistoryOwnershipModelV1
                   for model in models) \
            or type(optimizers) is not tuple \
            or len(optimizers) != len(models) \
            or len({id(model) for model in models}) != len(models) \
            or type(epoch) is not int or epoch <= 0:
        raise BeliefTrainerError("training cohort population drift")
    for model, optimizer in zip(models, optimizers, strict=True):
        _validate_optimizer(model, optimizer)
    try:
        iterator = iter(batches)
    except TypeError as exc:
        raise BeliefTrainerError(
            "training epoch batch population drift") from exc
    before = tuple(model_state_sha256(model) for model in models)
    for model in models:
        model.train(True)
    weighted_losses = [0.0] * len(models)
    active_total = 0
    batch_count = 0
    decision_count = 0
    identity: tuple[str, str, str, str] | None = None
    seen: set[str] = set()
    scheduled_batches: list[tuple[str, ...]] = []
    for batch in iterator:
        if type(batch) is not BeliefTrainingBatchV1:
            raise BeliefTrainerError(
                "training epoch batch population drift")
        current = (batch.schema, batch.history_transform,
                   batch.label_transform, batch.control_kind)
        if identity is None:
            identity = current
        elif current != identity:
            raise BeliefTrainerError(
                "training epoch mixed candidate/control batch")
        if batch.control_kind == HISTORY_ABLATION_CONTROL:
            raise BeliefTrainerError(
                "history chronology ablation is inference-only")
        if batch.split != "train" \
                or batch.privileged_targets_consumed is not True \
                or batch.runtime_artifact is not False:
            raise BeliefTrainerError(
                "training epoch batch authority/split drift")
        if any(key in seen for key in batch.decision_keys) \
                or len(batch.decision_keys) != len(set(batch.decision_keys)):
            raise BeliefTrainerError("training epoch duplicate decision")
        seen.update(batch.decision_keys)
        scheduled_batches.append(batch.decision_keys)
        active = int(batch.active_mask.sum().item())
        if active <= 0:
            raise BeliefTrainerError("training batch has no active labels")
        for index, (model, optimizer) in enumerate(zip(
                models, optimizers, strict=True)):
            optimizer.zero_grad(set_to_none=True)
            try:
                loss = training_batch_loss(model, batch)
            except (BeliefTrainingError, ValueError) as exc:
                raise BeliefTrainerError(
                    "training batch loss refused") from exc
            if loss.ndim != 0 or not bool(torch.isfinite(loss)):
                raise BeliefTrainerError("training loss is nonfinite")
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(), float(TRAIN_GRADIENT_NORM_CAP),
                error_if_nonfinite=True)
            if not bool(torch.isfinite(norm)):
                raise BeliefTrainerError(
                    "training gradient norm is nonfinite")
            optimizer.step()
            weighted_losses[index] += float(loss.detach()) * active
        active_total += active
        batch_count += 1
        decision_count += len(batch.decision_keys)
    if batch_count == 0 or identity is None or active_total <= 0:
        raise BeliefTrainerError("training epoch batch population drift")
    population_sha, schedule_sha = _epoch_input_digests(
        tuple(scheduled_batches), epoch=epoch)
    receipts = []
    for index, model in enumerate(models):
        weighted = weighted_losses[index]
        mean_nanonats = round(weighted / active_total * LOSS_SCALE)
        if type(mean_nanonats) is not int or mean_nanonats < 0 \
                or not math.isfinite(weighted):
            raise BeliefTrainerError(
                "training epoch loss receipt is invalid")
        receipts.append(EpochTrainingReceiptV1(
            epoch=epoch, batch_count=batch_count,
            decision_count=decision_count,
            active_label_count=active_total,
            mean_loss_nanonats=mean_nanonats,
            batch_schema=identity[0], history_transform=identity[1],
            label_transform=identity[2], control_kind=identity[3],
            decision_population_sha256=population_sha,
            batch_schedule_sha256=schedule_sha,
            model_state_sha256_before=before[index],
            model_state_sha256_after=model_state_sha256(model)))
    return tuple(receipts)


def evaluate_calibration_cohort_stream_nanonats(
        models: tuple[HistoryOwnershipModelV1, ...],
        batches: Iterable[BeliefTrainingBatchV1]) -> tuple[int, ...]:
    """Evaluate all fixed members while retaining only one batch."""
    if type(models) is not tuple or len(models) != len(COHORT_SEEDS) \
            or any(type(model) is not HistoryOwnershipModelV1
                   for model in models) \
            or len({id(model) for model in models}) != len(models):
        raise BeliefTrainerError("calibration cohort population drift")
    try:
        iterator = iter(batches)
    except TypeError as exc:
        raise BeliefTrainerError(
            "calibration batch population/split drift") from exc
    before = tuple(model_state_sha256(model) for model in models)
    states = tuple(model.training for model in models)
    weighted_losses = [0.0] * len(models)
    active_total = 0
    batch_count = 0
    identity: tuple[str, str, str, str] | None = None
    seen: set[str] = set()
    for model in models:
        model.eval()
    try:
        with torch.no_grad():
            for batch in iterator:
                if type(batch) is not BeliefTrainingBatchV1 \
                        or batch.split != "calibration" \
                        or batch.privileged_targets_consumed is not True \
                        or batch.runtime_artifact is not False:
                    raise BeliefTrainerError(
                        "calibration batch population/split drift")
                current = (batch.schema, batch.history_transform,
                           batch.label_transform, batch.control_kind)
                if identity is None:
                    identity = current
                elif current != identity:
                    raise BeliefTrainerError(
                        "calibration mixed candidate/control batch")
                if any(key in seen for key in batch.decision_keys) \
                        or len(batch.decision_keys) \
                        != len(set(batch.decision_keys)):
                    raise BeliefTrainerError(
                        "calibration duplicate decision")
                seen.update(batch.decision_keys)
                active = int(batch.active_mask.sum().item())
                if active <= 0:
                    raise BeliefTrainerError(
                        "calibration batch has no active labels")
                for index, model in enumerate(models):
                    try:
                        loss = training_batch_loss(model, batch)
                    except (BeliefTrainingError, ValueError) as exc:
                        raise BeliefTrainerError(
                            "calibration batch loss refused") from exc
                    if loss.ndim != 0 or not bool(torch.isfinite(loss)):
                        raise BeliefTrainerError(
                            "calibration loss is nonfinite")
                    weighted_losses[index] += float(loss) * active
                active_total += active
                batch_count += 1
    finally:
        for model, state in zip(models, states, strict=True):
            model.train(state)
    if batch_count == 0 or identity is None or active_total <= 0 \
            or tuple(model_state_sha256(model) for model in models) != before:
        raise BeliefTrainerError("calibration cohort evaluation drift")
    values = tuple(round(
        weighted / active_total * LOSS_SCALE) for weighted in weighted_losses)
    if any(type(value) is not int or value < 0 for value in values) \
            or any(not math.isfinite(value) for value in weighted_losses):
        raise BeliefTrainerError("calibration loss receipt is invalid")
    return values
