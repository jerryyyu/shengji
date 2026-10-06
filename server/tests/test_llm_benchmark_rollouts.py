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


@pytest.mark.parametrize("cards, message", [
    ([], "You don't hold those cards."),
    (["S5", "S5"], "You don't hold those cards."),
    (["C8"], "You must follow suit."),
    (["NOT_A_CARD"], "You don't hold those cards."),
    (["C4"] * 100, "You don't hold those cards."),
])
def test_invalid_follow_shapes_return_feedback_and_consume_evaluation(cards, message):
    rnd = root()
    tool = DecisionRollouts(rnd, 1, information="perfect", seed=99,
                            max_evaluations=1, invalid_action_feedback=True)
    result = tool.evaluate(cards)
    assert result["status"] == "invalid"
    assert result["cards"] == cards
    assert result["worlds"] == 0
    assert result["error"] == "illegal_action"
    assert result["message"] == message
    assert "mean_attacker_points" not in result
    assert "mean_signed_levels" not in result
    with pytest.raises(ValueError, match="budget exhausted"):
        tool.evaluate(HeuristicBot().decide_play(rnd, 1))


def test_invalid_feedback_is_hidden_twin_invariant_and_does_not_mutate_live_round():
    a = root()
    b = copy.deepcopy(a)
    b.hands[2][0], b.buried[0] = b.buried[0], b.hands[2][0]
    before_a = observation(a, 1, information="actor-only")
    before_b = observation(b, 1, information="actor-only")
    assert before_a == before_b
    results = [DecisionRollouts(rnd, 1, information="actor-only", seed=99,
                                worlds=2, invalid_action_feedback=True).evaluate(["SJ"])
               for rnd in (a, b)]
    assert results[0] == results[1]
    assert results[0]["status"] == "invalid"
    assert observation(a, 1, information="actor-only") == before_a
    assert observation(b, 1, information="actor-only") == before_b


@pytest.mark.parametrize("feedback", [False, True])
def test_malformed_cards_and_unknown_continuation_remain_fatal_without_budget_use(feedback):
    rnd = root()
    cards = HeuristicBot().decide_play(rnd, 1)
    tool = DecisionRollouts(rnd, 1, information="perfect", seed=99,
                            max_evaluations=1, invalid_action_feedback=feedback)
    with pytest.raises(ValueError, match="rollout cards"):
        tool.evaluate(tuple(cards))
    with pytest.raises(ValueError, match="continuation drift"):
        tool.evaluate(cards, continuation="not-a-continuation")
    assert tool.evaluate(cards)["worlds"] == 1


def test_perfect_tool_uses_true_world_and_invalid_follow_refuses():
    rnd = root()
    tool = DecisionRollouts(rnd, 1, information="perfect", seed=99)
    assert tool._worlds == [({s: rnd.hands[s] for s in (0, 2, 3)}, rnd.buried)]
    with pytest.raises(IllegalPlay):
        tool.evaluate([])
    assert tool.evaluate(HeuristicBot().decide_play(rnd, 1))["worlds"] == 1


@pytest.mark.parametrize("feedback", [False, True])
def test_internal_rollout_illegal_play_is_not_treated_as_invalid_candidate(monkeypatch, feedback):
    rnd = root()
    cards = HeuristicBot().decide_play(rnd, 1)

    def fail(*args, **kwargs):
        raise IllegalPlay("internal rollout failure")

    monkeypatch.setattr("shengji.ai.mcbot.MCBot._rollout", fail)
    tool = DecisionRollouts(rnd, 1, information="actor-only", seed=99, worlds=1,
                            invalid_action_feedback=feedback)
    with pytest.raises(IllegalPlay, match="internal rollout failure"):
        tool.evaluate(cards)
    assert tool.last_failure == {"stage": "rollout_continuation",
                                 "error_type": "IllegalPlay", "world_index": 0}


@pytest.mark.parametrize("option", [{}, {"invalid_action_feedback": False}])
def test_default_invalid_candidate_is_fatal_without_spending_budget(option):
    rnd = root()
    tool = DecisionRollouts(rnd, 1, information="perfect", seed=99,
                            max_evaluations=1, **option)
    with pytest.raises(IllegalPlay):
        tool.evaluate([])
    assert tool.last_failure == {"stage": "rollout_validate", "error_type": "IllegalPlay"}
    assert tool.evaluate(HeuristicBot().decide_play(rnd, 1))["worlds"] == 1
    assert tool.last_failure is None


def test_r3_rank_trump_candidate_is_not_a_heart_follow():
    from shengji.engine.cards import Ordering
    from shengji.engine.legal import validate_follow
    ordering = Ordering('S', '8')
    hand = ['C3','C6','C7','C8','C9','CA','CJ','D5','D8','H10','H6',
            'H7','H8','HJ','HK','HQ','S10','S2','S3','S7']
    for card in ['H6', 'H7', 'HJ', 'HQ', 'HK', 'H10']:
        validate_follow([card], hand, ['HA'], ordering)
    with pytest.raises(IllegalPlay, match='must follow suit'):
        validate_follow(['H8'], hand, ['HA'], ordering)


@pytest.mark.parametrize("option", [None, 0, 1, "true"])
def test_feedback_option_rejects_non_boolean_before_world_generation(option):
    with pytest.raises(ValueError, match="invalid_action_feedback must be bool"):
        DecisionRollouts(None, 1, information="perfect", seed=99,
                         invalid_action_feedback=option)


def test_feedback_opt_in_preserves_legal_result_and_world_tape():
    rnd = root()
    cards = HeuristicBot().decide_play(rnd, 1)
    tools = [DecisionRollouts(rnd, 1, information="actor-only", seed=99,
                             worlds=2, invalid_action_feedback=feedback)
             for feedback in (False, True)]
    assert tools[0]._worlds == tools[1]._worlds
    assert tools[0].evaluate(cards) == tools[1].evaluate(cards)
