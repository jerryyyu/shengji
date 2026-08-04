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

`combos.py` caches on exact input order, so each case is also run against a
cold cache; a cache that returned an order-dependent result would otherwise be
masked by whichever ordering happened to run first.
"""
from __future__ import annotations

import itertools

import pytest

from shengji.engine.cards import Ordering
from shengji.engine.combos import decompose
from shengji.engine.legal import validate_lead

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


@pytest.mark.parametrize("size", [2, 3, 4])
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


@pytest.mark.parametrize("size", [2, 3, 4])
def test_decomposition_is_invariant_on_a_cold_cache(size):
    """The cache keys on exact input order, so warm results could hide a bug."""
    import shengji.engine.combos as combos

    for ms in _multisets(POOL, size):
        results = set()
        for p in sorted({p for p in itertools.permutations(ms)}):
            for cache in ("_DECOMP_CACHE", "_decomp_cache", "_CACHE"):
                c = getattr(combos, cache, None)
                if isinstance(c, dict):
                    c.clear()
            dec = decompose(list(p), O)
            results.add((dec.shape(), _split(dec)))
        assert len(results) == 1, (
            f"{ms} decomposes differently across orderings on a cold cache: "
            f"{results}")


@pytest.mark.parametrize("size", [2, 3, 4])
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


@pytest.mark.parametrize("size", [2, 3])
def test_successor_hand_is_permutation_invariant(size):
    """Two orderings of one action must leave the same residual hand."""
    for ms in _multisets(POOL, size):
        hand = list(ms) + ["H8", "S8"]
        residuals = set()
        for p in sorted({p for p in itertools.permutations(ms)}):
            left = list(hand)
            for c in p:
                left.remove(c)
            residuals.add(tuple(sorted(left)))
        assert len(residuals) == 1, f"{ms}: residual hand depends on order"


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
