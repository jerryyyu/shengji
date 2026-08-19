"""Opt-in producer-pipelined batch prefetch for BELIEF-V1 V2 training.

Measured on the live R3 run: the training stage realizes about six of sixteen
cores because each cohort alternates serial batch reconstruction from the
sealed index (one thread) with the parallel member step.  This adapter
overlaps the two phases: one producer thread builds the next batch while the
consumer trains on the current one.

Semantics are unchanged by construction — batches are a pure function of the
sealed index, a single producer preserves order, and the consumer sees the
exact same objects in the exact same sequence.  The ONLY resource change is
residency: at most TWO complete batches are alive at once (the one being
trained on and the prefetched one) instead of one, enforced by a live-batch
semaphore the tests witness.  Producer exceptions re-raise at the consumer
with their original type, so refusal semantics (schedule drift, deadline
expiry upstream) are preserved.

Nothing here is wired into any reviewed path: adoption is a V3 design
decision that additionally requires a re-measured host-memory gate at
two-batch residency and a re-run deadline probe so the frozen epoch estimate
matches the pipelined wall.  This module grants no execution authority.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Iterator


PIPELINE_PREFETCH_DEPTH = 1
_JOIN_TIMEOUT_SECONDS = 30.0


class BeliefV2PipelineError(ValueError):
    """The pipeline adapter was misused or its producer failed to stop."""


class _Done:
    pass


class _Raised:
    def __init__(self, error: BaseException) -> None:
        self.error = error


def pipelined_batches(
        factory: Callable[[], Any], *,
        prefetch_depth: int = PIPELINE_PREFETCH_DEPTH) -> Iterator[Any]:
    """Yield factory()'s batches unchanged, prefetching exactly one ahead.

    ``factory`` is the same zero-argument iterator factory the cohort trainer
    already consumes.  The live-batch budget is frozen at two (current +
    prefetched); other depths refuse so the residency bound stays provable.
    """
    if not callable(factory):
        raise BeliefV2PipelineError("V2 pipeline factory is not callable")
    if prefetch_depth != PIPELINE_PREFETCH_DEPTH:
        raise BeliefV2PipelineError(
            "V2 pipeline prefetch depth contract is exactly one")
    return _pipelined(factory)


def _pipelined(factory: Callable[[], Any]) -> Iterator[Any]:
    live_budget = threading.Semaphore(1 + PIPELINE_PREFETCH_DEPTH)
    handoff: queue.Queue = queue.Queue()
    stop = threading.Event()

    def produce() -> None:
        try:
            source = iter(factory())
            while True:
                while not live_budget.acquire(timeout=0.1):
                    if stop.is_set():
                        return
                if stop.is_set():
                    return
                try:
                    item = next(source)
                except StopIteration:
                    handoff.put(_Done())
                    return
                handoff.put(item)
        except BaseException as error:  # re-raised at the consumer
            handoff.put(_Raised(error))

    producer = threading.Thread(
        target=produce, name="belief-v2-batch-producer", daemon=True)
    producer.start()
    try:
        while True:
            item = handoff.get()
            if isinstance(item, _Done):
                return
            if isinstance(item, _Raised):
                raise item.error
            try:
                yield item
            finally:
                del item
            live_budget.release()
    finally:
        stop.set()
        # Unblock a producer waiting on the budget, then require it to exit.
        live_budget.release()
        producer.join(timeout=_JOIN_TIMEOUT_SECONDS)
        if producer.is_alive():
            raise BeliefV2PipelineError(
                "V2 pipeline producer failed to stop")


def pipelined_factory(
        factory: Callable[[], Any]) -> Callable[[], Iterator[Any]]:
    """Wrap an iterator factory so each call starts a fresh pipelined pass."""
    if not callable(factory):
        raise BeliefV2PipelineError("V2 pipeline factory is not callable")
    return lambda: pipelined_batches(factory)
