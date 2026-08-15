"""Typed reconstruction of persisted BELIEF-V1 actor and target payloads.

Corpus JSON is not training input merely because its outer hashes reconcile.
This module rebuilds the exact B0 dataclasses, closes every nested schema, and
rechecks the public mechanics and hidden ownership conservation.  It has no
filesystem, model, sampler, RNG, policy, or execution surface.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..engine.cards import RANKS, SUITS, Ordering, make_deck, total_points
from .belief_contract import (
    ACTOR_OBSERVATION_SCHEMA,
    BELIEF_CONTRACT_SOURCE_SHA256S,
    BELIEF_TARGETS_SCHEMA,
    DECLARATION_SCHEMA,
    ActorObservationV1,
    BeliefTargetsV1,
    DeclarationEligibilityV1,
    DeclarationView,
    DeductionView,
    HIDDEN_KITTY_RECEIVER,
    HiddenReceiverView,
    PlayView,
    TrickView,
)


_CARD_CODES = frozenset(make_deck())
_EFF_SUITS = frozenset(("C", "D", "H", "S", "T"))


class BeliefReopenError(ValueError):
    """Persisted actor/target payload bytes fail typed reconstruction."""


def _exact_keys(value: Any, keys: set[str], *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise BeliefReopenError(f"{label} field population drift")
    return value


def _integer(value: Any, *, label: str, low: int = 0,
             high: int | None = None) -> int:
    if type(value) is not int or value < low \
            or (high is not None and value > high):
        raise BeliefReopenError(f"{label} is invalid")
    return value


def _cards(value: Any, *, label: str, allow_empty: bool = False) \
        -> tuple[str, ...]:
    if type(value) is not list or (not allow_empty and not value) \
            or any(type(card) is not str or card not in _CARD_CODES
                   for card in value):
        raise BeliefReopenError(f"{label} cards are malformed")
    counts = Counter(value)
    if any(count > 2 for count in counts.values()):
        raise BeliefReopenError(f"{label} exceeds physical copies")
    return tuple(value)


def _counts(value: Any, *, label: str) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict:
        raise BeliefReopenError(f"{label} counts are not an object")
    rows = []
    for card, count in value.items():
        if type(card) is not str or card not in _CARD_CODES \
                or type(count) is not int or count not in (1, 2):
            raise BeliefReopenError(f"{label} count is malformed")
        rows.append((card, count))
    return tuple(sorted(rows))


def _caps(value: Any, *, label: str) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict:
        raise BeliefReopenError(f"{label} caps are not an object")
    rows = []
    for suit, cap in value.items():
        if type(suit) is not str or suit not in _EFF_SUITS \
                or type(cap) is not int or cap < 0:
            raise BeliefReopenError(f"{label} cap is malformed")
        rows.append((suit, cap))
    return tuple(sorted(rows))


def _declaration(value: Any, *, ordering: Ordering,
                 label: str) -> DeclarationView:
    row = _exact_keys(value, {"schema", "seat_relative", "cards",
                              "strength"}, label=label)
    cards = _cards(row["cards"], label=label)
    if row["schema"] != DECLARATION_SCHEMA \
            or _integer(row["seat_relative"], label=f"{label} seat",
                        high=3) != row["seat_relative"] \
            or _integer(row["strength"], label=f"{label} strength",
                        low=1, high=4) != row["strength"] \
            or tuple(sorted(cards, key=ordering.sort_key)) != cards:
        raise BeliefReopenError(f"{label} is malformed")
    return DeclarationView(
        schema=row["schema"], seat_relative=row["seat_relative"],
        cards=cards, strength=row["strength"])


def _play(value: Any, *, ordering: Ordering, label: str) -> PlayView:
    row = _exact_keys(value, {"seat_relative", "failed_throw",
                              "attempted_cards", "cards"},
                      label=label)
    attempted = _cards(row["attempted_cards"], label=f"{label} attempted")
    actual = _cards(row["cards"], label=f"{label} actual")
    if _integer(row["seat_relative"], label=f"{label} seat", high=3) \
            != row["seat_relative"] \
            or tuple(sorted(attempted, key=ordering.sort_key)) != attempted \
            or type(row["failed_throw"]) is not bool \
            or tuple(sorted(actual, key=ordering.sort_key)) != actual \
            or Counter(actual) - Counter(attempted):
        raise BeliefReopenError(f"{label} is malformed")
    return PlayView(
        seat_relative=row["seat_relative"],
        failed_throw=row["failed_throw"], attempted_cards=attempted,
        cards=actual)


def _trick(value: Any, *, ordering: Ordering, complete: bool,
           label: str) -> TrickView:
    row = _exact_keys(value, {"leader_relative", "plays", "winner_relative",
                              "points"}, label=label)
    leader = _integer(row["leader_relative"], label=f"{label} leader", high=3)
    if type(row["plays"]) is not list:
        raise BeliefReopenError(f"{label} plays are malformed")
    plays = tuple(_play(play, ordering=ordering,
                        label=f"{label} play {index}")
                  for index, play in enumerate(row["plays"]))
    if (complete and len(plays) != 4) \
            or (not complete and not 0 <= len(plays) <= 3) \
            or tuple(play.seat_relative for play in plays) != tuple(
                (leader + index) % 4 for index in range(len(plays))):
        raise BeliefReopenError(f"{label} play population/order drift")
    for position, play in enumerate(plays):
        if position and play.failed_throw:
            raise BeliefReopenError(
                f"{label} nonlead attempted/actual cards drift")
        if play.seat_relative != 0 \
                and Counter(play.attempted_cards) != Counter(play.cards):
            raise BeliefReopenError(
                f"{label} exposes another seat's private attempted cards")
        if not play.failed_throw \
                and Counter(play.attempted_cards) != Counter(play.cards):
            raise BeliefReopenError(
                f"{label} successful play attempted/actual cards drift")
    points = _integer(row["points"], label=f"{label} points")
    actual_points = total_points(
        card for play in plays for card in play.cards)
    if points != actual_points:
        raise BeliefReopenError(f"{label} point total drift")
    winner = row["winner_relative"]
    if complete:
        winner = _integer(winner, label=f"{label} winner", high=3)
    elif winner is not None:
        raise BeliefReopenError(f"{label} open trick has a winner")
    return TrickView(
        leader_relative=leader, plays=plays,
        winner_relative=winner, points=points)


def _deductions(value: Any) -> DeductionView:
    row = _exact_keys(value, {
        "played", "played_by_relative", "unseen", "voids_by_relative",
        "pair_caps_by_relative", "run_caps_by_relative", "declaration_pins",
        "declaration_eligibility",
    }, label="actor deductions")
    if any(type(row[field]) is not list or len(row[field]) != 4
           for field in ("played_by_relative", "voids_by_relative",
                         "pair_caps_by_relative", "run_caps_by_relative")):
        raise BeliefReopenError("actor deduction receiver population drift")
    voids = []
    for entry in row["voids_by_relative"]:
        if type(entry) is not list \
                or any(type(suit) is not str or suit not in _EFF_SUITS
                       for suit in entry) \
                or tuple(sorted(set(entry))) != tuple(entry):
            raise BeliefReopenError("actor proven voids are malformed")
        voids.append(tuple(entry))
    pins = []
    if type(row["declaration_pins"]) is not list:
        raise BeliefReopenError("actor declaration pins are malformed")
    for entry in row["declaration_pins"]:
        pin = _exact_keys(entry, {"card", "seat_relative", "copies"},
                          label="actor declaration pin")
        if type(pin["card"]) is not str or pin["card"] not in _CARD_CODES:
            raise BeliefReopenError("actor declaration pin card is invalid")
        pins.append((
            pin["card"],
            _integer(pin["seat_relative"], label="pin seat", low=1, high=3),
            _integer(pin["copies"], label="pin copies", low=1, high=2),
        ))
    if tuple(sorted(set(pins))) != tuple(pins):
        raise BeliefReopenError("actor declaration pins are not canonical")
    eligibility = []
    if type(row["declaration_eligibility"]) is not list:
        raise BeliefReopenError("actor declaration eligibility is malformed")
    for entry in row["declaration_eligibility"]:
        constraint = _exact_keys(
            entry, {"card", "eligible_receivers", "minimum_copies"},
            label="actor declaration eligibility")
        receivers = constraint["eligible_receivers"]
        if type(constraint["card"]) is not str \
                or constraint["card"] not in _CARD_CODES \
                or type(receivers) is not list \
                or len(receivers) != 2 \
                or type(receivers[0]) is not str \
                or receivers[0] not in {
                    "seat-relative-1", "seat-relative-2", "seat-relative-3"} \
                or receivers[1] != HIDDEN_KITTY_RECEIVER:
            raise BeliefReopenError(
                "actor declaration eligibility is malformed")
        eligibility.append(DeclarationEligibilityV1(
            card=constraint["card"],
            eligible_receivers=tuple(receivers),
            minimum_copies=_integer(
                constraint["minimum_copies"], label="eligibility copies",
                low=1, high=2),
        ))
    if tuple(sorted(eligibility, key=lambda value: value.card)) \
            != tuple(eligibility) \
            or len({value.card for value in eligibility}) != len(eligibility):
        raise BeliefReopenError(
            "actor declaration eligibility is not canonical")
    return DeductionView(
        played=_counts(row["played"], label="played"),
        played_by_relative=tuple(
            _counts(value, label="played-by")
            for value in row["played_by_relative"]),
        unseen=_counts(row["unseen"], label="unseen"),
        voids_by_relative=tuple(voids),
        pair_caps_by_relative=tuple(
            _caps(value, label="pair")
            for value in row["pair_caps_by_relative"]),
        run_caps_by_relative=tuple(
            _caps(value, label="run")
            for value in row["run_caps_by_relative"]),
        declaration_pins=tuple(pins),
        declaration_eligibility=tuple(eligibility),
    )


def actor_observation_from_dict(payload: dict[str, Any]) -> ActorObservationV1:
    """Rebuild and mechanically validate one exact actor payload object."""
    keys = {
        "schema", "perspective", "phase", "trump_rank", "trump_suit",
        "trump_is_nt", "banker_relative", "actor_is_attacker",
        "attacker_points", "hand_sizes_relative", "actor_hand",
        "actor_known_burial", "hidden_burial_size", "declaration",
        "declaration_history", "declaration_history_complete",
        "attempted_play_history_complete", "completed_tricks",
        "current_trick", "deductions", "source_sha256s",
    }
    row = _exact_keys(payload, keys, label="actor payload")
    if row["schema"] != ACTOR_OBSERVATION_SCHEMA \
            or row["perspective"] != "acting-seat-relative-zero" \
            or row["phase"] != "play" \
            or type(row["trump_rank"]) is not str \
            or row["trump_rank"] not in RANKS \
            or type(row["trump_is_nt"]) is not bool \
            or (row["trump_is_nt"] and row["trump_suit"] is not None) \
            or (not row["trump_is_nt"] and row["trump_suit"] not in SUITS) \
            or row["source_sha256s"] != BELIEF_CONTRACT_SOURCE_SHA256S:
        raise BeliefReopenError("actor identity or source boundary drift")
    ordering = Ordering(row["trump_suit"], row["trump_rank"])
    banker = _integer(row["banker_relative"], label="banker relative", high=3)
    if type(row["actor_is_attacker"]) is not bool \
            or row["actor_is_attacker"] != (banker % 2 == 1):
        raise BeliefReopenError("actor role drift")
    attacker_points = _integer(row["attacker_points"],
                               label="attacker points")
    if type(row["hand_sizes_relative"]) is not list \
            or len(row["hand_sizes_relative"]) != 4:
        raise BeliefReopenError("actor hand-size population drift")
    hand_sizes = tuple(_integer(size, label="actor hand size", high=33)
                       for size in row["hand_sizes_relative"])
    actor_hand = _counts(row["actor_hand"], label="actor hand")
    burial = _counts(row["actor_known_burial"], label="actor known burial")
    hidden_burial_size = _integer(
        row["hidden_burial_size"], label="hidden burial size", high=8)
    if sum(count for _, count in actor_hand) != hand_sizes[0] \
            or (banker == 0 and (
                sum(count for _, count in burial) != 8
                or hidden_burial_size != 0)) \
            or (banker != 0 and (burial or hidden_burial_size != 8)):
        raise BeliefReopenError("actor private-card boundary drift")

    declaration = None if row["declaration"] is None else _declaration(
        row["declaration"], ordering=ordering, label="final declaration")
    if type(row["declaration_history"]) is not list \
            or row["declaration_history_complete"] is not True \
            or row["attempted_play_history_complete"] is not True:
        raise BeliefReopenError("actor public history is incomplete")
    declarations = tuple(_declaration(
        value, ordering=ordering, label=f"declaration {index}")
        for index, value in enumerate(row["declaration_history"]))
    if any(left.strength >= right.strength
           for left, right in zip(declarations, declarations[1:])) \
            or ((declaration is None) != (not declarations)) \
            or (declaration is not None and declarations[-1] != declaration):
        raise BeliefReopenError("actor declaration history drift")
    if type(row["completed_tricks"]) is not list:
        raise BeliefReopenError("actor completed tricks are malformed")
    completed = tuple(_trick(
        trick, ordering=ordering, complete=True,
        label=f"completed trick {index}")
        for index, trick in enumerate(row["completed_tricks"]))
    current = _trick(row["current_trick"], ordering=ordering, complete=False,
                     label="current trick")
    deductions = _deductions(row["deductions"])

    played = Counter(card for trick in (*completed, current)
                     for play in trick.plays for card in play.cards)
    played_by = [Counter() for _ in range(4)]
    for trick in (*completed, current):
        for play in trick.plays:
            played_by[play.seat_relative].update(play.cards)
    if tuple(sorted(played.items())) != deductions.played \
            or tuple(tuple(sorted(counts.items())) for counts in played_by) \
            != deductions.played_by_relative:
        raise BeliefReopenError("actor public play deductions drift")
    known = Counter(dict(actor_hand)) + Counter(dict(burial))
    unseen = Counter(dict(deductions.unseen))
    for card in _CARD_CODES:
        if known[card] + played[card] + unseen[card] != 2:
            raise BeliefReopenError("actor unseen-card conservation drift")
    hidden_size = sum(hand_sizes[1:]) + hidden_burial_size
    if sum(unseen.values()) != hidden_size:
        raise BeliefReopenError("actor hidden receiver conservation drift")
    for card, relative, copies in deductions.declaration_pins:
        if unseen[card] < copies:
            raise BeliefReopenError("actor declaration pin exceeds unseen")
    expected_eligibility = ()
    if declaration is not None \
            and declaration.seat_relative == banker \
            and banker != 0:
        expected_rows = []
        declared = Counter(declaration.cards)
        banker_played = dict(deductions.played_by_relative[banker])
        for card, copies in sorted(declared.items()):
            remaining = copies - banker_played.get(card, 0)
            if remaining > 0:
                expected_rows.append(DeclarationEligibilityV1(
                    card=card,
                    eligible_receivers=(
                        f"seat-relative-{banker}", HIDDEN_KITTY_RECEIVER),
                    minimum_copies=remaining,
                ))
        expected_eligibility = tuple(expected_rows)
    if deductions.declaration_eligibility != expected_eligibility:
        raise BeliefReopenError("actor declaration eligibility drift")

    actor = ActorObservationV1(
        schema=row["schema"],
        trump_rank=row["trump_rank"], trump_suit=row["trump_suit"],
        trump_is_nt=row["trump_is_nt"], banker_relative=banker,
        actor_is_attacker=row["actor_is_attacker"],
        attacker_points=attacker_points, hand_sizes_relative=hand_sizes,
        actor_hand=actor_hand, actor_known_burial=burial,
        hidden_burial_size=hidden_burial_size,
        declaration=declaration, declaration_history=declarations,
        declaration_history_complete=True,
        attempted_play_history_complete=True,
        completed_tricks=completed, current_trick=current,
        deductions=deductions,
    )
    if actor.to_dict() != payload:
        raise BeliefReopenError("actor payload is not canonical typed V1")
    return actor


def belief_targets_from_dict(
        payload: dict[str, Any], *,
        actor: ActorObservationV1 | None = None) -> BeliefTargetsV1:
    """Rebuild one exact privileged target and optionally bind its actor."""
    row = _exact_keys(payload, {
        "schema", "perspective", "other_hands", "hidden_burial",
        "hidden_burial_count",
    }, label="target payload")
    if row["schema"] != BELIEF_TARGETS_SCHEMA \
            or row["perspective"] != "acting-seat-relative-zero" \
            or type(row["other_hands"]) is not list \
            or len(row["other_hands"]) != 3:
        raise BeliefReopenError("target identity or receiver population drift")
    hands = []
    for expected_relative, value in enumerate(row["other_hands"], start=1):
        hand = _exact_keys(
            value, {"seat_relative", "cards", "card_count"},
            label="target hand")
        if _integer(hand["seat_relative"], label="target relative seat",
                    low=1, high=3) != expected_relative:
            raise BeliefReopenError("target receiver order drift")
        cards = _counts(hand["cards"], label="target hand")
        if _integer(hand["card_count"], label="target hand count", high=33) \
                != sum(count for _, count in cards):
            raise BeliefReopenError("target hand count drift")
        hands.append(HiddenReceiverView(
            seat_relative=expected_relative, cards=cards))
    burial = _counts(row["hidden_burial"], label="target hidden burial")
    if _integer(row["hidden_burial_count"], label="target burial count",
                high=8) != sum(count for _, count in burial):
        raise BeliefReopenError("target burial count drift")
    target = BeliefTargetsV1(
        schema=row["schema"], other_hands=tuple(hands),
        hidden_burial=burial)
    if target.to_dict() != payload:
        raise BeliefReopenError("target payload is not canonical typed V1")
    if actor is not None:
        if type(actor) is not ActorObservationV1:
            raise BeliefReopenError("target actor binding type drift")
        if tuple(sum(count for _, count in hand.cards)
                 for hand in target.other_hands) \
                != actor.hand_sizes_relative[1:] \
                or sum(count for _, count in target.hidden_burial) \
                != actor.hidden_burial_size:
            raise BeliefReopenError("target receiver sizes disagree with actor")
        target_counts = Counter()
        for hand in target.other_hands:
            target_counts.update(dict(hand.cards))
        target_counts.update(dict(target.hidden_burial))
        if target_counts != Counter(dict(actor.deductions.unseen)):
            raise BeliefReopenError("target ownership disagrees with actor unseen")
    return target
