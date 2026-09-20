import copy

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.train.policy_trick_value import PolicyTrickValueBot
from shengji.train import policy_trick_value as module
from test_policy_world_search import state


@pytest.mark.parametrize('worlds', [0, 5, True, 1.5])
def test_invalid_continuation_budget(worlds):
    with pytest.raises(ValueError):
        PolicyTrickValueBot(None, evaluator=object(), continuation_worlds=worlds)


@pytest.mark.parametrize('already_played', [0, 1, 2, 3])
def test_only_current_trick_resolved_at_each_root_position(already_played):
    rnd = state()
    for _ in range(already_played):
        rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    seat = rnd.turn
    before = copy.deepcopy(rnd.hands)
    inputs = []
    bot = PolicyTrickValueBot(lambda x: inputs.append(x.copy()) or np.zeros((len(x),54)),
                             evaluator=object(), seed=17)
    action = HeuristicBot().decide_play(rnd, seat)
    leaf = bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)
    assert len(leaf.history) == len(rnd.history)+1
    assert not leaf.trick.plays
    assert len(inputs) == 3-already_played
    assert bot._continuation_work.get('plies',0) == 3-already_played
    assert rnd.hands == before


def test_root_counterfactual_and_value_perspective():
    rnd = state(); seat = rnd.turn
    changed = copy.deepcopy(rnd)
    others = [s for s in range(4) if s != seat]
    changed.hands[others[0]], changed.hands[others[1]] = (
        changed.hands[others[1]], changed.hands[others[0]])
    traces = []
    class Evaluator:
        def score(self, leaves, perspective):
            assert perspective == seat
            assert all(len(r.history) == len(rnd.history)+1 for r in leaves)
            traces.append([(copy.deepcopy(r.hands), list(r.buried)) for r in leaves])
            return np.zeros(len(leaves))
    predict = lambda x: np.tile(np.arange(54), (len(x),1))
    first = PolicyTrickValueBot(predict, evaluator=Evaluator(), worlds=2, candidates=2, seed=23)
    second = PolicyTrickValueBot(predict, evaluator=Evaluator(), worlds=2, candidates=2, seed=23)
    assert first.decide_play(rnd,seat) == second.decide_play(changed,seat)
    assert traces[0] == traces[1]
    assert first.last_decision_record['continuation_work']['plies'] == 12


def test_terminal_afterstate_skips_policy(monkeypatch):
    from types import SimpleNamespace
    terminal = SimpleNamespace(phase='round_end')
    monkeypatch.setattr(module, 'afterstate', lambda *a, **kw: terminal)
    def forbidden(x):
        pytest.fail('terminal state invoked policy')
    bot = PolicyTrickValueBot(forbidden, evaluator=object())
    assert bot._leaf(None, 0, None, None, None, 0) is terminal
    assert bot._continuation_work == {}


def test_sampling_failure_propagates_without_heuristic_fallback(monkeypatch):
    rnd = state(); seat = rnd.turn
    action = HeuristicBot().decide_play(rnd, seat)
    def refused(*args):
        raise RuntimeError('sampling short')
    monkeypatch.setattr(module.PolicyWorldBot, 'decide_play', refused)
    bot = PolicyTrickValueBot(None, evaluator=object())
    with pytest.raises(RuntimeError, match='sampling short'):
        bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)


def test_repeated_candidate_uses_same_continuation_inputs():
    rnd = state(); seat = rnd.turn
    action = HeuristicBot().decide_play(rnd, seat)
    seen = []
    def predict(x):
        seen.append(x.copy())
        return np.tile(np.arange(54), (len(x),1))
    bot = PolicyTrickValueBot(predict, evaluator=object(), seed=37)
    first = bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)
    expected = seen[:]; seen.clear()
    second = bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)
    assert len(expected) == len(seen) == 3
    assert all(np.array_equal(a,b) for a,b in zip(expected,seen))
    assert first.hands == second.hands
