"""Pure REF-C ownership probabilities from sampled complete worlds.

This module does not draw worlds.  It validates an already-frozen ordered set
of 256 current-sampler worlds against one ``ActorObservationV1`` and converts
their empirical receiver-count frequencies into ``BeliefOwnershipV1``.  It has
no RNG, sampler call, target access, model, file I/O, CLI, or run authority.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..engine.cards import Ordering, make_deck
from ..engine.combos import decompose
from .belief_contract import ActorObservationV1, canonical_json_bytes
from .belief_ownership import (PROBABILITY_SCALE, BeliefOwnershipV1,
                               ReceiverCountProbabilityV1, receiver_sizes,
                               validate_ownership)


WORLD_SCHEMA = "belief-v1-sampled-ownership-world-v1"
REF_C_MODEL_SCHEMA = "belief-v1-ref-c-sound-constraint-sampler-256-v2"
REF_C_WORLD_COUNT = 256
_WORLD_UNIT_PPB = PROBABILITY_SCALE // REF_C_WORLD_COUNT
_CARD_CODES = frozenset(make_deck())


class BeliefReferenceError(ValueError):
    """A REF-C complete world or empirical distribution is invalid."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class ReceiverCardsV1:
    receiver: str
    cards: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "receiver": self.receiver,
            "cards": {card: count for card, count in self.cards},
            "card_count": sum(count for _, count in self.cards),
        }


@dataclass(frozen=True)
class SampledOwnershipWorldV1:
    actor_observation_sha256: str
    receivers: tuple[ReceiverCardsV1, ...]
    schema: str = WORLD_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "actor_observation_sha256": self.actor_observation_sha256,
            "receivers": [receiver.to_dict() for receiver in self.receivers],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def validate_sampled_world(actor: ActorObservationV1,
                           world: SampledOwnershipWorldV1) -> None:
    """Validate one world through the batch validator's shared context."""
    validate_sampled_worlds(actor, (world,))


def validate_sampled_worlds(
        actor: ActorObservationV1,
        worlds: tuple[SampledOwnershipWorldV1, ...]) -> None:
    """Validate worlds while deriving actor-constant mechanics exactly once."""
    if type(actor) is not ActorObservationV1:
        raise BeliefReferenceError("REF-C requires an exact actor observation")
    if type(worlds) is not tuple or not worlds:
        raise BeliefReferenceError("REF-C world population is malformed")
    actor_sha256 = actor.sha256()
    expected_receivers = receiver_sizes(actor)
    unseen = dict(actor.deductions.unseen)
    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    receiver_names = tuple(receiver for receiver, _ in expected_receivers)
    voids_by_relative = tuple(
        frozenset(actor.deductions.voids_by_relative[relative])
        for relative in range(1, 4))
    pair_caps_by_relative = tuple(
        actor.deductions.pair_caps_by_relative[relative]
        for relative in range(1, 4))
    run_caps_by_relative = tuple(
        actor.deductions.run_caps_by_relative[relative]
        for relative in range(1, 4))

    for world in worlds:
        if type(world) is not SampledOwnershipWorldV1 \
                or world.schema != WORLD_SCHEMA \
                or world.actor_observation_sha256 != actor_sha256:
            raise BeliefReferenceError(
                "REF-C world actor/schema binding drift")
        if type(world.receivers) is not tuple \
                or tuple(row.receiver for row in world.receivers) \
                != receiver_names:
            raise BeliefReferenceError(
                "REF-C receiver population/order drift")

        totals: Counter[str] = Counter()
        by_receiver: dict[str, Counter[str]] = {}
        for relative, (row, (_, size)) in enumerate(
                zip(world.receivers, expected_receivers, strict=True), start=1):
            if type(row) is not ReceiverCardsV1 \
                    or type(row.receiver) is not str \
                    or type(row.cards) is not tuple:
                raise BeliefReferenceError("REF-C receiver row is malformed")
            counts: Counter[str] = Counter()
            for item in row.cards:
                if type(item) is not tuple or len(item) != 2:
                    raise BeliefReferenceError(
                        "REF-C receiver cards are malformed")
                card, count = item
                if type(card) is not str or card not in _CARD_CODES \
                        or card not in unseen or type(count) is not int \
                        or count not in (1, 2) or card in counts:
                    raise BeliefReferenceError(
                        "REF-C receiver cards are malformed")
                counts[card] = count
            if tuple(sorted(row.cards)) != row.cards:
                raise BeliefReferenceError("REF-C receiver cards are malformed")
            if sum(counts.values()) != size:
                raise BeliefReferenceError("REF-C receiver size drift")
            by_receiver[row.receiver] = counts
            totals.update(counts)

            if relative <= 3:
                voids = voids_by_relative[relative - 1]
                if any(ordering.eff_suit(card) in voids for card in counts):
                    raise BeliefReferenceError(
                        "REF-C world violates a proven void")
                by_suit: dict[str, list[str]] = {}
                for card in counts.elements():
                    by_suit.setdefault(
                        ordering.eff_suit(card), []).append(card)
                for suit, cap in pair_caps_by_relative[relative - 1]:
                    pair_count = sum(value // 2 for value in Counter(
                        by_suit.get(suit, ())).values())
                    if pair_count > cap:
                        raise BeliefReferenceError(
                            "REF-C world violates a proven pair cap")
                for suit, cap in run_caps_by_relative[relative - 1]:
                    cards = by_suit.get(suit, [])
                    run = 0 if not cards else decompose(
                        cards, ordering).max_pair_run()
                    if run > cap:
                        raise BeliefReferenceError(
                            "REF-C world violates a proven run cap")

        if dict(totals) != unseen:
            raise BeliefReferenceError(
                "REF-C world violates unseen conservation")
        for card, relative, copies in actor.deductions.declaration_pins:
            receiver = f"seat-relative-{relative}"
            if receiver not in by_receiver \
                    or by_receiver[receiver][card] < copies:
                raise BeliefReferenceError(
                    "REF-C world violates declaration pin")
        for constraint in actor.deductions.declaration_eligibility:
            if any(receiver not in by_receiver
                   for receiver in constraint.eligible_receivers) \
                    or sum(by_receiver[receiver][constraint.card]
                           for receiver in constraint.eligible_receivers) \
                    < constraint.minimum_copies:
                raise BeliefReferenceError(
                    "REF-C world violates declaration eligibility")


def reference_ownership(
        actor: ActorObservationV1,
        worlds: tuple[SampledOwnershipWorldV1, ...], *,
        sampler_source_sha256: str,
        behavior_policy_ids: tuple[str, ...]) -> BeliefOwnershipV1:
    """Convert exactly 256 ordered REF-C worlds into empirical marginals."""
    if type(worlds) is not tuple or len(worlds) != REF_C_WORLD_COUNT:
        raise BeliefReferenceError("REF-C requires exactly 256 worlds")
    if not _is_sha256(sampler_source_sha256):
        raise BeliefReferenceError("REF-C sampler source identity is invalid")
    validate_sampled_worlds(actor, worlds)

    rows: list[ReceiverCountProbabilityV1] = []
    for card, _ in actor.deductions.unseen:
        for receiver, _ in receiver_sizes(actor):
            histogram = Counter(
                dict(row.cards).get(card, 0)
                for world in worlds
                for row in world.receivers
                if row.receiver == receiver
            )
            if sum(histogram.values()) != REF_C_WORLD_COUNT:
                raise BeliefReferenceError("REF-C histogram population drift")
            rows.append(ReceiverCountProbabilityV1(
                card=card,
                receiver=receiver,
                count_0_ppb=histogram[0] * _WORLD_UNIT_PPB,
                count_1_ppb=histogram[1] * _WORLD_UNIT_PPB,
                count_2_ppb=histogram[2] * _WORLD_UNIT_PPB,
            ))
    belief = BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema=REF_C_MODEL_SCHEMA,
        model_sha256=sampler_source_sha256,
        behavior_policy_ids=behavior_policy_ids,
        receiver_sizes=receiver_sizes(actor),
        probabilities=tuple(rows),
    )
    validate_ownership(actor, belief)
    return belief
