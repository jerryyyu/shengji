"""Final-action corrections must stay inside one bounded, private decision."""
import copy
import random

import pytest

from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.legal import IllegalPlay
from shengji.luna.benchmark_games import play_mirror
from shengji.luna.benchmark_policy import SeatPlannerPolicy
from test_llm_benchmark_games import planner as legal_planner
from test_llm_benchmark_observation import state


def follow_root():
    rnd = state()
    rnd.hands = [["C4", "C4", "CQ"], ["CK", "C3", "C5"],
                 ["CK", "C6", "C8"], ["D10", "D9", "D8"]]
    for seat, cards in [(1, ["CK"]), (2, ["CK"]), (3, ["D10"])]:
        rnd.play(seat, cards)
    return rnd


def bot(planner, **kwargs):
    return SeatPlannerPolicy(seat=0, information="actor-only", planner=planner,
                             setup_policy=None, **kwargs)


@pytest.mark.parametrize("classify", [False, True])
def test_final_follow_corrected_without_mutating_round(classify):
    rnd = follow_root()
    before = copy.deepcopy(rnd.__dict__)
    packets = []
    def choose(packet):
        packets.append(copy.deepcopy(packet))
        return {"cards": ["C4", "C4"] if len(packets) == 1 else ["C4"],
                "memory": "own memory"}
    policy = bot(choose, invalid_action_feedback=True,
                 classify_final_action_failures=classify)
    cards = policy.decide_play(rnd, 0)
    assert cards == ["C4"] and len(packets) == 2
    assert packets[0]["observation"] == packets[1]["observation"]
    assert packets[1]["memory"] == "own memory"
    assert packets[1]["final_action_errors"][0]["message"] == "Must play exactly 1 card(s)."
    assert rnd.hands == before["hands"] and rnd.trick == before["trick"]
    assert len(policy.final_action_feedback) == 1
    rnd.play(0, cards)


def test_feedback_off_still_returns_illegal_final_once():
    packets = []
    def choose(packet):
        packets.append(packet)
        return {"cards": ["C4", "C4"], "memory": ""}
    rnd = follow_root()
    cards = bot(choose).decide_play(rnd, 0)
    with pytest.raises(IllegalPlay):
        rnd.play(0, cards)
    assert len(packets) == 1 and "final_action_errors" not in packets[0]


def test_repeated_illegal_final_exhausts_without_fallback():
    packets = []
    def choose(packet):
        packets.append(packet)
        return {"cards": [], "memory": ""}
    policy = bot(choose, invalid_action_feedback=True)
    with pytest.raises(IllegalPlay):
        policy.decide_play(follow_root(), 0)
    assert len(packets) == 3
    assert len(policy.final_action_feedback) == 3


def test_tool_budget_and_instance_survive_final_correction(monkeypatch):
    import shengji.luna.benchmark_policy as module
    instances = []
    class Tool:
        def __init__(self, *args, **kwargs):
            instances.append(self)
        def evaluate(self, **kwargs):
            return dict(kwargs, worlds=1, mean_signed_levels=0)
    monkeypatch.setattr(module, "DecisionRollouts", Tool)
    packets = []
    def choose(packet):
        packets.append(copy.deepcopy(packet))
        if len(packets) in (1, 3):
            return {"evaluations": [{"cards": ["C4"], "continuation": "heuristic-all"}], "memory": ""}
        return {"cards": ["C4", "C4"] if len(packets) == 2 else ["C4"], "memory": ""}
    policy = bot(choose, invalid_action_feedback=True)
    assert policy.decide_play(follow_root(), 0) == ["C4"]
    assert len(instances) == 1
    assert [p["rollout_calls_remaining"] for p in packets] == [2, 1, 1, 0]
    assert len(packets[-1]["rollout_results"]) == 2
    assert policy.rollout_usage["requested_batches"] == 2


def test_hidden_twins_get_identical_legality_feedback():
    all_packets = []
    for hidden_card in ("S3", "H3"):
        rnd = follow_root()
        rnd.hands[1][0] = hidden_card
        packets = []
        def choose(packet):
            packets.append(copy.deepcopy(packet))
            return {"cards": [] if len(packets) == 1 else ["C4"], "memory": ""}
        bot(choose, invalid_action_feedback=True).decide_play(rnd, 0)
        all_packets.append(packets)
    assert all_packets[0] == all_packets[1]


def test_malformed_reply_is_not_retried():
    calls = []
    def choose(packet):
        calls.append(packet)
        return {"cards": "C4", "memory": ""}
    with pytest.raises(ValueError):
        bot(choose, invalid_action_feedback=True).decide_play(follow_root(), 0)
    assert len(calls) == 1


def test_internal_validator_fault_is_not_model_feedback(monkeypatch):
    import shengji.luna.benchmark_policy as module
    calls = []
    def choose(packet):
        calls.append(packet)
        return {"cards": ["C4"], "memory": ""}
    def broken_validator(*args, **kwargs):
        raise RuntimeError("internal validator fault")
    monkeypatch.setattr(module, "validate_follow", broken_validator)
    policy = bot(choose, invalid_action_feedback=True)
    with pytest.raises(RuntimeError, match="internal validator fault"):
        policy.decide_play(follow_root(), 0)
    assert len(calls) == 1
    assert policy.final_action_feedback == []


def test_legal_throw_is_not_corrected_using_hidden_opponent_cards():
    rnd = state()
    rnd.hands[1] = ["C3", "C5"]
    rnd.hands[2] = ["CA", "C6"]
    packets = []
    def choose(packet):
        packets.append(packet)
        return {"cards": ["C3", "C5"], "memory": ""}
    policy = SeatPlannerPolicy(seat=1, information="actor-only", planner=choose,
                               setup_policy=None, invalid_action_feedback=True)
    cards = policy.decide_play(rnd, 1)
    assert cards == ["C3", "C5"] and len(packets) == 1
    assert policy.final_action_feedback == []
    rnd.play(1, cards)
    assert len(rnd.trick.plays[-1].cards) == 1  # engine resolves the failed throw


def test_no_third_rollout_batch_after_final_correction(monkeypatch):
    import shengji.luna.benchmark_policy as module
    class Tool:
        def __init__(self, *args, **kwargs):
            pass
        def evaluate(self, **kwargs):
            return dict(kwargs, worlds=1)
    monkeypatch.setattr(module, "DecisionRollouts", Tool)
    calls = []
    def choose(packet):
        calls.append(packet)
        if len(calls) == 2:
            return {"cards": [], "memory": ""}
        return {"evaluations": [{"cards": ["C4"], "continuation": "heuristic-all"}], "memory": ""}
    policy = bot(choose, invalid_action_feedback=True)
    with pytest.raises(ValueError, match="rollout call budget exhausted"):
        policy.decide_play(follow_root(), 0)
    assert len(calls) == 4 and policy.rollout_usage["requested_batches"] == 2


@pytest.mark.parametrize("exhaust", [False, True])
def test_mirror_retains_invalid_final_and_all_call_receipts(exhaust):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    class Planner:
        def __init__(self):
            self.calls = []
        def __call__(self, packet):
            self.calls.append({"ordinal": len(self.calls), "tokens": 7})
            if exhaust or len(self.calls) == 1:
                return {"cards": [], "memory": ""}
            return legal_planner(packet)
    row = play_mirror(game, flip=0, information="actor-only",
                      planner_factory=lambda seat: Planner(),
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733,
                      invalid_action_feedback=True)
    assert row["complete"] is not exhaust
    assert len(row["final_action_feedback"]) == (3 if exhaust else 2)
    assert all(c["tokens"] == 7 for c in row["calls"])
    if exhaust:
        assert len(row["calls"]) == 3 and "signed_levels" not in row
    else:
        assert len(row["calls"]) > len(row["final_action_feedback"])
