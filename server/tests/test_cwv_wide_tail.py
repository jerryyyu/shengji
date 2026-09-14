"""Witness the bounded two-stage legal-tail admission on real game states."""
from __future__ import annotations

import math
from dataclasses import asdict
import json

import numpy as np
import pytest

from shengji.ai.registry import REGISTRY
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.train.cwv_wide_tail import CWVWideTailBot, CWVWideTailConfig
from tests.test_cwv_shortlist import Values
from tests.test_world_shortlist import play_state, round_signature


def test_recipe_is_strict_and_capture_is_refused():
    assert asdict(CWVWideTailConfig()) == {
        "threshold": 10_000, "coarse_worlds": 2, "pool": 256,
    }
    with pytest.raises(ValueError):
        CWVWideTailBot(Values(), config=CWVWideTailConfig(pool=4))
    with pytest.raises(ValueError):
        CWVWideTailConfig(threshold=True)
    with pytest.raises(ValueError, match="capture"):
        CWVWideTailBot(Values(), capture_full_legal_scores=True)


def test_parent_candidate_wiring_uses_disjoint_two_and_thirty_world_slices():
    rnd = play_state()
    before = round_signature(rnd)
    calls = []

    class Traced(CWVWideTailBot):
        def _means(self, rnd, seat, actions, worlds):
            calls.append((len(actions), len(worlds), tuple(id(world) for world in worlds)))
            return super()._means(rnd, seat, actions, worlds)

    bot = Traced(Values(), seed=13,
                 config=CWVWideTailConfig(threshold=1, pool=8))
    rng = bot.rng.getstate()
    selected = bot._candidates(rnd, rnd.turn)
    assert len(selected) == 5
    assert calls[0][1] == 2 and calls[1][1] == 30
    assert set(calls[0][2]).isdisjoint(calls[1][2])
    assert calls[0][0] == bot.last_shortlist["legal_count"]
    assert calls[1][0] == bot.last_shortlist["wide_tail"]["pool_action_count"]
    assert bot.rng.getstate() == rng
    assert round_signature(rnd) == before
    assert bot.last_shortlist["wide_tail"]["ranking_basis"] == "remaining-world-mean"
    assert all(math.isfinite(value) for value in bot.last_shortlist["shortlist_means"])


def test_refinement_ranking_beats_coarse_preference_and_keeps_anchors():
    rnd = play_state()
    seat = rnd.turn
    legal = enumerate_legal(rnd, seat, cap=None).actions
    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, seat)
    production_keys = {tuple(sorted(action)) for action in production}
    candidates = [action for action in legal if tuple(sorted(action)) not in production_keys]
    coarse_favorite, refined_favorite = candidates[:2]
    calls = []

    def controlled_means(_rnd, _seat, actions, worlds):
        calls.append((len(actions), len(worlds), [tuple(sorted(a)) for a in actions]))
        if len(worlds) == 2:
            return np.asarray([
                1000.0 if action == coarse_favorite else
                999.0 if action == refined_favorite else 0.0
                for action in actions
            ])
        return np.asarray([
            100.0 if action == refined_favorite else
            -100.0 if action == coarse_favorite else 0.0
            for action in actions
        ])

    bot = CWVWideTailBot(Values(), seed=13,
                         config=CWVWideTailConfig(threshold=1, pool=8))
    bot._means = controlled_means
    selected = bot._candidates(rnd, seat)
    assert refined_favorite in selected
    assert coarse_favorite not in selected
    refined_position = [list(action) for action in selected].index(refined_favorite)
    assert bot.last_shortlist["shortlist_means"][refined_position] == 100.0
    refined_keys = set(calls[1][2])
    assert production_keys <= refined_keys
    assert bot.last_shortlist["wide_tail"]["pool_indices"] == sorted(
        bot.last_shortlist["wide_tail"]["pool_indices"])
    json.dumps(bot.last_shortlist, allow_nan=False)


def test_threshold_path_remains_one_original_means_call():
    rnd = play_state()
    calls = []
    bot = CWVWideTailBot(Values(), seed=13)

    def reference(_rnd, _seat, actions, worlds):
        calls.append((len(actions), len(worlds)))
        return np.zeros(len(actions), dtype=float)

    bot._means = reference
    bot._candidates(rnd, rnd.turn)
    assert len(calls) == 1
    assert calls[0][1] == 32
    assert "wide_tail" not in bot.last_shortlist


@pytest.mark.parametrize("headroom", [0, 1, 10_000])
def test_threshold_boundary_is_reference_equivalent(headroom):
    rnd = play_state()
    count = len(enumerate_legal(rnd, rnd.turn, cap=None).actions)
    config = CWVShortlistConfig(worlds=32, batch_size=17)
    reference = CWVShortlistBot(Values(), seed=13, config=config)
    bounded = CWVWideTailBot(Values(), seed=13, config=config,
                             wide_tail=CWVWideTailConfig(threshold=count + headroom))
    assert bounded._candidates(rnd, rnd.turn) == reference._candidates(rnd, rnd.turn)
    assert bounded.rng.getstate() == reference.rng.getstate()
    assert bounded.shortlist_counts == reference.shortlist_counts
    assert [len(rows) for rows, _ in bounded.evaluator.calls] == [
        len(rows) for rows, _ in reference.evaluator.calls]
    for detail in (bounded.last_shortlist, reference.last_shortlist):
        detail.pop("wall_seconds")
    assert bounded.last_shortlist == reference.last_shortlist


@pytest.mark.parametrize("count", [9_999, 10_000, 10_001])
def test_ten_thousand_boundary_selects_exact_world_doses(count):
    bot = CWVWideTailBot(Values(), seed=13)
    actions = [[i] for i in range(count)]
    worlds = list(range(32))
    calls = []

    def means(_rnd, _seat, candidates, sampled):
        calls.append((len(candidates), tuple(sampled)))
        return np.zeros(len(candidates))

    bot._means = means
    bot._admission_means(None, 0, actions, worlds, actions[:1])
    if count <= 10_000:
        assert calls == [(count, tuple(worlds))]
        assert bot._wide_tail_diagnostics is None
    else:
        assert calls == [(count, (0, 1)), (256, tuple(range(2, 32)))]
        assert bot._wide_tail_diagnostics["threshold"] == 10_000


def test_forced_decision_drops_previous_wide_receipt(monkeypatch):
    from types import SimpleNamespace
    from shengji.train import cwv_shortlist as base
    rnd = play_state()
    bot = CWVWideTailBot(Values(), seed=13)
    bot._wide_tail_diagnostics = {"triggered": True}
    action = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, rnd.turn)[0]
    monkeypatch.setattr(REGISTRY["mc-s0-report-lcb"], "_candidates", lambda *a: [action])
    monkeypatch.setattr(base, "enumerate_legal", lambda *a, **k:
                        SimpleNamespace(actions=[sorted(action)], count=1))
    assert bot._candidates(rnd, rnd.turn) == [sorted(action)]
    assert "wide_tail" not in bot.last_shortlist
    assert bot._wide_tail_diagnostics is None
