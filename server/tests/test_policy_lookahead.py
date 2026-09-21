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


@pytest.mark.parametrize('continuation', ['policy', 'heuristic'])
def test_real_continuation_preserves_hidden_information_and_original_state(continuation):
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
    kw = dict(continuation_policy=continuation,
              continuation_worlds=1 if continuation == 'policy' else 0)
    first = PolicyLookaheadBot(predict, evaluator=first_eval, worlds=2, candidates=2, seed=21, **kw)
    second = PolicyLookaheadBot(predict, evaluator=second_eval, worlds=2, candidates=2, seed=21, **kw)
    before = copy.deepcopy(rnd.hands)
    action = first.decide_play(rnd, seat)
    expected_inputs = inputs[:]
    inputs.clear()
    assert second.decide_play(changed, seat) == action
    assert len(inputs) == len(expected_inputs)
    assert all(np.array_equal(a, b) for a, b in zip(inputs, expected_inputs))
    assert rnd.hands == before
    assert first.last_decision_record['continuation_work']['plies'] == 16
    assert first.last_decision_record['continuation_work']['worlds'] == (16 if continuation == 'policy' else 0)
    assert all(len(leaf.history) == len(rnd.history) + 2 for leaf in first_eval.leaves)
    assert [r.hands for r in first_eval.leaves] == [r.hands for r in second_eval.leaves]


@pytest.mark.parametrize('kwargs', [dict(continuation_policy='other'),
    dict(continuation_policy='heuristic'),
    dict(continuation_policy='heuristic', continuation_worlds=False)])
def test_continuation_recipe_refuses_unused_or_invalid_worlds(kwargs):
    with pytest.raises(ValueError):
        PolicyLookaheadBot(None, evaluator=object(), **kwargs)


def test_heuristic_leaf_uses_no_policy_inference_and_exactly_one_extra_trick():
    from shengji.ai.heuristic import HeuristicBot
    rnd = state(); seat = rnd.turn
    def forbidden(_):
        raise AssertionError('heuristic continuation must not call policy head')
    bot = PolicyLookaheadBot(forbidden, evaluator=object(), continuation_policy='heuristic',
                             continuation_worlds=0)
    action = HeuristicBot().decide_play(rnd, seat)
    expected = PolicyValueBot(None, evaluator=object())._leaf(
        rnd, seat, rnd.hands, rnd.buried, action, 0)
    for _ in range(4):
        if expected.phase != 'play':
            break
        actor = expected.turn
        expected.play(actor, HeuristicBot().decide_play(expected, actor))
    actual = bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)
    assert actual.hands == expected.hands and actual.attacker_points == expected.attacker_points
    assert len(actual.history) == len(rnd.history)+2
    assert bot._continuation_work == dict(plies=4, worlds=0, sample_attempts=0, capped_decisions=0)


def test_each_heuristic_actor_reads_only_its_own_hand(monkeypatch):
    """Guard decision-time access, not engine validation of the returned action."""
    from shengji.ai.heuristic import HeuristicBot
    rnd = state(); seat = rnd.turn
    original = HeuristicBot.decide_play
    actors = []
    class OwnHandOnly:
        def __init__(self, hands, actor):
            self.hands, self.actor = hands, actor
        def __getitem__(self, key):
            assert type(key) is int and key == self.actor, 'read another player hand'
            return self.hands[key]
        def __iter__(self):
            raise AssertionError('iterated hidden hands')
    def guarded(bot, leaf, actor):
        hands = leaf.hands
        leaf.hands = OwnHandOnly(hands, actor)
        try:
            result = original(bot, leaf, actor)
            actors.append(actor)
            return result
        finally:
            leaf.hands = hands
    action = original(HeuristicBot(), rnd, seat)
    monkeypatch.setattr(HeuristicBot, 'decide_play', guarded)
    bot = PolicyLookaheadBot(None, evaluator=object(), continuation_policy='heuristic',
                             continuation_worlds=0)
    bot._leaf(rnd, seat, rnd.hands, rnd.buried, action, 0)
    assert len(actors) == 7  # three current-trick replies and four extra-trick plays
    assert set(actors) == {0, 1, 2, 3}
