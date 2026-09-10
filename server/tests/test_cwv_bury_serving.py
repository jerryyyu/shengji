"""Budget/failure witnesses at the helper, live-serving and X-ray boundaries."""
import asyncio
import copy
import json
import random
from collections import Counter
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai.mcbot import MCBot
from shengji.ai.smart import SmartBot
from shengji.api import debug, server
from shengji.engine.game import Game
from shengji.harvest import trajectory
from shengji.train import cwv_bury_policy as policy
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state


class Evaluator:
    max_batch = 4
    backend = "numpy"  # exercise the serving semaphore path

    def score(self, positions, seat, **kwargs):
        return np.zeros(len(positions))


def bot(evaluator=None, budget=1.0, arm="hybrid"):
    return policy.CWVBuryBot(
        Evaluator() if evaluator is None else evaluator, seed=73, arm=arm,
        bury_config=policy.CWVBuryConfig(max_candidates=6, model_worlds=2,
                                         selection_worlds=2, alternatives=2),
        serving_budget_seconds=budget)


@pytest.mark.parametrize("where", ["sampling", "model", "rollout"])
def test_budget_stops_actual_loop_and_returns_only_legal_incumbent(monkeypatch, where):
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(policy, "time", SimpleNamespace(perf_counter=lambda: clock.value))
    calls = []
    sample = MCBot._sample_hands
    rollout = MCBot._rollout_from_bury

    def timed_sample(self, *args, **kwargs):
        result = sample(self, *args, **kwargs)
        if where == "sampling":
            calls.append("sampling")
            clock.value = 2.0
        return result

    def timed_rollout(self, *args, **kwargs):
        result = rollout(self, *args, **kwargs)
        if where == "rollout":
            calls.append("rollout")
            clock.value = 2.0
        return result

    class TimedEvaluator(Evaluator):
        def score(self, positions, seat, **kwargs):
            if where == "model":
                calls.append("model")
                clock.value = 2.0
            return super().score(positions, seat, **kwargs)

    monkeypatch.setattr(MCBot, "_sample_hands", timed_sample)
    monkeypatch.setattr(MCBot, "_rollout_from_bury", timed_rollout)
    rnd = reopen_state(capture_state(65))
    player = bot(TimedEvaluator())
    before = player.rng.getstate()
    expected = SmartBot().decide_bury(rnd, rnd.banker)
    assert player.decide_bury(rnd, rnd.banker) == expected
    assert calls == [where]  # no second attempt/batch/rollout after expiry
    assert rnd.phase == "bury" and rnd.buried == []
    assert player.rng.getstate() == before
    record = player.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1"
    assert record["reason"] == "budget" and record["work_complete"] is False
    assert record["elapsed_seconds"] == 2.0
    assert "mc_evidence" not in record  # partial matrix must never become a label
    with pytest.raises(trajectory.TrajectoryError, match="^partial bury fallback is not MC training evidence$"):
        trajectory._bury_fields({}, "test", 0, 0, rnd.banker,
                                rnd.hands[rnd.banker], expected, record)


def test_no_budget_preserves_fail_stop_and_successful_budget_preserves_decision():
    rnd = reopen_state(capture_state(66))
    results = []
    for budget in (None, 30.0):
        player = bot(budget=budget)
        picked = player.decide_bury(rnd, rnd.banker)
        record = {k: v for k, v in player.last_bury_record.items()
                  if k not in ("elapsed_seconds", "model_seconds", "rollout_seconds")}
        results.append((picked, record, player.rng.getstate()))
    assert results[0] == results[1]

    class FailingEvaluator(Evaluator):
        def score(self, *args, **kwargs):
            raise RuntimeError("private model details")

    with pytest.raises(RuntimeError, match="^private model details$"):
        bot(FailingEvaluator(), budget=None).decide_bury(rnd, rnd.banker)
    with pytest.raises(policy.BuryPolicyError, match="^bury policy requires the banker in bury phase$"):
        bot(FailingEvaluator()).decide_bury(rnd, (rnd.banker + 1) % 4)


@pytest.mark.parametrize("stale", [False, True])
def test_serving_snapshot_fallback_commit_or_discard_and_telemetry(tmp_path, stale):
    class FailingEvaluator(Evaluator):
        def score(self, *args, **kwargs):
            raise RuntimeError("private model details must not appear in logs")

    async def scenario():
        rnd = reopen_state(capture_state(65))
        game = Game(random.Random(7))
        game.round = rnd
        player = bot(FailingEvaluator())
        room = server.Room(code="BURYTEST", game=game, bot=player,
                           seats=[server.Seat(str(i), is_bot=True) for i in range(4)],
                           log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        events = []
        room.log_event = lambda kind, **fields: events.append({"kind": kind, **fields})
        seat = rnd.banker
        before = player.rng.getstate()
        hand = Counter(rnd.hands[seat])
        prepared = await server._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert room.bot is player and rnd.phase == "bury"  # worker only changed snapshot
        assert len(prepared.decision.cards) == 8
        assert not Counter(prepared.decision.cards) - hand
        if stale:
            room.seats[seat].is_bot = False
        acted = server._commit_bot_turn(room, prepared)
        server._log_bot_timing(room, prepared, acted=acted)
        assert acted is not stale
        assert rnd.phase == ("bury" if stale else "play")
        assert room.bot.rng.getstate() == before
        if stale:
            assert room.bot is player and Counter(rnd.hands[seat]) == hand
        timing = [event for event in events if event["kind"] == "bot_timing"][-1]
        assert timing["bury_search_status"] == "fallback"
        assert timing["bury_fallback_reason"] == "search-error"
        assert timing["bury_error_class"] == "RuntimeError"
        assert timing["acted"] is (not stale)
        assert "private model details" not in json.dumps(events)
        # Same bad evaluator reaches the X-ray consumer without exposing a
        # partial score, secret error text, or mutating the live bot.
        root = reopen_state(capture_state(65))
        view = debug._bury_xray(root, root.banker, bot(FailingEvaluator()))
        assert view["fallback"] is True and view["work"] is None
        assert view["candidates"][0]["banker_avg"] is None
        assert "private model details" not in json.dumps(view)

    asyncio.run(scenario())


def test_successful_bury_xray_uses_mc_finalists_not_model_pool():
    rnd = reopen_state(capture_state(65))
    view = debug._bury_xray(rnd, rnd.banker, bot(budget=None))
    assert view["fallback"] is False
    assert view["mode"] == "hybrid"
    assert len(view["candidates"]) == 3
    assert all(row["worlds"] == 2 for row in view["candidates"])
    assert view["work"]["candidate_rollouts"] == 6
    assert sum(row["bot_buries"] for row in view["candidates"]) == 1
    assert rnd.phase == "bury"
