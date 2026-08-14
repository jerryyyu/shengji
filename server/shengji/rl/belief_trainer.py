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
from typing import Any

import torch

from .belief_b2_protocol import (
    TRAIN_GRADIENT_NORM_CAP,
    TRAIN_LEARNING_RATE,
    TRAIN_WEIGHT_DECAY,
)
from .belief_contract import canonical_json_bytes
from .belief_model import HistoryOwnershipModelV1
from .belief_training import (
    HISTORY_ABLATION_CONTROL,
    BeliefTrainingBatchV1,
    BeliefTrainingError,
    training_batch_loss,
)


OPTIMIZER_SCHEMA = "belief-v1-b2-adamw-optimizer-v1"
EPOCH_RECEIPT_SCHEMA = "belief-v1-b2-training-epoch-receipt-v1"
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
            "model_state_sha256_before": self.model_state_sha256_before,
            "model_state_sha256_after": self.model_state_sha256_after,
            "privileged_targets_consumed": True,
            "checkpoint_written": False,
            "runtime_artifact": False,
        }


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
