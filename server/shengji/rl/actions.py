"""Legal-play enumeration for RL (DouZero-style enumerate-and-score).

v1 policy: exhaustive for leads (all singles, pairs, tractors, plus the
heuristic's safe throw if any); follow candidates come from the MCBot
candidate machinery (guaranteed legal, covers win/dump/feed shapes).
TODO Phase 3: exhaustive follow enumeration if candidate coverage caps
learning.
"""

from __future__ import annotations

from collections import Counter

from ..engine.cards import TRUMP
from ..engine.combos import decompose, find_tractor_runs
from ..engine.legal import suit_cards
from ..engine.round import Round
from ..ai.heuristic import PLAIN_SUITS
from ..ai.mcbot import MCBot

_helper = MCBot(seed=0)


def enumerate_actions(rnd: Round, seat: int,
                      exhaustive_follows: bool = False) -> list[list[str]]:
    """Candidate plays for the acting seat, deduped, legality-guaranteed.

    exhaustive_follows=False (default): follows come from the search's
    candidate generator — the SAME distribution RL training data uses, so
    play-time ballots match training ballots (a net scoring encodings it
    never trained on collapses: measured Elo 798 vs 1022-equivalent).
    exhaustive_follows=True: every legal distinct-code multiset (bounded) —
    for coverage analysis and human-decision evaluation, NOT for net play."""
    assert rnd.ordering is not None and rnd.trick is not None
    o = rnd.ordering
    hand = rnd.hands[seat]
    plays: list[list[str]] = []
    seen: set[tuple] = set()

    def add(play: list[str] | None) -> None:
        if not play:
            return
        key = tuple(sorted(play))
        if key not in seen:
            seen.add(key)
            plays.append(play)

    if not rnd.trick.plays:
        for s in list(PLAIN_SUITS) + [TRUMP]:
            cards = suit_cards(hand, s, o)
            if not cards:
                continue
            for code in set(cards):
                add([code])
            cnt = Counter(cards)
            for code, k in cnt.items():
                if k >= 2:
                    add([code, code])
            for length in range(2, 7):
                for run in find_tractor_runs(cards, o, length):
                    add(run)
        add(_helper._lead(rnd, seat))  # heuristic pick incl. safe throws
    elif not exhaustive_follows:
        for cand in _helper._candidates(rnd, seat):
            add(cand)
    else:
        # Exhaustive follows (gap analysis 2026-08-01: the constructed
        # candidate set missed ~20% of humans' legal plays in narrow spots).
        # Enumerate distinct-code multisets, in-suit part first, validated by
        # the engine; structured fallbacks seed the pathological cases.
        from itertools import combinations
        from ..engine.legal import IllegalPlay, uniform_suit, validate_follow
        lead = rnd.trick.plays[0].cards
        n = len(lead)
        lead_suit = uniform_suit(lead, o)
        h_suit = suit_cards(hand, lead_suit, o)
        n_suit = min(n, len(h_suit))
        LIMIT = 64

        def valid_add(play):
            if len(plays) >= LIMIT:
                return
            try:
                validate_follow(list(play), hand, lead, o)
            except IllegalPlay:
                return
            add(list(play))

        for cand in _helper._candidates(rnd, seat):  # seeds (always present)
            add(cand)
        in_suit_sets = {tuple(sorted(c))
                        for c in combinations(sorted(h_suit), n_suit)}
        if n_suit == n:
            for s in sorted(in_suit_sets):
                valid_add(s)
        else:
            off = list(hand)
            for c in h_suit:
                off.remove(c)
            fill_k = n - n_suit
            fill_sets = {tuple(sorted(c))
                         for c in combinations(sorted(off), fill_k)}
            base = tuple(sorted(h_suit))
            if len(fill_sets) * max(len(in_suit_sets), 1) <= 4000:
                for f in sorted(fill_sets):
                    valid_add(base + f)
    return plays
