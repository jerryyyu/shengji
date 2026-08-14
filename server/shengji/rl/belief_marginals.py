"""Inspectable suit, shape, and point marginals from complete belief worlds.

The first report is deliberately a REF-C report: it summarizes the current
constraint-consistent proposal without calling it uniform or posterior truth.
The same exact schema can later summarize candidate complete-world samples.
No true hidden target, action value, rollout, or policy decision is consumed.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from ..ai.point_context import BRACKETS, EFF_SUITS
from ..engine.cards import Ordering, points
from ..engine.combos import decompose
from .belief_contract import canonical_json_bytes
from .belief_input import build_history_ownership_input
from .belief_ownership import PROBABILITY_SCALE
from .belief_refc_capture import (ReferenceWorldBatchV1,
                                  validate_reference_world_batch)
from .belief_reference import REF_C_WORLD_COUNT


MARGINALS_SCHEMA = "belief-v1-sample-derived-marginals-v1"
DISTRIBUTION_SCHEMA = "belief-v1-discrete-distribution-v1"
SUIT_MARGINAL_SCHEMA = "belief-v1-receiver-suit-marginal-v1"
RECEIVER_MARGINAL_SCHEMA = "belief-v1-receiver-marginal-v1"
INFORMATION_TAG = "current_constraint_proposal_empirical"
_WORLD_UNIT_PPB = PROBABILITY_SCALE // REF_C_WORLD_COUNT
_POINT_SUPPORT = tuple(range(0, 201, 5))


class BeliefMarginalsError(ValueError):
    """Complete-world marginals violated their exact report contract."""


@dataclass(frozen=True)
class DiscreteDistributionV1:
    name: str
    probabilities_ppb: tuple[tuple[int, int], ...]
    expected_value_ppb: int
    schema: str = DISTRIBUTION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "probabilities_ppb": [
                {"value": value, "probability_ppb": probability}
                for value, probability in self.probabilities_ppb
            ],
            "expected_value_ppb": self.expected_value_ppb,
        }


@dataclass(frozen=True)
class ReceiverSuitMarginalV1:
    receiver: str
    effective_suit: str
    length: DiscreteDistributionV1
    pair_count: DiscreteDistributionV1
    max_pair_run: DiscreteDistributionV1
    top_level: DiscreteDistributionV1
    point_count: DiscreteDistributionV1
    schema: str = SUIT_MARGINAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "receiver": self.receiver,
            "effective_suit": self.effective_suit,
            "length": self.length.to_dict(),
            "pair_count": self.pair_count.to_dict(),
            "max_pair_run": self.max_pair_run.to_dict(),
            "top_level": self.top_level.to_dict(),
            "point_count": self.point_count.to_dict(),
        }


@dataclass(frozen=True)
class ReceiverMarginalV1:
    receiver: str
    card_count: int
    total_point_count: DiscreteDistributionV1
    effective_suits: tuple[ReceiverSuitMarginalV1, ...]
    schema: str = RECEIVER_MARGINAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "receiver": self.receiver,
            "card_count": self.card_count,
            "total_point_count": self.total_point_count.to_dict(),
            "effective_suits": [row.to_dict() for row in self.effective_suits],
        }


@dataclass(frozen=True)
class BeliefMarginalsV1:
    actor_observation_sha256: str
    ownership_sha256: str
    world_batch_manifest_sha256: str
    sampler_source_sha256: str
    sample_count: int
    trick_points: int
    points_left_total: int
    points_left_by_suit: tuple[tuple[str, int], ...]
    bracket_distance: tuple[int, int, int]
    receivers: tuple[ReceiverMarginalV1, ...]
    information_tag: str = INFORMATION_TAG
    sampled_hidden_worlds_consumed: bool = True
    privileged_targets_consumed: bool = False
    schema: str = MARGINALS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "information_tag": self.information_tag,
            "actor_observation_sha256": self.actor_observation_sha256,
            "ownership_sha256": self.ownership_sha256,
            "world_batch_manifest_sha256": self.world_batch_manifest_sha256,
            "sampler_source_sha256": self.sampler_source_sha256,
            "sample_count": self.sample_count,
            "point_context": {
                "trick_points": self.trick_points,
                "points_left_total": self.points_left_total,
                "points_left_by_suit": dict(self.points_left_by_suit),
                "bracket_distance": {
                    str(bracket): distance for bracket, distance in zip(
                        BRACKETS, self.bracket_distance, strict=True)
                },
            },
            "receivers": [receiver.to_dict()
                          for receiver in self.receivers],
            "sampled_hidden_worlds_consumed": (
                self.sampled_hidden_worlds_consumed),
            "privileged_targets_consumed": self.privileged_targets_consumed,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _distribution(name: str, samples: Iterable[int],
                  support: tuple[int, ...]) -> DiscreteDistributionV1:
    values = tuple(samples)
    if type(name) is not str or not name or not values \
            or type(support) is not tuple \
            or tuple(sorted(set(support))) != support \
            or any(type(value) is not int or value not in support
                   for value in values):
        raise BeliefMarginalsError(f"{name} distribution input drift")
    histogram = Counter(values)
    rows = tuple((value, histogram[value] * _WORLD_UNIT_PPB)
                 for value in support)
    if sum(probability for _, probability in rows) != PROBABILITY_SCALE:
        raise BeliefMarginalsError(f"{name} distribution mass drift")
    return DiscreteDistributionV1(
        name=name,
        probabilities_ppb=rows,
        expected_value_ppb=sum(value * probability
                               for value, probability in rows),
    )


def _build_marginals(batch: ReferenceWorldBatchV1) -> BeliefMarginalsV1:
    validate_reference_world_batch(batch)
    actor = batch.actor
    ownership = batch.ownership()
    model_input = build_history_ownership_input(
        actor, behavior_policy_ids=batch.behavior_policy_ids)
    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    receiver_sizes = dict(ownership.receiver_sizes)
    receiver_rows = []
    for receiver, size in ownership.receiver_sizes:
        world_cards = []
        for world in batch.worlds:
            row = next(row for row in world.receivers
                       if row.receiver == receiver)
            world_cards.append(Counter(dict(row.cards)))
        suit_rows = []
        for suit in EFF_SUITS:
            suited = [
                [card for card in counts.elements()
                 if ordering.eff_suit(card) == suit]
                for counts in world_cards
            ]
            level_support = (-1, *sorted({
                ordering.level(card)
                for card, _ in actor.deductions.unseen
                if ordering.eff_suit(card) == suit
            }))
            suit_rows.append(ReceiverSuitMarginalV1(
                receiver=receiver,
                effective_suit=suit,
                length=_distribution(
                    "length", (len(cards) for cards in suited),
                    tuple(range(size + 1))),
                pair_count=_distribution(
                    "pair_count",
                    (sum(count // 2
                         for count in Counter(cards).values())
                     for cards in suited),
                    tuple(range(size // 2 + 1))),
                max_pair_run=_distribution(
                    "max_pair_run",
                    (0 if not cards else decompose(
                        cards, ordering).max_pair_run()
                     for cards in suited),
                    tuple(range(size // 2 + 1))),
                top_level=_distribution(
                    "top_level",
                    (-1 if not cards else max(ordering.level(card)
                                              for card in cards)
                     for cards in suited),
                    level_support),
                point_count=_distribution(
                    "point_count",
                    (sum(points(card) for card in cards)
                     for cards in suited),
                    _POINT_SUPPORT),
            ))
        receiver_rows.append(ReceiverMarginalV1(
            receiver=receiver,
            card_count=receiver_sizes[receiver],
            total_point_count=_distribution(
                "total_point_count",
                (sum(points(card) * count
                     for card, count in counts.items())
                 for counts in world_cards),
                _POINT_SUPPORT),
            effective_suits=tuple(suit_rows),
        ))
    return BeliefMarginalsV1(
        actor_observation_sha256=actor.sha256(),
        ownership_sha256=ownership.sha256(),
        world_batch_manifest_sha256=batch.manifest_sha256(),
        sampler_source_sha256=batch.sampler_source_sha256,
        sample_count=len(batch.worlds),
        trick_points=model_input.trick_points,
        points_left_total=model_input.points_left_total,
        points_left_by_suit=model_input.points_left_by_suit,
        bracket_distance=model_input.bracket_distance,
        receivers=tuple(receiver_rows),
    )


def build_belief_marginals(
        batch: ReferenceWorldBatchV1) -> BeliefMarginalsV1:
    """Build and independently rederive one exact inspectable REF-C report."""
    report = _build_marginals(batch)
    validate_belief_marginals(batch, report)
    return report


def validate_belief_marginals(
        batch: ReferenceWorldBatchV1,
        report: BeliefMarginalsV1) -> None:
    if type(report) is not BeliefMarginalsV1 \
            or report.schema != MARGINALS_SCHEMA \
            or report.information_tag != INFORMATION_TAG \
            or report.sampled_hidden_worlds_consumed is not True \
            or report.privileged_targets_consumed is not False:
        raise BeliefMarginalsError("belief marginal schema/authority drift")
    if report != _build_marginals(batch):
        raise BeliefMarginalsError("belief marginal derivation drift")
