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
    env = runner.recipe_environment(fly, tmp_path)
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
        runner.recipe_environment(changed, tmp_path)
