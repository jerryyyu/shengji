"""Witness real paired gameplay and the counters published by the new arm."""
import copy
from dataclasses import asdict

import pytest

pytest.importorskip("torch")

from shengji.train import world_shortlist_screen as S
from shengji.train.world_shortlist import WorldShortlistConfig


class Heads:
    metadata = {"checkpoint_sha256": "test-checkpoint"}

    def values(self, states):
        return [0.0] * len(states)


def config(arm="hybrid"):
    return {
        "arm": arm, "checkpoint": "unused", "checkpoint_sha256": "test-checkpoint",
        "allow_legacy": False,
        "hybrid": asdict(WorldShortlistConfig(
            cheap_worlds=3, refine_worlds=2, shortlist_size=3, batch_size=16)),
        "baseline_worlds": 1, "control_worlds": 2, "report_worlds": 30,
        "trump_ranks": ["2"], "seed0": 431, "clusters": 1,
    }


def test_worker_refuses_changed_checkpoint_before_building_policy(monkeypatch):
    monkeypatch.setattr(S, "loaded_heads", lambda *args: Heads())
    with pytest.raises(ValueError, match="^checkpoint changed between configuration and worker$"):
        S.make_side(dict(config(), checkpoint_sha256="changed"), "arm", 1)


def test_controls_leave_baseline_dose_and_registry_unchanged():
    from shengji.ai.registry import REGISTRY
    before = dict(REGISTRY)
    for arm, expected in (("none", 1), ("work", 2)):
        cfg = config(arm)
        assert S.make_side(cfg, "baseline", 1).N_DETERMINIZATIONS == 1
        assert S.make_side(cfg, "arm", 1).N_DETERMINIZATIONS == expected
        assert S.make_side(cfg, "arm", 1).REPORT_RULE == "lcb"
    assert REGISTRY == before


def test_real_mirrored_pair_reports_full_and_cheap_work_separately(monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "loaded_heads", lambda *args: Heads())
    cfg = config()
    shard = S.run_cluster(cfg, 0)
    assert [r["mirror"] for r in shard["records"]] == [0, 1]
    for row in shard["records"]:
        assert row["plays"] > 20 and row["arm"] == "hybrid"
        arm = row["work"]["arm"]
        assert arm["hybrid_cheap_evaluations"] > arm["hybrid_cheap_worlds"] > 0
        assert arm["hybrid_model_rows"] > arm["hybrid_model_batches"] > 0
        assert arm["hybrid_refine_full_rollouts"] > 0
        assert arm["hybrid_report_full_rollouts"] > 0
        assert arm["total_rollouts"] == (
            arm["hybrid_refine_full_rollouts"] + arm["hybrid_report_full_rollouts"])
        assert arm["candidate_evaluations"] == (
            arm["total_rollouts"] + arm["hybrid_cheap_evaluations"])
        assert arm["accepted_worlds"] == (
            arm["hybrid_cheap_worlds"] + arm["hybrid_refine_worlds"]
            + arm["hybrid_report_full_rollouts"] // 2)
        assert arm["decision_cpu_seconds"] > 0
        assert row["work"]["baseline"]["total_rollouts"] > 0
    arm_decisions = [d for t in shard["decision_traces"] if t["side"] == "arm"
                     for d in t["decisions"]]
    assert arm_decisions
    for decision in arm_decisions:
        hybrid = decision["world_shortlist"]
        assert hybrid is not None
        assert len(hybrid["candidates"]) == len(hybrid["cheap_means"])
        assert hybrid["candidates"][0] == decision["incumbent"]
        assert 0 in hybrid["shortlist_indices"]
        chosen = hybrid["report_candidate_index"]
        assert chosen in hybrid["shortlist_indices"]
        assert hybrid["candidates"][chosen] == decision["challenger"]
        for index, (mean, count) in enumerate(zip(
                hybrid["refinement_means"], hybrid["refinement_counts"])):
            if index in hybrid["shortlist_indices"]:
                assert mean is not None and count == 2
            else:
                assert mean is None and count == 0
        assert decision["report"]["rule"] == "lcb"
        assert decision["report"]["complete"]
        assert decision["report"]["worlds"] == 30
    path = tmp_path / "cluster-00000.json"
    S._publish(path, shard)
    assert S.reopen_shard(path, cfg, 0) == shard
    changed = copy.deepcopy(cfg)
    changed["hybrid"]["cheap_worlds"] += 1
    with pytest.raises(ValueError, match="^completed shard does not match its mirrored pair and recipe$"):
        S.reopen_shard(path, changed, 0)
    for mutation in (dict(cfg, seed0=432), dict(cfg, trump_ranks=["3"]),
                     dict(cfg, checkpoint_sha256="another-checkpoint")):
        with pytest.raises(ValueError, match="^completed shard does not match its mirrored pair and recipe$"):
            S.reopen_shard(path, mutation, 0)
    result = S.summary_for([shard], cfg)
    assert result["complete"]
    assert not result["equal_work_strength_claim"]
    assert result["arm_over_baseline_decision_cpu"] > 0
    assert result["arm_over_baseline_sampled_worlds"] > 0


def test_summary_counts_do_not_turn_a_cost_overrun_into_equal_work(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    # Summary consumes actual per-side timings, not requested world budgets.
    from shengji.oracle import screen as duel
    captured = {}

    def summarize(records, *args, **kwargs):
        captured["records"] = records
        return {"work_totals": {
            "arm": {"decision_cpu_seconds": 10, "accepted_worlds": 100},
            "baseline": {"decision_cpu_seconds": 1, "accepted_worlds": 10}}}

    monkeypatch.setattr(duel, "summarize", summarize)
    result = S.summary_for([{"records": ["sentinel"]}], config())
    assert captured["records"] == ["sentinel"]
    assert result["arm_over_baseline_decision_cpu"] == 10
    assert result["arm_over_baseline_sampled_worlds"] == 10
    assert result["equal_work_strength_claim"] is False
