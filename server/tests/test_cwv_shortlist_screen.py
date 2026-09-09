"""Pure wiring and receipt tests for the exhaustive shortlist screen."""
import copy
import json
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


def identity_summary(*args, **kwargs):
    """Shape returned by duel.summarize before summary_for adds screen metadata."""
    return {
        "arm": "none",
        "arm_description": "mc-s0-report-lcb on both sides (identity control)",
        "outcome_sentinel": {"utility": 7},
        "work_totals": {"arm": {}, "baseline": {}},
    }


def test_baseline_dose_is_fixed_when_production_arm_is_scaled():
    baseline = S.make_side(cfg("production", production_multiplier=3), "baseline", 1)
    arm = S.make_side(cfg("production", production_multiplier=3), "arm", 1)
    assert (baseline.N_DETERMINIZATIONS, baseline.REPORT_FOLD_WORLDS) == (30, 300)
    assert (arm.N_DETERMINIZATIONS, arm.REPORT_FOLD_WORLDS) == (90, 900)


def test_worker_refuses_changed_checkpoint_before_policy_construction(monkeypatch):
    class Evaluator:
        checkpoint_sha256 = "worker-sha"

    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    config = cfg("learned", checkpoint="checkpoint.pt",
                 checkpoint_sha256="configured-sha")
    with pytest.raises(ValueError, match="^checkpoint changed between configuration and worker$"):
        S.make_side(config, "arm", 1)


def test_production_union_cli_affects_only_treatment_and_binds_receipt(tmp_path, monkeypatch):
    from shengji.train.cwv_production_union import CWVProductionUnionBot
    from shengji.train.cwv_shortlist import CWVShortlistBot
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64,
                                identity=lambda: {"checkpoint_sha256": "a" * 64})
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **kw: evaluator)
    seen = []
    monkeypatch.setattr(S, "_run_pending", lambda config, *a, **kw: seen.append(config))
    out = tmp_path / "union"
    S.main(["--arm", "learned", "--checkpoint", "fixture.pt", "--production-union",
            "--baseline", "flat-shortlist", "--worlds", "32", "--seed0", "17",
            "--out", str(out)])
    config = json.loads((out / "config.json").read_text())
    assert config == seen[0] and config["production_union"] is True
    assert S._recipe(config)["production_union"] is True
    arm, base = S.make_side(config, "arm", 7), S.make_side(config, "baseline", 7)
    assert type(arm) is CWVProductionUnionBot and type(base) is CWVShortlistBot
    assert arm.evaluator is base.evaluator
    assert arm.shortlist_config == base.shortlist_config
    assert arm.N_DETERMINIZATIONS == base.N_DETERMINIZATIONS == 30
    assert arm.REPORT_FOLD_WORLDS == base.REPORT_FOLD_WORLDS == 300
    assert "production_union" not in S._recipe(cfg())


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


def test_cli_binds_k8_into_uniform_worker_and_persisted_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    seen = []

    def no_work(config, pending, shards, **kwargs):
        seen.append((config, pending, shards))

    monkeypatch.setattr(S, "_run_pending", no_work)
    out = tmp_path / "screen"
    assert S.main(["--arm", "uniform", "--alternatives", "8",
                   "--clusters", "1", "--workers", "1", "--seed0", "17",
                   "--out", str(out)]) == 0

    assert seen and seen[0][1] == [0]
    config = seen[0][0]
    assert config["shortlist"]["alternatives"] == 8
    assert config["shortlist"]["uniform"] is True
    persisted = json.loads((out / "config.json").read_text())
    assert persisted["shortlist"]["alternatives"] == 8
    worker_bot = S.make_side(persisted, "arm", seed=17)
    assert worker_bot.shortlist_config.alternatives == 8
    assert worker_bot.N_DETERMINIZATIONS == 30
    assert worker_bot.REPORT_FOLD_WORLDS == 300


def test_summary_flags_wall_target_without_censoring_completion(monkeypatch):
    captured = {}

    def summarize(records, base, **kwargs):
        captured["records"] = records
        return {"arm": "none",
                "arm_description": "mc-s0-report-lcb on both sides (identity control)",
                "outcome_sentinel": {"utility": 7},
                "work_totals": {
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
    assert result["arm"] == "uniform"
    assert result["outcome_sentinel"] == {"utility": 7}


@pytest.mark.parametrize(
    ("arm", "expected"),
    [
        ("learned", "flat exhaustive learned root shortlist"),
        ("uniform", "flat exhaustive uniform root shortlist"),
        ("identity", "production identity control"),
        ("production", "production at N=30 selection worlds, R=300 report worlds"),
    ],
)
def test_summary_describes_plain_arm_from_config(monkeypatch, arm, expected):
    monkeypatch.setattr(S.duel, "summarize", identity_summary)
    config = cfg(arm)
    result = S.summary_for([{"records": ["sentinel"]}], config)
    assert result["arm"] == arm
    assert result["arm_description"] == expected
    assert result["outcome_sentinel"] == {"utility": 7}
    if arm == "learned":
        assert "identity control" not in result["arm_description"]


def test_summary_describes_scaled_production_from_actual_dose(monkeypatch):
    monkeypatch.setattr(S.duel, "summarize", identity_summary)
    result = S.summary_for([{"records": ["sentinel"]}],
                           cfg("production", production_multiplier=3))
    assert result["arm"] == "production"
    assert result["arm_description"] == \
        "production at N=90 selection worlds, R=900 report worlds"
    assert result["outcome_sentinel"] == {"utility": 7}


@pytest.mark.parametrize("overrides", [
    {"double_shortlist": {"mode": "learned"}},
    {"baseline": "flat-shortlist"},
])
def test_summary_preserves_variant_descriptions(monkeypatch, overrides):
    monkeypatch.setattr(S.duel, "summarize", identity_summary)
    result = S.summary_for([{"records": ["sentinel"]}], cfg("learned", **overrides))
    if "double_shortlist" in overrides:
        assert result["arm_description"] == (
            "exhaustive learned root shortlist; bounded per-world perfect-information "
            "inner shortlist continuation, then terminal heuristic values and root MC-LCB")
        assert result["baseline_description"] == "production"
    else:
        assert result["arm_description"] == "flat exhaustive learned root shortlist"
        assert result["baseline_description"] == "flat-shortlist"
    assert result["outcome_sentinel"] == {"utility": 7}


def test_summary_overwrites_identity_description_from_real_duel_summary():
    result = S.summary_for([{"records": []}], cfg("learned"))
    assert result["arm"] == "learned"
    assert result["arm_description"] == "flat exhaustive learned root shortlist"
