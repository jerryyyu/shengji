"""Bounded public-information candidate sourcing for lead throws.

The production MC ballot already offers pairs, tractors, top/low singles and
one conservative near-boss throw family.  It cannot, however, offer either of
these common ``shuai pai`` shapes:

* a *partial* collection of boss/near-boss components while weaker cards of
  the same suit are retained; or
* the complete remaining holding of a suit as an evacuation throw.

This module sources those shapes without changing the production ballot or
deciding whether a throw is good.  In particular, ``ruff_risk`` is recorded
but is deliberately not a source veto: a search/evaluator must price that
risk.  The source reads only the acting hand and :class:`Memory`, so its output
is legal at the player's information set.  It is intentionally independent of
trick number: whenever any same-effective-suit holding decomposes into two or
more components, at least one throw is sourced on an early, middle or late
lead.  A trump-only opportunity receives a bounded whole-trump fallback.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..engine.cards import TRUMP
from ..engine.combos import decompose
from ..engine.legal import suit_cards
from ..engine.round import Round
from .heuristic import PLAIN_SUITS
from .memory import Memory


SCHEMA = "structured-lead-throw-ballot-v2"
BOSS_NEAR_BUNDLE = "boss_or_near_boss_component_bundle"
WHOLE_SUIT_EVACUATION = "whole_plain_suit_evacuation"
WHOLE_TRUMP_EVACUATION = "whole_trump_holding_fallback"
MAX_CANDIDATES = 2 * len(PLAIN_SUITS)
ALL_EFFECTIVE_SUITS = tuple(PLAIN_SUITS) + (TRUMP,)


@dataclass(frozen=True)
class ThrowCandidate:
    cards: tuple[str, ...]
    sources: tuple[str, ...]
    effective_suit: str
    component_count: int
    ruff_risk: bool

    def record(self) -> dict:
        return {
            "cards": list(self.cards),
            "sources": list(self.sources),
            "effective_suit": self.effective_suit,
            "component_count": self.component_count,
            "ruff_risk": self.ruff_risk,
        }


@dataclass(frozen=True)
class StructuredThrowBallot:
    candidates: tuple[ThrowCandidate, ...]
    generated_unique: int
    eligible_suits: tuple[str, ...] = ()
    max_candidates: int = MAX_CANDIDATES
    schema: str = SCHEMA

    @property
    def coverage_satisfied(self) -> bool:
        """Whether an available lead throw is represented by the source."""
        return not self.eligible_suits or bool(self.candidates)

    def record(self) -> dict:
        return {
            "schema": self.schema,
            "max_candidates": self.max_candidates,
            "generated_unique": self.generated_unique,
            "eligible_suits": list(self.eligible_suits),
            "coverage_satisfied": self.coverage_satisfied,
            "candidates": [candidate.record() for candidate in self.candidates],
        }


def union_with_live_ballot(
    live_candidates: list[list[str]],
    structured: StructuredThrowBallot,
) -> list[list[str]]:
    """Append bounded throw proposals without changing the incumbent ballot.

    This is the experimental S6 union seam, not a production-policy switch.
    Candidate zero and every other live action retain their exact order and
    card order; structured actions are canonical and append-only.  A later
    evaluator may spend equal work on this wider ballot, but must not truncate
    the appended throw back out after claiming S6 coverage.
    """
    if not live_candidates:
        raise ValueError("S6 union requires a live incumbent ballot")
    if not structured.coverage_satisfied:
        raise ValueError("S6 structured source did not cover an eligible lead")
    merged = [list(action) for action in live_candidates]
    seen = {tuple(sorted(action)) for action in live_candidates}
    for candidate in structured.candidates:
        if candidate.cards in seen:
            continue
        merged.append(list(candidate.cards))
        seen.add(candidate.cards)
    if len(merged) > len(live_candidates) + structured.max_candidates:
        raise AssertionError("S6 union exceeded its bounded addition cap")
    return merged


def _component_top(component, ordering) -> str:
    return max(component.cards, key=ordering.level)


def _pair_near_boss(code: str, suit: str, memory: Memory) -> bool:
    """Match the existing, intentionally narrow near-boss pair contract.

    A pair/tractor component is near-boss when exactly one higher *rank* can
    still form a pair.  Higher singletons cannot beat a paired component.
    """
    ordering = memory.o
    level = ordering.level(code)
    threats = sum(
        1 for unseen, copies in memory.unseen.items()
        if (ordering.eff_suit(unseen) == suit
            and ordering.level(unseen) > level and copies >= 2)
    )
    return threats == 1


def _boss_or_near_components(components, suit: str,
                             memory: Memory) -> list:
    ordering = memory.o
    selected = []
    for component in components:
        top = _component_top(component, ordering)
        if component.pair_len:
            if memory.pair_is_boss(top) or _pair_near_boss(top, suit, memory):
                selected.append(component)
        elif memory.is_boss(top):
            selected.append(component)
    return selected


def structured_throw_ballot(
    rnd: Round,
    seat: int,
    *,
    own_kitty: bool = True,
) -> StructuredThrowBallot:
    """Return at most two deterministic throw proposals per plain suit.

    This is a lead-only source.  A proposal must contain at least two
    decomposition components, so ordinary singles, pairs and tractors remain
    exclusively owned by the production ballot.  Candidate card multisets are
    canonical and duplicate source reasons are merged.
    """
    if rnd.ordering is None or rnd.trick is None:
        raise ValueError("structured throw sourcing requires play ordering")
    if rnd.trick.plays:
        return StructuredThrowBallot(candidates=(), generated_unique=0)
    if rnd.turn != seat or not 0 <= seat < len(rnd.hands):
        raise ValueError("structured throw sourcing requires the acting seat")

    ordering = rnd.ordering
    memory = Memory(rnd, seat, own_kitty=own_kitty)
    opponents = [other for other in range(4) if other % 2 != seat % 2]
    reasons: dict[tuple[str, ...], set[str]] = {}
    metadata: dict[tuple[str, ...], tuple[str, int, bool]] = {}
    holdings = {
        suit: sorted(suit_cards(rnd.hands[seat], suit, ordering))
        for suit in ALL_EFFECTIVE_SUITS
    }
    decompositions = {
        suit: decompose(cards, ordering).components
        for suit, cards in holdings.items() if cards
    }
    eligible_suits = tuple(
        suit for suit in ALL_EFFECTIVE_SUITS
        if len(decompositions.get(suit, ())) >= 2
    )

    def add(cards, source: str, suit: str) -> None:
        key = tuple(sorted(cards))
        if not key:
            return
        components = decompose(list(key), ordering).components
        if len(components) < 2:
            return
        reasons.setdefault(key, set()).add(source)
        current = (suit, len(components), memory.ruff_risk(suit, opponents))
        if key in metadata and metadata[key] != current:
            raise AssertionError("throw candidate metadata drift")
        metadata[key] = current

    # PLAIN_SUITS is a stable registered order.  Sort each holding before
    # decomposition so incidental deal/hand order cannot change the ballot.
    for suit in PLAIN_SUITS:
        cards = holdings[suit]
        if not cards:
            continue
        components = decompositions[suit]

        selected = _boss_or_near_components(components, suit, memory)
        if len(selected) >= 2:
            add(
                [card for component in selected for card in component.cards],
                BOSS_NEAR_BUNDLE,
                suit,
            )

        # "Whole remaining suit" is exact here: every card of this effective
        # plain suit currently in the acting hand.  It is admitted only when
        # it is genuinely a multi-component throw.  This yields no more than
        # one evacuation proposal per suit, with no combinatorial subsets.
        if len(components) >= 2:
            add(cards, WHOLE_SUIT_EVACUATION, suit)

    # A hand can reach the middle or endgame with throw structure only in its
    # effective-trump holding.  The original plain-suit-only source then
    # returned an empty ballot despite a legal shuai attempt.  Preserve the
    # eight-candidate cap: add this fallback only when no plain-suit proposal
    # already satisfies the phase-wide "at least one throw" contract.
    if not reasons and TRUMP in eligible_suits:
        add(holdings[TRUMP], WHOLE_TRUMP_EVACUATION, TRUMP)

    if len(reasons) > MAX_CANDIDATES:
        raise AssertionError("structured throw source exceeded its finite cap")
    if eligible_suits and not reasons:
        raise AssertionError("available lead throw was not represented")
    candidates = tuple(
        ThrowCandidate(
            cards=key,
            sources=tuple(sorted(reasons[key])),
            effective_suit=metadata[key][0],
            component_count=metadata[key][1],
            ruff_risk=metadata[key][2],
        )
        for key in reasons
    )
    return StructuredThrowBallot(
        candidates=candidates,
        generated_unique=len(reasons),
        eligible_suits=eligible_suits,
    )
