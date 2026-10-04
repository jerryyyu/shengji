import copy
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.eval.fixed_tape_capture import capture_fixed_tape
from shengji.train.pv_search_policy import PVSearchBot


ACTIONS = [["S3"], ["S2"], ["S4"]]
ROOT = SimpleNamespace(turn=0, history=[], is_attacker=lambda seat: seat % 2 == 1)


class Evaluator:
    def __init__(self):
        self.calls = []

    def score(self, leaves, seat):
        self.calls.append([(leaf.world, leaf.action) for leaf in leaves])
        return [leaf.value for leaf in leaves]


class Harness(PVSearchBot):
    def __init__(self, batch_size=5):
        self.evaluator = Evaluator()
        self.batch_size = batch_size
        self.leaf_calls = []

    def _leaf(self, root, seat, hands, buried, action, world_index):
        index = ACTIONS.index(action)
        self.leaf_calls.append((world_index, index))
        # Deliberately order-sensitive values distinguish fsum from serving sum.
        value = [1e16, 1., -1e16][world_index] + index * 0.125
        return SimpleNamespace(world=world_index, action=index, value=value,
                               history=[1], last_trick=SimpleNamespace(
                                   winner=index % 2, points=5 * (world_index + index)))


@pytest.mark.parametrize("batch_size", [1, 2, 5, 128])
def test_one_leaf_per_cell_and_exact_serving_accumulator(batch_size):
    worlds = [([], []) for _ in range(3)]
    original = copy.deepcopy((ACTIONS, worlds))
    bot = Harness(batch_size)
    evaluator = bot.evaluator
    result = capture_fixed_tape(bot, ROOT, 0, ACTIONS, worlds)
    reference = Harness(batch_size)
    means, batches = reference._value_means(ROOT, 0, ACTIONS, worlds)
    assert result["serving_value_means"] == means.tolist()
    assert result["batches"] == batches
    assert evaluator.calls == reference.evaluator.calls
    assert bot.leaf_calls == [(w, a) for w in range(3) for a in range(3)]
    assert result["signed_trick_points"] == [[0, -5, 10], [5, -10, 15], [10, -15, 20]]
    assert bot.evaluator is evaluator
    assert (ACTIONS, worlds) == original
    assert not result["provenance_verified"]


@pytest.mark.parametrize("failure", ["evaluator", "budget", "unresolved", "nan"])
def test_failure_restores_evaluator_and_returns_no_result(failure):
    bot = Harness()
    original = bot.evaluator
    if failure == "evaluator":
        def fail(*args):
            raise RuntimeError("evaluation failed")
        original.score = fail
    elif failure == "nan":
        original.score = lambda leaves, seat: [float("nan")] * len(leaves)
    elif failure == "unresolved":
        bot._leaf = lambda *args: SimpleNamespace(history=[], last_trick=None)
    calls = 0
    def budget():
        nonlocal calls
        calls += 1
        if failure == "budget" and calls == 2:
            raise RuntimeError("post-score deadline")
    with pytest.raises((RuntimeError, ValueError)):
        capture_fixed_tape(bot, ROOT, 0, ACTIONS, [([], [])] * 3, check_budget=budget)
    assert bot.evaluator is original


def test_real_engine_points_and_value_loop_share_the_identical_leaves():
    from test_pv_tiebreak_points import last_position, served, engine_points
    root = last_position()
    bot = served(tiebreak_points=True)
    worlds = [(copy.deepcopy(root.hands), list(root.buried))]
    actions = [["DK"], ["D6"]]
    expected = [engine_points(root, root.turn, action) for action in actions]
    evaluator = bot.evaluator
    result = capture_fixed_tape(bot, root, root.turn, actions, worlds)
    assert result["signed_trick_points"] == [expected] == [[-20, -10]]
    means, _ = bot._value_means(root, root.turn, actions, worlds)
    np.testing.assert_array_equal(result["serving_value_means"], means)
    assert bot.evaluator is evaluator


def test_reordered_scoring_override_is_refused_before_evaluation():
    bot = Harness()
    bot._score_leaves = lambda *args, **kwargs: None
    with pytest.raises(ValueError, match="canonical world-major"):
        capture_fixed_tape(bot, ROOT, 0, ACTIONS, [([], [])])
    assert bot.evaluator.calls == []
