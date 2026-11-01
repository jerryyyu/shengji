"""Release 48, the rollback of release 49: the candidate of the guarded R48 cloud screen.

The candidate is release 46 with three changes: the hidden hands are proposed by
the S58 belief package ``s58-e6-42444515`` (served at its stored temperature) in
place of S17's; the doomed-throw re-select's exact-stage guard (``-dtrx``) is on;
and the value leaf is finished greedily (``-lgf``), except on decisions an exact
stage is eligible for (``-lgfx``), with a 2 s deadline on the finish
(``-lgfd2000``).  Three latency switches (``SHENGJI_PV_ENCODE_PREFIX_CACHE``,
``SHENGJI_PV_LEAF_GREEDY_STREAM``, ``SHENGJI_PV_ENCODE_BATCH_FAST``) enter no
name or digest and are read from the process environment where the bot is
built, so they are witnessed here through the process environment, as the
server reads them.

Release 49 adds two lines (``RELEASE49_ADDED_KEYS``), so release 48's env is the
repo's ``fly.toml`` environment with them removed and the release-48 name restored
(``release48_env``, the documented rollback).  The served bot is built from that
environment exactly as the server builds it (``pv_env_recipe`` -> ``pv_registry_entries`` -> the factory)
on the hash-pinned production and belief packages, and one served play goes
through the server's own snapshot and commit path with the real belief model.
The package tests fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the
CI package-gate step, which runs ``SHENGJI_FAST=1`` on the compiled engine, the
image's runtime).
"""
import asyncio
import copy
import hashlib
import os
import random
from pathlib import Path

import pytest

from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA, REQUIRE_PACKAGE  # noqa: F401
from test_pv_search_serving import _play_state
from test_release46_fly_config import (BELIEF_SHA as RELEASE46_BELIEF_SHA, DTRX_FLAG, RELEASE46,
                                       RELEASE48_ADDED_KEYS, RELEASE49_ADDED_KEYS, V92_CANDIDATE_ENV,
                                       fly_env as production_env, pinned_belief_package,
                                       release46_env)  # noqa: F401
from native_switches import NATIVE_OFF

#: the candidate name of the guarded R48 cloud screen (arms.candidate.name of its plan)
RELEASE48 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-"
             "lgfd2000-ed7-xf7-xfcompactlevel-rc252e656-bury-hybrid-bwv-cd6dd3d2b02a")
BELIEF_SHA = "424445158f3392b57e40bb23e13a923009d734530d5253958d5c541a0d2a259e"
BELIEF_VOLUME_PATH = "/data/models/s58-e6-42444515.npz"
#: the package's stored calibration temperature, served as is (no env knob overrides it)
BELIEF_TEMPERATURE = 1.0129481491372179
LATENCY_KEYS = {"encode_prefix_cache": "SHENGJI_PV_ENCODE_PREFIX_CACHE",
                "leaf_greedy_stream": "SHENGJI_PV_LEAF_GREEDY_STREAM",
                "encode_batch_fast": "SHENGJI_PV_ENCODE_BATCH_FAST",
                "encode_native": "SHENGJI_PV_ENCODE_NATIVE",
                "legal_native": "SHENGJI_PV_LEGAL_NATIVE",
                "leaf_cache_release": "SHENGJI_PV_LEAF_CACHE_RELEASE",
                "leaf_clone_fast": "SHENGJI_PV_LEAF_CLONE_FAST",
                "leaf_trick_cache": "SHENGJI_PV_LEAF_TRICK_CACHE",
                "world_fast": "SHENGJI_PV_WORLD_FAST"}
#: what the screen's candidate arm changed on release 46 (its comparator), with the
#: belief package at its Fly volume path (the screen host's copy had the same sha256)
R48_CANDIDATE_CHANGES = {"SHENGJI_PV_BELIEF_CKPT": BELIEF_VOLUME_PATH,
                         "SHENGJI_PV_BELIEF_SHA256": BELIEF_SHA,
                         DTRX_FLAG: "1",
                         "SHENGJI_PV_LEAF_GREEDY_FINISH": "1",
                         "SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP": "1",
                         "SHENGJI_PV_LEAF_GREEDY_DEADLINE": "2",
                         **{key: "1" for key in LATENCY_KEYS.values()}}
BELIEF_PACKAGE = os.environ.get("SHENGJI_PV_BELIEF48_PACKAGE_PATH")


def release48_env(env: dict) -> dict:
    """Production's env with release 49's rollback applied: its two lines removed and
    the release-48 name restored."""
    env = {k: v for k, v in env.items() if k not in RELEASE49_ADDED_KEYS}
    env["SHENGJI_BOT"] = RELEASE48
    return env


def fly_env() -> dict:
    """Release 48's ``fly.toml`` ``[env]``: the repo's, rolled back from release 49."""
    return release48_env(production_env())


@pytest.fixture(scope="module")
def pinned_release48_belief_package(pinned_production_package):
    """The hash-pinned S58 belief package named by ``SHENGJI_PV_BELIEF48_PACKAGE_PATH``
    (CI fetches it from the ``serving-packages`` release); missing FAILS under
    ``SHENGJI_REQUIRE_PV_PACKAGE=1``, like the production package."""
    if not BELIEF_PACKAGE:
        if REQUIRE_PACKAGE:
            pytest.fail("SHENGJI_REQUIRE_PV_PACKAGE=1 but SHENGJI_PV_BELIEF48_PACKAGE_PATH is unset")
        pytest.skip("set SHENGJI_PV_BELIEF48_PACKAGE_PATH (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
    path = Path(BELIEF_PACKAGE)
    if not path.exists():
        pytest.fail(f"pinned belief package is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == BELIEF_SHA, f"belief package is {actual[:12]}, not the pinned {BELIEF_SHA[:12]}"
    return path


def local_env(path, belief_path, env=None) -> dict:
    """``env`` (production's by default) with the volume paths mapped to local copies."""
    env = fly_env() if env is None else env
    return {**env, "SHENGJI_PV_CKPT": str(path), "SHENGJI_PV_SHA256": PACKAGE_SHA,
            "SHENGJI_PV_BELIEF_CKPT": str(belief_path)}


def served_entries(path, belief_path, env=None):
    from shengji.train import pv_search_policy as pv

    env = fly_env() if env is None else env
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(local_env(path, belief_path, env)))
    name, = entries
    return env, name, entries[name]


def apply_to_process(monkeypatch, env: dict) -> None:
    """Export ``env`` into the process environment as Fly does at boot.  The engine
    switch and the log directory are left to the test process: the engine is chosen
    at import (the run's own ``--engine``) and logs go to the test's tmp path."""
    for key, value in env.items():
        if key not in ("SHENGJI_FAST", "SHENGJI_LOG_DIR"):
            monkeypatch.setenv(key, str(value))


def test_fly_toml_is_release46_plus_the_r48_changes():
    env = fly_env()
    assert {k: env[k] for k in R48_CANDIDATE_CHANGES} == R48_CANDIDATE_CHANGES
    assert set(R48_CANDIDATE_CHANGES) == set(RELEASE48_ADDED_KEYS) | {
        "SHENGJI_PV_BELIEF_CKPT", "SHENGJI_PV_BELIEF_SHA256"}
    assert env["SHENGJI_BOT"] == RELEASE48
    # every other line is release 46's
    def rest(e):
        return {k: v for k, v in e.items() if k not in R48_CANDIDATE_CHANGES and k != "SHENGJI_BOT"}
    r46 = release46_env(env)
    assert rest(env) == rest(r46)
    assert {k: r46[k] for k in V92_CANDIDATE_ENV} == V92_CANDIDATE_ENV
    assert RELEASE46_BELIEF_SHA != BELIEF_SHA
    # the belief log stays at its default (on); no temperature, width or DEV knob is set
    for key in ("SHENGJI_PV_BELIEF_LOG", "SHENGJI_PV_EXACT_LEAD_TIE_BASELINE",
                "SHENGJI_PV_EXACT_LEAD_POLICY_FIRST", "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY",
                "SHENGJI_PV_EXACT_LEAD_MAX_SECONDS", "SHENGJI_PV_EXACT_DEEP_MAX_NODES",
                "SHENGJI_PV_SINGLE_CANDIDATE_FAST", "SHENGJI_PV_EXACT_WORLD_SUBSET",
                "SHENGJI_PV_BURY_KITTY_CHARGE", "SHENGJI_PV_BURY_WIDE_SWAPS"):
        assert key not in env
    assert not [k for k in env if "TEMPERATURE" in k]
    # release 46's unchanged budgets and widths on the compiled engine; packages on the volume
    assert (env["SHENGJI_PV_WORLDS"], env["SHENGJI_PV_CANDIDATES"]) == ("64", "8")
    assert env["SHENGJI_PV_EXACT_DEEP_CARDS"] == env["SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS"] == "7"
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_FAST"] == "1"
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["SHENGJI_PV_CKPT"].startswith("/data/models/")


def test_served_bot_is_the_r48_candidate(pinned_production_package, pinned_release48_belief_package):
    from shengji.ai.endgame_compact import default_backend
    from shengji.train.pv_search_policy import PVSearchBuryBot

    env, name, factory = served_entries(pinned_production_package, pinned_release48_belief_package)
    assert name == env["SHENGJI_BOT"] == RELEASE48
    bot = factory(seed=17)
    assert isinstance(bot, PVSearchBuryBot) and bot.checkpoint_sha256 == PACKAGE_SHA
    # the S58 belief model at its stored temperature
    assert bot.belief_model is not None and bot.belief_model.package_sha256 == BELIEF_SHA
    assert bot.config.belief_sha256 == BELIEF_SHA and bot.belief_log is True
    assert bot.belief_model.temperature == BELIEF_TEMPERATURE
    assert bot.belief_model.config["d"] == 192
    # dtrx on the re-select
    assert bot.doomed_throw_reselect is True
    assert bot.doomed_throw_reselect_exact_guard is True
    assert bot.config.doomed_throw_reselect_exact_guard is True
    # the guarded greedy finish: lgf, its exact-stage yield and the 2000 ms deadline
    assert (bot.leaf_greedy_finish, bot.leaf_greedy_finish_exact_skip,
            bot.leaf_greedy_deadline_ms) == (True, True, 2000)
    assert (bot.config.leaf_greedy_finish, bot.config.leaf_greedy_finish_exact_skip,
            bot.config.leaf_greedy_deadline_ms) == (True, True, 2000)
    # release 46 underneath
    assert (bot.world_history_legal, bot.world_history_draw, bot.belief_worlds) == (True, True, True)
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (True, 7, True)
    assert (bot.exact_follow_solver, bot.exact_follow_max_cards,
            bot.exact_follow_max_nodes) == ("compact-level", 7, 50_000_000)
    assert (bot.exact_lead_tie_baseline, bot.exact_lead_policy_first) == (False, False)
    assert (bot.value_declare, bot.value_declare_every_first) == (True, True)
    assert (bot.worlds, bot.candidates, bot.bury_wide_value, bot.bury_wide_k) == (64, 8, True, 64)
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    assert default_backend() == expected


def test_latency_switches_are_on_through_the_process_environment(
        pinned_production_package, pinned_release48_belief_package, monkeypatch):
    """fly.toml's [env] exported into the process, as Fly does: the switches the
    server reads (``latency_switches()``) and the built bot's attributes are on,
    the single-candidate switch is off, and the name is unchanged by them."""
    from shengji.train import pv_search_policy as pv

    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    env = local_env(pinned_production_package, pinned_release48_belief_package)
    plain = served_entries(pinned_production_package, pinned_release48_belief_package)[2](seed=17)
    assert not set(LATENCY_KEYS) & set(vars(plain))
    apply_to_process(monkeypatch, env)
    assert pv.latency_switches() == {"encode_prefix_cache": True, "single_candidate_fast": False,
                                     "leaf_greedy_stream": True, "encode_batch_fast": True, **{k: True for k in NATIVE_OFF}}
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(dict(os.environ)))
    name, = entries
    assert name == RELEASE48
    bot = entries[name](seed=17)
    for attr in LATENCY_KEYS:
        assert getattr(bot, attr) is True and vars(bot)[attr] is True
    assert bot.single_candidate_fast is False


def test_served_play_takes_the_belief_proposal_through_the_server_path(
        pinned_production_package, pinned_release48_belief_package, tmp_path, monkeypatch):
    """One play by the served bot, built with fly.toml's [env] in the process
    environment, through ``_paced_bot_step`` / ``_commit_bot_turn``: the worlds are
    proposed by the real S58 belief model with no fallback and the snapshot the
    server searches with carries the latency switches.

    The proposal's wall-clock preparation cap is lifted here so a slow or cold CI
    runner cannot turn this wiring witness into a timing test: an over-cap
    preparation is a belief error, whose fallback to the history-legal draw is
    tested on its own, and serving latency is measured on the intended host."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    apply_to_process(monkeypatch, local_env(pinned_production_package, pinned_release48_belief_package))
    _, name, factory = served_entries(pinned_production_package, pinned_release48_belief_package)
    bot = factory(seed=7)
    rnd = _play_state()
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R48", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        switches = {attr: getattr(searched, attr) for attr in LATENCY_KEYS}
        record = copy.deepcopy(searched.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)
        return record, switches

    record, switches = asyncio.run(scenario())
    assert switches == {attr: True for attr in LATENCY_KEYS}
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert name == RELEASE48
    assert record["worlds"] == 64
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64, {k: v for k, v in record.items() if k.startswith("belief") and k != "belief_snapshot"}
    assert record["belief_log"] == 1
    # the deadline's record fields are present (the deadline is on)
    assert "leaf_greedy_deadline_fired" in record and "leaf_greedy_deadline_cut_leaves" in record


def test_healthz_reports_the_latency_switches(pinned_production_package, monkeypatch):
    from shengji.api import server as srv

    for key in LATENCY_KEYS.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SHENGJI_PV_CKPT", str(pinned_production_package))
    off = srv._pv_search_health()
    assert off["sha256"] == PACKAGE_SHA
    assert off["latency_switches"] == {"encode_prefix_cache": False, "single_candidate_fast": False,
                                       "leaf_greedy_stream": False, "encode_batch_fast": False, **NATIVE_OFF}
    apply_to_process(monkeypatch, {k: fly_env()[k] for k in LATENCY_KEYS.values()})
    assert srv._pv_search_health()["latency_switches"] == {
        "encode_prefix_cache": True, "single_candidate_fast": False,
        "leaf_greedy_stream": True, "encode_batch_fast": True, **{k: True for k in NATIVE_OFF}}


def test_rollback_to_release46_restores_the_belief_pair_and_drops_the_r48_lines(
        pinned_production_package, pinned_belief_package, monkeypatch):
    from shengji.train import pv_search_policy as pv

    env = release46_env(fly_env())
    assert not set(RELEASE48_ADDED_KEYS) & set(env)
    assert {k: env[k] for k in V92_CANDIDATE_ENV} == V92_CANDIDATE_ENV
    # rolled back with its env in the process: no latency switch survives the rollback
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    apply_to_process(monkeypatch, local_env(pinned_production_package, pinned_belief_package, env))
    assert not any(pv.latency_switches().values())
    env, name, factory = served_entries(pinned_production_package, pinned_belief_package, env=env)
    assert name == env["SHENGJI_BOT"] == RELEASE46
    bot = factory(seed=17)
    assert bot.belief_model.package_sha256 == RELEASE46_BELIEF_SHA
    assert bot.doomed_throw_reselect_exact_guard is False and bot.doomed_throw_reselect is True
    assert (bot.leaf_greedy_finish, bot.leaf_greedy_finish_exact_skip,
            bot.leaf_greedy_deadline_ms) == (False, False, 0)
    assert not {"encode_prefix_cache", "leaf_greedy_stream", "encode_batch_fast"} & set(vars(bot))
