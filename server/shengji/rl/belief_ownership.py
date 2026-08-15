"""Exact output contract for BELIEF-V1's B2 ownership model.

This module validates quantized hidden-receiver count probabilities against an
``ActorObservationV1``.  It does not contain a model, read privileged targets,
sample a world, choose an action, or register a runtime policy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..engine.cards import Ordering, make_deck
from .belief_contract import (HIDDEN_KITTY_RECEIVER, ActorObservationV1,
                              DeclarationEligibilityV1,
                              canonical_json_bytes)


OWNERSHIP_SCHEMA = "belief-v1-hidden-ownership-probability-v1"
COUNT_PROBABILITY_SCHEMA = "belief-v1-receiver-count-probability-v1"
PROBABILITY_SCALE = 1_000_000_000
INFORMATION_TAG = "probabilistic_policy_conditioned"
KITTY_RECEIVER = HIDDEN_KITTY_RECEIVER
SEAT_RECEIVERS = tuple(f"seat-relative-{relative}" for relative in range(1, 4))
_CARD_CODES = frozenset(make_deck())


class BeliefOwnershipError(ValueError):
    """A candidate ownership distribution violates the actor-visible contract."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BeliefOwnershipError("ownership JSON has a duplicate key")
        result[key] = value
    return result


def _reject_noninteger_number(value: str) -> None:
    raise BeliefOwnershipError(
        f"ownership JSON contains a non-integer number: {value}")


def _strict_json(raw: bytes) -> Any:
    if type(raw) is not bytes or not raw:
        raise BeliefOwnershipError("ownership artifact must be nonempty bytes")
    try:
        text = raw.decode("ascii")
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_noninteger_number,
            parse_constant=_reject_noninteger_number,
        )
    except BeliefOwnershipError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefOwnershipError("ownership artifact is not strict JSON") from exc


def receiver_sizes(actor: ActorObservationV1) -> tuple[tuple[str, int], ...]:
    """Return the exact actor-relative hidden receiver population."""
    sizes = tuple(
        (SEAT_RECEIVERS[relative - 1], actor.hand_sizes_relative[relative])
        for relative in range(1, 4)
    )
    if actor.hidden_burial_size:
        sizes = (*sizes, (KITTY_RECEIVER, actor.hidden_burial_size))
    return sizes


@dataclass(frozen=True)
class ReceiverCountProbabilityV1:
    card: str
    receiver: str
    count_0_ppb: int
    count_1_ppb: int
    count_2_ppb: int
    schema: str = COUNT_PROBABILITY_SCHEMA

    @property
    def expected_count_ppb(self) -> int:
        return self.count_1_ppb + 2 * self.count_2_ppb

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "card": self.card,
            "receiver": self.receiver,
            "count_probability_ppb": [
                self.count_0_ppb,
                self.count_1_ppb,
                self.count_2_ppb,
            ],
            "expected_count_ppb": self.expected_count_ppb,
        }


@dataclass(frozen=True)
class BeliefOwnershipV1:
    actor_observation_sha256: str
    model_schema: str
    model_sha256: str
    behavior_policy_ids: tuple[str, ...]
    receiver_sizes: tuple[tuple[str, int], ...]
    probabilities: tuple[ReceiverCountProbabilityV1, ...]
    information_tag: str = INFORMATION_TAG
    schema: str = OWNERSHIP_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "information_tag": self.information_tag,
            "actor_observation_sha256": self.actor_observation_sha256,
            "model_schema": self.model_schema,
            "model_sha256": self.model_sha256,
            "behavior_policy_ids": list(self.behavior_policy_ids),
            "probability_scale": PROBABILITY_SCALE,
            "receiver_sizes": [
                {"receiver": receiver, "card_count": size}
                for receiver, size in self.receiver_sizes
            ],
            "count_probabilities": [row.to_dict()
                                    for row in self.probabilities],
            "privileged_targets_consumed": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def validate_ownership(actor: ActorObservationV1,
                       belief: BeliefOwnershipV1) -> None:
    """Validate exact mechanics without consulting the hidden-world target."""
    if type(actor) is not ActorObservationV1:
        raise BeliefOwnershipError("ownership requires an exact actor observation")
    if not actor.declaration_history_complete \
            or not actor.attempted_play_history_complete:
        raise BeliefOwnershipError("ownership requires complete public history")
    if type(belief) is not BeliefOwnershipV1:
        raise BeliefOwnershipError("ownership payload must be exact V1")
    if belief.schema != OWNERSHIP_SCHEMA \
            or belief.information_tag != INFORMATION_TAG:
        raise BeliefOwnershipError("ownership schema or information tag drift")
    if belief.actor_observation_sha256 != actor.sha256():
        raise BeliefOwnershipError("ownership actor binding drift")
    if type(belief.model_schema) is not str or not belief.model_schema \
            or not _is_sha256(belief.model_sha256):
        raise BeliefOwnershipError("ownership model identity is invalid")
    if type(belief.behavior_policy_ids) is not tuple \
            or not belief.behavior_policy_ids \
            or any(type(policy) is not str or not policy
                   for policy in belief.behavior_policy_ids) \
            or tuple(sorted(set(belief.behavior_policy_ids))) \
            != belief.behavior_policy_ids:
        raise BeliefOwnershipError("behavior policy identity is invalid")

    expected_receivers = receiver_sizes(actor)
    if type(belief.receiver_sizes) is not tuple \
            or belief.receiver_sizes != expected_receivers:
        raise BeliefOwnershipError("hidden receiver population drift")
    receivers = tuple(receiver for receiver, _ in expected_receivers)
    receiver_capacity = dict(expected_receivers)
    unseen = dict(actor.deductions.unseen)
    if sum(unseen.values()) != sum(receiver_capacity.values()):
        raise BeliefOwnershipError("actor unseen and receiver sizes disagree")

    expected_keys = tuple(
        (card, receiver)
        for card in sorted(unseen)
        for receiver in receivers
    )
    if type(belief.probabilities) is not tuple \
            or tuple((row.card, row.receiver)
                     for row in belief.probabilities) != expected_keys:
        raise BeliefOwnershipError("count-probability population/order drift")

    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    voids = {
        SEAT_RECEIVERS[relative - 1]: set(
            actor.deductions.voids_by_relative[relative])
        for relative in range(1, 4)
    }
    zero_pair_suits = {
        SEAT_RECEIVERS[relative - 1]: {
            suit for suit, cap
            in actor.deductions.pair_caps_by_relative[relative]
            if cap == 0
        }
        for relative in range(1, 4)
    }
    rows: dict[tuple[str, str], ReceiverCountProbabilityV1] = {}
    expected_by_receiver = {receiver: 0 for receiver in receivers}
    expected_by_card = {card: 0 for card in unseen}
    for row in belief.probabilities:
        if type(row) is not ReceiverCountProbabilityV1 \
                or row.schema != COUNT_PROBABILITY_SCHEMA \
                or row.card not in _CARD_CODES \
                or row.receiver not in receiver_capacity:
            raise BeliefOwnershipError("count-probability row is malformed")
        values = (row.count_0_ppb, row.count_1_ppb, row.count_2_ppb)
        if any(type(value) is not int or not 0 <= value <= PROBABILITY_SCALE
               for value in values) \
                or sum(values) != PROBABILITY_SCALE:
            raise BeliefOwnershipError("count probability is invalid")
        if unseen[row.card] == 1 and row.count_2_ppb != 0:
            raise BeliefOwnershipError("one-copy card has two-copy mass")
        if receiver_capacity[row.receiver] < 2 and row.count_2_ppb != 0:
            raise BeliefOwnershipError("receiver capacity forbids two copies")
        if row.receiver in voids \
                and ordering.eff_suit(row.card) in voids[row.receiver] \
                and row.count_0_ppb != PROBABILITY_SCALE:
            raise BeliefOwnershipError("proven void carries positive mass")
        if row.receiver in zero_pair_suits \
                and ordering.eff_suit(row.card) \
                in zero_pair_suits[row.receiver] \
                and row.count_2_ppb != 0:
            raise BeliefOwnershipError("proven zero-pair cap carries pair mass")
        rows[(row.card, row.receiver)] = row
        expected_by_receiver[row.receiver] += row.expected_count_ppb
        expected_by_card[row.card] += row.expected_count_ppb

    for card, copies in unseen.items():
        if expected_by_card[card] != copies * PROBABILITY_SCALE:
            raise BeliefOwnershipError("card expectation violates conservation")
    for receiver, size in receiver_capacity.items():
        if expected_by_receiver[receiver] != size * PROBABILITY_SCALE:
            raise BeliefOwnershipError("receiver expectation violates conservation")

    for card, relative, copies in actor.deductions.declaration_pins:
        if card not in _CARD_CODES or type(relative) is not int \
                or relative not in range(1, 4) or type(copies) is not int \
                or copies not in (1, 2):
            raise BeliefOwnershipError("declaration pin is malformed")
        owner = f"seat-relative-{relative}"
        if card not in unseen or owner not in receiver_capacity:
            raise BeliefOwnershipError("declaration pin is outside hidden receivers")
        for receiver in receivers:
            row = rows[(card, receiver)]
            if copies == 2:
                required = 2 if receiver == owner else 0
                probabilities = (
                    row.count_0_ppb, row.count_1_ppb, row.count_2_ppb)
                if probabilities[required] != PROBABILITY_SCALE:
                    raise BeliefOwnershipError(
                        "declared pair is not probability-one ownership")
            elif receiver == owner and row.count_0_ppb != 0:
                raise BeliefOwnershipError(
                    "single declaration has probability of absent owner")
            elif receiver != owner and row.count_2_ppb != 0:
                raise BeliefOwnershipError(
                    "single declaration leaves two-copy mass elsewhere")

    pinned_cards = {card for card, _, _
                    in actor.deductions.declaration_pins}
    eligibility_cards = set()
    for constraint in actor.deductions.declaration_eligibility:
        if type(constraint) is not DeclarationEligibilityV1 \
                or constraint.card not in _CARD_CODES \
                or type(constraint.eligible_receivers) is not tuple \
                or len(constraint.eligible_receivers) != 2 \
                or len(set(constraint.eligible_receivers)) != 2 \
                or any(type(receiver) is not str
                       or receiver not in receiver_capacity
                       for receiver in constraint.eligible_receivers) \
                or type(constraint.minimum_copies) is not int \
                or constraint.minimum_copies not in (1, 2) \
                or constraint.card not in unseen \
                or constraint.minimum_copies > unseen[constraint.card] \
                or constraint.card in pinned_cards \
                or constraint.card in eligibility_cards:
            raise BeliefOwnershipError(
                "declaration eligibility is malformed")
        eligibility_cards.add(constraint.card)
        eligible = set(constraint.eligible_receivers)
        eligible_expectation = sum(
            rows[(constraint.card, receiver)].expected_count_ppb
            for receiver in eligible
        )
        if eligible_expectation \
                < constraint.minimum_copies * PROBABILITY_SCALE:
            raise BeliefOwnershipError(
                "declared copies leave their eligible receiver set")
        outside_capacity = unseen[constraint.card] \
            - constraint.minimum_copies
        for receiver in receivers:
            if receiver in eligible:
                continue
            row = rows[(constraint.card, receiver)]
            if outside_capacity == 0 \
                    and row.count_0_ppb != PROBABILITY_SCALE:
                raise BeliefOwnershipError(
                    "declared copies carry mass outside eligible receivers")
            if outside_capacity == 1 and row.count_2_ppb != 0:
                raise BeliefOwnershipError(
                    "single declared copy leaves pair mass outside eligibility")


def ownership_from_bytes(actor: ActorObservationV1,
                         raw: bytes) -> BeliefOwnershipV1:
    """Strictly reopen, reconstruct, and validate exact artifact bytes."""
    payload = _strict_json(raw)
    root_keys = {
        "schema", "information_tag", "actor_observation_sha256",
        "model_schema", "model_sha256", "behavior_policy_ids",
        "probability_scale", "receiver_sizes", "count_probabilities",
        "privileged_targets_consumed",
    }
    if type(payload) is not dict or set(payload) != root_keys:
        raise BeliefOwnershipError("ownership artifact root schema is open")
    if payload["privileged_targets_consumed"] is not False:
        raise BeliefOwnershipError("ownership artifact consumed privileged targets")
    if type(payload["probability_scale"]) is not int \
            or payload["probability_scale"] != PROBABILITY_SCALE:
        raise BeliefOwnershipError("ownership probability scale drift")
    if type(payload["behavior_policy_ids"]) is not list \
            or type(payload["receiver_sizes"]) is not list \
            or type(payload["count_probabilities"]) is not list:
        raise BeliefOwnershipError("ownership artifact population is malformed")

    receiver_rows: list[tuple[str, int]] = []
    for row in payload["receiver_sizes"]:
        if type(row) is not dict or set(row) != {"receiver", "card_count"} \
                or type(row["receiver"]) is not str \
                or type(row["card_count"]) is not int:
            raise BeliefOwnershipError("ownership receiver row is malformed")
        receiver_rows.append((row["receiver"], row["card_count"]))

    probability_rows: list[ReceiverCountProbabilityV1] = []
    probability_keys = {
        "schema", "card", "receiver", "count_probability_ppb",
        "expected_count_ppb",
    }
    for row in payload["count_probabilities"]:
        if type(row) is not dict or set(row) != probability_keys \
                or type(row["schema"]) is not str \
                or type(row["card"]) is not str \
                or type(row["receiver"]) is not str \
                or type(row["count_probability_ppb"]) is not list \
                or len(row["count_probability_ppb"]) != 3 \
                or type(row["expected_count_ppb"]) is not int:
            raise BeliefOwnershipError(
                "ownership count-probability row is malformed")
        probabilities = row["count_probability_ppb"]
        if any(type(value) is not int for value in probabilities):
            raise BeliefOwnershipError("ownership count probability is invalid")
        if row["expected_count_ppb"] != probabilities[1] \
                + 2 * probabilities[2]:
            raise BeliefOwnershipError("ownership expected-count field drift")
        probability_rows.append(ReceiverCountProbabilityV1(
            schema=row["schema"],
            card=row["card"],
            receiver=row["receiver"],
            count_0_ppb=probabilities[0],
            count_1_ppb=probabilities[1],
            count_2_ppb=probabilities[2],
        ))

    belief = BeliefOwnershipV1(
        schema=payload["schema"],
        information_tag=payload["information_tag"],
        actor_observation_sha256=payload["actor_observation_sha256"],
        model_schema=payload["model_schema"],
        model_sha256=payload["model_sha256"],
        behavior_policy_ids=tuple(payload["behavior_policy_ids"]),
        receiver_sizes=tuple(receiver_rows),
        probabilities=tuple(probability_rows),
    )
    validate_ownership(actor, belief)
    if belief.canonical_bytes() != raw:
        raise BeliefOwnershipError("ownership artifact is not canonical bytes")
    return belief


def count_brier_fraction(
        belief: BeliefOwnershipV1,
        true_counts: dict[tuple[str, str], int]) -> tuple[int, int]:
    """Return the exact numerator/denominator of mean receiver-count Brier.

    ``true_counts`` is an offline evaluator input. It is intentionally not a
    field or method argument of runtime construction/validation.
    """
    keys = tuple((row.card, row.receiver) for row in belief.probabilities)
    if type(true_counts) is not dict or set(true_counts) != set(keys) \
            or any(type(value) is not int or value not in (0, 1, 2)
                   for value in true_counts.values()):
        raise BeliefOwnershipError("true-count evaluation population is invalid")
    numerator = 0
    for row in belief.probabilities:
        truth = true_counts[(row.card, row.receiver)]
        for count, probability in enumerate((
                row.count_0_ppb, row.count_1_ppb, row.count_2_ppb)):
            target = PROBABILITY_SCALE if count == truth else 0
            numerator += (probability - target) ** 2
    denominator = len(keys) * PROBABILITY_SCALE ** 2
    return numerator, denominator
