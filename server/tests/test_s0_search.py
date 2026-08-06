"""Falsifying contracts for the S0 report-fold/search package."""
from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.ai.memory import Memory
from shengji.ai.mcbot import restore_random_state
from shengji.ai.registry import S0_REPORT_WORLDS, make_bot
from shengji.api.server import _log_play
from shengji.rl.replay_log import rebuild_round


FIXTURE = Path(__file__).with_name("data") / "mc_override_variance.json"


def incident_state():
    fx = json.loads(FIXTURE.read_text())
    events, seat = fx["events"], fx["seat"]
    rnd = rebuild_round(events)
    for event in events:
        if event["e"] != "play":
            continue
        if (rnd.trick is None or not rnd.trick.plays) and event["seat"] == seat:
            break
        rnd.play(event["seat"], list(event["cards"]))
    return rnd, seat


def partial_report(*args, seed, **kwargs):
    """Tempt the decision rule with a huge gain on an incomplete fold."""
    return {"gap": 100.0, "se": 0.0, "worlds": 2, "attempts": 1200,
            "rejected": 1198, "complete": False, "seed": seed}


def fixed_report(gap):
    def report(*args, seed, **kwargs):
        return {"gap": float(gap), "se": 0.0,
                "worlds": S0_REPORT_WORLDS,
                "attempts": S0_REPORT_WORLDS, "rejected": 0,
                "complete": True, "seed": seed}
    return report


def test_every_early_exit_clears_all_previous_decision_state(monkeypatch):
    rnd, seat = incident_state()
    bot = make_bot("mc-strong", seed=1)

    for name in ("last_decision_record", "last_override_stats", "last_alloc"):
        setattr(bot, name, {"stale": name})
    bot.TRACTOR_LOCK = False
    monkeypatch.setattr(bot, "_candidates", lambda _rnd, _seat: [["SA"]])
    assert bot.decide_play(rnd, seat) == ["SA"]
    assert bot.last_decision_record is None
    assert bot.last_override_stats is None
    assert bot.last_alloc is None

    for name in ("last_decision_record", "last_override_stats", "last_alloc"):
        setattr(bot, name, {"stale": name})
    bot.TRACTOR_LOCK = True
    monkeypatch.setattr(bot, "canonical_lead",
                        lambda _rnd, _seat: ["SA", "SA", "SK", "SK"])
    monkeypatch.setattr(bot, "_candidates", lambda *_: pytest.fail(
        "tractor-lock should return before candidate generation"))
    assert bot.decide_play(rnd, seat) == ["SA", "SA", "SK", "SK"]
    assert bot.last_decision_record is None
    assert bot.last_override_stats is None
    assert bot.last_alloc is None


def test_json_logged_rng_state_replays_the_exact_decision():
    rnd, seat = incident_state()
    first = make_bot("mc-strong", seed=238)
    play1 = first.decide_play(rnd, seat)
    record = json.loads(json.dumps(first.last_decision_record))

    replay = make_bot("mc-strong", seed=999)
    restore_random_state(replay.rng, record["rng_state"])
    play2 = replay.decide_play(rnd, seat)
    assert play2 == play1
    assert replay.last_decision_record["means"] == \
        first.last_decision_record["means"]
    assert replay.last_decision_record["n_by_candidate"] == \
        first.last_decision_record["n_by_candidate"]


def test_live_record_binds_policy_code_ballot_and_actual_play():
    rnd, seat = incident_state()
    bot = make_bot("mc-strong", seed=238)
    played = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert rec["policy"] == "mc-strong"
    assert len(rec["code"]["mcbot_sha256"]) == 64
    assert rec["code"]["git_sha"]
    assert len(rec["ballot"]["digest"]) == 12
    assert sorted(rec["played"]) == sorted(played)
    assert rec["played_index"] != rec["raw_winner_index"] or \
        rec["reason"] == "search_override"


def test_server_refuses_a_record_that_names_a_different_play():
    room = SimpleNamespace(
        bot=SimpleNamespace(last_decision_record={"played": ["SA"]}),
        log_event=lambda *args, **kwargs: pytest.fail("must fail before logging"),
        round=None,
    )
    with pytest.raises(RuntimeError, match="record/play mismatch"):
        _log_play(room, 0, ["DJ"], True, None)


def test_incident_report_fold_is_complete_disjoint_and_fully_accounted():
    rnd, seat = incident_state()
    bot = make_bot("mc-s0-report-lcb", seed=238)
    played = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert played == ["SA", "SA", "SK"]
    assert rec["reason"] == "report_lcb_below_min_gain"
    assert rec["report_fold"]["complete"] is True
    assert rec["report_fold"]["worlds"] == S0_REPORT_WORLDS
    assert rec["report_fold"]["seed"] == rec["report_seed"]
    assert rec["work"]["report_rollouts"] == 2 * S0_REPORT_WORLDS
    assert rec["work"]["total_rollouts"] == rec["work"]["total_budget"]
    assert bot.rollouts == rec["work"]["total_rollouts"]
    delta = rec["sampler_counters"]["delta"]
    assert delta["sample_attempts"] == \
        delta["accepted_worlds"] + delta["failed_worlds"]
    assert delta["accepted_worlds"] == \
        bot.N_DETERMINIZATIONS + S0_REPORT_WORLDS
    assert rec["search_secs"] <= bot.search_secs


def test_an_underfilled_report_fold_can_never_override(monkeypatch):
    rnd, seat = incident_state()
    bot = make_bot("mc-s0-report-lcb", seed=238)
    monkeypatch.setattr(bot, "_report_fold_gap", partial_report)
    played = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert played == rec["candidates"][0]
    assert rec["reason"] == "report_underfilled"
    assert rec["work"]["complete"] is False
    assert bot.short_search_decisions == 1


@pytest.mark.parametrize("gap,overrides", [(2.0, True), (-2.0, False)])
def test_report_lcb_must_override_a_certain_gain_and_refuse_a_loss(
        monkeypatch, gap, overrides):
    rnd, seat = incident_state()
    bot = make_bot("mc-s0-report-lcb", seed=238)
    monkeypatch.setattr(bot, "_report_fold_gap", fixed_report(gap))
    played = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    if overrides:
        assert rec["played_index"] == rec["report_candidate_index"] != 0
        assert rec["reason"] == "report_lcb_override"
    else:
        assert rec["played_index"] == 0
        assert rec["reason"] == "report_lcb_below_min_gain"
    assert sorted(rec["played"]) == sorted(played)


def test_adaptive_random_and_uniform_controls_have_exact_matched_work():
    rnd, seat = incident_state()
    records = {}
    for name in ("mc-s0-report-lcb", "mc-s0-adaptive", "mc-s0-random",
                 "mc-s0-uniform-work"):
        bot = make_bot(name, seed=238)
        bot.decide_play(rnd, seat)
        rec = bot.last_decision_record
        assert rec["work"]["complete"] is True
        assert rec["work"]["total_rollouts"] == bot.rollouts
        records[name] = rec
    budgets = {rec["work"]["total_budget"] for rec in records.values()}
    assert len(budgets) == 1, f"S0 controls are not equal-work: {budgets}"
    assert records["mc-s0-adaptive"]["alloc"]["mode"] == \
        "deterministic_adaptive"
    assert records["mc-s0-random"]["alloc"]["mode"] == "random_adaptive"
    assert records["mc-s0-adaptive"]["sampler_counters"]["delta"][
        "accepted_worlds"] >= 30 + S0_REPORT_WORLDS


@pytest.mark.parametrize("name", ["mc-s0-adaptive", "mc-s0-random"])
def test_s0_allocation_and_report_streams_reproduce(name):
    rnd, seat = incident_state()
    a, b = make_bot(name, seed=44), make_bot(name, seed=44)
    pa, pb = a.decide_play(rnd, seat), b.decide_play(rnd, seat)
    assert pa == pb
    assert a.last_decision_record["alloc"] == b.last_decision_record["alloc"]
    assert a.last_decision_record["report_fold"] == \
        b.last_decision_record["report_fold"]


def test_report_helper_refuses_a_completely_failed_sampler(monkeypatch):
    rnd, seat = incident_state()
    bot = make_bot("mc-s0-report-lcb", seed=1)
    mem = Memory(rnd, seat, own_kitty=True)
    monkeypatch.setattr(bot, "_sample_hands", lambda *args: None)
    result = bot._report_fold_gap(
        rnd, seat, mem, rnd.is_attacker(seat), ["DJ"], ["SA", "SA", "SK"],
        30, seed=123)
    assert result["complete"] is False and result["worlds"] == 0
    assert result["attempts"] == 30 * bot.SAMPLE_ATTEMPT_FACTOR
    assert result["se"] == float("inf")


def test_restore_random_state_accepts_live_tuple_and_json_lists():
    source = random.Random(7)
    live = source.getstate()
    decoded = json.loads(json.dumps(live))
    a, b = random.Random(), random.Random()
    restore_random_state(a, live)
    restore_random_state(b, decoded)
    assert [a.random() for _ in range(10)] == [b.random() for _ in range(10)]
