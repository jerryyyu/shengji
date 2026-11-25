"""Guard an active SZ3 trainer segment using its checkpoint progress reports."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_TIMESTAMP = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (.+)")
_PROGRESS = re.compile(r"epoch 1 buffer ([1-9]\d*)/([1-9]\d*) \{.*\} \(\d+s\)")
_MIN_WINDOW = 590
_MAX_WINDOW = 750


class PaceError(RuntimeError):
    """SZ3's pace cannot be verified or is below the allowed floor."""


@dataclass(frozen=True)
class _Sample:
    time: datetime
    buffer: int
    total: int


def _active_segment(status: str, now: datetime) -> tuple[str, list[_Sample]]:
    if not status.endswith("\n"):
        raise PaceError("incomplete SZ3 trainer status")
    segment = ""
    samples = []
    last_time = None
    ended = False
    for line in status.splitlines():
        stamp = _TIMESTAMP.fullmatch(line)
        if stamp is None:
            raise PaceError("malformed SZ3 trainer status")
        try:
            when = datetime.fromisoformat(stamp[1])
        except ValueError as exc:
            raise PaceError("invalid SZ3 trainer timestamp") from exc
        if when > now or (last_time is not None and when < last_time):
            raise PaceError("SZ3 trainer timestamp is out of order")
        last_time = when
        message = stamp[2]
        if message.startswith(("UTR START ", "RESUME epoch 0 buffer ")):
            segment, samples, ended = line, [], False
        elif message.startswith(("STOPPED ", "UTR PAUSED ", "UTR DONE ", "UTR ABORT ", "EPOCH ")):
            ended = True
        elif message.startswith(("INIT calib ", "CAPACITY ", "DEVICE mps ")):
            continue
        else:
            progress = _PROGRESS.fullmatch(message)
            if progress is None or not segment or ended:
                raise PaceError("malformed SZ3 trainer progress")
            sample = _Sample(when, int(progress[1]), int(progress[2]))
            if sample.buffer >= sample.total:
                raise PaceError("SZ3 buffer is outside the active epoch")
            if samples and (sample.buffer <= samples[-1].buffer or sample.total != samples[-1].total
                            or sample.time <= samples[-1].time):
                raise PaceError("SZ3 trainer progress reset within a segment")
            samples.append(sample)
    if ended or len(samples) < 2:
        raise PaceError("SZ3 trainer has no active pace baseline")
    if (now - samples[-1].time).total_seconds() > _MAX_WINDOW:
        raise PaceError("SZ3 trainer progress is stale")
    return segment, samples


def _window(previous: _Sample, current: _Sample) -> tuple[int, float]:
    elapsed = (current.time - previous.time).total_seconds()
    if not _MIN_WINDOW <= elapsed <= _MAX_WINDOW:
        raise PaceError("SZ3 progress interval differs from the ten-minute report cadence")
    return current.buffer - previous.buffer, elapsed


class PaceGuard:
    """Freeze the last pre-start rate and require two consecutive slow report windows."""

    def __init__(self, status_text: str, now: datetime):
        self._segment, samples = _active_segment(status_text, now)
        self._baseline_buffers, self._baseline_seconds = _window(*samples[-2:])
        self._seen = samples[-1]
        self._started = now
        self._consecutive_slow = 0

    @property
    def baseline_buffers_per_minute(self) -> float:
        return 60 * self._baseline_buffers / self._baseline_seconds

    def check(self, status_text: str, now: datetime) -> None:
        segment, samples = _active_segment(status_text, now)
        if segment != self._segment:
            raise PaceError("SZ3 trainer changed segments")
        try:
            index = samples.index(self._seen)
        except ValueError as exc:
            raise PaceError("SZ3 trainer progress history changed") from exc
        for sample in samples[index + 1:]:
            previous = self._seen
            buffers, seconds = _window(previous, sample)
            self._seen = sample
            # The first report after start anchors full windows under the concurrent load.
            if previous.time > self._started:
                if 10 * buffers * self._baseline_seconds < 9 * self._baseline_buffers * seconds:
                    self._consecutive_slow += 1
                else:
                    self._consecutive_slow = 0
                if self._consecutive_slow == 2:
                    raise PaceError("SZ3 pace fell more than 10% in two consecutive report windows")
