"""Target-blind fixed tensors for the BELIEF-V1 ownership GRU.

The tensorizer consumes only ``ActorObservationV1`` through the validated
``HistoryOwnershipInputV1``.  It does not accept targets, sampled worlds,
files, RNG, models, policies, or gameplay objects.  Every array has a frozen
shape/dtype and can be independently rederived from the actor bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..ai.point_context import EFF_SUITS
from ..engine.cards import RANKS
from .belief_contract import ActorObservationV1
from .belief_input import (CARD_CODES, HistoryOwnershipInputV1,
                           build_history_ownership_input)


TENSOR_SCHEMA = "belief-v1-history-ownership-tensors-v1"
MAX_RECEIVERS = 4
CARD_COUNT_SCALE = 2.0
HAND_SIZE_SCALE = 33.0
POINT_SCALE = 200.0
LEVEL_SCALE = 20.0
CAP_SCALE = 16.0

EVENT_FEATURE_DIM = 191
GLOBAL_FEATURE_DIM = 38
CARD_FEATURE_DIM = 23
RECEIVER_FEATURE_DIM = 30

_EVENT_KINDS = ("declaration", "play")
_TRUMP_SUITS = ("C", "D", "H", "S", None)


class BeliefTensorError(ValueError):
    """A target-blind tensor or its source binding is malformed."""


def _one_hot(value: Any, values: tuple[Any, ...]) -> list[float]:
    if value not in values:
        raise BeliefTensorError(f"tensor categorical value {value!r} drift")
    return [1.0 if value == candidate else 0.0 for candidate in values]


def _counts_vector(items: tuple[tuple[str, int], ...]) -> list[float]:
    counts = dict(items)
    if len(counts) != len(items) or any(
            card not in CARD_CODES or type(count) is not int
            or count not in (1, 2) for card, count in items):
        raise BeliefTensorError("tensor event card counts are malformed")
    return [counts.get(card, 0) / CARD_COUNT_SCALE for card in CARD_CODES]


@dataclass(frozen=True)
class HistoryOwnershipTensorsV1:
    actor_observation_sha256: str
    history_input_sha256: str
    behavior_policy_ids: tuple[str, ...]
    events: np.ndarray
    global_features: np.ndarray
    card_features: np.ndarray
    receiver_features: np.ndarray
    receiver_mask: np.ndarray
    unseen_mask: np.ndarray
    count_minimums: np.ndarray
    count_maximums: np.ndarray
    schema: str = TENSOR_SCHEMA


def _events(model_input: HistoryOwnershipInputV1) -> np.ndarray:
    rows = []
    for event in model_input.events:
        row = [
            *_one_hot(event.event_kind, _EVENT_KINDS),
            *_one_hot(event.seat_relative, tuple(range(4))),
            *_one_hot(event.trick_position, tuple(range(-1, 4))),
            *_one_hot(event.trick_leader_relative, tuple(range(-1, 4))),
            *_one_hot(event.trick_winner_relative, tuple(range(-1, 4))),
            *_one_hot(event.declaration_strength, tuple(range(5))),
            float(event.failed_throw),
            (event.trick_index + 1) / 26.0,
            event.trick_points / POINT_SCALE,
            *_counts_vector(event.shown_cards),
            *_counts_vector(event.attempted_cards),
            *_counts_vector(event.actual_cards),
        ]
        if len(row) != EVENT_FEATURE_DIM:
            raise BeliefTensorError("event feature dimension drift")
        rows.append(row)
    result = np.asarray(rows, dtype=np.float32)
    if not rows:
        result = np.empty((0, EVENT_FEATURE_DIM), dtype=np.float32)
    return result


def _global(model_input: HistoryOwnershipInputV1) -> np.ndarray:
    points_by_suit = dict(model_input.points_left_by_suit)
    row = [
        *_one_hot(model_input.banker_relative, tuple(range(4))),
        float(model_input.actor_is_attacker),
        model_input.attacker_points / POINT_SCALE,
        *_one_hot(model_input.trump_rank, tuple(RANKS)),
        *_one_hot(model_input.trump_suit, _TRUMP_SUITS),
        *(size / HAND_SIZE_SCALE for size in model_input.hand_sizes_relative),
        model_input.trick_points / POINT_SCALE,
        model_input.points_left_total / POINT_SCALE,
        *(points_by_suit[suit] / POINT_SCALE for suit in EFF_SUITS),
        *(distance / POINT_SCALE for distance in model_input.bracket_distance),
    ]
    if len(row) != GLOBAL_FEATURE_DIM:
        raise BeliefTensorError("global feature dimension drift")
    return np.asarray(row, dtype=np.float32)


def _receivers(model_input: HistoryOwnershipInputV1) -> tuple[
        np.ndarray, np.ndarray]:
    rows = np.zeros(
        (MAX_RECEIVERS, RECEIVER_FEATURE_DIM), dtype=np.float32)
    mask = np.zeros(MAX_RECEIVERS, dtype=np.bool_)
    for index, receiver in enumerate(model_input.receivers):
        if index >= MAX_RECEIVERS:
            raise BeliefTensorError("receiver population exceeds tensor cap")
        pair_caps = dict(receiver.pair_caps)
        run_caps = dict(receiver.run_caps)
        row = [
            *_one_hot(index, tuple(range(MAX_RECEIVERS))),
            receiver.card_count / HAND_SIZE_SCALE,
            *(float(suit in receiver.proven_void_suits)
              for suit in EFF_SUITS),
            *(float(suit in pair_caps) for suit in EFF_SUITS),
            *(pair_caps.get(suit, 0) / CAP_SCALE for suit in EFF_SUITS),
            *(float(suit in run_caps) for suit in EFF_SUITS),
            *(run_caps.get(suit, 0) / CAP_SCALE for suit in EFF_SUITS),
        ]
        if len(row) != RECEIVER_FEATURE_DIM:
            raise BeliefTensorError("receiver feature dimension drift")
        rows[index] = row
        mask[index] = True
    return rows, mask


def _cards(model_input: HistoryOwnershipInputV1) -> tuple[
        np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rows = np.zeros((len(CARD_CODES), CARD_FEATURE_DIM), dtype=np.float32)
    unseen = np.zeros(len(CARD_CODES), dtype=np.bool_)
    minimums = np.zeros((len(CARD_CODES), MAX_RECEIVERS), dtype=np.int64)
    maximums = np.zeros((len(CARD_CODES), MAX_RECEIVERS), dtype=np.int64)
    if tuple(card.card for card in model_input.card_facts) != CARD_CODES:
        raise BeliefTensorError("card fact population/order drift")
    receiver_count = len(model_input.receivers)
    for index, card in enumerate(model_input.card_facts):
        if card.card_index != index \
                or len(card.min_count_by_receiver) != receiver_count \
                or len(card.max_count_by_receiver) != receiver_count \
                or type(card.required_receiver_group) is not tuple \
                or any(receiver not in {
                    row.receiver for row in model_input.receivers}
                       for receiver in card.required_receiver_group) \
                or type(card.required_receiver_group_min_count) is not int \
                or card.required_receiver_group_min_count not in (0, 1, 2) \
                or bool(card.required_receiver_group) != bool(
                    card.required_receiver_group_min_count):
            raise BeliefTensorError("card fact identity/bound population drift")
        row = [
            *_one_hot(card.effective_suit, tuple(EFF_SUITS)),
            card.level / LEVEL_SCALE,
            card.point_value / 10.0,
            card.actor_hand_count / CARD_COUNT_SCALE,
            card.actor_known_burial_count / CARD_COUNT_SCALE,
            card.played_count / CARD_COUNT_SCALE,
            *(count / CARD_COUNT_SCALE
              for count in card.played_by_relative),
            card.unseen_count / CARD_COUNT_SCALE,
            *(count / CARD_COUNT_SCALE
              for count in (*card.min_count_by_receiver,
                            *(0,) * (MAX_RECEIVERS - receiver_count))),
            *(count / CARD_COUNT_SCALE
              for count in (*card.max_count_by_receiver,
                            *(0,) * (MAX_RECEIVERS - receiver_count))),
        ]
        if len(row) != CARD_FEATURE_DIM:
            raise BeliefTensorError("card feature dimension drift")
        rows[index] = row
        unseen[index] = card.unseen_count > 0
        minimums[index, :receiver_count] = card.min_count_by_receiver
        maximums[index, :receiver_count] = card.max_count_by_receiver
    return rows, unseen, minimums, maximums


def _tensorize(model_input: HistoryOwnershipInputV1) \
        -> HistoryOwnershipTensorsV1:
    events = _events(model_input)
    global_features = _global(model_input)
    receiver_features, receiver_mask = _receivers(model_input)
    card_features, unseen_mask, minimums, maximums = _cards(model_input)
    arrays = (events, global_features, card_features, receiver_features,
              receiver_mask, unseen_mask, minimums, maximums)
    if any(not array.flags.c_contiguous for array in arrays) \
            or any(np.issubdtype(array.dtype, np.floating)
                   and not np.all(np.isfinite(array)) for array in arrays):
        raise BeliefTensorError("tensor layout or finiteness drift")
    return HistoryOwnershipTensorsV1(
        actor_observation_sha256=model_input.actor_observation_sha256,
        history_input_sha256=model_input.sha256(),
        behavior_policy_ids=model_input.behavior_policy_ids,
        events=events,
        global_features=global_features,
        card_features=card_features,
        receiver_features=receiver_features,
        receiver_mask=receiver_mask,
        unseen_mask=unseen_mask,
        count_minimums=minimums,
        count_maximums=maximums,
    )


def build_history_ownership_tensors(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...]) -> HistoryOwnershipTensorsV1:
    """Build and independently rederive exact target-blind model tensors."""
    model_input = build_history_ownership_input(
        actor, behavior_policy_ids=behavior_policy_ids)
    result = _tensorize(model_input)
    validate_history_ownership_tensors(actor, result)
    return result


def validate_history_ownership_tensors(
        actor: ActorObservationV1,
        candidate: HistoryOwnershipTensorsV1) -> None:
    if type(candidate) is not HistoryOwnershipTensorsV1 \
            or candidate.schema != TENSOR_SCHEMA:
        raise BeliefTensorError("tensor schema drift")
    model_input = build_history_ownership_input(
        actor, behavior_policy_ids=candidate.behavior_policy_ids)
    expected = _tensorize(model_input)
    scalar_fields = (
        "schema", "actor_observation_sha256", "history_input_sha256",
        "behavior_policy_ids",
    )
    if any(getattr(candidate, field) != getattr(expected, field)
           for field in scalar_fields):
        raise BeliefTensorError("tensor source binding drift")
    array_fields = (
        "events", "global_features", "card_features", "receiver_features",
        "receiver_mask", "unseen_mask", "count_minimums", "count_maximums",
    )
    if any(type(getattr(candidate, field)) is not np.ndarray
           or getattr(candidate, field).dtype != getattr(expected, field).dtype
           or getattr(candidate, field).shape != getattr(expected, field).shape
           or not np.array_equal(getattr(candidate, field),
                                 getattr(expected, field))
           for field in array_fields):
        raise BeliefTensorError("tensor derivation drift")
