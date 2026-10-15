"""The draw-time form of the history-legal world test (``world_history_draw``,
`ai.history_legality.draw_constraints` / `constrained_draw`).

Witnesses: the constraints are exact for the pair obligation (on production's
own worlds over many heuristic states, a world breaks a follow's pair
obligation iff it deals a constrained seat one of its twins); the constrained
draw never breaks a pair obligation, and whatever the oracle still rejects is a
tractor obligation; every world the rule returns replays through the real
engine; the sampler's method override lives only during a draw; the flag
requires ``world_history_legal``, names ``-whl-whd``, and with it off the
history-legal draw is unchanged.
"""
import copy
import random
from collections import Counter

import pytest

from shengji.ai import history_legality as HL
from shengji.ai.cwv_policy import sample_worlds
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine import legal
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_ENV, PRODUCTION_SHA
from test_world_history_legal import (RELEASE45_ENV, SEED, W, engine_replays, fixture,
                                      served, started)


def states(n_games=6, every=5, min_trick=3):
    """Heuristic decision states with some follow history."""
    h = HeuristicBot()
    out = []
    for game_seed in range(n_games):
        rnd, _ = started(game_seed)
        k = 0
        while rnd.phase == "play":
            if k % every == 0 and len(rnd.history) >= min_trick:
                out.append((copy.deepcopy(rnd), rnd.turn))
            rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
            k += 1
    return out


def pair_violation(events, hands, ordering):
    """Does some follow break its PAIR obligation in this world?"""
    for ev in events:
        try:
            legal.validate_follow(list(ev.cards), list(hands[ev.seat]) + list(ev.later),
                                  list(ev.lead), ordering)
        except legal.IllegalPlay as exc:
            if "pairs from the led suit" in str(exc):
                return True
    return False


def breaks_constraints(constraints, hands, ordering):
    return any(Counter(hands[s])[c] for (s, suit), codes in constraints.items() for c in codes)


def test_constraints_are_exact_for_the_pair_obligation():
    checked = flagged = 0
    for rnd, seat in states():
        events = HL.follow_events(rnd, seat)
        constraints = HL.draw_constraints(rnd, seat, events)
        assert not breaks_constraints(constraints, rnd.hands, rnd.ordering)
        worlds, _ = sample_worlds(MCBot(seed=11), rnd, seat, 24,
                                  mem=Memory(rnd, seat, own_kitty=True))
        for hands, _ in worlds:
            got = breaks_constraints(constraints, hands, rnd.ordering)
            assert got == pair_violation(events, hands, rnd.ordering)
            checked += 1
            flagged += got
    assert checked > 500 and flagged > 50


def test_the_constrained_draw_breaks_no_pair_obligation():
    tractor_only = drawn = 0
    for rnd, seat in states():
        events = HL.follow_events(rnd, seat)
        bot = MCBot(seed=13)
        propose = HL.constrained_draw(bot, HL.draw_constraints(rnd, seat, events))
        mem = Memory(rnd, seat, own_kitty=True)
        for _ in range(16):
            got = propose(rnd, seat, mem)
            assert "_deal_suit" not in vars(bot)
            if got is None:
                continue
            hands = bot._complete_determinized_hands(rnd, seat, got[0], buried=got[1])
            drawn += 1
            assert not pair_violation(events, hands, rnd.ordering)
            bad = HL.first_violation(events, hands, rnd.ordering)
            if bad is not None:
                ev = events[bad]
                with pytest.raises(legal.IllegalPlay, match="tractor"):
                    legal.validate_follow(list(ev.cards), list(hands[ev.seat]) + list(ev.later),
                                          list(ev.lead), rnd.ordering)
                tractor_only += 1
    assert drawn > 1000


def test_every_world_the_draw_rule_returns_replays_through_the_engine():
    start, now, seat = fixture()
    bot = served(world_history_legal=True, world_history_draw=True)
    worlds, attempts = bot._worlds(now, seat)
    stats = bot._last_sampling
    assert len(worlds) == W and stats["history_fallback_worlds"] == 0
    assert stats["history_draw_constraints"] >= 1 and stats["history_draw_forbidden"] >= 1
    assert "_deal_suit" not in vars(bot.sampler)
    for hands, _ in worlds:
        assert HL.history_legal(now, seat, hands)
        assert engine_replays(start, now, seat, hands)
    # fewer rejections than the rejection-only draw on the same seed
    plain = served(world_history_legal=True)
    plain._worlds(now, seat)
    assert stats["history_rejections"] < plain._last_sampling["history_rejections"]


def test_without_the_draw_flag_the_history_draw_is_unchanged():
    start, now, seat = fixture()
    a = served(world_history_legal=True)._worlds(now, seat)
    worlds, attempts, stats = HL.sample_worlds_history_legal(
        MCBot(seed=SEED), now, seat, W, mem=Memory(now, seat, own_kitty=True))
    assert a == (worlds, attempts)
    assert "history_draw_constraints" not in stats
    bot = served(world_history_legal=True)
    bot.decide_play(copy.deepcopy(now), seat)
    assert "history_draw_constraints" not in bot.last_decision_record


def test_a_proposal_bypasses_the_draw_constraints():
    start, now, seat = fixture()
    sampler = MCBot(seed=SEED)
    calls = []

    def propose(rnd, s, mem):
        calls.append(s)
        return sampler._sample_hands(rnd, s, mem)
    worlds, attempts, stats = HL.sample_worlds_history_legal(
        sampler, now, seat, W, mem=Memory(now, seat, own_kitty=True), propose=propose,
        constrain=True)
    assert len(calls) == attempts and stats["history_draw_constraints"] == 0
    assert worlds == served(world_history_legal=True)._worlds(now, seat)[0]


@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_flag_requires_the_test_and_names_whd(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires world_history_legal"):
        names({**PRODUCTION_ENV, "SHENGJI_PV_WORLD_HISTORY_DRAW": "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires world_history_legal"):
        served(world_history_draw=True)
    on, = names({**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
                 "SHENGJI_PV_WORLD_HISTORY_DRAW": "1"})
    whl, = names({**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1"})
    assert "-rc-whl-whd-tb-" in on and on != whl
    assert whl == ("pv-search-491ee4bf-w64-k8-div-rc-whl-tb-la-dtr-vd-r018c6784-"
                   "bury-hybrid-bwv-6ca0a6fd5972")
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert "world_history_draw" not in pv.recipe_payload(config)
