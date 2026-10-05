import copy
import random
from types import SimpleNamespace

from shengji.ai.env import play_round, prepare_round, play_prepared_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.luna.benchmark_games import play_mirror
from shengji.luna.benchmark_games import _RecordedPolicy, RecordedSetupPolicy, fallback_summary
import pytest


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


def test_fallback_metadata_is_copied_without_private_search_state():
    class Bot:
        def decide_play(self, rnd, seat):
            self.last_decision_record = {"schema": "pv-search-fallback-v1",
                "reason": "budget", "hands": ["SECRET"], "work_complete": False}
            return ["C3"]
    bot, events = Bot(), []
    assert _RecordedPolicy(bot, 1, lambda: None, events).decide_play(None, 1) == ["C3"]
    bot.last_decision_record["reason"] = "changed"
    assert "hands" not in events[0]["policy_record"]
    summary = fallback_summary(events)
    assert summary["attempted_decisions"] == summary["fallbacks"] == 1
    assert summary["reasons"] == {"budget": 1}
    assert summary["warning"]


def test_failed_decision_retains_attempt_and_does_not_reuse_stale_record():
    class Bot:
        last_decision_record = {"schema": "pv-search-fallback-v1", "reason": "budget"}
        def decide_play(self, rnd, seat):
            raise RuntimeError("broken")
    events = []
    with pytest.raises(RuntimeError):
        _RecordedPolicy(Bot(), 1, lambda: None, events).decide_play(None, 1)
    assert events[0]["error"] == "RuntimeError: broken"
    summary = fallback_summary(events)
    assert summary["attempted_decisions"] == summary["missing_records"] == 1
    assert summary["fallbacks"] == 0


def test_bury_is_recorded_separately_and_planner_events_not_counted():
    class Bot:
        def decide_bury(self, rnd, seat):
            self.last_bury_record = {"schema": "cwv-bury-fallback-v1", "reason": "search-error"}
            return ["C3"]
    events = []
    assert RecordedSetupPolicy(Bot(), events).decide_bury(None, 0) == ["C3"]
    events.append({"side": "planner", "policy_record": None})
    assert fallback_summary(events)["reasons"] == {"search-error": 1}
    assert fallback_summary(events)["attempted_decisions"] == 1
