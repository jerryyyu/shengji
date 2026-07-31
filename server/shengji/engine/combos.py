"""Decomposition of same-suit plays into singles / pairs / tractors."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .cards import Ordering


@dataclass
class Component:
    kind: str            # "single" | "pair" | "tractor"
    cards: list[str]
    top: int             # highest level in the component
    pair_len: int        # 0 for single, 1 for pair, k for tractor of k pairs

    @property
    def size(self) -> int:
        return len(self.cards)


@dataclass
class Decomposition:
    components: list[Component] = field(default_factory=list)

    @property
    def n_pairs(self) -> int:
        return sum(c.pair_len for c in self.components)

    @property
    def size(self) -> int:
        return sum(c.size for c in self.components)

    def shape(self) -> tuple[tuple[int, ...], int]:
        """Structure signature: (sorted pair-run lengths desc, #singles).

        Two plays with the same shape are comparable; a follower must match
        the lead's shape to contend for the trick.
        """
        runs = sorted((c.pair_len for c in self.components if c.pair_len), reverse=True)
        singles = sum(1 for c in self.components if c.pair_len == 0)
        return (tuple(runs), singles)

    def top_level(self) -> int:
        """Comparison level: top of the largest component (pairs beat shape
        ties, so rank by pair-run length first, then level)."""
        best = max(self.components, key=lambda c: (c.pair_len, c.top))
        return best.top

    def max_pair_run(self) -> int:
        return max((c.pair_len for c in self.components), default=0)


def decompose(cards: list[str], ordering: Ordering) -> Decomposition:
    """Split ``cards`` (all one effective suit) into tractors, pairs, singles.

    Tractors are maximal runs of pairs on strictly consecutive levels, longest
    first. Two different pairs sharing a level (off-suit trump-rank pairs)
    cannot join the same tractor.
    """
    cnt = Counter(cards)
    pair_codes = [c for c, k in cnt.items() if k >= 2]
    singles = [c for c, k in cnt.items() if k == 1]

    # Map level -> available pair codes at that level.
    by_level: dict[int, list[str]] = {}
    for c in pair_codes:
        by_level.setdefault(ordering.level(c), []).append(c)

    comps: list[Component] = []
    remaining = {lv: list(codes) for lv, codes in by_level.items()}
    # Greedy: repeatedly take the longest run of consecutive levels, consuming
    # one pair per level. Terminates because every pass consumes >=1 pair.
    while remaining:
        levels = sorted(remaining)
        best: list[int] = []
        i = 0
        while i < len(levels):
            j = i
            while j + 1 < len(levels) and levels[j + 1] == levels[j] + 1:
                j += 1
            if j - i + 1 > len(best):
                best = levels[i:j + 1]
            i = j + 1
        chosen = []
        for lv in best:
            chosen.append(remaining[lv].pop(0))
            if not remaining[lv]:
                del remaining[lv]
        if len(chosen) >= 2:
            comps.append(Component("tractor", [c for c in chosen for _ in (0, 1)],
                                   top=best[-1], pair_len=len(chosen)))
        else:
            comps.append(Component("pair", chosen * 2, top=best[0], pair_len=1))

    for c in singles:
        comps.append(Component("single", [c], top=ordering.level(c), pair_len=0))
    comps.sort(key=lambda c: (-c.pair_len, -c.top))
    return Decomposition(comps)


def pair_count(cards: list[str]) -> int:
    return sum(k // 2 for k in Counter(cards).values())


def find_tractor_runs(cards: list[str], ordering: Ordering, k: int) -> list[list[str]]:
    """All k-length tractors (as card lists) available in ``cards`` (one suit),
    lowest first. Windows over consecutive levels each holding a pair."""
    cnt = Counter(cards)
    by_level: dict[int, list[str]] = {}
    for c, n in cnt.items():
        if n >= 2:
            by_level.setdefault(ordering.level(c), []).append(c)
    levels = sorted(by_level)
    out: list[list[str]] = []
    for start in levels:
        window = [start + d for d in range(k)]
        if all(lv in by_level for lv in window):
            chosen = [by_level[lv][0] for lv in window]
            out.append([c for c in chosen for _ in (0, 1)])
    return out


def has_tractor(cards: list[str], ordering: Ordering, k: int) -> bool:
    return bool(find_tractor_runs(cards, ordering, k))
