"""Cython fast-path vs pure-Python parity (PERF.md #2+#3 prototype).

Extends the test_engine_parity.py pattern: the compiled kernels in
shengji/engine/_fast must reproduce combos._decompose_uncached and
combos._find_tractor_runs_uncached byte-identically — including their
order sensitivity (input order feeds Counter insertion order, which the
memo layer then freezes for the round). Pure Python stays the reference.

Skipped when the extension isn't built:
    cd server && uv run python setup.py build_ext --inplace
"""

import itertools
import random
import sys

import pytest

sys.path.insert(0, ".")
from shengji.engine import combos, fast, legal  # noqa: E402
from shengji.engine.cards import BJ, LJ, TRUMP, Ordering, make_deck  # noqa: E402

pytestmark = pytest.mark.skipif(not fast.HAVE_FAST,
                                reason="_fast extension not built")

ORDERINGS = [
    Ordering("H", "7"),   # suited trump
    Ordering("S", "2"),   # trump rank at the bottom of the plain ladder
    Ordering("D", "A"),   # trump rank at the top
    Ordering(None, "7"),  # no-trump: all rank cards share one level
    Ordering(None, "A"),
    Ordering("C", "10"),
]


def _assert_group_parity(cards, o):
    ref = combos._decompose_uncached(cards, o)
    got = fast.decompose_uncached(cards, o)
    assert got == ref, (cards, o.trump_suit, o.trump_rank)
    for k in range(1, 7):
        r = combos._find_tractor_runs_uncached(cards, o, k)
        g = fast.find_tractor_runs_uncached(cards, o, k)
        assert g == r, (cards, k, o.trump_suit, o.trump_rank)


def test_random_hand_parity():
    """2000 random hands x all orderings, split per effective suit (the
    decompose contract), in raw sample order (order sensitivity matters)."""
    rng = random.Random(42)
    deck = make_deck()
    for i in range(2000):
        o = ORDERINGS[i % len(ORDERINGS)]
        hand = rng.sample(deck, rng.randint(1, 25))
        groups = {}
        for c in hand:
            groups.setdefault(o.eff_suit(c), []).append(c)
        for cards in groups.values():
            _assert_group_parity(cards, o)


def test_edge_cases():
    o = Ordering("H", "7")
    nt = Ordering(None, "7")
    cases = [
        [BJ, BJ],                                     # big joker pair
        [LJ, LJ, BJ, BJ],                             # top-of-trump tractor
        ["H7", "H7", LJ, LJ],                         # trump-rank + joker run
        ["S7", "S7", "D7", "D7", "C7", "C7"],         # off-suit rank pairs, shared level
        ["S7", "D7", "S7", "D7", "H7", "H7"],         # interleaved order variant
        ["HA", "HA", "S7", "S7", "H7", "H7", LJ, LJ], # ambiguous run through rank level
        ["H2", "H2", "H3", "H3", "H4", "H4",
         "H5", "H5", "H6", "H6", "H8", "H8"],         # 6-pair tractor (rank gap bridged)
        ["S3", "S3", "S4", "S4", "S5", "S5"],         # plain 3-tractor
        ["S3", "S4", "S3", "S4", "S5", "S6", "S5"],   # tractor + single, shuffled
    ]
    for cards in cases:
        for perm in itertools.islice(itertools.permutations(cards), 24):
            _assert_group_parity(list(perm), o)
    # no-trump: S7/H7/D7/C7 all share one level with the jokers above
    for cards in ([("%s7" % s) for s in "SHDC" for _ in (0, 1)],
                  ["S7", "S7", "H7", "H7", LJ, LJ, BJ, BJ]):
        for perm in itertools.islice(itertools.permutations(cards), 24):
            _assert_group_parity(list(perm), nt)


def test_suit_cards_parity():
    """fast.suit_cards == legal.suit_cards on full mixed hands."""
    rng = random.Random(5)
    deck = make_deck()
    pure = fast._saved.get("suit_cards", legal.suit_cards)  # pure reference
    for i in range(500):
        o = ORDERINGS[i % len(ORDERINGS)]
        hand = rng.sample(deck, rng.randint(1, 33))
        for eff in ["S", "H", "D", "C", TRUMP]:
            assert fast.suit_cards(hand, eff, o) == pure(hand, eff, o)


def test_memoized_route_matches_reference():
    """With activate(), the routed decompose / find_tractor_runs (C memo key
    + kernels) still equal fresh pure-Python recomputes."""
    rng = random.Random(7)
    deck = make_deck()
    was_active = bool(fast._saved)  # don't tear down a suite-wide activation
    fast.activate()
    try:
        for _ in range(300):
            # Fresh Ordering => fresh memo per hand: the memo freezes the
            # first caller's card order for anagram keys (pure Python does
            # too), so cross-hand cache hits can't be compared to a fresh
            # recompute of a differently-ordered anagram.
            o = Ordering("S", "9")
            hand = rng.sample(deck, rng.randint(2, 16))
            groups = {}
            for c in hand:
                groups.setdefault(o.eff_suit(c), []).append(c)
            for cards in groups.values():
                assert combos.decompose(cards, o) == combos._decompose_uncached(
                    cards, o)
                for k in (2, 3):
                    assert (combos.find_tractor_runs(cards, o, k)
                            == combos._find_tractor_runs_uncached(cards, o, k))
    finally:
        if not was_active:
            fast.deactivate()
