"""Card primitives and trump-aware ordering for Sheng Ji (2 decks, 108 cards)."""

from __future__ import annotations

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = "SHDC"
LJ = "LJ"  # little (black) joker
BJ = "BJ"  # big (red) joker
JOKERS = (LJ, BJ)

TRUMP = "T"  # effective-suit tag for trump cards


def make_deck() -> list[str]:
    """108 card codes: two standard decks including both jokers."""
    one = [s + r for s in SUITS for r in RANKS] + [LJ, BJ]
    return one * 2


def is_joker(code: str) -> bool:
    return code in JOKERS


def card_suit(code: str) -> str | None:
    return None if is_joker(code) else code[0]


def card_rank(code: str) -> str | None:
    return None if is_joker(code) else code[1:]


def points(code: str) -> int:
    r = card_rank(code)
    if r == "5":
        return 5
    if r in ("10", "K"):
        return 10
    return 0


def total_points(codes) -> int:
    return sum(points(c) for c in codes)


class Ordering:
    """Card comparison/grouping for a fixed trump suit + trump rank.

    ``trump_suit`` is one of SHDC, or None for no-trump (joker declaration).
    Every card has an effective suit (its own suit, or "T" if it is trump)
    and a level: an integer position within its effective suit. Levels are
    consecutive, so tractor adjacency is "level difference of exactly 1".

    Trump ladder (ascending), suited trump example (hearts, rank 7):
      H2 H3 H4 H5 H6 H8 ... HA | S7/D7/C7 (one shared level) | H7 | LJ | BJ
    No-trump: rank cards of all suits share level 0, then LJ, BJ.
    """

    def __init__(self, trump_suit: str | None, trump_rank: str):
        self.trump_suit = trump_suit
        self.trump_rank = trump_rank
        self.plain_ranks = [r for r in RANKS if r != trump_rank]
        self._plain_level = {r: i for i, r in enumerate(self.plain_ranks)}
        self._n_plain_trump = len(self.plain_ranks) if trump_suit else 0

    def is_trump(self, code: str) -> bool:
        if is_joker(code):
            return True
        if card_rank(code) == self.trump_rank:
            return True
        return self.trump_suit is not None and code[0] == self.trump_suit

    def eff_suit(self, code: str) -> str:
        return TRUMP if self.is_trump(code) else code[0]

    def level(self, code: str) -> int:
        if not self.is_trump(code):
            return self._plain_level[card_rank(code)]
        base = self._n_plain_trump
        if code == BJ:
            return base + 3 if self.trump_suit else base + 2
        if code == LJ:
            return base + 2 if self.trump_suit else base + 1
        if card_rank(code) == self.trump_rank:
            if self.trump_suit is None:
                return base  # all rank cards tie in no-trump
            return base + 1 if code[0] == self.trump_suit else base
        return self._plain_level[card_rank(code)]  # plain card of the trump suit

    def sort_key(self, code: str) -> tuple[int, int, str]:
        """Stable display/sort order: plain suits first, trump group last."""
        suit_order = {"S": 0, "H": 1, "C": 2, "D": 3, TRUMP: 4}
        return (suit_order[self.eff_suit(code)], self.level(code), code)


def natural_sort_key(code: str) -> tuple[int, int]:
    """Sort order before trump is known."""
    if code == BJ:
        return (4, 1)
    if code == LJ:
        return (4, 0)
    return ({"S": 0, "H": 1, "C": 2, "D": 3}[code[0]], RANKS.index(code[1:]))
