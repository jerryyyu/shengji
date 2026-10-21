"""Release 46, now the rollback of release 47: the combo screened as v92combo45.

The combo is release 45 plus history-legal, belief-proposed play worlds (``-whl
-whd -bw``, the S17 belief package), the exact endgame search at 7 cards (``-ele
-ed7 -xf7 -xfcompactlevel``) and the value-guided declaration at every
first-round chance (``-vdef``).  Release 47 changes the belief pair and adds the
dtrx line, so release 46's env is the repo's ``fly.toml`` environment with that
change undone (``release46_env``, the documented rollback).  The bot is built
from it exactly as the server builds it (``pv_env_recipe`` ->
``pv_registry_entries`` -> the factory) on the hash-pinned production and belief
packages, so the registry name, every combo knob, the bound belief model and the
compact solver's backend are witnessed on this tree, and one served play goes
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
import tomllib
from pathlib import Path

import pytest

from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA, REQUIRE_PACKAGE  # noqa: F401
from test_pv_search_serving import _play_state

RELEASE45 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
#: the candidate name v92combo45 screened (#707 issuecomment-6216352632)
RELEASE46 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-"
             "xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0")
BELIEF_SHA = "763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343"
BELIEF_VOLUME_PATH = "/data/models/s17long-e2-763b5e05.npz"
#: the candidate arm's env as v92's launcher exported it, with the belief package at its
#: Fly volume path (the screen host's copy had the same sha256)
V92_CANDIDATE_ENV = {"SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
                     "SHENGJI_PV_WORLD_HISTORY_DRAW": "1",
                     "SHENGJI_PV_BELIEF_WORLDS": "1",
                     "SHENGJI_PV_BELIEF_CKPT": BELIEF_VOLUME_PATH,
                     "SHENGJI_PV_BELIEF_SHA256": BELIEF_SHA,
                     "SHENGJI_PV_EXACT_LEAD_ENDGAME": "1",
                     "SHENGJI_PV_EXACT_DEEP_CARDS": "7",
                     "SHENGJI_PV_EXACT_FOLLOW": "1",
                     "SHENGJI_PV_EXACT_FOLLOW_SOLVER": "compact-level",
                     "SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS": "7",
                     "SHENGJI_PV_EXACT_FOLLOW_MAX_NODES": "50000000",
                     "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1"}
DTRX_FLAG = "SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD"
#: every line production's env carries above release 45: release 46's twelve and
#: release 47's dtrx line (release 47 changed the belief pair's values, not its keys)
COMBO_KEYS = tuple(V92_CANDIDATE_ENV) + (DTRX_FLAG,)


def without_combo(env: dict) -> dict:
    """``env`` without the lines above release 45: release 45's env when ``env`` is
    production's or release 46's (the documented rollbacks)."""
    return {k: v for k, v in env.items() if k not in COMBO_KEYS}


def release46_env(env: dict) -> dict:
    """Production's env with release 47's rollback applied: the dtrx line removed,
    the S17 belief pair and the release-46 name restored."""
    env = {k: v for k, v in env.items() if k != DTRX_FLAG}
    env.update(SHENGJI_PV_BELIEF_CKPT=BELIEF_VOLUME_PATH, SHENGJI_PV_BELIEF_SHA256=BELIEF_SHA,
               SHENGJI_BOT=RELEASE46)
    return env
BELIEF_PACKAGE = os.environ.get("SHENGJI_PV_BELIEF46_PACKAGE_PATH")


def fly_env() -> dict:
    return tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]


@pytest.fixture(scope="module")
def pinned_release46_belief_package(pinned_production_package):
    """The hash-pinned S17 belief package named by ``SHENGJI_PV_BELIEF46_PACKAGE_PATH``
    (CI fetches it from the ``serving-packages`` release); missing FAILS under
    ``SHENGJI_REQUIRE_PV_PACKAGE=1``, like the production package."""
    if not BELIEF_PACKAGE:
        if REQUIRE_PACKAGE:
            pytest.fail("SHENGJI_REQUIRE_PV_PACKAGE=1 but SHENGJI_PV_BELIEF46_PACKAGE_PATH is unset")
        pytest.skip("set SHENGJI_PV_BELIEF46_PACKAGE_PATH (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
    path = Path(BELIEF_PACKAGE)
    if not path.exists():
        pytest.fail(f"pinned belief package is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == BELIEF_SHA, f"belief package is {actual[:12]}, not the pinned {BELIEF_SHA[:12]}"
    return path


def served_entries(path, belief_path):
    from shengji.train import pv_search_policy as pv

    env = release46_env(fly_env())
    recipe = pv.pv_env_recipe({**env, "SHENGJI_PV_CKPT": str(path),
                               "SHENGJI_PV_SHA256": PACKAGE_SHA,
                               "SHENGJI_PV_BELIEF_CKPT": str(belief_path)})
    entries = pv.pv_registry_entries(**recipe)
    name, = entries
    return env, name, entries[name]


def test_release46_env_carries_the_v92_candidate_env():
    env = release46_env(fly_env())
    assert {k: env[k] for k in V92_CANDIDATE_ENV} == V92_CANDIDATE_ENV
    assert env["SHENGJI_BOT"] == RELEASE46
    # the belief log stays at its default (on); the screen did not set it either
    assert "SHENGJI_PV_BELIEF_LOG" not in env
    assert "SHENGJI_PV_EXACT_LEAD_TIE_BASELINE" not in env
    assert "SHENGJI_PV_EXACT_LEAD_POLICY_FIRST" not in env
    assert "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY" not in env
    assert "SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD" not in env
    # the combo runs inside release 45's unchanged budgets on the compiled engine
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_FAST"] == "1"
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    # both packages sit on the volume
    assert env["SHENGJI_PV_CKPT"].startswith("/data/models/")
    assert env["SHENGJI_PV_BELIEF_CKPT"] == BELIEF_VOLUME_PATH


def test_release46_bot_is_the_screened_combo_on_the_compiled_solver(pinned_production_package,
                                                                  pinned_release46_belief_package):
    from shengji.ai.endgame_compact import CompactWorldSession, HAVE_FAST, default_backend
    from shengji.train.pv_search_policy import PVSearchBuryBot

    env, name, factory = served_entries(pinned_production_package, pinned_release46_belief_package)
    assert name == env["SHENGJI_BOT"] == RELEASE46
    bot = factory(seed=17)
    assert isinstance(bot, PVSearchBuryBot) and bot.checkpoint_sha256 == PACKAGE_SHA
    # play worlds: history-legal, draw-constrained, belief-proposed by the pinned package
    assert (bot.world_history_legal, bot.world_history_draw, bot.belief_worlds) == (True, True, True)
    assert bot.belief_model is not None and bot.belief_model.package_sha256 == BELIEF_SHA
    assert bot.config.belief_sha256 == BELIEF_SHA and bot.belief_log is True
    # the exact endgame search at 7 cards
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (True, 7, True)
    assert (bot.config.exact_lead_endgame, bot.config.exact_deep_cards,
            bot.config.exact_follow) == (True, 7, True)
    knobs = ("compact-level", 7, 50_000_000)
    assert (bot.exact_follow_solver, bot.exact_follow_max_cards, bot.exact_follow_max_nodes) == knobs
    assert (bot.config.exact_follow_solver, bot.config.exact_follow_max_cards,
            bot.config.exact_follow_max_nodes) == knobs
    assert (bot.exact_lead_tie_baseline, bot.exact_lead_policy_first) == (False, False)
    # the value-guided declaration at every first-round chance
    assert (bot.value_declare, bot.value_declare_every_first) == (True, True)
    # release 45 underneath: W64/K8, the wide value-only bury at K=64 and dtr
    assert (bot.worlds, bot.candidates, bot.bury_wide_value, bot.bury_wide_k) == (64, 8, True, 64)
    assert bot.doomed_throw_reselect is True
    # The compact-level session the follow and deep-lead stages open takes the default
    # backend: "compiled" exactly when SHENGJI_FAST=1 activated the engine at package import
    # and _endgame_fast is built (the image's runtime and the CI package gate); the pure
    # twin, identical results, otherwise.
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    if expected == "compiled":
        assert HAVE_FAST, "SHENGJI_FAST=1 but shengji/ai/_endgame_fast is not built"
    assert default_backend() == expected
    session = CompactWorldSession(_play_state(), max_hand_cards=7, max_nodes=50_000_000,
                                  alpha_beta=True, level=True)
    assert session.backend == expected


def test_release46_play_takes_the_belief_proposal_through_the_server_path(
        pinned_production_package, pinned_release46_belief_package, tmp_path, monkeypatch):
    """One play by the release-46 bot through ``_paced_bot_step`` / ``_commit_bot_turn``:
    the worlds are proposed by the real belief model with no fallback.

    The proposal's wall-clock preparation cap is lifted here so a slow or cold CI
    runner cannot turn this wiring witness into a timing test: an over-cap
    preparation is a belief error, whose fallback to the history-legal draw is
    tested on its own, and serving latency is measured on the intended host."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    _, name, factory = served_entries(pinned_production_package, pinned_release46_belief_package)
    bot = factory(seed=7)
    rnd = _play_state()
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R46", game=game, bot=bot,
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
    assert name == RELEASE46
    assert record["worlds"] == 64
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64, {k: v for k, v in record.items() if k.startswith("belief") and k != "belief_snapshot"}
    assert record["belief_log"] == 1


def test_rollback_to_release45_is_the_env_without_the_twelve_combo_lines(pinned_production_package):
    from shengji.train import pv_search_policy as pv

    env = without_combo(release46_env(fly_env()))
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(
        {**env, "SHENGJI_PV_CKPT": str(pinned_production_package), "SHENGJI_PV_SHA256": PACKAGE_SHA}))
    name, = entries
    assert name == RELEASE45
    bot = entries[name](seed=17)
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (False, 0, False)
    assert (bot.world_history_legal, bot.belief_worlds, bot.belief_model) == (False, False, None)
    assert (bot.value_declare, bot.value_declare_every_first) == (True, False)
    assert (bot.worlds, bot.candidates, bot.bury_wide_value, bot.bury_wide_k) == (64, 8, True, 64)


#: release 46 with the doomed-throw re-select's exact-stage guard on (token ``dtrx``
#: after ``dtr``): a DEV arm, never the served name
RELEASE46_DTRX = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-ed7-xf7-"
                  "xfcompactlevel-r42abaa1e-bury-hybrid-bwv-0b3219432da4")


def test_dtrx_off_keeps_the_served_name_and_on_adds_its_token(pinned_production_package,
                                                                pinned_release46_belief_package):
    from shengji.train import pv_search_policy as pv

    def built(**extra):
        recipe = pv.pv_env_recipe({**release46_env(fly_env()), "SHENGJI_PV_CKPT": str(pinned_production_package),
                                   "SHENGJI_PV_SHA256": PACKAGE_SHA,
                                   "SHENGJI_PV_BELIEF_CKPT": str(pinned_release46_belief_package), **extra})
        entries = pv.pv_registry_entries(**recipe)
        name, = entries
        return name, entries[name]

    for off in ({}, {DTRX_FLAG: "0"}, {DTRX_FLAG: ""}):
        name, factory = built(**off)
        assert name == RELEASE46
        bot = factory(seed=17)
        assert bot.doomed_throw_reselect_exact_guard is False
        assert "doomed_throw_reselect_exact_guard" not in vars(bot)
        assert bot.config.doomed_throw_reselect_exact_guard is False
    name, factory = built(**{DTRX_FLAG: "1"})
    assert name == RELEASE46_DTRX
    bot = factory(seed=17)
    assert bot.doomed_throw_reselect_exact_guard is True and bot.doomed_throw_reselect is True
    assert bot.config.doomed_throw_reselect_exact_guard is True
    # the guard binds to the exact stage: release 45 (dtr, no exact stage) refuses it
    with pytest.raises(pv.PVSearchPolicyError, match="requires doomed_throw_reselect and exact_lead_endgame"):
        pv.pv_registry_entries(**pv.pv_env_recipe(
            {**without_combo(fly_env()), "SHENGJI_PV_CKPT": str(pinned_production_package),
             "SHENGJI_PV_SHA256": PACKAGE_SHA, DTRX_FLAG: "1"}))


LGF_FLAG = "SHENGJI_PV_LEAF_GREEDY_FINISH"


def test_lgf_off_keeps_the_served_name_and_on_adds_its_token(pinned_production_package,
                                                               pinned_belief_package):
    """Release 46 with the greedy-finished value leaf (token ``lgf`` after the
    declaration tokens): a DEV arm, never the served name."""
    from shengji.train import pv_search_policy as pv

    def built(**extra):
        recipe = pv.pv_env_recipe({**fly_env(), "SHENGJI_PV_CKPT": str(pinned_production_package),
                                   "SHENGJI_PV_SHA256": PACKAGE_SHA,
                                   "SHENGJI_PV_BELIEF_CKPT": str(pinned_belief_package), **extra})
        entries = pv.pv_registry_entries(**recipe)
        name, = entries
        return name, entries[name]

    for off in ({}, {LGF_FLAG: "0"}, {LGF_FLAG: ""}):
        name, factory = built(**off)
        assert name == RELEASE46
        bot = factory(seed=17)
        assert bot.leaf_greedy_finish is False
        assert "leaf_greedy_finish" not in vars(bot) and "_leaf_greedy" not in vars(bot)
        assert bot.config.leaf_greedy_finish is False
    name, factory = built(**{LGF_FLAG: "1"})
    assert name != RELEASE46 and "-vdef-lgf-ed7-" in name
    assert name.split("-lgf-")[0] == RELEASE46.split("-ed7-")[0]
    bot = factory(seed=17)
    assert bot.leaf_greedy_finish is True and bot.config.leaf_greedy_finish is True
    assert (bot.exact_lead_endgame, bot.tiebreak_points, bot.doomed_throw_reselect) == (True, True, True)
