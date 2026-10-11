"""``round_kind: fixed_banker`` for the served-bot shortlist screen.

Every screen before the option dealt FIRST rounds (banker unknown, the first
declarer takes the bank and the kitty).  The option deals LATER rounds, as
``Game.start_round`` does once a banker exists: the banker seat is fixed
(``cluster % 4``), the cluster's rank is the banker team's level, and a
declaration only names the trump suit.  The default must stay byte-identical:
the key is absent from config and recipe, and the rounds are the legacy ones.
"""
import json
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.cards import RANKS
from shengji.engine.game import Game
from shengji.engine.round import Round
from shengji.train import cwv_screen_queue as Q
from shengji.train import cwv_shortlist_screen as S
from shengji.train import leaf_screen


def cfg(**overrides):
    """A cheap served-bot screen: heuristic arm vs SmartBot (no search)."""
    value = {
        "schema": "cwv-shortlist-config-v1", "arm": "policy", "arm_policy": "heuristic",
        "arm_policy_identity": S._policy_identity(make_bot("heuristic", seed=0)),
        "base_policy": "smart", "checkpoint_sha256": None,
        "shortlist": {"worlds": 1, "selection_worlds": 30, "alternatives": 4,
                      "batch_size": 128, "uniform": False},
        "report_worlds": 300, "production_multiplier": 1, "target_wall_multiplier": 1,
        "seed0": 17, "clusters": 8, "trump_ranks": ["2", "7", "A"],
    }
    value.update(overrides)
    return value


FIXED = {"round_kind": "fixed_banker"}


def deterministic(obj):
    """A shard without its clocks (wall/CPU vary run to run)."""
    if isinstance(obj, dict):
        return {k: deterministic(v) for k, v in obj.items()
                if not any(t in k for t in ("secs", "seconds", "wall", "cpu"))}
    if isinstance(obj, list):
        return [deterministic(v) for v in obj]
    return obj


def legacy_game_factory_for(rank):
    """``leaf_screen._game_factory_for`` exactly as it was before the option."""
    def game_factory(rng):
        game = Game(rng)
        game.level_idx = [RANKS.index(rank), RANKS.index(rank)]

        def start():
            game.round = Round(rank, None, game.rng)
            game.round_no += 1
            return game.round
        game.start_round = start
        return game
    return game_factory


@pytest.fixture(autouse=True)
def require_voids(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")


# ------------------------------------------------------------ default identity

def test_default_rounds_are_the_legacy_first_rounds(monkeypatch):
    config = cfg()
    current = [deterministic(S.run_cluster(config, c)) for c in range(3)]
    monkeypatch.setattr(S, "_game_factory_for", legacy_game_factory_for)
    legacy = [deterministic(S.run_cluster(config, c)) for c in range(3)]
    assert json.dumps(current, sort_keys=True) == json.dumps(legacy, sort_keys=True)
    # first rounds: the banker is whoever won the declaration
    assert all("round_kind" not in shard["recipe"] for shard in current)


def test_absent_round_kind_leaves_config_and_recipe_unchanged(tmp_path, monkeypatch):
    configs = []

    def run_pending(config, pending, shards, **kwargs):
        configs.append(config)

    monkeypatch.setattr(S, "_run_pending", run_pending)
    base = ["--arm", "uniform", "--clusters", "1", "--workers", "1", "--seed0", "17",
            "--trump-ranks", "2,A"]
    assert S.main([*base, "--out", str(tmp_path / "a")]) == 0
    assert S.main([*base, "--out", str(tmp_path / "b"), "--round-kind", "first"]) == 0
    assert S.main([*base, "--out", str(tmp_path / "c"), "--round-kind", "fixed_banker"]) == 0
    first, explicit, fixed = configs
    assert "round_kind" not in first and "round_kind" not in explicit
    assert "round_kind" not in S._recipe(first)
    assert S._recipe(first) == S._recipe(explicit)
    assert fixed["round_kind"] == "fixed_banker"
    assert S._recipe(fixed) == {**S._recipe(first), "round_kind": "fixed_banker"}
    assert S.banker_for(first, 5) is None
    # "first" is spelled only by absence: one behaviour, one identity
    with pytest.raises(ValueError, match="round_kind"):
        S.banker_for({"round_kind": "first"}, 0)


def test_queue_forwards_round_kind_only_when_not_default(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(Q.screen, "main", lambda command: commands.append(command) or 0)
    common = ["--arm-policy", "heuristic", "--name", "w", "--seeds", "100",
              "--clusters", "2", "--workers", "1"]
    assert Q.main([*common, "--out", str(tmp_path / "q1")]) == 0
    assert Q.main([*common, "--out", str(tmp_path / "q2"), "--round-kind", "fixed_banker"]) == 0
    assert "--round-kind" not in commands[0]
    assert commands[1][commands[1].index("--round-kind") + 1] == "fixed_banker"


# ------------------------------------------------------------ fixed-banker rounds

def test_fixed_banker_round_is_what_game_start_round_deals():
    for banker in range(4):
        for rank in ("2", "7", "A"):
            screen_game = leaf_screen._game_factory_for(rank, banker)(random.Random(5))
            ours = screen_game.start_round()
            game = Game(random.Random(5))
            game.banker = banker
            game.level_idx[banker % 2] = RANKS.index(rank)
            real = game.start_round()
            assert (ours.banker, ours.trump_rank, ours.first_round) == (banker, rank, False)
            assert (real.banker, real.trump_rank, real.first_round) == (banker, rank, False)
            assert ours.deck == real.deck and ours.kitty == real.kitty
    with pytest.raises(ValueError, match="seat"):
        leaf_screen._game_factory_for("2", 4)


def test_fixed_banker_declare_window_kitty_and_records(monkeypatch):
    config = cfg(**FIXED)
    seen = []
    real_factory = leaf_screen._game_factory_for

    def spying_factory(rank, banker=None):
        assert banker is not None
        make = real_factory(rank, banker)

        def game_factory(rng):
            game = make(rng)
            start = game.start_round

            def spied_start():
                rnd = start()
                info = {"banker": banker, "rank": rank, "declarers": []}
                seen.append(info)
                declare, finalize = rnd.declare, rnd.finalize_declare

                def spied_declare(seat, cards):
                    declare(seat, cards)
                    info["declarers"].append(seat)
                    assert rnd.banker == banker            # declaring never moves the bank

                def spied_finalize():
                    kitty = list(rnd.kitty)
                    before = [list(h) for h in rnd.hands]
                    finalize()
                    assert rnd.banker == banker
                    assert rnd.hands[banker] == before[banker] + kitty
                    assert all(rnd.hands[s] == before[s] for s in range(4) if s != banker)
                    assert rnd.turn == banker and rnd.phase == "bury"
                rnd.declare, rnd.finalize_declare = spied_declare, spied_finalize
                return rnd
            game.start_round = spied_start
            return game
        return game_factory

    monkeypatch.setattr(S, "_game_factory_for", spying_factory)
    shards = [S.run_cluster(config, c) for c in range(8)]
    assert len(seen) == 16
    for shard in shards:
        cluster = shard["cluster"]
        rank = S.rank_for(config, cluster)
        assert shard["recipe"]["round_kind"] == "fixed_banker"
        records = shard["records"]
        assert [r["banker"] for r in records] == [cluster % 4] * 2
        assert [r["trump_rank"] for r in records] == [rank] * 2
        assert sorted(r["arm_role"] for r in records) == ["attacker", "banker"]
        for r in records:
            assert r["arm_role"] == ("banker" if r["banker"] % 2 == r["arm_team"] else "attacker")
            assert r["winner_team"] in (0, 1) and r["plays"] > 0
            assert r["trump_suit"] in ("S", "H", "D", "C", "NT")
    # anyone may declare: some trump suit was named by the defending team
    assert any(seat % 2 != info["banker"] % 2 for info in seen for seat in info["declarers"])


def test_arm_banker_share_is_exactly_half_over_any_four_clusters():
    config = cfg(**FIXED)
    for start in range(12):
        clusters = range(start, start + 4)
        roles = [S.banker_for(config, c) % 2 == (0 if mirror == 0 else 1)
                 for c in clusters for mirror in (0, 1)]
        assert sum(roles) == 4 and len(roles) == 8
        # and every seat (so each side's two seat-bots) holds the bank once
        assert sorted(S.banker_for(config, c) for c in clusters) == [0, 1, 2, 3]


def test_reopen_refuses_a_shard_with_the_wrong_banker(tmp_path):
    config = cfg(**FIXED)
    shard = S.run_cluster(config, 2)
    path = tmp_path / "cluster-00002.json"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 2)["records"] == json.loads(json.dumps(shard["records"]))
    shard["records"][1]["banker"] = 3
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, config, 2)
    shard["records"][1]["banker"] = 2
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="completed shard"):   # first-round config: other recipe
        S.reopen_shard(path, cfg(), 2)


def test_summary_reports_arm_role_coverage(monkeypatch):
    monkeypatch.setattr(S.duel, "summarize", lambda *a, **kw: {"work_totals": {}})
    config = cfg(**FIXED)
    shards = [S.run_cluster(config, c) for c in range(2)]
    result = S.summary_for(shards, config)
    assert result["round_kind"] == "fixed_banker"
    assert result["arm_role_coverage"] == {"banker": 2, "attacker": 2}
    assert "round_kind" not in S.summary_for(shards, cfg())
