import json
from types import SimpleNamespace

import pytest

from shengji.engine.cards import RANKS
from shengji.ai.smart import SmartBot
from shengji.train import cwv_bury_screen as screen


@pytest.mark.parametrize("start_index", [64, 320])
def test_three_arm_driver_preserves_completed_arms_after_failure(tmp_path, monkeypatch, start_index):
    config = {"output": str(tmp_path), "checkpoint": "unused", "checkpoint_sha256": "test",
              "config_sha256": "config", "deals": 1, "start_index": start_index}
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    calls = []
    fail = [True]

    class Control(SmartBot):
        def decide_bury(self, rnd, seat):
            chosen = super().decide_bury(rnd, seat)
            self.last_bury_record = {"elapsed_seconds": 0.0}
            return chosen

    def factory(evaluator, *, seed, arm):
        calls.append((arm, seed))
        if arm == "hybrid" and fail[0]:
            raise RuntimeError("injected third-arm failure")
        return Control()

    monkeypatch.setattr(screen, "make_cwv_bury_bot", factory)
    with pytest.raises(RuntimeError, match="^injected third-arm failure$"):
        screen.run_cluster(config, 0)
    assert {p.name for p in tmp_path.glob("arm-*.json")} == {
        "arm-0000-heuristic.json", "arm-0000-mc.json"}
    saved = {p.name: p.read_bytes() for p in tmp_path.glob("arm-*.json")}
    calls.clear()
    fail[0] = False
    shard = screen.run_cluster(config, 0)
    assert len(calls) == 4 and all(arm == "hybrid" for arm, _ in calls)
    assert all((tmp_path / name).read_bytes() == raw for name, raw in saved.items())
    records = shard["records"]
    assert all(r["state"]["index"] == start_index for r in records)
    assert [seed for _, seed in calls] == [
        screen.derived_seed(f"cwv-bury-gameplay-v1:{start_index}", seat)
        for seat in range(4)]
    assert [r["arm"] for r in records] == list(screen.ARMS)
    assert len({r["attacker_points"] for r in records}) == 1
    assert records[0]["transcript"] == records[1]["transcript"] == records[2]["transcript"]
    result = screen.summarize([shard], config)
    assert result["complete"]
    assert result["comparisons"]["hybrid_minus_mc"]["utility"]["mean"] == 0
    old = json.loads((tmp_path / "arm-0000-mc.json").read_text())
    old["config_sha256"] = "wrong"
    (tmp_path / "arm-0000-mc.json").write_text(json.dumps(old))
    with pytest.raises(ValueError, match="^completed arm binding mismatch$"):
        screen.run_cluster(config, 0)


def test_cli_binds_extension_start_index_before_scheduling(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    monkeypatch.setattr(screen, "execution_source_identity", lambda *_a: {})
    observed = []
    monkeypatch.setattr(screen, "_run_pending", lambda config, pending, *_a, **_k:
                        observed.append((config, pending)))
    screen.main(["--checkpoint", "unused", "--out", str(tmp_path),
                 "--deals", "768", "--start-index", "320", "--workers", "8"])
    config, pending = observed[0]
    assert config["start_index"] == 320
    assert config["deals"] == 768
    assert pending == list(range(768))
    assert json.loads((tmp_path / "config.json").read_text()) == config
    with pytest.raises(SystemExit):
        screen.main(["--checkpoint", "unused", "--out", str(tmp_path), "--start-index", "63"])


def test_gameplay_metric_is_screen_metric_not_half_level_model_support():
    assert [screen.banker_utility(p) for p in (0, 35, 75, 80, 120, 160)] == [3, 2, 1, -1, -1, -2]


def test_scaling_recipes_reach_each_banker_and_preserve_common_play_seeds(tmp_path, monkeypatch):
    config = {"output": str(tmp_path), "checkpoint": "unused", "checkpoint_sha256": "test",
              "config_sha256": "scaling", "deals": 1, "start_index": 1088,
              "arm_recipes": screen.scaling_recipes()}
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    calls = []

    class Control(SmartBot):
        def decide_bury(self, rnd, seat):
            chosen = super().decide_bury(rnd, seat)
            self.last_bury_record = {"elapsed_seconds": 0.001,
                                     "candidates": [chosen], "mc_rollouts": 32}
            return chosen

    def factory(evaluator, *, seed, arm, bury_config):
        calls.append((seed, arm, bury_config))
        return Control()

    monkeypatch.setattr(screen, "make_cwv_bury_bot", factory)
    shard = screen.run_cluster(config, 0)
    assert len(calls) == 24
    assert len(shard["records"]) == 6
    expected = [("mc", 32, 32), ("hybrid", 32, 32),
                ("hybrid", 64, 32), ("hybrid", 32, 128),
                ("hybrid", 64, 128), ("mc", 64, 128)]
    for index, (arm, cap, worlds) in enumerate(expected):
        group = calls[index * 4:(index + 1) * 4]
        assert [seed for seed, _, _ in group] == [seed for seed, _, _ in calls[:4]]
        assert all(a == arm and c.max_candidates == cap and c.selection_worlds == worlds
                   and c.model_worlds == 32 and c.alternatives == 4 for _, a, c in group)
    result = screen.summarize([shard], config)
    assert result["complete"] and result["comparisons_are_exploratory"]
    assert len(result["comparisons"]) == 8
    assert result["comparisons"]["hybrid_pool64_mc128_minus_mc_pool64_mc128"]["utility"]["mean"] == 0
    assert result["cost"]["hybrid_pool64"]["full_bury_rollouts"] == 32
    calls.clear()
    assert screen.run_cluster(config, 0) == shard
    assert calls == []  # completed arms are not replayed


def test_scaling_cli_binds_recipes_and_rejects_used_population(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    monkeypatch.setattr(screen, "execution_source_identity", lambda *_a: {})
    seen = []
    monkeypatch.setattr(screen, "_run_pending", lambda config, pending, *_a, **_k:
                        seen.append((config, pending)))
    args = ["--checkpoint", "unused", "--out", str(tmp_path), "--scaling",
            "--deals", "512", "--start-index", "1088"]
    screen.main(args)
    config, pending = seen[0]
    assert pending == list(range(512))
    assert config["arm_recipes"] == screen.scaling_recipes()
    assert json.loads((tmp_path / "config.json").read_text())["arm_recipes"] == screen.scaling_recipes()
    with pytest.raises(SystemExit):
        screen.main(args[:-1] + ["320"])


def test_allrank_cli_binds_fresh_population_defaults_and_rejects_scaling(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    monkeypatch.setattr(screen, "execution_source_identity", lambda *_a: {})
    observed = []
    monkeypatch.setattr(screen, "_run_pending", lambda config, pending, *_a, **_k:
                        observed.append((config, pending)))
    screen.main(["--checkpoint", "unused", "--out", str(tmp_path),
                 "--population", screen.ALLRANK_POPULATION])
    config, pending = observed[0]
    assert config["deals"] == 1040 and config["start_index"] == 0
    assert config["population"] == screen.ALLRANK_POPULATION
    assert config["namespace"] == screen.ALLRANK_NAMESPACE
    assert config["schedule"] == {"ranks": RANKS, "bankers": 4,
                                   "deals_per_rank_banker": 20}
    assert pending == list(range(1040))
    assert json.loads((tmp_path / "config.json").read_text()) == config
    for extra in (["--deals", "51"], ["--start-index", "1"], ["--scaling"]):
        with pytest.raises(SystemExit):
            screen.main(["--checkpoint", "unused", "--out", str(tmp_path),
                         "--population", screen.ALLRANK_POPULATION] + extra)


def test_allrank_driver_uses_real_capture_and_fresh_common_play_seed(tmp_path, monkeypatch):
    config = {"output": str(tmp_path), "checkpoint": "unused",
              "checkpoint_sha256": "test", "config_sha256": "allrank",
              "deals": 1, "start_index": 52,
              "population": screen.ALLRANK_POPULATION,
              "namespace": screen.ALLRANK_NAMESPACE}
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    calls = []

    class Control(SmartBot):
        def decide_bury(self, rnd, seat):
            chosen = super().decide_bury(rnd, seat)
            self.last_bury_record = {"elapsed_seconds": 0.0,
                                     "candidates": [chosen]}
            return chosen

    def factory(evaluator, *, seed, arm):
        calls.append((arm, seed))
        return Control()

    monkeypatch.setattr(screen, "make_cwv_bury_bot", factory)
    shard = screen.run_cluster(config, 17)
    state = shard["records"][0]["state"]
    assert state["index"] == 69 and state["population"] == screen.ALLRANK_POPULATION
    assert state["setup"]["trump_rank"] == "6" and state["initial_banker"] == 1
    assert [seed for _, seed in calls[:4]] == [
        screen.derived_seed(f"{screen.ALLRANK_NAMESPACE}:play:69", seat)
        for seat in range(4)]
    assert len(calls) == 12
    assert calls[4:8] == [("mc", seed) for _, seed in calls[:4]]
    assert calls[8:12] == [("hybrid", seed) for _, seed in calls[:4]]
    assert [r["transcript"] for r in shard["records"]].count(shard["records"][0]["transcript"]) == 3


def test_allrank_saved_arm_failure_recovery_does_not_replay_completed(tmp_path, monkeypatch):
    config = {"output": str(tmp_path), "checkpoint": "unused",
              "checkpoint_sha256": "test", "config_sha256": "allrank",
              "deals": 1, "start_index": 0,
              "population": screen.ALLRANK_POPULATION,
              "namespace": screen.ALLRANK_NAMESPACE}
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    calls, fail = [], [True]

    class Control(SmartBot):
        def decide_bury(self, rnd, seat):
            chosen = super().decide_bury(rnd, seat)
            self.last_bury_record = {"elapsed_seconds": 0.0}
            return chosen

    def factory(evaluator, *, seed, arm):
        calls.append((arm, seed))
        if arm == "hybrid" and fail[0]:
            raise RuntimeError("injected allrank failure")
        return Control()

    monkeypatch.setattr(screen, "make_cwv_bury_bot", factory)
    with pytest.raises(RuntimeError, match="^injected allrank failure$"):
        screen.run_cluster(config, 0)
    saved = {path.name: path.read_bytes() for path in tmp_path.glob("arm-*.json")}
    assert set(saved) == {"arm-0000-heuristic.json", "arm-0000-mc.json"}
    calls.clear()
    fail[0] = False
    shard = screen.run_cluster(config, 0)
    assert [arm for arm, _ in calls] == ["hybrid"] * 4
    assert [seed for _, seed in calls] == [
        screen.derived_seed(f"{screen.ALLRANK_NAMESPACE}:play:0", seat)
        for seat in range(4)]
    assert all((tmp_path / name).read_bytes() == raw for name, raw in saved.items())
    assert len(shard["records"]) == 3


def _stratum_shard(cluster, rank, banker, values):
    records = []
    for arm, value in zip(screen.ARMS, values):
        records.append({"arm": arm, "state": {"setup": {"trump_rank": rank},
                         "initial_banker": banker}})
    return {"cluster": cluster, "records": records}


def test_allrank_stratified_bootstrap_is_balanced_deterministic_and_order_free():
    constant = [_stratum_shard(i, "2", i // 2, (3, 3, 3)) for i in range(4)]
    zero = screen.stratified_interval([0, 0, 0, 0], constant)
    assert zero["ci95"] == [0.0, 0.0] and zero["n_independent_states"] == 4
    varying = screen.stratified_interval([0, 1, 2, 3], constant)
    assert varying["ci95"][0] < varying["ci95"][1]
    reversed_result = screen.stratified_interval([3, 2, 1, 0], list(reversed(constant)))
    assert reversed_result == varying


def test_allrank_summary_reports_population_and_paired_diagnostics():
    shards = []
    incumbent = ["S2", "S3", "S4", "S6", "S7", "S8", "S9", "SJ"]
    alternative = ["H5", "HK", "H4", "H6", "H7", "H8", "H9", "HJ"]
    for cluster in range(52):
        rank, banker = RANKS[cluster % 13], cluster // 13
        records = []
        for arm, bury in zip(screen.ARMS, (incumbent, list(reversed(incumbent)), alternative)):
            records.append({"arm": arm, "state": {"setup": {
                             "trump_rank": rank, "trump_suit": "S",
                             "trump_is_nt": False}, "initial_banker": banker},
                            "buried": bury, "attacker_points": 120 if arm == "mc" and cluster == 0 else 40,
                            "banker_won": 1, "banker_utility": 1,
                            "kitty_bonus": 80 if arm == "mc" and cluster == 0 else 0,
                            "transcript": ([{"seat": 0}] if arm == "mc" else
                                           [{"seat": 1}] if arm == "hybrid" else []),
                            "wall_seconds": 1.0, "cpu_seconds": 1.0,
                            "bury": {"elapsed_seconds": 1.0,
                                      "candidates": [bury]}})
        shards.append({"cluster": cluster, "records": records})
    result = screen.summarize(shards, {"deals": 52, "population": screen.ALLRANK_POPULATION})
    assert result["claim"].startswith("exploratory all-rank known-banker")
    assert sum(result["rank_counts"].values()) == 52
    assert result["trump_suit_counts"] == {"S": 52}
    contrast = result["comparisons"]["mc_minus_heuristic"]
    assert contrast["same_bury_count"] == 52
    assert contrast["different_bury_deals"] == 0
    assert contrast["same_bury_transcript_mismatch_count"] == 52
    assert contrast["same_bury_outcome_mismatch_count"] == 1
    assert contrast["buried_points_delta"]["mean"] == 0
    assert contrast["kitty_ge80_difference"]["mean"] == pytest.approx(1 / 52)
    hybrid = result["comparisons"]["hybrid_minus_heuristic"]
    assert hybrid["same_bury_count"] == 0
    assert hybrid["same_bury_transcript_mismatch_count"] == 0
    assert hybrid["buried_points_delta"]["mean"] == 15
    assert result["cost"]["hybrid"]["max_candidate_count"] == 1
    assert result["cost"]["hybrid"]["bury_latency_p95_seconds"] == 1.0
    assert result["cost"]["mc"]["kitty_nonzero_count"] == 1
    assert result["cost"]["mc"]["kitty_ge80_count"] == 1
    assert result["cost"]["mc"]["kitty_bonus_max"] == 80
