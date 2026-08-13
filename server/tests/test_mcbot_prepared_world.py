"""Parity and aliasing guards for one-time determinization preparation."""

from __future__ import annotations

import copy
import json
import random
from collections import Counter
from types import MethodType

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.rl.replay_log import rebuild_round


def _round_in_play(seed: int):
    rnd = Game(random.Random(seed)).start_round()
    heuristic = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        else:
            rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
    return rnd


def _round_in_bury(seed: int):
    rnd = Game(random.Random(seed)).start_round()
    while rnd.phase != "bury":
        if rnd.phase == "deal":
            rnd.deal_next()
        else:
            rnd.finalize_declare()
    return rnd


def _incident_state():
    from pathlib import Path

    fixture = Path(__file__).with_name("data") / "mc_override_variance.json"
    payload = json.loads(fixture.read_text())
    rnd = rebuild_round(payload["events"])
    seat = payload["seat"]
    for event in payload["events"]:
        if event["e"] != "play":
            continue
        if (rnd.trick is None or not rnd.trick.plays) and event["seat"] == seat:
            break
        rnd.play(event["seat"], list(event["cards"]))
    return rnd, seat


def _semantic_record(bot):
    record = copy.deepcopy(bot.last_decision_record)
    assert record is not None
    record.pop("search_secs", None)
    return record


def _reference_prepare(self, _rnd, _seat, sampled, *, buried):
    """The pre-change path: pass the mapping through and validate per arm."""
    return sampled


def test_prepared_world_returns_fresh_hands_and_retains_burial_snapshot():
    rnd = _round_in_play(5)
    seat = rnd.banker
    bot = MCBot(seed=17)
    sampled = bot._sample_hands(
        rnd, seat, Memory(rnd, seat, own_kitty=True))
    assert sampled is not None
    hands, buried = sampled
    prepared = bot._prepare_determinized_world(
        rnd, seat, hands, buried=buried)

    first = bot._fresh_determinized_hands(
        rnd, seat, prepared, buried=buried)
    second = bot._fresh_determinized_hands(
        rnd, seat, prepared, buried=list(reversed(buried)))
    assert first == second
    assert first is not second
    assert all(left is not right for left, right in zip(first, second))
    original = tuple(tuple(hand) for hand in second)
    first[0].pop()
    first[1].append("impossible-alias-probe")
    assert tuple(tuple(hand) for hand in second) == original
    assert prepared.hands == original
    assert prepared.buried == tuple(sorted(buried))


def test_prepared_banker_world_preserves_known_kitty_and_conservation():
    """Regression: banker kitty is removed once, never twice or reintroduced."""
    rnd = _round_in_play(11)
    seat = rnd.banker
    bot = MCBot(seed=31)
    mem = Memory(rnd, seat, own_kitty=True)
    sampled = bot._sample_hands(rnd, seat, mem)
    assert sampled is not None
    hands, buried = sampled
    prepared = bot._prepare_determinized_world(
        rnd, seat, hands, buried=buried)
    completed = bot._fresh_determinized_hands(
        rnd, seat, prepared, buried=buried)

    observed = Counter(buried)
    for hand in completed:
        observed.update(hand)
    for trick in rnd.history:
        for play in trick.plays:
            observed.update(play.cards)
    if rnd.trick is not None:
        for play in rnd.trick.plays:
            observed.update(play.cards)
    assert observed == Counter(rnd.deck)
    assert list(prepared.buried) == sorted(rnd.buried)


@pytest.mark.parametrize("policy", [
    "mc-strong", "mc-s0-report-lcb", "mc-s0-adaptive",
])
def test_uniform_report_and_adaptive_match_reference_path(policy):
    rnd, seat = _incident_state()
    optimized = make_bot(policy, seed=238)
    reference = make_bot(policy, seed=238)
    # Preserve each algorithm while keeping this permanent differential test
    # small.  LCB still requires at least 30 disjoint report worlds.
    for bot in (optimized, reference):
        bot.N_DETERMINIZATIONS = 4
        if bot.REPORT_FOLD_WORLDS:
            bot.REPORT_FOLD_WORLDS = 30
    reference._prepare_play_world = MethodType(_reference_prepare, reference)

    optimized_action = optimized.decide_play(copy.deepcopy(rnd), seat)
    reference_action = reference.decide_play(copy.deepcopy(rnd), seat)
    assert optimized_action == reference_action
    assert _semantic_record(optimized) == _semantic_record(reference)
    assert optimized.rng.getstate() == reference.rng.getstate()
    assert optimized._sampler_snapshot() == reference._sampler_snapshot()
    assert optimized.rollouts == reference.rollouts
    assert optimized.last_n_worlds == reference.last_n_worlds


def test_one_completion_per_accepted_world_across_selection_and_report():
    rnd, seat = _incident_state()
    bot = make_bot("mc-s0-report-lcb", seed=238)
    bot.N_DETERMINIZATIONS = 4
    bot.REPORT_FOLD_WORLDS = 30
    complete = bot._complete_determinized_hands
    calls = 0

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return complete(*args, **kwargs)

    bot._complete_determinized_hands = MethodType(counted, bot)
    before = bot._sampler_snapshot()
    bot.decide_play(rnd, seat)
    delta = bot._sampler_delta(before)
    assert calls == delta["accepted_worlds"] == 34
    assert bot.last_decision_record["work"]["complete"] is True


def test_sampler_rejection_and_all_counters_match_reference_path():
    rnd, seat = _incident_state()
    optimized = make_bot("mc-strong", seed=73)
    reference = make_bot("mc-strong", seed=73)
    optimized.N_DETERMINIZATIONS = reference.N_DETERMINIZATIONS = 4
    reference._prepare_play_world = MethodType(_reference_prepare, reference)

    for bot in (optimized, reference):
        real_sample = bot._sample_hands

        def rejector(real):
            calls = 0

            def reject_first(self, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    self.sample_attempts += 1
                    self.failed_worlds += 1
                    return None
                return real(*args, **kwargs)

            return reject_first

        bot._sample_hands = MethodType(rejector(real_sample), bot)

    assert optimized.decide_play(copy.deepcopy(rnd), seat) == \
        reference.decide_play(copy.deepcopy(rnd), seat)
    assert _semantic_record(optimized) == _semantic_record(reference)
    assert optimized._sampler_snapshot() == reference._sampler_snapshot()


def test_structured_bury_matches_reference_and_prepares_once_per_world():
    rnd = _round_in_bury(37)
    seat = rnd.banker
    optimized = make_bot("mc-structured-bury", seed=19)
    reference = make_bot("mc-structured-bury", seed=19)
    for bot in (optimized, reference):
        bot.N_BURY_WORLDS = 3
        bot.BURY_MAX_ROLLOUTS = 96
    reference._prepare_bury_world = MethodType(_reference_prepare, reference)

    complete = optimized._complete_determinized_hands
    calls = 0

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return complete(*args, **kwargs)

    optimized._complete_determinized_hands = MethodType(counted, optimized)
    optimized_action = optimized.decide_bury(copy.deepcopy(rnd), seat)
    reference_action = reference.decide_bury(copy.deepcopy(rnd), seat)
    assert optimized_action == reference_action
    optimized_record = copy.deepcopy(optimized.last_bury_record)
    reference_record = copy.deepcopy(reference.last_bury_record)
    optimized_record.pop("search_secs", None)
    reference_record.pop("search_secs", None)
    assert optimized_record == reference_record
    assert optimized.rng.getstate() == reference.rng.getstate()
    assert optimized._sampler_snapshot() == reference._sampler_snapshot()
    assert calls == optimized_record["work"]["worlds_used"] == 3
