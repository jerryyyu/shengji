import asyncio

import pytest

from shengji.api.model_serving import run_model_search


def test_concurrency_one_and_queued_cancel():
    async def scenario():
        first_started = asyncio.Event(); release = asyncio.Event(); calls = []
        async def compute():
            calls.append(1); first_started.set(); await release.wait(); return 3
        events = []
        one = asyncio.create_task(run_model_search(compute, lambda k, **f: events.append(k)))
        await first_started.wait()
        two = asyncio.create_task(run_model_search(compute, lambda k, **f: events.append(k)))
        await asyncio.sleep(0); two.cancel()
        with pytest.raises(asyncio.CancelledError): await two
        assert len(calls) == 1 and "cancelled" in events
        release.set(); assert await one == 3
    asyncio.run(scenario())


def test_running_cancel_drains_and_releases_then_next_runs():
    async def scenario():
        started = asyncio.Event(); release = asyncio.Event(); calls = 0
        async def compute():
            nonlocal calls
            calls += 1; started.set(); await release.wait(); return calls
        events = []
        task = asyncio.create_task(run_model_search(compute, lambda k, **f: events.append(k)))
        await started.wait(); task.cancel(); await asyncio.sleep(0)
        assert calls == 1
        blocked = asyncio.create_task(run_model_search(compute, lambda k, **f: events.append(k)))
        await asyncio.sleep(0); assert calls == 1
        task.cancel(); await asyncio.sleep(0); await asyncio.sleep(0)
        assert not task.done() and calls == 1
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert await blocked == 2
    asyncio.run(scenario())


def test_failure_releases_and_no_completed_event_heartbeat():
    async def scenario():
        events = []
        async def bad():
            await asyncio.sleep(.01)
            raise RuntimeError("private details")
        with pytest.raises(RuntimeError):
            await run_model_search(bad, lambda k, **f: events.append((k, f)), heartbeat_interval=.001)
        assert [k for k, _ in events][-1] == "error"
        assert "completed" not in [k for k, _ in events]
        assert all("private" not in repr(item) for item in events)
        assert any(k == "heartbeat" for k, _ in events)
    asyncio.run(scenario())
