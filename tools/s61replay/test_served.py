from copy import deepcopy
from types import SimpleNamespace
import random
import pytest
from served import endpoint_evaluator, reply_factory
from continuation import compare_continuations
from test_capture import make_bot
from test_continuation import fixture


def test_bound_search_replies_reach_independent_endpoint():
    root, actions = fixture()
    assert root.turn == 2
    seats = []
    class Evaluator:
        def score(self, positions, root_seat):
            seats.append(root_seat)
            assert len(positions[0].history) == 2
            return [float(root_seat)]
    def make(seed):
        bot = make_bot()
        bot.sampler.rng = random.Random(seed)
        return bot
    result = compare_continuations([root], [1.], actions, tricks=2,
        reply_factory=reply_factory(make),
        evaluate=endpoint_evaluator(SimpleNamespace(evaluator=Evaluator())), seed=5,
        reply_identity='served-search-test', evaluator_identity='seat-sensitive-test',
        served_ballot=actions)
    assert seats == [root.turn] * 2
    assert all(a['weighted_value'] == root.turn for a in result['actions'])
    assert len(root.history) == 0


def test_endpoint_preserves_seat_two_and_three():
    seen = []
    class Evaluator:
        def score(self, positions, root_seat):
            seen.append(root_seat)
            return [root_seat]
    evaluate = endpoint_evaluator(SimpleNamespace(evaluator=Evaluator()))
    assert evaluate(None, 2) == 2 and evaluate(None, 3) == 3
    assert seen == [2, 3]


def test_reply_refuses_fallback():
    root, _ = fixture()
    bot = SimpleNamespace(decide_play=lambda *a: ['D4'],
                          last_decision_record={'schema':'pv-search-decision-v1', 'work_complete':False})
    reply = reply_factory(lambda **kwargs: bot)(random.Random(1))
    with pytest.raises(ValueError, match='complete served'):
        reply(deepcopy(root), root.turn)
