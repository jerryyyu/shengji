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
            # Fresh Ordering => fresh memo per hand (keeps every probe a
            # first-touch of its exact-order key).
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


def test_exact_order_memo_contract_fast_route():
    """The 08-03 audit contract, enforced on the COMPILED memo route: keys
    are the caller's exact order, so anagram inputs with equal-level pairs
    each get their own reference-identical result (a sorted key collapses
    them — the bug that quarantined the prototype)."""
    was_active = bool(fast._saved)
    fast.activate()
    try:
        o = Ordering("H", "7")
        c1 = ["S7", "S7", "D7", "D7"]
        c2 = ["D7", "D7", "S7", "S7"]
        combos.decompose(c2, o)  # prime with the other order
        assert combos.decompose(c1, o) == combos._decompose_uncached(c1, o)
        assert combos.decompose(c2, o) == combos._decompose_uncached(c2, o)
        t1 = ["HA", "HA", "S7", "S7", "D7", "D7"]
        t2 = ["HA", "HA", "D7", "D7", "S7", "S7"]
        combos.find_tractor_runs(t2, o, 2)
        assert (combos.find_tractor_runs(t1, o, 2)
                == combos._find_tractor_runs_uncached(t1, o, 2))
        # the fast route fills the SAME dicts the invariant audit reads
        assert tuple(c1) in o._dcache and (tuple(t1), 2) in o._trcache
    finally:
        if not was_active:
            fast.deactivate()


# ---------------------------------------------------------------------------
# Phase 1: rules parity — beats / decompose_matching / validate_follow +
# helpers vs the pure reference on randomized cases (throws, mixed suits,
# trump-rank equal-level pairs, no-trump). Pure and fast use SEPARATE
# Ordering instances so a shared memo can never mask a kernel divergence,
# and routing is DEACTIVATED for the comparison (under SHENGJI_FAST=1 the
# saved pure functions would otherwise call fast internals through their
# rebound module globals, masking divergence inside beats/validate_follow).
# ---------------------------------------------------------------------------

CONFIGS = [("H", "7"), ("S", "2"), ("D", "A"), (None, "7"), (None, "A"),
           ("C", "10")]


@pytest.fixture
def pure_routing():
    """legal/combos globals guaranteed pure for the duration of the test;
    restores suite-wide activation afterwards."""
    was_active = bool(fast._saved)
    if was_active:
        fast.deactivate()
    try:
        yield
    finally:
        if was_active:
            fast.activate()


def _outcome(fn, *args):
    try:
        return fn(*args)
    except legal.IllegalPlay as e:
        return ("IllegalPlay", str(e))
    except AssertionError:
        return ("AssertionError",)


def _suit_groups(cards, o):
    groups = {}
    for c in cards:
        groups.setdefault(o.eff_suit(c), []).append(c)
    return groups


def _random_lead(rng, group):
    """A lead-shaped play from one suit group: a decomposition component,
    a random sub-multiset (throw), or the whole group (throw)."""
    r = rng.random()
    if r < 0.45:
        o = Ordering("H", "7")  # only used to pick cards, any split works
        comps = combos.decompose(list(group), o).components
        return list(rng.choice(comps).cards)
    if r < 0.8:
        n = rng.randint(1, len(group))
        return rng.sample(group, n)
    return list(group)


def test_beats_and_decompose_matching_random_parity(pure_routing):
    """10k+ randomized beats / decompose_matching comparisons."""
    rng = random.Random(20260803)
    deck = make_deck()
    pure_beats = legal.beats
    pure_match = combos.decompose_matching
    checked_beats = checked_match = 0
    while checked_beats < 10_000 or checked_match < 10_000:
        suit, rank = CONFIGS[rng.randrange(len(CONFIGS))]
        op, of = Ordering(suit, rank), Ordering(suit, rank)
        hand = rng.sample(deck, rng.randint(4, 25))
        groups = list(_suit_groups(hand, op).values())
        lead_group = rng.choice(groups)
        lead = _random_lead(rng, lead_group)
        shape = combos._decompose_uncached(lead, op).shape()
        inc_suit = legal.uniform_suit(lead, op)
        inc_top = (combos._decompose_uncached(lead, op).top_level()
                   if rng.random() < 0.7 else rng.randrange(16))
        # challengers: same-length random (mixed suits), a same-length
        # same-suit group slice, and an all-trump slice when available.
        challengers = [rng.sample(deck, len(lead))]
        other = rng.sample(deck, rng.randint(len(lead), 30))
        for g in _suit_groups(other, op).values():
            if len(g) >= len(lead):
                challengers.append(rng.sample(g, len(lead)))
        for ch in challengers:
            assert (fast.beats(ch, lead, inc_suit, inc_top, of)
                    == pure_beats(ch, lead, inc_suit, inc_top, op)), (
                ch, lead, inc_suit, inc_top, suit, rank)
            checked_beats += 1
            got = fast.decompose_matching(ch, of, shape)
            ref = pure_match(ch, op, shape)
            assert got == ref, (ch, shape, suit, rank)
            checked_match += 1
        # random shapes against the lead group itself
        rand_shape = (tuple(sorted((rng.randint(1, 3)
                                    for _ in range(rng.randint(0, 2))),
                            reverse=True)), rng.randint(0, 4))
        assert (fast.decompose_matching(lead_group, of, rand_shape)
                == pure_match(lead_group, op, rand_shape)), (
            lead_group, rand_shape, suit, rank)
        checked_match += 1
    assert checked_beats >= 10_000 and checked_match >= 10_000


def test_beats_equal_level_trump_rank_edges(pure_routing):
    """Randomized sweep of the order-sensitive class: off-suit trump-rank
    pairs sharing a level (suited trump) and the 4-codes-one-level no-trump
    ladder, as leads AND challengers."""
    pure_beats = legal.beats
    pure_match = combos.decompose_matching
    pool_h7 = ["HA", "HA", "S7", "S7", "D7", "D7", "C7", "C7", "H7", "H7",
               LJ, LJ, BJ, BJ]
    pool_nt = ["S7", "S7", "H7", "H7", "D7", "D7", "C7", "C7", LJ, LJ, BJ, BJ]
    rng = random.Random(99)
    for (suit, rank), pool in ((("H", "7"), pool_h7), ((None, "7"), pool_nt)):
        for trial in range(400):
            op, of = Ordering(suit, rank), Ordering(suit, rank)
            lead = rng.sample(pool, 2 * rng.randint(1, 4))
            ch = rng.sample(pool, len(lead))
            shape = combos._decompose_uncached(lead, op).shape()
            top = combos._decompose_uncached(lead, op).top_level()
            for inc in ("T", "H", "S"):
                assert (fast.beats(ch, lead, inc, top, of)
                        == pure_beats(ch, lead, inc, top, op)), (
                    ch, lead, inc, suit, rank)
            assert (fast.decompose_matching(ch, of, shape)
                    == pure_match(ch, op, shape)), (ch, lead, shape, suit)


def test_validate_follow_and_helpers_random_parity(pure_routing):
    """validate_follow / check_in_hand / uniform_suit / pair_count parity:
    same result or the same exception type AND message."""
    rng = random.Random(777)
    deck = make_deck()
    pure_vf = legal.validate_follow
    pure_cih = legal.check_in_hand
    pure_us = legal.uniform_suit
    pure_pc = combos.pair_count
    for i in range(4000):
        suit, rank = CONFIGS[i % len(CONFIGS)]
        op, of = Ordering(suit, rank), Ordering(suit, rank)
        hand = rng.sample(deck, rng.randint(2, 20))
        lead_hand = rng.sample(deck, rng.randint(1, 12))
        lead_group = rng.choice(list(_suit_groups(lead_hand, op).values()))
        lead = _random_lead(rng, lead_group)
        if rng.random() < 0.1:  # occasionally a non-uniform lead (assert path)
            lead = rng.sample(deck, rng.randint(2, 4))
        # plays: in-hand subsets (right and wrong sizes), suit-following
        # subsets, and not-in-hand plays
        plays = []
        if len(hand) >= len(lead):
            plays.append(rng.sample(hand, len(lead)))
        in_suit = [c for c in hand
                   if op.eff_suit(c) == op.eff_suit(lead[0])]
        if len(in_suit) >= len(lead):
            plays.append(rng.sample(in_suit, len(lead)))
        plays.append(rng.sample(hand, rng.randint(1, len(hand))))
        plays.append(rng.sample(deck, len(lead)))  # may not be held
        if rng.random() < 0.05:
            plays.append([])
        for play in plays:
            assert (_outcome(fast.validate_follow, play, hand, lead, of)
                    == _outcome(pure_vf, play, hand, lead, op)), (
                play, hand, lead, suit, rank)
            assert (_outcome(fast.check_in_hand, hand, play)
                    == _outcome(pure_cih, hand, play)), (hand, play)
            assert fast.uniform_suit(play, of) == pure_us(play, op)
            assert fast.pair_count(play) == pure_pc(play)
