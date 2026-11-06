"""Release 50, the rollback of release 51: the cbaC stack, release 49 on new packages.

Release 50 changes four things in release 49's environment and nothing else
(``R50_CHANGES``): the value package is G3 Stage A's ``g3a-e04-f4f4127e`` (the
evaluator at every stage), the card-play prior is FT1's ``p0-ft1-1fa201b2``
(``SHENGJI_PV_PRIOR_*``, name token ``-prior-1fa201b2``), the belief package is
B1a's ``b1a-028131a0`` in place of S58's, and the wide value-only bury scores
its candidates on belief-drawn worlds (``SHENGJI_PV_BURY_BELIEF_WORLDS = '1'``,
bury token ``-bbw``).  lcc32, sc8, every rule, budget and latency switch are
release 49's, so release 49's env is this one with that change undone
(``release49_env``, the documented rollback).  Release 51 turns lcc32 off and changes
nothing else, so release 50's env is the repo's ``fly.toml`` with that undone
(``release50_env``).

The served bot is built from that environment exactly as the
server builds it: the env in the process, the registry's import-time
registration (``_register_pv_search_from_env``) and ``make_bot(SHENGJI_BOT)``,
on the hash-pinned release-50 packages.  One served lead goes through the
server's own snapshot and commit path with the real B1a belief model and the
FT1 prior, and one bury is decided on B1a's worlds.  The package tests fail,
never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI package-gate step,
which runs ``SHENGJI_FAST=1`` on the compiled engine, the image's runtime).
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
from test_release46_fly_config import (RELEASE49_VALUES, RELEASE50_ADDED_KEYS,
                                       fly_env as production_env, undo_release51)
from test_release48_fly_config import (BELIEF_SHA as S58_SHA, LATENCY_KEYS, apply_to_process,
                                       pinned_release48_belief_package)  # noqa: F401
from test_release49_fly_config import RELEASE49, Y_CHANGES, release49_env
from test_release49_fly_config import served_bot as release49_served_bot
from native_switches import NATIVE_OFF

#: the stack cbaC confirmed against release 49 as served (#1171 issuecomment-6629239690);
#: the registry derives it from this env (no package path enters the name)
RELEASE50 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-"
             "lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-rb3477266-bury-hybrid-bwv-bbw-"
             "b6262940978b-sc8")
VALUE_SHA = "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd"
PRIOR_SHA = "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf"
BELIEF_SHA = "028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8"
VALUE_VOLUME_PATH = "/data/models/g3a-e04-f4f4127e.npz"
PRIOR_VOLUME_PATH = "/data/models/p0-ft1-1fa201b2.npz"
BELIEF_VOLUME_PATH = "/data/models/b1a-028131a0.npz"
#: B1a's stored calibration temperature, served as is (no env knob overrides it)
BELIEF_TEMPERATURE = 1.0189738579997958
#: every line release 50 adds to or changes in release 49's env (besides the name)
R50_CHANGES = {"SHENGJI_PV_CKPT": VALUE_VOLUME_PATH,
               "SHENGJI_PV_SHA256": VALUE_SHA,
               "SHENGJI_PV_PRIOR_CKPT": PRIOR_VOLUME_PATH,
               "SHENGJI_PV_PRIOR_SHA256": PRIOR_SHA,
               "SHENGJI_PV_BELIEF_CKPT": BELIEF_VOLUME_PATH,
               "SHENGJI_PV_BELIEF_SHA256": BELIEF_SHA,
               "SHENGJI_PV_BURY_BELIEF_WORLDS": "1"}
#: the release-50 packages, by the env var naming each local copy (CI fetches them from
#: the ``serving-packages`` release)
PACKAGES = {"value": ("SHENGJI_PV50_PACKAGE_PATH", VALUE_SHA),
            "prior": ("SHENGJI_PV50_PRIOR_PACKAGE_PATH", PRIOR_SHA),
            "belief": ("SHENGJI_PV50_BELIEF_PACKAGE_PATH", BELIEF_SHA)}


def release50_env(env: dict) -> dict:
    """Production's env with release 51's rollback applied: lcc32 back on and the
    release-50 name restored."""
    return {**undo_release51(env), "SHENGJI_BOT": RELEASE50}


def fly_env() -> dict:
    """Release 50's ``fly.toml`` ``[env]``: the repo's, rolled back from release 51."""
    return release50_env(production_env())


@pytest.fixture(scope="module")
def release50_packages():
    """The three hash-pinned release-50 packages named by ``PACKAGES``' env vars;
    any missing FAILS under ``SHENGJI_REQUIRE_PV_PACKAGE=1``, like the production
    package."""
    out = {}
    for role, (var, sha) in PACKAGES.items():
        value = os.environ.get(var)
        if not value:
            if REQUIRE_PACKAGE:
                pytest.fail(f"SHENGJI_REQUIRE_PV_PACKAGE=1 but {var} is unset")
            pytest.skip(f"set {', '.join(v for v, _ in PACKAGES.values())} "
                        "(and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
        path = Path(value)
        if not path.exists():
            pytest.fail(f"pinned release-50 {role} package is missing: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == sha, f"{role} package is {actual[:12]}, not the pinned {sha[:12]}"
        out[role] = path
    return out


def local_env(packages, env=None) -> dict:
    """``env`` (release 50's by default) with the release-50 volume paths mapped to the
    local copies; the hashes stay the pinned ones."""
    env = fly_env() if env is None else env
    return {**env, "SHENGJI_PV_CKPT": str(packages["value"]),
            "SHENGJI_PV_PRIOR_CKPT": str(packages["prior"]),
            "SHENGJI_PV_BELIEF_CKPT": str(packages["belief"])}


def served_bot(packages, monkeypatch, *, env=None, seed=17):
    """``(name, bot)`` built as the server builds it from ``env`` (release 50's by
    default) on the local packages: the registry's import-time pv-search registration,
    then ``make_bot(SHENGJI_BOT)``.  The registry is a scratch copy."""
    from shengji.ai import registry

    env = local_env(packages, env)
    for key in list(os.environ):
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.delenv(key)
    apply_to_process(monkeypatch, env)
    monkeypatch.setattr(registry, "REGISTRY", {k: v for k, v in registry.REGISTRY.items()
                                               if not k.startswith("pv-search-")})
    registry._register_pv_search_from_env()
    name = env["SHENGJI_BOT"]
    return name, registry.make_bot(name, seed=seed)


def test_release50_is_release49_plus_the_r50_changes():
    env = fly_env()
    assert {k: env[k] for k in R50_CHANGES} == R50_CHANGES
    assert env["SHENGJI_BOT"] == RELEASE50
    assert set(RELEASE50_ADDED_KEYS) == set(R50_CHANGES) - set(RELEASE49_VALUES)
    # every other line is release 49's
    r49 = release49_env(env)
    assert set(env) - set(r49) == set(RELEASE50_ADDED_KEYS) and not set(r49) - set(env)
    def rest(e):
        return {k: v for k, v in e.items() if k not in R50_CHANGES and k != "SHENGJI_BOT"}
    assert rest(env) == rest(r49)
    assert r49["SHENGJI_BOT"] == RELEASE49
    assert {k: r49[k] for k in RELEASE49_VALUES} == RELEASE49_VALUES
    assert r49["SHENGJI_PV_SHA256"] == PACKAGE_SHA and r49["SHENGJI_PV_BELIEF_SHA256"] == S58_SHA
    # release 49's lead rules stay on; no other candidate knob rides along
    assert {k: env[k] for k in Y_CHANGES} == Y_CHANGES
    for key in ("SHENGJI_PV_WIDE_LEAD_ADMISSION", "SHENGJI_PV_WIDE_LEAD_K", "SHENGJI_PV_LEAF_GREEDY_TOP",
                "SHENGJI_PV_TREE_SIMS", "SHENGJI_PV_ADAPTIVE_WORLDS", "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS",
                "SHENGJI_PV_SINGLE_CANDIDATE_FAST", "SHENGJI_PV_BELIEF_LOG", "SHENGJI_PV_BELIEF_CAPACITY",
                "SHENGJI_PV_BURY_TWO_STAGE", "SHENGJI_PV_BURY_KITTY_CHARGE",
                "SHENGJI_PV_VALUE_DECLARE_SERVED_BURY", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK"):
        assert key not in env
    assert (env["SHENGJI_PV_WORLDS"], env["SHENGJI_PV_CANDIDATES"]) == ("64", "8")
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_PV_LEAF_GREEDY_DEADLINE"] == "2"
    assert (env["SHENGJI_PV_BURY_WIDE_VALUE"], env["SHENGJI_PV_BURY_WIDE_K"]) == ("1", "64")
    assert all(env[key] == "1" for key in LATENCY_KEYS.values())
    assert env["SHENGJI_FAST"] == "1" and env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"


def test_the_volume_paths_derive_the_served_name(monkeypatch):
    """The name the server registers from release 50's env (volume paths, hashes
    stood in for the files): the package paths do not enter it, only their hashes."""
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv

    env = fly_env()
    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA, BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    recipe = pv.pv_env_recipe(env)
    assert recipe["bury_belief_worlds"] is True
    assert (recipe["prior_checkpoint"], recipe["prior_sha256"]) == (PRIOR_VOLUME_PATH, PRIOR_SHA)
    names = list(pv.singleton_registry_entries(**recipe))
    plain = list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))
    assert names == [env["SHENGJI_BOT"]] == [RELEASE50] == [plain[0] + "-sc8"]
    assert RELEASE50.startswith("pv-search-f4f4127e-prior-1fa201b2-w64-k8-")
    assert "-xfcompactlevel-lcc32-r" in RELEASE50 and "-bury-hybrid-bwv-bbw-" in RELEASE50


def test_served_bot_is_release50(release50_packages, monkeypatch):
    from shengji.ai.endgame_compact import default_backend
    from shengji.eval.served_config import registry_name
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    assert registry_name(local_env(release50_packages)) == RELEASE50
    name, bot = served_bot(release50_packages, monkeypatch)
    assert name == bot.policy_name == RELEASE50
    assert isinstance(bot, SingletonChallengerBuryBot)
    # the three packages: G3 A value, FT1 prior, B1a belief at its stored temperature
    assert bot.checkpoint_sha256 == VALUE_SHA
    assert bot.prior_sha256 == PRIOR_SHA and bot.prior_checkpoint == str(release50_packages["prior"])
    assert bot.belief_model is not None and bot.belief_model.package_sha256 == BELIEF_SHA
    assert bot.belief_model.temperature == BELIEF_TEMPERATURE and bot.belief_log is True
    assert bot.model_ids("play") == {"value": VALUE_SHA[:8], "prior": PRIOR_SHA[:8],
                                     "belief": BELIEF_SHA[:8]}
    # bbw: the wide value-only bury on belief worlds, value only
    assert bot.bury_belief_worlds is True and bot.bury_wide_value is True and bot.bury_wide_k == 64
    assert bot.model_ids("bury") == {"value": VALUE_SHA[:8], "prior": None, "belief": BELIEF_SHA[:8]}
    # release 49 underneath: lcc32 and sc8, dtrx, the guarded greedy finish, exact endgame
    assert bot.lead_confirm == 32 and bot.config.lead_confirm == 32
    assert not (bot.admit_forced_single or bot.finish_lead_admission or bot.small_joker_guard)
    assert not (bot.adaptive_worlds or bot.adaptive_worlds_leads or bot.wide_lead_admission)
    assert bot.doomed_throw_reselect is True and bot.doomed_throw_reselect_exact_guard is True
    assert (bot.leaf_greedy_finish, bot.leaf_greedy_finish_exact_skip,
            bot.leaf_greedy_deadline_ms) == (True, True, 2000)
    assert (bot.world_history_legal, bot.world_history_draw, bot.belief_worlds) == (True, True, True)
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (True, 7, True)
    assert (bot.exact_follow_solver, bot.exact_follow_max_cards,
            bot.exact_follow_max_nodes) == ("compact-level", 7, 50_000_000)
    assert (bot.value_declare, bot.value_declare_every_first) == (True, True)
    assert (bot.worlds, bot.candidates) == (64, 8)
    assert bot.serving_budget_seconds == 3.0 and bot.bury_serving_budget_seconds == 2.0
    for attr in LATENCY_KEYS:
        assert getattr(bot, attr) is True
    assert bot.single_candidate_fast is False
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    assert default_backend() == expected


def test_healthz_reports_the_value_package_and_the_latency_switches(release50_packages, monkeypatch):
    from shengji.api import server as srv

    monkeypatch.setenv("SHENGJI_PV_CKPT", str(release50_packages["value"]))
    apply_to_process(monkeypatch, {k: fly_env()[k] for k in (*LATENCY_KEYS.values(), *Y_CHANGES)})
    health = srv._pv_search_health()
    assert health["sha256"] == VALUE_SHA
    assert health["latency_switches"] == {
        "encode_prefix_cache": True, "single_candidate_fast": False,
        "leaf_greedy_stream": True, "encode_batch_fast": True, **{k: True for k in NATIVE_OFF}}


def test_served_lead_runs_on_the_release50_packages_through_the_server_path(
        release50_packages, tmp_path, monkeypatch):
    """One lead by the release-50 bot, built with its [env] in the process
    environment, through ``_paced_bot_step`` / ``_commit_bot_turn``: the worlds are
    proposed by the real B1a model with no fallback, the FT1 prior and the G3 A value
    package are the ones the record names, and both lead rules run.

    The wall clocks are lifted so a slow or cold CI runner cannot turn this wiring
    witness into a timing test (serving latency is measured on the intended host)."""
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    name, bot = served_bot(release50_packages, monkeypatch, seed=7)
    assert name == RELEASE50
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    seat = rnd.turn
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="R50", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        assert searched.policy_name == RELEASE50 and searched.prior_sha256 == PRIOR_SHA
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
    assert record["model_ids"] == {"value": VALUE_SHA[:8], "prior": PRIOR_SHA[:8], "belief": BELIEF_SHA[:8]}
    assert "singleton_challenger_applied" in record
    assert record["lead_confirm_status"] in ("applied", "rejected", "no_challenger", "no_pool")


def test_served_bury_is_decided_on_belief_worlds(release50_packages, monkeypatch):
    """One bury by the served bot: the candidates are scored on B1a's worlds (no
    belief fallback, no heuristic fallback) and the record names the packages."""
    from test_cwv_bury_wide_value import bury_state

    name, bot = served_bot(release50_packages, monkeypatch)
    assert name == RELEASE50
    bot.bury_serving_budget_seconds = 120.0        # a cold or slow runner never expires it
    rnd = bury_state(63)
    chosen = bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-policy-v1"
    assert (record["bury_belief_fallbacks"], record["bury_belief_error"]) == (0, None)
    assert record["bury_belief_worlds"] is True
    assert record["world_counts"]["model_attempts"] == bot.bury_config.model_worlds
    assert record["model_ids"] == {"value": VALUE_SHA[:8], "prior": None, "belief": BELIEF_SHA[:8]}
    assert len(chosen) == 8


def test_rollback_to_release49_restores_its_packages_and_drops_the_three_lines(
        pinned_production_package, pinned_release48_belief_package, monkeypatch):
    from shengji.eval.singleton_challenger import SingletonChallengerBuryBot

    env = release49_env(fly_env())
    assert not set(RELEASE50_ADDED_KEYS) & set(env)
    name, bot = release49_served_bot(pinned_production_package, pinned_release48_belief_package,
                                     monkeypatch, env=env)
    assert name == env["SHENGJI_BOT"] == RELEASE49
    assert isinstance(bot, SingletonChallengerBuryBot) and bot.checkpoint_sha256 == PACKAGE_SHA
    assert bot.prior_sha256 is None and bot.bury_belief_worlds is False
    assert bot.belief_model.package_sha256 == S58_SHA and bot.lead_confirm == 32
    for attr in LATENCY_KEYS:
        assert getattr(bot, attr) is True
