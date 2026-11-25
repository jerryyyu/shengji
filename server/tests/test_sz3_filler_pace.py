import sys
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("sz3_filler_pace", ROOT / "scripts" / "lanes" / "sz3_filler_pace.py")
pace = module_from_spec(SPEC)
sys.modules[SPEC.name] = pace
SPEC.loader.exec_module(pace)

START = datetime(2026, 11, 25, 16, tzinfo=timezone.utc)


def now(offset):
    return START + timedelta(seconds=offset)


def line(offset, body):
    return f"{now(offset):%Y-%m-%dT%H:%M:%SZ} {body}\n"


def report(offset, buffer):
    return line(offset, f'epoch 1 buffer {buffer}/1042 {{"belief": 1.1}} (600s)')


BASE = line(0, "UTR START params=11055739 buffers=1042 init=scratch:{} device=mps")
BASE += line(0, "INIT calib {}") + report(600, 100) + report(1200, 150)


def test_stops_on_two_full_slow_windows_and_ignores_repeat_polls():
    guard = pace.PaceGuard(BASE, now(1300))
    assert guard.baseline_buffers_per_minute == 5
    status = BASE + report(1800, 190)
    guard.check(status, now(1801))
    status += report(2400, 234)
    for t in (2410, 2510, 2610):
        guard.check(status, now(t))
    status += report(3003, 278)
    with pytest.raises(pace.PaceError, match="two consecutive"):
        guard.check(status, now(3005))


def test_recovery_and_exactly_ten_percent_do_not_trigger_guard():
    guard = pace.PaceGuard(BASE, now(1300))
    status = BASE + report(1800, 200) + report(2400, 244)
    status += report(3000, 289) + report(3600, 333) + report(4200, 383)
    guard.check(status, now(4201))


@pytest.mark.parametrize(("suffix", "offset", "reason"), [
    ("", 1951, "stale"),
    (line(1800, "epoch 1 buffer bad"), 1801, "malformed"),
    (report(1800, 150), 1801, "reset"),
    (report(1800, 200).rstrip("\n"), 1801, "incomplete"),
    (report(1951, 200), 1951, "report cadence"),
    (report(1800, 200), 1790, "out of order"),
])
def test_refuses_unreliable_progress(suffix, offset, reason):
    guard = pace.PaceGuard(BASE, now(1300))
    with pytest.raises(pace.PaceError, match=reason):
        guard.check(BASE + suffix, now(offset))


def test_refuses_terminal_or_resumed_segment():
    guard = pace.PaceGuard(BASE, now(1300))
    terminal = BASE + line(1250, "STOPPED at epoch 1 buffer 153/1042 (STOP file or --max-seconds); checkpoint saved")
    with pytest.raises(pace.PaceError, match="no active pace baseline"):
        guard.check(terminal, now(1250))
    resumed = terminal + line(1260, "RESUME epoch 0 buffer 153 device=mps") + report(1860, 205) + report(2460, 255)
    with pytest.raises(pace.PaceError, match="changed segments"):
        guard.check(resumed, now(2460))


def test_truncated_status_cannot_replace_the_guard_anchor():
    guard = pace.PaceGuard(BASE, now(1300))
    changed = BASE.replace(report(1200, 150), report(1200, 151))
    with pytest.raises(pace.PaceError, match="history changed"):
        guard.check(changed, now(1301))
