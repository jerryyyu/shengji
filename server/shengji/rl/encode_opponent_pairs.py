"""Encoder v4: what the OTHER seats can answer a pair with (issue #341).

Codex's v3 (PR #336) added eight own-hand control columns and improved offline
loss without moving play.  This block is the opponent side of the same table:
per effective suit, how many cards are still unseen, how many pairs have been
played as pairs and by whom, how many pairs are still possible, and the memory's
provable per-seat pair caps -- the inference the sampler already enforces but
no encoder version has ever exposed to the net.

Everything here is public: the memory is the same ``Memory(rnd, seat,
own_kitty=False)`` the v1/v2 columns use, and play history is public by
construction.  No other seat's hand is ever read.
"""
from collections import Counter

from ..engine.cards import SUITS, TRUMP

_SUITS_EFF = tuple(SUITS) + (TRUMP,)
#: relative seats other than the actor: next, partner, previous
_OTHERS = (1, 2, 3)
_CAP_STATES = ("zero", "at_most_one", "unknown")

OPPONENT_PAIR_COLUMNS = (
    *[f"unseen_frac:{s}" for s in _SUITS_EFF],                       # 5
    *[f"pairs_played_frac:{s}" for s in _SUITS_EFF],                 # 5
    *[f"pairs_possible_frac:{s}" for s in _SUITS_EFF],               # 5
    *[f"pair_cap:{rel}:{s}:{state}" for rel in _OTHERS
      for s in _SUITS_EFF for state in _CAP_STATES],                 # 45
    *[f"pairs_played_by_frac:{rel}:{s}" for rel in _OTHERS
      for s in _SUITS_EFF],                                          # 15
)
N_OPPONENT_PAIR_COLUMNS = len(OPPONENT_PAIR_COLUMNS)                 # 75
assert N_OPPONENT_PAIR_COLUMNS == 75


def _pairs_in_play(cards, ordering) -> Counter:
    """Pairs played TOGETHER in one play, per effective suit: a rank held twice
    in the same play.  Two copies played on different tricks are not a pair,
    which is exactly what the card-count planes cannot tell apart."""
    out: Counter = Counter()
    for card, count in Counter(cards).items():
        if count >= 2:
            out[ordering.eff_suit(card)] += count // 2
    return out


def opponent_pair_columns(rnd, seat: int, mem) -> list[float]:
    """The 75 v4 columns for ``seat``; ``mem`` is the public memory."""
    o = rnd.ordering
    assert o is not None
    unseen_by_suit: Counter = Counter()
    pairs_possible: Counter = Counter()
    for card, count in mem.unseen.items():
        if count <= 0:
            continue
        suit = o.eff_suit(card)
        unseen_by_suit[suit] += count
        if count >= 2:
            pairs_possible[suit] += 1
    played_all: Counter = Counter()
    played_by = {s: Counter() for s in range(4)}
    tricks = list(rnd.history)
    if rnd.trick is not None and rnd.trick.plays:
        tricks.append(rnd.trick)
    for trick in tricks:
        for tp in trick.plays:
            pairs = _pairs_in_play(tp.cards, o)
            played_all.update(pairs)
            played_by[tp.seat].update(pairs)
    obs: list[float] = []
    for s in _SUITS_EFF:
        obs.append(unseen_by_suit[s] / 27.0)
    for s in _SUITS_EFF:
        obs.append(played_all[s] / 13.0)
    for s in _SUITS_EFF:
        obs.append(pairs_possible[s] / 13.0)
    for rel in _OTHERS:
        other = (seat + rel) % 4
        for s in _SUITS_EFF:
            cap = mem.max_pairs(other, s)
            obs += [1.0 if cap == 0 else 0.0,
                    1.0 if cap == 1 else 0.0,
                    1.0 if cap is None else 0.0]
    for rel in _OTHERS:
        other = (seat + rel) % 4
        for s in _SUITS_EFF:
            obs.append(played_by[other][s] / 13.0)
    assert len(obs) == N_OPPONENT_PAIR_COLUMNS
    return obs
