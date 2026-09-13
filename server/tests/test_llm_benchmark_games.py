import copy
import random
from types import SimpleNamespace

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
