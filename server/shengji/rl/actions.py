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


def enumerate_actions(rnd: Round, seat: int) -> list[list[str]]:
    """All candidate plays for the acting seat, deduped, legality-guaranteed."""
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
    else:
        for cand in _helper._candidates(rnd, seat):
            add(cand)
    return plays
