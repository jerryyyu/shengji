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


def test_failed_mirror_groups_calls_by_seat_but_counts_rollouts_globally():
    """Historical adapters must join decision context, not calls[-1]."""
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    original = copy.deepcopy(game.round.hands)
    chronological = []

    class RecordingPlanner:
        def __init__(self, seat):
            self.seat = seat
            self.calls = []
            self.decisions = set()

        def __call__(self, packet):
            observation = packet["observation"]
            self.decisions.add(observation["observation_sha256"])
            receipt = {"seat": self.seat, "ordinal": len(chronological),
                       "decision_results": len(packet["rollout_results"]),
                       "observation_sha256": observation["observation_sha256"]}
            self.calls.append(receipt)
            chronological.append(receipt)
            cards = planner(packet)["cards"]
            if self.seat == 1 and len(self.decisions) == 2:
                # Match the historical 4+3+16 prior evaluations, then fail at
                # index2 of a seven-candidate batch. This is synthetic: no H8
                # artifact or exact-endgame continuation is replayed here.
                candidates = ([cards] * 16 if not packet["rollout_results"]
                              else [cards, cards, [], cards, cards, cards, cards])
            elif not packet["rollout_results"]:
                candidates = [cards] * (4 if self.seat == 1 else 3)
            else:
                return planner(packet)
            return {"evaluations": [{"cards": list(candidate),
                                      "continuation": "heuristic-all"}
                                     for candidate in candidates], "memory": ""}

    row = play_mirror(
        game, flip=1, information="perfect", planner_factory=RecordingPlanner,
        baseline_factory=lambda seat, seed: HeuristicBot(), seed=733,
        invalid_action_feedback=False, classify_final_action_failures=True)

    assert row["complete"] is False
    assert "failure" not in row and "signed_levels" not in row
    assert [call["seat"] for call in chronological] == [1, 1, 3, 3, 1, 1]
    assert [call["ordinal"] for call in row["calls"]] == [0, 1, 4, 5, 2, 3]
    assert row["calls"][-1]["seat"] == 3  # NOT the failing call.
    assert chronological[-1]["seat"] == 1
    # The failing packet exposes16 local results, not the23 global results
    # completed before its batch; seven were completed at earlier decisions.
    assert chronological[-1]["decision_results"] == 16
    assert row["rollout_usage"] == {
        "requested_batches": 4, "attempted_evaluations": 26,
        "completed_evaluations": 25, "completed_world_rollouts": 25}
    diagnostic = row["rollout_diagnostic"]
    assert diagnostic["seat"] == 1 and diagnostic["stage"] == "rollout_validate"
    assert diagnostic["request_index"] == 1 and diagnostic["evaluation_index"] == 2
    assert diagnostic["completed_play_events"] == len(row["events"])
    assert row["rollout_request_binding"]["observation_sha256"] == chronological[-1]["observation_sha256"]
    assert game.round.hands == original


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
        assert "failure" not in row
        assert row["rollout_diagnostic"] == {
            "schema": "benchmark-rollout-diagnostic-v1", "stage": "rollout_validate",
            "error_type": "IllegalPlay", "seat": 0, "request_index": 0,
            "evaluation_index": 0, "cards": [], "continuation": "heuristic-all",
            "completed_play_events": 0}
        binding = row["rollout_request_binding"]
        assert binding["schema"] == "benchmark-rollout-request-binding-v1"
        assert (binding["seat"], binding["request_index"], binding["evaluation_index"],
                binding["completed_play_events"]) == (0, 0, 0, 0)
        assert all(len(binding[key]) == 64 for key in
                   ("packet_sha256", "reply_sha256", "observation_sha256"))
    else:
        assert "rollout_diagnostic" not in row
        assert "rollout_request_binding" not in row
    assert game.round.hands == original


@pytest.mark.parametrize("option", [None, 0, 1, "true"])
def test_mirror_feedback_option_is_strict_before_factories(option):
    def forbidden(*args):
        pytest.fail("invalid flag must refuse before factory calls")
    with pytest.raises(ValueError, match="invalid_action_feedback must be bool"):
        play_mirror(None, flip=0, information="perfect", planner_factory=forbidden,
                    baseline_factory=forbidden, seed=0, invalid_action_feedback=option)


@pytest.mark.parametrize("feedback", [False, True])
@pytest.mark.parametrize("classify", [False, True])
def test_feedback_and_final_action_attribution_are_independent(feedback, classify):
    game = Game(random.Random(733))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    calls = []

    def choose(packet):
        calls.append(packet)
        if not packet["rollout_results"]:
            return {"evaluations": [{"cards": [], "continuation": "heuristic-all"}],
                    "memory": "candidate"}
        assert packet["rollout_results"][0]["status"] == "invalid"
        return {"cards": [], "memory": "final"}

    row = play_mirror(game, flip=game.round.turn % 2, information="perfect",
                      planner_factory=lambda seat: choose,
                      baseline_factory=lambda seat, seed: HeuristicBot(), seed=733,
                      invalid_action_feedback=feedback,
                      classify_final_action_failures=classify)
    assert not row["complete"] and "signed_levels" not in row
    assert len(calls) == (4 if feedback else 1)
    assert row["rollout_usage"] == {
        "requested_batches": 1, "attempted_evaluations": 1,
        "completed_evaluations": 0, "completed_world_rollouts": 0}
    assert row["invalid_action_feedback"] is feedback
    assert row.get("classify_final_action_failures", False) is classify
    if feedback and classify:
        assert row["failure"]["category"] == "model_illegal_action"
        assert row["failure"]["stage"] == "engine_play"
        assert row["events"][-1]["attempted_cards"] == []
    else:
        assert "failure" not in row
        assert row["events"] == []
    if feedback:
        assert len(row["final_action_feedback"]) == 3
        assert row["error"] == "IllegalPlay: You don't hold those cards."
    else:
        assert "final_action_feedback" not in row
        assert "final_action_feedback_counts" not in row
