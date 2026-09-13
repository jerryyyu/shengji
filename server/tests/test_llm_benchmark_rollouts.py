import copy
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.legal import IllegalPlay
from shengji.engine.round import Round
from shengji.luna.benchmark_observation import observation
from shengji.luna.benchmark_rollouts import DecisionRollouts


def root():
    rnd = Round("7", 0, random.Random(711))
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(0, HeuristicBot().decide_bury(rnd, 0))
    rnd.play(0, [rnd.hands[0][0]])
    return rnd


@pytest.mark.parametrize("continuation", ["heuristic-all", "smart-all", "team-smart", "opponent-smart", "exact-endgame-smart"])
def test_public_tool_results_are_hidden_twin_invariant_and_do_not_mutate_live_round(continuation):
    a = root()
    b = copy.deepcopy(a)
    b.hands[2][0], b.buried[0] = b.buried[0], b.hands[2][0]
    before = observation(a, 1, information="perfect")
    cards = HeuristicBot().decide_play(a, 1)
    results = [DecisionRollouts(rnd, 1, information="actor-only", seed=99, worlds=2)
               .evaluate(cards, continuation=continuation) for rnd in (a, b)]
    assert results[0] == results[1]
    assert results[0]["worlds"] == 2
    assert observation(a, 1, information="perfect") == before


def test_worlds_reused_and_budget_enforced():
    rnd = root()
    tool = DecisionRollouts(rnd, 1, information="actor-only", seed=99,
                            worlds=2, max_evaluations=2)
    cards = HeuristicBot().decide_play(rnd, 1)
    assert tool.evaluate(cards) == tool.evaluate(cards)
    with pytest.raises(ValueError, match="budget exhausted"):
        tool.evaluate(cards)


def test_perfect_tool_uses_true_world_and_invalid_follow_refuses():
    rnd = root()
    tool = DecisionRollouts(rnd, 1, information="perfect", seed=99)
    assert tool._worlds == [({s: rnd.hands[s] for s in (0, 2, 3)}, rnd.buried)]
    with pytest.raises(IllegalPlay):
        tool.evaluate([])
    assert tool.evaluate(HeuristicBot().decide_play(rnd, 1))["worlds"] == 1
