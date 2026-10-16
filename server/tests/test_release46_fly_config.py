"""Release 46: the shipping ``fly.toml`` serves the deeper exact endgame search.

The served bot is built from the repo's ``fly.toml`` environment exactly as the
server builds it (``pv_env_recipe`` -> ``pv_registry_entries`` -> the factory) on
the hash-pinned production package, so the registry name, the exact-stage knobs
and the compact solver's backend are witnessed on this tree.  The package test
fails, never skips, under ``SHENGJI_REQUIRE_PV_PACKAGE=1`` (the CI package-gate
step, which runs ``SHENGJI_FAST=1`` on the compiled engine, the image's runtime).
"""
import os
import tomllib
from pathlib import Path

from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA  # noqa: F401
from test_pv_search_serving import _play_state

RELEASE45 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
#: the candidate name v87dx45 screened (#707 issuecomment-6203794263), registered by #1039
RELEASE46 = ("pv-search-491ee4bf-w64-k8-div-rc-tb-ele-la-dtr-vd-ed6-xf6-xfcompactlevel-"
             "rd774ea98-bury-hybrid-bwv-ba1c68b8fa9a")
#: the candidate arm's env as v87's launcher exported and verified it on every sealed window
V87_CANDIDATE_ENV = {"SHENGJI_PV_EXACT_LEAD_ENDGAME": "1",
                     "SHENGJI_PV_EXACT_DEEP_CARDS": "6",
                     "SHENGJI_PV_EXACT_FOLLOW": "1",
                     "SHENGJI_PV_EXACT_FOLLOW_SOLVER": "compact-level",
                     "SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS": "6",
                     "SHENGJI_PV_EXACT_FOLLOW_MAX_NODES": "50000000"}
EXACT_KEYS = tuple(V87_CANDIDATE_ENV)


def fly_env() -> dict:
    return tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]


def served_entries(path):
    from shengji.train import pv_search_policy as pv

    env = fly_env()
    recipe = pv.pv_env_recipe({**env, "SHENGJI_PV_CKPT": str(path),
                               "SHENGJI_PV_SHA256": PACKAGE_SHA})
    entries = pv.pv_registry_entries(**recipe)
    name, = entries
    return env, name, entries[name]


def test_fly_toml_carries_the_v87_candidate_env():
    env = fly_env()
    assert {k: env[k] for k in EXACT_KEYS} == V87_CANDIDATE_ENV
    assert env["SHENGJI_BOT"] == RELEASE46
    assert "SHENGJI_PV_EXACT_LEAD_TIE_BASELINE" not in env
    assert "SHENGJI_PV_EXACT_LEAD_POLICY_FIRST" not in env
    # the exact stages run inside the unchanged play budget on the compiled engine
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_FAST"] == "1"
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"


def test_served_bot_is_the_screened_candidate_on_the_compiled_solver(pinned_production_package):
    from shengji.ai.endgame_compact import CompactWorldSession, HAVE_FAST, default_backend
    from shengji.train.pv_search_policy import PVSearchBuryBot

    env, name, factory = served_entries(pinned_production_package)
    assert name == env["SHENGJI_BOT"] == RELEASE46
    bot = factory(seed=17)
    assert isinstance(bot, PVSearchBuryBot) and bot.checkpoint_sha256 == PACKAGE_SHA
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (True, 6, True)
    assert (bot.config.exact_lead_endgame, bot.config.exact_deep_cards,
            bot.config.exact_follow) == (True, 6, True)
    knobs = ("compact-level", 6, 50_000_000)
    assert (bot.exact_follow_solver, bot.exact_follow_max_cards, bot.exact_follow_max_nodes) == knobs
    assert (bot.config.exact_follow_solver, bot.config.exact_follow_max_cards,
            bot.config.exact_follow_max_nodes) == knobs
    assert (bot.exact_lead_tie_baseline, bot.exact_lead_policy_first) == (False, False)
    # release 45 underneath: W64/K8, the wide value-only bury at K=64, vd and dtr
    assert (bot.worlds, bot.candidates, bot.bury_wide_value, bot.bury_wide_k) == (64, 8, True, 64)
    assert (bot.value_declare, bot.doomed_throw_reselect) == (True, True)
    # The compact-level session the follow and deep-lead stages open takes the default
    # backend: "compiled" exactly when SHENGJI_FAST=1 activated the engine at package import
    # and _endgame_fast is built (the image's runtime and the CI package gate); the pure
    # twin, identical results, otherwise.
    expected = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "python"
    if expected == "compiled":
        assert HAVE_FAST, "SHENGJI_FAST=1 but shengji/ai/_endgame_fast is not built"
    assert default_backend() == expected
    session = CompactWorldSession(_play_state(), max_hand_cards=6, max_nodes=50_000_000,
                                  alpha_beta=True, level=True)
    assert session.backend == expected


def test_rollback_to_release45_is_the_env_without_the_six_exact_lines(pinned_production_package):
    from shengji.train import pv_search_policy as pv

    env = {k: v for k, v in fly_env().items() if k not in EXACT_KEYS}
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(
        {**env, "SHENGJI_PV_CKPT": str(pinned_production_package), "SHENGJI_PV_SHA256": PACKAGE_SHA}))
    name, = entries
    assert name == RELEASE45
    bot = entries[name](seed=17)
    assert (bot.exact_lead_endgame, bot.exact_deep_cards, bot.exact_follow) == (False, 0, False)
    assert (bot.worlds, bot.candidates, bot.bury_wide_value, bot.bury_wide_k) == (64, 8, True, 64)
