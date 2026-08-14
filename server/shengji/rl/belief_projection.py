"""Deterministic exact-conservation projection for ownership count weights.

The learned network may emit arbitrary positive integer weights for allowed
count categories 0/1/2.  This module performs deterministic KL-style matrix
scaling in the pinned NumPy runtime, rounds the expected-count matrix with a
deterministic integral flow, and reconstructs count probabilities whose mass,
per-card copies, per-receiver sizes, hard zeros, and hard minimums are exact at
one-part-per-billion resolution.

It consumes ``ActorObservationV1`` only through the target-blind
``HistoryOwnershipInputV1``.  It has no target, sampler, RNG, torch, file,
policy, or execution surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .belief_contract import ActorObservationV1
from .belief_input import (CardFactV1, HistoryOwnershipInputV1,
                           build_history_ownership_input)
from .belief_ownership import (PROBABILITY_SCALE, BeliefOwnershipV1,
                               ReceiverCountProbabilityV1,
                               validate_ownership)


RAW_WEIGHT_SCHEMA = "belief-v1-raw-receiver-count-weight-v1"
MAX_RAW_WEIGHT = 10**18


class BeliefProjectionError(ValueError):
    """Raw weights or their exact constrained projection are invalid."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class RawCountWeightV1:
    card: str
    receiver: str
    count_weights: tuple[int, int, int]
    schema: str = RAW_WEIGHT_SCHEMA


def uniform_raw_count_weights(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...]) -> tuple[RawCountWeightV1, ...]:
    """Return equal positive weights over every mechanically allowed count."""
    model_input = build_history_ownership_input(
        actor, behavior_policy_ids=behavior_policy_ids)
    rows = []
    for card in model_input.card_facts:
        if not card.unseen_count:
            continue
        for index, receiver in enumerate(model_input.receivers):
            lower = card.min_count_by_receiver[index]
            upper = card.max_count_by_receiver[index]
            rows.append(RawCountWeightV1(
                card=card.card,
                receiver=receiver.receiver,
                count_weights=tuple(
                    1 if lower <= count <= upper else 0
                    for count in range(3)),
            ))
    return tuple(rows)


def _validate_weights(
        model_input: HistoryOwnershipInputV1,
        raw_weights: tuple[RawCountWeightV1, ...]) -> tuple[
            tuple[CardFactV1, ...], list[list[tuple[int, int, int]]]]:
    cards = tuple(row for row in model_input.card_facts if row.unseen_count)
    expected_keys = tuple(
        (card.card, receiver.receiver)
        for card in cards for receiver in model_input.receivers)
    if type(raw_weights) is not tuple \
            or tuple((row.card, row.receiver) for row in raw_weights
                     if type(row) is RawCountWeightV1) != expected_keys \
            or len(raw_weights) != len(expected_keys):
        raise BeliefProjectionError("raw count-weight population/order drift")
    matrix: list[list[tuple[int, int, int]]] = []
    offset = 0
    for card in cards:
        card_rows = []
        for receiver_index, _ in enumerate(model_input.receivers):
            row = raw_weights[offset]
            offset += 1
            if row.schema != RAW_WEIGHT_SCHEMA \
                    or type(row.count_weights) is not tuple \
                    or len(row.count_weights) != 3 \
                    or any(type(weight) is not int
                           or not 0 <= weight <= MAX_RAW_WEIGHT
                           for weight in row.count_weights):
                raise BeliefProjectionError("raw count-weight row is malformed")
            lower = card.min_count_by_receiver[receiver_index]
            upper = card.max_count_by_receiver[receiver_index]
            for count, weight in enumerate(row.count_weights):
                allowed = lower <= count <= upper
                if (allowed and weight <= 0) or (not allowed and weight != 0):
                    raise BeliefProjectionError(
                        "raw weights disagree with hard count bounds")
            card_rows.append(row.count_weights)
        matrix.append(card_rows)
    return cards, matrix


def _fractional_expectations(
        cards: tuple[CardFactV1, ...],
        model_input: HistoryOwnershipInputV1,
        weights: list[list[tuple[int, int, int]]]) -> tuple[
            list[list[float]], np.ndarray]:
    n_cards = len(cards)
    n_receivers = len(model_input.receivers)
    log_weights = np.full((n_cards, n_receivers, 3), -np.inf,
                          dtype=np.float64)
    lower = np.empty((n_cards, n_receivers), dtype=np.int8)
    upper = np.empty((n_cards, n_receivers), dtype=np.int8)
    for card_index, card in enumerate(cards):
        for receiver_index in range(n_receivers):
            lower[card_index, receiver_index] = (
                card.min_count_by_receiver[receiver_index])
            upper[card_index, receiver_index] = (
                card.max_count_by_receiver[receiver_index])
            for count in range(lower[card_index, receiver_index],
                               upper[card_index, receiver_index] + 1):
                log_weights[card_index, receiver_index, count] = np.log(
                    weights[card_index][receiver_index][count])
    counts = np.arange(3, dtype=np.float64)[None, None, :]
    card_target = np.array([card.unseen_count for card in cards],
                           dtype=np.float64)
    receiver_target = np.array(
        [receiver.card_count for receiver in model_input.receivers],
        dtype=np.float64)
    if np.any(card_target < lower.sum(axis=1)) \
            or np.any(card_target > upper.sum(axis=1)) \
            or np.any(receiver_target < lower.sum(axis=0)) \
            or np.any(receiver_target > upper.sum(axis=0)):
        raise BeliefProjectionError("projection margin is infeasible")
    card_bias = np.zeros(n_cards, dtype=np.float64)
    receiver_bias = np.zeros(n_receivers, dtype=np.float64)

    def evaluate() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        scores = log_weights + counts * (
            card_bias[:, None, None] + receiver_bias[None, :, None])
        maximum = np.max(scores, axis=2, keepdims=True)
        mass = np.exp(scores - maximum)
        mass /= mass.sum(axis=2, keepdims=True)
        expected = (mass * counts).sum(axis=2)
        variance = (mass * counts * counts).sum(axis=2) - expected * expected
        return mass, expected, variance

    for _ in range(512):
        _, expected, variance = evaluate()
        residual = card_target - expected.sum(axis=1)
        curvature = variance.sum(axis=1)
        movable = curvature > 1e-15
        if np.any(~movable & (np.abs(residual) > 1e-10)):
            raise BeliefProjectionError("card projection margin is fixed wrong")
        card_bias[movable] += np.clip(
            residual[movable] / curvature[movable], -4.0, 4.0)

        _, expected, variance = evaluate()
        residual = receiver_target - expected.sum(axis=0)
        curvature = variance.sum(axis=0)
        movable = curvature > 1e-15
        if np.any(~movable & (np.abs(residual) > 1e-10)):
            raise BeliefProjectionError(
                "receiver projection margin is fixed wrong")
        receiver_bias[movable] += np.clip(
            residual[movable] / curvature[movable], -4.0, 4.0)
        gauge = float(card_bias.mean())
        card_bias -= gauge
        receiver_bias += gauge

        probabilities, expected, _ = evaluate()
        error = max(
            float(np.max(np.abs(expected.sum(axis=1) - card_target))),
            float(np.max(np.abs(expected.sum(axis=0) - receiver_target))),
        )
        if error < 1e-11:
            return expected.tolist(), probabilities
    raise BeliefProjectionError("projection did not converge")


@dataclass
class _Edge:
    to: int
    reverse: int
    capacity: int


def _add_edge(graph: list[list[_Edge]], left: int, right: int,
              capacity: int) -> _Edge:
    forward = _Edge(right, len(graph[right]), capacity)
    backward = _Edge(left, len(graph[left]), 0)
    graph[left].append(forward)
    graph[right].append(backward)
    return forward


def _round_transport(
        expected: list[list[float]], cards: tuple[CardFactV1, ...],
        model_input: HistoryOwnershipInputV1) -> list[list[int]]:
    n_cards = len(cards)
    n_receivers = len(model_input.receivers)
    scaled = [[value * PROBABILITY_SCALE for value in row]
              for row in expected]
    rounded = [[int(value) for value in row] for row in scaled]
    row_need = [card.unseen_count * PROBABILITY_SCALE - sum(row)
                for card, row in zip(cards, rounded, strict=True)]
    col_need = [
        model_input.receivers[receiver].card_count * PROBABILITY_SCALE
        - sum(rounded[card][receiver] for card in range(n_cards))
        for receiver in range(n_receivers)
    ]
    if sum(row_need) != sum(col_need) \
            or any(not 0 <= need <= n_receivers for need in row_need) \
            or any(not 0 <= need <= n_cards for need in col_need):
        raise BeliefProjectionError("fractional projection cannot be rounded")

    source = 0
    row_offset = 1
    col_offset = row_offset + n_cards
    sink = col_offset + n_receivers
    graph = [[] for _ in range(sink + 1)]
    for card, need in enumerate(row_need):
        _add_edge(graph, source, row_offset + card, need)
    cell_edges: dict[tuple[int, int], _Edge] = {}
    for card in range(n_cards):
        order = sorted(
            range(n_receivers),
            key=lambda receiver: (
                -(scaled[card][receiver] - rounded[card][receiver]),
                receiver),
        )
        for receiver in order:
            upper = cards[card].max_count_by_receiver[receiver] \
                * PROBABILITY_SCALE
            if rounded[card][receiver] < upper:
                cell_edges[(card, receiver)] = _add_edge(
                    graph, row_offset + card, col_offset + receiver, 1)
    for receiver, need in enumerate(col_need):
        _add_edge(graph, col_offset + receiver, sink, need)

    total = sum(row_need)
    flow = 0
    while flow < total:
        level = [-1] * len(graph)
        level[source] = 0
        queue = [source]
        for node in queue:
            for edge in graph[node]:
                if edge.capacity and level[edge.to] < 0:
                    level[edge.to] = level[node] + 1
                    queue.append(edge.to)
        if level[sink] < 0:
            raise BeliefProjectionError("integral projection flow is infeasible")
        cursor = [0] * len(graph)

        def send(node: int, amount: int) -> int:
            if node == sink:
                return amount
            while cursor[node] < len(graph[node]):
                edge = graph[node][cursor[node]]
                if edge.capacity and level[edge.to] == level[node] + 1:
                    sent = send(edge.to, min(amount, edge.capacity))
                    if sent:
                        edge.capacity -= sent
                        graph[edge.to][edge.reverse].capacity += sent
                        return sent
                cursor[node] += 1
            return 0

        while flow < total:
            sent = send(source, total - flow)
            if not sent:
                break
            flow += sent
    for (card, receiver), edge in cell_edges.items():
        if edge.capacity == 0:
            rounded[card][receiver] += 1
    if any(sum(row) != card.unseen_count * PROBABILITY_SCALE
           for card, row in zip(cards, rounded, strict=True)) \
            or any(sum(rounded[card][receiver] for card in range(n_cards))
                   != model_input.receivers[receiver].card_count
                   * PROBABILITY_SCALE
                   for receiver in range(n_receivers)):
        raise BeliefProjectionError("integral projection margins drift")
    return rounded


def _count_probabilities(
        expected_count_ppb: int, probabilities: tuple[float, float, float],
        lower: int, upper: int) -> tuple[int, int, int]:
    scale = PROBABILITY_SCALE
    if lower == upper:
        values = [0, 0, 0]
        values[lower] = scale
        if expected_count_ppb != lower * scale:
            raise BeliefProjectionError("forced count expectation drift")
        return tuple(values)  # type: ignore[return-value]
    if (lower, upper) == (0, 1):
        return scale - expected_count_ppb, expected_count_ppb, 0
    if (lower, upper) == (1, 2):
        count_2 = expected_count_ppb - scale
        return 0, scale - count_2, count_2
    if (lower, upper) != (0, 2):
        raise BeliefProjectionError("unsupported hard count interval")
    lower_2 = max(0, expected_count_ppb - scale)
    upper_2 = expected_count_ppb // 2
    preferred_2 = round(probabilities[2] * PROBABILITY_SCALE)
    count_2 = min(upper_2, max(lower_2, preferred_2))
    count_1 = expected_count_ppb - 2 * count_2
    count_0 = scale - count_1 - count_2
    if min(count_0, count_1, count_2) < 0:
        raise BeliefProjectionError("quantized count probability is negative")
    return count_0, count_1, count_2


def project_count_weights(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...],
        model_schema: str,
        model_sha256: str,
        raw_weights: tuple[RawCountWeightV1, ...]) -> BeliefOwnershipV1:
    """Project raw model weights into an exact ``BeliefOwnershipV1``."""
    if type(model_schema) is not str or not model_schema \
            or not _is_sha256(model_sha256):
        raise BeliefProjectionError("projected model identity is invalid")
    model_input = build_history_ownership_input(
        actor, behavior_policy_ids=behavior_policy_ids)
    cards, weight_matrix = _validate_weights(model_input, raw_weights)
    expected, probability_matrix = _fractional_expectations(
        cards, model_input, weight_matrix)
    expected_ppb = _round_transport(expected, cards, model_input)
    rows = []
    for card_index, card in enumerate(cards):
        for receiver_index, receiver in enumerate(model_input.receivers):
            lower = card.min_count_by_receiver[receiver_index]
            upper = card.max_count_by_receiver[receiver_index]
            probabilities = tuple(float(value) for value in
                                  probability_matrix[
                                      card_index, receiver_index])
            values = _count_probabilities(
                expected_ppb[card_index][receiver_index],
                probabilities, lower, upper)
            rows.append(ReceiverCountProbabilityV1(
                card=card.card,
                receiver=receiver.receiver,
                count_0_ppb=values[0], count_1_ppb=values[1],
                count_2_ppb=values[2],
            ))
    belief = BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema=model_schema,
        model_sha256=model_sha256,
        behavior_policy_ids=behavior_policy_ids,
        receiver_sizes=tuple((receiver.receiver, receiver.card_count)
                             for receiver in model_input.receivers),
        probabilities=tuple(rows),
    )
    validate_ownership(actor, belief)
    return belief
