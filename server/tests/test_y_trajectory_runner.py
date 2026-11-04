"""The data runner binds its candidate to the deployed recipe."""
import importlib.util
from pathlib import Path

import pytest

from test_release50_fly_config import release50_packages  # noqa: F401


_PATH = Path(__file__).resolve().parents[1] / "scripts" / "y_trajectory.py"
_SPEC = importlib.util.spec_from_file_location("y_trajectory", _PATH)
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


def test_recipe_keeps_served_budgets_and_latency_switches(tmp_path):
    fly = _PATH.parents[2] / "fly.toml"
    env = runner.recipe_environment(fly, tmp_path)
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "2"
    assert env["SHENGJI_PV_LEAF_GREEDY_DEADLINE"] == "2"
    assert env["SHENGJI_PV_ENCODE_NATIVE"] == "1"
    assert env["SHENGJI_PV_BELIEF_CKPT"] == str(tmp_path / "b1a-028131a0.npz")
    assert "SHENGJI_DATA_DIR" not in env
    assert not any(key.startswith("SHENGJI_CWV_") for key in env)


@pytest.mark.parametrize("old,new", [
    ("SHENGJI_PV_SERVING_BUDGET_SECONDS = '3'", "SHENGJI_PV_SERVING_BUDGET_SECONDS = '0'"),
    ("SHENGJI_PV_CANDIDATES = '8'", "SHENGJI_PV_CANDIDATES = '24'"),
    ("SHENGJI_PV_SINGLETON_CHALLENGER = '1'", "SHENGJI_PV_SINGLETON_CHALLENGER = '0'"),
    ("SHENGJI_PV_LEAD_CONFIRM = '32'", "SHENGJI_PV_LEAD_CONFIRM = '0'"),
    ("/data/models/g3a-e04-f4f4127e.npz", "/data/models/../g3a-e04-f4f4127e.npz"),
])
def test_recipe_refuses_budget_width_and_model_path_drift(tmp_path, old, new):
    text = (_PATH.parents[2] / "fly.toml").read_text()
    assert old in text
    changed = tmp_path / "fly.toml"
    changed.write_text(text.replace(old, new))
    with pytest.raises(ValueError):
        runner.recipe_environment(changed, tmp_path)


@pytest.mark.parametrize("capture", [False, True])
def test_runner_constructs_exact_served_bot(release50_packages, tmp_path, capture):
    import json
    import os
    import subprocess
    import sys
    import tomllib

    fly = _PATH.parents[2] / "fly.toml"
    env = tomllib.loads(fly.read_text())["env"]
    models = tmp_path / "models"
    models.mkdir()
    for role, key in (("value", "SHENGJI_PV_CKPT"),
                      ("prior", "SHENGJI_PV_PRIOR_CKPT"),
                      ("belief", "SHENGJI_PV_BELIEF_CKPT")):
        (models / Path(env[key]).name).symlink_to(release50_packages[role])
    from test_harvest_trajectory import _seed_windows
    output = tmp_path / "store"
    registry = _seed_windows(output)
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1", "windows": []}))
    options = (["--rounds", "2", "--workers", "1", "--seed", "4300000",
                "--out", str(output), "--cap", "256"] if capture else ["--inspect"])
    result = subprocess.run([
        sys.executable, str(_PATH), "--fly", str(fly), "--models", str(models),
        "--seed-registry", str(registry), *options,
    ], env={"PATH": os.environ["PATH"], "SHENGJI_PV_LEAD_CONFIRM": "0",
            "SHENGJI_PV_SINGLETON_CHALLENGER": "0"}, text=True,
        capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report["candidate"] == report["baseline"] == env["SHENGJI_BOT"]
    assert report["environment"]["SHENGJI_PV_BURY_BELIEF_WORLDS"] == "1"
    assert report["environment"]["SHENGJI_PV_PRIOR_SHA256"] == env["SHENGJI_PV_PRIOR_SHA256"]
    assert report["play_seconds"] == 3 and report["bury_seconds"] == 2

    if capture:
        from shengji.train.belief_labels import extract_cluster
        from shengji.train.cwv_data import bridge_record, search_means_points
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["config"]["policy"] == env["SHENGJI_BOT"]
        shard = output / manifest["shards"][0]["path"]
        records = [json.loads(line) for line in shard.read_text().splitlines()]
        plays = [row for row in records if row["decision_kind"] == "play"]
        buries = [row for row in records if row["decision_kind"] == "bury"]
        assert len(buries) == 2 and plays
        for row in plays:
            assert bridge_record(row) is not None
            search_means_points(row)
        labels = extract_cluster(shard, store_index=0, cluster_index=0,
                                 calib=0.0, test=0.0, windows=[],
                                 sampler_worlds=0, sampler_splits=[])
        assert labels is not None and len(labels["X"]) == len(plays)
        assert all(row["allocation"]["serving_decision"]["bury_belief_worlds"] for row in buries)
        assert manifest["counts"]["bury_belief_worlds"] == 2
        assert manifest["counts"]["bury_belief_fallbacks"] == sum(
            row["allocation"]["serving_decision"]["bury_belief_fallbacks"] for row in buries)


def test_runner_refuses_legal_capture_cap_drift(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["--fly", str(tmp_path / "absent.toml"), "--models", str(tmp_path),
                     "--seed-registry", str(tmp_path / "absent.json"), "--cap", "1"])
