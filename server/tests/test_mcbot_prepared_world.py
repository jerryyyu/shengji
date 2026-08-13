"""Parity and aliasing guards for one-time determinization preparation."""

from __future__ import annotations

import copy
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
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


def _count_world_completions(bot):
    """Count the expensive validate/canonicalise boundary on one bot."""
    original = bot._complete_determinized_hands
    calls = {"count": 0}

    def counted(self, *args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    bot._complete_determinized_hands = MethodType(counted, bot)
    return calls


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


def test_adaptive_prepares_once_per_accepted_selection_and_report_world():
    rnd, seat = _incident_state()
    bot = make_bot("mc-s0-adaptive", seed=238)
    bot.N_DETERMINIZATIONS = 4
    bot.REPORT_FOLD_WORLDS = 30
    calls = _count_world_completions(bot)

    before = bot._sampler_snapshot()
    bot.decide_play(rnd, seat)
    delta = bot._sampler_delta(before)

    assert bot.last_alloc["mode"] == "deterministic_adaptive"
    assert bot.last_decision_record["report_fold"]["complete"] is True
    assert calls["count"] == delta["accepted_worlds"] == 34
    assert bot.last_decision_record["work"]["complete"] is True


def test_uniform_residual_prepares_its_dummy_world_once():
    rnd, seat = _incident_state()
    bot = make_bot("mc-s0-uniform-work", seed=91)
    bot.N_DETERMINIZATIONS = 4
    # The fixture has eleven candidates: 4*11+7 buys four complete common
    # worlds plus seven explicit dummy evaluations on one additional world.
    bot.EXTRA_SELECTION_WORK = 7
    calls = _count_world_completions(bot)

    before = bot._sampler_snapshot()
    bot.decide_play(rnd, seat)
    delta = bot._sampler_delta(before)

    assert bot.last_alloc["worlds"] == 4
    assert bot.last_alloc["dummy_rollouts"] == 7
    assert bot.last_alloc["short"] is False
    assert calls["count"] == delta["accepted_worlds"] == 5
    assert bot.last_decision_record["work"]["complete"] is True


def test_exact_endgame_prepares_once_per_world_before_session_reuse():
    rnd = _round_in_play(20)
    heuristic = HeuristicBot()
    while rnd.phase == "play" and max(len(hand) for hand in rnd.hands) > 3:
        actor = rnd.turn
        assert actor is not None
        rnd.play(actor, heuristic.decide_play(rnd, actor))
    assert rnd.phase == "play" and rnd.turn is not None

    bot = make_bot("mc-exact-endgame", seed=1020)
    bot.N_DETERMINIZATIONS = 2
    calls = _count_world_completions(bot)
    before = bot._sampler_snapshot()
    bot.decide_play(rnd, rnd.turn)
    delta = bot._sampler_delta(before)

    assert calls["count"] == delta["accepted_worlds"] == 2
    assert bot.exact_endgame_sessions == 2
    assert bot.exact_endgame_calls > bot.exact_endgame_sessions
    assert bot.exact_endgame_refusals == 0
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


def test_exact_head_performance_receipt_recomputes_and_retires_mixed_claim():
    receipt_path = (Path(__file__).with_name("data") /
                    "prepared_world_perf_exact_head.v1.json")
    receipt = json.loads(receipt_path.read_text())
    assert receipt["schema"] == "prepared-world-perf-exact-head-v1"
    assert receipt["supersedes"]["status"] == "retired_mixed_revision"
    assert receipt["claim_boundary"] == {
        "performance_only": True,
        "production_deployment": False,
        "strength_claim": False,
    }

    # This is a historical receipt, so never compare it to the moving live
    # source.  Pin the reviewed identities literally while allowing a future
    # mcbot edit to report drift instead of forcing evidence rewriting.
    assert receipt["base"] == {
        "git": "093ec33d8d9e137d276b84ffd907ca4417ba44af",
        "mcbot_sha256": (
            "45a82f44b95d1bce5126c63b1a5af6baaed54270aca9d55677b2e0bbb9c9d957"
        ),
    }
    assert receipt["head"] == {
        "implementation_git": "fe97a1f341e28d9c890cd46eaaf1a28665756db9",
        "mcbot_sha256": (
            "f88b7ad9060132b4abfb76000845618aaafe95ee18ad6d548bb7eeb868b18ebe"
        ),
    }
    assert receipt["design"]["pairs"] == len(receipt["records"]) == 6
    assert [row["seed"] for row in receipt["records"]] == \
        receipt["design"]["seeds"]
    assert [row["order"] for row in receipt["records"]] == [
        "base_head", "head_base", "base_head",
        "head_base", "base_head", "head_base",
    ]
    assert all(row["base"]["transcript_sha256"] ==
               row["head"]["transcript_sha256"]
               for row in receipt["records"])
    assert all(row["base"]["rollouts"] == row["head"]["rollouts"]
               for row in receipt["records"])
    for row in receipt["records"]:
        for field in ("short_search_decisions", "zero_world_decisions"):
            assert row["base"][field] == row["head"][field] == [0, 0, 0, 0]

    base = [row["base"]["elapsed_seconds"] for row in receipt["records"]]
    head = [row["head"]["elapsed_seconds"] for row in receipt["records"]]
    relative = [(left - right) / left for left, right in zip(base, head)]
    paired_mean = statistics.mean(relative)
    paired_se = statistics.stdev(relative) / math.sqrt(len(relative))
    critical = receipt["design"]["one_sided_t95_df5"]
    aggregate = receipt["aggregate"]
    assert sum(base) == pytest.approx(aggregate["base_wall_seconds"], abs=1e-12)
    assert sum(head) == pytest.approx(aggregate["head_wall_seconds"], abs=1e-12)
    assert 100 * (sum(base) - sum(head)) / sum(base) == pytest.approx(
        aggregate["wall_reduction_percent"], abs=1e-12)
    assert 100 * (sum(base) / sum(head) - 1) == pytest.approx(
        aggregate["throughput_increase_percent"], abs=1e-12)
    assert 100 * paired_mean == pytest.approx(
        aggregate["paired_relative_mean_percent"], abs=1e-12)
    assert 100 * (paired_mean - critical * paired_se) == pytest.approx(
        aggregate["paired_one_sided_95_lb_percent"], abs=1e-12)
