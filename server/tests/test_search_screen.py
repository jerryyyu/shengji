"""Real mirrored driver, full cost recording, and retained pair boundaries."""
import copy

import pytest

pytest.importorskip("torch")

from shengji.oracle import screen as duel
from shengji.train import search_screen as S


def config(arm="none"):
    return {"checkpoint": "unused", "allow_legacy": False, "batch_size": 32,
            "arm": arm, "leaf_tricks": 1, "select_worlds": 1,
            "report_worlds": 30, "seed0": 431, "clusters": 1}


class Heads:
    def priors(self, rnd, seat, actions):
        return [1 / len(actions)] * len(actions)

    def values(self, states):
        return [1.0] * len(states)


def test_injected_identity_driver_reproduces_existing_paired_harness(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    cfg = config()
    shard = S.run_cluster(cfg, 0)
    base = duel.build_config(arm="none", select_worlds=1, report_worlds=30)
    for mirror, actual in enumerate(shard["records"]):
        expected, _ = duel.play_screen_round(base, 0, cfg["seed0"], mirror)
        # New counters include the complete decision, including enumeration.
        for side in ("arm", "baseline"):
            assert actual["work"][side]["decision_cpu_seconds"] > 0
            actual["work"][side] = {k: actual["work"][side][k]
                                    for k in expected["work"][side]}
        assert actual == expected


def test_learned_heads_finish_real_mirrored_game_and_count_actual_cost(monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "loaded_heads", lambda *a: Heads())
    cfg = config("both")
    cfg["candidate_select_worlds"] = 2
    shard = S.run_cluster(cfg, 0)
    assert [r["mirror"] for r in shard["records"]] == [0, 1]
    for row in shard["records"]:
        assert row["plays"] > 20 and row["arm"] == "both"
        work = row["work"]["arm"]
        assert work["learned_value_evaluations"] > 0
        assert work["learned_legal_actions"] > work["learned_production_actions"]
        assert work["learned_full_rollout_calls"] == work["total_rollouts"] > 0
        assert work["decision_cpu_seconds"] > 0
        assert work["decision_wall_seconds"] >= work["learned_inference_secs"] > 0
    for trace in shard["decision_traces"]:
        assert trace["decisions"]
        for decision in trace["decisions"]:
            assert decision["selection_N"] == (2 if trace["side"] == "arm" else 1)
            assert decision["report_worlds"] == 30
            assert decision["report"]["worlds"] == 30
    path = tmp_path / "cluster-00000.json"
    S._publish(path, shard)
    assert S.reopen_shard(path, cfg, 0) == shard
    # Different seed or rank is not the same completed pair.
    with pytest.raises(ValueError, match="^completed shard does not contain its exact mirrored pair$"):
        S.reopen_shard(path, dict(cfg, seed0=cfg["seed0"] + 1), 0)
    summary = S.summary_for([shard], cfg)
    assert summary["complete"]
    assert not summary["equal_work_strength_claim"]
    assert summary["arm_over_baseline_decision_cpu"] > 0
    costly = copy.deepcopy(shard)
    for row in costly["records"]:
        row["work"]["arm"]["decision_cpu_seconds"] = 10
        row["work"]["baseline"]["decision_cpu_seconds"] = 1
    assert not S.summary_for([costly], cfg)["no_more_measured_decision_cpu"]


def test_publish_survives_stale_temporary_file_and_replaces_only_target(tmp_path):
    path = tmp_path / "summary.json"
    stale = tmp_path / "summary.json.tmp"
    stale.write_text("interrupted")
    S._publish(path, {"done": 1})
    S._publish(path, {"done": 2})
    assert '"done": 2' in path.read_text()
    assert stale.read_text() == "interrupted"


def test_changed_transitive_game_dependency_refuses_resuming_old_pairs(tmp_path):
    package = tmp_path / "package"
    (package / "engine").mkdir(parents=True)
    dependency = package / "engine/game.py"
    dependency.write_text("payoff = 1\n")
    output = tmp_path / "out"
    old = dict(config(), source_sha256=S.execution_source_identity(package))
    S.bind_output_config(output, old)
    S.bind_output_config(output, old)  # identical recovery is allowed
    dependency.write_text("payoff = 2\n")
    changed = dict(config(), source_sha256=S.execution_source_identity(package))
    with pytest.raises(ValueError, match="^existing output belongs to a different configuration$"):
        S.bind_output_config(output, changed)
    S.bind_output_config(output, old)  # original config was not overwritten
