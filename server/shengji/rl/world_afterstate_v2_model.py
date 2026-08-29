"""Structured, target-free absolute leaf value model for Value-Afterstate V2.

The only callable model input is :class:`WorldAfterstateV2Batch`.  In
particular, actions, incumbent identity, ballots, teachers, and experiment
metadata are deliberately not represented by this module's input contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch
from torch import nn

from ..engine.cards import RANKS, SUITS
from .douzero_micro import HISTORY_EVENT_DIM
from .encode import CARD_INDEX, N_CARDS
from .world_afterstate import (
    OUTCOME_CLASSES,
    PERSPECTIVE_DIM,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
    WorldAfterstateError,
    WorldAfterstateTensorsV0,
    category_signed_level,
)


MODEL_SCHEMA = "world-afterstate-value-v2-structured-absolute"
CARD_PLANES = 9
PUBLIC_CARD_DIM = CARD_PLANES * N_CARDS
PUBLIC_TAIL_DIM = PUBLIC_DIM - PUBLIC_CARD_DIM
EMBEDDING_DIM = 16
RELATIVE_EMBEDDING_DIM = 8
CARD_ZONE_WIDTH = 32
HISTORY_WIDTH = 32
PUBLIC_CONTEXT_WIDTH = 32
FUSED_WIDTH = 64


class WorldAfterstateV2ModelError(WorldAfterstateError):
    """A V2 model input, output, or objective was malformed."""


@dataclass(frozen=True)
class WorldAfterstateV2Batch:
    """Validated target-free batch; no outcome or action fields are present."""

    public: torch.Tensor
    history: torch.Tensor
    history_lengths: torch.Tensor
    world: torch.Tensor
    perspective: torch.Tensor

    def validate(self) -> None:
        if any(not isinstance(value, torch.Tensor) for value in (
                self.public, self.history, self.history_lengths, self.world,
                self.perspective)):
            raise WorldAfterstateV2ModelError("V2 batch tensor type drift")
        batch = self.public.shape[0] if self.public.ndim == 2 else -1
        if self.public.ndim != 2 or self.public.shape[0] < 1 \
                or self.public.shape[1] != PUBLIC_DIM \
                or self.public.dtype != torch.float32:
            raise WorldAfterstateV2ModelError("V2 public batch drift")
        if self.history.ndim != 3 or self.history.shape[0] != batch \
                or self.history.shape[2] != HISTORY_EVENT_DIM \
                or self.history.dtype != torch.float32:
            raise WorldAfterstateV2ModelError("V2 history batch drift")
        if self.history_lengths.shape != (batch,) \
                or self.history_lengths.dtype != torch.long \
                or bool(torch.any(self.history_lengths < 0)) \
                or bool(torch.any(self.history_lengths > self.history.shape[1])):
            raise WorldAfterstateV2ModelError("V2 history lengths drift")
        if self.world.shape != (batch, WORLD_RECEIVERS, N_CARDS) \
                or self.world.dtype != torch.float32:
            raise WorldAfterstateV2ModelError("V2 world batch drift")
        public_cards = self.public[:, :PUBLIC_CARD_DIM]
        if not bool(torch.all(
                (public_cards == 0.0) | (public_cards == 0.5)
                | (public_cards == 1.0))):
            raise WorldAfterstateV2ModelError(
                "V2 public card-plane encoding drift")
        if not bool(torch.all((self.world == 0.0) | (self.world == 0.5)
                              | (self.world == 1.0))):
            raise WorldAfterstateV2ModelError("V2 world encoding drift")
        if self.perspective.shape != (batch, PERSPECTIVE_DIM) \
                or self.perspective.dtype != torch.float32 \
                or not bool(torch.all((self.perspective == 0.0)
                                      | (self.perspective == 1.0))) \
                or not bool(torch.all(self.perspective.sum(dim=1) == 1.0)):
            raise WorldAfterstateV2ModelError("V2 perspective batch drift")
        if any(not bool(torch.all(torch.isfinite(value))) for value in (
                self.public, self.history, self.world, self.perspective)):
            raise WorldAfterstateV2ModelError("V2 batch contains non-finite value")

    @property
    def size(self) -> int:
        self.validate()
        return int(self.public.shape[0])


def collate_world_afterstate_tensors(
        values: Sequence[WorldAfterstateTensorsV0]) -> WorldAfterstateV2Batch:
    """Collate complete-state tensors without constructing or accepting labels."""
    if type(values) not in (list, tuple) or not values \
            or any(type(value) is not WorldAfterstateTensorsV0
                   for value in values):
        raise WorldAfterstateV2ModelError("V2 tensor population drift")
    for value in values:
        value.validate()
    max_events = max(len(value.history) for value in values)
    history = torch.zeros(
        (len(values), max_events, HISTORY_EVENT_DIM), dtype=torch.float32)
    for index, value in enumerate(values):
        if len(value.history):
            history[index, :len(value.history)] = torch.from_numpy(value.history)
    result = WorldAfterstateV2Batch(
        public=torch.as_tensor(np.stack([value.public for value in values]),
                               dtype=torch.float32),
        history=history,
        history_lengths=torch.as_tensor(
            [len(value.history) for value in values], dtype=torch.long),
        world=torch.as_tensor(np.stack([value.world for value in values]),
                              dtype=torch.float32),
        perspective=torch.as_tensor(
            np.stack([value.perspective for value in values]),
            dtype=torch.float32),
    )
    result.validate()
    return result


def _card_tables() -> tuple[torch.Tensor, torch.Tensor]:
    rank_ids: list[int] = []
    suit_ids: list[int] = []
    rank_map = {rank: index for index, rank in enumerate(RANKS)}
    suit_map = {suit: index for index, suit in enumerate(SUITS)}
    for card, _ in sorted(CARD_INDEX.items(), key=lambda item: item[1]):
        if card in ("LJ", "BJ"):
            rank_ids.append(13 + (card == "BJ"))
            suit_ids.append(4)
        else:
            rank_ids.append(rank_map[card[1:]])
            suit_ids.append(suit_map[card[0]])
    return (torch.tensor(rank_ids, dtype=torch.long),
            torch.tensor(suit_ids, dtype=torch.long))


class WorldAfterstateValueV2(nn.Module):
    """The fixed 16/8/32/32/32/64/204 structured V2 architecture."""

    def __init__(self):
        super().__init__()
        # A card representation is shared by public planes, world receivers,
        # and history card fields.  Jokers use two extra rank ids and one
        # shared joker suit id.
        self.rank_embedding = nn.Embedding(15, EMBEDDING_DIM)
        self.suit_embedding = nn.Embedding(5, EMBEDDING_DIM)
        self.card_embedding = nn.Embedding(N_CARDS, EMBEDDING_DIM)
        # Nine public zones followed by five relative world receivers.
        self.zone_embedding = nn.Embedding(CARD_PLANES + WORLD_RECEIVERS,
                                            RELATIVE_EMBEDDING_DIM)
        self.receiver_embedding = nn.Embedding(WORLD_RECEIVERS,
                                                RELATIVE_EMBEDDING_DIM)
        self.team_embedding = nn.Embedding(3, RELATIVE_EMBEDDING_DIM)
        self.perspective_embedding = nn.Embedding(PERSPECTIVE_DIM,
                                                   RELATIVE_EMBEDDING_DIM)
        self.card_zone_encoder = nn.Sequential(
            nn.Linear(EMBEDDING_DIM + RELATIVE_EMBEDDING_DIM * 4 + 1,
                      CARD_ZONE_WIDTH),
            nn.ReLU(),
        )
        self.history_event_encoder = nn.Sequential(
            nn.Linear(HISTORY_EVENT_DIM, CARD_ZONE_WIDTH), nn.ReLU())
        self.history_gru = nn.GRU(
            CARD_ZONE_WIDTH, HISTORY_WIDTH, batch_first=True)
        self.public_context_encoder = nn.Sequential(
            nn.Linear(PUBLIC_TAIL_DIM, PUBLIC_CONTEXT_WIDTH), nn.ReLU())
        # Three permutation-aware world contexts (team 0, team 1, burial),
        # plus public cards, history, non-card context, and perspective.
        fused_input = CARD_ZONE_WIDTH * 4 + HISTORY_WIDTH \
            + PUBLIC_CONTEXT_WIDTH + RELATIVE_EMBEDDING_DIM
        self.fused_trunk = nn.Sequential(
            nn.Linear(fused_input, FUSED_WIDTH), nn.ReLU())
        self.value_head = nn.Linear(FUSED_WIDTH, OUTCOME_CLASSES)
        rank_ids, suit_ids = _card_tables()
        self.register_buffer("card_rank_ids", rank_ids, persistent=False)
        self.register_buffer("card_suit_ids", suit_ids, persistent=False)

    def _card_base(self, device: torch.device) -> torch.Tensor:
        return (self.rank_embedding(self.card_rank_ids.to(device))
                + self.suit_embedding(self.card_suit_ids.to(device))
                + self.card_embedding(
                    torch.arange(N_CARDS, device=device, dtype=torch.long)))

    def _card_context(self, batch: WorldAfterstateV2Batch,
                      perspective_ids: torch.Tensor) -> tuple[torch.Tensor,
                                                               torch.Tensor]:
        device = batch.public.device
        size = batch.size
        base = self._card_base(device)
        card_zones = batch.public[:, :PUBLIC_CARD_DIM].reshape(
            size, CARD_PLANES, N_CARDS)
        world_zones = batch.world
        zone_ids_public = torch.arange(CARD_PLANES, device=device)
        # Receiver position remains visible: exchanging the actor's hand with
        # the partner's hand is a different state.  Partnership aggregation
        # happens only after the shared per-card/per-receiver encoder.
        zone_ids_world = torch.arange(
            CARD_PLANES, CARD_PLANES + WORLD_RECEIVERS, device=device)
        p_embed = self.perspective_embedding(perspective_ids)

        def encode(values: torch.Tensor, zone_ids: torch.Tensor,
                   receivers: torch.Tensor, teams: torch.Tensor) -> torch.Tensor:
            zones = self.zone_embedding(zone_ids)[None, :, None, :]
            rec = self.receiver_embedding(receivers)[None, :, None, :]
            team = self.team_embedding(teams)[None, :, None, :]
            p = p_embed[:, None, None, :]
            features = torch.cat([
                base[None, None, :, :].expand(size, values.shape[1], -1, -1),
                zones.expand(size, -1, N_CARDS, -1),
                rec.expand(size, -1, N_CARDS, -1),
                team.expand(size, -1, N_CARDS, -1),
                p.expand(size, values.shape[1], N_CARDS, -1),
                values.unsqueeze(-1),
            ], dim=-1)
            encoded = self.card_zone_encoder(features)
            return (encoded * values.unsqueeze(-1)).sum(dim=2)

        public = encode(
            card_zones, zone_ids_public,
            torch.zeros(CARD_PLANES, dtype=torch.long, device=device),
            torch.full((CARD_PLANES,), 2, dtype=torch.long, device=device),
        ).sum(dim=1)
        world_by_receiver = encode(
            world_zones, zone_ids_world,
            torch.arange(WORLD_RECEIVERS, dtype=torch.long, device=device),
            torch.tensor([0, 1, 0, 1, 2], dtype=torch.long, device=device),
        )
        # The sums are partnership-aware, while distinct receiver embeddings
        # preserve self/partner and clockwise/counter-clockwise roles.
        world = torch.cat([
            world_by_receiver[:, 0] + world_by_receiver[:, 2],
            world_by_receiver[:, 1] + world_by_receiver[:, 3],
            world_by_receiver[:, 4],
        ], dim=1)
        return public, world

    def forward(
            self, batch: WorldAfterstateV2Batch | torch.Tensor,
            history: torch.Tensor | None = None,
            history_lengths: torch.Tensor | None = None,
            world: torch.Tensor | None = None,
            perspective: torch.Tensor | None = None) -> torch.Tensor:
        # Accepting the five target-free tensors is convenient for inference
        # callers; the batch form is the canonical collator output.  Neither
        # form has an action/label/metadata slot.
        if type(batch) is WorldAfterstateV2Batch:
            if any(value is not None for value in (
                    history, history_lengths, world, perspective)):
                raise WorldAfterstateV2ModelError(
                    "V2 batch forward received extra inputs")
        elif isinstance(batch, torch.Tensor) and all(
                isinstance(value, torch.Tensor) for value in (
                    history, history_lengths, world, perspective)):
            batch = WorldAfterstateV2Batch(
                public=batch, history=history,
                history_lengths=history_lengths, world=world,
                perspective=perspective)
        else:
            raise WorldAfterstateV2ModelError(
                "V2 forward requires target-free batch input")
        batch.validate()
        perspective_ids = torch.argmax(batch.perspective, dim=1)
        public_cards, world = self._card_context(batch, perspective_ids)
        tail = self.public_context_encoder(batch.public[:, PUBLIC_CARD_DIM:])
        if batch.history.shape[1] == 0:
            history_context = torch.zeros(
                (batch.size, HISTORY_WIDTH), dtype=batch.public.dtype,
                device=batch.public.device)
        else:
            events = self.history_event_encoder(batch.history)
            sequence, _ = self.history_gru(events)
            indices = (batch.history_lengths - 1).clamp(min=0)
            selector = nn.functional.one_hot(
                indices, num_classes=sequence.shape[1]).to(sequence.dtype)
            history_context = torch.bmm(
                selector.unsqueeze(1), sequence).squeeze(1)
            history_context = torch.where(
                (batch.history_lengths > 0).unsqueeze(1), history_context,
                torch.zeros_like(history_context))
        perspective = self.perspective_embedding(perspective_ids)
        fused = self.fused_trunk(torch.cat([
            public_cards, world, history_context, tail, perspective,
        ], dim=1))
        logits = self.value_head(fused)
        if logits.shape != (batch.size, OUTCOME_CLASSES) \
                or not bool(torch.all(torch.isfinite(logits))):
            raise WorldAfterstateV2ModelError("V2 output drift")
        return logits


def count_trainable_parameters(model: nn.Module) -> int:
    if not isinstance(model, nn.Module):
        raise WorldAfterstateV2ModelError("parameter-count model type drift")
    return sum(parameter.numel() for parameter in model.parameters()
               if parameter.requires_grad)


def new_world_afterstate_v2_model(seed: int) -> WorldAfterstateValueV2:
    """Create deterministic weights while preserving the global CPU RNG state."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise WorldAfterstateV2ModelError("V2 model seed must be an integer")
    cpu_state = torch.get_rng_state().clone()
    try:
        model = WorldAfterstateValueV2()
    finally:
        torch.set_rng_state(cpu_state)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    with torch.no_grad():
        for _, parameter in sorted(model.named_parameters()):
            parameter.uniform_(-0.05, 0.05, generator=generator)
    return model


def _check_logits(logits: torch.Tensor) -> None:
    if not isinstance(logits, torch.Tensor) \
            or logits.ndim != 2 or logits.shape[0] < 1 \
            or logits.shape[1] != OUTCOME_CLASSES \
            or logits.dtype != torch.float32 \
            or not bool(torch.all(torch.isfinite(logits))):
        raise WorldAfterstateV2ModelError("V2 logits tensor drift")


def _check_labels(logits: torch.Tensor, labels: torch.Tensor) -> None:
    _check_logits(logits)
    if not isinstance(labels, torch.Tensor) \
            or labels.ndim != 1 or labels.shape[0] != logits.shape[0] \
            or labels.dtype != torch.long \
            or bool(torch.any(labels < 0)) \
            or bool(torch.any(labels >= OUTCOME_CLASSES)):
        raise WorldAfterstateV2ModelError("V2 outcome labels drift")


def absolute_cross_entropy_rows(logits: torch.Tensor,
                                labels: torch.Tensor) -> torch.Tensor:
    """Return normalized absolute NLL rows, with a uniform row equal to 1."""
    _check_labels(logits, labels)
    return -torch.gather(torch.log_softmax(logits, dim=1), 1,
                         labels[:, None]).squeeze(1) / np.log(OUTCOME_CLASSES)


def absolute_value_loss(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    return absolute_cross_entropy_rows(logits, labels).mean()


def expected_signed_utility(logits: torch.Tensor) -> torch.Tensor:
    _check_logits(logits)
    support = torch.as_tensor(
        [category_signed_level(index) for index in range(OUTCOME_CLASSES)],
        dtype=logits.dtype, device=logits.device)
    return torch.softmax(logits, dim=1) @ support


def paired_expectation_loss(
        candidate_logits: torch.Tensor, incumbent_logits: torch.Tensor,
        target_difference: torch.Tensor,
        sigma_pair_squared: float | torch.Tensor) -> torch.Tensor:
    """Normalized MSE of candidate-minus-incumbent expected utility."""
    _check_logits(candidate_logits)
    _check_logits(incumbent_logits)
    if not isinstance(target_difference, torch.Tensor) \
            or incumbent_logits.shape != candidate_logits.shape \
            or target_difference.ndim != 1 \
            or target_difference.shape[0] != candidate_logits.shape[0] \
            or target_difference.dtype != torch.float32 \
            or not bool(torch.all(torch.isfinite(target_difference))):
        raise WorldAfterstateV2ModelError("V2 paired target drift")
    if bool(torch.any(target_difference < -203.0)) \
            or bool(torch.any(target_difference > 203.0)):
        raise WorldAfterstateV2ModelError("V2 paired target range drift")
    if isinstance(sigma_pair_squared, torch.Tensor):
        if sigma_pair_squared.ndim != 0 or sigma_pair_squared.dtype \
                not in (torch.float32, torch.float64) \
                or not bool(torch.isfinite(sigma_pair_squared)) \
                or bool(sigma_pair_squared < 0):
            raise WorldAfterstateV2ModelError("V2 pair variance drift")
        denominator = torch.maximum(
            torch.ones((), dtype=candidate_logits.dtype,
                       device=candidate_logits.device),
            sigma_pair_squared.to(candidate_logits.device,
                                  dtype=candidate_logits.dtype))
    else:
        if isinstance(sigma_pair_squared, bool) \
                or not isinstance(sigma_pair_squared, (int, float)) \
                or not np.isfinite(sigma_pair_squared) \
                or sigma_pair_squared < 0:
            raise WorldAfterstateV2ModelError("V2 pair variance drift")
        denominator = torch.as_tensor(
            max(1.0, float(sigma_pair_squared)), dtype=candidate_logits.dtype,
            device=candidate_logits.device)
    prediction = expected_signed_utility(candidate_logits) \
        - expected_signed_utility(incumbent_logits)
    return (prediction - target_difference).square().mean() / denominator


def combined_value_loss(
        logits: torch.Tensor, labels: torch.Tensor,
        candidate_logits: torch.Tensor | None = None,
        incumbent_logits: torch.Tensor | None = None,
        target_difference: torch.Tensor | None = None,
        sigma_pair_squared: float | torch.Tensor = 1.0) -> torch.Tensor:
    """The fixed 1:1 absolute plus normalized paired-expectation objective."""
    absolute = absolute_value_loss(logits, labels)
    provided = (candidate_logits, incumbent_logits, target_difference)
    if all(value is None for value in provided):
        raise WorldAfterstateV2ModelError("V2 combined loss requires pair data")
    if any(value is None for value in provided):
        raise WorldAfterstateV2ModelError("V2 paired loss arguments incomplete")
    return absolute + paired_expectation_loss(
        candidate_logits, incumbent_logits, target_difference,
        sigma_pair_squared)


__all__ = [
    "MODEL_SCHEMA", "CARD_PLANES", "PUBLIC_CARD_DIM", "PUBLIC_TAIL_DIM",
    "OUTCOME_CLASSES",
    "WorldAfterstateV2Batch", "WorldAfterstateV2ModelError",
    "WorldAfterstateValueV2", "collate_world_afterstate_tensors",
    "new_world_afterstate_v2_model", "count_trainable_parameters",
    "absolute_cross_entropy_rows", "absolute_value_loss",
    "expected_signed_utility", "paired_expectation_loss",
    "combined_value_loss",
]
