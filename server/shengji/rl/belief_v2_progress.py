"""Outcome-blind, log-only progress telemetry for BELIEF-V1 V2 workers."""

from __future__ import annotations

import sys
import time
from typing import Callable, TextIO

from .belief_contract import canonical_json_bytes


PROGRESS_SCHEMA = "belief-v1-v2-worker-progress-v1"
PROGRESS_PREFIX = "BELIEF_V2_PROGRESS "
ProgressCallback = Callable[[int, int, str], None]


class BeliefV2ProgressError(ValueError):
    """A worker tried to publish ambiguous or non-monotonic progress."""


class V2ProgressReporter:
    """Emit canonical progress records without touching evidence artifacts."""

    def __init__(
            self, *, stage: str, worker: str,
            stream: TextIO | None = None,
            clock: Callable[[], int] = time.monotonic_ns) -> None:
        if not _token(stage) or not _token(worker) or not callable(clock):
            raise BeliefV2ProgressError("V2 progress identity drift")
        self._stage = stage
        self._worker = worker
        self._stream = sys.stderr if stream is None else stream
        self._clock = clock
        self._started = clock()
        if type(self._started) is not int or self._started < 0:
            raise BeliefV2ProgressError("V2 progress clock drift")
        self._total: int | None = None
        self._completed = -1

    def update(self, completed: int, total: int, phase: str) -> None:
        """Write one monotonic JSON line; percentages are integer basis points."""
        observed = self._clock()
        if type(completed) is not int or type(total) is not int \
                or total <= 0 or not 0 <= completed <= total \
                or not _token(phase) \
                or type(observed) is not int or observed < self._started \
                or self._completed > completed \
                or self._total not in {None, total}:
            raise BeliefV2ProgressError("V2 progress population drift")
        self._total = total
        self._completed = completed
        elapsed = observed - self._started
        remaining = (None if completed == 0 else
                     elapsed * (total - completed) // completed)
        payload = {
            "schema": PROGRESS_SCHEMA,
            "stage": self._stage,
            "worker": self._worker,
            "phase": phase,
            "completed_units": completed,
            "total_units": total,
            "percent_basis_points": completed * 10_000 // total,
            "elapsed_nanoseconds": elapsed,
            "estimated_remaining_nanoseconds": remaining,
            "status": "complete" if completed == total else "running",
            "outcome_blind": True,
            "evidence_artifact": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }
        raw = canonical_json_bytes(payload).decode("ascii")
        self._stream.write(PROGRESS_PREFIX + raw)
        self._stream.flush()


def _token(value: object) -> bool:
    return type(value) is str and bool(value) and value.isascii() \
        and all(char.isalnum() or char in "-_." for char in value)
