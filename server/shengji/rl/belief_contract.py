"""Typed information boundary for BELIEF-V1.

This module is the B0 mechanics layer only.  It does not learn a belief,
sample a world, choose an action, register a policy, or launch an experiment.

The central contract is deliberately split in two:

* :class:`ActorObservationV1` contains public information, the actor's hand,
  the banker's own known burial, and sound deductions from ``Memory``.
* :class:`BeliefTargetsV1` contains the simulator's true remaining ownership
  for the other three seats and the non-banker-hidden burial.

Keeping separate canonical byte strings makes the leakage boundary testable:
changing a hidden allocation inside the same information set must leave the
actor bytes unchanged while changing the target bytes.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..ai.memory import Memory
from ..engine.cards import (RANKS, SUITS, Ordering, card_suit, is_joker,
                            make_deck, total_points)
from ..engine.round import HAND_SIZE, Round, Trick, TrickPlay


ACTOR_OBSERVATION_SCHEMA = "belief-v1-actor-observation-v3"
BELIEF_TARGETS_SCHEMA = "belief-v1-hidden-ownership-targets-v1"
PARTITION_SCHEMA = "belief-v1-information-partition-v1"
DECLARATION_SCHEMA = "final-winning-declaration-v1"
HIDDEN_KITTY_RECEIVER = "hidden-kitty"

_CARD_CODES = frozenset(make_deck())
_SOURCE_ROOT = Path(__file__).resolve().parents[1]


class BeliefContractError(ValueError):
    """An actor/target boundary could not be reconstructed exactly."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


BELIEF_CONTRACT_SOURCE_SHA256S = {
    "belief_contract": _sha256_file(Path(__file__).resolve()),
    "memory": _sha256_file(_SOURCE_ROOT / "ai" / "memory.py"),
    "cards": _sha256_file(_SOURCE_ROOT / "engine" / "cards.py"),
    "combos": _sha256_file(_SOURCE_ROOT / "engine" / "combos.py"),
    "legal": _sha256_file(_SOURCE_ROOT / "engine" / "legal.py"),
    "round": _sha256_file(_SOURCE_ROOT / "engine" / "round.py"),
}


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False) + "\n").encode(
                               "ascii")
    except (TypeError, ValueError) as exc:
        raise BeliefContractError("contract is not canonical JSON") from exc


def _card_counts(cards: Iterable[str], *, label: str) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for card in cards:
        if type(card) is not str or card not in _CARD_CODES:
            raise BeliefContractError(f"{label} contains unknown card {card!r}")
        counts[card] += 1
        if counts[card] > 2:
            raise BeliefContractError(
                f"{label} contains more than two physical copies of {card}")
    return tuple(sorted(counts.items()))


def _counts_dict(counts: tuple[tuple[str, int], ...]) -> dict[str, int]:
    return {card: count for card, count in counts}


@dataclass(frozen=True)
class DeclarationView:
    seat_relative: int
    cards: tuple[str, ...]
    strength: int
    schema: str = DECLARATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "seat_relative": self.seat_relative,
            "cards": list(self.cards),
            "strength": self.strength,
        }


@dataclass(frozen=True)
class CapturedDeclarationEvent:
    """One public declaration accepted by the engine, in event order."""

    seat: int
    cards: tuple[str, ...]
    strength: int


@dataclass(frozen=True)
class CapturedPlayEvent:
    """One public play attempt and the component the engine accepted."""

    seat: int
    attempted_cards: tuple[str, ...]
    actual_cards: tuple[str, ...]


@dataclass(frozen=True)
class PublicTranscriptV1:
    """Complete public event prefix maintained by a capture/runtime driver.

    ``Round`` itself retains only the final declaration and engine-accepted
    cards.  Callers that want a training-eligible actor record must retain the
    overwritten declarations and attempted throws in this separate public
    transcript.  Appends are functional so a captured actor snapshot cannot be
    changed by later play.
    """

    declarations: tuple[CapturedDeclarationEvent, ...] = ()
    plays: tuple[CapturedPlayEvent, ...] = ()

    def with_declaration(self, seat: int, cards: Iterable[str],
                         strength: int) -> "PublicTranscriptV1":
        return PublicTranscriptV1(
            declarations=(*self.declarations, CapturedDeclarationEvent(
                seat=seat, cards=tuple(cards), strength=strength)),
            plays=self.plays,
        )

    def with_play(self, seat: int, attempted_cards: Iterable[str],
                  actual_cards: Iterable[str]) -> "PublicTranscriptV1":
        return PublicTranscriptV1(
            declarations=self.declarations,
            plays=(*self.plays, CapturedPlayEvent(
                seat=seat,
                attempted_cards=tuple(attempted_cards),
                actual_cards=tuple(actual_cards),
            )),
        )


@dataclass(frozen=True)
class PlayView:
    seat_relative: int
    failed_throw: bool
    attempted_cards: tuple[str, ...]
    cards: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat_relative": self.seat_relative,
            "failed_throw": self.failed_throw,
            "attempted_cards": list(self.attempted_cards),
            "cards": list(self.cards),
        }


@dataclass(frozen=True)
class TrickView:
    leader_relative: int
    plays: tuple[PlayView, ...]
    winner_relative: int | None
    points: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "leader_relative": self.leader_relative,
            "plays": [play.to_dict() for play in self.plays],
            "winner_relative": self.winner_relative,
            "points": self.points,
        }


@dataclass(frozen=True)
class DeclarationEligibilityV1:
    """A shown copy constrained to a public set of hidden receivers.

    This is distinct from a hand pin.  In particular, a banker-declarer's
    still-unplayed shown copy may be in the banker hand or the hidden kitty,
    but cannot be in either unrelated opponent hand.
    """

    card: str
    eligible_receivers: tuple[str, ...]
    minimum_copies: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "card": self.card,
            "eligible_receivers": list(self.eligible_receivers),
            "minimum_copies": self.minimum_copies,
        }


@dataclass(frozen=True)
class DeductionView:
    played: tuple[tuple[str, int], ...]
    played_by_relative: tuple[tuple[tuple[str, int], ...], ...]
    unseen: tuple[tuple[str, int], ...]
    voids_by_relative: tuple[tuple[str, ...], ...]
    pair_caps_by_relative: tuple[tuple[tuple[str, int], ...], ...]
    run_caps_by_relative: tuple[tuple[tuple[str, int], ...], ...]
    declaration_pins: tuple[tuple[str, int, int], ...]
    declaration_eligibility: tuple[DeclarationEligibilityV1, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "played": _counts_dict(self.played),
            "played_by_relative": [
                _counts_dict(counts) for counts in self.played_by_relative
            ],
            "unseen": _counts_dict(self.unseen),
            "voids_by_relative": [list(voids)
                                  for voids in self.voids_by_relative],
            "pair_caps_by_relative": [dict(caps)
                                      for caps in self.pair_caps_by_relative],
            "run_caps_by_relative": [dict(caps)
                                     for caps in self.run_caps_by_relative],
            "declaration_pins": [
                {"card": card, "seat_relative": seat, "copies": copies}
                for card, seat, copies in self.declaration_pins
            ],
            "declaration_eligibility": [
                constraint.to_dict()
                for constraint in self.declaration_eligibility
            ],
        }


@dataclass(frozen=True)
class ActorObservationV1:
    trump_rank: str
    trump_suit: str | None
    trump_is_nt: bool
    banker_relative: int
    actor_is_attacker: bool
    attacker_points: int
    hand_sizes_relative: tuple[int, int, int, int]
    actor_hand: tuple[tuple[str, int], ...]
    actor_known_burial: tuple[tuple[str, int], ...]
    hidden_burial_size: int
    declaration: DeclarationView | None
    declaration_history: tuple[DeclarationView, ...]
    declaration_history_complete: bool
    attempted_play_history_complete: bool
    completed_tricks: tuple[TrickView, ...]
    current_trick: TrickView
    deductions: DeductionView
    schema: str = ACTOR_OBSERVATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "perspective": "acting-seat-relative-zero",
            "phase": "play",
            "trump_rank": self.trump_rank,
            "trump_suit": self.trump_suit,
            "trump_is_nt": self.trump_is_nt,
            "banker_relative": self.banker_relative,
            "actor_is_attacker": self.actor_is_attacker,
            "attacker_points": self.attacker_points,
            "hand_sizes_relative": list(self.hand_sizes_relative),
            "actor_hand": _counts_dict(self.actor_hand),
            "actor_known_burial": _counts_dict(self.actor_known_burial),
            "hidden_burial_size": self.hidden_burial_size,
            "declaration": (
                None if self.declaration is None else self.declaration.to_dict()
            ),
            "declaration_history": [
                event.to_dict() for event in self.declaration_history
            ],
            # Round currently retains only the winning declaration.  The flag
            # makes that limitation explicit instead of implying a chronology
            # that the engine cannot reconstruct.
            "declaration_history_complete": self.declaration_history_complete,
            # Round stores the engine-accepted component of a failed throw,
            # not the original attempted throw.  A later replay-capture
            # contract must supply attempts; B0 refuses to imply they exist.
            "attempted_play_history_complete": (
                self.attempted_play_history_complete
            ),
            "completed_tricks": [trick.to_dict()
                                 for trick in self.completed_tricks],
            "current_trick": self.current_trick.to_dict(),
            "deductions": self.deductions.to_dict(),
            "source_sha256s": dict(BELIEF_CONTRACT_SOURCE_SHA256S),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class HiddenReceiverView:
    seat_relative: int
    cards: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat_relative": self.seat_relative,
            "cards": _counts_dict(self.cards),
            "card_count": sum(count for _, count in self.cards),
        }


@dataclass(frozen=True)
class BeliefTargetsV1:
    other_hands: tuple[HiddenReceiverView, ...]
    hidden_burial: tuple[tuple[str, int], ...]
    schema: str = BELIEF_TARGETS_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "perspective": "acting-seat-relative-zero",
            "other_hands": [hand.to_dict() for hand in self.other_hands],
            "hidden_burial": _counts_dict(self.hidden_burial),
            "hidden_burial_count": sum(count for _, count in self.hidden_burial),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class BeliefInformationPartitionV1:
    actor: ActorObservationV1
    targets: BeliefTargetsV1
    schema: str = PARTITION_SCHEMA

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "actor_schema": self.actor.schema,
            "actor_sha256": self.actor.sha256(),
            "targets_schema": self.targets.schema,
            "targets_sha256": self.targets.sha256(),
            "runtime_consumes_targets": False,
        }

    def canonical_bytes(self) -> bytes:
        """Bind the two separate payload hashes without co-locating payloads."""
        return canonical_json_bytes(self.manifest())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _strict_decision_round(rnd: Round, seat: int) -> None:
    if type(rnd) is not Round:
        raise BeliefContractError("belief contract requires an exact Round")
    if type(seat) is not int or seat not in range(4):
        raise BeliefContractError("acting seat must be an integer in range(4)")
    if rnd.phase != "play" or rnd.turn != seat \
            or type(rnd.ordering) is not Ordering \
            or type(rnd.trick) is not Trick:
        raise BeliefContractError(
            "actor observation requires the acting seat's play decision")
    if type(rnd.hands) is not list or len(rnd.hands) != 4 \
            or any(type(hand) is not list for hand in rnd.hands):
        raise BeliefContractError("round hands must be four exact lists")
    if type(rnd.banker) is not int or rnd.banker not in range(4):
        raise BeliefContractError("round banker is invalid")
    if type(rnd.buried) is not list or len(rnd.buried) != 8:
        raise BeliefContractError("play state must retain the exact burial")
    if type(rnd.attacker_points) is not int or rnd.attacker_points < 0:
        raise BeliefContractError("attacker points are invalid")
    if type(rnd.trump_rank) is not str or rnd.trump_rank not in RANKS \
            or type(rnd.trump_is_nt) is not bool:
        raise BeliefContractError("trump identity is invalid")
    if (rnd.trump_is_nt and rnd.trump_suit is not None) \
            or (not rnd.trump_is_nt and rnd.trump_suit not in SUITS):
        raise BeliefContractError("trump suit and no-trump flag disagree")
    if type(rnd.history) is not list:
        raise BeliefContractError("round history must be an exact list")


def _play_view(play: TrickPlay, attempted_cards: tuple[str, ...],
               seat: int, rnd: Round) -> PlayView:
    if type(play) is not TrickPlay or type(play.seat) is not int \
            or play.seat not in range(4) or type(play.cards) is not list \
            or not play.cards:
        raise BeliefContractError("public play is malformed")
    _card_counts(play.cards, label="public play")
    _card_counts(attempted_cards, label="public attempted play")
    failed_throw = Counter(attempted_cards) != Counter(play.cards)
    # A failed throw's forced component and failure signal are public, but the
    # cards returned to another seat's hand are not broadcast.  The acting
    # seat may retain its own attempted action; every other perspective sees
    # only the engine-accepted cards plus the explicit public failure bit.
    actor_visible_attempt = (
        attempted_cards if play.seat == seat else tuple(play.cards))
    return PlayView(
        seat_relative=(play.seat - seat) % 4,
        failed_throw=failed_throw,
        attempted_cards=tuple(sorted(actor_visible_attempt,
                                    key=rnd.ordering.sort_key)),
        cards=tuple(sorted(play.cards, key=rnd.ordering.sort_key)),
    )


def _trick_view(trick: Trick, attempts: tuple[tuple[str, ...], ...],
                seat: int, rnd: Round, *, complete: bool) -> TrickView:
    if type(trick) is not Trick or type(trick.leader) is not int \
            or trick.leader not in range(4) or type(trick.plays) is not list:
        raise BeliefContractError("public trick is malformed")
    if (complete and len(trick.plays) != 4) \
            or (not complete and not 0 <= len(trick.plays) <= 3):
        raise BeliefContractError("public trick play count is invalid")
    expected = [(trick.leader + index) % 4
                for index in range(len(trick.plays))]
    if [play.seat for play in trick.plays] != expected:
        raise BeliefContractError("public trick seat order is invalid")
    if len(attempts) != len(trick.plays):
        raise BeliefContractError("attempted-play transcript length drift")
    plays = tuple(
        _play_view(play, attempted, seat, rnd)
        for play, attempted in zip(trick.plays, attempts, strict=True)
    )
    recomputed_points = total_points(
        card for play in trick.plays for card in play.cards)
    if complete:
        if type(trick.winner) is not int or trick.winner not in range(4) \
                or type(trick.points) is not int \
                or trick.points != recomputed_points:
            raise BeliefContractError("completed trick resolution is invalid")
        winner = (trick.winner - seat) % 4
        points = trick.points
    else:
        if trick.winner is not None or trick.points != 0:
            raise BeliefContractError("open trick carries terminal fields")
        winner = None
        points = recomputed_points
    return TrickView(
        leader_relative=(trick.leader - seat) % 4,
        plays=plays,
        winner_relative=winner,
        points=points,
    )


def _declaration_view(rnd: Round, seat: int) -> DeclarationView | None:
    if rnd.declaration is None:
        return None
    declaration = rnd.declaration
    if type(declaration) is not dict or set(declaration) != {
            "seat", "cards", "strength"}:
        raise BeliefContractError("declaration schema is invalid")
    owner = declaration["seat"]
    cards = declaration["cards"]
    strength = declaration["strength"]
    if type(owner) is not int or owner not in range(4) \
            or type(cards) is not list or not cards \
            or type(strength) is not int or strength not in range(1, 5):
        raise BeliefContractError("declaration values are invalid")
    _card_counts(cards, label="declaration")
    expected_strength = rnd._declaration_strength(cards)
    if expected_strength != strength:
        raise BeliefContractError("declaration strength is invalid")
    declared_nt = is_joker(cards[0])
    if declared_nt != rnd.trump_is_nt \
            or (not declared_nt and card_suit(cards[0]) != rnd.trump_suit):
        raise BeliefContractError("declaration and trump identity disagree")
    return DeclarationView(
        seat_relative=(owner - seat) % 4,
        cards=tuple(sorted(cards, key=rnd.ordering.sort_key)),
        strength=strength,
    )


def _transcript_views(
        rnd: Round, seat: int, transcript: PublicTranscriptV1 | None) -> tuple[
            tuple[DeclarationView, ...], tuple[tuple[str, ...], ...], bool,
            bool]:
    actual_entries = [
        (position, play)
        for trick in [*rnd.history, rnd.trick]
        if trick is not None
        for position, play in enumerate(trick.plays)
    ]
    final = _declaration_view(rnd, seat)
    if transcript is None:
        return (
            tuple(() if final is None else (final,)),
            tuple(tuple(play.cards) for _, play in actual_entries),
            False,
            False,
        )
    if type(transcript) is not PublicTranscriptV1:
        raise BeliefContractError("public transcript must be exact V1")
    if type(transcript.declarations) is not tuple \
            or type(transcript.plays) is not tuple:
        raise BeliefContractError("public transcript collections must be tuples")

    declaration_views: list[DeclarationView] = []
    previous_strength = 0
    for event in transcript.declarations:
        if type(event) is not CapturedDeclarationEvent \
                or type(event.seat) is not int or event.seat not in range(4) \
                or type(event.cards) is not tuple or not event.cards \
                or type(event.strength) is not int:
            raise BeliefContractError("captured declaration event is malformed")
        _card_counts(event.cards, label="captured declaration")
        expected_strength = rnd._declaration_strength(list(event.cards))
        if expected_strength != event.strength \
                or event.strength <= previous_strength:
            raise BeliefContractError(
                "captured declaration strength/order is invalid")
        previous_strength = event.strength
        declaration_views.append(DeclarationView(
            seat_relative=(event.seat - seat) % 4,
            cards=tuple(sorted(event.cards, key=rnd.ordering.sort_key)),
            strength=event.strength,
        ))
    if final is None:
        if declaration_views:
            raise BeliefContractError(
                "transcript has declarations but Round has no winner")
    elif not declaration_views or declaration_views[-1] != final:
        raise BeliefContractError(
            "transcript final declaration disagrees with Round")

    if len(transcript.plays) != len(actual_entries):
        raise BeliefContractError(
            "captured play prefix disagrees with public history length")
    attempts: list[tuple[str, ...]] = []
    for event, (position, actual) in zip(
            transcript.plays, actual_entries, strict=True):
        if type(event) is not CapturedPlayEvent \
                or type(event.seat) is not int or event.seat not in range(4) \
                or type(event.attempted_cards) is not tuple \
                or not event.attempted_cards \
                or type(event.actual_cards) is not tuple \
                or not event.actual_cards:
            raise BeliefContractError("captured play event is malformed")
        _card_counts(event.attempted_cards, label="captured attempted play")
        _card_counts(event.actual_cards, label="captured actual play")
        if event.seat != actual.seat \
                or Counter(event.actual_cards) != Counter(actual.cards):
            raise BeliefContractError(
                "captured actual play disagrees with Round")
        attempted = Counter(event.attempted_cards)
        accepted = Counter(event.actual_cards)
        if accepted - attempted:
            raise BeliefContractError(
                "engine-accepted cards are absent from attempted play")
        if position != 0 and attempted != accepted:
            raise BeliefContractError(
                "only a lead throw may differ from its attempted action")
        attempts.append(event.attempted_cards)
    return tuple(declaration_views), tuple(attempts), True, True


def _deductions(rnd: Round, seat: int) -> DeductionView:
    memory = Memory(rnd, seat, own_kitty=True)
    played_by = tuple(
        _card_counts(memory.played_by[(seat + relative) % 4].elements(),
                     label="public played-by")
        for relative in range(4)
    )
    voids = tuple(
        tuple(sorted(memory.voids[(seat + relative) % 4]))
        for relative in range(4)
    )
    pair_caps = tuple(
        tuple(sorted(memory.pair_cap[(seat + relative) % 4].items()))
        for relative in range(4)
    )
    run_caps = tuple(
        tuple(sorted(memory.run_cap[(seat + relative) % 4].items()))
        for relative in range(4)
    )
    declaration = rnd.declaration
    banker_declaration = bool(
        declaration is not None
        and declaration.get("seat") == rnd.banker
        and rnd.banker != seat
    )
    pins = tuple(sorted(
        (card, (owner - seat) % 4, copies)
        for card, (owner, copies) in memory.known.items()
        if not banker_declaration or owner != rnd.banker
    ))
    eligibility: tuple[DeclarationEligibilityV1, ...] = ()
    if banker_declaration:
        assert declaration is not None
        constraints = []
        for card, shown_copies in sorted(Counter(declaration["cards"]).items()):
            remaining = shown_copies - memory.played_by[rnd.banker][card]
            if remaining > 0:
                constraints.append(DeclarationEligibilityV1(
                    card=card,
                    eligible_receivers=(
                        f"seat-relative-{(rnd.banker - seat) % 4}",
                        HIDDEN_KITTY_RECEIVER,
                    ),
                    minimum_copies=remaining,
                ))
        eligibility = tuple(constraints)
    return DeductionView(
        played=_card_counts(memory.played.elements(), label="public played"),
        played_by_relative=played_by,
        unseen=_card_counts(memory.unseen.elements(), label="actor unseen"),
        voids_by_relative=voids,
        pair_caps_by_relative=pair_caps,
        run_caps_by_relative=run_caps,
        declaration_pins=pins,
        declaration_eligibility=eligibility,
    )


def _validate_physical_population(rnd: Round) -> None:
    population: Counter[str] = Counter()
    for index, hand in enumerate(rnd.hands):
        _card_counts(hand, label=f"hand {index}")
        population.update(hand)
    _card_counts(rnd.buried, label="burial")
    population.update(rnd.buried)
    for trick in rnd.history:
        for play in trick.plays:
            population.update(play.cards)
    if rnd.trick is not None:
        for play in rnd.trick.plays:
            population.update(play.cards)
    expected = Counter(make_deck())
    if population != expected:
        raise BeliefContractError("round physical card population is invalid")


def build_actor_observation(
        rnd: Round, seat: int,
        transcript: PublicTranscriptV1 | None = None) -> ActorObservationV1:
    """Build canonical runtime input without reading hidden allocations."""
    _strict_decision_round(rnd, seat)
    declaration_history, attempts, declaration_complete, attempt_complete = (
        _transcript_views(rnd, seat, transcript)
    )
    completed_list: list[TrickView] = []
    offset = 0
    for trick in rnd.history:
        completed_list.append(_trick_view(
            trick, attempts[offset:offset + 4], seat, rnd, complete=True))
        offset += 4
    completed = tuple(completed_list)
    current = _trick_view(
        rnd.trick, attempts[offset:offset + len(rnd.trick.plays)], seat, rnd,
        complete=False)
    if (rnd.trick.leader + len(rnd.trick.plays)) % 4 != seat:
        raise BeliefContractError("current trick does not route to acting seat")
    actor_is_banker = seat == rnd.banker
    deductions = _deductions(rnd, seat)
    hand_sizes = tuple(
        HAND_SIZE - sum(count for _, count in played)
        for played in deductions.played_by_relative
    )
    if any(size < 0 for size in hand_sizes) or hand_sizes[0] != len(
            rnd.hands[seat]):
        raise BeliefContractError("public hand-size reconstruction is invalid")
    return ActorObservationV1(
        trump_rank=rnd.trump_rank,
        trump_suit=rnd.trump_suit,
        trump_is_nt=bool(rnd.trump_is_nt),
        banker_relative=(rnd.banker - seat) % 4,
        actor_is_attacker=bool(rnd.is_attacker(seat)),
        attacker_points=rnd.attacker_points,
        hand_sizes_relative=hand_sizes,
        actor_hand=_card_counts(rnd.hands[seat], label="actor hand"),
        actor_known_burial=(
            _card_counts(rnd.buried, label="actor-known burial")
            if actor_is_banker else tuple()
        ),
        hidden_burial_size=0 if actor_is_banker else len(rnd.buried),
        declaration=_declaration_view(rnd, seat),
        declaration_history=declaration_history,
        declaration_history_complete=declaration_complete,
        attempted_play_history_complete=attempt_complete,
        completed_tricks=completed,
        current_trick=current,
        deductions=deductions,
    )


def build_belief_targets(rnd: Round, seat: int) -> BeliefTargetsV1:
    """Build simulator-only ownership labels, never runtime model input."""
    _strict_decision_round(rnd, seat)
    _validate_physical_population(rnd)
    other_hands = tuple(
        HiddenReceiverView(
            seat_relative=relative,
            cards=_card_counts(rnd.hands[(seat + relative) % 4],
                               label=f"hidden relative hand {relative}"),
        )
        for relative in range(1, 4)
    )
    return BeliefTargetsV1(
        other_hands=other_hands,
        hidden_burial=(
            tuple() if seat == rnd.banker
            else _card_counts(rnd.buried, label="hidden burial")
        ),
    )


def build_information_partition(
        rnd: Round, seat: int,
        transcript: PublicTranscriptV1 | None = None
        ) -> BeliefInformationPartitionV1:
    """Build separately hashed actor input and privileged training label."""
    return BeliefInformationPartitionV1(
        actor=build_actor_observation(rnd, seat, transcript),
        targets=build_belief_targets(rnd, seat),
    )
