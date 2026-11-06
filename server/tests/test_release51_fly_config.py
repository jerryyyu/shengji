"""Release 51: the shipping ``fly.toml`` serves release 50 with the lead confirmation off.

Release 51 changes one value in release 50's environment and nothing else:
``SHENGJI_PV_LEAD_CONFIRM`` is ``'0'`` instead of ``'32'``, so the held-out lead
confirmation (``lcc32``) never runs.  The name loses ``-lcc32`` and its two digests
move; the packages, the stage table, sc8, every other rule, budget and latency switch
are release 50's.  Release 50's env is this one with lcc32 restored
(``release50_env``, the documented rollback).

The served bot is built from the repo's ``fly.toml`` environment exactly as the
server builds it (the registry's import-time registration, then
``make_bot(SHENGJI_BOT)``) on the hash-pinned release-50 packages, and one served
lead goes through the server's own snapshot and commit path.  The package tests
fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI package-gate step,
which runs ``SHENGJI_FAST=1`` on the compiled engine, the image's runtime).
"""
import asyncio
import copy
import os
import random

from shengji import releases
from test_release46_fly_config import fly_env as production_env
from test_release48_fly_config import LATENCY_KEYS
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA, PRIOR_VOLUME_PATH,
                                       RELEASE50, VALUE_SHA, VALUE_VOLUME_PATH, release50_env,
                                       release50_packages, served_bot)  # noqa: F401
from test_pv_search_serving import _play_state

#: release 50 with lcc32 off: the arm lccC and loo duelled against release 50
#: (lccC KEEP_LCC -0.0133 [-0.0232, -0.0033]; loo DROP_SAFE +0.0079 [-0.0069, +0.0221])
RELEASE51 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-"
             "lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-r30ff6f0f-bury-hybrid-bwv-bbw-"
             "73a716a9bf72-sc8")
#: the one line release 51 changes in release 50's env (besides the name)
R51_CHANGES = {"SHENGJI_PV_LEAD_CONFIRM": "0"}


def test_fly_toml_is_release50_with_lcc_off():
    env = production_env()
    assert env["SHENGJI_BOT"] == RELEASE51
    assert {k: env[k] for k in R51_CHANGES} == R51_CHANGES
    r50 = release50_env(env)
    changed = {k for k in set(env) | set(r50) if env.get(k) != r50.get(k)}
    assert changed == {"SHENGJI_BOT", *R51_CHANGES}
    assert r50["SHENGJI_BOT"] == RELEASE50 and r50["SHENGJI_PV_LEAD_CONFIRM"] == "32"
    # the rollback is release 50's manifest env, key for key
    assert {k: v for k, v in r50.items() if k not in releases.NON_BOT_KEYS} == releases.load(50)["env"]
    assert env["SHENGJI_PV_SINGLETON_CHALLENGER"] == "1"


def test_the_volume_paths_derive_the_served_name(monkeypatch):
    """The name the server registers from fly.toml as written (volume paths, hashes
    stood in for the files): lcc32 leaves the name and the play and bury digests move."""
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA, BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    env = production_env()
    assert not pv.pv_env_recipe(env).get("lead_confirm")
    assert pv.pv_env_recipe(release50_env(env))["lead_confirm"] == 32
    assert list(pv.singleton_registry_entries(**pv.pv_env_recipe(env))) == [env["SHENGJI_BOT"]] == [RELEASE51]
    assert list(pv.singleton_registry_entries(**pv.pv_env_recipe(release50_env(env)))) == [RELEASE50]
    assert "lcc" not in RELEASE51
    assert RELEASE51.replace("-r30ff6f0f-", "-lcc32-rb3477266-").replace(
        "-bbw-73a716a9bf72-", "-bbw-b6262940978b-") == RELEASE50


def test_served_bot_is_release51(release50_packages, monkeypatch):
    from shengji.eval.served_config import registry_name
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    env = production_env()
    name, bot = served_bot(release50_packages, monkeypatch, env=env)
    assert name == bot.policy_name == RELEASE51
    assert registry_name({**env, "SHENGJI_PV_CKPT": str(release50_packages["value"]),
                          "SHENGJI_PV_PRIOR_CKPT": str(release50_packages["prior"]),
                          "SHENGJI_PV_BELIEF_CKPT": str(release50_packages["belief"])}) == RELEASE51
    assert isinstance(bot, SingletonChallengerBuryBot)
    assert bot.lead_confirm == 0 and bot.config.lead_confirm == 0
    assert bot.model_ids("play") == {"value": VALUE_SHA[:8], "prior": PRIOR_SHA[:8],
                                     "belief": BELIEF_SHA[:8]}
    assert bot.bury_belief_worlds is True and bot.bury_wide_k == 64
    assert bot.serving_budget_seconds == 3.0 and bot.bury_serving_budget_seconds == 2.0
    assert bot.leaf_greedy_deadline_ms == 2000 and (bot.worlds, bot.candidates) == (64, 8)
    for attr in LATENCY_KEYS:
        assert getattr(bot, attr) is True


def test_served_lead_runs_without_lead_confirmation_through_the_server_path(
        release50_packages, tmp_path, monkeypatch):
    """One lead by the served bot through ``_paced_bot_step`` / ``_commit_bot_turn``:
    the search completes on B1a's worlds with the FT1 prior and the G3 A value, sc8
    probes the lead, and the lead-confirmation stage never runs."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(release50_packages, monkeypatch, env=production_env(), seed=7)
    assert name == RELEASE51
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    seat = rnd.turn
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R51", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        assert searched.policy_name == RELEASE51 and searched.lead_confirm == 0
        record = copy.deepcopy(searched.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)
        return record

    record = asyncio.run(scenario())
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    assert record["model_ids"] == {"value": VALUE_SHA[:8], "prior": PRIOR_SHA[:8], "belief": BELIEF_SHA[:8]}
    assert "singleton_challenger_applied" in record
    assert "lead_confirm_status" not in record


def test_rollback_to_release50_restores_lcc32(release50_packages, monkeypatch):
    name, bot = served_bot(release50_packages, monkeypatch, env=release50_env(production_env()))
    assert name == bot.policy_name == RELEASE50
    assert bot.lead_confirm == 32 and bot.config.lead_confirm == 32
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    from shengji.ai.endgame_compact import default_backend
    assert default_backend() == expected
