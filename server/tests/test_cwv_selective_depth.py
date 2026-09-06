"""Pure witnesses for the opt-in CWV selective-depth gate."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.harvest.legal import LegalSet
from shengji.train.cwv_double_shortlist import DoubleShortlistError
from shengji.train.cwv_selective_depth import CWVSelectiveDepthBot
from shengji.train.cwv_shortlist import CWVShortlistConfig
from tests.test_cwv_double_shortlist import PointsNet
from tests.test_world_shortlist import play_state, round_signature


def _bot(**kwargs):
    return CWVSelectiveDepthBot(
        PointsNet(), seed=7,
        config=CWVShortlistConfig(worlds=1, selection_worlds=2), **kwargs)


@pytest.mark.parametrize("kwargs", [
    {"gate_z": 0}, {"gate_z": float("nan")},
    {"inner_legal_limit": True}, {"inner_legal_limit": 0},
])
def test_selective_depth_rejects_invalid_limits(kwargs):
    with pytest.raises(DoubleShortlistError):
        _bot(**kwargs)


def test_gate_false_reuses_flat_matrix_and_does_not_rank(monkeypatch):
    rnd = play_state()
    bot = _bot()
    seat = rnd.turn
    worlds = [([list(h) for h in rnd.hands], list(rnd.buried))] * 2
    candidates = [list(rnd.hands[seat][:1]), list(rnd.hands[seat][1:2])]
    flat = np.asarray([[10.0, 10.0], [10.0, 10.0]])
    monkeypatch.setattr(bot, "_flat_matrix", lambda *a, **k: flat.copy())
    values = bot._lockstep_values(rnd, seat, worlds, candidates, stage="selection")
    np.testing.assert_array_equal(values, flat)
    assert bot.last_selective_depth["triggered"] is False
    assert bot.last_selective_depth["reason"] == "paired-se-not-positive"
    assert bot.last_double_shortlist is None
    report = bot._lockstep_values(rnd, seat, worlds, candidates, stage="report")
    np.testing.assert_array_equal(report, flat)
    assert bot.last_selective_depth["extra_rollout_cost"] == 0


def test_gate_true_only_overwrites_guided_prefix_and_records_work(monkeypatch):
    rnd = play_state()
    bot = _bot()
    bot.N_DETERMINIZATIONS = 8
    seat = rnd.turn
    worlds = [([list(h) for h in rnd.hands], list(rnd.buried))] * 8
    candidates = [list(rnd.hands[seat][:1]), list(rnd.hands[seat][1:2])]
    flat = np.asarray([[10.0, 11.0], [10.0, 9.0]] * 4)
    original = flat.copy(), copy.deepcopy(worlds), round_signature(rnd)
    monkeypatch.setattr(bot, "_flat_matrix", lambda *a, **k: flat)
    root_calls = []
    root_leaf = bot._root_leaf

    def counted_leaf(*args, **kwargs):
        root_calls.append(1)
        return root_leaf(*args, **kwargs)

    monkeypatch.setattr(bot, "_root_leaf", counted_leaf)
    values = bot._lockstep_values(rnd, seat, worlds, candidates, stage="selection")
    assert bot.last_selective_depth["triggered"] is True
    assert bot.last_selective_depth["pilot_gap"] == 0.0
    assert bot.last_selective_depth["pilot_se"] > 0
    assert bot.last_selective_depth["reused_flat_cells"] == 8
    assert len(root_calls) == 8  # four worlds x two actions, not all 16 cells
    np.testing.assert_array_equal(values[4:], flat[4:])
    np.testing.assert_array_equal(flat, original[0])
    assert worlds == original[1] and round_signature(rnd) == original[2]
    assert values.shape == flat.shape
    assert bot.last_selective_depth["stages"][0]["guided"] is True
    assert bot.last_selective_depth["inner_eligible"] > 0
    assert bot.evaluator.calls


@pytest.mark.parametrize("attacker,nominated,triggered,gap", [
    (True, 2, False, 3.0), (False, 1, True, 0.0),
])
def test_gate_nominates_and_scores_from_acting_team(attacker, nominated, triggered, gap):
    bot = _bot()
    bot.LEVEL_OBJECTIVE = False
    rnd = SimpleNamespace(is_attacker=lambda seat: attacker)
    matrix = np.asarray([[100., 101., 104.], [100., 99., 102.]])
    result = bot._pilot_gate(rnd, 0, matrix, [["C3"], ["D3"], ["S3"]])
    assert bool(result[0]) is triggered
    assert result[2:] == (nominated, gap, 1.0)


@pytest.mark.parametrize("count", [0, 1])
def test_underfilled_pilot_never_admits_guidance(count):
    bot = _bot()
    result = bot._pilot_gate(play_state(), 0, np.zeros((count, 2)), [["C3"], ["D3"]])
    assert result[0] is False
    assert result[1] == "selection-worlds-underfilled"


def test_terminal_root_leaves_record_zero_inner_work(monkeypatch):
    from shengji.ai.heuristic import HeuristicBot
    rnd = play_state()
    terminal = copy.deepcopy(rnd)
    policy = HeuristicBot()
    while terminal.phase == "play":
        terminal.play(terminal.turn, policy.decide_play(terminal, terminal.turn))
    bot = _bot()
    worlds = [([list(h) for h in rnd.hands], list(rnd.buried))] * 2
    candidates = [rnd.hands[rnd.turn][:1], rnd.hands[rnd.turn][1:2]]
    monkeypatch.setattr(bot, "_flat_matrix", lambda *a, **k: np.array([[10., 11.], [10., 9.]]))
    monkeypatch.setattr(bot, "_root_leaf", lambda *a, **k: terminal)
    values = bot._lockstep_values(rnd, rnd.turn, worlds, candidates, stage="selection")
    assert np.isfinite(values).all()
    detail = bot.last_selective_depth
    assert detail["triggered"] is True
    assert detail["inner_eligible"] == detail["inner_skipped"] == detail["inner_rollouts"] == 0
    assert detail["extra_rollout_cost"] == 4


def test_real_decide_play_charges_guided_outer_work_once(monkeypatch):
    rnd = play_state()
    original = tuple(tuple(h) for h in rnd.hands)
    bot = _bot()
    bot.REPORT_FOLD_WORLDS = 0
    bot.REPORT_RULE = "none"

    def flat(_rnd, _seat, worlds, candidates, **_kwargs):
        values = np.full((len(worlds), len(candidates)), 10.0)
        values[:, 1] = [11.0, 9.0]
        return values

    monkeypatch.setattr(bot, "_flat_matrix", flat)
    played = bot.decide_play(rnd, rnd.turn)
    assert played == bot.last_decision_record["played"]
    detail = bot.last_decision_record["cwv_selective_depth"]
    assert detail["triggered"] is True
    selection = detail["stages"][0]
    assert selection["extra_rollout_cost"] == 2 * len(bot.last_decision_record["candidates"])
    assert bot.last_decision_record["work"]["selective_depth_rollouts"] == selection["extra_rollout_cost"]
    assert bot.rollouts == bot.last_decision_record["work"][
        "total_rollouts_including_selective_depth"]
    assert tuple(tuple(h) for h in rnd.hands) == original


def test_overwide_inner_set_uses_incumbent_without_learned_ranker(monkeypatch):
    rnd = play_state()
    bot = _bot(inner_legal_limit=2)
    mover = rnd.turn
    incumbent = tuple(sorted(bot.rollout_policy.decide_play(rnd, mover)))
    parent = {"state": rnd, "mover": mover, "branch": (0, 0, 0)}
    calls = []

    def bounded(*args, **kwargs):
        calls.append(kwargs["cap"])
        return LegalSet("lead", [list(incumbent), [rnd.hands[mover][1]]], 99, False)

    monkeypatch.setattr("shengji.train.cwv_selective_depth.enumerate_legal", bounded)
    stats = {"inner_actions": 0, "inner_finalist_actions": 0,
             "inner_net_rows": 0, "inner_batches": 0, "inner_full_rollouts": 0}
    result = bot._rank_inner_many([parent], stats)
    assert calls == [3]
    assert result[0][0] == [incumbent]
    assert result[0][1][incumbent].phase in {"play", "round_end"}
    assert stats["inner_skipped"] == 1
    assert stats["inner_skip_reasons"] == {"incomplete": 1}
    assert bot.evaluator.calls == []


def test_raw_follow_bound_skips_before_global_enumerator(monkeypatch):
    rnd = play_state()
    # A live follow state is enough; the count helper is tripwired to model a
    # wide raw subset space without changing the engine fixture.
    from shengji.ai.heuristic import HeuristicBot
    rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    bot = _bot()
    mover = rnd.turn
    parent = {"state": rnd, "mover": mover, "branch": (0, 0, 0)}
    monkeypatch.setattr(
        "shengji.train.cwv_selective_depth.count_multiset_subsets",
        lambda *args: 4097)
    monkeypatch.setattr(
        "shengji.train.cwv_selective_depth.enumerate_legal",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not enumerate")))
    stats = {"inner_actions": 0, "inner_finalist_actions": 0,
             "inner_net_rows": 0, "inner_batches": 0, "inner_full_rollouts": 0}
    result = bot._rank_inner_many([parent], stats)
    incumbent = tuple(sorted(bot.rollout_policy.decide_play(rnd, mover)))
    assert result[0][0] == [incumbent]
    assert stats["inner_skip_reasons"] == {"raw-follow-bound": 1}
    assert stats["inner_raw_follow_skipped"] == 1


def test_forced_decision_clears_previous_selective_trace(monkeypatch):
    rnd = play_state()
    bot = _bot()
    bot.last_selective_depth = {"triggered": True}
    bot._selective_gate = True
    incumbent = bot.rollout_policy.decide_play(rnd, rnd.turn)
    monkeypatch.setattr(bot, "_candidates", lambda *_: [incumbent])
    assert bot.decide_play(rnd, rnd.turn) == incumbent
    assert bot.last_selective_depth is None
    assert bot._selective_gate is False


def test_consecutive_gate_states_do_not_reuse_prior_stage_stats(monkeypatch):
    rnd = play_state()
    bot = _bot()
    bot.REPORT_FOLD_WORLDS = 0
    bot.REPORT_RULE = "none"
    ambiguous = [True]

    def flat(_rnd, _seat, worlds, candidates, **_kwargs):
        values = np.full((len(worlds), len(candidates)), 10.0)
        if ambiguous[0]:
            values[:, 1] = [11.0, 9.0]
        return values

    monkeypatch.setattr(bot, "_flat_matrix", flat)
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_selective_depth["triggered"] is True
    ambiguous[0] = False
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_selective_depth["triggered"] is False
    assert bot.last_selective_depth["inner_rollouts"] == 0
    assert bot.last_selective_depth["stages"] == [
        {"stage": "selection", "worlds": 2, "cells": 10,
         "guided": False, "inner_eligible": 0, "inner_skipped": 0,
         "inner_raw_follow_skipped": 0, "inner_skip_reasons": {},
         "inner_rollouts": 0, "extra_rollout_cost": 0}]
    monkeypatch.setattr(bot, "_candidates", lambda *_: [rnd.hands[rnd.turn][:1]])
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_selective_depth is None
    assert bot._selective_gate is False
