"""Release 47: the shipping ``fly.toml`` serves the candidate screened as v98combo.

The candidate is release 46 with two changes: the hidden hands are proposed by the
S46 r3 belief package ``s46-e2-36e2024e`` (served at its stored temperature) in
place of S17's, and the doomed-throw re-select's exact-stage guard (``-dtrx``) is
on.  The served bot is built from the repo's ``fly.toml`` environment exactly as
the server builds it (``pv_env_recipe`` -> ``pv_registry_entries`` -> the
factory) on the hash-pinned production and belief packages, so the registry name,
the bound belief model, the guard and everything release 46 serves are witnessed
on this tree, and one served play goes through the server's own snapshot and
commit path with the real belief model.  The package tests fail, never skip, under
``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI package-gate step, which runs
``SHENGJI_FAST=1`` on the compiled engine, the image's runtime).
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
                                       V92_CANDIDATE_ENV, fly_env, pinned_release46_belief_package,  # noqa: F401
                                       release46_env)

#: the candidate name v98combo screened (#1075 issuecomment-6300257249)
RELEASE47 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-ed7-xf7-"
             "xfcompactlevel-r8ef724b5-bury-hybrid-bwv-7cdf6f0d4232")
BELIEF_SHA = "36e2024e36884906099727212ddd7f870ff39e961c42f58a9cf7eb445c65a3ac"
BELIEF_VOLUME_PATH = "/data/models/s46-e2-36e2024e.npz"
#: the package's stored calibration temperature, served as is (no env knob overrides it)
BELIEF_TEMPERATURE = 1.0071070111258198
#: what v98combo's candidate arm changed on release 46, with the belief package at its
#: Fly volume path (the screen host's copy had the same sha256)
V98_CANDIDATE_CHANGES = {"SHENGJI_PV_BELIEF_CKPT": BELIEF_VOLUME_PATH,
                         "SHENGJI_PV_BELIEF_SHA256": BELIEF_SHA,
                         DTRX_FLAG: "1"}
BELIEF_PACKAGE = os.environ.get("SHENGJI_PV_BELIEF_PACKAGE_PATH")


@pytest.fixture(scope="module")
def pinned_belief_package(pinned_production_package):
    """The hash-pinned S46 r3 belief package named by ``SHENGJI_PV_BELIEF_PACKAGE_PATH``
    (CI fetches it from the ``serving-packages`` release); missing FAILS under
    ``SHENGJI_REQUIRE_PV_PACKAGE=1``, like the production package."""
    if not BELIEF_PACKAGE:
        if REQUIRE_PACKAGE:
            pytest.fail("SHENGJI_REQUIRE_PV_PACKAGE=1 but SHENGJI_PV_BELIEF_PACKAGE_PATH is unset")
        pytest.skip("set SHENGJI_PV_BELIEF_PACKAGE_PATH (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
    path = Path(BELIEF_PACKAGE)
    if not path.exists():
        pytest.fail(f"pinned belief package is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == BELIEF_SHA, f"belief package is {actual[:12]}, not the pinned {BELIEF_SHA[:12]}"
    return path


def served_entries(path, belief_path, env=None):
    from shengji.train import pv_search_policy as pv

    env = fly_env() if env is None else env
    recipe = pv.pv_env_recipe({**env, "SHENGJI_PV_CKPT": str(path),
                               "SHENGJI_PV_SHA256": PACKAGE_SHA,
                               "SHENGJI_PV_BELIEF_CKPT": str(belief_path)})
    entries = pv.pv_registry_entries(**recipe)
    name, = entries
    return env, name, entries[name]


def test_fly_toml_is_release46_plus_the_v98combo_changes():
    env = fly_env()
    assert {k: env[k] for k in V98_CANDIDATE_CHANGES} == V98_CANDIDATE_CHANGES
    assert env["SHENGJI_BOT"] == RELEASE47
    # every other line is release 46's
    rest = {k: v for k, v in env.items() if k not in V98_CANDIDATE_CHANGES and k != "SHENGJI_BOT"}
    r46 = release46_env(env)
    assert rest == {k: v for k, v in r46.items() if k not in V98_CANDIDATE_CHANGES and k != "SHENGJI_BOT"}
    assert {k: r46[k] for k in V92_CANDIDATE_ENV} == V92_CANDIDATE_ENV
    assert RELEASE46_BELIEF_SHA != BELIEF_SHA
    # the belief log stays at its default (on); no temperature or DEV knob is set
    for key in ("SHENGJI_PV_BELIEF_LOG", "SHENGJI_PV_EXACT_LEAD_TIE_BASELINE",
                "SHENGJI_PV_EXACT_LEAD_POLICY_FIRST", "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY",
                "SHENGJI_PV_EXACT_LEAD_MAX_SECONDS", "SHENGJI_PV_EXACT_DEEP_MAX_NODES"):
        assert key not in env
    assert not [k for k in env if "TEMPERATURE" in k]
    # release 46's unchanged budgets on the compiled engine; both packages on the volume
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_FAST"] == "1"
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["SHENGJI_PV_CKPT"].startswith("/data/models/")


def test_served_bot_is_the_v98combo_candidate(pinned_production_package, pinned_belief_package):
    from shengji.ai.endgame_compact import default_backend
    from shengji.train.pv_search_policy import PVSearchBuryBot

    env, name, factory = served_entries(pinned_production_package, pinned_belief_package)
    assert name == env["SHENGJI_BOT"] == RELEASE47
    bot = factory(seed=17)
    assert isinstance(bot, PVSearchBuryBot) and bot.checkpoint_sha256 == PACKAGE_SHA
    # the S46 r3 belief model at its stored temperature
    assert bot.belief_model is not None and bot.belief_model.package_sha256 == BELIEF_SHA
    assert bot.config.belief_sha256 == BELIEF_SHA and bot.belief_log is True
    assert bot.belief_model.temperature == BELIEF_TEMPERATURE
    assert bot.belief_model.config["d"] == 192
    # dtrx on the re-select, as instance state and in the config
    assert bot.doomed_throw_reselect is True
    assert bot.doomed_throw_reselect_exact_guard is True
    assert bot.config.doomed_throw_reselect_exact_guard is True
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


def test_served_play_takes_the_belief_proposal_through_the_server_path(
        pinned_production_package, pinned_belief_package, tmp_path, monkeypatch):
    """One play by the served bot through ``_paced_bot_step`` / ``_commit_bot_turn``:
    the worlds are proposed by the real S46 r3 belief model with no fallback.

    The proposal's wall-clock preparation cap is lifted here so a slow or cold CI
    runner cannot turn this wiring witness into a timing test: an over-cap
    preparation is a belief error, whose fallback to the history-legal draw is
    tested on its own, and serving latency is measured on the intended host."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    _, name, factory = served_entries(pinned_production_package, pinned_belief_package)
    bot = factory(seed=7)
    rnd = _play_state()
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R47", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = copy.deepcopy(prepared.decision.snapshot.bot_copy.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)
        return record

    record = asyncio.run(scenario())
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert name == RELEASE47
    assert record["worlds"] == 64
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64, {k: v for k, v in record.items() if k.startswith("belief") and k != "belief_snapshot"}
    assert record["belief_log"] == 1


def test_rollback_to_release46_restores_the_belief_pair_and_drops_dtrx(
        pinned_production_package, pinned_release46_belief_package):
    env, name, factory = served_entries(pinned_production_package, pinned_release46_belief_package,
                                        env=release46_env(fly_env()))
    assert DTRX_FLAG not in env
    assert name == env["SHENGJI_BOT"] == RELEASE46
    bot = factory(seed=17)
    assert bot.belief_model.package_sha256 == RELEASE46_BELIEF_SHA
    assert bot.doomed_throw_reselect_exact_guard is False and bot.doomed_throw_reselect is True
