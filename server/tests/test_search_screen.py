"""Real mirrored driver, full cost recording, and retained pair boundaries."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

pytest.importorskip("torch")

from shengji.oracle import screen as duel
from shengji.train import search_screen as S


def config(arm="none"):
    return {"checkpoint": "unused", "allow_legacy": False, "batch_size": 32,
            "arm": arm, "leaf_tricks": 1, "select_worlds": 1,
            "report_worlds": 30, "seed0": 431, "clusters": 1}


class Heads:
    metadata = {"checkpoint_sha256": "test-checkpoint"}

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


@pytest.mark.parametrize("paired,depth", [(False, 1), (True, 1), (False, 3)])
def test_learned_heads_finish_real_mirrored_game_and_count_actual_cost(monkeypatch, tmp_path, paired, depth):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "loaded_heads", lambda *a: Heads())
    cfg = config("both")
    cfg["candidate_select_worlds"] = 2
    cfg["paired_advantage"] = paired
    cfg["leaf_tricks"] = depth
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
            if trace["side"] == "arm":
                assert decision["leaf_tricks"] == depth
                assert decision["ranking_basis"] == (
                    "paired_advantage" if paired else "absolute_value_mean")
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


def test_bounded_pending_failure_publishes_and_drains_running_success(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    cfg = config()
    cfg["clusters"] = 4
    # A real shard lets the final partial summary exercise its normal schema.
    retained_shard = S.run_cluster(cfg, 1)
    started = threading.Event()
    release = threading.Event()
    submitted = []
    holder = []

    def task(_config, cluster):
        if cluster == 0:
            # Ensure the peer is already running before the failure appears.
            assert started.wait(5)
            raise RuntimeError("cluster 0 failed")
        if cluster == 1:
            started.set()
            assert release.wait(5)
            return retained_shard
        raise AssertionError(f"unexpected post-failure submission: {cluster}")

    def executor_factory(n):
        pool = ThreadPoolExecutor(max_workers=n)
        original_submit = pool.submit

        def submit(fn, _config, cluster):
            submitted.append(cluster)
            return original_submit(fn, _config, cluster)

        pool.submit = submit
        return pool

    def runner():
        try:
            S.main(["--checkpoint", "unused", "--out", str(tmp_path),
                    "--arm", "none", "--clusters", "4", "--seed0", "431",
                    "--workers", "2", "--select-worlds", "1",
                    "--report-worlds", "30"])
        except BaseException as exc:
            holder.append(exc)

    real_runner = S._run_pending

    def injected_runner(config_, pending, shards, *, output, workers):
        return real_runner(config_, pending, shards, output=output, workers=workers,
                           executor_factory=executor_factory, task_fn=task)

    monkeypatch.setattr(S, "loaded_heads", lambda *args: Heads())
    monkeypatch.setattr(S, "_run_pending", injected_runner)

    thread = threading.Thread(target=runner)
    thread.start()
    assert started.wait(5)
    failure = tmp_path / "failure.json"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not failure.exists():
        time.sleep(0.01)
    assert failure.exists()
    immediate = json.loads(failure.read_text())
    assert immediate["failed_clusters"] == [0]
    assert immediate["completed_clusters"] == []
    assert submitted == [0, 1]
    assert thread.is_alive()  # running work is being drained, not abandoned

    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert len(holder) == 1 and isinstance(holder[0], RuntimeError)
    final = json.loads(failure.read_text())
    assert final["failed_clusters"] == [0]
    assert final["completed_clusters"] == [1]
    assert (tmp_path / "cluster-00001.json").exists()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["complete"] is False
