"""Shared action-relative successor model for Value-Afterstate V1.

The same scorer processes the protected incumbent and one candidate.  Their
difference is the only prediction, so action-independent state bias cancels,
identical successors score exactly zero, and swapping the pair negates the
prediction.  The engine-applied successor remains the only action input.

This module contains model mechanics only.  It has no artifact, split,
training-controller, report, gameplay, strength, merge, or deployment
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch
from torch import nn

from .douzero_micro import HISTORY_EVENT_DIM
from .encode import N_CARDS
from .world_afterstate import (
    MAX_SIGNED_LEVEL_UTILITY, PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
    WorldAfterstateExampleV0, WorldAfterstateError,
    WorldAfterstateTensorsV0)
from .world_afterstate_model import (
    INIT_SCALE, WorldAfterstateShapeV0)


MODEL_SCHEMA = "world-afterstate-advantage-v1"
PAIR_EXAMPLE_SCHEMA = "world-afterstate-advantage-example-v1"


class WorldAfterstateV1ModelError(WorldAfterstateError):
    """A pair example, batch, model input, output, or loss drifted."""


@dataclass(frozen=True)
class AdvantageExampleV1:
    incumbent: WorldAfterstateExampleV0
    candidate: WorldAfterstateExampleV0
    advantage_levels: int
    schema: str = PAIR_EXAMPLE_SCHEMA

    def validate(self) -> None:
        if self.schema != PAIR_EXAMPLE_SCHEMA \
                or type(self.incumbent) is not WorldAfterstateExampleV0 \
                or type(self.candidate) is not WorldAfterstateExampleV0:
            raise WorldAfterstateV1ModelError(
                "advantage example schema drift")
        self.incumbent.validate()
        self.candidate.validate()
        if isinstance(self.advantage_levels, bool) \
                or not isinstance(self.advantage_levels, int) \
                or self.advantage_levels != (
                    self.candidate.signed_level_category
                    - self.incumbent.signed_level_category) \
                or not -203 <= self.advantage_levels <= 203:
            raise WorldAfterstateV1ModelError(
                "advantage example label drift")
        if self.incumbent.successor_sha256 \
                == self.candidate.successor_sha256 \
                and self.advantage_levels != 0:
            raise WorldAfterstateV1ModelError(
                "identical successor has nonzero advantage")


@dataclass(frozen=True)
class SuccessorBatchV1:
    public: torch.Tensor
    history: torch.Tensor
    history_lengths: torch.Tensor
    world: torch.Tensor
    perspective: torch.Tensor

    def validate(self) -> None:
        if self.public.ndim != 2 or self.public.shape[1] != PUBLIC_DIM \
                or self.public.dtype != torch.float32:
            raise WorldAfterstateV1ModelError("successor public batch drift")
        batch = self.public.shape[0]
        if self.history.ndim != 3 or self.history.shape[0] != batch \
                or self.history.shape[2] != HISTORY_EVENT_DIM \
                or self.history.dtype != torch.float32 \
                or self.history_lengths.shape != (batch,) \
                or self.history_lengths.dtype != torch.long \
                or bool(torch.any(self.history_lengths < 0)) \
                or bool(torch.any(
                    self.history_lengths > self.history.shape[1])):
            raise WorldAfterstateV1ModelError("successor history batch drift")
        if self.world.shape != (batch, WORLD_RECEIVERS, N_CARDS) \
                or self.world.dtype != torch.float32 \
                or not bool(torch.all(
                    (self.world == 0.0) | (self.world == 0.5)
                    | (self.world == 1.0))):
            raise WorldAfterstateV1ModelError("successor world batch drift")
        if self.perspective.shape != (batch, PERSPECTIVE_DIM) \
                or self.perspective.dtype != torch.float32 \
                or not bool(torch.all(
                    (self.perspective == 0.0)
                    | (self.perspective == 1.0))) \
                or not bool(torch.all(
                    self.perspective.sum(dim=1) == 1.0)):
            raise WorldAfterstateV1ModelError(
                "successor perspective batch drift")
        if any(not bool(torch.all(torch.isfinite(value))) for value in (
                self.public, self.history, self.world, self.perspective)):
            raise WorldAfterstateV1ModelError(
                "successor batch contains a non-finite value")

    @property
    def size(self) -> int:
        self.validate()
        return self.public.shape[0]


@dataclass(frozen=True)
class AdvantageBatchV1:
    incumbent: SuccessorBatchV1
    candidate: SuccessorBatchV1
    targets: torch.Tensor

    def validate(self) -> None:
        if type(self.incumbent) is not SuccessorBatchV1 \
                or type(self.candidate) is not SuccessorBatchV1:
            raise WorldAfterstateV1ModelError("advantage batch schema drift")
        self.incumbent.validate()
        self.candidate.validate()
        if self.incumbent.size != self.candidate.size \
                or self.targets.shape != (self.incumbent.size,) \
                or self.targets.dtype != torch.float32 \
                or not bool(torch.all(torch.isfinite(self.targets))) \
                or bool(torch.any(self.targets < -203.0)) \
                or bool(torch.any(self.targets > 203.0)):
            raise WorldAfterstateV1ModelError("advantage target batch drift")


def _successor_batch(
        examples: Sequence[WorldAfterstateExampleV0]) -> SuccessorBatchV1:
    # Training examples are already target-bound.  Drop their labels before
    # calling the same target-free tensor collation used for audit inference.
    if type(examples) not in (list, tuple) or not examples \
            or any(type(example) is not WorldAfterstateExampleV0
                   for example in examples):
        raise WorldAfterstateV1ModelError(
            "successor example population drift")
    for example in examples:
        example.validate()
    return collate_successor_tensors([example.tensors for example in examples])


def collate_successor_tensors(
        values: Sequence[WorldAfterstateTensorsV0]) -> SuccessorBatchV1:
    """Collate model input without constructing or receiving any target."""
    if type(values) not in (list, tuple) or not values \
            or any(type(value) is not WorldAfterstateTensorsV0
                   for value in values):
        raise WorldAfterstateV1ModelError(
            "successor tensor population drift")
    for value in values:
        value.validate()
    max_events = max(len(value.history) for value in values)
    history = torch.zeros(
        (len(values), max_events, HISTORY_EVENT_DIM), dtype=torch.float32)
    for index, value in enumerate(values):
        if len(value.history):
            history[index, :len(value.history)] = torch.from_numpy(
                value.history)
    result = SuccessorBatchV1(
        public=torch.as_tensor(
            np.stack([value.public for value in values]),
            dtype=torch.float32),
        history=history,
        history_lengths=torch.as_tensor(
            [len(value.history) for value in values], dtype=torch.long),
        world=torch.as_tensor(
            np.stack([value.world for value in values]),
            dtype=torch.float32),
        perspective=torch.as_tensor(
            np.stack([value.perspective for value in values]),
            dtype=torch.float32))
    result.validate()
    return result


def collate_advantage_examples(
        examples: Sequence[AdvantageExampleV1]) -> AdvantageBatchV1:
    if type(examples) not in (list, tuple) or not examples \
            or any(type(example) is not AdvantageExampleV1
                   for example in examples):
        raise WorldAfterstateV1ModelError(
            "advantage collate population drift")
    for example in examples:
        example.validate()
    result = AdvantageBatchV1(
        incumbent=_successor_batch([example.incumbent for example in examples]),
        candidate=_successor_batch([example.candidate for example in examples]),
        targets=torch.as_tensor(
            [example.advantage_levels for example in examples],
            dtype=torch.float32))
    result.validate()
    return result


class WorldAfterstateAdvantageV1(nn.Module):
    """One shared bounded successor scorer, consumed only as a difference."""

    def __init__(self, shape: WorldAfterstateShapeV0):
        super().__init__()
        shape.validate()
        self.shape = shape
        self.public_encoder = nn.Sequential(
            nn.Linear(PUBLIC_DIM, shape.public_hidden), nn.ReLU())
        self.history_encoder = nn.GRU(
            HISTORY_EVENT_DIM, shape.history_hidden, batch_first=True)
        self.world_encoder = nn.Sequential(
            nn.Linear(WORLD_RECEIVERS * N_CARDS, shape.world_hidden),
            nn.ReLU())
        self.perspective_encoder = nn.Sequential(
            nn.Linear(PERSPECTIVE_DIM, shape.perspective_hidden), nn.ReLU())
        self.score_head = nn.Sequential(
            nn.Linear(shape.public_hidden + shape.history_hidden
                      + shape.world_hidden + shape.perspective_hidden,
                      shape.head_hidden),
            nn.ReLU(), nn.Linear(shape.head_hidden, 1), nn.Tanh())

    def _score(self, value: SuccessorBatchV1) -> torch.Tensor:
        if type(value) is not SuccessorBatchV1:
            raise WorldAfterstateV1ModelError(
                "successor scorer input type drift")
        value.validate()
        public_context = self.public_encoder(value.public)
        if value.history.shape[1] == 0:
            history_context = torch.zeros(
                (value.size, self.shape.history_hidden),
                dtype=value.public.dtype, device=value.public.device)
        else:
            sequence, _ = self.history_encoder(value.history)
            indices = (value.history_lengths - 1).clamp(min=0)
            selector = nn.functional.one_hot(
                indices, num_classes=value.history.shape[1]).to(
                    sequence.dtype)
            history_context = torch.bmm(
                selector.unsqueeze(1), sequence).squeeze(1)
            history_context = torch.where(
                (value.history_lengths > 0).unsqueeze(1), history_context,
                torch.zeros_like(history_context))
        world_context = self.world_encoder(value.world.flatten(start_dim=1))
        perspective_context = self.perspective_encoder(value.perspective)
        score = self.score_head(torch.cat([
            public_context, history_context, world_context,
            perspective_context,
        ], dim=1)).squeeze(1) * MAX_SIGNED_LEVEL_UTILITY
        if score.shape != (value.size,) \
                or not bool(torch.all(torch.isfinite(score))) \
                or bool(torch.any(score < -MAX_SIGNED_LEVEL_UTILITY)) \
                or bool(torch.any(score > MAX_SIGNED_LEVEL_UTILITY)):
            raise WorldAfterstateV1ModelError(
                "successor score output drift")
        return score

    def forward(
            self, incumbent: SuccessorBatchV1,
            candidate: SuccessorBatchV1) -> torch.Tensor:
        if type(incumbent) is not SuccessorBatchV1 \
                or type(candidate) is not SuccessorBatchV1:
            raise WorldAfterstateV1ModelError(
                "advantage forward input drift")
        incumbent.validate()
        candidate.validate()
        if incumbent.size != candidate.size:
            raise WorldAfterstateV1ModelError(
                "advantage sibling batch-size drift")
        result = self._score(candidate) - self._score(incumbent)
        if result.shape != (incumbent.size,) \
                or not bool(torch.all(torch.isfinite(result))) \
                or bool(torch.any(result < -203.0)) \
                or bool(torch.any(result > 203.0)):
            raise WorldAfterstateV1ModelError("advantage output drift")
        return result


def new_world_afterstate_advantage_model(
        seed: int, shape: WorldAfterstateShapeV0) \
        -> WorldAfterstateAdvantageV1:
    """Deterministically initialize without advancing the global CPU RNG."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise WorldAfterstateV1ModelError("model seed must be an integer")
    shape.validate()
    cpu_state = torch.get_rng_state().clone()
    try:
        model = WorldAfterstateAdvantageV1(shape)
    finally:
        torch.set_rng_state(cpu_state)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    with torch.no_grad():
        for _, parameter in sorted(model.named_parameters()):
            parameter.uniform_(-INIT_SCALE, INIT_SCALE, generator=generator)
    return model


def advantage_loss(
        predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    return advantage_loss_rows(predictions, targets).mean()


def advantage_loss_rows(
        predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    if predictions.ndim != 1 or predictions.dtype != torch.float32 \
            or targets.shape != predictions.shape \
            or targets.dtype != torch.float32 \
            or not bool(torch.all(torch.isfinite(predictions))) \
            or not bool(torch.all(torch.isfinite(targets))) \
            or bool(torch.any(predictions < -203.0)) \
            or bool(torch.any(predictions > 203.0)) \
            or bool(torch.any(targets < -203.0)) \
            or bool(torch.any(targets > 203.0)):
        raise WorldAfterstateV1ModelError("advantage loss tensor drift")
    return nn.functional.smooth_l1_loss(
        predictions, targets, beta=1.0, reduction="none")


__all__ = [
    "MODEL_SCHEMA", "PAIR_EXAMPLE_SCHEMA", "AdvantageBatchV1",
    "AdvantageExampleV1", "SuccessorBatchV1", "WorldAfterstateAdvantageV1",
    "WorldAfterstateV1ModelError", "advantage_loss",
    "collate_advantage_examples", "new_world_afterstate_advantage_model",
]
