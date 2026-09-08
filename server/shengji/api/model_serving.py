"""Small cancellation-safe admission wrapper for opt-in model searches."""
from __future__ import annotations

import asyncio
import inspect
import os
import time
import weakref
from typing import Any, Awaitable, Callable

_SEMAPHORES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _configured_concurrency() -> int:
    raw = os.environ.get("SHENGJI_MODEL_SEARCH_CONCURRENCY", "1")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("SHENGJI_MODEL_SEARCH_CONCURRENCY must be 1..8") from exc
    if not 1 <= value <= 8:
        raise ValueError("SHENGJI_MODEL_SEARCH_CONCURRENCY must be 1..8")
    return value


# The server imports this module at startup: invalid deployment configuration
# must fail before it accepts rooms, not at the first player's search.
_CONCURRENCY = _configured_concurrency()


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _SEMAPHORES.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(_CONCURRENCY)
        _SEMAPHORES[loop] = sem
    return sem


async def _send(emit: Callable[..., Any], kind: str, **fields: Any) -> None:
    result = emit(kind, **fields)
    if inspect.isawaitable(result):
        await result


async def run_debug_search(compute: Callable[[], Awaitable[Any]]) -> Any:
    """Debug shares gameplay's permits but never queues behind a busy search.

    There is no yielding operation between the availability check and the
    synchronous-emitter admission path below. Snapshotting occurs only after
    admission, so rejected requests allocate neither bot copies nor workers.
    """
    if _semaphore().locked():
        return {"error": "search busy; retry Xray after the current decision"}
    return await run_model_search(compute, lambda *args, **kwargs: None)


async def run_model_search(compute: Callable[[], Awaitable[Any]], emit: Callable[..., Any], *,
                           heartbeat_interval: float = 10.0) -> Any:
    """Run one admitted search, preserving cancellation until worker drain.

    ``compute`` is never started before semaphore admission.  Events contain
    stage and elapsed time only; failures deliberately expose exception class,
    never exception text or model/search inputs.
    """
    if not callable(compute) or not callable(emit):
        raise TypeError("compute and emit must be callable")
    if not isinstance(heartbeat_interval, (int, float)) or heartbeat_interval <= 0:
        raise ValueError("heartbeat_interval must be positive")
    started = time.monotonic()
    await _send(emit, "queued", stage="queued", elapsed_seconds=0.0)
    sem = _semaphore()
    acquired = False
    worker: asyncio.Task | None = None
    heartbeat: asyncio.Task | None = None
    stage = "queued"

    async def beat() -> None:
        while True:
            await asyncio.sleep(heartbeat_interval)
            await _send(emit, "heartbeat", stage=stage,
                        elapsed_seconds=max(0.0, time.monotonic() - started))

    try:
        heartbeat = asyncio.create_task(beat())
        try:
            await sem.acquire()
        except asyncio.CancelledError:
            await _send(emit, "cancelled", stage="cancelled",
                        elapsed_seconds=max(0.0, time.monotonic() - started))
            raise
        acquired = True
        stage = "running"
        await _send(emit, "running", stage="running",
                    elapsed_seconds=max(0.0, time.monotonic() - started))
        worker = asyncio.create_task(compute())
        cancelled = None
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError as exc:
                # Multiple cancel requests (disconnect, then cleanup) must
                # not free the permit while CPU search still owns it.
                cancelled = exc
            except Exception:
                break
        if cancelled is not None:
            # Drain also consumes a secondary worker error, but cancellation
            # retains precedence for asyncio.timeout / TaskGroup callers.
            if not worker.cancelled():
                worker.exception()
            await _send(emit, "cancelled", stage="cancelled",
                        elapsed_seconds=max(0.0, time.monotonic() - started))
            raise cancelled
        try:
            result = worker.result()
        except Exception as exc:
            await _send(emit, "error", stage="error", error_class=type(exc).__name__,
                        elapsed_seconds=max(0.0, time.monotonic() - started))
            raise
        await _send(emit, "completed", stage="completed",
                    elapsed_seconds=max(0.0, time.monotonic() - started))
        return result
    finally:
        try:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
        finally:
            if acquired:
                sem.release()
