import copy

import numpy as np
import pytest

from shengji.train.policy_lookahead import PolicyLookaheadBot
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state


@pytest.mark.parametrize('kwargs', [{'extra_plies': 0}, {'extra_plies': 5},
                                   {'extra_plies': True}, {'continuation_worlds': 5}])
def test_bounds(kwargs):
    with pytest.raises(ValueError):
        PolicyLookaheadBot(None, evaluator=object(), **kwargs)


def test_terminal_leaf_never_calls_continuation(monkeypatch):
    from types import SimpleNamespace
    terminal = SimpleNamespace(phase='round_end')
    monkeypatch.setattr(PolicyValueBot, '_leaf', lambda *a: terminal)
    def forbidden(x):
        raise AssertionError('terminal continuation must not invoke policy')
    bot = PolicyLookaheadBot(forbidden, evaluator=object())
    assert bot._leaf(None, 0, None, None, None, 0) is terminal
    assert bot._continuation_work == {}


def test_real_continuation_preserves_hidden_information_and_original_state():
    rnd = state()
    seat = rnd.turn
    changed = copy.deepcopy(rnd)
    other = [s for s in range(4) if s != seat]
    changed.hands[other[0]], changed.hands[other[1]] = (
        changed.hands[other[1]], changed.hands[other[0]])
    class Evaluator:
        def __init__(self):
            self.leaves = []
        def score(self, leaves, root):
            assert root == seat
            self.leaves.extend(copy.deepcopy(leaves))
            return np.arange(len(leaves), dtype=float)
    inputs = []
    def predict(x):
        inputs.append(x.copy())
        return np.tile(np.arange(54), (len(x), 1))
    first_eval, second_eval = Evaluator(), Evaluator()
    first = PolicyLookaheadBot(predict, evaluator=first_eval, worlds=2, candidates=2, seed=21)
    second = PolicyLookaheadBot(predict, evaluator=second_eval, worlds=2, candidates=2, seed=21)
    before = copy.deepcopy(rnd.hands)
    action = first.decide_play(rnd, seat)
    expected_inputs = inputs[:]
    inputs.clear()
    assert second.decide_play(changed, seat) == action
    assert len(inputs) == len(expected_inputs)
    assert all(np.array_equal(a, b) for a, b in zip(inputs, expected_inputs))
    assert rnd.hands == before
    assert first.last_decision_record['continuation_work']['plies'] == 16
    assert first.last_decision_record['continuation_work']['worlds'] == 16
    assert all(len(leaf.history) == len(rnd.history) + 2 for leaf in first_eval.leaves)
    assert [r.hands for r in first_eval.leaves] == [r.hands for r in second_eval.leaves]


@pytest.mark.parametrize('mutation', ['root_hand', 'kitty'])
def test_continuation_actor_does_not_see_root_world_hidden_cards(monkeypatch, mutation):
    """Root privacy alone cannot detect privileged information at later actors."""
    from shengji.ai.heuristic import HeuristicBot
    leaf = state()
    root = leaf.turn
    leaf.play(root, HeuristicBot().decide_play(leaf, root))
    actor = leaf.turn
    assert actor != root and actor != leaf.banker
    changed = copy.deepcopy(leaf)
    if mutation == 'root_hand':
        other = next(s for s in range(4) if s not in (actor, root))
        changed.hands[root][-1], changed.hands[other][-1] = (
            changed.hands[other][-1], changed.hands[root][-1])
    else:
        changed.buried[0], changed.hands[root][-1] = (
            changed.hands[root][-1], changed.buried[0])
    assert changed.hands[root] != leaf.hands[root]
    assert changed.hands[actor] == leaf.hands[actor]
    # Inject the two counterfactuals at the continuation boundary. The outer
    # root's supplied hands/kitty are deliberately absent; only the actor's
    # information may determine the policy input and submitted action.
    monkeypatch.setattr(PolicyValueBot, '_leaf',
                        lambda self, rnd, *args: copy.deepcopy(rnd))
    observed = []
    def predict(x):
        observed.append(x.copy())
        return np.tile(np.arange(54), (len(x), 1))
    actions = []
    from shengji.train.policy_world_search import PolicyWorldBot
    original = PolicyWorldBot.decide_play
    def capture(self, rnd, seat):
        assert seat == actor
        cards = original(self, rnd, seat)
        actions.append(cards)
        return cards
    monkeypatch.setattr(PolicyWorldBot, 'decide_play', capture)
    bot = PolicyLookaheadBot(predict, evaluator=object(), extra_plies=1, seed=29)
    bot._leaf(leaf, root, None, None, None, 0)
    bot._leaf(changed, root, None, None, None, 0)
    assert len(observed) == 2
    assert np.array_equal(observed[0], observed[1])
    assert actions[0] == actions[1]
