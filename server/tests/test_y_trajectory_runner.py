"""The data runner binds its candidate to the deployed recipe."""
import importlib.util
from pathlib import Path

import pytest


_PATH = Path(__file__).resolve().parents[1] / "scripts" / "y_trajectory.py"
_SPEC = importlib.util.spec_from_file_location("y_trajectory", _PATH)
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


def test_recipe_keeps_served_budgets_and_latency_switches(tmp_path):
    fly = _PATH.parents[2] / "fly.toml"
    env = runner.recipe_environment(fly, tmp_path, recipe_mode="served-y")
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_PV_LEAF_GREEDY_DEADLINE"] == "2"
    assert env["SHENGJI_PV_ENCODE_NATIVE"] == "1"
    assert env["SHENGJI_PV_BELIEF_CKPT"] == str(tmp_path / "s58-e6-42444515.npz")
    assert "SHENGJI_DATA_DIR" not in env


@pytest.mark.parametrize("old,new", [
    ("SHENGJI_PV_SERVING_BUDGET_SECONDS = '3'", "SHENGJI_PV_SERVING_BUDGET_SECONDS = '0'"),
    ("SHENGJI_PV_CANDIDATES = '8'", "SHENGJI_PV_CANDIDATES = '24'"),
    ("/data/models/smv3out-491ee4bf.npz", "/data/models/../smv3out-491ee4bf.npz"),
])
def test_recipe_refuses_budget_width_and_model_path_drift(tmp_path, old, new):
    text = (_PATH.parents[2] / "fly.toml").read_text()
    assert old in text
    changed = tmp_path / "fly.toml"
    changed.write_text(text.replace(old, new))
    with pytest.raises(ValueError):
        runner.recipe_environment(changed, tmp_path, recipe_mode="served-y")


def test_legacy_refuses_already_y():
    with pytest.raises(ValueError, match="baseline already"):
        runner.recipe_environment(_PATH.parents[2] / "fly.toml", Path("/models"))


def test_incomplete_package_selection_refuses():
    with pytest.raises(ValueError, match="required together"):
        runner.bind_packages({}, Path("missing"), "a" * 64, None, None)


def test_changed_package_bytes_refuse(tmp_path):
    p = tmp_path / "weights.npz"
    p.write_bytes(b"changed")
    with pytest.raises(ValueError, match="mismatch"):
        runner.bind_packages({}, p, "a" * 64, p, "b" * 64)


def test_served_y_and_split_reach_real_bot_and_manifest(tmp_path, tmp_path_factory, monkeypatch, capsys):
    import json
    import os
    from tests.test_pv_search_prior_package import _joint_package
    from shengji.train import pv_search_policy as pv
    from shengji.ai import registry
    from shengji.harvest.trajectory import build_config, make_trajectory_bot
    import random
    value, value_sha = _joint_package(tmp_path_factory, 111)
    prior, prior_sha = _joint_package(tmp_path_factory, 222)
    env = {
        "SHENGJI_PV_CKPT": value, "SHENGJI_PV_SHA256": value_sha,
        "SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8",
        "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
        "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2",
        "SHENGJI_PV_SINGLETON_CHALLENGER": "1", "SHENGJI_PV_LEAD_CONFIRM": "32",
        "SHENGJI_PV_BURY_ARM": "hybrid",
    }
    if os.environ.get("SHENGJI_FAST") == "1":
        env["SHENGJI_FAST"] = "1"
    # Restore the complete environment after the runner's deliberate isolation.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for k in list(os.environ):
        if k.startswith("SHENGJI_"):
            del os.environ[k]
    os.environ.update(env)
    env["SHENGJI_BOT"] = next(iter(pv.singleton_registry_entries(**pv.pv_env_recipe())))
    env["SHENGJI_PV_CKPT"] = "/data/models/" + Path(value).name
    fly = tmp_path / "fly.toml"
    fly.write_text("[env]\n" + "\n".join(f"{k} = {v!r}" for k, v in env.items()))
    seeds = tmp_path / "seeds.json"
    seeds.write_text("{}")
    args = ["--fly", str(fly), "--models", str(Path(value).parent),
            "--seed-registry", str(seeds), "--recipe-mode", "served-y", "--inspect"]
    for extra, expected_prior in [([], None), (["--value-package", value, "--value-sha256", value_sha,
            "--prior-package", prior, "--prior-sha256", prior_sha], prior_sha)]:
        assert runner.main(args + extra) == 0
        record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        bot = registry.make_bot(record["candidate"], seed=0)
        assert bot.checkpoint_sha256 == value_sha
        assert bot.prior_sha256 == expected_prior
        assert bot.serving_budget_seconds == 3 and bot.bury_serving_budget_seconds == 2
        config = build_config(policy=record["candidate"], seed0=1,
                              capture_served_budget=True, explore_rate=0, explore_k=0)
        captured = make_trajectory_bot(config, seed=1, explore_rng=random.Random(2))
        assert captured.checkpoint_sha256 == value_sha
        assert captured.prior_sha256 == expected_prior
        assert captured.serving_budget_seconds == 3 and captured.bury_serving_budget_seconds == 2
        import subprocess
        import sys
        worker = """
import json, random, sys
from shengji.harvest.trajectory import make_trajectory_bot
config = json.loads(sys.stdin.read())
bot = make_trajectory_bot(config, seed=1, explore_rng=random.Random(2))
print(json.dumps([bot.checkpoint_sha256, bot.prior_sha256,
                  bot.serving_budget_seconds, bot.bury_serving_budget_seconds]))
"""
        fresh = subprocess.run([sys.executable, "-c", worker], input=json.dumps(config),
                               text=True, capture_output=True, env=dict(os.environ), timeout=30)
        assert fresh.returncode == 0, fresh.stderr
        assert json.loads(fresh.stdout) == [value_sha, expected_prior, 3, 2]
        runtime = config["served_runtime"]
        assert runtime["SHENGJI_Y_CAPTURE_HOST"] == runner.platform.node()
        assert runtime["SHENGJI_Y_CAPTURE_RECIPE_MODE"] == "served-y"
        if expected_prior:
            assert runtime["SHENGJI_PV_PRIOR_SHA256"] == expected_prior


def test_legacy_conversion_input_is_still_accepted(tmp_path):
    text = (_PATH.parents[2] / "fly.toml").read_text()
    text = text.replace("SHENGJI_PV_SINGLETON_CHALLENGER = '1'", "SHENGJI_PV_SINGLETON_CHALLENGER = '0'")
    text = text.replace("SHENGJI_PV_LEAD_CONFIRM = '32'", "SHENGJI_PV_LEAD_CONFIRM = '0'")
    fly = tmp_path / "legacy.toml"
    fly.write_text(text)
    assert runner.recipe_environment(fly, tmp_path)["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
