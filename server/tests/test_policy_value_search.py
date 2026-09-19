from types import SimpleNamespace
import copy

import numpy as np
import pytest

from shengji.train import policy_value_search as module
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state


def test_policy_admits_then_value_selects_and_anchor_is_retained(monkeypatch):
    actions = [('S2',), ('S3',), ('S4',)]
    monkeypatch.setattr(module.HeuristicBot, 'decide_play', lambda *a: ['S2'])
    monkeypatch.setattr(module, 'enumerate_legal', lambda *a, **k:
                        SimpleNamespace(actions=actions, count=3, complete=True))
    bot = PolicyValueBot(None, evaluator=object(), candidates=2)
    monkeypatch.setattr(bot, '_worlds', lambda *a: ([None] * 4, 4))
    monkeypatch.setattr(bot, 'scores', lambda *a: np.tile([0., 9., 5.], (4, 1)))
    def values(rnd, seat, admitted, worlds):
        assert admitted == actions[:2]
        assert len(worlds) == 4
        return np.array([0., 1.]), 1
    monkeypatch.setattr(bot, '_value_means', values)
    assert bot.decide_play(None, 0) == ['S3']
    assert bot.last_decision_record['value_evaluations'] == 8
    monkeypatch.setattr(bot, '_value_means', lambda *a: (np.zeros(2), 1))
    assert bot.decide_play(None, 0) == ['S2']


def test_value_batches_keep_world_action_order_and_root_perspective(monkeypatch):
    calls = []
    def leaf(rnd, seat, hands, buried, action, finish_trick):
        assert finish_trick is True
        return (hands, action)
    monkeypatch.setattr(module, 'afterstate', leaf)
    class Evaluator:
        def score(self, leaves, seat):
            assert seat == 2
            calls.append(list(leaves))
            return [w + a[0] for w, a in leaves]
    bot = PolicyValueBot(None, evaluator=Evaluator(), batch_size=3)
    means, batches = bot._value_means(None, 2, [(1,), (2,)], [(10, []), (20, [])])
    assert np.array_equal(means, [16., 17.])
    assert [len(c) for c in calls] == [3, 1]
    assert batches == 2


@pytest.mark.parametrize('bad', [[float('nan')], [1., 2.]])
def test_bad_value_output_refuses(monkeypatch, bad):
    monkeypatch.setattr(module, 'afterstate', lambda *a, **k: None)
    bot = PolicyValueBot(None, evaluator=SimpleNamespace(score=lambda *a: bad))
    with pytest.raises(ValueError, match='finite root-team'):
        bot._value_means(None, 0, [('S2',)], [(None, None)])


@pytest.mark.parametrize('n', [0, True, 513])
def test_candidate_budget_bounded(n):
    with pytest.raises(ValueError):
        PolicyValueBot(None, evaluator=object(), candidates=n)


def test_real_afterstates_do_not_depend_on_actual_hidden_hands():
    rnd = state(); seat = rnd.turn
    changed = copy.deepcopy(rnd)
    opponents = [s for s in range(4) if s != seat]
    changed.hands[opponents[0]], changed.hands[opponents[1]] = (
        changed.hands[opponents[1]], changed.hands[opponents[0]])
    traces = []
    class Evaluator:
        def score(self, leaves, perspective):
            assert perspective == seat
            traces.append([(copy.deepcopy(r.hands), list(r.buried), r.attacker_points)
                           for r in leaves])
            return np.zeros(len(leaves))
    predict = lambda x: np.tile(np.arange(54), (len(x), 1))
    first = PolicyValueBot(predict, evaluator=Evaluator(), worlds=2, candidates=3, seed=17)
    second = PolicyValueBot(predict, evaluator=Evaluator(), worlds=2, candidates=3, seed=17)
    before = copy.deepcopy(rnd.hands)
    assert first.decide_play(rnd, seat) == second.decide_play(changed, seat)
    assert traces[0] == traces[1]
    assert rnd.hands == before


def test_nonbanker_value_leaves_do_not_read_actual_kitty():
    rnd = state()
    rnd.play(rnd.turn, module.HeuristicBot().decide_play(rnd, rnd.turn))
    seat = rnd.turn
    assert seat != rnd.banker
    changed = copy.deepcopy(rnd)
    other = next(s for s in range(4) if s != seat)
    changed.buried[0], changed.hands[other][-1] = (
        changed.hands[other][-1], changed.buried[0])
    traces = []
    class Evaluator:
        def score(self, leaves, perspective):
            assert perspective == seat
            traces.extend((copy.deepcopy(r.hands), list(r.buried), r.attacker_points)
                          for r in leaves)
            return np.zeros(len(leaves))
    predict = lambda x: np.tile(np.arange(54), (len(x), 1))
    first = PolicyValueBot(predict, evaluator=Evaluator(), worlds=2, candidates=3,
                           seed=19, batch_size=1)
    second = PolicyValueBot(predict, evaluator=Evaluator(), worlds=2, candidates=3,
                            seed=19, batch_size=128)
    action = first.decide_play(rnd, seat)
    expected = copy.deepcopy(traces)
    traces.clear()
    assert second.decide_play(changed, seat) == action
    assert traces == expected
    assert first.last_decision_record['value_means'] == second.last_decision_record['value_means']
