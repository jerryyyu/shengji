import copy

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.teacher_v1 import attacker_level_utility
from shengji.train.mc_policy_value_cutoff import MCPolicyValueCutoff
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state


class RecordingValue:
    def __init__(self, value=1.25):
        self.value = value
        self.calls = []

    def score(self, positions, seat):
        self.calls.append((copy.deepcopy(positions[0]), seat))
        return np.full(len(positions), self.value, dtype=float)


def continuation(value=None):
    evaluator = RecordingValue(0.0 if value is None else value)
    bot = PolicyValueBot(
        lambda x: np.zeros((len(x), 54)), evaluator=evaluator,
        worlds=1, candidates=1)
    return bot, evaluator


def make_bot(*, evaluator=None, cutoff_tricks=1, learned=True):
    cont, _ = continuation()
    return MCPolicyValueCutoff(
        cont, evaluator=evaluator or RecordingValue(), seed=7,
        cutoff_tricks=cutoff_tricks, learned_continuation=learned)


@pytest.mark.parametrize("value", [True, False, 0, 65, 1.0])
def test_cutoff_validation(value):
    with pytest.raises(ValueError):
        make_bot(cutoff_tricks=value)


def test_constructor_keeps_matched_root_settings_and_level_knobs():
    bot = make_bot()
    assert (bot.N_DETERMINIZATIONS, bot.REPORT_FOLD_WORLDS,
            bot.REPORT_RULE, bot.EXACT_ENDGAME) == (30, 300, "lcb", False)
    assert bot.POINT_SHY_EPS == bot.MARGIN == 0
    assert bot.LEAD_MARGIN is None


def test_leaf_value_converts_root_team_to_attacker_perspective():
    rnd = state()
    evaluator = RecordingValue(2.0)
    bot = make_bot(evaluator=evaluator)
    attacker = next(seat for seat in range(4) if rnd.is_attacker(seat))
    defender = next(seat for seat in range(4) if not rnd.is_attacker(seat))
    assert bot._value_leaf(rnd, attacker) == 2.0
    assert bot._value_leaf(rnd, defender) == -2.0


@pytest.mark.parametrize("scores", [np.array([np.nan]), np.array([1.0, 2.0]),
                                     np.array(1.0)])
def test_leaf_evaluator_requires_one_finite_score(scores):
    class Bad:
        def score(self, positions, seat):
            return scores
    with pytest.raises(ValueError, match="one finite"):
        make_bot(evaluator=Bad())._value_leaf(state(), 0)


def test_cutoff_evaluates_after_one_completed_trick_and_preserves_live_round():
    rnd = state()
    before = copy.deepcopy({k: v for k, v in rnd.__dict__.items()
                            if k != "ordering"})
    seat = rnd.turn
    candidate = HeuristicBot().decide_play(rnd, seat)
    sampled = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
    evaluator = RecordingValue(1.25)
    bot = make_bot(evaluator=evaluator)
    expected = 1.25 if rnd.is_attacker(seat) else -1.25
    assert bot._rollout(rnd, seat, sampled, list(rnd.buried), candidate) == expected
    leaf, root_seat = evaluator.calls[0]
    assert leaf.phase == "play" and len(leaf.history) == len(rnd.history) + 1
    assert root_seat == seat
    assert {k: v for k, v in rnd.__dict__.items() if k != "ordering"} == before
    assert bot.leaf_rollouts == {
        "started": 1, "completed": 1, "predicted": 1,
        "terminal": 0, "continuation_plies": 3,
    }


def test_terminal_utility_is_attacker_level_and_bypasses_evaluator():
    class NoCall:
        def score(self, positions, seat):
            raise AssertionError("terminal leaves must not call CWV")
    bot = make_bot(evaluator=NoCall(), cutoff_tricks=None, learned=False)
    value = bot._terminal(type("Leaf", (), {"attacker_points": 80})())
    assert value == attacker_level_utility(80) == 0.5


def test_terminal_takes_precedence_when_horizon_is_final_trick():
    class NoCall:
        def score(self, positions, seat):
            raise AssertionError("terminal leaves must not call CWV")
    rnd = state()
    heuristic = HeuristicBot()
    while rnd.phase == "play" and len(rnd.hands[rnd.turn]) > 1:
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    seat = rnd.turn
    candidate = heuristic.decide_play(rnd, seat)
    sampled = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
    bot = make_bot(evaluator=NoCall(), learned=False, cutoff_tricks=1)
    bot._rollout(rnd, seat, sampled, list(rnd.buried), candidate)
    assert bot.leaf_rollouts["terminal"] == 1
    assert bot.leaf_rollouts["predicted"] == 0


def test_failed_leaf_score_retains_completed_continuation_plies():
    class Refused:
        def score(self, positions, seat):
            raise RuntimeError("score refused")
    rnd = state()
    seat = rnd.turn
    candidate = HeuristicBot().decide_play(rnd, seat)
    sampled = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
    bot = make_bot(evaluator=Refused(), learned=False)
    with pytest.raises(RuntimeError, match="score refused"):
        bot._rollout(rnd, seat, sampled, list(rnd.buried), candidate)
    assert bot.leaf_rollouts == {
        "started": 1, "completed": 0, "predicted": 0,
        "terminal": 0, "continuation_plies": 3,
    }
