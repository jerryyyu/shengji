import asyncio
import os
from pathlib import Path
import subprocess
import sys

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


@pytest.mark.parametrize("via_timeout", [False, True])
def test_cancellation_wins_over_failed_worker_and_releases_permit(via_timeout):
    async def scenario():
        started = asyncio.Event()
        fail = asyncio.Event()
        events = []
        timers = []

        async def compute():
            started.set()
            await fail.wait()
            raise ValueError("private worker failure")

        async def caller():
            async with asyncio.timeout(None) as timer:
                timers.append(timer)
                return await run_model_search(compute, lambda k, **f: events.append((k, f)))

        task = asyncio.create_task(caller())
        await started.wait()
        if via_timeout:
            timers[0].reschedule(asyncio.get_running_loop().time() - 1)
            await asyncio.sleep(0)
        else:
            task.cancel()
        await asyncio.sleep(0)
        assert not task.done()  # must still own its permit until worker drain
        fail.set()
        with pytest.raises(TimeoutError if via_timeout else asyncio.CancelledError):
            await task
        assert task.cancelled() is (not via_timeout)
        if via_timeout:
            assert task.cancelling() == 0
        assert [kind for kind, _ in events] == ["queued", "running", "cancelled"]
        assert "private" not in repr(events)

        async def next_compute():
            return 7
        assert await run_model_search(next_compute, lambda *a, **kw: None) == 7

    asyncio.run(scenario())


@pytest.mark.parametrize("value", ["typo", "0", "9"])
def test_invalid_concurrency_refuses_actual_server_import(value):
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
           "SHENGJI_MODEL_SEARCH_CONCURRENCY": value}
    result = subprocess.run([sys.executable, "-c", "import shengji.api.server"],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "ValueError: SHENGJI_MODEL_SEARCH_CONCURRENCY must be 1..8" in result.stderr


def test_valid_concurrency_is_bound_at_server_startup():
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
           "SHENGJI_MODEL_SEARCH_CONCURRENCY": "2"}
    script = """
import asyncio, os
import shengji.api.server
from shengji.api.model_serving import _semaphore
os.environ['SHENGJI_MODEL_SEARCH_CONCURRENCY'] = 'typo'
async def check():
    sem = _semaphore()
    await sem.acquire()
    assert not sem.locked()
    await sem.acquire()
    assert sem.locked()
asyncio.run(check())
"""
    result = subprocess.run([sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
