"""Release 49: the shipping ``fly.toml`` serves board combo3 arm Y, release 48 plus two lead rules.

Y adds two lines to release 48's environment: the singleton challenger
(``SHENGJI_PV_SINGLETON_CHALLENGER = '1'``, which registers the served name with
the ``-sc8`` suffix and builds `SingletonChallengerBuryBot`) and the held-out lead
confirmation at 32 (``SHENGJI_PV_LEAD_CONFIRM = '32'``, token ``lcc32``).  Every
other line is release 48's, so release 48's env is this one with those two lines
removed and the release-48 name restored (``release48_env``, the documented
rollback).

The served bot is built from the repo's ``fly.toml`` environment exactly as the
server builds it: the env in the process, the registry's import-time
registration (``_register_pv_search_from_env``, which registers the ``-sc8`` name
when the challenger is on) and ``make_bot(SHENGJI_BOT)``, on the hash-pinned
production and S58 belief packages.  One served lead goes through
the server's own snapshot and commit path with the real belief model, and both
rules run on it.  The package tests fail, never skip, under
``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI package-gate step, which runs
``SHENGJI_FAST=1`` on the compiled engine, the image's runtime).
"""
import asyncio
import copy
import os
import random

import pytest

from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA  # noqa: F401
from test_pv_search_serving import _play_state
from test_release46_fly_config import RELEASE49_ADDED_KEYS, fly_env
from test_release48_fly_config import (BELIEF_SHA, BELIEF_TEMPERATURE, LATENCY_KEYS, R48_CANDIDATE_CHANGES,
                                       RELEASE48, apply_to_process, local_env, release48_env,
                                       pinned_release48_belief_package)  # noqa: F401
from native_switches import NATIVE_OFF

#: the arm-Y name combo3y and combo3yc screened (#1075 issuecomment-6475680068, -6479431994)
RELEASE49 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-"
             "xfcompactlevel-lcc32-r9f8f5c05-bury-hybrid-bwv-d12d7acfc860-sc8")
#: the two lines release 49 adds to release 48's env
Y_CHANGES = {"SHENGJI_PV_SINGLETON_CHALLENGER": "1", "SHENGJI_PV_LEAD_CONFIRM": "32"}


def served_bot(path, belief_path, monkeypatch, *, env=None, seed=17):
    """``(name, bot)`` built as the server builds it, with ``env`` (production's by
    default) mapped to the local packages and exported into the process: the
    registry's import-time pv-search registration, then ``make_bot(SHENGJI_BOT)``.
    The registry is a scratch copy, so no name leaks into other tests."""
    from shengji.ai import registry

    env = local_env(path, belief_path, fly_env() if env is None else env)
    for key in list(os.environ):
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.delenv(key)
    apply_to_process(monkeypatch, env)
    monkeypatch.setattr(registry, "REGISTRY", {k: v for k, v in registry.REGISTRY.items()
                                               if not k.startswith("pv-search-")})
    registry._register_pv_search_from_env()
    name = env["SHENGJI_BOT"]
    return name, registry.make_bot(name, seed=seed)


def test_fly_toml_is_release48_plus_y():
    env = fly_env()
    assert set(Y_CHANGES) == set(RELEASE49_ADDED_KEYS)
    assert {k: env[k] for k in Y_CHANGES} == Y_CHANGES
    assert env["SHENGJI_BOT"] == RELEASE49
    # every other line is release 48's
    r48 = release48_env(env)
    assert set(env) - set(r48) == set(Y_CHANGES)
    assert {k: v for k, v in env.items() if k not in Y_CHANGES and k != "SHENGJI_BOT"} == \
        {k: v for k, v in r48.items() if k != "SHENGJI_BOT"}
    assert r48["SHENGJI_BOT"] == RELEASE48
    assert {k: r48[k] for k in R48_CANDIDATE_CHANGES} == R48_CANDIDATE_CHANGES
    # no other candidate knob rides along
    for key in ("SHENGJI_PV_WIDE_LEAD_ADMISSION", "SHENGJI_PV_WIDE_LEAD_K", "SHENGJI_PV_LEAF_GREEDY_TOP",
                "SHENGJI_PV_TREE_SIMS", "SHENGJI_PV_ADAPTIVE_WORLDS", "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS",
                "SHENGJI_PV_SINGLE_CANDIDATE_FAST", "SHENGJI_PV_BELIEF_LOG"):
        assert key not in env
    assert (env["SHENGJI_PV_WORLDS"], env["SHENGJI_PV_CANDIDATES"]) == ("64", "8")
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_PV_LEAF_GREEDY_DEADLINE"] == "2"
    assert env["SHENGJI_FAST"] == "1" and env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"


def test_served_bot_is_arm_y(pinned_production_package, pinned_release48_belief_package, monkeypatch):
    from shengji.ai.endgame_compact import default_backend
    from shengji.eval.served_config import registry_name
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    env = local_env(pinned_production_package, pinned_release48_belief_package, fly_env())
    assert registry_name(env) == RELEASE49
    name, bot = served_bot(pinned_production_package, pinned_release48_belief_package, monkeypatch)
    assert name == bot.policy_name == RELEASE49
    assert isinstance(bot, SingletonChallengerBuryBot) and bot.checkpoint_sha256 == PACKAGE_SHA
    # Y's two rules
    assert bot.lead_confirm == 32 and bot.config.lead_confirm == 32
    assert not (bot.admit_forced_single or bot.finish_lead_admission or bot.small_joker_guard)
    assert not (bot.adaptive_worlds or bot.adaptive_worlds_leads or bot.wide_lead_admission)
    # release 48 underneath: S58 at its stored temperature, dtrx, the guarded greedy finish
    assert bot.belief_model is not None and bot.belief_model.package_sha256 == BELIEF_SHA
    assert bot.belief_model.temperature == BELIEF_TEMPERATURE and bot.belief_log is True
    assert bot.doomed_throw_reselect is True and bot.doomed_throw_reselect_exact_guard is True
    assert (bot.leaf_greedy_finish, bot.leaf_greedy_finish_exact_skip,
            bot.leaf_greedy_deadline_ms) == (True, True, 2000)
    assert (bot.world_history_legal, bot.world_history_draw, bot.belief_worlds) == (True, True, True)
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (True, 7, True)
    assert (bot.exact_follow_solver, bot.exact_follow_max_cards,
            bot.exact_follow_max_nodes) == ("compact-level", 7, 50_000_000)
    assert (bot.value_declare, bot.value_declare_every_first) == (True, True)
    assert (bot.worlds, bot.candidates, bot.bury_wide_value, bot.bury_wide_k) == (64, 8, True, 64)
    assert bot.serving_budget_seconds == 3.0
    # every latency switch on, as the process environment sets them
    for attr in LATENCY_KEYS:
        assert getattr(bot, attr) is True
    assert bot.single_candidate_fast is False
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    assert default_backend() == expected


def test_healthz_reports_the_latency_switches_with_y(pinned_production_package, monkeypatch):
    from shengji.api import server as srv

    monkeypatch.setenv("SHENGJI_PV_CKPT", str(pinned_production_package))
    apply_to_process(monkeypatch, {k: fly_env()[k] for k in (*LATENCY_KEYS.values(), *Y_CHANGES)})
    health = srv._pv_search_health()
    assert health["sha256"] == PACKAGE_SHA
    assert health["latency_switches"] == {
        "encode_prefix_cache": True, "single_candidate_fast": False,
        "leaf_greedy_stream": True, "encode_batch_fast": True, **{k: True for k in NATIVE_OFF}}


def test_served_lead_runs_both_rules_through_the_server_path(
        pinned_production_package, pinned_release48_belief_package, tmp_path, monkeypatch):
    """One lead by the served bot, built with fly.toml's [env] in the process
    environment, through ``_paced_bot_step`` / ``_commit_bot_turn``: the worlds are
    proposed by the real S58 belief model with no fallback, the singleton probe
    runs, and the lead confirmation runs to a completed status.

    The wall clocks are lifted so a slow or cold CI runner cannot turn this wiring
    witness into a timing test (an over-budget stage is a designed skip, tested on
    its own; serving latency is measured on the intended host)."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(pinned_production_package, pinned_release48_belief_package, monkeypatch, seed=7)
    assert name == RELEASE49
    assert bot.leaf_greedy_deadline_ms == 2000 and bot.serving_budget_seconds == 3.0
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    seat = rnd.turn
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R49", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        assert searched.policy_name == RELEASE49 and searched.lead_confirm == 32
        switches = {attr: getattr(searched, attr) for attr in LATENCY_KEYS}
        record = copy.deepcopy(searched.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)
        return record, switches

    record, switches = asyncio.run(scenario())
    assert switches == {attr: True for attr in LATENCY_KEYS}
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert record["worlds"] == 64
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    # sc8: the probe ran on this lead (its key is present on every lead the rule sees)
    assert "singleton_challenger_applied" in record
    # lcc32: the stage ran to a completed status on the served lead
    assert record["lead_confirm_status"] in ("applied", "rejected", "no_challenger", "no_pool")
    if record["lead_confirm_status"] in ("applied", "rejected", "no_challenger"):
        assert record["lead_confirm_screen_worlds"] == 32
    if record["lead_confirm_status"] in ("applied", "rejected"):
        assert record["lead_confirm_worlds"] == 128
    if record["lead_confirm_applied"]:
        assert sorted(record["played"]) == sorted(record["lead_confirm_to"])


def test_rollback_to_release48_drops_the_two_lines(
        pinned_production_package, pinned_release48_belief_package, monkeypatch):
    from shengji.train import pv_search_policy as pv

    env = release48_env(fly_env())
    assert not set(Y_CHANGES) & set(env)
    name, bot = served_bot(pinned_production_package, pinned_release48_belief_package, monkeypatch, env=env)
    assert name == env["SHENGJI_BOT"] == RELEASE48
    assert type(bot) is pv.PVSearchBuryBot
    assert bot.lead_confirm == 0
    assert bot.belief_model.package_sha256 == BELIEF_SHA
    for attr in LATENCY_KEYS:
        assert getattr(bot, attr) is True
