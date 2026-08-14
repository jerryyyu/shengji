"""Target-blind deterministic inputs for ``HistoryOwnershipV1``.

The builder consumes only one exact ``ActorObservationV1`` and named behavior
policy identities.  It expands the actor contract into an ordered public-event
sequence, fixed card facts, exact hidden-receiver constraints, and the public
point facts already represented by ``PointContext``.  No Round, target,
sampler, model, file, RNG, or action-selection object is accepted.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..ai.point_context import BRACKETS, EFF_SUITS
from ..engine.cards import RANKS, SUITS, Ordering, make_deck, points
from .belief_contract import (ACTOR_OBSERVATION_SCHEMA, ActorObservationV1,
                              DeclarationView, DeductionView, PlayView,
                              TrickView, canonical_json_bytes)
from .belief_ownership import receiver_sizes


INPUT_SCHEMA = "belief-v1-history-ownership-input-v2"
EVENT_SCHEMA = "belief-v1-history-event-v2"
RECEIVER_FACT_SCHEMA = "belief-v1-hidden-receiver-fact-v1"
CARD_FACT_SCHEMA = "belief-v1-card-fact-v1"
INFORMATION_TAG = "public_actor_private_and_logically_deduced_only"
CARD_CODES = tuple(sorted(set(make_deck())))


class BeliefInputError(ValueError):
    """An ownership-model input violated the target-blind feature contract."""


def _counts(items: tuple[tuple[str, int], ...], *, label: str) \
        -> dict[str, int]:
    if type(items) is not tuple:
        raise BeliefInputError(f"{label} card counts are not canonical")
    result: dict[str, int] = {}
    for item in items:
        if type(item) is not tuple or len(item) != 2:
            raise BeliefInputError(f"{label} card count row is malformed")
        card, count = item
        if type(card) is not str or card not in CARD_CODES \
                or type(count) is not int or count not in (1, 2) \
                or card in result:
            raise BeliefInputError(f"{label} card count row is malformed")
        result[card] = count
    if tuple(sorted(items)) != items:
        raise BeliefInputError(f"{label} card counts are not canonical")
    return result


def _card_tuple(cards: tuple[str, ...], *, label: str) \
        -> tuple[tuple[str, int], ...]:
    if type(cards) is not tuple or any(
            type(card) is not str or card not in CARD_CODES for card in cards):
        raise BeliefInputError(f"{label} cards are malformed")
    counts = Counter(cards)
    if any(count not in (1, 2) for count in counts.values()):
        raise BeliefInputError(f"{label} cards exceed physical multiplicity")
    return tuple(sorted(counts.items()))


def _caps(items: tuple[tuple[str, int], ...], *, label: str) \
        -> tuple[tuple[str, int], ...]:
    if type(items) is not tuple:
        raise BeliefInputError(f"{label} cap population is malformed")
    result: dict[str, int] = {}
    for item in items:
        if type(item) is not tuple or len(item) != 2:
            raise BeliefInputError(f"{label} cap row is malformed")
        suit, cap = item
        if type(suit) is not str or suit not in EFF_SUITS \
                or type(cap) is not int or cap < 0 or suit in result:
            raise BeliefInputError(f"{label} cap row is malformed")
        result[suit] = cap
    if tuple(sorted(items)) != items:
        raise BeliefInputError(f"{label} cap population is not canonical")
    return items


@dataclass(frozen=True)
class HistoryEventV1:
    event_kind: str
    seat_relative: int
    trick_index: int
    trick_position: int
    trick_leader_relative: int
    trick_winner_relative: int
    trick_points: int
    declaration_strength: int
    failed_throw: bool
    shown_cards: tuple[tuple[str, int], ...]
    attempted_cards: tuple[tuple[str, int], ...]
    actual_cards: tuple[tuple[str, int], ...]
    schema: str = EVENT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "event_kind": self.event_kind,
            "seat_relative": self.seat_relative,
            "trick_index": self.trick_index,
            "trick_position": self.trick_position,
            "trick_leader_relative": self.trick_leader_relative,
            "trick_winner_relative": self.trick_winner_relative,
            "trick_points": self.trick_points,
            "declaration_strength": self.declaration_strength,
            "failed_throw": self.failed_throw,
            "shown_cards": dict(self.shown_cards),
            "attempted_cards": dict(self.attempted_cards),
            "actual_cards": dict(self.actual_cards),
        }


@dataclass(frozen=True)
class ReceiverFactV1:
    receiver: str
    card_count: int
    proven_void_suits: tuple[str, ...]
    pair_caps: tuple[tuple[str, int], ...]
    run_caps: tuple[tuple[str, int], ...]
    schema: str = RECEIVER_FACT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "receiver": self.receiver,
            "card_count": self.card_count,
            "proven_void_suits": list(self.proven_void_suits),
            "pair_caps": dict(self.pair_caps),
            "run_caps": dict(self.run_caps),
        }


@dataclass(frozen=True)
class CardFactV1:
    card: str
    card_index: int
    effective_suit: str
    level: int
    point_value: int
    actor_hand_count: int
    actor_known_burial_count: int
    played_count: int
    played_by_relative: tuple[int, int, int, int]
    unseen_count: int
    min_count_by_receiver: tuple[int, ...]
    max_count_by_receiver: tuple[int, ...]
    schema: str = CARD_FACT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "card": self.card,
            "card_index": self.card_index,
            "effective_suit": self.effective_suit,
            "level": self.level,
            "point_value": self.point_value,
            "actor_hand_count": self.actor_hand_count,
            "actor_known_burial_count": self.actor_known_burial_count,
            "played_count": self.played_count,
            "played_by_relative": list(self.played_by_relative),
            "unseen_count": self.unseen_count,
            "min_count_by_receiver": list(self.min_count_by_receiver),
            "max_count_by_receiver": list(self.max_count_by_receiver),
        }


@dataclass(frozen=True)
class HistoryOwnershipInputV1:
    actor_observation_sha256: str
    behavior_policy_ids: tuple[str, ...]
    banker_relative: int
    actor_is_attacker: bool
    attacker_points: int
    trump_rank: str
    trump_suit: str | None
    hand_sizes_relative: tuple[int, int, int, int]
    trick_points: int
    points_left_total: int
    points_left_by_suit: tuple[tuple[str, int], ...]
    bracket_distance: tuple[int, int, int]
    receivers: tuple[ReceiverFactV1, ...]
    events: tuple[HistoryEventV1, ...]
    card_facts: tuple[CardFactV1, ...]
    information_tag: str = INFORMATION_TAG
    privileged_targets_consumed: bool = False
    schema: str = INPUT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "information_tag": self.information_tag,
            "actor_observation_sha256": self.actor_observation_sha256,
            "behavior_policy_ids": list(self.behavior_policy_ids),
            "banker_relative": self.banker_relative,
            "actor_is_attacker": self.actor_is_attacker,
            "attacker_points": self.attacker_points,
            "trump_rank": self.trump_rank,
            "trump_suit": self.trump_suit,
            "hand_sizes_relative": list(self.hand_sizes_relative),
            "point_context": {
                "trick_points": self.trick_points,
                "points_left_total": self.points_left_total,
                "points_left_by_suit": dict(self.points_left_by_suit),
                "bracket_distance": {
                    str(bracket): distance for bracket, distance in zip(
                        BRACKETS, self.bracket_distance, strict=True)
                },
            },
            "receivers": [receiver.to_dict() for receiver in self.receivers],
            "events": [event.to_dict() for event in self.events],
            "card_facts": [row.to_dict() for row in self.card_facts],
            "privileged_targets_consumed": self.privileged_targets_consumed,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _validate_actor(actor: ActorObservationV1) -> tuple[
        dict[str, int], dict[str, int], dict[str, int],
        tuple[dict[str, int], ...]]:
    if type(actor) is not ActorObservationV1 \
            or actor.schema != ACTOR_OBSERVATION_SCHEMA \
            or actor.declaration_history_complete is not True \
            or actor.attempted_play_history_complete is not True:
        raise BeliefInputError(
            "history input requires an exact complete actor observation")
    if type(actor.deductions) is not DeductionView \
            or type(actor.hand_sizes_relative) is not tuple \
            or len(actor.hand_sizes_relative) != 4 \
            or any(type(size) is not int or not 0 <= size <= 33
                   for size in actor.hand_sizes_relative) \
            or type(actor.banker_relative) is not int \
            or actor.banker_relative not in range(4) \
            or type(actor.actor_is_attacker) is not bool \
            or type(actor.attacker_points) is not int \
            or actor.attacker_points < 0 \
            or type(actor.trump_rank) is not str \
            or actor.trump_rank not in RANKS \
            or type(actor.trump_is_nt) is not bool \
            or (actor.trump_is_nt and actor.trump_suit is not None) \
            or (not actor.trump_is_nt and actor.trump_suit not in SUITS) \
            or type(actor.hidden_burial_size) is not int \
            or actor.hidden_burial_size not in (0, 8):
        raise BeliefInputError("actor scalar or receiver population drift")
    actor_hand = _counts(actor.actor_hand, label="actor hand")
    burial = _counts(actor.actor_known_burial, label="actor burial")
    played = _counts(actor.deductions.played, label="played")
    unseen = _counts(actor.deductions.unseen, label="unseen")
    if sum(actor_hand.values()) != actor.hand_sizes_relative[0] \
            or (actor.banker_relative == 0 and (
                sum(burial.values()) != 8 or actor.hidden_burial_size != 0)) \
            or (actor.banker_relative != 0 and (
                burial or actor.hidden_burial_size != 8)):
        raise BeliefInputError("actor private cards and role disagree")
    if type(actor.deductions.played_by_relative) is not tuple \
            or len(actor.deductions.played_by_relative) != 4:
        raise BeliefInputError("played-by population drift")
    played_by = tuple(_counts(row, label="played-by")
                      for row in actor.deductions.played_by_relative)
    for card in CARD_CODES:
        if sum(row.get(card, 0) for row in played_by) != played.get(card, 0):
            raise BeliefInputError("played-by counts do not reconcile")
        if actor_hand.get(card, 0) + burial.get(card, 0) \
                + played.get(card, 0) + unseen.get(card, 0) != 2:
            raise BeliefInputError("actor card population does not reconcile")
    if sum(unseen.values()) != sum(size for _, size in receiver_sizes(actor)):
        raise BeliefInputError("unseen cards and receiver sizes disagree")
    if type(actor.deductions.voids_by_relative) is not tuple \
            or len(actor.deductions.voids_by_relative) != 4 \
            or type(actor.deductions.pair_caps_by_relative) is not tuple \
            or len(actor.deductions.pair_caps_by_relative) != 4 \
            or type(actor.deductions.run_caps_by_relative) is not tuple \
            or len(actor.deductions.run_caps_by_relative) != 4:
        raise BeliefInputError("deduction receiver population drift")
    return actor_hand, burial, played, played_by


def _events(actor: ActorObservationV1) -> tuple[HistoryEventV1, ...]:
    events: list[HistoryEventV1] = []
    if type(actor.declaration_history) is not tuple \
            or any(type(event) is not DeclarationView
                   for event in actor.declaration_history) \
            or type(actor.completed_tricks) is not tuple \
            or any(type(trick) is not TrickView
                   for trick in actor.completed_tricks) \
            or type(actor.current_trick) is not TrickView:
        raise BeliefInputError("actor event population drift")
    for declaration in actor.declaration_history:
        if type(declaration.seat_relative) is not int \
                or declaration.seat_relative not in range(4) \
                or type(declaration.strength) is not int \
                or declaration.strength not in range(1, 5):
            raise BeliefInputError("actor declaration event is malformed")
        events.append(HistoryEventV1(
            event_kind="declaration",
            seat_relative=declaration.seat_relative,
            trick_index=-1,
            trick_position=-1,
            trick_leader_relative=-1,
            trick_winner_relative=-1,
            trick_points=0,
            declaration_strength=declaration.strength,
            failed_throw=False,
            shown_cards=_card_tuple(
                declaration.cards, label="declaration event"),
            attempted_cards=(),
            actual_cards=(),
        ))
    tricks = (*actor.completed_tricks, actor.current_trick)
    for trick_index, trick in enumerate(tricks):
        if type(trick.plays) is not tuple \
                or any(type(play) is not PlayView for play in trick.plays) \
                or type(trick.leader_relative) is not int \
                or trick.leader_relative not in range(4) \
                or (trick.winner_relative is not None and (
                    type(trick.winner_relative) is not int
                    or trick.winner_relative not in range(4))) \
                or type(trick.points) is not int or trick.points < 0:
            raise BeliefInputError("actor play event population drift")
        winner = -1 if trick.winner_relative is None else trick.winner_relative
        for position, play in enumerate(trick.plays):
            if type(play.seat_relative) is not int \
                    or play.seat_relative not in range(4) \
                    or type(play.failed_throw) is not bool:
                raise BeliefInputError("actor play event is malformed")
            events.append(HistoryEventV1(
                event_kind="play",
                seat_relative=play.seat_relative,
                trick_index=trick_index,
                trick_position=position,
                trick_leader_relative=trick.leader_relative,
                trick_winner_relative=winner,
                trick_points=trick.points,
                declaration_strength=0,
                failed_throw=play.failed_throw,
                shown_cards=(),
                attempted_cards=_card_tuple(
                    play.attempted_cards, label="attempted play event"),
                actual_cards=_card_tuple(
                    play.cards, label="actual play event"),
            ))
    return tuple(events)


def _build_history_ownership_input(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...]) -> HistoryOwnershipInputV1:
    """Build the exact target-blind ownership-model input."""
    actor_hand, burial, played, played_by = _validate_actor(actor)
    if type(behavior_policy_ids) is not tuple \
            or not behavior_policy_ids \
            or any(type(policy) is not str or not policy
                   for policy in behavior_policy_ids) \
            or tuple(sorted(set(behavior_policy_ids))) != behavior_policy_ids:
        raise BeliefInputError("behavior policy identity is invalid")

    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    sizes = receiver_sizes(actor)
    receiver_rows: list[ReceiverFactV1] = []
    for index, (receiver, size) in enumerate(sizes, start=1):
        if receiver == "hidden-kitty":
            receiver_rows.append(ReceiverFactV1(
                receiver=receiver, card_count=size, proven_void_suits=(),
                pair_caps=(), run_caps=()))
            continue
        voids = actor.deductions.voids_by_relative[index]
        pair_caps = actor.deductions.pair_caps_by_relative[index]
        run_caps = actor.deductions.run_caps_by_relative[index]
        if type(voids) is not tuple \
                or any(type(suit) is not str or suit not in EFF_SUITS
                       for suit in voids) \
                or tuple(sorted(set(voids))) != voids:
            raise BeliefInputError("receiver deductions are malformed")
        pair_caps = _caps(pair_caps, label="pair")
        run_caps = _caps(run_caps, label="run")
        receiver_rows.append(ReceiverFactV1(
            receiver=receiver, card_count=size,
            proven_void_suits=voids, pair_caps=pair_caps,
            run_caps=run_caps))

    unseen = dict(actor.deductions.unseen)
    raw_pins = actor.deductions.declaration_pins
    if type(raw_pins) is not tuple or any(
            type(pin) is not tuple or len(pin) != 3 for pin in raw_pins):
        raise BeliefInputError("declaration pin is malformed")
    if any(type(card) is not str or card not in CARD_CODES
           or type(relative) is not int or relative not in range(1, 4)
           or type(copies) is not int or copies not in (1, 2)
           for card, relative, copies in raw_pins):
        raise BeliefInputError("declaration pin is malformed")
    pins = {card: (relative, copies) for card, relative, copies in raw_pins}
    if len(pins) != len(raw_pins):
        raise BeliefInputError("declaration pin is malformed")
    card_rows: list[CardFactV1] = []
    for card_index, card in enumerate(CARD_CODES):
        multiplicity = unseen.get(card, 0)
        minimums = [0] * len(sizes)
        maximums = [min(multiplicity, size) for _, size in sizes]
        for receiver_index, ((receiver, _), receiver_fact) in enumerate(
                zip(sizes, receiver_rows, strict=True)):
            if receiver != "hidden-kitty":
                if ordering.eff_suit(card) in receiver_fact.proven_void_suits:
                    maximums[receiver_index] = 0
                if dict(receiver_fact.pair_caps).get(
                        ordering.eff_suit(card)) == 0:
                    maximums[receiver_index] = min(
                        maximums[receiver_index], 1)
        pin = pins.get(card)
        if pin is not None:
            relative, copies = pin
            if type(relative) is not int or relative not in range(1, 4) \
                    or type(copies) is not int or copies not in (1, 2) \
                    or copies > multiplicity:
                raise BeliefInputError("declaration pin is malformed")
            owner = relative - 1
            minimums[owner] = copies
            if copies == multiplicity:
                maximums = [0] * len(sizes)
                maximums[owner] = copies
            else:
                # A public one-copy declaration proves the declarer owns at
                # least one copy and, just as importantly, no other receiver
                # can own both copies of that card.
                maximums = [min(maximum, 1) if index != owner else maximum
                            for index, maximum in enumerate(maximums)]
        if sum(minimums) > multiplicity or sum(maximums) < multiplicity \
                or any(minimum > maximum
                       for minimum, maximum in zip(
                           minimums, maximums, strict=True)):
            raise BeliefInputError("card receiver bounds are infeasible")
        card_rows.append(CardFactV1(
            card=card,
            card_index=card_index,
            effective_suit=ordering.eff_suit(card),
            level=ordering.level(card),
            point_value=points(card),
            actor_hand_count=actor_hand.get(card, 0),
            actor_known_burial_count=burial.get(card, 0),
            played_count=played.get(card, 0),
            played_by_relative=tuple(
                row.get(card, 0) for row in played_by),
            unseen_count=multiplicity,
            min_count_by_receiver=tuple(minimums),
            max_count_by_receiver=tuple(maximums),
        ))

    for receiver_index, (_, size) in enumerate(sizes):
        if sum(row.min_count_by_receiver[receiver_index]
               for row in card_rows) > size \
                or sum(row.max_count_by_receiver[receiver_index]
                       for row in card_rows) < size:
            raise BeliefInputError("receiver bounds are infeasible")

    points_by_suit = tuple(
        (suit, sum(points(card) * count for card, count in unseen.items()
                   if ordering.eff_suit(card) == suit))
        for suit in EFF_SUITS
    )
    trick_points = actor.current_trick.points
    result = HistoryOwnershipInputV1(
        actor_observation_sha256=actor.sha256(),
        behavior_policy_ids=behavior_policy_ids,
        banker_relative=actor.banker_relative,
        actor_is_attacker=actor.actor_is_attacker,
        attacker_points=actor.attacker_points,
        trump_rank=actor.trump_rank,
        trump_suit=actor.trump_suit,
        hand_sizes_relative=actor.hand_sizes_relative,
        trick_points=trick_points,
        points_left_total=sum(value for _, value in points_by_suit),
        points_left_by_suit=points_by_suit,
        bracket_distance=tuple(
            max(0, bracket - actor.attacker_points) for bracket in BRACKETS),
        receivers=tuple(receiver_rows),
        events=_events(actor),
        card_facts=tuple(card_rows),
    )
    return result


def build_history_ownership_input(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...]) -> HistoryOwnershipInputV1:
    """Build and independently rederive the exact target-blind model input."""
    result = _build_history_ownership_input(
        actor, behavior_policy_ids=behavior_policy_ids)
    validate_history_ownership_input(actor, result)
    return result


def validate_history_ownership_input(
        actor: ActorObservationV1,
        candidate: HistoryOwnershipInputV1) -> None:
    if type(candidate) is not HistoryOwnershipInputV1 \
            or candidate.schema != INPUT_SCHEMA \
            or candidate.information_tag != INFORMATION_TAG \
            or candidate.privileged_targets_consumed is not False:
        raise BeliefInputError("history input schema or authority drift")
    # Rebuilding is deliberately the validator: every derived field remains a
    # pure function of the exact actor bytes and named behavior policy cohort.
    expected = _build_history_ownership_input(
        actor, behavior_policy_ids=candidate.behavior_policy_ids)
    if candidate != expected:
        raise BeliefInputError("history input derivation drift")
