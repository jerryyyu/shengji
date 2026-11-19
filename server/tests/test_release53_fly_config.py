"""Release 53: the shipping ``fly.toml`` serves release 52 with the all-data unified model.

Release 53 changes release 52's environment in five lines and the name (``R53_CHANGES``): the
belief pair becomes the unified model's belief package (its trunk is the unified package's), the
unified readout package is added (``-ushare -uvalue -ureply``) and its fast path is on
(``-ufast``).  The name is the UT-alldata exploiter's (screen and confirmation) plus ``-ufast``,
byte for byte the name UT-fly-fast timed on the production machine.  The search, its rules,
budgets, bury, declaration and the G3 A value and FT1 prior bindings are release 52's.  Release
52's env is this one with the five lines undone (``release52_env``, the documented rollback).

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
from test_release46_fly_config import (BURY3, RELEASE52_BELIEF, RELEASE52_NAME, RELEASE53_ADDED_KEYS,
                                       fly_env as served_env, release52_env, undo_bury3)
from test_release48_fly_config import apply_to_process
from test_release50_fly_config import (PRIOR_SHA, PRIOR_VOLUME_PATH, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages)  # noqa: F401
from test_release52_fly_config import RELEASE52
from test_unified_serving import (PAIR_VARS, SCREENED, UNIFIED_BELIEF_SHA, UNIFIED_BELIEF_VOLUME_PATH,
                                  UNIFIED_SHA, UNIFIED_VOLUME_PATH, served_functions)  # noqa: F401
from test_pv_search_serving import _play_state

#: UT-alldata's exploiter (screen +0.0573 [+0.0422, +0.0728], confirmation +0.0521
#: [+0.0410, +0.0633] against release 52 as served) with the fast readout: the name UT-fly-fast
#: derived on the production machine and timed at 0.992x release 52
RELEASE53 = SCREENED + "-ufast"
#: every line release 53 adds to or changes in release 52's env (besides the name)
R53_CHANGES = {"SHENGJI_PV_BELIEF_CKPT": UNIFIED_BELIEF_VOLUME_PATH,
               "SHENGJI_PV_BELIEF_SHA256": UNIFIED_BELIEF_SHA,
               "SHENGJI_PV_UNIFIED_CKPT": UNIFIED_VOLUME_PATH,
               "SHENGJI_PV_UNIFIED_SHA256": UNIFIED_SHA,
               "SHENGJI_PV_UNIFIED_FAST": "1"}

#: production's name: release 53's with the bury digest of the 3 s budget
BURY3_NAME = RELEASE53.replace("-1b1a47f5dd8b-", "-3a676f3c01ea-")


def release53_env(env: dict) -> dict:
    """Production's env with the bury-3 rollback applied and the release-53 name restored:
    release 53's ``fly.toml`` ``[env]``."""
    return {**undo_bury3(env), "SHENGJI_BOT": RELEASE53}


def production_env() -> dict:
    """Release 53's ``fly.toml`` ``[env]``: the repo's with the bury-3 rollback applied."""
    return release53_env(served_env())


def bot_env(env):
    return {k: v for k, v in env.items() if k not in releases.NON_BOT_KEYS}


@pytest.fixture(scope="module")
def release53_pair():
    """The hash-pinned unified pair named by ``PAIR_VARS`` (CI fetches both from the
    ``serving-packages`` release); missing FAILS under ``SHENGJI_REQUIRE_PV_PACKAGE=1``."""
    out = {}
    for var, sha, role in zip(PAIR_VARS, (UNIFIED_SHA, UNIFIED_BELIEF_SHA), ("unified", "belief")):
        value = os.environ.get(var)
        if not value:
            if REQUIRE_PACKAGE:
                pytest.fail(f"SHENGJI_REQUIRE_PV_PACKAGE=1 but {var} is unset")
            pytest.skip(f"set {' and '.join(PAIR_VARS)} (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
        path = Path(value)
        if not path.exists():
            pytest.fail(f"pinned release-53 {role} package is missing: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == sha, f"{role} package is {actual[:12]}, not the pinned {sha[:12]}"
        out[role] = path
    return out


def local_env(packages, pair, env=None) -> dict:
    """``env`` (production's by default) with the volume paths mapped to the local copies; the
    hashes stay the pinned ones."""
    env = production_env() if env is None else env
    out = {**env, "SHENGJI_PV_CKPT": str(packages["value"]),
           "SHENGJI_PV_PRIOR_CKPT": str(packages["prior"])}
    if env.get("SHENGJI_PV_BELIEF_SHA256") == UNIFIED_BELIEF_SHA:
        out["SHENGJI_PV_BELIEF_CKPT"] = str(pair["belief"])
    else:
        out["SHENGJI_PV_BELIEF_CKPT"] = str(packages["belief"])
    if "SHENGJI_PV_UNIFIED_CKPT" in env:
        out["SHENGJI_PV_UNIFIED_CKPT"] = str(pair["unified"])
    return out


def served_bot(packages, pair, monkeypatch, *, env=None, seed=17):
    """``(name, bot)`` built as the server builds it from ``env`` on the local packages: the
    registry's import-time pv-search registration, then ``make_bot(SHENGJI_BOT)``.  The
    registry is a scratch copy."""
    from shengji.ai import registry

    env = local_env(packages, pair, env)
    for key in list(os.environ):
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.delenv(key)
    apply_to_process(monkeypatch, env)
    monkeypatch.setattr(registry, "REGISTRY", {k: v for k, v in registry.REGISTRY.items()
                                               if not k.startswith("pv-search-")})
    registry._register_pv_search_from_env()
    name = env["SHENGJI_BOT"]
    return name, registry.make_bot(name, seed=seed)


def test_fly_toml_is_release52_plus_the_unified_lines():
    env = production_env()
    assert env["SHENGJI_BOT"] == RELEASE53
    assert {k: env[k] for k in R53_CHANGES} == R53_CHANGES
    assert set(R53_CHANGES) == set(RELEASE53_ADDED_KEYS) | set(RELEASE52_BELIEF)
    r52 = release52_env(env)
    changed = {k for k in set(env) | set(r52) if env.get(k) != r52.get(k)}
    assert changed == {"SHENGJI_BOT", *R53_CHANGES}
    assert r52["SHENGJI_BOT"] == RELEASE52 == RELEASE52_NAME
    assert bot_env(env) == releases.load(53)["env"]
    assert bot_env(r52) == releases.load(52)["env"]


def test_the_volume_paths_derive_the_served_name(monkeypatch):
    """The name the server registers from fly.toml as written (volume paths, hashes stood in for
    the files): the served part is release 52's with the belief digests moved, then the unified
    tokens and -ufast."""
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv
    from shengji.train import unified_serving as serving

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               UNIFIED_BELIEF_VOLUME_PATH: UNIFIED_BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    env = production_env()
    served, = pv.singleton_registry_entries(**pv.pv_env_recipe(env))
    path, sha = serving.unified_env(env)
    assert (path, sha) == (UNIFIED_VOLUME_PATH, UNIFIED_SHA)
    assert serving.unified_name(served, sha, fast=serving.unified_fast(env)) == env["SHENGJI_BOT"] == RELEASE53
    gone = [t for t in RELEASE52.split("-") if t not in RELEASE53.split("-")]
    new = [t for t in RELEASE53.split("-") if t not in RELEASE52.split("-")]
    assert gone == ["r12e81e0c", "7a9a430fe690"]
    assert new == ["r09a10415", "1b1a47f5dd8b", "ushare97c07be8", "uvalue97c07be8", "ureply97c07be8", "ufast"]


def test_served_bot_is_release53(release50_packages, release53_pair, monkeypatch, served_functions):
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    name, bot = served_bot(release50_packages, release53_pair, monkeypatch)
    assert name == bot.policy_name == RELEASE53
    assert isinstance(bot, SingletonChallengerBuryBot)
    assert bot.unified_fast is True and bot.unified_sha256 == UNIFIED_SHA
    assert bot.model_ids("play")["belief"] == UNIFIED_BELIEF_SHA[:8]
    assert bot.serving_budget_seconds == 3.0 and bot.bury_serving_budget_seconds == 2.0
    assert bot.exact_lead_max_seconds == 1.6 and bot.lead_confirm == 0


def test_served_lead_runs_on_the_unified_slots_through_the_server_path(
        release50_packages, release53_pair, tmp_path, monkeypatch, served_functions):
    """A lead above the exact bound through ``_paced_bot_step`` / ``_commit_bot_turn``: the search
    completes on the unified belief package's worlds, every root prior, value row and reply row
    of the decision comes from the unified package, and none is left to the served nets."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, seed=7)
    assert name == RELEASE53
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R53", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = len(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        assert searched.policy_name == RELEASE53
        record = copy.deepcopy(searched.last_decision_record)
        cards = list(prepared.decision.cards)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == before - len(cards)
        return record

    record = asyncio.run(scenario())
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    unified = record["unified"]
    assert unified["package"] == UNIFIED_SHA[:8]
    assert unified["shared"] == 1 and unified["missed"] == 0 and unified["trunk"] == 0
    assert unified["value_rows"] > 0 and unified["value_left"] == 0
    assert unified["reply_left"] == 0
    assert {"value_memo", "reply_memo"} <= set(unified)
    assert "singleton_challenger_applied" in record and "lead_confirm_status" not in record


def test_rollback_to_release52_restores_b1a_and_drops_the_unified_lines(
        release50_packages, release53_pair, monkeypatch, served_functions):
    env = release52_env(production_env())
    assert not set(RELEASE53_ADDED_KEYS) & set(env)
    assert {k: env[k] for k in RELEASE52_BELIEF} == RELEASE52_BELIEF
    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, env=env)
    assert name == bot.policy_name == RELEASE52
    assert not hasattr(bot, "unified_sha256")
    assert bot.model_ids("play")["belief"] == RELEASE52_BELIEF["SHENGJI_PV_BELIEF_SHA256"][:8]


def test_fly_toml_is_release53_with_the_3s_bury():
    """Production is release 53 with one line changed, the bury budget at 3 s; the budget enters
    the bury identity, so only the name's bury digest moves."""
    env = served_env()
    assert env["SHENGJI_BOT"] == BURY3_NAME
    assert {k: env[k] for k in BURY3} == BURY3
    r53 = release53_env(env)
    changed = {k for k in set(env) | set(r53) if env.get(k) != r53.get(k)}
    assert changed == {"SHENGJI_BOT", *BURY3}
    assert bot_env(env) == releases.load(54)["env"]
    assert bot_env(r53) == releases.load(53)["env"]
    # the release-28 rollback keys keep release 28's 2 s budget
    assert env["SHENGJI_CWV_BURY_SERVING_BUDGET_SECONDS"] == "2"


def test_served_bot_buries_on_the_3s_budget(release50_packages, release53_pair, monkeypatch,
                                            served_functions):
    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, env=served_env())
    assert name == bot.policy_name == BURY3_NAME
    assert bot.serving_budget_seconds == 3.0 and bot.bury_serving_budget_seconds == 3.0
    assert bot.bury_recipe_identity["serving_budget_seconds"] == 3.0
    assert bot.unified_fast is True and bot.unified_sha256 == UNIFIED_SHA
