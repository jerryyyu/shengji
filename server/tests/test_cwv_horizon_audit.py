"""Focused contracts for the bounded CWV horizon diagnostics."""

import numpy as np
import pytest

from shengji.ai.mcbot import MCBot
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.train.cwv_horizon_audit import (
    reference_returns,
    run_fixed_ballot,
    score_horizon_matrix,
    topk_with_incumbent,
)
from tests.test_world_shortlist import fixed_world, play_state, round_signature


class RecordingEvaluator:
    def __init__(self, offset=0.0):
        self.offset = offset
        self.calls = []

    def score(self, leaves, seat, *, tensor_cache=None):
        self.calls.append((len(leaves), tuple(id(leaf) for leaf in leaves), tensor_cache))
        return [self.offset + 10 * len(leaf.history) + len(leaf.trick.plays)
                for leaf in leaves]


def test_matrix_is_world_major_bounded_and_does_not_mutate_inputs():
    rnd = play_state()
    seat = rnd.turn
    worlds = [fixed_world(rnd, seat)]
    actions = REGISTRY["mc-s0-report-lcb"](seed=2)._candidates(rnd, seat)[:2]
    before = round_signature(rnd)
    left, right = RecordingEvaluator(), RecordingEvaluator(0.5)

    result = score_horizon_matrix(
        rnd, seat, actions, worlds, {"left": left, "right": right},
        finish_trick=False, batch_size=1)
    assert result["left"].shape == (1, 2)
    assert len(left.calls) == len(right.calls) == 2
    assert all(call[0] == 1 for call in left.calls)
    assert [call[1] for call in left.calls] == [call[1] for call in right.calls]
    assert left.calls[0][2] is left.calls[1][2]
    assert left.calls[0][2] is not right.calls[0][2]
    assert round_signature(rnd) == before
    assert worlds[0][0] == fixed_world(rnd, seat)[0]

    finished = score_horizon_matrix(
        rnd, seat, actions, worlds, {"left": RecordingEvaluator()},
        finish_trick=True, batch_size=2)["left"]
    assert not np.array_equal(result["left"], finished)


def test_matrix_refuses_duplicates_nan_and_empty_inputs():
    rnd = play_state()
    seat = rnd.turn
    world = fixed_world(rnd, seat)
    action = HeuristicBot().decide_play(rnd, seat)
    evaluator = RecordingEvaluator()
    with pytest.raises(ValueError, match="unique"):
        score_horizon_matrix(rnd, seat, [action, action], [world], {"x": evaluator},
                             finish_trick=False)
    with pytest.raises(ValueError, match="non-empty"):
        score_horizon_matrix(rnd, seat, [action], [], {"x": evaluator}, finish_trick=False)

    class NaN:
        def score(self, leaves, seat, **kwargs):
            return [np.nan] * len(leaves)

    with pytest.raises(ValueError, match="finite"):
        score_horizon_matrix(rnd, seat, [action], [world], {"x": NaN()},
                             finish_trick=False)


def test_topk_keeps_incumbent_and_uses_exact_card_tuple_tie_order():
    actions = [["S9"], ["S10"], ["H2"], ["D2"]]
    assert topk_with_incumbent(actions, [1.0, 3.0, 3.0, 2.0], ["S9"], 2) == [
        0, 2, 1]
    with pytest.raises(ValueError, match="incumbent"):
        topk_with_incumbent(actions, [1.0] * 4, ["CA"])


def test_repeated_worlds_preserve_requested_rows_and_match_means_consumer():
    rnd = play_state()
    seat = rnd.turn
    actions = REGISTRY["mc-s0-report-lcb"](seed=2)._candidates(rnd, seat)[:2]
    world = fixed_world(rnd, seat)
    full_world = ([list(hand) for hand in rnd.hands], list(world[1]))
    worlds = [full_world, full_world]
    audit_eval = RecordingEvaluator()
    got = score_horizon_matrix(rnd, seat, actions, worlds, {"x": audit_eval},
                               finish_trick=True, batch_size=2)["x"]
    consumer_eval = RecordingEvaluator()
    consumer = CWVShortlistBot(
        consumer_eval, config=CWVShortlistConfig(batch_size=2),
        reuse_successors=True)
    expected = consumer._means(rnd, seat, actions, worlds)
    assert got.shape == (2, 2)
    assert np.array_equal(got[0], got[1])
    assert np.allclose(got.mean(axis=0), expected)
    assert len(audit_eval.calls) == 2

    refs = reference_returns(rnd, seat, [actions[0]], worlds)
    assert refs["points"].shape == refs["levels"].shape == (2, 1)
    assert refs["points"][0, 0] == refs["points"][1, 0]
    assert refs["levels"][0, 0] == refs["levels"][1, 0]


def test_reference_and_fixed_ballot_follow_native_production_paths():
    rnd = play_state()
    seat = rnd.turn
    bot = REGISTRY["mc-s0-report-lcb"](seed=0)
    actions = bot._candidates(rnd, seat)[:2]
    world = fixed_world(rnd, seat)
    expected = bot._rollout(
        rnd, seat,
        {s: list(world[0][s]) for s in range(4) if s != seat},
        list(world[1]), list(actions[0]))
    values = reference_returns(rnd, seat, [actions[0]], [world])
    assert values["points"][0, 0] == expected
    assert values["points"].dtype == values["levels"].dtype == np.float64
    result = run_fixed_ballot(rnd, seat, actions, seed=7,
                              selection_worlds=1, report_worlds=30)
    assert result["played"] in actions
    assert result["record"]["work"]["selection_rollouts"] == 2
    assert result["record"]["work"]["report_rollouts"] == 60


def test_fixed_ballot_inherits_selection_objective_and_report(monkeypatch):
    rnd = play_state()
    seat = rnd.turn
    base = REGISTRY["mc-s0-report-lcb"](seed=0)
    actions = base._candidates(rnd, seat)[:2]
    report_calls = []
    original_report = MCBot._report_fold_gap

    def wrapped_report(self, *args, **kwargs):
        report_calls.append((self.REPORT_RULE, self.LEVEL_OBJECTIVE,
                             self.TRACTOR_LOCK))
        return original_report(self, *args, **kwargs)

    def fixed_rollout(_self, _rnd, _seat, _sampled, _buried, candidate, **_kwargs):
        if tuple(sorted(candidate)) != tuple(sorted(actions[1])):
            return 0.0
        return 100.0 if _rnd.is_attacker(_seat) else -100.0

    monkeypatch.setattr(MCBot, "_report_fold_gap", wrapped_report)
    monkeypatch.setattr(MCBot, "_rollout", fixed_rollout)
    result = run_fixed_ballot(rnd, seat, actions, seed=7,
                              selection_worlds=1, report_worlds=30)
    assert result["played"] == actions[1]
    assert report_calls == [("lcb", False, False)]
    assert result["record"]["report_rule"] == "lcb"
    assert result["record"]["confidence_override"] is False
