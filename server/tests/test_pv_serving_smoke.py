"""The serving smoke (`scripts/cwv_serving_smoke.py`) builds the pv-search mode (#585)
exactly as the server would from a fly.toml ``[env]`` and plays bury + play turns
through `_paced_bot_step` / `_commit_bot_turn` — the release-25 witness, on this mode."""
import pytest

from scripts.cwv_serving_smoke import build_production_bot, run_smoke
from shengji.ai.registry import REGISTRY
from shengji.engine import combos, fast
from shengji.train import pv_search_policy as pv
from test_pv_search_serving import package  # noqa: F401

pytestmark = pytest.mark.skipif(not (fast.HAVE_FAST and combos.decompose is fast.decompose),
                                reason="server-path smoke runs in the compiled engine only")


def _env(path, sha, **knobs):
    env = {"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha,
           "SHENGJI_PV_WORLDS": "3", "SHENGJI_PV_CANDIDATES": "4", "SHENGJI_PV_CAP": "400",
           "SHENGJI_PV_BATCH_SIZE": "16", "SHENGJI_PV_SERVING_BUDGET_SECONDS": "30",
           "SHENGJI_MODEL_SEARCH_CONCURRENCY": "1", "SHENGJI_FAST": "1"}
    env.update(knobs)
    recipe = pv.pv_env_recipe(env)
    name, = pv.pv_registry_entries(**recipe)
    env["SHENGJI_BOT"] = name
    return env, name


@pytest.fixture
def clean_registry():
    before = set(REGISTRY)
    yield
    for name in set(REGISTRY) - before:
        REGISTRY.pop(name, None)


def test_pv_search_env_registers_and_plays_through_the_server(package, clean_registry):
    path, sha = package
    env, name = _env(path, sha)
    built_name, bot = build_production_bot(env)
    assert built_name == name and isinstance(bot, pv.PVSearchBot)
    receipt = run_smoke(env, turns=12)
    assert receipt["passed"] is True
    assert receipt["policy"] == name and receipt["bot_class"] == "PVSearchBot"
    assert receipt["files"]["SHENGJI_PV_CKPT"]["sha256"] == sha
    phases = [t["phase"] for t in receipt["turns"]]
    assert "bury" in phases and phases.count("play") >= 4


def test_pv_search_env_with_the_wrong_sha_is_refused_before_play(package, clean_registry):
    path, sha = package
    env, _ = _env(path, sha)
    env["SHENGJI_PV_SHA256"] = "0" * 64
    with pytest.raises(pv.PVSearchPolicyError, match="on disk"):
        build_production_bot(env)
