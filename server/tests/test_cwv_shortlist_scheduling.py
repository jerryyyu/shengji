"""Execution-only ordering from prior shortlist screen shard timings."""
import json
import math

import pytest

from shengji.train import cwv_shortlist_screen as S


def prior_shard(cluster, seed, walls, *, rank="2"):
    return {
        "schema": "cwv-shortlist-shard-v1", "cluster": cluster,
        "seed": seed, "rank": rank,
        "timings": [
            {"cluster": cluster, "seed": seed, "mirror": mirror,
             "wall_secs": wall}
            for mirror, wall in enumerate(walls)
        ],
    }


def completed_shard(config, cluster, seed):
    return {
        "schema": "cwv-shortlist-shard-v1", "cluster": cluster,
        "seed": seed, "rank": "2", "recipe": S._recipe(config),
        "records": [
            {"cluster": cluster, "seed": seed, "mirror": mirror,
             "trump_rank": "2", "arm": "uniform"}
            for mirror in (0, 1)
        ],
    }


def test_cli_cost_order_is_longest_first_and_resume_skips_completed(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    prior = tmp_path / "prior"
    prior.mkdir()
    for cluster, walls in ((0, (5.0, 1.0)), (1, (2.0, 2.0)), (2, (10.0, 1.0))):
        (prior / f"cluster-{cluster:05}.json").write_text(
            json.dumps(prior_shard(cluster, 17 + cluster, walls)))

    calls = []

    def no_work(config, pending, shards, **kwargs):
        calls.append((config, list(pending), list(shards)))

    monkeypatch.setattr(S, "_run_pending", no_work)
    monkeypatch.setattr(S, "summary_for", lambda shards, config: {})
    args = ["--arm", "uniform", "--clusters", "3", "--workers", "1",
            "--seed0", "17", "--out", str(tmp_path / "out"),
            "--cost-order-from", str(prior)]
    assert S.main(args) == 0
    assert calls[0][1] == [2, 0, 1]
    assert calls[0][0]["execution_order"]["clusters"] == [2, 0, 1]
    assert len(calls[0][1]) == len(set(calls[0][1])) == 3

    config = calls[0][0]
    assert S._recipe(config) == S._recipe({
        key: value for key, value in config.items() if key != "execution_order"})
    out = tmp_path / "out"
    (out / "cluster-00001.json").write_text(
        json.dumps(completed_shard(config, 1, 18)))
    assert S.main(args) == 0
    assert calls[1][1] == [2, 0]
    assert calls[1][1] + [1] == [2, 0, 1]

    default_calls = []
    monkeypatch.setattr(S, "_run_pending",
                        lambda config, pending, shards, **kwargs:
                        default_calls.append((config, list(pending))))
    assert S.main(["--arm", "uniform", "--clusters", "3", "--workers", "1",
                   "--seed0", "17", "--out", str(tmp_path / "default")]) == 0
    assert default_calls[0][1] == [0, 1, 2]
    assert "execution_order" not in default_calls[0][0]


@pytest.mark.parametrize("mutation", [
    lambda shard: shard.update(seed=999),
    lambda shard: shard["timings"][0].update(wall_secs=math.inf),
])
def test_cli_cost_order_refuses_drift_or_nonfinite_timing(tmp_path, monkeypatch, mutation):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    prior = tmp_path / "prior"
    prior.mkdir()
    shard = prior_shard(0, 17, (1.0, 2.0))
    mutation(shard)
    (prior / "cluster-00000.json").write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="cost-order"):
        S._cost_order(prior, range(1), 17)


def test_cli_cost_order_refuses_missing_cluster(tmp_path):
    with pytest.raises(ValueError, match="artifact missing cluster 0"):
        S._cost_order(tmp_path / "missing", range(1), 17)
