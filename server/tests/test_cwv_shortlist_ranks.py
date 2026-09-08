"""Rank-cycle wiring and actual trump-suit coverage for the shortlist screen."""
import copy
import json
import random

import pytest

from shengji.engine.cards import RANKS
from shengji.train import cwv_shortlist_screen as S


def cfg(**overrides):
    value = {
        "schema": "cwv-shortlist-config-v1", "arm": "uniform",
        "checkpoint": None, "checkpoint_sha256": None,
        "shortlist": {"worlds": 1, "selection_worlds": 30,
                       "alternatives": 4, "batch_size": 128, "uniform": True},
        "report_worlds": 300, "production_multiplier": 1,
        "target_wall_multiplier": 1, "seed0": 17, "clusters": 2,
    }
    value.update(overrides)
    return value


def cli_args(out, *extra):
    return ["--arm", "uniform", "--clusters", "1", "--workers", "1",
            "--seed0", "17", "--out", str(out), *extra]


@pytest.mark.parametrize("text", ["2,2", "bogus"])
def test_cli_rejects_duplicate_or_unknown_trump_rank(tmp_path, monkeypatch, text):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "_run_pending", lambda *args, **kwargs: None)
    with pytest.raises(SystemExit):
        S.main(cli_args(tmp_path / "out", "--trump-ranks", text))


def test_cli_rank_cycle_uses_real_game_factory_for_both_mirrors(tmp_path, monkeypatch):
    calls = []

    def fake_play(base, cluster, seed, mirror, *, bot_factory, counter_fn, game_factory):
        game = game_factory(random.Random(seed + mirror))
        game.start_round()
        if mirror == 0:
            game.round.trump_suit = "S"
        else:
            game.round.trump_is_nt = True
        calls.append((cluster, mirror, game.level_idx[:], game.round.trump_rank))
        return ({"trump_rank": game.round.trump_rank}, {"wall_secs": 0.0})

    monkeypatch.setattr(S.duel, "play_screen_round", fake_play)
    captured = []

    def run_pending(config, pending, shards, **kwargs):
        captured.append((config, [kwargs["task_fn"](config, cluster)
                                  for cluster in pending]))

    monkeypatch.setattr(S, "_run_pending", run_pending)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    assert S.main(["--arm", "uniform", "--clusters", "2", "--workers", "1",
                   "--seed0", "17", "--out", str(tmp_path / "out"),
                   "--trump-ranks", "2,A"]) == 0
    config, shards = captured[0]
    assert config["trump_ranks"] == ["2", "A"]
    assert [(cluster, mirror, levels, rank) for cluster, mirror, levels, rank in calls] == [
        (0, 0, [RANKS.index("2"), RANKS.index("2")], "2"),
        (0, 1, [RANKS.index("2"), RANKS.index("2")], "2"),
        (1, 0, [RANKS.index("A"), RANKS.index("A")], "A"),
        (1, 1, [RANKS.index("A"), RANKS.index("A")], "A"),
    ]
    assert [shard["rank"] for shard in shards] == ["2", "A"]
    assert [[row["trump_rank"] for row in shard["records"]]
            for shard in shards] == [["2", "2"], ["A", "A"]]
    assert [[row["trump_suit"] for row in shard["records"]]
            for shard in shards] == [["S", "NT"], ["S", "NT"]]
    assert all(shard["recipe"]["trump_ranks"] == ["2", "A"] for shard in shards)


def test_reopen_refuses_wrong_rank_and_cycle_drift(tmp_path):
    config = cfg(trump_ranks=["2", "A"])
    shard = {
        "schema": "cwv-shortlist-shard-v1", "cluster": 1, "seed": 18,
        "rank": "2", "recipe": S._recipe(config),
        "records": [{"cluster": 1, "seed": 18, "mirror": mirror,
                      "trump_rank": "A", "trump_suit": "S",
                      "arm": "uniform"}
                     for mirror in (0, 1)],
    }
    path = tmp_path / "cluster-00001.json"
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, config, 1)

    shard["rank"] = "A"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 1) == shard
    shard["records"][0]["trump_rank"] = "2"
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, config, 1)
    shard["records"][0]["trump_rank"] = "A"
    shard["records"][0]["trump_suit"] = "bogus"
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, config, 1)
    shard["records"][0]["trump_suit"] = "S"
    path.write_text(json.dumps(shard))
    changed = copy.deepcopy(config)
    changed["trump_ranks"] = ["2", "K"]
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, changed, 1)


def test_summary_reports_rank_and_actual_suit_coverage_separately(monkeypatch):
    monkeypatch.setattr(S.duel, "summarize", lambda *args, **kwargs: {
        "work_totals": {"arm": {}, "baseline": {}},
    })
    config = cfg(trump_ranks=["2", "A"])
    shards = [{"cluster": 0, "records": [
        {"trump_rank": "2", "trump_suit": "S"},
        {"trump_rank": "2", "trump_suit": "NT"},
    ]}, {"cluster": 1, "records": [
        {"trump_rank": "A", "trump_suit": "S"},
        {"trump_rank": "A", "trump_suit": "NT"},
    ]}]
    result = S.summary_for(shards, config)
    assert result["rank"] is None
    assert result["coverage"]["by_rank"] == {"2": 2, "A": 2}
    assert result["coverage"]["by_trump_suit"] == {
        "S": 2, "H": 0, "D": 0, "C": 0, "NT": 2}
    assert result["coverage"]["by_rank"] != result["coverage"]["by_trump_suit"]
    single = cfg(trump_ranks=["A"])
    single_result = S.summary_for([{"cluster": 0, "records": [
        {"trump_rank": "A", "trump_suit": "S"},
        {"trump_rank": "A", "trump_suit": "NT"},
    ]}], single)
    assert single_result["rank"] == "A"
    assert S._recipe(single)["rank"] == "A"


def test_omitted_rank_cycle_keeps_legacy_rank2_receipt_shape():
    config = cfg()
    assert S.rank_for(config, 0) == "2"
    assert S.rank_for(config, 99) == "2"
    assert "trump_ranks" not in S._recipe(config)


def test_cost_order_accepts_and_validates_the_rank_cycle(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    for cluster, rank in ((0, "2"), (1, "A")):
        (prior / f"cluster-{cluster:05}.json").write_text(json.dumps({
            "schema": "cwv-shortlist-shard-v1", "cluster": cluster,
            "seed": 17 + cluster, "rank": rank,
            "timings": [{"cluster": cluster, "seed": 17 + cluster,
                          "mirror": mirror, "wall_secs": wall}
                         for mirror, wall in enumerate((1.0, 2.0 + cluster))],
        }))
    ordered = S._cost_order(prior, range(2), 17, trump_ranks=["2", "A"])
    assert ordered["clusters"] == [1, 0]
    bad = json.loads((prior / "cluster-00001.json").read_text())
    bad["rank"] = "2"
    (prior / "cluster-00001.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="cost-order artifact drift"):
        S._cost_order(prior, range(2), 17, trump_ranks=["2", "A"])
