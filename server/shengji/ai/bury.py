"""Deterministic, information-set-legal candidate sourcing for banker buries.

The first MC_BURY experiment compared four hand-authored policies.  That did
not test whether search can improve the once-per-round bury decision; it only
tested four points in a combinatorial space.  This module broadens the source
without looking at opponents' hidden hands.  Its entire input is the banker's
33-card hand, public trump ordering, and the incumbent eight-card bury.

Candidate scoring remains in :mod:`shengji.ai.mcbot`.  Keeping source and
scorer separate prevents bury experimentation from changing the ordinary
lead/follow ballot identity.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from ..engine.cards import SUITS, TRUMP, Ordering, points
from ..engine.round import HAND_SIZE, KITTY_SIZE


SCHEMA = "structured-bury-ballot-v1"
DEFAULT_MAX_CANDIDATES = 32


@dataclass(frozen=True)
class BuryCandidate:
    cards: tuple[str, ...]
    sources: tuple[str, ...]
    point_total: int
    trumps_buried: int
    voids_created: tuple[str, ...]
    split_pairs: tuple[str, ...]

    def record(self) -> dict:
        return {
            "cards": list(self.cards),
            "sources": list(self.sources),
            "point_total": self.point_total,
            "trumps_buried": self.trumps_buried,
            "voids_created": list(self.voids_created),
            "split_pairs": list(self.split_pairs),
        }


@dataclass(frozen=True)
class StructuredBuryBallot:
    candidates: tuple[BuryCandidate, ...]
    max_candidates: int
    generated_unique: int
    truncated: bool
    schema: str = SCHEMA

    def record(self) -> dict:
        return {
            "schema": self.schema,
            "max_candidates": self.max_candidates,
            "generated_unique": self.generated_unique,
            "truncated": self.truncated,
            "candidates": [candidate.record() for candidate in self.candidates],
        }


_PROFILES = (
    "point_preserving",
    "trump_preserving",
    "pair_preserving",
    "short_suit",
    "low_strength",
)


def _discard_key(code: str, profile: str, ordering: Ordering,
                 counts: Counter[str], suit_counts: Counter[str]) -> tuple:
    """Deterministic low-to-high discard preference for one objective."""
    trump = ordering.eff_suit(code) == TRUMP
    point = points(code)
    paired = counts[code] >= 2
    level = ordering.level(code)
    suit_len = suit_counts[ordering.eff_suit(code)]
    if profile == "point_preserving":
        return (point > 0, point, trump, paired, level, code)
    if profile == "trump_preserving":
        return (trump, point > 0, point, paired, level, code)
    if profile == "pair_preserving":
        return (trump, point > 0, paired, point, level, code)
    if profile == "short_suit":
        return (trump, suit_len, point > 0, point, paired, level, code)
    if profile == "low_strength":
        return (trump, level, point > 0, point, paired, code)
    raise ValueError(f"unknown bury profile {profile!r}")


def structured_bury_ballot(hand, ordering: Ordering, incumbent,
                           *, max_candidates: int = DEFAULT_MAX_CANDIDATES
                           ) -> StructuredBuryBallot:
    """Build a bounded structured bury ballot from banker-visible data only.

    The incumbent is always candidate zero.  Other candidates combine five
    discard priorities with forced one- and two-suit voids.  Every candidate
    is an eight-card multiset contained in ``hand``; duplicates are merged by
    card multiset before the explicit cap is applied.
    """
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    hand_counts = Counter(hand)
    incumbent_counts = Counter(incumbent)
    if len(incumbent) != KITTY_SIZE:
        raise ValueError(f"incumbent must bury exactly {KITTY_SIZE} cards")
    if incumbent_counts - hand_counts:
        raise ValueError("incumbent contains cards outside the banker hand")
    if len(hand) != HAND_SIZE + KITTY_SIZE:
        raise ValueError(
            f"structured bury requires the banker's {HAND_SIZE + KITTY_SIZE}-"
            f"card pre-bury hand, got {len(hand)}")

    suit_counts = Counter(ordering.eff_suit(code) for code in hand)
    # Insertion order is the registered source priority. Values are reason
    # sets so two strategies that reach the same multiset are deduplicated but
    # remain diagnosable.
    reasons: dict[tuple[str, ...], set[str]] = {}

    def add(cards, source: str) -> None:
        if len(cards) != KITTY_SIZE:
            return
        card_counts = Counter(cards)
        if card_counts - hand_counts:
            raise AssertionError(f"generated illegal bury from {source}")
        key = tuple(sorted(cards))
        reasons.setdefault(key, set()).add(source)

    def fill(forced, profile: str, source: str,
             *, boundary_alternatives: int = 0) -> None:
        forced = list(forced)
        if len(forced) > KITTY_SIZE:
            return
        remaining = hand_counts - Counter(forced)
        if sum(remaining.values()) < KITTY_SIZE - len(forced):
            return
        ordered = sorted(
            remaining.elements(),
            key=lambda code: _discard_key(
                code, profile, ordering, hand_counts, suit_counts),
        )
        need = KITTY_SIZE - len(forced)
        add(forced + ordered[:need], source)
        # Search the local Pareto frontier around each deterministic profile.
        # Replacing only the marginal fill card keeps the objective/forced
        # void intact while exposing trade-offs the five single argmins miss.
        # This is bounded explicitly; it is not combinatorial enumeration.
        if need:
            for offset in range(1, boundary_alternatives + 1):
                j = need - 1 + offset
                if j >= len(ordered):
                    break
                add(forced + ordered[:need - 1] + [ordered[j]],
                    f"{source}:boundary+{offset}")

    # Candidate zero is a literal incumbent control, not just whichever
    # structured profile happens to reproduce it.
    add(incumbent, "incumbent")
    for profile in _PROFILES:
        fill([], profile, profile)

    by_suit = {
        suit: sorted(code for code in hand
                     if ordering.eff_suit(code) == suit)
        for suit in SUITS
    }
    nonempty = sorted(
        (suit for suit in SUITS if by_suit[suit]),
        key=lambda suit: (len(by_suit[suit]), SUITS.index(suit)),
    )
    # Force every feasible single-suit void, then fill the residual slots under
    # several preservation objectives. Shortest suits come first so a tight
    # cap still covers the clearest void opportunities.
    for suit in nonempty:
        forced = by_suit[suit]
        if len(forced) <= KITTY_SIZE:
            for profile in ("point_preserving", "trump_preserving",
                            "pair_preserving", "low_strength"):
                fill(forced, profile, f"void:{suit}+{profile}")

    # Two-suit voids are rare but strategically distinct: the banker may trade
    # a few points now for two future ruff lanes. They are lower source priority
    # than ensuring every one-suit hypothesis is represented.
    for left, right in combinations(nonempty, 2):
        forced = by_suit[left] + by_suit[right]
        if len(forced) <= KITTY_SIZE:
            for profile in ("point_preserving", "trump_preserving"):
                fill(forced, profile,
                     f"void:{left}+{right}+{profile}")

    # Only after every base objective and feasible void has one slot do we add
    # bounded one-card frontier alternatives. This ordering prevents a tight
    # cap from spending the entire ballot around one objective or one suit.
    for profile in _PROFILES:
        fill([], profile, profile, boundary_alternatives=5)
    for suit in nonempty:
        forced = by_suit[suit]
        if len(forced) <= KITTY_SIZE:
            for profile in ("point_preserving", "trump_preserving",
                            "pair_preserving", "low_strength"):
                fill(forced, profile, f"void:{suit}+{profile}",
                     boundary_alternatives=3)

    generated_unique = len(reasons)
    keys = list(reasons)[:max_candidates]
    candidates = []
    for key in keys:
        buried = Counter(key)
        voids = tuple(
            suit for suit in SUITS
            if suit_counts[suit] > 0 and
            suit_counts[suit] == sum(
                n for code, n in buried.items()
                if ordering.eff_suit(code) == suit)
        )
        split_pairs = tuple(sorted(
            code for code, n in hand_counts.items()
            if n >= 2 and 0 < n - buried[code] < n
        ))
        candidates.append(BuryCandidate(
            cards=key,
            sources=tuple(sorted(reasons[key])),
            point_total=sum(points(code) for code in key),
            trumps_buried=sum(
                1 for code in key if ordering.eff_suit(code) == TRUMP),
            voids_created=voids,
            split_pairs=split_pairs,
        ))
    return StructuredBuryBallot(
        candidates=tuple(candidates),
        max_candidates=max_candidates,
        generated_unique=generated_unique,
        truncated=generated_unique > max_candidates,
    )
