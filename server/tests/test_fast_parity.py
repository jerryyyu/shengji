"""Cython fast-path vs pure-Python parity (PERF.md #2+#3 prototype).

Extends the test_engine_parity.py pattern: the compiled kernels in
shengji/engine/_fast must reproduce combos._decompose_uncached and
combos._find_tractor_runs_uncached byte-identically — including physical card
codes and canonical enumeration order. Pure Python stays the reference.

Skipped when the extension isn't built:
    cd server && uv run python setup.py build_ext --inplace
"""

import itertools
import random
import sys
from collections import Counter

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
            # Fresh Ordering => fresh memo per hand.
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


def test_multiset_memo_contract_fast_route():
    """The memo contract, REPLACED 2026-08-04 and enforced on the compiled route.

    It used to be that keys were the caller's EXACT order, because the greedy
    split resolved tied-level pairs by input order and a sorted key would have
    collapsed genuinely different results onto one entry. Codex's witness
    showed that order dependence was itself the defect, not something to
    preserve: `C7 C7 D7 D7 H7 H7` and `D7 C7 C7 D7 H7 H7` gave the same shape
    with different physical splits.

    Both kernels now canonicalise their input, so the contract is stronger:
    anagram inputs return the SAME decomposition, the key is the multiset, and
    a cache hit can no longer hand back a different split than a fresh
    computation would.
    """
    was_active = bool(fast._saved)
    fast.activate()
    try:
        o = Ordering("H", "7")
        c1 = ["S7", "S7", "D7", "D7"]
        c2 = ["D7", "D7", "S7", "S7"]
        combos.decompose(c2, o)  # prime with the other order
        assert combos.decompose(c1, o) == combos._decompose_uncached(c1, o)
        assert combos.decompose(c2, o) == combos._decompose_uncached(c2, o)
        assert combos.decompose(c1, o) == combos.decompose(c2, o), \
            "anagrams must decompose identically"

        # the six-card case that reopened the gate
        w1 = ["C7", "C7", "D7", "D7", "H7", "H7"]
        w2 = ["D7", "C7", "C7", "D7", "H7", "H7"]
        d1, d2 = combos.decompose(w1, o), combos.decompose(w2, o)
        assert [sorted(c.cards) for c in d1.components] == \
               [sorted(c.cards) for c in d2.components], \
            "the Codex witness must not split differently by input order"

        t1 = ["HA", "HA", "S7", "S7", "D7", "D7"]
        t2 = ["HA", "HA", "D7", "D7", "S7", "S7"]
        combos.find_tractor_runs(t2, o, 2)
        assert (combos.find_tractor_runs(t1, o, 2)
                == combos._find_tractor_runs_uncached(t1, o, 2))
        assert (tuple(t1), 2) in o._trcache
        assert (tuple(t2), 2) in o._trcache
        # the fast route fills the SAME dicts the invariant audit reads
        assert tuple(sorted(c1)) in o._dcache
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


def test_points_and_policy_leaves_random_parity(pure_routing):
    """Phase 2 partial: points / total_points / HeuristicBot._lowest /
    _forced_follow parity (both VOID_DUMP settings, avoid sets, both
    prefer_points modes; leads incl. tractors/throws)."""
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.cards import points, total_points

    class _NoVoidDump(HeuristicBot):
        VOID_DUMP = False

    rng = random.Random(424242)
    deck = make_deck()
    for c in sorted(set(deck)):
        assert fast.points(c) == points(c)
    assert fast.points("XX") == 0 and fast.points("H5") == 5
    assert fast.total_points(deck) == total_points(deck) == 200
    assert fast.total_points(iter(["SK", "H10", "D5"])) == 25

    bots = [HeuristicBot(), _NoVoidDump()]
    checked = 0
    for i in range(3000):
        suit, rank = CONFIGS[i % len(CONFIGS)]
        op, of = Ordering(suit, rank), Ordering(suit, rank)
        bot = bots[i % 2]
        hand = rng.sample(deck, rng.randint(1, 25))
        avoid = (None if rng.random() < 0.4
                 else set(rng.sample(hand, rng.randint(0, len(hand) // 2))))
        for ap, sp in ((False, False), (True, False), (False, True)):
            assert (fast.heuristic_lowest(hand, of, bot.VOID_DUMP, ap, sp,
                                          avoid)
                    == bot._lowest(hand, op, avoid_points=ap, seek_points=sp,
                                   avoid=avoid)), (hand, ap, sp, avoid, suit)
            checked += 1
        # forced_follow: uniform lead from another hand's suit group
        lead_hand = rng.sample(deck, rng.randint(1, 14))
        lead_group = rng.choice(list(_suit_groups(lead_hand, op).values()))
        lead = _random_lead(rng, lead_group)
        if len(hand) < len(lead):
            continue
        for prefer in (False, True):
            got = _outcome(fast.forced_follow, hand, lead, of, bot.VOID_DUMP,
                           prefer, avoid)
            ref = _outcome(bot._forced_follow, hand, lead, op, prefer, avoid)
            assert got == ref, (hand, lead, prefer, avoid, suit, rank)
            checked += 1
    assert checked >= 10_000


def test_cheapest_winning_named_seams_and_exceptions(pure_routing):
    """Mutation-resistant witnesses for every contest branch.

    Assertions include the exact chosen physical cards, not merely whether a
    winner exists.  Equal-level trump-rank codes pin Python's stable Counter
    tie, and the throw witness reaches the intentionally retained shape
    matcher before the compiled beats check.
    """
    from shengji.ai.heuristic import HeuristicBot

    bot = HeuristicBot()
    pure = bot._cheapest_winning
    cases = [
        # label, ordering, hand, lead, incumbent suit/top, exact result
        ("single", ("H", "7"), ["S10", "SJ", "SA"], ["S9"],
         "S", 6, ["S10"]),
        ("pair", ("H", "7"), ["SJ", "SJ", "S10", "S10"],
         ["S9", "S9"], "S", 6, ["S10", "S10"]),
        ("tractor", ("H", "7"),
         ["S9", "S9", "S10", "S10", "SJ", "SJ"],
         ["S8", "S8", "S9", "S9"], "S", 6,
         ["S9", "S9", "S10", "S10"]),
        ("void-ruff", ("H", "7"), ["H2", "H3", "C4"], ["D9"],
         "D", 6, ["H2"]),
        ("partial-suit", ("H", "7"), ["S10", "H2", "H3"],
         ["S9", "S9"], "S", 6, None),
        ("already-ruffed", ("H", "7"), ["S10", "SJ", "SA"], ["S9"],
         "T", 2, None),
        ("throw-ruff", ("H", "7"), ["H2", "H2", "H3", "C4"],
         ["S3", "S3", "SA"], "S", 1, ["H2", "H2", "H3"]),
        # D7/S7 share one trump level: first Counter insertion wins the tie.
        ("equal-level-pair", ("H", "7"),
         ["D7", "D7", "S7", "S7", "D4"], ["C9", "C9"],
         "C", 6, ["D7", "D7"]),
        # In no-trump all four rank codes tie; preserve the hand's first code.
        ("no-trump-level-tie", (None, "7"), ["C7", "S7", "H3"],
         ["D9"], "D", 6, ["C7"]),
    ]
    for label, config, hand, lead, inc_suit, inc_top, expected in cases:
        op, of = Ordering(*config), Ordering(*config)
        ref = pure(list(hand), list(lead), inc_suit, inc_top, op)
        got = fast.cheapest_winning(
            bot, list(hand), list(lead), inc_suit, inc_top, of)
        assert ref == expected, (label, "fixture drift", ref)
        assert got == expected, (label, got)

    for lead in ([], ["S3", "H3"]):
        assert _outcome(pure, ["S4", "H4"], lead, "S", 0,
                        Ordering("H", "7")) == ("AssertionError",)
        assert _outcome(fast.cheapest_winning, bot, ["S4", "H4"], lead,
                        "S", 0, Ordering("H", "7")) == ("AssertionError",)


def test_cheapest_winning_random_and_shape_weighted_parity(pure_routing):
    """30k differential calls with deliberate single/pair/tractor/throw dose.

    Random sampling alone almost never produces a pure tractor; half this
    test therefore draws actual components/runs from duplicate-rich suit
    groups.  Separate Ordering objects prevent shared caches from masking a
    divergence.  The output list (including order/physical tied-level code),
    None, or exception is compared exactly.
    """
    from shengji.ai.heuristic import HeuristicBot

    rng = random.Random(20260813)
    deck = make_deck()
    bot = HeuristicBot()
    pure = bot._cheapest_winning
    seen = {"single": 0, "pair": 0, "tractor": 0, "throw": 0,
            "trump_incumbent": 0, "partial_suit": 0,
            "winning_result": 0}
    for i in range(30_000):
        config = CONFIGS[i % len(CONFIGS)]
        op, of = Ordering(*config), Ordering(*config)
        source = rng.sample(deck, rng.randint(4, 28))
        groups = list(_suit_groups(source, op).values())
        group = rng.choice(groups)

        mode = i % 5
        if mode == 0:
            lead = [rng.choice(group)]
        elif mode == 1:
            pair_codes = [c for c, n in Counter(group).items() if n >= 2]
            lead = ([rng.choice(pair_codes)] * 2 if pair_codes
                    else [rng.choice(group)])
        elif mode == 2:
            # Draw from a duplicate-complete effective-suit group: ordinary
            # random hands almost never contain even a 2-pair tractor.
            runs = []
            complete_group = rng.choice(list(_suit_groups(deck, op).values()))
            for k in (2, 3, 4):
                runs.extend(combos.find_tractor_runs(complete_group, op, k))
            lead = list(rng.choice(runs))
        else:
            lead = _random_lead(rng, group)

        dec = combos.decompose(lead, op)
        kind = (dec.components[0].kind
                if len(dec.components) == 1 else "throw")
        seen[kind] += 1
        hand = rng.sample(deck, rng.randint(1, 33))
        lead_suit = legal.uniform_suit(lead, op)
        assert lead_suit is not None
        incumbent_suit = rng.choice(
            [lead_suit, TRUMP, rng.choice(["S", "H", "C", "D"])])
        incumbent_top = rng.randint(-1, 15)
        if incumbent_suit == TRUMP:
            seen["trump_incumbent"] += 1
        led_count = len(legal.suit_cards(hand, lead_suit, op))
        if 0 < led_count < len(lead):
            seen["partial_suit"] += 1

        ref = _outcome(pure, list(hand), list(lead), incumbent_suit,
                       incumbent_top, op)
        got = _outcome(fast.cheapest_winning, bot, list(hand), list(lead),
                       incumbent_suit, incumbent_top, of)
        assert got == ref, (i, config, hand, lead, incumbent_suit,
                            incumbent_top, kind, ref, got)
        if isinstance(ref, list):
            seen["winning_result"] += 1

    assert seen["single"] >= 8_000, seen
    assert seen["pair"] >= 500, seen
    assert seen["tractor"] >= 100, seen
    assert seen["throw"] >= 4_000, seen
    assert seen["trump_incumbent"] >= 8_000, seen
    assert seen["partial_suit"] >= 500, seen
    assert seen["winning_result"] >= 3_000, seen


def test_cheapest_winning_route_is_observable(monkeypatch):
    """Falsification probe: activation must really dispatch to this kernel.

    If the method-router entry is removed, the sentinel can no longer be
    observed and this test turns red instead of letting randomized parity
    compare the unmodified pure method to itself.
    """
    from shengji.ai.heuristic import HeuristicBot

    was_active = bool(fast._saved)
    try:
        fast.deactivate()
        original = fast._fast.cheapest_winning
        monkeypatch.setattr(fast._fast, "cheapest_winning",
                            lambda *args: ["ROUTE-SENTINEL"])
        fast.activate()
        assert HeuristicBot()._cheapest_winning(
            ["S4"], ["S3"], "S", 0, Ordering("H", "7")) == \
            ["ROUTE-SENTINEL"]
        monkeypatch.setattr(fast._fast, "cheapest_winning", original)
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()


def test_cheapest_winning_public_out_of_domain_falls_back_with_parity(
        pure_routing):
    """C narrowing is restricted to the exact engine-produced top domain."""
    from shengji.ai.heuristic import HeuristicBot

    bot = HeuristicBot()
    pure = bot._cheapest_winning
    cases = [
        -10**100,
        10**100,
        -2,
        16,
        1.25,
        True,
        "0",
    ]
    def public_outcome(fn, *args):
        try:
            return ("return", fn(*args))
        except Exception as exc:
            return (type(exc).__name__, str(exc))

    expected = []
    for incumbent_top in cases:
        expected.append(public_outcome(
            pure, ["S4"], ["S3"], "S", incumbent_top, Ordering("H", "7")))

    # Restore routing only for the public-method calls under test.
    fast.activate()
    try:
        got = [public_outcome(
            HeuristicBot()._cheapest_winning,
            ["S4"], ["S3"], "S", incumbent_top, Ordering("H", "7"))
               for incumbent_top in cases]
        assert got == expected
    finally:
        fast.deactivate()


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


# ---------------------------------------------------------------------------
# 2026-08-03 validation pass (deep-correctness audit before trusting the fast
# path for training-data generation). The tests above compare the compiled
# kernels to their pure twins in isolation; these compare the ROUTED SYSTEM —
# what generation, duels and the engine actually observe — by running the
# same work with routing off (reference) and on, always on FRESH Ordering
# instances so a shared memo can never mask a divergence.
# ---------------------------------------------------------------------------


def _both_modes(fn):
    """Run ``fn()`` with routing off then on; returns (pure, fast).

    Restores suite-wide activation (SHENGJI_FAST=1) afterwards.
    """
    was_active = bool(fast._saved)
    try:
        fast.deactivate()
        pure = fn()
        fast.activate()
        got = fn()
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()
    return pure, got


def _lead_outcome(play, hand, others, config):
    """validate_lead through whatever routing is live, on a FRESH Ordering."""
    from shengji.engine.legal import validate_lead
    o = Ordering(*config)
    try:
        return ("ok", validate_lead(list(play), list(hand),
                                    [list(h) for h in others], o))
    except legal.IllegalPlay as e:
        return ("IllegalPlay", str(e))
    except AssertionError:
        return ("AssertionError",)


def test_validate_lead_throw_penalty_parity():
    """The 08-03 throw rule (forfeit the LOWEST beatable component) is pure
    Python but reads decompose / find_tractor_runs / suit_cards / level —
    all routed. Constructed multi-component throws where SEVERAL components
    are beatable, so the tie-break itself is observable, plus random deals.
    """
    rng = random.Random(24)
    deck = make_deck()
    fired = checked = 0
    for i in range(400):
        cfg = CONFIGS[i % len(CONFIGS)]
        o0 = Ordering(*cfg)
        eff = ("S", "H", "D", "C", TRUMP)[i % 5]
        pool = [c for c in deck if o0.eff_suit(c) == eff]
        codes = sorted(set(pool), key=o0.level)
        if len(codes) < 6:
            continue
        lo, hi = codes[:len(codes) // 2], codes[len(codes) // 2:]
        picks = rng.sample(lo, rng.randint(2, min(4, len(lo))))
        play = [c for c in picks for _ in (0, 1)]
        if rng.random() < 0.7:                    # + a high single (the ace)
            play.append(rng.choice(hi[:max(1, len(hi) - 1)]))
        rng.shuffle(play)
        off = [c for c in deck if o0.eff_suit(c) != eff]
        hand = list(play) + rng.sample(off, 5)
        beaters = rng.sample(hi, min(len(hi), rng.randint(1, 4)))
        others = [[c for c in beaters for _ in (0, 1)],
                  rng.sample(off, 4),
                  rng.sample(pool, min(4, len(pool)))]
        pure, got = _both_modes(
            lambda: _lead_outcome(play, hand, others, cfg))
        assert pure == got, (play, hand, others, cfg)
        checked += 1
        if pure[0] == "ok" and pure[1][1]:
            fired += 1
    # random full deals: the shapes real leads actually take
    for i in range(200):
        cfg = CONFIGS[i % len(CONFIGS)]
        o0 = Ordering(*cfg)
        rng.shuffle(deck)
        hands = [deck[s * 25:(s + 1) * 25] for s in range(4)]
        hand, others = hands[0], hands[1:]
        groups = {}
        for c in hand:
            groups.setdefault(o0.eff_suit(c), []).append(c)
        g = rng.choice(list(groups.values()))
        for play in (list(g), rng.sample(g, rng.randint(1, len(g)))):
            pure, got = _both_modes(
                lambda: _lead_outcome(play, hand, others, cfg))
            assert pure == got, (play, hand, others, cfg)
            checked += 1
            if pure[0] == "ok" and pure[1][1]:
                fired += 1
    assert checked >= 700
    assert fired >= 100, f"throw penalty never fired ({fired}) — test is blind"


def test_points_tolerant_and_iterable_parity():
    """points/total_points are table lookups now: every deck code, codes
    OUTSIDE the table (pure is tolerant — the fallback must match), and the
    non-list iterables total_points is called with (genexpr in _resolve_trick).
    """
    from shengji.engine import cards as cards_mod
    deck = make_deck()
    exotic = ["XX", "S1", "H100", "?", "Z5", "QK", "A10"]

    def probe():
        pts = [cards_mod.points(c) for c in sorted(set(deck))]
        ex = [cards_mod.points(c) for c in exotic]
        return (pts, ex,
                cards_mod.total_points(deck),
                cards_mod.total_points(tuple(deck)),
                cards_mod.total_points(iter(deck)),
                cards_mod.total_points(c for c in deck),
                cards_mod.total_points([]),
                cards_mod.total_points(iter(["SK", "H10", "D5"])))

    pure, got = _both_modes(probe)
    assert pure == got
    assert pure[2] == 200


def test_pure_fast_interleave_cannot_corrupt_shared_caches():
    """One Ordering, alternating pure/fast calls, anagram inputs whose split
    is order-dependent (equal-level trump-rank pairs). Every result must
    equal a fresh uncached reference, and the handed-back tractor runs must
    stay defensive copies across the mode switch (the 08-02 aliasing bug
    class, now with two writers into one cache)."""
    was_active = bool(fast._saved)
    variants = [
        ["S7", "S7", "D7", "D7"], ["D7", "D7", "S7", "S7"],
        ["S7", "D7", "S7", "D7"], ["HA", "HA", "S7", "S7", "D7", "D7"],
        ["HA", "HA", "D7", "D7", "S7", "S7"], [LJ, LJ, BJ, BJ, "S7", "S7"],
    ]
    try:
        for cfg in (("H", "7"), (None, "7"), ("S", "2")):
            for modes in itertools.product((False, True), repeat=3):
                o = Ordering(*cfg)          # ONE shared Ordering
                for pas in (modes, tuple(not m for m in modes)):
                    for i, cards in enumerate(variants):
                        if pas[i % 3]:
                            fast.activate()
                        else:
                            fast.deactivate()
                        ref_o = Ordering(*cfg)
                        assert (combos.decompose(list(cards), o)
                                == combos._decompose_uncached(list(cards),
                                                              ref_o))
                        for k in (1, 2, 3):
                            runs = combos.find_tractor_runs(list(cards), o, k)
                            assert runs == combos._find_tractor_runs_uncached(
                                list(cards), Ordering(*cfg), k), (cards, k, cfg)
                            for r in runs:   # poison attempt on the cache
                                r.append("ZZ")
                # the ctx must still point at the very dicts pure Python uses
                fast.activate()
                combos.decompose(["S7", "S7"], o)
                ctx = o._fast_ctx
                assert ctx[0] is o._dcache and ctx[1] is o._trcache
                fast.deactivate()
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()


def test_generation_recording_parity():
    """THE generation gate: distill_generate records VALUES, not just plays.

    Runs RecordingMCBot self-play both ways on the same seed and requires
    bit-identical observations, candidate action encodings (same set AND
    order), chosen index, and EXACT-equal per-candidate search values. A
    play-history-only check cannot see a value drift; a drifted value set
    poisons the distillation targets silently.

    N_DETERMINIZATIONS is dialled down for suite runtime; the wide ballots,
    DECLARER_PIN and TRACTOR_LOCK paths (all fresh code) are the production
    ones. The full-config sweep (N=30, 50 rounds) lives in the 08-03
    validation run.
    """
    import random as _random

    from shengji.ai.env import play_round
    from shengji.engine.game import Game
    from shengji.rl.distill_generate import RecordingMCBot

    def run(seed):
        bot = RecordingMCBot(seed=seed)
        bot.N_DETERMINIZATIONS = 3
        assert bot.WIDE_LEAD_BALLOT and bot.WIDE_FOLLOW_BALLOT
        assert bot.DECLARER_PIN and bot.TRACTOR_LOCK
        bot.decisions = []
        game = Game(_random.Random(seed))
        log = play_round(game, [bot] * 4, record=True)
        return (log.history, log.attacker_points, log.level_change,
                [(d.seat, d.chosen, d.obs, d.actions, d.action_values)
                 for d in bot.decisions])

    for seed in (3, 11):
        pure, got = _both_modes(lambda: run(seed))
        assert pure[0] == got[0], f"seed {seed}: play history diverged"
        assert pure[1:3] == got[1:3], f"seed {seed}: round result diverged"
        pd, gd = pure[3], got[3]
        assert len(pd) == len(gd), f"seed {seed}: decision count"
        for i, (a, b) in enumerate(zip(pd, gd)):
            assert a[0] == b[0], (seed, i, "seat")
            assert a[2] == b[2], (seed, i, "observation")
            assert a[3] == b[3], (seed, i, "candidate action encodings")
            assert a[1] == b[1], (seed, i, "chosen index")
            assert a[4] == b[4], (seed, i, "per-candidate search values")
        assert len(pd) > 20, f"seed {seed}: only {len(pd)} decisions recorded"


def test_activate_routes_everything_and_deactivate_restores():
    """Meta-guard for every differential test in this file: if deactivate()
    leaked even one compiled binding, the 'pure' reference would silently BE
    the fast path and the whole suite would compare fast against fast. Also
    pins the reverse — activate() must reach ``from x import y`` aliases in
    ai/ and rl/, not just the engine module attributes."""
    import importlib
    import types

    tracked = []
    for modname, attrs in (
            ("shengji.engine.combos", ("decompose", "find_tractor_runs",
                                       "decompose_matching", "pair_count")),
            ("shengji.engine.legal", ("suit_cards", "beats", "uniform_suit",
                                      "check_in_hand", "validate_follow")),
            ("shengji.engine.cards", ("points", "total_points")),
            ("shengji.engine.round", ("decompose", "beats", "validate_follow",
                                      "check_in_hand", "uniform_suit",
                                      "total_points")),
            ("shengji.ai.heuristic", ("decompose", "beats", "suit_cards",
                                      "find_tractor_runs", "points")),
            ("shengji.ai.mcbot", ("decompose", "suit_cards",
                                  "validate_follow")),
            ("shengji.ai.smart", ("decompose", "suit_cards")),
            ("shengji.rl.encode", ("decompose",)),
            ("shengji.rl.actions", ("suit_cards", "find_tractor_runs")),
    ):
        mod = importlib.import_module(modname)
        for a in attrs:
            tracked.append((mod, a))

    def compiled(fn):
        return getattr(fn, "__module__", "") == "shengji.engine._fast"

    was_active = bool(fast._saved)
    try:
        from shengji.ai.heuristic import HeuristicBot
        fast.deactivate()
        before = {(m.__name__, a): getattr(m, a) for m, a in tracked}
        assert not any(compiled(v) for v in before.values())
        pure_methods = {a: getattr(HeuristicBot, a)
                        for a in ("_lowest", "_forced_follow", "_lead",
                                  "_follow", "_cheapest_winning",
                                  "decide_play")}
        from shengji.engine.round import Round as _Round
        pure_round_play = _Round.play

        fast.activate()
        unrouted = [k for (m, a), k in
                    ((t, (t[0].__name__, t[1])) for t in tracked)
                    if not compiled(getattr(m, a))]
        assert not unrouted, f"activate() missed: {unrouted}"
        assert HeuristicBot._lowest is fast._fast.heuristic_lowest_m
        assert HeuristicBot._forced_follow is \
            fast._fast.heuristic_forced_follow
        assert HeuristicBot._lead is fast._fast.heuristic_lead
        assert HeuristicBot._follow is fast._fast.heuristic_follow
        assert HeuristicBot.decide_play is fast._fast.heuristic_decide_play
        from shengji.engine.round import Round
        assert Round.play is fast._fast.round_play
        assert HeuristicBot._cheapest_winning is \
            fast._fast.heuristic_cheapest_winning
        # a name bound AFTER activation must see the compiled function too
        late = types.ModuleType("late_import_probe")
        exec("from shengji.engine.legal import beats", late.__dict__)
        assert compiled(late.beats)

        fast.deactivate()
        leaked = [k for (m, a) in tracked
                  for k in [(m.__name__, a)] if getattr(m, a) is not before[k]]
        assert not leaked, f"deactivate() did not restore: {leaked}"
        for a, fn in pure_methods.items():
            assert getattr(HeuristicBot, a) is fn, f"method leak: {a}"
        assert _Round.play is pure_round_play, "Round.play leak"
    finally:
        fast.deactivate()
        if was_active:
            fast.activate()
