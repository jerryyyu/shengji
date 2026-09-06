"""Opt-in inner successor reuse: real consumer and receipt witnesses."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from shengji.ai.cwv_policy import CompleteWorldEvaluator
from shengji.ai.heuristic import HeuristicBot
from shengji.harvest.legal import enumerate_legal
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import cwv_shortlist_screen as screen
from shengji.train.cwv_double_shortlist import CWVDoubleShortlistBot, DoubleShortlistError
from shengji.train.cwv_shortlist import CWVShortlistConfig
from tests.test_cwv_double_shortlist import PointsNet
from tests.test_cwv_static_public import _state_after
from tests.test_world_shortlist import round_signature


class _TraceEvaluator:
    """Keep the real evaluator's score and batch boundaries observable."""

    def __init__(self, model):
        self.inner = CompleteWorldEvaluator(None, model=model, max_batch=16)
        self.batches = []
        self.outputs = []

    def score(self, positions, seat, *, tensor_cache=None):
        self.batches.append(("score", len(positions), (seat,) * len(positions)))
        values = self.inner.score(positions, seat, tensor_cache=tensor_cache)
        self.outputs.append(np.asarray(values, dtype=np.float64).tobytes())
        return values

    def score_many(self, positions, seats, *, tensor_cache=None):
        self.batches.append(("score_many", len(positions), tuple(seats)))
        values = self.inner.score_many(positions, seats, tensor_cache=tensor_cache)
        self.outputs.append(np.asarray(values, dtype=np.float64).tobytes())
        return values


def _scientific(value):
    """Drop only observational timing/cache receipts for exact A/B parity."""
    if isinstance(value, dict):
        return {key: _scientific(item) for key, item in value.items()
                if key not in {"inner_successor_reuse", "successor_reuse",
                               "wall_seconds", "search_secs"}}
    if isinstance(value, (list, tuple)):
        return [_scientific(item) for item in value]
    return value


def _real_bot(state, model, reuse):
    config = CWVShortlistConfig(worlds=1, selection_worlds=1, batch_size=16)
    evaluator = _TraceEvaluator(model)
    bot = CWVDoubleShortlistBot(
        evaluator, seed=91, config=config, inner_worlds=1,
        inner_batch_size=16, inner_reuse_successors=reuse)
    bot.REPORT_FOLD_WORLDS = 30
    bot.REPORT_RULE = "lcb"
    return bot, evaluator


def test_real_decide_play_reuse_is_a_scientific_noop_with_actual_cache_work():
    # Late, valid engine state keeps both the physical deck and the real
    # CompleteWorldEvaluator contract while making this witness inexpensive.
    import torch
    torch.manual_seed(37)
    model = ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    state = _state_after(73, 50)
    assert state.trick.plays  # actual FOLLOW decision, not a helper-only path
    original = round_signature(state)
    off, off_eval = _real_bot(state, model, False)
    on, on_eval = _real_bot(state, model, True)
    off_input = copy.deepcopy(state)
    on_input = copy.deepcopy(state)
    played_off = off.decide_play(off_input, state.turn)
    played_on = on.decide_play(on_input, state.turn)

    assert played_on == played_off
    assert on.rng.getstate() == off.rng.getstate()
    assert _scientific(on.last_decision_record) == _scientific(
        off.last_decision_record)
    for key in ("candidates", "means", "paired_se", "report_fold",
                "sampler_counters", "raw_winner_index",
                "report_candidate_index", "alloc"):
        assert on.last_decision_record[key] == off.last_decision_record[key]
    assert on_eval.batches == off_eval.batches
    assert on_eval.outputs == off_eval.outputs
    assert round_signature(off_input) == original
    assert round_signature(on_input) == original
    assert off.last_inner_successor_reuse is None
    assert on.last_inner_successor_reuse["leaf_hits"] > 0
    assert on.last_inner_successor_reuse["tensor_hits"] > 0
    assert on.last_double_shortlist["inner_successor_reuse"] == (
        on.last_inner_successor_reuse)
    assert on.inner_successor_counts["peak_entries"] == max(
        row["inner_successor_reuse"]["peak_entries"]
        for row in on.last_double_shortlist["stages"])
    assert on.inner_successor_counts["peak_tensor_entries"] == max(
        row["inner_successor_reuse"]["peak_tensor_entries"]
        for row in on.last_double_shortlist["stages"])
    assert "inner_successor_reuse" not in off.last_double_shortlist
    assert round_signature(state) == original


def test_zero_reuse_and_nonstandard_heuristic_keep_original_inner_path():
    state = _state_after(73, 50)
    seat = state.turn
    legal = enumerate_legal(state, seat, cap=None)

    class CustomHeuristic(HeuristicBot):
        pass

    class CacheAwareNet(PointsNet):
        def score_many(self, positions, seats, *, tensor_cache=None):
            return super().score_many(positions, seats)

    bot = CWVDoubleShortlistBot(CacheAwareNet(), inner_worlds=1,
                                inner_reuse_successors=True)
    bot.rollout_policy = CustomHeuristic()
    stats = {key: 0 for key in (
        "inner_actions", "inner_finalist_actions", "inner_net_rows",
        "inner_batches", "inner_full_rollouts")}
    bot._rank_inner(state, seat, (0, 0, 0), stats, legal)
    assert stats.get("inner_cache_leaf_hits", 0) == 0
    assert stats.get("inner_cache_leaf_completions", 0) == 0
    assert stats["inner_net_rows"] == len(legal.actions)

    plain = CWVDoubleShortlistBot(PointsNet(), inner_worlds=1)
    assert plain.inner_reuse_successors is False
    assert plain.last_inner_successor_reuse is None


def test_reuse_keyword_requires_boolean_and_tensor_cache_capability():
    with pytest.raises(DoubleShortlistError, match="must be boolean"):
        CWVDoubleShortlistBot(PointsNet(), inner_reuse_successors=1)
    with pytest.raises(DoubleShortlistError, match="tensor_cache"):
        CWVDoubleShortlistBot(PointsNet(), inner_reuse_successors=True)


def test_zero_reuse_follows_keep_cross_parent_movers_scores_and_all_rows():
    import torch
    torch.manual_seed(39)
    model = ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))
    states = [_state_after(73, n) for n in (49, 50)]
    assert all(state.trick.plays for state in states)
    assert len({state.turn for state in states}) == 2
    signatures = [round_signature(state) for state in states]
    results = []
    for reuse in (False, True):
        evaluator = _TraceEvaluator(model)
        bot = CWVDoubleShortlistBot(evaluator, inner_batch_size=128,
                                    inner_reuse_successors=reuse)
        parents = [{"state": state, "mover": state.turn, "branch": (i, 0, 0)}
                   for i, state in enumerate(states)]
        stats = {"inner_actions": 0, "inner_net_rows": 0, "inner_batches": 0}
        ranked = bot._rank_inner_many(parents, stats)
        results.append((evaluator, stats, [
            (actions, [round_signature(leaves[action]) for action in actions])
            for actions, leaves in ranked]))
    before, after = results
    assert before[0].outputs == after[0].outputs
    assert before[0].batches == after[0].batches
    assert before[2] == after[2]
    assert after[1]["inner_cache_leaf_hits"] == after[1]["inner_tensor_hits"] == 0
    assert after[1]["inner_cache_root_actions"] == after[1]["inner_actions"] > 0
    assert after[1]["inner_cache_leaf_completions"] == after[1]["inner_actions"]
    assert after[1]["inner_tensor_completions"] == after[1]["inner_net_rows"]
    assert after[1]["inner_cross_parent_batches"] > 0
    assert [round_signature(state) for state in states] == signatures


def test_screen_published_opt_in_factory_and_resume_refusal(tmp_path, monkeypatch):
    class ReuseEvaluator(PointsNet):
        checkpoint_sha256 = "b" * 64

        def score_many(self, positions, seats, *, tensor_cache=None):
            return super().score_many(positions, seats)

        def identity(self):
            return {"checkpoint_sha256": self.checkpoint_sha256}

    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator", lambda *a, **k: ReuseEvaluator())
    monkeypatch.setattr(screen, "_run_pending", lambda *a, **k: None)
    out = tmp_path / "screen"
    assert screen.main([
        "--arm", "learned", "--checkpoint", "unused.pt",
        "--selection-worlds", "30", "--report-worlds", "30",
        "--inner-mode", "learned", "--inner-worlds", "4",
        "--inner-reuse-successors", "--clusters", "1", "--workers", "1",
        "--seed0", "17", "--out", str(out)]) == 0
    config = json.loads((out / "config.json").read_text())
    assert config["double_shortlist"]["reuse_successors"] is True
    bot = screen.make_side(config, "arm", 17)
    assert bot.inner_reuse_successors is True
    shard = {"schema": "cwv-shortlist-shard-v1", "cluster": 0,
             "seed": 17, "rank": "2", "recipe": screen._recipe(config),
             "records": [{"cluster": 0, "seed": 17, "mirror": mirror,
                          "trump_rank": "2", "arm": "learned"}
                         for mirror in (0, 1)]}
    path = out / "cluster-00000.json"
    path.write_text(json.dumps(shard))
    assert screen.reopen_shard(path, config, 0) == shard
    changed = copy.deepcopy(config)
    changed["double_shortlist"]["reuse_successors"] = False
    with pytest.raises(ValueError, match="^completed shard does not match its mirrored pair and recipe$"):
        screen.reopen_shard(path, changed, 0)
