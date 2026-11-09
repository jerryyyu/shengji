"""Release 52: the shipping ``fly.toml`` serves release 51 with the combo51 search rules.

Release 52 adds five lines to release 51's environment and changes nothing else
(``R52_CHANGES``): the exact lead keeps the baseline unless the exact pass strictly
improves on it (``elt``), solves its own first trick by full minimax (``elm``) and
stops at 1.6 s (``els1600``); the play worlds keep history-legal throws (``wht``); and
refusals are recorded from every committed play (``rcec``).  The name is the
combo51 / combo51C exploiter's, byte for byte; the packages, the stage table, sc8,
lcc off, every other rule, budget and latency switch are release 51's.  Release
51's env is this one with the five lines removed (``release51_env``, the documented
rollback).

The served bot is built from the repo's ``fly.toml`` environment exactly as the
server builds it (the registry's import-time registration, then
``make_bot(SHENGJI_BOT)``) on the hash-pinned release-50 packages, and one served
lead and one exact-stage lead go through the server's own snapshot and commit path.
The package tests fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI
package-gate step, which runs ``SHENGJI_FAST=1`` on the compiled engine, the
image's runtime).
"""
import asyncio
import copy
import dataclasses
import os
import random

import r50_flag_positions as P
from shengji import releases
from test_release46_fly_config import RELEASE52_ADDED_KEYS, fly_env as production_env
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA, PRIOR_VOLUME_PATH,
                                       VALUE_SHA, VALUE_VOLUME_PATH, release50_packages,  # noqa: F401
                                       served_bot)
from test_release51_fly_config import RELEASE51, release51_env
from test_pv_search_serving import _play_state

#: the arm combo51 (SCREEN_PASS +0.0418 [+0.0332, +0.0506]) and combo51C (CONFIRMED
#: +0.0438 [+0.0381, +0.0497]) duelled against release 51 as served
RELEASE52 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-"
             "dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-r12e81e0c-bury-"
             "hybrid-bwv-bbw-7a9a430fe690-sc8")
#: the lines release 52 adds to release 51's env (besides the name)
R52_CHANGES = {"SHENGJI_PV_EXACT_LEAD_TIE_BASELINE": "1",
               "SHENGJI_PV_EXACT_LEAD_FULL_MINIMAX": "1",
               "SHENGJI_PV_EXACT_LEAD_MAX_SECONDS": "1.6",
               "SHENGJI_PV_WORLD_HISTORY_THROWS": "1",
               "SHENGJI_PV_REFUSAL_EVENT_COMPLETE": "1"}
#: the bot config fields the five lines move, release 51 -> release 52
R52_CONFIG = {"exact_lead_tie_baseline": (False, True), "exact_lead_full_minimax": (False, True),
              "exact_lead_max_seconds": (2.25, 1.6), "world_history_throws": (False, True),
              "refusal_event_complete": (False, True)}


def test_fly_toml_is_release51_plus_the_combo51_lines():
    env = production_env()
    assert env["SHENGJI_BOT"] == RELEASE52
    assert {k: env[k] for k in R52_CHANGES} == R52_CHANGES
    assert set(R52_CHANGES) == set(RELEASE52_ADDED_KEYS)
    r51 = release51_env(env)
    changed = {k for k in set(env) | set(r51) if env.get(k) != r51.get(k)}
    assert changed == {"SHENGJI_BOT", *R52_CHANGES}
    assert r51["SHENGJI_BOT"] == RELEASE51
    bot_env = lambda e: {k: v for k, v in e.items() if k not in releases.NON_BOT_KEYS}
    assert bot_env(env) == releases.load(52)["env"]
    assert bot_env(r51) == releases.load(51)["env"]
    assert env["SHENGJI_PV_LEAD_CONFIRM"] == "0" and env["SHENGJI_PV_SINGLETON_CHALLENGER"] == "1"


def test_the_volume_paths_derive_the_served_name(monkeypatch):
    """The name the server registers from fly.toml as written (volume paths, hashes
    stood in for the files): five tokens join and the play and bury digests move."""
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA, BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    env = production_env()
    assert list(pv.singleton_registry_entries(**pv.pv_env_recipe(env))) == [env["SHENGJI_BOT"]] == [RELEASE52]
    assert list(pv.singleton_registry_entries(**pv.pv_env_recipe(release51_env(env)))) == [RELEASE51]
    gone = [t for t in RELEASE51.split("-") if t not in RELEASE52.split("-")]
    new = [t for t in RELEASE52.split("-") if t not in RELEASE51.split("-")]
    assert gone == ["r30ff6f0f", "73a716a9bf72"]
    assert new == ["rcec", "wht", "elt", "elm", "els1600", "r12e81e0c", "7a9a430fe690"]


def test_served_bot_is_release52(release50_packages, monkeypatch):
    from shengji.eval.served_config import registry_name
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    env = production_env()
    name, bot = served_bot(release50_packages, monkeypatch, env=env)
    assert name == bot.policy_name == RELEASE52
    assert registry_name({**env, "SHENGJI_PV_CKPT": str(release50_packages["value"]),
                          "SHENGJI_PV_PRIOR_CKPT": str(release50_packages["prior"]),
                          "SHENGJI_PV_BELIEF_CKPT": str(release50_packages["belief"])}) == RELEASE52
    assert isinstance(bot, SingletonChallengerBuryBot) and hasattr(bot, "observe_public")
    assert bot.exact_lead_tie_baseline is True and bot.exact_lead_full_minimax is True
    assert bot.exact_lead_max_seconds == 1.6
    assert bot.world_history_throws is True and bot.refusal_event_complete is True
    assert bot.lead_confirm == 0
    assert bot.model_ids("play") == {"value": VALUE_SHA[:8], "prior": PRIOR_SHA[:8],
                                     "belief": BELIEF_SHA[:8]}
    assert bot.serving_budget_seconds == 3.0 and bot.bury_serving_budget_seconds == 2.0
    # against release 51's bot, exactly the five config fields move
    _, r51 = served_bot(release50_packages, monkeypatch, env=release51_env(env))
    a, b = dataclasses.asdict(r51.config), dataclasses.asdict(bot.config)
    assert {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)} == R52_CONFIG
    assert {k: v for k, v in r51.bury_recipe_identity.items() if k != "play_policy"} == \
        {k: v for k, v in bot.bury_recipe_identity.items() if k != "play_policy"}


def _server_turn(bot, rnd, tmp_path, code):
    """One bot turn through ``_paced_bot_step`` / ``_commit_bot_turn``; returns the
    searched copy's decision record and the committed cards."""
    from shengji.api import server as srv
    from shengji.engine.game import Game

    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code=code, game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = len(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        assert searched.policy_name == RELEASE52
        record = copy.deepcopy(searched.last_decision_record)
        cards = list(prepared.decision.cards)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == before - len(cards)
        return record, cards

    return asyncio.run(scenario())


def test_served_lead_runs_through_the_server_path(release50_packages, tmp_path, monkeypatch):
    """A lead above the exact bound: the search completes on B1a's worlds with the FT1
    prior and the G3 A value, sc8 probes it, and no lead-confirmation stage runs."""
    from shengji.ai import belief_numpy as bn
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(release50_packages, monkeypatch, env=production_env(), seed=7)
    assert name == RELEASE52
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7
    record, _ = _server_turn(bot, rnd, tmp_path, "R52")
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    assert record["model_ids"] == {"value": VALUE_SHA[:8], "prior": PRIOR_SHA[:8], "belief": BELIEF_SHA[:8]}
    assert "singleton_challenger_applied" in record
    assert "lead_confirm_status" not in record


def test_served_exact_lead_solves_its_first_trick_by_minimax_through_the_server_path(
        release50_packages, tmp_path, monkeypatch):
    """A production lead inside the exact bound (SDUS round 2 trick 14): the exact
    stage completes with the full-minimax first trick and the tie rule's record.
    The clocks are lifted (``P.lift``) so a slow engine never cuts the stage."""
    from shengji.ai import belief_numpy as bn

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(release50_packages, monkeypatch, env=production_env(), seed=P.SEED)
    assert name == RELEASE52 and bot.exact_lead_max_seconds == 1.6
    P.lift(bot)
    rnd = P.replay("SDUS2", 14, 0)
    assert not rnd.trick.plays and max(map(len, rnd.hands)) <= 7
    record, cards = _server_turn(bot, rnd, tmp_path, "R52X")
    assert record["exact_lead_status"] == "complete"
    assert record["exact_lead_first_trick"] == "minimax"
    assert "exact_lead_tie_baseline_kept" in record
    assert cards and "lead_confirm_status" not in record


def test_rollback_to_release51_drops_the_five_lines(release50_packages, monkeypatch):
    name, bot = served_bot(release50_packages, monkeypatch, env=release51_env(production_env()))
    assert name == bot.policy_name == RELEASE51
    assert not bot.exact_lead_tie_baseline and not bot.exact_lead_full_minimax
    assert bot.exact_lead_max_seconds == 2.25
    assert not bot.world_history_throws and not bot.refusal_event_complete
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    from shengji.ai.endgame_compact import default_backend
    assert default_backend() == expected
