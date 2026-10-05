import copy
import random
from types import SimpleNamespace

import pytest

from shengji.ai.env import play_round, prepare_round, play_prepared_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.luna.benchmark_games import play_mirror


def planner(packet):
    v = packet["observation"]
    hands = [[] for _ in range(4)]
    hands[v["seat"]] = v["own_hand"]
    public = SimpleNamespace(
        hands=hands, trump_rank=v["trump_rank"],
        ordering=Ordering(v["trump_suit"], v["trump_rank"]),
        trick=SimpleNamespace(leader=v["current_trick"]["leader"],
                              plays=[SimpleNamespace(**p) for p in v["current_trick"]["plays"]]))
    return {"cards": HeuristicBot().decide_play(public, v["seat"]), "memory": ""}


def test_prepare_continue_is_identical_to_original_round_interface():
    whole = play_round(Game(random.Random(733)), [HeuristicBot() for _ in range(4)], record=True)
    game = Game(random.Random(733))
    policies = [HeuristicBot() for _ in range(4)]
    prepare_round(game, policies)
    split = play_prepared_round(game, policies, record=True)
    assert split == whole


def test_mirrors_reuse_root_and_signed_scores_cancel_for_identical_players():
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    hands = copy.deepcopy(game.round.hands)
    rows = [play_mirror(game, flip=flip, information="actor-only",
                        planner_factory=lambda seat: planner,
                        baseline_factory=lambda seat, seed: HeuristicBot(), seed=733)
            for flip in (0, 1)]
    assert all(r["complete"] for r in rows)
    assert all(r["invalid_action_feedback"] is False for r in rows)
    assert all(r["rollout_usage"] == {"requested_batches": 0, "attempted_evaluations": 0,
                                      "completed_evaluations": 0, "completed_world_rollouts": 0}
               for r in rows)
    assert rows[0]["result"] == rows[1]["result"]
    assert rows[0]["signed_levels"] == -rows[1]["signed_levels"]
    assert game.round.phase == "play" and game.round.hands == hands
    assert all(len(r["events"]) == len(r["result"]["history"]) for r in rows)


def test_expiry_retains_failure_without_scoring_or_playing():
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    def expired():
        raise TimeoutError("benchmark deadline")
    row = play_mirror(game, flip=0, information="actor-only",
                      planner_factory=lambda seat: planner,
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733,
                      before_decision=expired)
    assert not row["complete"]
    assert "signed_levels" not in row and row["events"] == []
    assert row["error"] == "TimeoutError: benchmark deadline"


@pytest.mark.parametrize("feedback", [False, True])
def test_mirror_feedback_option_and_partial_rollout_accounting(feedback):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    original = copy.deepcopy(game.round.hands)

    def factory(seat):
        sent = False

        def choose(packet):
            nonlocal sent
            if not sent:
                sent = True
                return {"evaluations": [{"cards": [], "continuation": "heuristic-all"}],
                        "memory": "invalid candidate probe"}
            return planner(packet)
        return choose

    row = play_mirror(game, flip=0, information="perfect", planner_factory=factory,
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733,
                      invalid_action_feedback=feedback)
    assert row["invalid_action_feedback"] is feedback
    assert row["complete"] is feedback
    attempts = 2 if feedback else 1
    assert row["rollout_usage"] == {
        "requested_batches": attempts, "attempted_evaluations": attempts,
        "completed_evaluations": 0, "completed_world_rollouts": 0}
    if not feedback:
        assert row["error"].startswith("IllegalPlay:")
        assert "signed_levels" not in row
    assert game.round.hands == original


@pytest.mark.parametrize("option", [None, 0, 1, "true"])
def test_mirror_feedback_option_is_strict_before_factories(option):
    def forbidden(*args):
        pytest.fail("invalid flag must refuse before factory calls")
    with pytest.raises(ValueError, match="invalid_action_feedback must be bool"):
        play_mirror(None, flip=0, information="perfect", planner_factory=forbidden,
                    baseline_factory=forbidden, seed=0, invalid_action_feedback=option)
