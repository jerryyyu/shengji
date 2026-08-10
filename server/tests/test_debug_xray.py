"""Concurrency and read-only contracts for the live decision X-ray."""
from __future__ import annotations

import asyncio
import copy
import random
import threading
import time

import pytest

from shengji.ai.registry import make_bot
from shengji.ai.smart import SmartBot
from shengji.api import debug
from shengji.engine.game import Game


def _bury_state(seed: int = 73):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    smart = SmartBot()
    for seat in range(4):
        declaration = smart.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    assert rnd.phase == "bury" and rnd.turn == rnd.banker
    return rnd, rnd.banker


def _lead_state(seed: int = 73):
    rnd, banker = _bury_state(seed)
    rnd.bury(banker, SmartBot().decide_bury(rnd, banker))
    assert rnd.phase == "play" and rnd.turn is not None
    assert not rnd.trick.plays
    return rnd, rnd.turn


class _RecordingBot:
    """Small deterministic stand-in that visibly mutates on every decision."""

    def __init__(self):
        self.rng = random.Random(9182)
        self.calls = 0
        self.samples = []
        self.last_eval = {"sentinel": "live bot must retain this object"}

    def decide_play(self, rnd, seat):
        self.calls += 1
        self.samples.append(self.rng.random())
        hand = rnd.sorted_hand(seat)
        candidates = [[hand[0]], [hand[-1]]]
        self.last_eval = (candidates, [2.5, -1.5])
        return candidates[1]


class _RecordingBuryBot:
    """Bury stand-in with replay-only fields that must stay server-side."""

    policy_name = "recording-bury"

    def __init__(self):
        self.rng = random.Random(771)
        self.calls = 0
        self.last_bury_record = {"sentinel": "live record"}

    def decide_bury(self, rnd, seat):
        self.calls += 1
        hand = rnd.sorted_hand(seat)
        incumbent = hand[:8]
        challenger = hand[-8:]
        self.last_bury_record = {
            "schema": "test-bury-search-v1",
            "policy": self.policy_name,
            "mode": "structured",
            "rng_state": self.rng.getstate(),
            "incumbent_index": 0,
            "raw_winner_index": 1,
            "played_index": 0,
            "reason": "test_fallback",
            "margin": 5.0,
            "gap_vs_incumbent": 2.5,
            "search_secs": 0.125,
            "candidates": [
                {"cards": incumbent, "sources": ["incumbent"],
                 "mean_banker_value": 10.0, "worlds": 8},
                {"cards": challenger, "sources": ["void", "points"],
                 "mean_banker_value": 12.5, "worlds": 8},
            ],
            "work": {
                "cap": 16,
                "worlds_requested": 8,
                "worlds_used": 8,
                "attempts": 9,
                "attempt_cap": 320,
                "candidate_rollouts": 16,
                "complete": True,
                "future_private_field": ["must", "not", "leak"],
            },
            "sampler_counters": {
                "before": {"sample_attempts": 100},
                "after": {"sample_attempts": 109},
                "delta": {
                    "sample_attempts": 9,
                    "accepted_worlds": 8,
                    "failed_worlds": 1,
                    "rejected_worlds": 0,
                    "impossible_worlds": 0,
                    "future_private_counter": 88,
                },
            },
        }
        return incumbent


def test_xray_uses_exact_rng_copy_without_mutating_live_bot():
    rnd, seat = _lead_state()
    live = _RecordingBot()
    expected = copy.deepcopy(live)
    expected_pick = expected.decide_play(rnd, seat)
    rng_before = live.rng.getstate()
    sentinel = live.last_eval

    rnd_copy, bot_copy = debug._snapshot_xray(rnd, live)
    result = debug._xray(rnd_copy, seat, bot_copy)

    assert live.calls == 0
    assert live.samples == []
    assert live.rng.getstate() == rng_before
    assert live.last_eval is sentinel
    assert sum(item["bot_plays"] for item in result["candidates"]) == 1
    picked = next(item["play"] for item in result["candidates"]
                  if item["bot_plays"])
    assert picked == expected_pick


def test_xray_reports_redacted_bury_search_without_mutating_live_bot():
    rnd, seat = _bury_state()
    live = _RecordingBuryBot()
    sentinel = live.last_bury_record
    rng_before = live.rng.getstate()

    rnd_copy, bot_copy = debug._snapshot_xray(rnd, live)
    result = debug._xray(rnd_copy, seat, bot_copy)

    assert live.calls == 0
    assert live.last_bury_record is sentinel
    assert live.rng.getstate() == rng_before
    assert result["candidates"] is None
    bury = result["bury"]
    assert bury["policy"] == "recording-bury"
    assert bury["mode"] == "structured"
    assert bury["reason"] == "test_fallback"
    assert bury["fallback"] is True
    assert bury["chosen"] == rnd.sorted_hand(seat)[:8]
    assert sum(c["bot_buries"] for c in bury["candidates"]) == 1
    assert bury["candidates"][1]["sources"] == ["void", "points"]
    assert bury["work"] == {
        "cap": 16,
        "worlds_requested": 8,
        "worlds_used": 8,
        "attempts": 9,
        "attempt_cap": 320,
        "candidate_rollouts": 16,
        "complete": True,
    }
    assert bury["sampler_delta"] == {
        "sample_attempts": 9,
        "accepted_worlds": 8,
        "failed_worlds": 1,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }
    rendered = repr(bury)
    assert "rng_state" not in rendered
    assert "future_private" not in rendered
    assert "before" not in rendered
    assert "after" not in rendered


def test_xray_reports_production_heuristic_bury_without_inventing_search():
    rnd, seat = _bury_state(seed=91)
    result = debug._xray(rnd, seat, make_bot("mc-s0-report-lcb", seed=17))

    bury = result["bury"]
    assert bury["policy"] == "mc-s0-report-lcb"
    assert bury["mode"] == "heuristic"
    assert bury["reason"] == "heuristic_pick"
    assert bury["fallback"] is False
    assert len(bury["chosen"]) == 8
    assert bury["work"] is None
    assert bury["sampler_delta"] is None
    assert bury["candidates"] == [{
        "cards": bury["chosen"],
        "sources": ["heuristic"],
        "banker_avg": None,
        "worlds": 0,
        "incumbent": True,
        "raw_winner": True,
        "bot_buries": True,
    }]


def test_xray_snapshot_detaches_round_and_bot_before_worker_runs():
    rnd, seat = _lead_state()
    live = _RecordingBot()

    rnd_copy, bot_copy = debug._snapshot_xray(rnd, live)
    original_hand = rnd_copy.sorted_hand(seat)

    # Mutations after the room lock is released cannot alter the worker view.
    rnd.hands[seat].clear()
    live.calls = 99

    assert rnd_copy.sorted_hand(seat) == original_hand
    assert bot_copy.calls == 0
    result = debug._xray(rnd_copy, seat, bot_copy)
    assert result["hand"] == original_hand


def test_deployed_report_lcb_bot_can_be_isolated_by_deepcopy():
    live = make_bot("mc-s0-report-lcb", seed=17)
    clone = copy.deepcopy(live)

    assert clone is not live
    assert clone.policy_name == live.policy_name
    assert clone.rng.getstate() == live.rng.getstate()
    clone.rng.random()
    assert clone.rng.getstate() != live.rng.getstate()


def test_cpu_bound_xray_yields_event_loop(monkeypatch):
    def cpu_xray(rnd, seat, source_bot):
        deadline = time.perf_counter() + 0.08
        value = 1
        while time.perf_counter() < deadline:
            value = (value * 33 + 17) & 0xFFFFFFFF
        return {"value": value}

    monkeypatch.setattr(debug, "_xray", cpu_xray)

    async def scenario():
        task = asyncio.create_task(debug._xray_off_loop(None, 0, None))
        heartbeats = 0
        while not task.done():
            await asyncio.sleep(0.005)
            heartbeats += 1
        assert (await task)["value"] >= 0
        return heartbeats

    assert asyncio.run(scenario()) >= 3


def test_xray_releases_live_room_lock_before_search(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_xray(rnd, seat, isolated_bot):
        started.set()
        assert release.wait(timeout=2)
        return {"done": True}

    monkeypatch.setattr(debug, "_xray", blocking_xray)
    rnd, seat = _lead_state()

    class Room:
        lock = asyncio.Lock()
        round = rnd
        bot = _RecordingBot()

    async def scenario():
        task = asyncio.create_task(debug._xray_room(Room(), seat, None))
        while not started.is_set():
            await asyncio.sleep(0)

        # Chat, reconnect and seat claims use this same lock.  They must not
        # wait for the CPU-heavy debug search.
        await asyncio.wait_for(Room.lock.acquire(), timeout=0.2)
        Room.lock.release()

        release.set()
        assert await task == {"done": True}

    asyncio.run(scenario())


def test_xray_cancellation_waits_for_worker_before_room_unlock(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_xray(rnd, seat, source_bot):
        started.set()
        assert release.wait(timeout=2)
        return {"done": True}

    monkeypatch.setattr(debug, "_xray", blocking_xray)

    async def scenario():
        lock = asyncio.Lock()

        async def owner():
            async with lock:
                return await debug._xray_off_loop(None, 0, None)

        task = asyncio.create_task(owner())
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.01)
        assert lock.locked(), "cancelled request released a reading worker"
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not lock.locked()

    asyncio.run(scenario())
