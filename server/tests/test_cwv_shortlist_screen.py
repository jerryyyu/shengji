"""Pure wiring and receipt tests for the exhaustive shortlist screen."""
import copy
from types import SimpleNamespace

import pytest

from shengji.train import cwv_shortlist_screen as S


def cfg(arm="uniform", **overrides):
    value = {
        "schema": "cwv-shortlist-config-v1", "arm": arm,
        "checkpoint": None, "checkpoint_sha256": None,
        "shortlist": {"worlds": 1, "selection_worlds": 30,
                       "alternatives": 4, "batch_size": 128,
                       "uniform": arm == "uniform"},
        "report_worlds": 300, "production_multiplier": 1,
        "target_wall_multiplier": 1, "seed0": 17, "clusters": 1,
    }
    value.update(overrides)
    return value


def test_baseline_dose_is_fixed_when_production_arm_is_scaled():
    baseline = S.make_side(cfg("production", production_multiplier=3), "baseline", 1)
    arm = S.make_side(cfg("production", production_multiplier=3), "arm", 1)
    assert (baseline.N_DETERMINIZATIONS, baseline.REPORT_FOLD_WORLDS) == (30, 300)
    assert (arm.N_DETERMINIZATIONS, arm.REPORT_FOLD_WORLDS) == (90, 900)


@pytest.mark.parametrize("options, expected", [
    (["--arm", "production", "--production-multiplier", "10",
      "--target-wall-multiplier", "10"], (300, 3000, 1)),
    (["--arm", "learned", "--checkpoint", "fixture", "--worlds", "64",
      "--target-wall-multiplier", "20"], (30, 300, 64)),
    (["--arm", "learned", "--checkpoint", "fixture", "--worlds", "32",
      "--selection-worlds", "60", "--report-worlds", "600",
      "--target-wall-multiplier", "10"], (60, 600, 32)),
])
def test_scaling_cli_wires_exact_arm_without_scaling_baseline(tmp_path, monkeypatch, options, expected):
    captured = {}
    evaluator = SimpleNamespace(checkpoint_sha256="fixture", identity=lambda: {"fixture": True})
    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: evaluator)
    monkeypatch.setattr(S, "execution_source_identity", lambda _path: {"test": "fixture"})
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")

    def pending(config, cluster_ids, shards, *, workers, **kwargs):
        captured.update(config)
        assert cluster_ids == list(range(256))
        assert workers == 16
        assert shards == []

    monkeypatch.setattr(S, "_run_pending", pending)
    assert S.main([*options, "--seed0", "90260904", "--clusters", "256",
                   "--workers", "16", "--out", str(tmp_path)]) == 0
    arm = S.make_side(captured, "arm", 7)
    baseline = S.make_side(captured, "baseline", 7)
    assert (arm.N_DETERMINIZATIONS, arm.REPORT_FOLD_WORLDS,
            captured["shortlist"]["worlds"]) == expected
    assert (baseline.N_DETERMINIZATIONS, baseline.REPORT_FOLD_WORLDS) == (30, 300)
    assert captured["shortlist"]["alternatives"] == 4
    assert captured["shortlist"]["batch_size"] == 128


def test_worker_refuses_changed_checkpoint_before_policy_construction(monkeypatch):
    class Evaluator:
        checkpoint_sha256 = "worker-sha"

    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    config = cfg("learned", checkpoint="checkpoint.pt",
                 checkpoint_sha256="configured-sha")
    with pytest.raises(ValueError, match="^checkpoint changed between configuration and worker$"):
        S.make_side(config, "arm", 1)


def test_forced_shortlist_is_traced_even_without_inherited_record():
    class Bot:
        last_decision_record = None
        last_shortlist = {"counts": {"forced": 1}, "legal_count": 1}

        def decide_play(self, rnd, seat):
            return ["2"]

    policy = S.CwvTimedPolicy(Bot())
    result = policy.decide_play(SimpleNamespace(history=[]), 2)
    assert result == ["2"]
    assert policy.decisions[0]["forced"] is True
    assert policy.decisions[0]["cwv_shortlist"]["legal_count"] == 1


def test_reopen_binds_recipe_and_rank(tmp_path):
    config = cfg()
    shard = {
        "schema": "cwv-shortlist-shard-v1", "cluster": 0, "seed": 17,
        "rank": "2", "recipe": S._recipe(config),
        "records": [{"cluster": 0, "seed": 17, "mirror": 0,
                      "trump_rank": "2", "arm": "uniform"},
                     {"cluster": 0, "seed": 17, "mirror": 1,
                      "trump_rank": "2", "arm": "uniform"}],
    }
    path = tmp_path / "cluster-00000.json"
    path.write_text(__import__("json").dumps(shard))
    assert S.reopen_shard(path, config, 0) == shard
    changed = copy.deepcopy(config)
    changed["shortlist"]["alternatives"] = 3
    with pytest.raises(ValueError, match="^completed shard does not match"):
        S.reopen_shard(path, changed, 0)


def test_summary_flags_wall_target_without_censoring_completion(monkeypatch):
    captured = {}

    def summarize(records, base, **kwargs):
        captured["records"] = records
        return {"work_totals": {
            "arm": {"decision_cpu_seconds": 4, "decision_wall_seconds": 4},
            "baseline": {"decision_cpu_seconds": 2, "decision_wall_seconds": 2},
        }}

    monkeypatch.setattr(S.duel, "summarize", summarize)
    config = cfg(target_wall_multiplier=1, clusters=1)
    result = S.summary_for([{"records": ["sentinel"]}], config)
    assert captured["records"] == ["sentinel"]
    assert result["complete"]
    assert result["arm_over_baseline_decision_cpu"] == 2
    assert result["arm_over_baseline_decision_wall"] == 2
    assert result["decision_wall_target_status"] == "over_target"
    assert result["equal_work_strength_claim"] is False
