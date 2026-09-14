"""The card GRID behind the ``grid`` trunk block (issue #411).

The value net's inputs are fourteen 54-wide planes per state (nine public
card-count planes and the five world receivers), so a fact such as "how many
pairs of hearts are still out" is spread across thirteen unrelated columns
that only the trump one-hots tie together.  The grid lays the same numbers out
as a table the way a player sees the round: one ROW per effective suit
(S, H, D, C, trump) and one COLUMN per level within the row, so a pair is two
counts in one cell, a run is neighbouring cells, and "everything above my ace"
is the columns to the right.  Because the trump suit and rank move cards
between rows, the layout depends on the round: one index table per
(trump suit | no-trump) x trump rank, selected from the public one-hots.

Columns (18 per row):

* plain rows: the twelve non-trump ranks by level in columns 0..11, columns
  12..17 empty;
* trump row, suited trump: the trump suit's twelve plain ranks by level in
  0..11, the three off-suit trump-rank cards in 12..14 (spade, heart, diamond,
  club order minus the trump suit), the trump-suit trump rank in 15, the small
  joker in 16, the big joker in 17;
* trump row, no-trump: columns 0..11 empty, the four trump-rank cards in
  12..15 (suit order), jokers in 16 and 17.

Column index never decreases with the engine's ``Ordering.level`` along a row
(tested), so a column is a level and neighbouring columns are neighbouring
levels.  Empty slots point at a zero column appended to the card axis.
"""
from __future__ import annotations

import numpy as np

from ..engine.cards import BJ, LJ, RANKS, SUITS, TRUMP, Ordering
from .encode import CARD_INDEX, N_CARDS

GRID_ROWS = 5                     # S, H, D, C, trump
GRID_COLS = 18
#: the trump-suit one-hot order of ``encode_obs`` (S H D C NT)
TRUMP_CHOICES = tuple(SUITS) + (None,)
PAD = N_CARDS                     # the appended all-zero column
#: ``encode_obs`` offsets of the trump one-hots (the v1 prefix, every version)
SUIT_ONEHOT_OFFSET = 9 * N_CARDS  # 486
RANK_ONEHOT_OFFSET = SUIT_ONEHOT_OFFSET + 5


def grid_slots(trump_suit: str | None, trump_rank: str) -> np.ndarray:
    """``(GRID_ROWS, GRID_COLS)`` card indices (``PAD`` = empty) for one trump."""
    o = Ordering(trump_suit, trump_rank)
    slots = np.full((GRID_ROWS, GRID_COLS), PAD, dtype=np.int64)
    for code, index in CARD_INDEX.items():
        if code in (LJ, BJ):
            slots[4, 17 if code == BJ else 16] = index
            continue
        suit, rank = code[0], code[1:]
        if rank == trump_rank:
            if trump_suit is None:
                slots[4, 12 + SUITS.index(suit)] = index
            elif suit == trump_suit:
                slots[4, 15] = index
            else:
                others = [s for s in SUITS if s != trump_suit]
                slots[4, 12 + others.index(suit)] = index
            continue
        row = 4 if suit == trump_suit else SUITS.index(suit)
        slots[row, o.level(code)] = index
    return slots


def grid_table() -> np.ndarray:
    """``(len(TRUMP_CHOICES) * len(RANKS), GRID_ROWS * GRID_COLS)`` indexed by
    ``suit_choice * 13 + rank_choice`` in the one-hot orders of ``encode_obs``."""
    rows = []
    for suit in TRUMP_CHOICES:
        for rank in RANKS:
            rows.append(grid_slots(suit, rank).reshape(-1))
    return np.stack(rows)
