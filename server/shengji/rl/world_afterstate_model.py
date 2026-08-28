"""Parametric mechanics for the V0 complete-world successor value head.

Model widths remain explicit inputs until a score-free capacity receipt picks
one frozen shape.  The model has one output only: 204 signed-level logits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch
from torch import nn

from .douzero_micro import HISTORY_EVENT_DIM
from .encode import N_CARDS
from .world_afterstate import (OUTCOME_CLASSES, PERSPECTIVE_DIM, PUBLIC_DIM,
                               WORLD_RECEIVERS, WorldAfterstateError,
                               category_signed_level)


MODEL_SCHEMA = "world-afterstate-value-v0"
INIT_SCALE = 0.05


@dataclass(frozen=True)
class WorldAfterstateShapeV0:
    public_hidden: int
    history_hidden: int
    world_hidden: int
    perspective_hidden: int
    head_hidden: int

    def validate(self) -> None:
        values = (
            self.public_hidden, self.history_hidden, self.world_hidden,
            self.perspective_hidden, self.head_hidden,
        )
        if any(isinstance(value, bool) or not isinstance(value, int)
               or not 1 <= value <= 4096 for value in values):
            raise WorldAfterstateError("model shape is outside capacity bounds")


CAPACITY_SHAPES = {
    "small": WorldAfterstateShapeV0(64, 32, 64, 8, 128),
    "medium": WorldAfterstateShapeV0(128, 64, 128, 8, 256),
    "large": WorldAfterstateShapeV0(256, 128, 256, 16, 512),
}


class WorldAfterstateValueV0(nn.Module):
    """Distributional value of an engine-reached complete-world successor."""

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
        self.value_head = nn.Sequential(
            nn.Linear(shape.public_hidden + shape.history_hidden
                      + shape.world_hidden + shape.perspective_hidden,
                      shape.head_hidden),
            nn.ReLU(),
            nn.Linear(shape.head_hidden, OUTCOME_CLASSES),
        )

    def forward(
            self, public: torch.Tensor, history: torch.Tensor,
            history_lengths: torch.Tensor, world: torch.Tensor,
            perspective: torch.Tensor) -> torch.Tensor:
        if public.ndim != 2 or public.shape[1] != PUBLIC_DIM \
                or public.dtype != torch.float32:
            raise WorldAfterstateError("public batch tensor drift")
        batch = public.shape[0]
        if history.ndim != 3 or history.shape[0] != batch \
                or history.shape[2] != HISTORY_EVENT_DIM \
                or history.dtype != torch.float32:
            raise WorldAfterstateError("history batch tensor drift")
        if history_lengths.shape != (batch,) \
                or history_lengths.dtype != torch.long \
                or bool(torch.any(history_lengths < 0)) \
                or bool(torch.any(history_lengths > history.shape[1])):
            raise WorldAfterstateError("history length tensor drift")
        if world.shape != (batch, WORLD_RECEIVERS, N_CARDS) \
                or world.dtype != torch.float32:
            raise WorldAfterstateError("world batch tensor drift")
        if perspective.shape != (batch, PERSPECTIVE_DIM) \
                or perspective.dtype != torch.float32:
            raise WorldAfterstateError("perspective batch tensor drift")
        if any(not bool(torch.all(torch.isfinite(value))) for value in (
                public, history, world, perspective)):
            raise WorldAfterstateError("model input contains a non-finite value")
        if not bool(torch.all((world == 0.0) | (world == 0.5)
                              | (world == 1.0))):
            raise WorldAfterstateError("model world count encoding drift")
        if not bool(torch.all((perspective == 0.0) | (perspective == 1.0))) \
                or not bool(torch.all(perspective.sum(dim=1) == 1.0)):
            raise WorldAfterstateError("model perspective is not one-hot")
        public_context = self.public_encoder(public)
        if history.shape[1] == 0:
            history_context = torch.zeros(
                (batch, self.shape.history_hidden), dtype=public.dtype,
                device=public.device)
        else:
            sequence, _ = self.history_encoder(history)
            indices = (history_lengths - 1).clamp(min=0)
            selector = nn.functional.one_hot(
                indices, num_classes=history.shape[1]).to(sequence.dtype)
            history_context = torch.bmm(
                selector.unsqueeze(1), sequence).squeeze(1)
            history_context = torch.where(
                (history_lengths > 0).unsqueeze(1), history_context,
                torch.zeros_like(history_context))
        world_context = self.world_encoder(world.flatten(start_dim=1))
        perspective_context = self.perspective_encoder(perspective)
        return self.value_head(torch.cat([
            public_context, history_context, world_context,
            perspective_context,
        ], dim=1))


def new_world_afterstate_model(
        seed: int, shape: WorldAfterstateShapeV0) -> WorldAfterstateValueV0:
    """Deterministically initialize without advancing the global CPU RNG."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise WorldAfterstateError("model seed must be an integer")
    shape.validate()
    cpu_state = torch.get_rng_state().clone()
    try:
        model = WorldAfterstateValueV0(shape)
    finally:
        torch.set_rng_state(cpu_state)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    with torch.no_grad():
        for _, parameter in sorted(model.named_parameters()):
            parameter.uniform_(-INIT_SCALE, INIT_SCALE, generator=generator)
    return model


def collate_world_afterstates(examples: Sequence[object]) \
        -> tuple[torch.Tensor, ...]:
    """Collate validated tensors and mechanically derived category labels."""
    from .world_afterstate import WorldAfterstateExampleV0

    if type(examples) not in (list, tuple) or not examples:
        raise WorldAfterstateError("afterstate batch must not be empty")
    tensors = []
    labels = []
    for example in examples:
        if not isinstance(example, WorldAfterstateExampleV0):
            raise WorldAfterstateError("afterstate batch example type drift")
        example.validate()
        tensors.append(example.tensors)
        labels.append(example.signed_level_category)
    max_events = max(len(tensor.history) for tensor in tensors)
    history = torch.zeros(
        (len(tensors), max_events, HISTORY_EVENT_DIM), dtype=torch.float32)
    for index, tensor in enumerate(tensors):
        if len(tensor.history):
            history[index, :len(tensor.history)] = torch.from_numpy(
                tensor.history)
    return (
        torch.as_tensor(
            np.stack([tensor.public for tensor in tensors]),
            dtype=torch.float32),
        history,
        torch.as_tensor([len(tensor.history) for tensor in tensors],
                        dtype=torch.long),
        torch.as_tensor(
            np.stack([tensor.world for tensor in tensors]),
            dtype=torch.float32),
        torch.as_tensor(
            np.stack([tensor.perspective for tensor in tensors]),
            dtype=torch.float32),
        torch.as_tensor(labels, dtype=torch.long),
    )


def distributional_value_loss(logits: torch.Tensor,
                              labels: torch.Tensor) -> torch.Tensor:
    if logits.ndim != 2 or logits.shape[1] != OUTCOME_CLASSES \
            or logits.dtype != torch.float32 or labels.shape != (logits.shape[0],) \
            or labels.dtype != torch.long \
            or bool(torch.any(labels < 0)) \
            or bool(torch.any(labels >= OUTCOME_CLASSES)):
        raise WorldAfterstateError("distributional value loss tensor drift")
    return nn.functional.cross_entropy(logits, labels)


def proper_score_rows(logits: torch.Tensor, labels: torch.Tensor) \
        -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Per-raw-outcome NLL, categorical Brier, and expected utility error."""
    _ = distributional_value_loss(logits, labels)
    if not bool(torch.all(torch.isfinite(logits))):
        raise WorldAfterstateError("proper-score logits are non-finite")
    log_probabilities = torch.log_softmax(logits, dim=1)
    probabilities = torch.exp(log_probabilities)
    one_hot = nn.functional.one_hot(
        labels, num_classes=OUTCOME_CLASSES).to(probabilities.dtype)
    nll = -torch.gather(
        log_probabilities, 1, labels.unsqueeze(1)).squeeze(1)
    brier = torch.sum((probabilities - one_hot).square(), dim=1)
    support = torch.as_tensor(
        [category_signed_level(index) for index in range(OUTCOME_CLASSES)],
        dtype=probabilities.dtype, device=probabilities.device)
    expected = probabilities @ support
    truth = support[labels]
    return nll, brier, torch.abs(expected - truth)
