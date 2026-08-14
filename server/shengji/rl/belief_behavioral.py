"""Public behavioral signals and separated private audits for BELIEF-V1.

The ownership model consumes the raw public history, not these labels.  This
module derives inspectable C2 evaluation strata from the same history:

* a player declined a point feed while their partner was winning;
* a player chose a point card despite a legal nonpoint alternative; and
* a player exposed one joker while following a trump-pair lead without a pair.

The public record contains only observable action context.  Whether a legal
alternative actually existed, and the actor's pre-play trump count, live in a
separate privileged audit artifact.  This is policy-conditioned evidence, not
a logical ownership fact.  The module has no model, sampler, training,
filesystem, policy, gameplay mutation, or execution authority.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ..engine.cards import Ordering, TRUMP, is_joker, points
from ..engine.combos import decompose
from ..engine.legal import beats, uniform_suit
from .belief_capture import (CapturedBeliefRoundV1, BeliefCaptureError,
                             validate_captured_round)
from .belief_contract import (ActorObservationV1, CapturedPlayEvent,
                              canonical_json_bytes)
from .belief_corpus import BeliefCorpusError, reopen_actor_row


PUBLIC_SIGNAL_SCHEMA = "belief-v1-public-choice-signal-v1"
PRIVILEGED_AUDIT_SCHEMA = "belief-v1-privileged-choice-audit-v1"
BEHAVIORAL_ROUND_SCHEMA = "belief-v1-behavioral-signal-round-v1"
BEHAVIORAL_EXPOSURE_SCHEMA = "belief-v1-behavioral-signal-exposure-v1"
DECLINED_POINT_FEED = "declined-point-feed-single-v1"
UNFORCED_POINT_PLAY = "unforced-point-play-single-v1"
FORCED_SINGLE_JOKER = "single-joker-on-trump-pair-v1"
SIGNAL_KINDS = (
    DECLINED_POINT_FEED, FORCED_SINGLE_JOKER, UNFORCED_POINT_PLAY)


class BeliefBehavioralError(ValueError):
    """A public signal or its separated private audit drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class PublicChoiceSignalV1:
    round_seed: int
    decision_index: int
    acting_seat: int
    signal_kind: str
    actual_cards: tuple[str, ...]
    public_context_sha256: str
    policy_assumption: str = "mc-s0-report-lcb-behavior-conditioned-v1"
    information_tag: str = "probabilistic_policy_conditioned"
    schema: str = PUBLIC_SIGNAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_seed": self.round_seed,
            "decision_index": self.decision_index,
            "acting_seat": self.acting_seat,
            "signal_kind": self.signal_kind,
            "actual_cards": list(self.actual_cards),
            "public_context_sha256": self.public_context_sha256,
            "policy_assumption": self.policy_assumption,
            "information_tag": self.information_tag,
            "contains_actor_hand": False,
            "contains_privileged_target": False,
            "logical_fact_claimed": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class PrivilegedChoiceAuditV1:
    public_signal_sha256: str
    source_actor_observation_sha256: str
    signal_kind: str
    alternative_available: bool | None
    eligible_point_card_count: int | None
    eligible_nonpoint_card_count: int | None
    preplay_trump_count: int | None
    preplay_trump_pair_type_count: int | None
    schema: str = PRIVILEGED_AUDIT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "public_signal_sha256": self.public_signal_sha256,
            "source_actor_observation_sha256": (
                self.source_actor_observation_sha256),
            "signal_kind": self.signal_kind,
            "alternative_available": self.alternative_available,
            "eligible_point_card_count": self.eligible_point_card_count,
            "eligible_nonpoint_card_count": (
                self.eligible_nonpoint_card_count),
            "preplay_trump_count": self.preplay_trump_count,
            "preplay_trump_pair_type_count": (
                self.preplay_trump_pair_type_count),
            "privileged_actor_hand_consumed": True,
            "runtime_input": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class BehavioralSignalRoundV1:
    round_seed: int
    public_signals: tuple[PublicChoiceSignalV1, ...]
    privileged_audits: tuple[PrivilegedChoiceAuditV1, ...]
    schema: str = BEHAVIORAL_ROUND_SCHEMA

    def public_bytes(self) -> bytes:
        return canonical_json_bytes({
            "schema": self.schema,
            "round_seed": self.round_seed,
            "public_signals": [row.to_dict() for row in self.public_signals],
            "contains_privileged_audits": False,
            "runtime_input": False,
        })

    def privileged_bytes(self) -> bytes:
        return canonical_json_bytes({
            "schema": self.schema,
            "round_seed": self.round_seed,
            "public_stream_sha256": hashlib.sha256(
                self.public_bytes()).hexdigest(),
            "privileged_audits": [
                row.to_dict() for row in self.privileged_audits],
            "runtime_input": False,
        })


@dataclass(frozen=True)
class BehavioralSignalExposureV1:
    round_seed: int
    decision_index: int
    decision_key: str
    actor_seat: int
    source_acting_seat: int
    source_signal_sha256: str
    signal_kind: str
    receiver: str
    privileged_signal_confirmed: bool
    schema: str = BEHAVIORAL_EXPOSURE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_seed": self.round_seed,
            "decision_index": self.decision_index,
            "decision_key": self.decision_key,
            "actor_seat": self.actor_seat,
            "source_acting_seat": self.source_acting_seat,
            "source_signal_sha256": self.source_signal_sha256,
            "signal_kind": self.signal_kind,
            "receiver": self.receiver,
            "privileged_signal_confirmed": (
                self.privileged_signal_confirmed),
            "privileged_evaluation_artifact": True,
            "runtime_input": False,
        }


def _public_context(actor: ActorObservationV1, metadata: dict[str, Any],
                    event: CapturedPlayEvent) -> bytes:
    return canonical_json_bytes({
        "schema": "belief-v1-public-choice-context-v1",
        "round_seed": metadata["round_seed"],
        "decision_index": metadata["decision_index"],
        "acting_seat": metadata["actor_seat"],
        "trump_rank": actor.trump_rank,
        "trump_suit": actor.trump_suit,
        "trump_is_nt": actor.trump_is_nt,
        "banker_seat": (metadata["actor_seat"]
                        + actor.banker_relative) % 4,
        "attacker_points": actor.attacker_points,
        "completed_trick_count": len(actor.completed_tricks),
        "declaration": (None if actor.declaration is None
                        else actor.declaration.to_dict()),
        "current_trick": actor.current_trick.to_dict(),
        "attempted_cards": list(event.attempted_cards),
        "actual_cards": list(event.actual_cards),
        "contains_actor_hand": False,
        "contains_privileged_target": False,
    })


def _current_winner_relative(actor: ActorObservationV1,
                             ordering: Ordering) -> int | None:
    plays = actor.current_trick.plays
    if not plays:
        return None
    lead = list(plays[0].cards)
    incumbent_suit = uniform_suit(lead, ordering)
    if incumbent_suit is None:
        raise BeliefBehavioralError("behavioral lead is not a uniform suit")
    incumbent_top = decompose(lead, ordering).top_level()
    winner = plays[0].seat_relative
    for play in plays[1:]:
        won, top = beats(list(play.cards), lead, incumbent_suit,
                         incumbent_top, ordering)
        if won:
            winner = play.seat_relative
            incumbent_top = top
            incumbent_suit = ordering.eff_suit(play.cards[0])
    return winner


def _eligible_single_cards(actor: ActorObservationV1,
                           ordering: Ordering) -> tuple[str, ...]:
    hand = tuple(card for card, count in actor.actor_hand
                 for _ in range(count))
    plays = actor.current_trick.plays
    if not plays:
        return hand
    lead = plays[0].cards
    if len(lead) != 1:
        raise BeliefBehavioralError("single-card signal has nonsingle lead")
    lead_suit = ordering.eff_suit(lead[0])
    matching = tuple(card for card in hand
                     if ordering.eff_suit(card) == lead_suit)
    return matching or hand


def _signal(actor: ActorObservationV1, metadata: dict[str, Any],
            event: CapturedPlayEvent, kind: str,
            *, alternative: bool | None,
            point_cards: int | None, nonpoint_cards: int | None,
            trump_count: int | None, trump_pairs: int | None) \
        -> tuple[PublicChoiceSignalV1, PrivilegedChoiceAuditV1]:
    context_sha = hashlib.sha256(
        _public_context(actor, metadata, event)).hexdigest()
    public = PublicChoiceSignalV1(
        round_seed=metadata["round_seed"],
        decision_index=metadata["decision_index"],
        acting_seat=metadata["actor_seat"], signal_kind=kind,
        actual_cards=event.actual_cards,
        public_context_sha256=context_sha)
    audit = PrivilegedChoiceAuditV1(
        public_signal_sha256=public.sha256(),
        source_actor_observation_sha256=actor.sha256(),
        signal_kind=kind, alternative_available=alternative,
        eligible_point_card_count=point_cards,
        eligible_nonpoint_card_count=nonpoint_cards,
        preplay_trump_count=trump_count,
        preplay_trump_pair_type_count=trump_pairs)
    return public, audit


def _classify_choice_signals(
        actor: ActorObservationV1, metadata: dict[str, Any],
        event: CapturedPlayEvent) \
        -> tuple[tuple[PublicChoiceSignalV1, PrivilegedChoiceAuditV1], ...]:
    """Classify one action without opening another player's hidden target."""
    expected_metadata = {
        "round_seed", "decision_index", "actor_seat", "decision_key",
        "split_schema", "split"}
    if type(actor) is not ActorObservationV1 \
            or type(metadata) is not dict or set(metadata) != expected_metadata \
            or type(event) is not CapturedPlayEvent \
            or event.seat != metadata["actor_seat"]:
        raise BeliefBehavioralError("behavioral action identity drift")
    hand = Counter(dict(actor.actor_hand))
    if Counter(event.actual_cards) - hand:
        raise BeliefBehavioralError("behavioral actual play is outside hand")
    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    result = []

    if len(event.actual_cards) == 1 \
            and (not actor.current_trick.plays
                 or len(actor.current_trick.plays[0].cards) == 1):
        eligible = _eligible_single_cards(actor, ordering)
        if event.actual_cards[0] not in eligible:
            raise BeliefBehavioralError(
                "behavioral single violates follow obligation")
        point_count = sum(points(card) > 0 for card in eligible)
        nonpoint_count = sum(points(card) == 0 for card in eligible)
        winner = _current_winner_relative(actor, ordering)
        if winner == 2 and points(event.actual_cards[0]) == 0:
            result.append(_signal(
                actor, metadata, event, DECLINED_POINT_FEED,
                alternative=point_count > 0,
                point_cards=point_count, nonpoint_cards=nonpoint_count,
                trump_count=None, trump_pairs=None))
        if points(event.actual_cards[0]) > 0:
            result.append(_signal(
                actor, metadata, event, UNFORCED_POINT_PLAY,
                alternative=nonpoint_count > 0,
                point_cards=point_count, nonpoint_cards=nonpoint_count,
                trump_count=None, trump_pairs=None))

    plays = actor.current_trick.plays
    if plays:
        lead = plays[0].cards
        is_trump_pair = (len(lead) == 2 and lead[0] == lead[1]
                         and ordering.eff_suit(lead[0]) == TRUMP)
        actual = event.actual_cards
        single_joker = (len(actual) == 2
                        and sum(is_joker(card) for card in actual) == 1
                        and actual[0] != actual[1])
        if is_trump_pair and single_joker:
            trumps = tuple(card for card, count in actor.actor_hand
                           for _ in range(count)
                           if ordering.eff_suit(card) == TRUMP)
            trump_pairs = sum(count >= 2 for card, count in Counter(
                trumps).items())
            result.append(_signal(
                actor, metadata, event, FORCED_SINGLE_JOKER,
                alternative=None, point_cards=None, nonpoint_cards=None,
                trump_count=len(trumps), trump_pairs=trump_pairs))
    return tuple(result)


def classify_choice_signals(
        actor_row_bytes: bytes, event: CapturedPlayEvent) \
        -> tuple[tuple[PublicChoiceSignalV1, PrivilegedChoiceAuditV1], ...]:
    """Classify one action from an authenticated target-blind actor row."""
    try:
        actor, metadata = reopen_actor_row(actor_row_bytes)
    except BeliefCorpusError as exc:
        raise BeliefBehavioralError("behavioral actor row refused") from exc
    return _classify_choice_signals(actor, metadata, event)


def build_behavioral_signal_round(
        captured: CapturedBeliefRoundV1) -> BehavioralSignalRoundV1:
    """Derive separated public/audit signal streams for one full round."""
    try:
        validate_captured_round(captured)
    except BeliefCaptureError as exc:
        raise BeliefBehavioralError("behavioral capture refused") from exc
    public = []
    audits = []
    for pair, event in zip(captured.pairs,
                           captured.public_transcript.plays, strict=True):
        for signal, audit in classify_choice_signals(
                pair.actor_bytes, event):
            public.append(signal)
            audits.append(audit)
    result = BehavioralSignalRoundV1(
        round_seed=captured.round_seed, public_signals=tuple(public),
        privileged_audits=tuple(audits))
    validate_behavioral_signal_round(captured, result)
    return result


def validate_behavioral_signal_round(
        captured: CapturedBeliefRoundV1,
        result: BehavioralSignalRoundV1) -> None:
    if type(result) is not BehavioralSignalRoundV1 \
            or result.schema != BEHAVIORAL_ROUND_SCHEMA \
            or result.round_seed != captured.round_seed \
            or type(result.public_signals) is not tuple \
            or type(result.privileged_audits) is not tuple \
            or len(result.public_signals) != len(result.privileged_audits):
        raise BeliefBehavioralError("behavioral signal round schema drift")
    rebuilt_public = []
    rebuilt_audits = []
    for pair, event in zip(captured.pairs,
                           captured.public_transcript.plays, strict=True):
        for signal, audit in classify_choice_signals(
                pair.actor_bytes, event):
            rebuilt_public.append(signal)
            rebuilt_audits.append(audit)
    if tuple(rebuilt_public) != result.public_signals \
            or tuple(rebuilt_audits) != result.privileged_audits \
            or any(type(signal) is not PublicChoiceSignalV1
                   or signal.signal_kind not in SIGNAL_KINDS
                   or not _is_sha256(signal.public_context_sha256)
                   for signal in result.public_signals) \
            or any(type(audit) is not PrivilegedChoiceAuditV1
                   or audit.public_signal_sha256 != signal.sha256()
                   for signal, audit in zip(
                       result.public_signals, result.privileged_audits,
                       strict=True)):
        raise BeliefBehavioralError("behavioral signal derivation drift")


def behavioral_signal_exposures(
        captured: CapturedBeliefRoundV1,
        result: BehavioralSignalRoundV1) \
        -> tuple[BehavioralSignalExposureV1, ...]:
    """Bind each signal to downstream decisions until its source acts again.

    A signal remains active until its source seat acts again.  This gives a
    fixed natural-frequency horizon: the intervening players may update their
    beliefs about that seat, while the source's own next decision is excluded
    because ownership output never predicts the actor's own hand.
    """
    validate_behavioral_signal_round(captured, result)
    signals_by_index: dict[int, list[tuple[
        PublicChoiceSignalV1, PrivilegedChoiceAuditV1]]] = {}
    for signal, audit in zip(result.public_signals,
                             result.privileged_audits, strict=True):
        signals_by_index.setdefault(signal.decision_index, []).append(
            (signal, audit))
    active: dict[int, tuple[
        tuple[PublicChoiceSignalV1, PrivilegedChoiceAuditV1], ...]] = {}
    exposures = []
    for pair in captured.pairs:
        actor, metadata = reopen_actor_row(pair.actor_bytes)
        del actor
        actor_seat = metadata["actor_seat"]
        for source_seat in sorted(active):
            if source_seat == actor_seat:
                continue
            receiver = f"seat-relative-{(source_seat - actor_seat) % 4}"
            for signal, audit in active[source_seat]:
                confirmed = (audit.alternative_available is True
                             if signal.signal_kind != FORCED_SINGLE_JOKER
                             else audit.preplay_trump_pair_type_count == 0)
                exposures.append(BehavioralSignalExposureV1(
                    round_seed=metadata["round_seed"],
                    decision_index=metadata["decision_index"],
                    decision_key=metadata["decision_key"],
                    actor_seat=actor_seat,
                    source_acting_seat=source_seat,
                    source_signal_sha256=signal.sha256(),
                    signal_kind=signal.signal_kind, receiver=receiver,
                    privileged_signal_confirmed=confirmed))
        active.pop(actor_seat, None)
        emitted = tuple(signals_by_index.get(metadata["decision_index"], ()))
        if emitted:
            active[actor_seat] = emitted
    if any(exposure.schema != BEHAVIORAL_EXPOSURE_SCHEMA
           or exposure.round_seed != captured.round_seed
           or not _is_sha256(exposure.decision_key)
           or not _is_sha256(exposure.source_signal_sha256)
           or exposure.actor_seat == exposure.source_acting_seat
           or exposure.receiver != "seat-relative-" + str(
               (exposure.source_acting_seat - exposure.actor_seat) % 4)
           for exposure in exposures):
        raise BeliefBehavioralError("behavioral exposure derivation drift")
    return tuple(exposures)
