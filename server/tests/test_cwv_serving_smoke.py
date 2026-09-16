"""The server-path smoke builds the bot from a fly.toml env exactly as the server does and
plays through the server's own bot-turn path (the release 25 incident, #435).

Witnessed both ways on real tiny packages: a consistent config passes with a bury and play
turns committed through ``_paced_bot_step`` / ``_commit_bot_turn``; a fly.toml whose
SHENGJI_BOT is not the name its own env registers is refused before any play (the server
would not boot with it); a prior whose deepcopy fails is surfaced as FAIL, not hidden.
"""
import copy
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.cwv_serving_smoke import env_from_fly_toml, run_smoke
from shengji.engine import combos, fast

from test_cwv_shortlist_registry import checkpoint  # noqa: F401
from test_cwv_prior_admission import prior_ckpt  # noqa: F401

pytestmark = pytest.mark.skipif(not (fast.HAVE_FAST and combos.decompose is fast.decompose),
                                reason="server-path smoke runs in the compiled engine only")

FLY = """
[env]
  SHENGJI_BOT = '{bot}'
  SHENGJI_CWV_SHORTLIST_CKPT = '/data/models/value.npz'
  SHENGJI_CWV_PRIOR_CKPT = '/data/models/prior.npz'
  SHENGJI_CWV_PRIOR_THRESHOLD = '6'
  SHENGJI_CWV_PRIOR_TOP = '5'
  SHENGJI_CWV_BURY_ARM = 'hybrid'
  SHENGJI_CWV_BURY_MAX_CANDIDATES = '2'
  SHENGJI_CWV_BURY_MODEL_WORLDS = '1'
  SHENGJI_CWV_BURY_SELECTION_WORLDS = '1'
  SHENGJI_CWV_BURY_ALTERNATIVES = '1'
  SHENGJI_CWV_BURY_SERVING_BUDGET_SECONDS = '2'
  SHENGJI_CWV_SHORTLIST_WORLDS = '2'
  SHENGJI_CWV_SHORTLIST_SELECTION_WORLDS = '2'
  SHENGJI_CWV_SHORTLIST_REPORT_WORLDS = '30'
  SHENGJI_MODEL_SEARCH_CONCURRENCY = '1'
"""


@pytest.fixture(scope="module")
def packages(checkpoint, prior_ckpt, tmp_path_factory):
    from scripts.export_cwv_numpy import export_cwv_numpy
    from scripts.export_policy_prior_numpy import export_policy_prior_numpy
    d = tmp_path_factory.mktemp("smoke")
    export_cwv_numpy(checkpoint, d / "value.npz")
    export_policy_prior_numpy(prior_ckpt[0], d / "prior.npz")
    return {"/data/models/value.npz": str(d / "value.npz"), "/data/models/prior.npz": str(d / "prior.npz")}


def _registered_name(mapped_env):
    from shengji.train.cwv_bury_policy import bury_env_recipe, bury_registry_entries
    checkpoint, worlds, recipe, arm, config, budget = bury_env_recipe(mapped_env)
    names = bury_registry_entries(checkpoint, worlds, arm=arm, bury_config=config,
                                  serving_budget_seconds=budget, **recipe)
    name, = names
    return name


def test_consistent_config_plays_bury_and_play_through_the_server(packages, tmp_path, monkeypatch):
    fly = tmp_path / "fly.toml"
    fly.write_text(FLY.format(bot="placeholder"))
    env = env_from_fly_toml(fly, packages)
    name = _registered_name(env)
    fly.write_text(FLY.format(bot=name))
    env = env_from_fly_toml(fly, packages)
    receipt = run_smoke(env, turns=4)
    assert receipt["passed"] is True and receipt["policy"] == name
    assert [t["phase"] for t in receipt["turns"]][:2] == ["bury", "play"]
    assert set(receipt["files"]) == {"SHENGJI_CWV_SHORTLIST_CKPT", "SHENGJI_CWV_PRIOR_CKPT"}


def test_a_bot_name_the_env_does_not_register_is_refused_before_play(packages, tmp_path):
    fly = tmp_path / "fly.toml"
    fly.write_text(FLY.format(bot="mc-shortlist-deadbeef-w32-r00000000-prior-00000000-bury-hybrid-000000000000"))
    env = env_from_fly_toml(fly, packages)
    with pytest.raises(SystemExit, match="not registered by this env"):
        run_smoke(env, turns=1)


def test_a_prior_that_cannot_be_deep_copied_fails_the_smoke(packages, tmp_path, monkeypatch):
    """The release 25 failure shape: the snapshot's deepcopy raises before any search."""
    from shengji.ai import cwv_prior_numpy
    def boom(self, memo):
        raise TypeError("cannot pickle 'mappingproxy' object")
    monkeypatch.setattr(cwv_prior_numpy.CWVNumpyPrior, "__deepcopy__", boom, raising=False)
    fly = tmp_path / "fly.toml"
    fly.write_text(FLY.format(bot="placeholder"))
    env = env_from_fly_toml(fly, packages)
    fly.write_text(FLY.format(bot=_registered_name(env)))
    env = env_from_fly_toml(fly, packages)
    with pytest.raises(TypeError, match="mappingproxy"):
        run_smoke(env, turns=1)


def test_cli_exit_status_follows_the_verdict(packages, tmp_path):
    fly = tmp_path / "fly.toml"
    fly.write_text(FLY.format(bot="placeholder"))
    env = env_from_fly_toml(fly, packages)
    fly.write_text(FLY.format(bot=_registered_name(env)))
    receipt = tmp_path / "smoke.json"
    cmd = [sys.executable, "-P", "-B", str(Path(__file__).parents[1] / "scripts" / "cwv_serving_smoke.py"),
           "--fly-toml", str(fly), "--turns", "3", "--receipt", str(receipt)]
    for volume, local in packages.items():
        cmd += ["--map", f"{volume}={local}"]
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=Path(__file__).parents[1])
    assert run.returncode == 0 and run.stdout.startswith("PASS"), run.stdout + run.stderr
    assert receipt.exists()
