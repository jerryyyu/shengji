"""Compact state-only GRU/Transformer value network, plus an MLP fast path.

All architectures consume the same afterstate tensors and emit the same
ordered 204-category terminal distribution.  The GRU is the historical
throughput baseline; the Transformer is the preferred trajectory experiment.
The ``mlp`` architecture is the batched fast path for search consumers: it
reads the fixed-size public, world and perspective tensors only
(concatenated, ``feedforward_width -> width`` trunk, GELU, dropout); the
history tensors are validated for the shared batch contract and otherwise
ignored.  No architecture receives a candidate action or search-policy
feature.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Mapping

import numpy as np
import torch
from torch import nn

from .douzero_micro import HISTORY_EVENT_DIM, HISTORY_MAX_EVENTS
from .value_afterstate import (
    OUTCOME_CLASSES,
    PERSPECTIVE_DIM,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
)
from .encode import N_CARDS


MLP_INPUT_DIM = PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM


class ValueModelError(ValueError):
    """A model configuration, batch, or parameter state drifted."""


@dataclass(frozen=True)
class ValueModelConfig:
    architecture: str = "transformer"
    width: int = 64
    history_layers: int = 2
    attention_heads: int = 4
    feedforward_width: int = 128
    dropout: float = 0.0
    max_history: int = HISTORY_MAX_EVENTS
    outcome_classes: int = OUTCOME_CLASSES

    def validate(self) -> None:
        integer_fields = (
            self.width, self.history_layers, self.attention_heads,
            self.feedforward_width, self.max_history, self.outcome_classes)
        if type(self.architecture) is not str \
                or self.architecture not in ("transformer", "gru", "mlp"):
            raise ValueModelError("architecture must be transformer, gru or mlp")
        if any(type(value) is not int for value in integer_fields) \
                or isinstance(self.dropout, bool) \
                or not isinstance(self.dropout, (int, float)) \
                or not math.isfinite(float(self.dropout)) \
                or self.width < 8 or self.history_layers < 1 \
                or self.attention_heads < 1 \
                or self.width % self.attention_heads != 0 \
                or self.feedforward_width < self.width \
                or not 0.0 <= self.dropout < 1.0 \
                or self.max_history < 1 \
                or self.outcome_classes != OUTCOME_CLASSES:
            raise ValueModelError("model configuration drift")

    def payload(self) -> dict[str, object]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> "ValueModelConfig":
        if type(value) is not dict or set(value) != set(asdict(cls())):
            raise ValueModelError("model configuration schema drift")
        try:
            config = cls(**value)
        except TypeError as exc:
            raise ValueModelError("model configuration schema drift") from exc
        try:
            config.validate()
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueModelError):
                raise
            raise ValueModelError("model configuration drift") from exc
        return config


class ValueNetwork(nn.Module):
    """One state-only value model with a selectable history encoder."""

    def __init__(self, config: ValueModelConfig = ValueModelConfig()):
        super().__init__()
        config.validate()
        self.config = config
        width = config.width
        if config.architecture == "mlp":
            # The fast path: one trunk over the concatenated fixed-size
            # tensors; no history encoder is built.  The sequence
            # architectures below are constructed exactly as before.
            self.history_position = None
            self.history_encoder = None
            self.trunk = nn.Sequential(
                nn.Linear(MLP_INPUT_DIM, config.feedforward_width), nn.GELU(),
                nn.Dropout(config.dropout),
                nn.Linear(config.feedforward_width, width), nn.GELU(),
                nn.Dropout(config.dropout))
            self.head = nn.Linear(width, OUTCOME_CLASSES)
            return
        self.public_encoder = nn.Sequential(
            nn.Linear(PUBLIC_DIM, width), nn.ReLU(), nn.LayerNorm(width))
        self.world_encoder = nn.Sequential(
            nn.Linear(WORLD_RECEIVERS * N_CARDS, width), nn.ReLU(),
            nn.LayerNorm(width))
        self.perspective_encoder = nn.Sequential(
            nn.Linear(PERSPECTIVE_DIM, width), nn.ReLU(), nn.LayerNorm(width))
        self.history_input = nn.Linear(HISTORY_EVENT_DIM, width)
        if config.architecture == "transformer":
            self.history_position = nn.Embedding(config.max_history, width)
            layer = nn.TransformerEncoderLayer(
                d_model=width, nhead=config.attention_heads,
                dim_feedforward=config.feedforward_width,
                dropout=config.dropout, activation="gelu", batch_first=True)
            self.history_encoder: nn.Module = nn.TransformerEncoder(
                layer, num_layers=config.history_layers,
                enable_nested_tensor=False)
        else:
            self.history_position = None
            self.history_encoder = nn.GRU(
                width, width, num_layers=config.history_layers,
                dropout=(config.dropout if config.history_layers > 1 else 0.0),
                batch_first=True)
        self.fused = nn.Sequential(
            nn.Linear(4 * width, 2 * width), nn.GELU(),
            nn.LayerNorm(2 * width), nn.Linear(2 * width, OUTCOME_CLASSES))

    def features(self, public: torch.Tensor, world: torch.Tensor,
                 perspective: torch.Tensor) -> torch.Tensor:
        """The mlp trunk's ``width``-dim embedding of the fixed-size tensors
        (an auxiliary head may read it); the sequence architectures expose
        no intermediate."""
        if self.config.architecture != "mlp":
            raise ValueModelError("features are exposed by the mlp architecture only")
        return self.trunk(torch.cat(
            (public, world.flatten(start_dim=1), perspective), dim=1))

    def _history_context(self, history: torch.Tensor,
                         history_mask: torch.Tensor) -> torch.Tensor:
        encoded = self.history_input(history)
        if self.config.architecture == "transformer":
            positions = torch.arange(
                history.shape[1], device=history.device).unsqueeze(0)
            encoded = encoded + self.history_position(positions)
            encoded = self.history_encoder(
                encoded, src_key_padding_mask=~history_mask)
            weights = history_mask.unsqueeze(-1).to(encoded.dtype)
            return (encoded * weights).sum(dim=1) / weights.sum(dim=1)
        output, _hidden = self.history_encoder(encoded)
        last = history_mask.sum(dim=1) - 1
        return output[torch.arange(output.shape[0], device=output.device), last]

    def forward(self, public: torch.Tensor, history: torch.Tensor,
                history_mask: torch.Tensor, world: torch.Tensor,
                perspective: torch.Tensor) -> torch.Tensor:
        batch = public.shape[0]
        if public.shape != (batch, PUBLIC_DIM) \
                or history.ndim != 3 or history.shape[0] != batch \
                or history.shape[2] != HISTORY_EVENT_DIM \
                or history.shape[1] > self.config.max_history \
                or history_mask.shape != history.shape[:2] \
                or history_mask.dtype != torch.bool \
                or not bool(torch.all(history_mask.any(dim=1))) \
                or world.shape != (batch, WORLD_RECEIVERS, N_CARDS) \
                or perspective.shape != (batch, PERSPECTIVE_DIM):
            raise ValueModelError("model batch shape drift")
        if self.config.architecture == "mlp":
            return self.head(self.features(public, world, perspective))
        context = torch.cat((
            self.public_encoder(public),
            self._history_context(history, history_mask),
            self.world_encoder(world.flatten(start_dim=1)),
            self.perspective_encoder(perspective),
        ), dim=1)
        return self.fused(context)


def model_state_sha256(model: ValueNetwork) -> str:
    """Stable logical-state hash independent of checkpoint container bytes."""
    if type(model) is not ValueNetwork:
        raise ValueModelError("state hash requires an exact ValueNetwork")
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        array = value.detach().cpu().contiguous().numpy()
        if array.dtype.byteorder not in ("<", "|", "="):
            array = array.byteswap().view(array.dtype.newbyteorder("<"))
        elif array.dtype.byteorder == "=" and not np.little_endian:
            array = array.byteswap().view(array.dtype.newbyteorder("<"))
        label = name.encode("utf-8")
        shape = ",".join(str(size) for size in array.shape).encode("ascii")
        dtype = str(array.dtype.newbyteorder("<")).encode("ascii")
        payload = array.tobytes(order="C")
        for part in (label, shape, dtype, payload):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()
