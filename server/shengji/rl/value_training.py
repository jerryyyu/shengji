"""Minimal in-memory training helpers for the reusable Value network."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import torch
from torch import nn

from .value_afterstate import ValueAfterstateExample, ValueAfterstateTensors
from .value_model import ValueModelError, ValueNetwork


class ValueTrainingError(ValueError):
    """A batch, optimizer epoch, or early-stopping request drifted."""


@dataclass(frozen=True)
class ValueTensorBatch:
    public: torch.Tensor
    history: torch.Tensor
    history_mask: torch.Tensor
    world: torch.Tensor
    perspective: torch.Tensor

    def to(self, device: torch.device | str) -> "ValueTensorBatch":
        return ValueTensorBatch(
            self.public.to(device), self.history.to(device),
            self.history_mask.to(device), self.world.to(device),
            self.perspective.to(device))


@dataclass(frozen=True)
class ValueTrainingBatch:
    tensors: ValueTensorBatch
    targets: torch.Tensor

    def to(self, device: torch.device | str) -> "ValueTrainingBatch":
        return ValueTrainingBatch(self.tensors.to(device), self.targets.to(device))


@dataclass(frozen=True)
class EpochReceipt:
    epoch: int
    train_loss: float
    validation_loss: float


@dataclass(frozen=True)
class TrainingReceipt:
    epochs: tuple[EpochReceipt, ...]
    best_epoch: int
    stopped_early: bool


def collate_tensors(rows: Sequence[ValueAfterstateTensors]) -> ValueTensorBatch:
    if not rows:
        raise ValueTrainingError("cannot collate an empty tensor population")
    for row in rows:
        row.validate()
        if len(row.history) < 1:
            raise ValueTrainingError("afterstate history must be non-empty")
    length = max(len(row.history) for row in rows)
    public = np.stack([row.public for row in rows])
    world = np.stack([row.world for row in rows])
    perspective = np.stack([row.perspective for row in rows])
    history = np.zeros((len(rows), length, rows[0].history.shape[1]),
                       dtype=np.float32)
    mask = np.zeros((len(rows), length), dtype=np.bool_)
    for index, row in enumerate(rows):
        n = len(row.history)
        history[index, :n] = row.history
        mask[index, :n] = True
    return ValueTensorBatch(
        public=torch.from_numpy(public), history=torch.from_numpy(history),
        history_mask=torch.from_numpy(mask), world=torch.from_numpy(world),
        perspective=torch.from_numpy(perspective))


def collate_examples(rows: Sequence[ValueAfterstateExample]) -> ValueTrainingBatch:
    if not rows:
        raise ValueTrainingError("cannot collate an empty example population")
    for row in rows:
        row.validate()
    return ValueTrainingBatch(
        collate_tensors([row.tensors for row in rows]),
        torch.tensor([row.target_category for row in rows], dtype=torch.long))


def _chunks(rows: Sequence[ValueAfterstateExample], batch_size: int,
            *, shuffle_seed: int | None) -> Iterable[list[ValueAfterstateExample]]:
    if batch_size < 1:
        raise ValueTrainingError("batch_size must be positive")
    order = list(range(len(rows)))
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(order)
    for start in range(0, len(order), batch_size):
        yield [rows[index] for index in order[start:start + batch_size]]


def _logits(model: ValueNetwork, batch: ValueTensorBatch) -> torch.Tensor:
    return model(batch.public, batch.history, batch.history_mask,
                 batch.world, batch.perspective)


def train_epoch(model: ValueNetwork, rows: Sequence[ValueAfterstateExample],
                optimizer: torch.optim.Optimizer, *, batch_size: int,
                device: torch.device | str = "cpu", shuffle_seed: int = 0) -> float:
    if not rows:
        raise ValueTrainingError("training population is empty")
    model.train()
    total_loss = 0.0
    total_rows = 0
    for chunk in _chunks(rows, batch_size, shuffle_seed=shuffle_seed):
        batch = collate_examples(chunk).to(device)
        optimizer.zero_grad(set_to_none=True)
        loss = nn.functional.cross_entropy(_logits(model, batch.tensors), batch.targets)
        if not bool(torch.isfinite(loss)):
            raise ValueTrainingError("training loss is non-finite")
        loss.backward()
        optimizer.step()
        total_loss += float(loss.detach().cpu()) * len(chunk)
        total_rows += len(chunk)
    return total_loss / total_rows


@torch.inference_mode()
def evaluate_loss(model: ValueNetwork, rows: Sequence[ValueAfterstateExample],
                  *, batch_size: int,
                  device: torch.device | str = "cpu") -> float:
    if not rows:
        raise ValueTrainingError("validation population is empty")
    model.eval()
    total_loss = 0.0
    total_rows = 0
    for chunk in _chunks(rows, batch_size, shuffle_seed=None):
        batch = collate_examples(chunk).to(device)
        loss = nn.functional.cross_entropy(_logits(model, batch.tensors), batch.targets)
        if not bool(torch.isfinite(loss)):
            raise ValueTrainingError("validation loss is non-finite")
        total_loss += float(loss.cpu()) * len(chunk)
        total_rows += len(chunk)
    return total_loss / total_rows


def fit(model: ValueNetwork, train_rows: Sequence[ValueAfterstateExample],
        validation_rows: Sequence[ValueAfterstateExample], *, max_epochs: int,
        patience: int, batch_size: int = 64, learning_rate: float = 3e-4,
        weight_decay: float = 1e-4, min_delta: float = 0.0,
        seed: int = 0, device: torch.device | str = "cpu") -> TrainingReceipt:
    """Fit with validation-loss early stopping and restore the best epoch."""
    if type(model) is not ValueNetwork:
        raise ValueTrainingError("fit requires an exact ValueNetwork")
    if any(type(value) is not int for value in (max_epochs, patience, batch_size,
                                                seed)) \
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(float(value))
                   for value in (learning_rate, weight_decay, min_delta)) \
            or max_epochs < 1 or patience < 1 or batch_size < 1 \
            or learning_rate <= 0.0 or weight_decay < 0.0 or min_delta < 0.0:
        raise ValueTrainingError("training configuration drift")
    if not train_rows or not validation_rows:
        raise ValueTrainingError("fit requires train and validation populations")
    for row in (*train_rows, *validation_rows):
        row.validate()
    overlap = ({row.deal_key for row in train_rows}
               & {row.deal_key for row in validation_rows})
    if overlap:
        raise ValueTrainingError("train and validation deal populations overlap")
    torch.manual_seed(seed)
    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    best_loss = math.inf
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    stale = 0
    receipts: list[EpochReceipt] = []
    for epoch in range(1, max_epochs + 1):
        train_loss = train_epoch(
            model, train_rows, optimizer, batch_size=batch_size,
            device=device, shuffle_seed=seed + epoch)
        validation_loss = evaluate_loss(
            model, validation_rows, batch_size=batch_size, device=device)
        receipts.append(EpochReceipt(epoch, train_loss, validation_loss))
        if validation_loss < best_loss - min_delta:
            best_loss = validation_loss
            best_epoch = epoch
            stale = 0
            best_state = {
                key: value.detach().cpu().clone()
                for key, value in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise ValueTrainingError("training produced no finite best epoch")
    try:
        model.load_state_dict(best_state, strict=True)
    except (RuntimeError, ValueModelError) as exc:
        raise ValueTrainingError("best model state restoration failed") from exc
    model.to(device)
    return TrainingReceipt(
        epochs=tuple(receipts), best_epoch=best_epoch,
        stopped_early=len(receipts) < max_epochs)
