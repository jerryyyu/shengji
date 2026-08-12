"""Exploration-only source for joint banker-bury and first-lead choices.

The existing structured-bury lane already offers the incumbent plus every
feasible single-suit void.  Its continuation scorer, however, immediately
hands the post-bury round to a simple heuristic policy.  That can undervalue
the very structures a strategic bury preserves: promoted low pairs, tractors,
and legal ``shuai pai`` bundles.

This module exposes those structures as one actor-visible combo ballot.  It
does not score, register, or deploy a policy.  A later high-N evaluator can
price every ``(bury, first lead)`` attempt on common determinized worlds, then
compare the selected combo with the protected incumbent.  Lead attempts are
sourced without opponents' hidden hands; whether a throw succeeds is left to
the engine inside each sampled world.
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from ..engine.cards import SUITS, TRUMP, points
from ..engine.combos import decompose
from ..engine.legal import uniform_suit
from ..engine.round import HAND_SIZE, Round
from .bury import (DEFAULT_MAX_CANDIDATES, BuryCandidate,
                   structured_bury_ballot)
from .throw_sourcing import (MAX_CANDIDATES as MAX_STRUCTURED_THROWS,
                             StructuredThrowBallot,
                             structured_throw_ballot)


SCHEMA = "bury-first-lead-combo-ballot-v1"
DEFAULT_MAX_LIVE_LEADS = 14
MAX_PAIR_LEADS = HAND_SIZE // 2

LeadBallotFn = Callable[[Round, int], list[list[str]]]


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


@dataclass(frozen=True)
class FirstLeadCandidate:
    cards: tuple[str, ...]
    sources: tuple[str, ...]
    component_count: int
    pair_lead: bool
    structured_throw: bool

    def record(self) -> dict:
        return {
            "cards": list(self.cards),
            "sources": list(self.sources),
            "component_count": self.component_count,
            "pair_lead": self.pair_lead,
            "structured_throw": self.structured_throw,
        }


@dataclass(frozen=True)
class BuryLeadGroup:
    bury_index: int
    bury: BuryCandidate
    retained_shape: dict[str, object]
    live_lead_count: int
    guaranteed_pair_lead_count: int
    structured_throw_ballot: StructuredThrowBallot
    leads: tuple[FirstLeadCandidate, ...]

    def record(self) -> dict:
        return {
            "bury_index": self.bury_index,
            "bury": self.bury.record(),
            "retained_shape": self.retained_shape,
            "live_lead_count": self.live_lead_count,
            "guaranteed_pair_lead_count": self.guaranteed_pair_lead_count,
            "structured_throw_ballot": self.structured_throw_ballot.record(),
            "leads": [lead.record() for lead in self.leads],
        }


@dataclass(frozen=True)
class BuryLeadComboBallot:
    groups: tuple[BuryLeadGroup, ...]
    feasible_single_suit_voids: tuple[str, ...]
    generated_buries: int
    combo_count: int
    max_buries: int
    max_live_leads_per_bury: int
    max_pair_leads_per_bury: int = MAX_PAIR_LEADS
    max_structured_throws_per_bury: int = MAX_STRUCTURED_THROWS
    schema: str = SCHEMA

    @property
    def max_combos(self) -> int:
        return self.max_buries * (
            self.max_live_leads_per_bury
            + self.max_pair_leads_per_bury
            + self.max_structured_throws_per_bury)

    def record(self) -> dict:
        first = self.groups[0]
        return {
            "schema": self.schema,
            "max_buries": self.max_buries,
            "max_live_leads_per_bury": self.max_live_leads_per_bury,
            "max_pair_leads_per_bury": self.max_pair_leads_per_bury,
            "max_structured_throws_per_bury":
                self.max_structured_throws_per_bury,
            "max_combos": self.max_combos,
            "generated_buries": self.generated_buries,
            "combo_count": self.combo_count,
            "feasible_single_suit_voids":
                list(self.feasible_single_suit_voids),
            "candidate_zero": {
                "bury_cards": list(first.bury.cards),
                "lead_cards": list(first.leads[0].cards),
            },
            "groups": [group.record() for group in self.groups],
            "strength_claim": False,
            "production_policy_registered": False,
        }


def _actor_view_after_bury(rnd: Round, seat: int,
                           bury_cards: tuple[str, ...]) -> Round:
    """Return a source-only view that makes hidden-hand access impossible."""
    view = copy.deepcopy(rnd)
    for other in range(len(view.hands)):
        if other != seat:
            view.hands[other] = []
    # Candidate generation has no authority to inspect the undealt/hidden
    # representation either.  The banker's own kitty remains available via
    # ``buried`` after the engine applies this candidate.
    view.deck = []
    view.bury(seat, list(bury_cards))
    view._actor_visible_candidate_source = True
    return view


def _retained_shape(view: Round, seat: int,
                    structured: StructuredThrowBallot) -> dict[str, object]:
    ordering = view.ordering
    assert ordering is not None
    hand = list(view.hands[seat])
    counts = Counter(hand)
    effective_suits = tuple(SUITS) + (TRUMP,)
    by_suit = {
        suit: sorted(
            card for card in hand if ordering.eff_suit(card) == suit)
        for suit in effective_suits
    }
    max_runs = {
        suit: (decompose(cards, ordering).max_pair_run() if cards else 0)
        for suit, cards in by_suit.items()
    }
    plain_suits = tuple(
        suit for suit in SUITS if suit != ordering.trump_suit)
    return {
        "cards": len(hand),
        "trump_count": len(by_suit[TRUMP]),
        "retained_point_total": sum(points(card) for card in hand),
        "pair_units": sum(copies // 2 for copies in counts.values()),
        "pair_codes": sorted(
            card for card, copies in counts.items() if copies >= 2),
        "max_pair_run": max(max_runs.values(), default=0),
        "max_pair_run_by_suit": max_runs,
        "tractor_suits": sorted(
            suit for suit, run in max_runs.items() if run >= 2),
        "plain_voids": sorted(
            suit for suit in plain_suits if not by_suit[suit]),
        "structured_throw_count": len(structured.candidates),
        "structured_throw_eligible_suits": list(structured.eligible_suits),
    }


def build_bury_lead_combo_ballot(
    rnd: Round,
    seat: int,
    incumbent_bury,
    *,
    live_lead_ballot: LeadBallotFn,
    max_buries: int = DEFAULT_MAX_CANDIDATES,
    max_live_leads: int = DEFAULT_MAX_LIVE_LEADS,
) -> BuryLeadComboBallot:
    """Build the bounded actor-visible ``bury x first-lead`` source.

    Candidate zero is the literal incumbent bury paired with candidate zero of
    the registered live lead ballot.  Every distinct pair in the retained hand
    is then guaranteed a lead slot, even if the live cap omitted a low pair,
    and every S6 structured throw is appended or source-merged.  No candidate
    is selected here.
    """
    if rnd.phase != "bury" or rnd.banker != seat or rnd.ordering is None:
        raise ValueError("bury/lead combo sourcing requires the acting banker")
    if max_buries < 1 or max_live_leads < 1:
        raise ValueError("combo source caps must be positive")

    bury_ballot = structured_bury_ballot(
        rnd.hands[seat], rnd.ordering, incumbent_bury,
        max_candidates=max_buries)
    suit_counts = Counter(
        rnd.ordering.eff_suit(card) for card in rnd.hands[seat])
    feasible_voids = tuple(
        suit for suit in SUITS if 0 < suit_counts[suit] <= 8)
    represented_voids = {
        suit for candidate in bury_ballot.candidates
        for suit in candidate.voids_created
    }
    if not set(feasible_voids).issubset(represented_voids):
        missing = sorted(set(feasible_voids) - represented_voids)
        raise AssertionError(
            f"structured bury ballot omitted feasible voids {missing}")

    groups = []
    combo_count = 0
    for bury_index, bury in enumerate(bury_ballot.candidates):
        view = _actor_view_after_bury(rnd, seat, bury.cards)
        live = [list(cards) for cards in live_lead_ballot(view, seat)]
        if not live:
            raise ValueError("live first-lead ballot must preserve candidate zero")
        if len(live) > max_live_leads:
            raise ValueError(
                f"live first-lead ballot exceeded cap {max_live_leads}")
        structured = structured_throw_ballot(view, seat, own_kitty=True)

        reasons: dict[tuple[str, ...], set[str]] = {}

        def add(cards, source: str) -> None:
            key = action_key(cards)
            if not key or Counter(key) - Counter(view.hands[seat]):
                raise AssertionError(f"illegal combo lead from {source}")
            if uniform_suit(list(key), view.ordering) is None:
                raise AssertionError(f"mixed-suit combo lead from {source}")
            reasons.setdefault(key, set()).add(source)

        for lead_index, cards in enumerate(live):
            add(cards, "live_ballot_candidate_zero" if lead_index == 0
                else "live_ballot")

        retained = Counter(view.hands[seat])
        pair_codes = sorted(
            (card for card, copies in retained.items() if copies >= 2),
            key=lambda card: (-view.ordering.level(card), card))
        if len(pair_codes) > MAX_PAIR_LEADS:
            raise AssertionError("retained hand exceeded finite pair-lead cap")
        for card in pair_codes:
            add([card, card], "all_retained_pairs")

        for candidate in structured.candidates:
            for source in candidate.sources:
                add(candidate.cards, f"s6:{source}")

        leads = tuple(
            FirstLeadCandidate(
                cards=key,
                sources=tuple(sorted(sources)),
                component_count=len(
                    decompose(list(key), view.ordering).components),
                pair_lead=(len(key) == 2 and key[0] == key[1]),
                structured_throw=any(
                    source.startswith("s6:") for source in sources),
            )
            for key, sources in reasons.items()
        )
        maximum = max_live_leads + MAX_PAIR_LEADS + MAX_STRUCTURED_THROWS
        if len(leads) > maximum:
            raise AssertionError("bury/lead combo source exceeded finite cap")
        if not leads or action_key(leads[0].cards) != action_key(live[0]):
            raise AssertionError("combo candidate-zero lead drift")
        pair_keys = {(card, card) for card in pair_codes}
        if not pair_keys.issubset({lead.cards for lead in leads}):
            raise AssertionError("combo source omitted a retained pair")
        structured_keys = {candidate.cards for candidate in structured.candidates}
        if not structured_keys.issubset({lead.cards for lead in leads}):
            raise AssertionError("combo source omitted an S6 throw")

        group = BuryLeadGroup(
            bury_index=bury_index,
            bury=bury,
            retained_shape=_retained_shape(view, seat, structured),
            live_lead_count=len(live),
            guaranteed_pair_lead_count=len(pair_codes),
            structured_throw_ballot=structured,
            leads=leads,
        )
        groups.append(group)
        combo_count += len(leads)

    ballot = BuryLeadComboBallot(
        groups=tuple(groups),
        feasible_single_suit_voids=feasible_voids,
        generated_buries=bury_ballot.generated_unique,
        combo_count=combo_count,
        max_buries=max_buries,
        max_live_leads_per_bury=max_live_leads,
    )
    if not ballot.groups or ballot.combo_count > ballot.max_combos:
        raise AssertionError("bury/lead combo ballot population drift")
    if action_key(ballot.groups[0].bury.cards) != action_key(incumbent_bury):
        raise AssertionError("combo candidate-zero bury drift")
    return ballot
