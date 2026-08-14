"""Two-layer GRU ownership model mechanics for BELIEF-V1.

The model consumes only the target-blind tensors from ``belief_tensor`` and
emits masked receiver/count logits.  Privileged labels are accepted solely by
the explicit offline loss helper; inference and projection never accept them.
There is no checkpoint writer, trainer loop, corpus reader, sampler, policy,
gameplay, registry, or run surface here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import torch
from torch import nn

from .belief_contract import ActorObservationV1
from .belief_input import CARD_CODES
from .belief_ownership import BeliefOwnershipV1
from .belief_projection import (MAX_RAW_WEIGHT, RawCountWeightV1,
                                project_count_weights)
from .belief_tensor import (CARD_FEATURE_DIM, EVENT_FEATURE_DIM,
                            GLOBAL_FEATURE_DIM, MAX_RECEIVERS,
                            RECEIVER_FEATURE_DIM, HistoryOwnershipTensorsV1,
                            build_history_ownership_tensors)


MODEL_SCHEMA = "belief-v1-history-ownership-gru-128x2-v1"
EVENT_HIDDEN = 128
EVENT_LAYERS = 2
CARD_EMBEDDING = 16
CARD_HIDDEN = 64
GLOBAL_HIDDEN = 64
RECEIVER_HIDDEN = 32
HEAD_HIDDEN = 128
INIT_SCALE = 0.05
RAW_WEIGHT_SCALE = 10**12
MASKED_LOGIT = -1.0e9


class BeliefModelError(ValueError):
    """The V1 model, tensor batch, label, or inference contract drifted."""


def _shape(value: torch.Tensor, expected: tuple[int, ...], label: str) -> None:
    if not isinstance(value, torch.Tensor) or tuple(value.shape) != expected:
        raise BeliefModelError(f"{label} tensor shape drift")


class HistoryOwnershipModelV1(nn.Module):
    """One shared public-history model over card × hidden-receiver counts."""

    def __init__(self):
        super().__init__()
        self.event_encoder = nn.GRU(
            EVENT_FEATURE_DIM, EVENT_HIDDEN, num_layers=EVENT_LAYERS,
            batch_first=True)
        self.card_embedding = nn.Embedding(len(CARD_CODES), CARD_EMBEDDING)
        self.card_encoder = nn.Sequential(
            nn.Linear(CARD_FEATURE_DIM + CARD_EMBEDDING, CARD_HIDDEN),
            nn.ReLU())
        self.global_encoder = nn.Sequential(
            nn.Linear(GLOBAL_FEATURE_DIM, GLOBAL_HIDDEN), nn.ReLU())
        self.receiver_encoder = nn.Sequential(
            nn.Linear(RECEIVER_FEATURE_DIM, RECEIVER_HIDDEN), nn.ReLU())
        self.count_head = nn.Sequential(
            nn.Linear(EVENT_HIDDEN + CARD_HIDDEN + GLOBAL_HIDDEN
                      + RECEIVER_HIDDEN, HEAD_HIDDEN),
            nn.ReLU(),
            nn.Linear(HEAD_HIDDEN, 3),
        )

    def forward(
            self, events: torch.Tensor, event_lengths: torch.Tensor,
            global_features: torch.Tensor, card_features: torch.Tensor,
            receiver_features: torch.Tensor, receiver_mask: torch.Tensor,
            unseen_mask: torch.Tensor, count_minimums: torch.Tensor,
            count_maximums: torch.Tensor) -> torch.Tensor:
        if not isinstance(events, torch.Tensor) or events.ndim != 3 \
                or events.shape[2] != EVENT_FEATURE_DIM \
                or events.dtype != torch.float32:
            raise BeliefModelError("event tensor shape/dtype drift")
        batch, event_count, _ = events.shape
        _shape(event_lengths, (batch,), "event length")
        _shape(global_features, (batch, GLOBAL_FEATURE_DIM), "global")
        _shape(card_features,
               (batch, len(CARD_CODES), CARD_FEATURE_DIM), "card")
        _shape(receiver_features,
               (batch, MAX_RECEIVERS, RECEIVER_FEATURE_DIM), "receiver")
        _shape(receiver_mask, (batch, MAX_RECEIVERS), "receiver mask")
        _shape(unseen_mask, (batch, len(CARD_CODES)), "unseen mask")
        _shape(count_minimums,
               (batch, len(CARD_CODES), MAX_RECEIVERS), "count minimum")
        _shape(count_maximums,
               (batch, len(CARD_CODES), MAX_RECEIVERS), "count maximum")
        if event_lengths.dtype != torch.long \
                or receiver_mask.dtype != torch.bool \
                or unseen_mask.dtype != torch.bool \
                or count_minimums.dtype != torch.long \
                or count_maximums.dtype != torch.long \
                or any(value.dtype != torch.float32 for value in (
                    global_features, card_features, receiver_features)):
            raise BeliefModelError("model tensor dtype drift")
        if bool(torch.any(event_lengths < 0)) \
                or bool(torch.any(event_lengths > event_count)) \
                or bool(torch.any(count_minimums < 0)) \
                or bool(torch.any(count_maximums > 2)) \
                or bool(torch.any(count_minimums > count_maximums)):
            raise BeliefModelError("model tensor range drift")

        if event_count == 0:
            event_summary = torch.zeros(
                (batch, EVENT_HIDDEN), dtype=events.dtype,
                device=events.device)
        else:
            sequence, _ = self.event_encoder(events)
            indices = (event_lengths - 1).clamp(min=0)
            event_summary = sequence[
                torch.arange(batch, device=events.device), indices]
            event_summary = torch.where(
                (event_lengths > 0).unsqueeze(1), event_summary,
                torch.zeros_like(event_summary))

        card_ids = torch.arange(
            len(CARD_CODES), device=card_features.device)
        card_ids = card_ids.unsqueeze(0).expand(batch, -1)
        card_context = self.card_encoder(torch.cat(
            [self.card_embedding(card_ids), card_features], dim=2))
        global_context = self.global_encoder(global_features)
        receiver_context = self.receiver_encoder(receiver_features)

        event_expanded = event_summary[:, None, None, :].expand(
            -1, len(CARD_CODES), MAX_RECEIVERS, -1)
        global_expanded = global_context[:, None, None, :].expand(
            -1, len(CARD_CODES), MAX_RECEIVERS, -1)
        card_expanded = card_context[:, :, None, :].expand(
            -1, -1, MAX_RECEIVERS, -1)
        receiver_expanded = receiver_context[:, None, :, :].expand(
            -1, len(CARD_CODES), -1, -1)
        logits = self.count_head(torch.cat([
            event_expanded, global_expanded, card_expanded,
            receiver_expanded], dim=3))

        counts = torch.arange(3, device=logits.device)[None, None, None, :]
        active = unseen_mask[:, :, None] & receiver_mask[:, None, :]
        allowed = active[:, :, :, None] \
            & (counts >= count_minimums[:, :, :, None]) \
            & (counts <= count_maximums[:, :, :, None])
        return torch.where(
            allowed, logits, torch.full_like(logits, MASKED_LOGIT))


def new_from_scratch_model(seed: int) -> HistoryOwnershipModelV1:
    """Create deterministic parameters without advancing global Torch RNG."""
    if type(seed) is not int or seed < 0:
        raise BeliefModelError("model seed must be a nonnegative integer")
    cpu_state = torch.get_rng_state().clone()
    try:
        model = HistoryOwnershipModelV1()
    finally:
        torch.set_rng_state(cpu_state)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    with torch.no_grad():
        for _, parameter in sorted(model.named_parameters()):
            parameter.uniform_(-INIT_SCALE, INIT_SCALE, generator=generator)
    return model


def _single_batch(tensors: HistoryOwnershipTensorsV1) -> tuple[torch.Tensor, ...]:
    if type(tensors) is not HistoryOwnershipTensorsV1:
        raise BeliefModelError("inference requires exact V1 tensors")
    return (
        torch.from_numpy(tensors.events).unsqueeze(0),
        torch.tensor([len(tensors.events)], dtype=torch.long),
        torch.from_numpy(tensors.global_features).unsqueeze(0),
        torch.from_numpy(tensors.card_features).unsqueeze(0),
        torch.from_numpy(tensors.receiver_features).unsqueeze(0),
        torch.from_numpy(tensors.receiver_mask).unsqueeze(0),
        torch.from_numpy(tensors.unseen_mask).unsqueeze(0),
        torch.from_numpy(tensors.count_minimums).unsqueeze(0),
        torch.from_numpy(tensors.count_maximums).unsqueeze(0),
    )


def inference_logits(
        model: HistoryOwnershipModelV1,
        tensors: HistoryOwnershipTensorsV1) -> np.ndarray:
    """Return one exact CPU float32 logits cube without privileged inputs."""
    if type(model) is not HistoryOwnershipModelV1:
        raise BeliefModelError("inference model type drift")
    if any(parameter.device.type != "cpu" for parameter in model.parameters()):
        raise BeliefModelError("V1 inference is pinned to CPU")
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            logits = model(*_single_batch(tensors)).squeeze(0).cpu().numpy()
    finally:
        model.train(was_training)
    if logits.dtype != np.float32 \
            or logits.shape != (len(CARD_CODES), MAX_RECEIVERS, 3) \
            or not np.all(np.isfinite(logits)):
        raise BeliefModelError("inference logits shape/dtype/finiteness drift")
    return np.ascontiguousarray(logits)


def quantize_raw_count_weights(
        tensors: HistoryOwnershipTensorsV1,
        logits: np.ndarray) -> tuple[RawCountWeightV1, ...]:
    """Convert allowed logits to deterministic positive fixed integer weights."""
    if type(tensors) is not HistoryOwnershipTensorsV1 \
            or type(logits) is not np.ndarray \
            or logits.dtype != np.float32 \
            or logits.shape != (len(CARD_CODES), MAX_RECEIVERS, 3) \
            or not np.all(np.isfinite(logits)):
        raise BeliefModelError("raw-logit quantization input drift")
    rows = []
    receiver_count = int(tensors.receiver_mask.sum())
    for card_index, card in enumerate(CARD_CODES):
        if not tensors.unseen_mask[card_index]:
            continue
        for receiver_index in range(receiver_count):
            lower = int(tensors.count_minimums[card_index, receiver_index])
            upper = int(tensors.count_maximums[card_index, receiver_index])
            allowed = logits[card_index, receiver_index, lower:upper + 1]
            shifted = allowed.astype(np.float64) - float(np.max(allowed))
            weights = np.maximum(
                1, np.rint(np.exp(shifted) * RAW_WEIGHT_SCALE).astype(
                    np.int64))
            values = [0, 0, 0]
            values[lower:upper + 1] = [int(value) for value in weights]
            if any(not 0 <= value <= MAX_RAW_WEIGHT for value in values):
                raise BeliefModelError("quantized raw weight exceeds V1 cap")
            rows.append(RawCountWeightV1(
                card=card,
                receiver=("hidden-kitty" if receiver_index == 3 else
                          f"seat-relative-{receiver_index + 1}"),
                count_weights=tuple(values),
            ))
    return tuple(rows)


def predict_ownership(
        model: HistoryOwnershipModelV1, actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...],
        model_sha256: str) -> BeliefOwnershipV1:
    """Target-blind inference followed by the exact ownership projection."""
    tensors = build_history_ownership_tensors(
        actor, behavior_policy_ids=behavior_policy_ids)
    logits = inference_logits(model, tensors)
    raw = quantize_raw_count_weights(tensors, logits)
    return project_count_weights(
        actor, behavior_policy_ids=behavior_policy_ids,
        model_schema=MODEL_SCHEMA, model_sha256=model_sha256,
        raw_weights=raw)


def masked_count_cross_entropy(
        logits: torch.Tensor, labels: torch.Tensor,
        active_mask: torch.Tensor,
        count_minimums: torch.Tensor,
        count_maximums: torch.Tensor) -> torch.Tensor:
    """Offline supervised loss; this is the only privileged-label inlet."""
    if not isinstance(logits, torch.Tensor) or logits.ndim != 4 \
            or logits.shape[-1] != 3:
        raise BeliefModelError("training logits shape drift")
    expected = tuple(logits.shape[:3])
    _shape(labels, expected, "training label")
    _shape(active_mask, expected, "training active mask")
    _shape(count_minimums, expected, "training count minimum")
    _shape(count_maximums, expected, "training count maximum")
    if labels.dtype != torch.long or active_mask.dtype != torch.bool \
            or count_minimums.dtype != torch.long \
            or count_maximums.dtype != torch.long:
        raise BeliefModelError("training label/mask dtype drift")
    if not bool(torch.any(active_mask)) \
            or bool(torch.any(labels[active_mask] < 0)) \
            or bool(torch.any(labels[active_mask] > 2)) \
            or bool(torch.any(labels[~active_mask] != -1)) \
            or bool(torch.any(labels[active_mask]
                              < count_minimums[active_mask])) \
            or bool(torch.any(labels[active_mask]
                              > count_maximums[active_mask])):
        raise BeliefModelError("training label population/bounds drift")
    return nn.functional.cross_entropy(
        logits[active_mask], labels[active_mask], reduction="mean")
