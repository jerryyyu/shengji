import copy
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.train.policy_heuristic_lookahead import PolicyHeuristicLookaheadBot
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state


@pytest.mark.parametrize('plies', [0, 5, True, 1.5])
def test_invalid_horizon(plies):
    with pytest.raises(ValueError, match='extra_plies'):
        PolicyHeuristicLookaheadBot(None, evaluator=object(), extra_plies=plies)


@pytest.mark.parametrize('offset', range(4))
def test_fixed_horizon_matches_manual_heuristic_continuation(offset):
    rnd = state()
    heuristic = HeuristicBot()
    for _ in range(offset):
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    before = copy.deepcopy(rnd)
    seat = rnd.turn
    action = heuristic.decide_play(rnd, seat)
    bot = PolicyHeuristicLookaheadBot(None, evaluator=object())
    expected = PolicyValueBot._leaf(bot, rnd, seat, rnd.hands, rnd.buried, action, 0)
    for _ in range(4):
        expected.play(expected.turn, heuristic.decide_play(expected, expected.turn))
    actual = bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)
    assert actual.hands == expected.hands
    assert actual.history == expected.history
    assert actual.turn == expected.turn
    assert actual.attacker_points == expected.attacker_points
    assert len(actual.history) == len(rnd.history) + 2
    assert bot._continuation_plies == 4
    assert rnd.hands == before.hands and rnd.history == before.history


def test_terminal_leaf_skips_heuristic(monkeypatch):
    terminal = SimpleNamespace(phase='round_end')
    monkeypatch.setattr(PolicyValueBot, '_leaf', lambda *args: terminal)
    def forbidden(*args):
        raise AssertionError('terminal continuation')
    monkeypatch.setattr(HeuristicBot, 'decide_play', forbidden)
    bot = PolicyHeuristicLookaheadBot(None, evaluator=object())
    assert bot._leaf(None, 0, None, None, None, 0) is terminal
    assert bot._continuation_plies == 0


def test_stops_when_continuation_finishes_round(monkeypatch):
    leaf = SimpleNamespace(phase='play', turn=2)
    def play(actor, cards):
        assert actor == 2 and cards == [7]
        leaf.phase = 'round_end'
    leaf.play = play
    monkeypatch.setattr(PolicyValueBot, '_leaf', lambda *args: leaf)
    monkeypatch.setattr(HeuristicBot, 'decide_play', lambda *args: [7])
    bot = PolicyHeuristicLookaheadBot(None, evaluator=object())
    assert bot._leaf(None, 0, None, None, None, 0) is leaf
    assert bot._continuation_plies == 1


def test_continuation_failure_is_not_silently_replaced(monkeypatch):
    monkeypatch.setattr(PolicyValueBot, '_leaf',
                        lambda *args: SimpleNamespace(phase='play', turn=2,
                                                      play=lambda *a: None))
    def fail(*args):
        raise RuntimeError('continuation failed')
    monkeypatch.setattr(HeuristicBot, 'decide_play', fail)
    bot = PolicyHeuristicLookaheadBot(None, evaluator=object())
    with pytest.raises(RuntimeError, match='continuation failed'):
        bot._leaf(None, 0, None, None, None, 0)


def test_real_decision_root_perspective_privacy_and_work():
    rnd = state()
    seat = rnd.turn
    changed = copy.deepcopy(rnd)
    other = [s for s in range(4) if s != seat]
    changed.hands[other[0]], changed.hands[other[1]] = (
        changed.hands[other[1]], changed.hands[other[0]])
    class Evaluator:
        def score(self, leaves, root):
            assert root == seat
            assert all(len(leaf.history) == len(rnd.history) + 2 for leaf in leaves)
            return np.asarray([leaf.attacker_points for leaf in leaves])
    def predict(x):
        return np.tile(np.arange(54), (len(x), 1))
    first = PolicyHeuristicLookaheadBot(predict, evaluator=Evaluator(), worlds=2,
                                        candidates=2, seed=21)
    second = PolicyHeuristicLookaheadBot(predict, evaluator=Evaluator(), worlds=2,
                                         candidates=2, seed=21)
    assert first.decide_play(rnd, seat) == second.decide_play(changed, seat)
    record = dict(first.last_decision_record)
    assert record['continuation_work'] == dict(plies=16, worlds=0,
                                             sample_attempts=0, capped_decisions=0)
    assert record['value_means'] == second.last_decision_record['value_means']
    first.decide_play(rnd, seat)
    assert first.last_decision_record['continuation_work']['plies'] == 16
