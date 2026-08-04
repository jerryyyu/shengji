"""Bounded action-semantics gate: is play identity independent of LIST ORDER?

Codex reported that `decompose()` keeps an input-order dependence for
tied-level trump pairs, while ballot dedupe keys on a sorted multiset — so the
generator and the engine could disagree about which action was played. I could
not reproduce it from the description across two attempts, and rather than
"fix" something I cannot demonstrate, the BACKLOG gate allows the other
resolution: close it with a committed exhaustive property test.

Under trump suit H and trump rank 7, the off-suit rank cards S7, D7 and C7 all
sit at effective level 12 — genuinely tied, distinct physical codes, two copies
each. That is the exact configuration the claim is about, and it is small
enough to enumerate rather than sample.

For every multiset drawn from that space, this asserts that permuting the LIST
changes nothing an action's identity depends on:

  * the decomposition's shape,
  * the decomposition's PHYSICAL split (not merely its shape — two orderings
    could agree on `((1,), 0)` while disagreeing about which pair was kept),
  * legality as a lead, and the cards the engine records as played,
  * the successor hand.

`decompose()` caches on `Ordering._dcache`, now keyed by the sorted multiset,
so each case is also run against a FRESH `Ordering`. An earlier version of
this file cleared module globals named `_DECOMP_CACHE`/`_decomp_cache`/`_CACHE`,
none of which exist — so the "cold cache" test was a no-op (Codex).

Sizes 2-4 were invariant even before the fix, which is exactly why my first
closure was wrong: exposing the defect needs SIX cards, so two tied-level pairs
can compete for the adjacent pair. Codex supplied that witness and it is the
last test in this file.
"""
from __future__ import annotations

import itertools
import random

import pytest

from shengji.engine.cards import Ordering
from shengji.engine.combos import decompose, find_tractor_runs
from shengji.engine.legal import validate_lead
from shengji.engine.round import Round, Trick

#: trump suit H, trump rank 7 => S7/D7/C7 tie at level 12; H7 is above them;
#: H8/H9 are ordinary trumps that can form runs with each other.
O = Ordering("H", "7")
POOL = ["S7", "S7", "D7", "D7", "C7", "C7", "H7", "H7", "H8", "H8", "H9", "H9"]


def _split(dec):
    """The physical cards each component holds, order-normalised.

    Comparing only `shape()` would let two orderings agree on ((1,), 0) while
    disagreeing about WHICH pair survived — precisely the distinction that
    makes S7 and D7 different actions from a hand of S7-S7-D7.
    """
    out = tuple(sorted(tuple(sorted(c.cards)) for c in dec.components))
    # A `getattr(c, "cards", ())` here would silently return empty tuples if
    # the attribute were ever renamed, making every comparison trivially equal
    # — the vacuous-test failure mode that has bitten this repo three times.
    assert out and all(cs for cs in out), "split extraction returned nothing"
    return out


def _multisets(pool, size):
    """Distinct multisets of `size`, as sorted tuples."""
    return sorted({tuple(sorted(c)) for c in itertools.combinations(pool, size)})


@pytest.mark.parametrize("size", [2, 3, 4, 6])
def test_decomposition_is_permutation_invariant(size):
    """Shape AND physical split must not depend on list order."""
    checked = multisets = reorderable = 0
    for ms in _multisets(POOL, size):
        perms = sorted({p for p in itertools.permutations(ms)})
        reorderable += len(perms) > 1
        base = decompose(list(perms[0]), O)
        base_key = (base.shape(), _split(base))
        for p in perms[1:]:
            got = decompose(list(p), O)
            assert (got.shape(), _split(got)) == base_key, (
                f"order dependence: {perms[0]} -> {base.shape()} {_split(base)} "
                f"but {p} -> {got.shape()} {_split(got)}")
            checked += 1
        multisets += 1
    # Coverage is asserted so this cannot quietly become a no-op. The bound is
    # the number of multisets that HAVE more than one ordering: a pair like
    # S7-S7 has exactly one, so it can never exercise order dependence.
    assert reorderable >= 6 and checked >= reorderable, (
        f"size {size}: {multisets} multisets, {reorderable} with multiple "
        f"orderings, {checked} comparisons — the space collapsed and this "
        f"test is not exercising anything")


@pytest.mark.parametrize("size", [2, 3, 4, 6])
def test_decomposition_is_invariant_on_a_cold_cache(size):
    """A shared warm cache must not be able to hide order dependence."""
    for ms in _multisets(POOL, size):
        results = set()
        for p in sorted({p for p in itertools.permutations(ms)}):
            # A FRESH Ordering is the cold cache: decompose memoises on
            # `Ordering._dcache`, so clearing module globals cleared nothing.
            dec = decompose(list(p), Ordering("H", "7"))
            results.add((dec.shape(), _split(dec)))
        assert len(results) == 1, (
            f"{ms} decomposes differently across orderings on a cold cache: "
            f"{results}")


@pytest.mark.parametrize("size", [2, 3, 4, 6])
def test_lead_legality_and_recorded_play_are_permutation_invariant(size):
    """The ENGINE must not interpret two orderings of one multiset differently.

    This is the half that actually matters for the ballot: dedupe keys on a
    sorted multiset, so if the engine can read two orderings differently, the
    generator and the engine disagree about which action was played.
    """
    others = [["S8", "S9"], ["D8", "D9"], ["C8", "C9"]]
    for ms in _multisets(POOL, size):
        hand = list(ms) + ["S8"]          # a spare so the hand is never empty
        outcomes = set()
        for p in sorted({p for p in itertools.permutations(ms)}):
            try:
                played, msg = validate_lead(list(p), hand, others, O)
                outcomes.add((tuple(sorted(played)), bool(msg)))
            except Exception as exc:
                outcomes.add((type(exc).__name__,))
        assert len(outcomes) == 1, (
            f"{ms}: the engine records different plays for different orderings "
            f"of the same multiset: {outcomes}")


def _failed_throw_round() -> Round:
    """Minimal live Round that forces the witness throw's lowest component."""
    rnd = Round("7", 0, random.Random(1))
    rnd.phase = "play"
    rnd.turn = 0
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.ordering = Ordering("H", "7")
    rnd.hands = [
        ["C7", "C7", "D7", "D7", "H7", "H7", "S8"],
        ["LJ", "LJ"],  # beats the residual level-12 pair, so the throw fails
        ["C8"],
        ["D8"],
    ]
    rnd.kitty = []
    rnd.buried = []
    rnd.history = []
    rnd.trick = Trick(leader=0)
    return rnd


def test_round_play_successor_is_permutation_invariant():
    """Exercise the real engine transition, including failed-throw coercion.

    The old "successor" test only removed each submitted card from a Python
    list.  That arithmetic is necessarily permutation-invariant and never
    called the engine path whose decomposition had been defective.
    """
    ms = ("C7", "C7", "D7", "D7", "H7", "H7")
    outcomes = set()
    for p in sorted({q for q in itertools.permutations(ms)}):
        rnd = _failed_throw_round()
        rnd.play(0, list(p))
        outcomes.add((
            tuple(rnd.trick.plays[0].cards),
            tuple(sorted(rnd.hands[0])),
            rnd.message,
        ))
    assert outcomes == {(
        ("D7", "D7"),
        ("C7", "C7", "H7", "H7", "S8"),
        "Throw failed — forced to play D7+D7",
    )}


def test_six_card_tied_level_tractor_is_permutation_invariant():
    """Codex's minimal witness. FIXED 2026-08-04; was xfail-strict until then.

        C7 C7 D7 D7 H7 H7  ->  tractor C7C7H7H7 + pair D7D7
        D7 C7 C7 D7 H7 H7  ->  tractor D7D7H7H7 + pair C7C7

    Same multiset, same shape ((2,1),0), different PHYSICAL split. The ballot
    dedupes on a sorted multiset, so the generator and the engine can disagree
    about which action was played.

    Both kernels now sort their input at entry, so the whole decomposition is a
    function of the multiset. Canonicalising only the tied-level pair choice was
    not enough: `singles` ordering and component tie-breaking also inherit list
    order, and pure and fast inherited it differently at the steps that were
    missed, which broke eight parity tests.
    """
    ms = ("C7", "C7", "D7", "D7", "H7", "H7")
    splits = set()
    for p in sorted({q for q in itertools.permutations(ms)}):
        dec = decompose(list(p), Ordering("H", "7"))
        splits.add((dec.shape(), _split(dec)))
    assert len(splits) == 1, (
        f"{len(splits)} distinct decompositions of one multiset: {splits}")


def test_tied_level_codes_are_not_collapsed_by_the_ballot():
    """The half of the P0 that WAS a real bug, kept as a regression.

    S7 and D7 tie at level 12, but from S7-S7-D7 leading S7 breaks the pair
    while leading D7 keeps it. V3 keyed equivalence on level alone and dropped
    one of them.
    """
    from shengji.ai.mcbot import MCBot

    assert O.level("S7") == O.level("D7"), "precondition: these tie"
    for keep, drop in (("S7", "D7"), ("D7", "S7")):
        rest = list({"S7": ["S7", "D7"], "D7": ["S7", "S7"]}[keep])
        assert decompose(rest, O).shape() != decompose(
            list({"S7": ["S7", "S7"], "D7": ["S7", "D7"]}[keep]), O).shape() \
            or keep == drop, "leading a tied code changes the residual shape"

    bot = MCBot(seed=1)
    bot.V3_LEAD_SINGLES = True
    from shengji.engine.ballot import mc_ballot
    assert mc_ballot(bot).digest != mc_ballot(MCBot(seed=1)).digest


def test_all_tied_code_tractors_are_enumerated():
    """`find_tractor_runs` promises ALL k-tractors; it returned one per level.

    From C7-C7-D7-D7-H7-H7 it offered only C7C7+H7H7, never D7D7+H7H7. Those
    are different lead actions leaving different residual hands, so the ballot
    was missing a real candidate. Canonicalising the choice made it
    deterministic WITHOUT making it complete, which is worse than the order
    bug it replaced because it reads as resolved (Codex, 2026-08-04).
    """
    hand = ["C7", "C7", "D7", "D7", "H7", "H7"]
    runs = [sorted(r) for r in find_tractor_runs(hand, O, 2)]
    assert sorted(["C7", "C7", "H7", "H7"]) in runs
    assert sorted(["D7", "D7", "H7", "H7"]) in runs, \
        "the tied-code alternative is a distinct lead action, not a duplicate"

    # and they really are distinct actions: different residual hands
    residuals = set()
    for r in find_tractor_runs(hand, O, 2):
        left = list(hand)
        for c in r:
            left.remove(c)
        residuals.add(tuple(sorted(left)))
    assert len(residuals) == 2, f"expected two distinct successors, got {residuals}"


def test_tractor_enumeration_is_permutation_invariant():
    """Complete AND canonical: same multiset, same list, any input order."""
    ms = ("C7", "C7", "D7", "D7", "H7", "H7")
    seen = {tuple(tuple(sorted(r)) for r in find_tractor_runs(list(p), O, 2))
            for p in sorted({q for q in itertools.permutations(ms)})}
    assert len(seen) == 1, f"enumeration depends on input order: {seen}"


def test_pure_and_fast_agree_on_PHYSICAL_cards_not_just_shape():
    """Shape parity would pass while the engines picked different cards.

    Codex asked for physical-card parity explicitly, because two engines can
    agree that a play is a 2-tractor while disagreeing about WHICH pair it
    consumed — and that changes the successor hand.
    """
    from shengji.engine import combos as pure
    from shengji.engine import fast

    hands = [
        ["C7", "C7", "D7", "D7", "H7", "H7"],
        ["S7", "S7", "D7", "D7", "H7", "H7", "H8", "H8"],
        ["C7", "C7", "D7", "D7", "S7", "S7", "H7", "H7"],
        ["H8", "H8", "H9", "H9", "H10", "H10"],
    ]
    was_active = bool(fast._saved)
    try:
        for hand in hands:
            fast.deactivate()
            o_pure = Ordering("H", "7")
            p_dec = pure._decompose_uncached(list(hand), o_pure)
            p_run = pure._find_tractor_runs_uncached(list(hand), o_pure, 2)
            fast.activate()
            o_fast = Ordering("H", "7")
            f_dec = pure._decompose_uncached(list(hand), o_fast)
            f_run = pure._find_tractor_runs_uncached(list(hand), o_fast, 2)
            assert _split(p_dec) == _split(f_dec), (
                f"{hand}: engines split differently — pure {_split(p_dec)} "
                f"vs fast {_split(f_dec)}")
            assert [sorted(r) for r in p_run] == [sorted(r) for r in f_run], (
                f"{hand}: engines enumerate different PHYSICAL tractors — "
                f"pure {p_run} vs fast {f_run}")
    finally:
        if was_active:
            fast.activate()
        else:
            fast.deactivate()
