"""Release 55: the shipping ``fly.toml`` serves release 54 with the RT4 unified model.

Release 55 changes release 54's environment in four lines and the name (``RELEASE55_PAIRS``):
the unified readout package and the belief package become RT4's (``ut-rt4-e2951d35`` and
``ut-rt4-belief-35e225cf``; the belief package's trunk is the unified package's).  The registry
derives the name from them: the play digest, the bury digest and the three unified tokens move,
and the result is byte for byte the RT4 name S159 duelled against release 54 as served.  The
search, its rules, budgets, bury, declaration, the fast readout and the G3 A value and FT1 prior
bindings are release 54's.  Release 54's env is this one with the four lines undone
(``release54_env``, the documented rollback).

The served bot is built from the repo's ``fly.toml`` environment exactly as the server builds it
(the registry's import-time registration, then ``make_bot(SHENGJI_BOT)``) on the hash-pinned
packages, and one served lead goes through the server's own snapshot and commit path with every
unified slot filled from one trunk forward.  The package tests fail, never skip, under
``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI package-gate step, which runs ``SHENGJI_FAST=1`` on the
compiled engine, the image's runtime).
"""
import asyncio
import copy
import hashlib
import os
import random
from pathlib import Path

import pytest

from shengji import releases
from test_encoder_round_compat import REQUIRE_PACKAGE
from test_release46_fly_config import (RELEASE54_NAME, RELEASE54_PAIRS, RELEASE55_PAIRS,
                                       fly_env as served_env, release54_env)
from test_release50_fly_config import (PRIOR_SHA, PRIOR_VOLUME_PATH, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages)  # noqa: F401
from test_release53_fly_config import BURY3_NAME, bot_env, release53_pair, served_bot  # noqa: F401
from test_unified_serving import served_functions  # noqa: F401
from test_pv_search_serving import _play_state

RT4_SHA = RELEASE55_PAIRS["SHENGJI_PV_UNIFIED_SHA256"]
RT4_BELIEF_SHA = RELEASE55_PAIRS["SHENGJI_PV_BELIEF_SHA256"]
RT4_VOLUME_PATH = RELEASE55_PAIRS["SHENGJI_PV_UNIFIED_CKPT"]
RT4_BELIEF_VOLUME_PATH = RELEASE55_PAIRS["SHENGJI_PV_BELIEF_CKPT"]
#: the hash-pinned RT4 pair (CI fetches both from the ``serving-packages`` release)
RT4_PAIR_VARS = ("SHENGJI_PV_RT4_UNIFIED_PACKAGE_PATH", "SHENGJI_PV_RT4_BELIEF_PACKAGE_PATH")
#: the RT4 name S159 confirmed against release 54 as served (+0.0612 [+0.0510, +0.0712] on
#: 7,840 fresh deals), byte for byte
RELEASE55 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-"
             "dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel-reac0a771-bury-"
             "hybrid-bwv-bbw-e191a6461fa8-sc8-usharee2951d35-uvaluee2951d35-ureplye2951d35-ufast")


@pytest.fixture(scope="module")
def release55_pair():
    """The hash-pinned RT4 pair named by ``RT4_PAIR_VARS``; missing FAILS under
    ``SHENGJI_REQUIRE_PV_PACKAGE=1``."""
    out = {}
    for var, sha, role in zip(RT4_PAIR_VARS, (RT4_SHA, RT4_BELIEF_SHA), ("unified", "belief")):
        value = os.environ.get(var)
        if not value:
            if REQUIRE_PACKAGE:
                pytest.fail(f"SHENGJI_REQUIRE_PV_PACKAGE=1 but {var} is unset")
            pytest.skip(f"set {' and '.join(RT4_PAIR_VARS)} (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
        path = Path(value)
        if not path.exists():
            pytest.fail(f"pinned release-55 {role} package is missing: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == sha, f"{role} package is {actual[:12]}, not the pinned {sha[:12]}"
        out[role] = path
    return out


def test_fly_toml_is_release54_with_the_rt4_pairs():
    env = served_env()
    assert env["SHENGJI_BOT"] == RELEASE55
    assert {k: env[k] for k in RELEASE55_PAIRS} == RELEASE55_PAIRS
    r54 = release54_env(env)
    changed = {k for k in set(env) | set(r54) if env.get(k) != r54.get(k)}
    assert changed == {"SHENGJI_BOT", *RELEASE55_PAIRS}
    assert {k: r54[k] for k in RELEASE54_PAIRS} == RELEASE54_PAIRS
    assert r54["SHENGJI_BOT"] == RELEASE54_NAME == BURY3_NAME
    assert bot_env(env) == releases.load(55)["env"]
    assert bot_env(r54) == releases.load(54)["env"]


def test_the_volume_paths_derive_the_served_name(monkeypatch):
    """The name the server registers from fly.toml as written (volume paths, hashes stood in for
    the files): release 54's with the play digest, the bury digest and the unified tokens moved."""
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv
    from shengji.train import unified_serving as serving

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               RT4_BELIEF_VOLUME_PATH: RT4_BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    env = served_env()
    served, = pv.singleton_registry_entries(**pv.pv_env_recipe(env))
    path, sha = serving.unified_env(env)
    assert (path, sha) == (RT4_VOLUME_PATH, RT4_SHA)
    assert serving.unified_name(served, sha, fast=serving.unified_fast(env)) == env["SHENGJI_BOT"] == RELEASE55
    gone = [t for t in RELEASE54_NAME.split("-") if t not in RELEASE55.split("-")]
    new = [t for t in RELEASE55.split("-") if t not in RELEASE54_NAME.split("-")]
    assert gone == ["r09a10415", "3a676f3c01ea", "ushare97c07be8", "uvalue97c07be8", "ureply97c07be8"]
    assert new == ["reac0a771", "e191a6461fa8", "usharee2951d35", "uvaluee2951d35", "ureplye2951d35"]


def test_served_bot_is_release55(release50_packages, release55_pair, monkeypatch, served_functions):
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    name, bot = served_bot(release50_packages, release55_pair, monkeypatch, env=served_env())
    assert name == bot.policy_name == RELEASE55
    assert isinstance(bot, SingletonChallengerBuryBot)
    assert bot.unified_fast is True and bot.unified_sha256 == RT4_SHA
    assert bot.model_ids("play")["belief"] == RT4_BELIEF_SHA[:8]
    assert bot.serving_budget_seconds == 3.0 and bot.bury_serving_budget_seconds == 3.0
    assert bot.exact_lead_max_seconds == 1.6 and bot.lead_confirm == 0


def test_served_lead_runs_on_the_rt4_slots_through_the_server_path(
        release50_packages, release55_pair, tmp_path, monkeypatch, served_functions):
    """A lead above the exact bound through ``_paced_bot_step`` / ``_commit_bot_turn``: the search
    completes on RT4's belief worlds, and every root prior, value row and reply row of the
    decision comes from RT4's unified package, none left to the served nets."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(release50_packages, release55_pair, monkeypatch, env=served_env(), seed=7)
    assert name == RELEASE55
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R55", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = len(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        assert searched.policy_name == RELEASE55
        record = copy.deepcopy(searched.last_decision_record)
        cards = list(prepared.decision.cards)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == before - len(cards)
        return record

    record = asyncio.run(scenario())
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    unified = record["unified"]
    assert unified["package"] == RT4_SHA[:8]
    assert unified["shared"] == 1 and unified["missed"] == 0 and unified["trunk"] == 0
    assert unified["value_rows"] > 0 and unified["value_left"] == 0
    assert unified["reply_left"] == 0
    assert "singleton_challenger_applied" in record and "lead_confirm_status" not in record


def test_rollback_to_release54_restores_the_all_data_pair(
        release50_packages, release53_pair, monkeypatch, served_functions):
    env = release54_env(served_env())
    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, env=env)
    assert name == bot.policy_name == RELEASE54_NAME
    assert bot.unified_sha256 == RELEASE54_PAIRS["SHENGJI_PV_UNIFIED_SHA256"]
    assert bot.model_ids("play")["belief"] == RELEASE54_PAIRS["SHENGJI_PV_BELIEF_SHA256"][:8]
    assert bot.bury_serving_budget_seconds == 3.0
