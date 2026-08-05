"""Arm invariants. A pilot comparing arms that differ in an unintended way
measures that difference instead of the one it claims to.
"""
from __future__ import annotations

import itertools
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.engine.legal import validate_lead
from shengji.pilot_arms import (ARMS, archetype, propose, protected,
                                structured_universe)

BUDGET = 14


def _lead_states(n=6, seed0=772000):
    out = []
    for k in range(n):
        game = Game(random.Random(seed0 + k))
        bots = [make_bot("smart") for _ in range(4)]
        rnd = game.start_round()
        while rnd.phase == "deal":
            s, _, _ = rnd.deal_next()
            cs = bots[s].decide_declare(rnd, s)
            if cs:
                rnd.declare(s, cs)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if not rnd.trick.plays and len(rnd.history) >= 2:
                out.append((rnd, s))
                break
            rnd.play(s, bots[s].decide_play(rnd, s))
    return out


def _all(bot, rnd, seat):
    return {a: propose(a, bot, rnd, seat, budget=BUDGET, seed=7,
                       state_key="k") for a in ARMS}


def test_every_proposed_action_is_a_legal_ATTEMPTED_lead():
    """Attempt-validity, not success.

    Whether a throw is beaten depends on HIDDEN cards, so requiring `not msg`
    made the ballot a function of the deal — the defect Codex found. A proposer
    may legitimately offer a throw that turns out to be beaten; the rollouts
    price that. What must hold is that the seat owns the cards and the play is
    a single effective suit.
    """
    bot = make_bot("mc", seed=1)
    checked = 0
    for rnd, seat in _lead_states():
        o = rnd.ordering
        for arm, ballot in _all(bot, rnd, seat).items():
            for a in ballot:
                assert a, f"{arm} proposed an empty action"
                assert all(a.count(c) <= rnd.hands[seat].count(c) for c in set(a)), \
                    f"{arm} proposed cards the seat does not hold: {a}"
                assert len({o.eff_suit(c) for c in a}) == 1, \
                    f"{arm} proposed a mixed-suit lead {a}"
                checked += 1
    assert checked > 100, f"only {checked} actions checked"


def test_the_deployed_ballot_stays_within_successful_leads():
    """The BASELINE arm should still only offer leads that actually succeed —
    it is the shipped policy. Only the widened arms may attempt-and-lose."""
    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states():
        others = [rnd.hands[s] for s in range(4) if s != seat]
        for a in propose("current", bot, rnd, seat, budget=BUDGET, seed=7,
                         state_key="k"):
            played, msg = validate_lead(list(a), rnd.hands[seat], others,
                                        rnd.ordering)
            assert sorted(played) == sorted(a) and not msg, \
                f"the deployed ballot offered a losing throw {a}"


def test_every_arm_keeps_the_protected_action():
    """No arm may lose by omitting SmartBot's pick — that would confound
    ballot quality with dropping the heuristic prior."""
    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states():
        keep = protected(bot, rnd, seat)
        for arm, ballot in _all(bot, rnd, seat).items():
            assert keep in ballot, f"{arm} dropped the protected action"


def test_budget_matched_arms_emit_the_same_count():
    """current / v3 / random_fill / quota must be compared at EQUAL budget.

    If they differ in size, a win could be more draws rather than better
    actions — which is exactly how a wider ballot fakes an improvement.
    """
    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states():
        got = _all(bot, rnd, seat)
        universe = len(structured_universe(rnd, seat, bot))
        sizes = {a: len(got[a]) for a in ("random_fill", "quota")}
        # these two draw from the same universe, so at equal budget they must
        # agree in size whenever the universe is large enough to fill it
        if universe >= BUDGET:
            assert sizes["random_fill"] == sizes["quota"] == BUDGET, sizes
        assert len(got["current"]) <= BUDGET
        assert len(got["v3"]) <= BUDGET


def test_full_universe_is_a_superset_and_not_budget_capped():
    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states():
        got = _all(bot, rnd, seat)
        full = {tuple(a) for a in got["full_universe"]}
        # `current` too. Checking only the new arms is how the missing-throws
        # defect survived: the high-compute arm was not a superset of the
        # BASELINE, which is the one comparison that has to hold (Codex).
        for arm in ("random_fill", "quota", "current", "v3"):
            assert {tuple(a) for a in got[arm]} <= full, \
                f"{arm} proposed something outside the structured universe"
        if len(structured_universe(rnd, seat, bot)) > BUDGET:
            assert len(got["full_universe"]) > BUDGET, \
                "the high-compute arm must not be silently budget-capped"


NEW_ARMS = ("random_fill", "quota", "full_universe")


def test_new_arms_are_deterministic_and_order_independent():
    """Same state and seed must give the same ballot; shuffling the HAND must
    not change it. A ballot that depends on hand order is not a function of
    the state.

    Scoped to the arms this pilot introduces; the deployed ballot has its own
    test below, kept separate because it guards shipped code rather than
    pilot code.
    """
    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states(n=4):
        a = _all(bot, rnd, seat)
        b = _all(bot, rnd, seat)
        assert a == b, "arms are not deterministic"
        original = list(rnd.hands[seat])
        try:
            for perm_seed in (1, 2, 3):
                shuffled = list(original)
                random.Random(perm_seed).shuffle(shuffled)
                rnd.hands[seat] = shuffled
                c = _all(bot, rnd, seat)
                for arm in NEW_ARMS:
                    assert sorted(c[arm]) == sorted(a[arm]), \
                        f"{arm} depends on hand order"
        finally:
            rnd.hands[seat] = original


def test_quota_spreads_across_archetypes_more_than_random_does():
    """The quota arm's entire claim. If it does not cover more archetypes at
    the same budget, it is a differently-shuffled random fill and the pilot
    has nothing to measure."""
    bot = make_bot("mc", seed=1)
    quota_better = random_better = 0
    for rnd, seat in _lead_states(n=10, seed0=773000):
        got = _all(bot, rnd, seat)
        if len(structured_universe(rnd, seat, bot)) <= BUDGET:
            continue                      # nothing to select between
        nq = len({archetype(rnd, seat, a) for a in got["quota"]})
        nr = len({archetype(rnd, seat, a) for a in got["random_fill"]})
        quota_better += nq > nr
        random_better += nr > nq
    assert quota_better > random_better, \
        f"quota covered more archetypes in {quota_better} states, random in " \
        f"{random_better} — the selector is not selecting"


def test_unknown_arm_is_refused():
    bot = make_bot("mc", seed=1)
    rnd, seat = _lead_states(n=1)[0]
    with pytest.raises(ValueError):
        propose("quotaa", bot, rnd, seat, budget=BUDGET, seed=1, state_key="k")


def test_deployed_ballot_is_order_independent():
    """The baseline arm's ballot must be a function of the state, not the list.

    FIXED 2026-08-05, having been pinned xfail-strict for one commit.
    `_candidates` returned a different ACTION SET under hand reordering in
    roughly one lead state in six — offering `D2` under one ordering and `H2`
    under another — because generation walks the hand and the caps truncate
    whatever came first. It now sorts the hand for the duration of generation,
    so every helper sees one canonical order.

    This matters for the pilot beyond tidiness: if `current` proposes different
    actions depending on incidental hand ordering, its measured strength is
    partly noise, and the coverage audit's "currently offered" counts inherit
    the same dependence.
    """
    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states(n=12, seed0=774000):
        original = list(rnd.hands[seat])
        sets = []
        try:
            for perm_seed in (0, 1, 2, 3):
                shuffled = list(original)
                random.Random(perm_seed).shuffle(shuffled)
                rnd.hands[seat] = shuffled
                sets.append(frozenset(tuple(sorted(a))
                                      for a in bot._candidates(rnd, seat)))
        finally:
            rnd.hands[seat] = original
        assert len(set(sets)) == 1, (
            f"deployed ballot depends on hand order: "
            f"{sorted(set(sets[0]) - set(sets[-1]))[:3]} present in one "
            f"ordering only")


def test_mc_more_shares_the_deployed_ballot():
    """`mc_more` must differ from `current` ONLY in worlds, not in actions.

    It is the arm that answers "is a wider ballot worth anything, or would the
    same compute spent pricing the old one do as well". If its ballot drifted
    from `current`, that question stops being asked.
    """
    import shengji.pilot_arms as pa

    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states():
        got = _all(bot, rnd, seat)
        assert got["mc_more_full_work"] == got["current"], \
            "mc_more's ballot diverged from the deployed one"
    assert not hasattr(pa, "MC_MORE_WORLD_MULTIPLIER"), \
        "a flat world multiplier is a SECOND contradictory work contract; " \
        "the runner budgets from worlds_for_equal_work()"


def test_one_component_add_from_a_singleton_is_reachable():
    """`SJ` -> `SJ SK` was unreachable because mutations skipped len<2 bases.

    Codex's witness: the hand holds SJ SK SQ and the uniform throw SJ SK never
    appeared in the universe despite being a one-component add.
    """
    bot = make_bot("mc", seed=1)
    hits = 0
    for rnd, seat in _lead_states(n=12, seed0=786000):
        o = rnd.ordering
        u = {tuple(sorted(a)) for a in structured_universe(rnd, seat, bot)}
        singles = [a for a in u if len(a) == 1]
        for (code,) in singles[:4]:
            eff = o.eff_suit(code)
            spare = [c for c in rnd.hands[seat]
                     if o.eff_suit(c) == eff and c != code]
            if not spare:
                continue
            grown = tuple(sorted([code, sorted(spare)[0]]))
            if grown in u:
                hits += 1
    assert hits > 0, "no one-component add from a singleton reached the universe"


def test_throw_archetypes_are_distinguished():
    """Without a throw class the safe/near-boss/speculative quotas cannot
    operate — every multi-component action fell in one bucket."""
    bot = make_bot("mc", seed=1)
    classes = set()
    for rnd, seat in _lead_states(n=12, seed0=787000):
        for a in structured_universe(rnd, seat, bot):
            classes.add(archetype(rnd, seat, a)[-1])
    assert "single_component" in classes
    assert len(classes & {"safe", "near_boss", "speculative"}) >= 2, \
        f"throws were not differentiated: {classes}"


def test_replace_emits_same_size_components_with_multiplicity():
    """Codex's exact witness. `combinations(set(pool), n)` cannot build a pair
    from two copies of one code, so the required pair replacement was absent
    while a three-distinct-card one appeared."""
    from shengji.engine.cards import Ordering
    from shengji.pilot_arms import _component_mutations

    class _R:
        ordering = Ordering("H", "7")
        hands = [["S3", "S3", "S4", "S4", "S5", "S6"], [], [], []]

    out = {tuple(sorted(a))
           for a in _component_mutations(_R(), 0, [["S3", "S3", "S5"]])}
    assert ("S4", "S4", "S5") in out, "pair replacement absent"
    assert ("S4", "S5", "S6") not in out, \
        "pair replacement changed shape into two singletons"


def test_remove_and_replace_are_exercised_not_just_add():
    """The old test was named for the bound but only checked ADD (Codex)."""
    from shengji.engine.cards import Ordering
    from shengji.pilot_arms import _component_mutations

    class _R:
        ordering = Ordering("H", "7")
        hands = [["S3", "S3", "S5", "S6"], [], [], []]

    out = {tuple(sorted(a))
           for a in _component_mutations(_R(), 0, [["S3", "S3", "S5"]])}
    assert ("S3", "S3") in out, "REMOVE of the single component is missing"
    assert ("S5",) in out or ("S3", "S3") in out, "REMOVE produced nothing"
    assert ("S3", "S3", "S5", "S6") in out, "ADD of a spare is missing"


def test_mutation_bound_matches_brute_force():
    """Exact-set check against an independently enumerated mutation oracle."""
    import itertools as it

    from shengji.engine.cards import Ordering
    from shengji.engine.combos import decompose
    from shengji.pilot_arms import _component_mutations

    def oracle(hand, base, o):
        """Brute-force ADD/REMOVE/REPLACE without calling the implementation.

        Replacement candidates are physical sub-multisets of the spare pool;
        decomposition is used only as the rules-level shape predicate.
        """
        expected = set()
        for action in base:
            dec = decompose(list(action), o)
            pool = list(hand)
            for c in action:
                pool.remove(c)
            for c in set(pool):
                expected.add(tuple(sorted(list(action) + [c])))
            for i, comp in enumerate(dec.components):
                rest = [c for j, other in enumerate(dec.components) if j != i
                        for c in other.cards]
                if len(dec.components) > 1:
                    expected.add(tuple(sorted(rest)))
                # Enumerate physical index subsets, then independently accept
                # exactly one component whose shape matches the removed one.
                for idxs in it.combinations(range(len(pool)), len(comp.cards)):
                    repl = [pool[j] for j in idxs]
                    rd = decompose(repl, o)
                    if len(rd.components) != 1:
                        continue
                    rc = rd.components[0]
                    if rc.pair_len == comp.pair_len:
                        expected.add(tuple(sorted(rest + repl)))
        return expected

    cases = [
        (["S3", "S4", "S5"], [["S3"]]),
        (["S3", "S3", "S4", "S4", "S5", "S6"],
         [["S3", "S3", "S5"]]),
        (["S3", "S3", "S4", "S4", "S5", "S5", "S6", "S6", "S8"],
         [["S3", "S3", "S4", "S4", "S8"]]),
    ]
    o = Ordering("H", "7")
    for hand, base in cases:
        class _R:
            ordering = o
            hands = [list(hand), [], [], []]
        got = {tuple(sorted(a)) for a in _component_mutations(_R(), 0, base)}
        assert got == oracle(hand, base, o), (
            f"mutation mismatch for {hand}/{base}: missing "
            f"{oracle(hand, base, o) - got}, extra {got - oracle(hand, base, o)}")

    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states(n=6, seed0=791000):
        o = rnd.ordering
        u = {tuple(sorted(a)) for a in structured_universe(rnd, seat, bot)}
        # independently enumerate ADD over every base in the universe
        by_suit = {}
        for c in rnd.hands[seat]:
            by_suit.setdefault(o.eff_suit(c), []).append(c)
        # ONE ROUND over the structured base, which is the stated bound —
        # not a transitive closure over mutation products. Singles are always
        # in the base, so they are the honest slice to check.
        for base in [a for a in u if len(a) == 1]:
            eff = o.eff_suit(base[0])
            spare = [c for c in by_suit.get(eff, []) if c != base[0]]
            for c in set(spare):
                grown = tuple(sorted(list(base) + [c]))
                assert grown in u, (
                    f"one-component ADD {base} + {c} = {grown} is missing; "
                    f"the universe is not the closure of the stated bound")


def test_mutation_bound_live_hand_sweep_has_no_order_hidden_or_overuse_leak():
    """Broad deterministic sweep beyond the three exact small-hand oracles."""
    from collections import Counter
    from shengji.pilot_arms import _component_mutations

    bot = make_bot("mc", seed=1)
    checked = 0
    for rnd, seat in _lead_states(n=24, seed0=794000):
        base = bot._candidates(rnd, seat)
        expected = {tuple(sorted(a))
                    for a in _component_mutations(rnd, seat, base)}
        hand = Counter(rnd.hands[seat])
        assert all(not (Counter(action) - hand) for action in expected), \
            "mutation emitted cards the acting seat does not hold"

        saved = [list(cards) for cards in rnd.hands]
        try:
            # Reverse the actor's representation and erase all hidden hands.
            # A public proposer may use its own cards, never the true deal.
            rnd.hands[seat] = list(reversed(rnd.hands[seat]))
            for other in range(4):
                if other != seat:
                    rnd.hands[other] = []
            got = {tuple(sorted(a))
                   for a in _component_mutations(rnd, seat,
                                                  list(reversed(base)))}
            assert got == expected, "mutation read list order or a hidden hand"
        finally:
            rnd.hands = saved
        checked += len(expected)
    assert checked > 250, f"broad sweep exercised only {checked} mutations"


def test_the_SK_SQ_witness_is_present():
    """Codex's exact witness: a hand holding SJ SK SQ must offer SK SQ."""
    bot = make_bot("mc", seed=1)
    seen = 0
    for rnd, seat in _lead_states(n=20, seed0=792000):
        o = rnd.ordering
        u = {tuple(sorted(a)) for a in structured_universe(rnd, seat, bot)}
        for suit, cards in {s: [c for c in rnd.hands[seat] if o.eff_suit(c) == s]
                            for s in {o.eff_suit(c) for c in rnd.hands[seat]}}.items():
            distinct = sorted(set(cards))
            for a, b in itertools.combinations(distinct, 2):
                seen += 1
                assert tuple(sorted([a, b])) in u, \
                    f"held uniform two-single throw {a} {b} absent from universe"
    assert seen > 50, f"only {seen} pairs checked"


def test_throw_risk_is_shape_aware():
    """A pair is beaten by a higher PAIR, not by any higher singleton.

    Counting singletons made `safe` and `near_boss` misleading quota labels.
    """
    from shengji.ai.memory import Memory
    from shengji.engine.combos import decompose

    bot = make_bot("mc", seed=1)
    checked = 0
    for rnd, seat in _lead_states(n=14, seed0=793000):
        o = rnd.ordering
        mem = Memory(rnd, seat)
        for a in structured_universe(rnd, seat, bot):
            dec = decompose(list(a), o)
            if len(dec.components) < 2:
                continue
            klass = archetype(rnd, seat, a)[-1]
            if klass != "safe":
                continue
            checked += 1
            for comp in dec.components:
                if comp.pair_len == 0:
                    continue
                eff = o.eff_suit(a[0])
                higher_pairs = [c for c, n in mem.unseen.items()
                                if o.eff_suit(c) == eff and n >= 2
                                and o.level(c) > comp.top]
                # NO tractor exemption. The old `or comp.pair_len > 1` made
                # this prove pair risk only, which is half the claim (Codex).
                if comp.pair_len == 1:
                    assert not higher_pairs, (
                        f"{a} called SAFE while a higher unseen PAIR exists "
                        f"({higher_pairs[:2]})")
                else:
                    levels = sorted({o.level(c) for c, n in mem.unseen.items()
                                     if o.eff_suit(c) == eff and n >= 2})
                    beat = any(
                        levels[i:i + comp.pair_len][-1] - levels[i] ==
                        comp.pair_len - 1 and
                        levels[i:i + comp.pair_len][-1] > comp.top
                        for i in range(len(levels) - comp.pair_len + 1))
                    assert not beat, (
                        f"{a} called SAFE while a higher unseen "
                        f"{comp.pair_len}-run exists")
    assert checked > 0, "no safe multi-component throws found to check"
