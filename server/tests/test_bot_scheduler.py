"""Concurrency and pacing contracts for production bot turns."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from shengji.api import server as srv


def _room() -> SimpleNamespace:
    return SimpleNamespace(
        code="TEST",
        lock=asyncio.Lock(),
        seats=[SimpleNamespace(is_bot=True)],
        round=SimpleNamespace(phase="play"),
        bot=SimpleNamespace(policy_name="test-policy"),
        records=[],
        log_event=lambda kind, **data: None,
    )


def test_bot_step_is_offloaded_and_other_coroutines_run(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_step(room, seat):
        started.set()
        assert release.wait(timeout=2)
        return True

    monkeypatch.setattr(srv, "bot_step", blocking_step)

    async def scenario():
        task = asyncio.create_task(srv._bot_step_off_loop(_room(), 0))
        while not started.is_set():
            await asyncio.sleep(0)
        # If bot_step were still on the event loop, this coroutine could not
        # reach the release and the worker would time out.
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        assert await task is True

    asyncio.run(scenario())


def test_cpu_bound_bot_still_yields_the_event_loop(monkeypatch):
    def cpu_step(room, seat):
        deadline = time.perf_counter() + 0.08
        value = 1
        while time.perf_counter() < deadline:
            value = (value * 33 + 17) & 0xFFFFFFFF
        return value >= 0

    monkeypatch.setattr(srv, "bot_step", cpu_step)

    async def scenario():
        task = asyncio.create_task(srv._bot_step_off_loop(_room(), 0))
        heartbeats = 0
        while not task.done():
            await asyncio.sleep(0.005)
            heartbeats += 1
        assert await task is True
        return heartbeats

    assert asyncio.run(scenario()) >= 3


def test_cancellation_waits_for_worker_before_releasing_room_lock(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_step(room, seat):
        started.set()
        assert release.wait(timeout=2)
        return True

    monkeypatch.setattr(srv, "bot_step", blocking_step)

    async def scenario():
        room = _room()

        async def owner():
            async with room.lock:
                return await srv._bot_step_off_loop(room, 0)

        task = asyncio.create_task(owner())
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.01)
        assert room.lock.locked(), "cancelled task released a mutating worker"
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not room.lock.locked()

    asyncio.run(scenario())


def test_compute_overlaps_minimum_pacing_delay(monkeypatch):
    compute_seconds = 0.08
    monkeypatch.setattr(srv, "BOT_DELAY", 0.12)
    monkeypatch.setattr(
        srv, "bot_step",
        lambda room, seat: (time.sleep(compute_seconds) or True),
    )
    room = _room()
    records = []
    room.log_event = lambda kind, **data: records.append((kind, data))

    async def scenario():
        started = time.perf_counter()
        assert await srv._paced_bot_step(room, 0) is True
        return time.perf_counter() - started

    elapsed = asyncio.run(scenario())
    assert elapsed >= 0.11
    assert elapsed < 0.18, "compute and pacing were paid additively"
    kind, record = records[-1]
    assert kind == "bot_timing"
    assert record["event_loop_offloaded"] is True
    assert record["compute_seconds"] >= compute_seconds * 0.8
    assert 0 < record["pacing_seconds"] < srv.BOT_DELAY
    assert record["turn_seconds"] >= srv.BOT_DELAY * 0.9


def test_slow_compute_adds_no_unconditional_delay(monkeypatch):
    monkeypatch.setattr(srv, "BOT_DELAY", 0.04)
    monkeypatch.setattr(
        srv, "bot_step", lambda room, seat: (time.sleep(0.08) or True),
    )
    room = _room()
    records = []
    room.log_event = lambda kind, **data: records.append((kind, data))

    started = time.perf_counter()
    assert asyncio.run(srv._paced_bot_step(room, 0)) is True
    elapsed = time.perf_counter() - started
    assert elapsed < 0.12
    assert records[-1][1]["pacing_seconds"] == 0.0


def test_two_rooms_do_not_serialize_bot_workers(monkeypatch):
    monkeypatch.setattr(
        srv, "bot_step", lambda room, seat: (time.sleep(0.08) or True),
    )

    async def scenario():
        started = time.perf_counter()
        assert await asyncio.gather(
            srv._bot_step_off_loop(_room(), 0),
            srv._bot_step_off_loop(_room(), 0),
        ) == [True, True]
        return time.perf_counter() - started

    elapsed = asyncio.run(scenario())
    assert elapsed < 0.14, "independent room turns serialized on the event loop"
