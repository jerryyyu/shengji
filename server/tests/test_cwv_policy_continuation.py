import copy
import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_policy_continuation import PriorRolloutPolicy, CWVPolicyContinuationBot
from shengji.train.cwv_truncated_search import CWVPriorTruncatedSearchBot
from shengji.train.cwv_truncated_value import continuation_values
from test_cwv_bounded_puct import root
from test_cwv_truncated_value import Evaluator


def test_prior_chooser_uses_acting_seat_legal_argmax_without_mutation():
    rnd = root()
    before = copy.deepcopy(rnd)
    actions = enumerate_legal(rnd, rnd.turn, cap=None).actions
    def scores(world, mover, legal):
        assert world is rnd and mover == rnd.turn
        return np.arange(len(legal))
    policy = PriorRolloutPolicy(scores, fallback=HeuristicBot())
    assert policy.decide_play(rnd, rnd.turn) == list(actions[-1])
    assert rnd.hands == before.hands and rnd.history == before.history


def test_chooser_refuses_live_state_and_wrong_actor():
    rnd = root()
    policy = PriorRolloutPolicy(lambda *a: [], fallback=HeuristicBot())
    with pytest.raises(ValueError, match='acting seat'):
        policy.decide_play(rnd, (rnd.turn + 1) % 4)
    rnd._determinized_world = False
    with pytest.raises(ValueError, match='private sampled'):
        policy.decide_play(rnd, rnd.turn)


def test_zero_guidance_reproduces_heuristic_full_continuation():
    rnd = root()
    def never(*args):
        raise AssertionError('zero guidance must not evaluate a prior')
    guide = PriorRolloutPolicy(never, fallback=HeuristicBot(), stop_trick=len(rnd.history))
    kwargs = dict(evaluator=Evaluator(), tricks=None)
    control = continuation_values([rnd], [rnd.turn], [len(rnd.history)], **kwargs)
    guided = continuation_values([rnd], [rnd.turn], [len(rnd.history)], policy=guide, **kwargs)
    np.testing.assert_array_equal(control.values, guided.values)
    assert guide.counts['guided_plies'] == 0
    assert guide.counts['fallback_plies'] > 0


def test_guidance_stops_at_root_relative_trick_boundary():
    rnd = root()
    stop = len(rnd.history) + 1
    calls = []
    def scores(world, mover, actions):
        assert len(world.history) < stop
        calls.append(mover)
        return np.zeros(len(actions))
    guide = PriorRolloutPolicy(scores, fallback=HeuristicBot(), stop_trick=stop)
    out = continuation_values([rnd], [rnd.turn], [len(rnd.history)],
                              evaluator=Evaluator(), tricks=None, policy=guide)
    assert guide.counts['guided_plies'] > 0
    assert guide.counts['fallback_plies'] > 0
    assert out.terminal_rows == 1


def test_full_guidance_reaches_terminal_without_heuristic_fallback():
    rnd = root()
    class NoFallback:
        def decide_play(self, *args):
            raise AssertionError('full guidance must never use the heuristic')
    guide = PriorRolloutPolicy(lambda world, mover, actions: np.zeros(len(actions)),
                              fallback=NoFallback(), stop_trick=None)
    out = continuation_values([rnd], [rnd.turn], [len(rnd.history)],
                              evaluator=Evaluator(), tricks=None, policy=guide)
    assert out.terminal_rows == 1
    assert guide.counts['guided_plies'] > 4
    assert guide.counts['fallback_plies'] == 0


def test_transient_guide_restored_even_on_continuation_failure(monkeypatch):
    rnd = root()
    bot = object.__new__(CWVPolicyContinuationBot)
    original = HeuristicBot()
    bot.rollout_policy = original
    bot.guided_tricks = 1
    bot.policy_continuation_totals = dict(guided_plies=0, fallback_plies=0,
                                         prior_calls=0, legal_actions=0)
    def fail(self, *args):
        assert isinstance(self.rollout_policy, PriorRolloutPolicy)
        self.rollout_policy.counts['guided_plies'] = 2
        raise RuntimeError('intentional failure')
    monkeypatch.setattr(CWVPriorTruncatedSearchBot, '_continuation_matrix', fail)
    with pytest.raises(RuntimeError, match='intentional'):
        bot._continuation_matrix(rnd, rnd.turn, [], None, 1)
    assert bot.rollout_policy is original
    assert bot.policy_continuation_totals['guided_plies'] == 2
