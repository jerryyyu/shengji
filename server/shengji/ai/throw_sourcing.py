"""Bounded public-information candidate sourcing for lead throws.

The production MC ballot already offers pairs, tractors, top/low singles and
one conservative near-boss throw family.  It cannot, however, offer either of
these common ``shuai pai`` shapes:

* a *partial* collection of boss/near-boss components while weaker cards of
  the same suit are retained; or
* the complete remaining holding of a plain suit as an evacuation throw.

This module sources those shapes without changing the production ballot or
deciding whether a throw is good.  In particular, ``ruff_risk`` is recorded
but is deliberately not a source veto: a search/evaluator must price that
risk.  The source reads only the acting hand and :class:`Memory`, so its output
is legal at the player's information set.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..engine.combos import decompose
from ..engine.legal import suit_cards
from ..engine.round import Round
from .heuristic import PLAIN_SUITS
from .memory import Memory


SCHEMA = "structured-lead-throw-ballot-v1"
BOSS_NEAR_BUNDLE = "boss_or_near_boss_component_bundle"
WHOLE_SUIT_EVACUATION = "whole_plain_suit_evacuation"
MAX_CANDIDATES = 2 * len(PLAIN_SUITS)


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
    max_candidates: int = MAX_CANDIDATES
    schema: str = SCHEMA

    def record(self) -> dict:
        return {
            "schema": self.schema,
            "max_candidates": self.max_candidates,
            "generated_unique": self.generated_unique,
            "candidates": [candidate.record() for candidate in self.candidates],
        }


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
        cards = sorted(suit_cards(rnd.hands[seat], suit, ordering))
        if not cards:
            continue
        components = decompose(cards, ordering).components

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

    if len(reasons) > MAX_CANDIDATES:
        raise AssertionError("structured throw source exceeded its finite cap")
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
    )
