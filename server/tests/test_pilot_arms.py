"""Arm invariants. A pilot comparing arms that differ in an unintended way
measures that difference instead of the one it claims to.
"""
from __future__ import annotations

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
    from shengji.pilot_arms import MC_MORE_WORLD_MULTIPLIER

    bot = make_bot("mc", seed=1)
    for rnd, seat in _lead_states():
        got = _all(bot, rnd, seat)
        assert got["mc_more"] == got["current"], \
            "mc_more's ballot diverged from the deployed one"
    assert MC_MORE_WORLD_MULTIPLIER > 1, "mc_more must actually get more worlds"
