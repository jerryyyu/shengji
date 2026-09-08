"""Contracts for the CWV shortlist consumer with a points continuation."""
from __future__ import annotations

import copy

import numpy as np

from shengji.train.cwv_leaf_shortlist import CWVPointsLeafShortlistBot
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state, round_signature


class PointsLeaf:
    kind = "test-points"

    def __init__(self, value=50.0):
        self.value = value
        self.positions = []

    def final_attacker_points(self, clone, seat):
        plays = clone.trick.plays if clone.trick is not None else []
        if not plays:
            plays = clone.history[-1].plays
        self.positions.append({
            "history": len(clone.history),
            "trick_plays": len(clone.trick.plays),
            "seat": seat,
            "turn": clone.turn,
            "last_actor": plays[-1].seat,
            "determinized": clone._determinized_world,
        })
        return self.value


class RootTeamEvaluator:
    def __init__(self, value=0.0):
        self.value = value
        self.calls = []

    def score(self, leaves, seat, **kwargs):
        self.calls.append((len(leaves), seat, kwargs.get("tensor_cache")))
        return np.full(len(leaves), self.value, dtype=np.float64)


def config():
    return CWVShortlistConfig(worlds=1, selection_worlds=2,
                              alternatives=4, batch_size=13)


def consumer(seed, leaf, *, view="last_actor"):
    bot = CWVPointsLeafShortlistBot(
        RootTeamEvaluator(), leaf, seed=seed, config=config(),
        reuse_successors=True, leaf_tricks=1, leaf_view=view)
    bot.REPORT_FOLD_WORLDS = 30
    return bot


def test_horizon_beyond_round_is_the_unchanged_shortlist_consumer():
    rnd = play_state()
    before = round_signature(rnd)
    baseline = CWVShortlistBot(
        RootTeamEvaluator(), seed=19, config=config(), reuse_successors=True)
    baseline.REPORT_FOLD_WORLDS = 30
    leaf = PointsLeaf()
    hybrid = CWVPointsLeafShortlistBot(
        RootTeamEvaluator(), leaf, seed=19, config=config(),
        reuse_successors=True, leaf_tricks=100, leaf_view="mover")
    hybrid.REPORT_FOLD_WORLDS = 30

    left = baseline.decide_play(rnd, rnd.turn)
    twin = copy.deepcopy(rnd)
    right = hybrid.decide_play(twin, twin.turn)
    assert right == left
    assert leaf.positions == []
    assert hybrid.leaf_counts["predicted_leaves"] == 0
    assert hybrid.leaf_stage == "all"
    assert hybrid.rng.getstate() == baseline.rng.getstate()
    for field in ("candidates", "means", "n_by_candidate", "paired_se",
                  "raw_winner_index", "report_candidate_index", "worlds",
                  "eligible_indices", "report_seed", "rng_state", "report_fold"):
        assert hybrid.last_decision_record[field] == baseline.last_decision_record[field]
    assert {k: v for k, v in hybrid.last_shortlist.items() if k != "wall_seconds"} == {
        k: v for k, v in baseline.last_shortlist.items() if k != "wall_seconds"}
    assert round_signature(rnd) == before
    assert round_signature(twin) == before


def test_t1_points_leaf_runs_in_selection_and_report_with_both_viewpoints():
    rnd = play_state()
    before = round_signature(rnd)
    mover_leaf, last_leaf = PointsLeaf(), PointsLeaf()
    mover = consumer(23, mover_leaf, view="mover")
    last_actor = consumer(23, last_leaf, view="last_actor")
    mover.decide_play(rnd, rnd.turn)
    twin = copy.deepcopy(rnd)
    last_actor.decide_play(twin, twin.turn)

    for bot, points in ((mover, mover_leaf), (last_actor, last_leaf)):
        assert bot.leaf_view in ("mover", "last_actor")
        assert bot.leaf_stage == "all"
        assert bot.leaf_counts["predicted_leaves"] > 0
        assert bot.stage_counts["selection_net_calls"] == bot.last_decision_record[
            "work"]["selection_rollouts"]
        assert bot.stage_counts["report_net_calls"] == bot.last_decision_record[
            "work"]["report_rollouts"] == 60
        assert len(points.positions) == bot.leaf_counts["predicted_leaves"]
        assert all(row["determinized"] for row in points.positions)
    assert all(row["seat"] == row["turn"] for row in mover_leaf.positions)
    assert all(row["seat"] == row["last_actor"] for row in last_leaf.positions)
    assert any(row["seat"] != row["turn"] for row in last_leaf.positions)
    assert "cwv-shortlist" in mover.policy_name
    assert "points-leaf-t1-mover" in mover.policy_name
    assert "points-leaf-t1-last_actor" in last_actor.policy_name
    assert round_signature(rnd) == before
    assert round_signature(twin) == before


def test_leaf_view_does_not_change_full_legal_nominations():
    rnd = play_state()
    mover = consumer(31, PointsLeaf(), view="mover")
    last_actor = consumer(31, PointsLeaf(), view="last_actor")
    assert mover._candidates(rnd, rnd.turn) == last_actor._candidates(rnd, rnd.turn)

