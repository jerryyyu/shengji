"""Witnesses for explicit per-world hand preparation in MC rollouts.

The identity-keyed per-world cache could return a stale completion for
in-place-mutated sampled hands (same object identities, same lengths, changed
contents) and bound neither the round nor the seat.  Preparation is now
explicit: each candidate loop completes an accepted world exactly once and
passes it to every candidate's rollout, and a direct ``_rollout`` call always
recomputes.  These tests are the review witnesses for that contract.
"""
from __future__ import annotations

import copy
import random

from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game


def _lead_state(seed: int = 73):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    smart = SmartBot()
    for seat in range(4):
        declaration = smart.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, SmartBot().decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play" and rnd.turn is not None
    return rnd, rnd.turn


def _accepted_world(bot, rnd, seat):
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    sampled = None
    while sampled is None:
        sampled = bot._sample_hands(rnd, seat, mem)
    return sampled


def test_direct_rollout_recomputes_after_inplace_world_mutation():
    """Codex review reproduction: in-place content mutation with preserved
    identities, sizes and card conservation must never reuse a previous
    completion."""
    rnd, seat = _lead_state(780002)
    bot = make_bot("mc-s0-report-lcb", seed=101)
    hands, buried = _accepted_world(bot, rnd, seat)
    candidate = [rnd.sorted_hand(seat)[0]]

    before = bot._rollout(rnd, seat, hands, buried, list(candidate))
    fresh_before = make_bot("mc-s0-report-lcb", seed=101)._rollout(
        rnd, seat, hands, buried, list(candidate))
    assert before == fresh_before

    other = [s for s in range(4) if s != seat]
    a, b = other[0], other[1]
    hands[a][0], hands[b][0] = hands[b][0], hands[a][0]

    after = bot._rollout(rnd, seat, hands, buried, list(candidate))
    fresh_after = make_bot("mc-s0-report-lcb", seed=101)._rollout(
        rnd, seat, hands, buried, list(candidate))
    assert after == fresh_after


def test_decide_play_prepares_each_accepted_world_exactly_once(monkeypatch):
    rnd, seat = _lead_state(780002)
    bot = make_bot("mc-s0-report-lcb", seed=101)

    preparations = []
    worlds = []
    rollout_prepared_flags = []
    orig_prepare = MCBot._complete_determinized_hands
    orig_session = MCBot._new_exact_world_session
    orig_rollout = MCBot._rollout

    def counting_prepare(self, *args, **kwargs):
        preparations.append(1)
        return orig_prepare(self, *args, **kwargs)

    def counting_session(self, *args, **kwargs):
        worlds.append(1)
        return orig_session(self, *args, **kwargs)

    def spying_rollout(self, *args, **kwargs):
        rollout_prepared_flags.append(
            kwargs.get("prepared_hands") is not None)
        return orig_rollout(self, *args, **kwargs)

    monkeypatch.setattr(MCBot, "_complete_determinized_hands",
                        counting_prepare)
    monkeypatch.setattr(MCBot, "_new_exact_world_session", counting_session)
    monkeypatch.setattr(MCBot, "_rollout", spying_rollout)

    bot.decide_play(rnd, seat)

    assert preparations and worlds
    assert len(preparations) == len(worlds)
    assert rollout_prepared_flags and all(rollout_prepared_flags)


def test_prepared_hands_stay_unmutated_and_candidates_get_fresh_copies():
    rnd, seat = _lead_state(780002)
    bot = make_bot("mc-s0-report-lcb", seed=101)
    hands, buried = _accepted_world(bot, rnd, seat)
    prepared = bot._complete_determinized_hands(rnd, seat, hands,
                                                buried=buried)
    snapshot = copy.deepcopy(prepared)
    candidate = [rnd.sorted_hand(seat)[0]]

    first = bot._rollout(rnd, seat, hands, buried, list(candidate),
                         prepared_hands=prepared)
    second = bot._rollout(rnd, seat, hands, buried, list(candidate),
                          prepared_hands=prepared)

    assert prepared == snapshot
    assert first == second


def test_direct_rollouts_are_bound_to_their_own_round_and_seat():
    bot = make_bot("mc-s0-report-lcb", seed=101)
    for seed in (780002, 780003):
        rnd, seat = _lead_state(seed)
        hands, buried = _accepted_world(bot, rnd, seat)
        candidate = [rnd.sorted_hand(seat)[0]]
        mine = bot._rollout(rnd, seat, hands, buried, list(candidate))
        fresh = make_bot("mc-s0-report-lcb", seed=101)._rollout(
            rnd, seat, hands, buried, list(candidate))
        assert mine == fresh


def test_bot_snapshots_share_no_world_preparation_state():
    rnd, seat = _lead_state(780002)
    bot = make_bot("mc-s0-report-lcb", seed=101)
    assert not hasattr(bot, "_world_hands_cache")

    clone = copy.deepcopy(bot)
    hands, buried = _accepted_world(bot, rnd, seat)
    candidate = [rnd.sorted_hand(seat)[0]]
    original = bot._rollout(rnd, seat, hands, buried, list(candidate))

    hands[[s for s in range(4) if s != seat][0]].sort(reverse=True)
    from_clone = clone._rollout(rnd, seat, hands, buried, list(candidate))
    fresh = make_bot("mc-s0-report-lcb", seed=101)._rollout(
        rnd, seat, hands, buried, list(candidate))
    assert from_clone == fresh
