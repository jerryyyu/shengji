import copy

import pytest

from shengji.luna.benchmark_policy import SeatPlannerPolicy
from test_llm_benchmark_observation import state


@pytest.mark.parametrize("pair,illegal", [(False, False), (True, False), (False, True)])
def test_lead_requirement_comes_from_first_engine_play_not_same_cards_across_seats(pair, illegal):
    from shengji.luna.benchmark_observation import observation
    from shengji.engine.legal import IllegalPlay
    rnd = state()
    # The saved Luna failure confused CK from seat1 and CK from seat2 as a
    # pair lead. Build those plays through the engine, plus a real pair control.
    rnd.hands = [["C4", "C4", "CQ"],
                 ["CK", "CK", "C3"] if pair else ["CK", "C3", "C5"],
                 ["C8", "C8", "C6"] if pair else ["CK", "C6", "C8"],
                 ["D10", "D9", "D8"]]
    rnd.play(1, ["CK", "CK"] if pair else ["CK"])
    rnd.play(2, ["C8", "C8"] if pair else ["CK"])
    rnd.play(3, ["D10", "D9"] if pair else ["D10"])
    before = observation(rnd, 0, information="actor-only")
    received = []
    def planner(packet):
        received.append(packet)
        return {"cards": ["C4", "C4"] if pair or illegal else ["C4"], "memory": ""}
    cards = policy(0, planner).decide_play(rnd, 0)
    if illegal:
        assert cards == ["C4", "C4"]  # no silent correction or fallback
        with pytest.raises(IllegalPlay, match=r"^Must play exactly 1 card\(s\)\.$"):
            rnd.play(0, cards)
        assert len(received) == 1  # no retry
    else:
        rnd.play(0, cards)
    assert received[0]["observation"] == before
    assert received[0]["play_requirement"] == {
        "is_leading": False, "lead_seat": 1,
        "lead_cards": ["CK", "CK"] if pair else ["CK"],
        "required_card_count": 2 if pair else 1}


def policy(seat, planner, information="actor-only"):
    return SeatPlannerPolicy(seat=seat, information=information,
                             planner=planner, setup_policy=None)


def test_engine_consumes_planner_cards_and_context_stays_seat_private():
    rnd = state()
    received = []
    def planner(packet):
        received.append(copy.deepcopy(packet))
        return {"cards": [packet["observation"]["own_hand"][0]],
                "memory": "private reasoning"}
    a, b = policy(1, planner), policy(2, planner)
    cards = a.decide_play(rnd, 1)
    rnd.play(1, cards)
    assert rnd.trick.plays[-1].cards == cards
    b.decide_play(rnd, 2)
    assert [p["memory"] for p in received] == ["", ""]
    assert all("hands_by_seat" not in p["observation"] for p in received)
    # Same seat gets its own memory; a fresh round never inherits it.
    rnd.turn = 1
    a.decide_play(rnd, 1)
    assert received[-1]["memory"] == "private reasoning"
    a.decide_play(state(), 1)
    assert received[-1]["memory"] == ""


def test_hidden_twins_are_identical_at_planner_callback():
    received = []
    def planner(packet):
        received.append(packet)
        return {"cards": ["C3"], "memory": ""}
    a, b = state(), state()
    b.hands[2][0], b.buried[0] = b.buried[0], b.hands[2][0]
    for rnd in (a, b):
        policy(1, planner).decide_play(rnd, 1)
    assert received[0] == received[1]
    assert received[0]["suggested_actions"]
    assert received[0]["play_requirement"] == {
        "is_leading": True, "lead_seat": None, "lead_cards": [],
        "required_card_count": None}
    from shengji.luna.game import WideHeuristicBallotBot
    assert received[0]["suggested_actions"] == [
        sorted(cards) for cards in WideHeuristicBallotBot(seed=0)._candidates(a, 1)]


def test_wrong_seat_and_bad_reply_do_not_fallback():
    calls = []
    def planner(packet):
        calls.append(packet)
        return {"cards": ["BJ"], "memory": "bad"}
    bot = policy(1, planner)
    with pytest.raises(ValueError, match="different seat"):
        bot.decide_play(state(), 2)
    assert not calls
    with pytest.raises(ValueError, match="invalid planner"):
        bot.decide_play(state(), 1)
    assert bot._memory == ""


def test_actual_tool_result_reaches_planner_then_engine():
    from test_llm_benchmark_rollouts import root
    from shengji.ai.heuristic import HeuristicBot
    rnd = root()
    cards = HeuristicBot().decide_play(rnd, 1)
    received = []
    def planner(packet):
        received.append(packet)
        if not packet["rollout_results"]:
            return {"evaluations": [{"cards": cards, "continuation": "heuristic-all"}],
                    "memory": "compare before committing"}
        assert packet["rollout_results"][0]["worlds"] == 2
        assert packet["memory"] == "compare before committing"
        return {"cards": cards, "memory": "selected after rollout"}
    bot = SeatPlannerPolicy(seat=1, information="actor-only", planner=planner,
                            setup_policy=None, worlds=2)
    rnd.play(1, bot.decide_play(rnd, 1))
    assert len(received) == 2
    assert rnd.trick.plays[-1].cards == cards


def test_rollout_call_limit_is_enforced_at_planner_wiring():
    from test_llm_benchmark_rollouts import root
    from shengji.ai.heuristic import HeuristicBot
    rnd = root()
    cards = HeuristicBot().decide_play(rnd, 1)
    calls = []
    def planner(packet):
        calls.append(packet)
        return {"evaluations": [{"cards": cards, "continuation": "heuristic-all"}],
                "memory": "again"}
    bot = SeatPlannerPolicy(seat=1, information="actor-only", planner=planner,
                            setup_policy=None, worlds=1)
    with pytest.raises(ValueError, match="call budget exhausted"):
        bot.decide_play(rnd, 1)
    assert len(calls) == 3
    assert [packet["rollout_calls_remaining"] for packet in calls] == [2, 1, 0]
    assert rnd.turn == 1


def test_existing_full_round_runner_accepts_json_only_planners():
    import random
    from types import SimpleNamespace
    from shengji.ai.env import play_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.cards import Ordering
    from shengji.engine.game import Game
    calls = []
    def planner(packet):
        visible = packet["observation"]
        calls.append(visible["seat"])
        # A scripted planner reconstructs only its own cards and the public
        # trick. No closure over the engine's Round or opponents' hands.
        hands = [[] for _ in range(4)]
        hands[visible["seat"]] = visible["own_hand"]
        trick = visible["current_trick"]
        public = SimpleNamespace(
            hands=hands, trump_rank=visible["trump_rank"],
            ordering=Ordering(visible["trump_suit"], visible["trump_rank"]),
            trick=SimpleNamespace(leader=trick["leader"],
                                  plays=[SimpleNamespace(**p) for p in trick["plays"]]))
        return {"cards": HeuristicBot().decide_play(public, visible["seat"]),
                "memory": ""}
    bots = [SeatPlannerPolicy(seat=s, information="actor-only", planner=planner,
                              setup_policy=HeuristicBot()) for s in range(4)]
    result = play_round(Game(random.Random(733)), bots, record=True)
    assert set(calls) == set(range(4))
    assert len(calls) == len(result.history)
    assert sum(len(cards) for seat, cards in result.history) == 100
    assert result.winner_team in (0, 1)
