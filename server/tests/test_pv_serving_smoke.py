"""The serving smoke (`scripts/cwv_serving_smoke.py`) builds the pv-search mode (#585)
exactly as the server would from a fly.toml ``[env]`` and plays bury + play turns
through `_paced_bot_step` / `_commit_bot_turn` — the release-25 witness, on this mode."""
import pytest

from scripts.cwv_serving_smoke import build_production_bot, run_smoke
from shengji.ai.registry import REGISTRY
from shengji.engine import combos, fast
from shengji.train import pv_search_policy as pv
from test_pv_search_serving import package  # noqa: F401
from native_switches import NATIVE_OFF

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


SWITCHES = {"encode_prefix_cache": "SHENGJI_PV_ENCODE_PREFIX_CACHE",
            "leaf_greedy_stream": "SHENGJI_PV_LEAF_GREEDY_STREAM",
            "encode_batch_fast": "SHENGJI_PV_ENCODE_BATCH_FAST"}


def test_the_smoke_builds_with_the_fly_env_in_the_process_environment(package, clean_registry,
                                                                      monkeypatch):
    """The latency switches are read from the process environment where the bot is
    built (they enter no name), so the smoke must build with fly.toml's [env]
    exported as the server boots with it, and restore the environment after."""
    import os

    path, sha = package
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    env, name = _env(path, sha, **{key: "1" for key in SWITCHES.values()})
    _, plain = build_production_bot(_env(path, sha)[0])
    assert not set(SWITCHES) & set(vars(plain))
    built_name, bot = build_production_bot(env)
    assert built_name == name
    for attr in SWITCHES:
        assert vars(bot)[attr] is True
    assert bot.single_candidate_fast is False
    # the overlay is scoped to the build
    assert not set(SWITCHES.values()) & set(os.environ)
    assert os.environ.get("SHENGJI_PV_CKPT") != path
    receipt = run_smoke(env, turns=4)
    assert receipt["passed"] is True
    assert receipt["latency_switches"] == {"encode_prefix_cache": True, "single_candidate_fast": False,
                                           "leaf_greedy_stream": True, "encode_batch_fast": True, **NATIVE_OFF}


def test_an_ambient_switch_absent_from_the_fly_env_does_not_reach_the_bot(package, clean_registry,
                                                                         monkeypatch):
    """A latency switch set in the invoking shell but absent from fly.toml's [env]
    enters no name, so the smoke would build a different bot under the expected
    name; the build scope clears it, then restores the shell's value."""
    import os

    path, sha = package
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SHENGJI_PV_SINGLE_CANDIDATE_FAST", "1")
    monkeypatch.setenv(pv.BELIEF_LOG_ENV, "1")
    env, name = _env(path, sha, **{key: "1" for key in SWITCHES.values()})
    assert "SHENGJI_PV_SINGLE_CANDIDATE_FAST" not in env
    built_name, bot = build_production_bot(env)
    assert built_name == name
    assert bot.single_candidate_fast is False
    for attr in SWITCHES:
        assert vars(bot)[attr] is True
    assert os.environ["SHENGJI_PV_SINGLE_CANDIDATE_FAST"] == "1"
    assert os.environ[pv.BELIEF_LOG_ENV] == "1"


def test_the_build_scope_restores_the_shell_after_an_error(monkeypatch):
    """The scope restores every key it touched when the build raises."""
    import os

    from scripts.cwv_serving_smoke import process_env

    monkeypatch.setenv("SHENGJI_PV_SINGLE_CANDIDATE_FAST", "1")
    monkeypatch.delenv("SHENGJI_PV_ENCODE_PREFIX_CACHE", raising=False)
    try:
        with process_env({"SHENGJI_PV_ENCODE_PREFIX_CACHE": "1"}):
            assert "SHENGJI_PV_SINGLE_CANDIDATE_FAST" not in os.environ
            assert os.environ["SHENGJI_PV_ENCODE_PREFIX_CACHE"] == "1"
            raise RuntimeError("build failed")
    except RuntimeError:
        pass
    assert os.environ["SHENGJI_PV_SINGLE_CANDIDATE_FAST"] == "1"
    assert "SHENGJI_PV_ENCODE_PREFIX_CACHE" not in os.environ
