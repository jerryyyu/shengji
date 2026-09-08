"""Wiring contracts for the opt-in CWV points-leaf screen arm."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_leaf_shortlist import CWVPointsLeafShortlistBot
from tests.test_cwv_shortlist_screen import cfg
from tests.test_world_shortlist import play_state


SHA = "a" * 64


class Evaluator:
    checkpoint_sha256 = SHA
    enc_version = 1

    def identity(self):
        return {"checkpoint_sha256": self.checkpoint_sha256,
                "enc_version": self.enc_version}

    def score(self, leaves, seat, **kwargs):
        return np.zeros(len(leaves), dtype=np.float64)


class Head:
    def __init__(self, sha=SHA, enc_version=1):
        self.metadata = {"checkpoint_sha256": sha}
        self.enc_version = enc_version


class ConstantPointsLeaf:
    kind = "test-cwv"
    points_clamp = "banked-v1"

    def __init__(self, value=50.0):
        self.value = value
        self.clamp_counts = {"predicted": 0, "clamped": 0, "lift_points": 0.0}

    def final_attacker_points(self, clone, seat):
        self.clamp_counts["predicted"] += 1
        return self.value


def leaf_recipe(**overrides):
    result = {"schema": "cwv-shortlist-points-leaf-v1", "tricks": 1,
              "view": "last_actor", "stage": "all", "clamp": "banked-v1"}
    result.update(overrides)
    return result


def learned_config(**overrides):
    return cfg("learned", checkpoint="ranking.pt", checkpoint_sha256=SHA,
               points_leaf=leaf_recipe(), **overrides)


def test_cli_persists_points_leaf_recipe_and_dispatches_only_arm(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    monkeypatch.setattr(S, "load_cwv_points_head", lambda path: Head())
    dispatched = []
    monkeypatch.setattr(S, "_run_pending", lambda config, *args, **kwargs:
                        dispatched.append(config))
    out = tmp_path / "screen"
    assert S.main(["--arm", "learned", "--checkpoint", "ranking.pt",
                   "--points-leaf-tricks", "1", "--points-leaf-view", "last_actor",
                   "--worlds", "1", "--selection-worlds", "1", "--report-worlds", "30",
                   "--clusters", "1", "--workers", "1", "--seed0", "17",
                   "--out", str(out)]) == 0
    config = json.loads((out / "config.json").read_text())
    assert dispatched == [config]
    assert config["points_leaf"] == leaf_recipe()
    arm = S.make_side(config, "arm", 23)
    baseline = S.make_side(config, "baseline", 23)
    assert type(arm) is CWVPointsLeafShortlistBot
    assert type(baseline) is not CWVPointsLeafShortlistBot
    assert not hasattr(baseline, "shortlist_config")
    assert arm.leaf_view == "last_actor" and arm.leaf_stage == "all"
    assert arm.raw_points_leaf.head.metadata["checkpoint_sha256"] == SHA
    assert baseline.N_DETERMINIZATIONS == 30
    assert baseline.REPORT_FOLD_WORLDS == 300


@pytest.mark.parametrize("bad", [
    {"metadata": {"checkpoint_sha256": "b" * 64}, "enc_version": 1},
    {"metadata": {"checkpoint_sha256": SHA}, "enc_version": 2},
])
def test_points_head_identity_refuses_before_worker_dispatch(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    monkeypatch.setattr(S, "load_cwv_points_head", lambda path: SimpleNamespace(**bad))
    dispatched = []
    monkeypatch.setattr(S, "_run_pending", lambda *args, **kwargs: dispatched.append(True))
    with pytest.raises(ValueError, match="^points leaf differs from ranking checkpoint or encoder$"):
        S.main(["--arm", "learned", "--checkpoint", "ranking.pt",
                "--points-leaf-tricks", "1", "--clusters", "1", "--workers", "1",
                "--seed0", "17", "--out", str(tmp_path / "screen")])
    assert dispatched == []


@pytest.mark.parametrize("args", [
    ["--arm", "uniform", "--points-leaf-tricks", "1"],
    ["--arm", "learned", "--checkpoint", "ranking.pt", "--points-leaf-view", "mover"],
    ["--arm", "learned", "--checkpoint", "ranking.pt", "--points-leaf-tricks", "1",
     "--inner-mode", "learned"],
])
def test_cli_rejects_points_leaf_combinations_before_loading_evaluator(tmp_path, monkeypatch, args):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator",
                        lambda *a, **k: pytest.fail("invalid config loaded evaluator"))
    with pytest.raises(SystemExit):
        S.main([*args, "--clusters", "1", "--workers", "1", "--seed0", "17",
                "--out", str(tmp_path / "screen")])


def test_recipe_validation_binds_points_leaf_and_refuses_drift():
    config = learned_config()
    assert S._points_leaf_recipe(config) == config["points_leaf"]
    assert S._recipe(config)["points_leaf"] == config["points_leaf"]
    changed = copy.deepcopy(config)
    changed["points_leaf"]["view"] = "mover"
    with pytest.raises(ValueError, match="^completed shard does not match"):
        S.reopen_shard(
            SimpleNamespace(read_text=lambda: json.dumps({
                "schema": "cwv-shortlist-shard-v1", "cluster": 0, "seed": 17,
                "rank": "2", "recipe": S._recipe(config),
                "records": [{"cluster": 0, "seed": 17, "mirror": 0,
                             "trump_rank": "2", "arm": "learned"},
                            {"cluster": 0, "seed": 17, "mirror": 1,
                             "trump_rank": "2", "arm": "learned"}],
            })), changed, 0)


@pytest.mark.parametrize("field,value", [("schema", "wrong"), ("tricks", -1),
                                          ("stage", "report"), ("clamp", "none")])
def test_invalid_persisted_points_leaf_recipe_refuses(field, value):
    config = learned_config()
    config["points_leaf"][field] = value
    with pytest.raises(ValueError, match="^invalid shortlist points-leaf recipe$"):
        S._points_leaf_recipe(config)


def test_timed_policy_and_counters_publish_points_leaf_telemetry(monkeypatch):
    config = learned_config()
    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    monkeypatch.setattr(S, "load_cwv_points_head", lambda path: Head())
    bot = S.make_side(config, "arm", 29)
    leaf = ConstantPointsLeaf()
    bot.leaf = bot.raw_points_leaf = leaf
    state = play_state()
    wrapped = S.CwvTimedPolicy(bot)
    wrapped.decide_play(state, state.turn)
    telemetry = wrapped.decisions[-1]["cwv_points_leaf"]
    assert telemetry["tricks"] == 1
    assert telemetry["view"] == "last_actor" and telemetry["stage"] == "all"
    assert telemetry["counts"]["predicted_leaves"] > 0
    counts = S.work_counters([wrapped])
    assert counts["points_leaf_predicted_leaves"] == telemetry["counts"]["predicted_leaves"]
    assert counts["points_leaf_report_net_calls"] > 0
    assert counts["rollout_invocations"] == counts["rollouts"] == counts["total_rollouts"]
    assert counts["continuation_rollouts"] == (
        counts["round_end_continuations"] + counts["exact_shortcuts"])
    assert counts["rollout_invocations"] == (
        counts["continuation_rollouts"] + counts["points_leaf_predicted_leaves"])
    assert counts["continuation_rollouts"] < counts["total_rollouts"]
    assert "full_rollout_accepted_worlds" not in counts
    assert counts["search_accepted_worlds"] == counts["accepted_worlds"] - counts["cwv_cheap_worlds"]


def test_points_leaf_summary_discloses_horizon_and_baseline(monkeypatch):
    captured = {}

    def summarize(records, base, **kwargs):
        captured["records"] = records
        return {"work_totals": {
            "arm": {"decision_cpu_seconds": 2, "decision_wall_seconds": 2},
            "baseline": {"decision_cpu_seconds": 1, "decision_wall_seconds": 1},
        }}

    monkeypatch.setattr(S.duel, "summarize", summarize)
    config = learned_config(target_wall_multiplier=1, clusters=1)
    result = S.summary_for([{"records": ["sentinel"]}], config)
    assert captured["records"] == ["sentinel"]
    assert result["arm_description"] == (
        "exhaustive learned root shortlist; T1 complete-world points leaf "
        "from last_actor, then unchanged root MC-LCB")
    assert result["baseline_description"] == "production"
    assert "points_leaf_predicted_leaves" in result["work_caveat"]
