"""Exhaustive legal-action enumeration for one decision state.

Why a new enumerator
--------------------
The engine exposes legality checks (``validate_lead`` / ``validate_follow``)
but no enumerator.  ``shengji.ai.endgame.exhaustive_legal_actions`` is
exhaustive but brute-forces every card subset and therefore refuses hands
above ``max_hand_cards`` (4 by default); ``shengji.rl.actions.enumerate_actions``
is a ballot (capped, heuristic-seeded), not the legal set.  This module
enumerates the legal set structurally so a 25-card hand is tractable, and
counts it exactly so a capped listing can say how much it withheld.

What "legal" means here (mirrors ``Round.play``)
-----------------------------------------------
* Lead: any non-empty sub-multiset of the hand drawn from ONE effective suit
  (plain suit or trump).  Multi-component throws are accepted by the engine
  (a failed throw is converted to its forced component, it does not raise),
  so every same-suit subset is a legal submitted action.
* Follow: exactly ``len(lead)`` cards; if the hand holds at least that many
  cards of the led effective suit the play must come entirely from it and
  satisfy the pair/tractor obligations (checked with the engine's own
  ``validate_follow``); if it holds fewer, all of them plus any fill; if void,
  anything.

Ordering (deterministic, documented so a capped prefix is meaningful)
--------------------------------------------------------------------
Leads: singles, then pairs, then tractors (shortest first), then throws by
size — each group in suit order S, H, C, D, trump and lexicographic on the
sorted card tuple.  Follows: lexicographic on the sorted card tuple within
the rule case.  Cards inside an action are sorted (canonical).

Caps
----
``enumerate_legal(..., cap=N)`` lists at most N actions and reports the exact
total in ``count``; ``complete`` is ``len(actions) == count``.  Counting is
closed-form (a generating function over multiplicities) for leads and for
short-suit / void follows; in-suit follows are counted by enumeration through
``validate_follow`` up to ``COUNT_CEILING`` raw candidates, beyond which
``count`` is None.
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Iterator, Sequence

from ..engine.cards import TRUMP, Ordering
from ..engine.combos import find_tractor_runs
from ..engine.legal import (IllegalPlay, suit_cards, uniform_suit,
                            validate_follow, validate_lead)
from ..engine.round import Round, Trick, TrickPlay

DEFAULT_CAP = 256
#: raw in-suit candidates examined when counting constrained follows
COUNT_CEILING = 2_000_000
SUIT_ORDER = ("S", "H", "C", "D", TRUMP)
MAX_TRACTOR = 12


@dataclass(frozen=True)
class LegalSet:
    kind: str                      # "lead" | "follow"
    actions: list[list[str]]       # canonical (sorted) card lists
    count: int | None              # exact total, None when uncountable
    complete: bool

    def keys(self) -> set[tuple[str, ...]]:
        return {tuple(a) for a in self.actions}


# ----------------------------------------------------------------- counting

def count_multiset_subsets(counts: Sequence[int], size: int) -> int:
    """Number of distinct ``size``-sub-multisets of a multiset with these
    multiplicities (coefficient of x^size in prod (1 + x + ... + x^m))."""
    poly = [1]
    for m in counts:
        new = [0] * min(len(poly) + m, size + 1)
        for i, c in enumerate(poly):
            if c == 0:
                continue
            for k in range(m + 1):
                if i + k > size:
                    break
                new[i + k] += c
        poly = new
    return poly[size] if size < len(poly) else 0


def count_nonempty_submultisets(counts: Sequence[int]) -> int:
    total = 1
    for m in counts:
        total *= m + 1
    return total - 1


def multiset_subsets(cards: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    """Distinct ``size``-sub-multisets of ``cards`` in lexicographic order."""
    cnt = Counter(cards)
    codes = sorted(cnt)
    out: list[str] = []

    def rec(i: int, left: int):
        if left == 0:
            yield tuple(out)
            return
        if i == len(codes):
            return
        # remaining capacity check for early exit
        for k in range(min(cnt[codes[i]], left), -1, -1):
            if k:
                out.extend([codes[i]] * k)
            yield from rec(i + 1, left - k)
            if k:
                del out[-k:]

    # rec yields larger-k-first per position, which is lexicographic on
    # sorted tuples because a repeated code sorts before the next code.
    yield from rec(0, size)


# ------------------------------------------------------------------- leads

def _lead_groups(hand: list[str], o: Ordering):
    """Yield (suit, cards) in canonical suit order."""
    for suit in SUIT_ORDER:
        cards = sorted(suit_cards(hand, suit, o))
        if cards:
            yield suit, cards


def iter_lead_actions(hand: list[str], o: Ordering) -> Iterator[tuple[str, ...]]:
    """All legal leads in the documented order, each exactly once."""
    groups = list(_lead_groups(hand, o))
    seen: set[tuple[str, ...]] = set()

    def emit(key: tuple[str, ...]):
        if key not in seen:
            seen.add(key)
            yield key

    for _, cards in groups:                                   # singles
        for code in sorted(set(cards)):
            yield from emit((code,))
    for _, cards in groups:                                   # pairs
        cnt = Counter(cards)
        for code in sorted(cnt):
            if cnt[code] >= 2:
                yield from emit((code, code))
    for _, cards in groups:                                   # tractors
        for length in range(2, MAX_TRACTOR + 1):
            runs = find_tractor_runs(cards, o, length)
            if not runs:
                break
            for run in sorted(tuple(sorted(r)) for r in runs):
                yield from emit(run)
    max_size = max((len(c) for _, c in groups), default=0)
    for size in range(2, max_size + 1):                       # throws
        for _, cards in groups:
            if len(cards) < size:
                continue
            for key in multiset_subsets(cards, size):
                yield from emit(key)


def count_lead_actions(hand: list[str], o: Ordering) -> int:
    return sum(count_nonempty_submultisets(list(Counter(cards).values()))
               for _, cards in _lead_groups(hand, o))


# ----------------------------------------------------------------- follows

def _follow_case(hand: list[str], lead: list[str], o: Ordering):
    suit = uniform_suit(lead, o)
    assert suit is not None
    h_suit = sorted(suit_cards(hand, suit, o))
    n = len(lead)
    if len(h_suit) >= n:
        return "in-suit", h_suit, None, n
    off = list(hand)
    for c in h_suit:
        off.remove(c)
    return ("short" if h_suit else "void"), h_suit, sorted(off), n


def iter_follow_actions(hand: list[str], lead: list[str],
                        o: Ordering) -> Iterator[tuple[str, ...]]:
    case, h_suit, off, n = _follow_case(hand, lead, o)
    if case == "in-suit":
        for key in multiset_subsets(h_suit, n):
            try:
                validate_follow(list(key), hand, lead, o)
            except IllegalPlay:
                continue
            yield key
    else:
        base = tuple(h_suit)
        for fill in multiset_subsets(off, n - len(base)):
            yield tuple(sorted(base + fill))


def count_follow_actions(hand: list[str], lead: list[str], o: Ordering) -> int | None:
    case, h_suit, off, n = _follow_case(hand, lead, o)
    if case == "in-suit":
        raw = count_multiset_subsets(list(Counter(h_suit).values()), n)
        if raw > COUNT_CEILING:
            return None
        return sum(1 for _ in iter_follow_actions(hand, lead, o))
    return count_multiset_subsets(list(Counter(off).values()), n - len(h_suit))


# -------------------------------------------------------------- public API

def enumerate_legal(rnd: Round, seat: int, cap: int | None = DEFAULT_CAP,
                    must_include: Sequence[Sequence[str]] = ()) -> LegalSet:
    """The exhaustive legal set at ``rnd`` for ``seat`` (which must be to act).

    ``must_include`` actions (e.g. the taken action and the source's ballot)
    are appended when a cap would otherwise drop them; they are verified legal
    with the engine's own validators first.
    """
    if rnd.phase != "play" or rnd.turn != seat or rnd.trick is None \
            or rnd.ordering is None:
        raise ValueError("enumerate_legal requires the acting seat in play phase")
    o = rnd.ordering
    hand = list(rnd.hands[seat])
    if not rnd.trick.plays:
        kind = "lead"
        it = iter_lead_actions(hand, o)
        count: int | None = count_lead_actions(hand, o)
    else:
        kind = "follow"
        lead = rnd.trick.plays[0].cards
        it = iter_follow_actions(hand, lead, o)
        count = count_follow_actions(hand, lead, o)
    actions: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for key in it:
        if cap is not None and len(actions) >= cap:
            break
        actions.append(key)
        seen.add(key)
    complete = count is not None and len(actions) == count
    if not complete:
        for extra in must_include:
            key = tuple(sorted(extra))
            if key in seen:
                continue
            if not is_legal(rnd, seat, list(key)):
                raise ValueError(f"must_include action is illegal: {key}")
            actions.append(key)
            seen.add(key)
    return LegalSet(kind, [list(a) for a in actions], count, complete)


def is_legal(rnd: Round, seat: int, cards: Sequence[str]) -> bool:
    """Engine oracle for one submitted action (no mutation, no rollouts)."""
    assert rnd.trick is not None and rnd.ordering is not None
    hand = rnd.hands[seat]
    try:
        if not rnd.trick.plays:
            # other hands only influence the failed-throw substitution, never
            # whether the submission is accepted
            validate_lead(list(cards), hand, [], rnd.ordering)
        else:
            validate_follow(list(cards), hand, rnd.trick.plays[0].cards,
                            rnd.ordering)
    except IllegalPlay:
        return False
    return True


def bury_action_count(hand_before: Sequence[str], kitty_size: int = 8) -> int:
    """Exact number of distinct 8-card buries from the banker's 33 cards."""
    return count_multiset_subsets(list(Counter(hand_before).values()), kitty_size)


# ------------------------------------------------------- brute-force oracle

def clone_for_probe(rnd: Round) -> Round:
    """Cheap copy of the mutable state ``Round.play`` touches."""
    clone: Round = copy.copy(rnd)
    clone.hands = [list(h) for h in rnd.hands]
    clone.buried = list(rnd.buried)
    clone.history = list(rnd.history)
    clone.passed = set(rnd.passed)
    clone.trick = (None if rnd.trick is None else Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays],
        winner=rnd.trick.winner, points=rnd.trick.points))
    clone.message = None
    clone.__dict__.pop("_trusted_rollout", None)
    return clone


def engine_accepts(rnd: Round, seat: int, cards: Sequence[str]) -> bool:
    """Does ``Round.play`` accept this submission?  (IllegalPlay => no.)"""
    probe = clone_for_probe(rnd)
    try:
        probe.play(seat, list(cards))
    except IllegalPlay:
        return False
    return True


def brute_force_legal(rnd: Round, seat: int, *, max_size: int | None = None,
                      sample: int | None = None, rng=None) -> set[tuple[str, ...]]:
    """Every distinct sub-multiset the ENGINE accepts, by trying ``Round.play``.

    Leads: all sizes up to ``max_size`` (or the whole hand).  Follows: exactly
    ``len(lead)`` cards.  ``sample`` limits the raw candidates tried (uniform
    random from the enumeration order) for combinatorially large cases.
    """
    assert rnd.trick is not None
    hand = list(rnd.hands[seat])
    if rnd.trick.plays:
        sizes = [len(rnd.trick.plays[0].cards)]
    else:
        top = len(hand) if max_size is None else min(max_size, len(hand))
        sizes = list(range(1, top + 1))
    candidates: list[tuple[str, ...]] = []
    for size in sizes:
        if size > len(hand):
            continue
        candidates.extend(multiset_subsets(hand, size))
    if sample is not None and len(candidates) > sample:
        assert rng is not None
        candidates = rng.sample(candidates, sample)
    return {key for key in candidates if engine_accepts(rnd, seat, key)}
