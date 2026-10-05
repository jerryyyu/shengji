import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts import launch_production_llm_panel as launcher
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
from test_launch_production_llm_panel import _config, _real_validation_fixture, _stub_validation
from test_launch_sol_recovery import _binding, _report, _retention, _controls


@pytest.fixture(autouse=True)
def _safe_recovery_release(monkeypatch):
    monkeypatch.setattr(launcher, '_require_recovery_release', lambda *args: None)


def _snapshot(page_size=16384, free=1, inactive=2, speculative=3):
    return (f'Mach Virtual Memory Statistics: (page size of {page_size} bytes)\n'
            f'Pages free: {free}.\nPages inactive: {inactive}.\n'
            f'Pages speculative: {speculative}.\n')


@pytest.mark.parametrize('page_size', [4096, 16384])
def test_memory_parser_counts_reclaimable_pages_once(page_size):
    assert launcher.benchmark_batch.available_memory_bytes(
        _snapshot(page_size)) == 6 * page_size


@pytest.mark.parametrize('snapshot', [
    None, '', _snapshot(8192), _snapshot(free=-1),
    _snapshot().replace('Pages inactive: 2.\n', ''),
    _snapshot() + 'Pages free: 1.\n',
    _snapshot() + _snapshot(),
    _snapshot().replace('Pages free: 1.', 'Pages free: 1.5.'),
    _snapshot(free=2 ** 64),
])
def test_memory_parser_refuses_unknown_or_ambiguous_snapshot(snapshot):
    with pytest.raises(ValueError):
        launcher.benchmark_batch.available_memory_bytes(snapshot)


def test_memory_guard_unsupported_platform_never_probes(monkeypatch):
    guard = launcher.benchmark_batch
    monkeypatch.setattr(guard.sys, 'platform', 'freebsd')
    monkeypatch.setattr(guard.subprocess, 'run',
                        lambda *a, **kw: pytest.fail('unsupported host probe'))
    assert not guard.assert_memory_headroom()


@pytest.mark.parametrize('failure', ['timeout', 'os-error', 'bad-snapshot', 'low-memory'])
def test_memory_guard_probe_failure_is_unsafe(monkeypatch, failure):
    from types import SimpleNamespace
    guard = launcher.benchmark_batch
    monkeypatch.setattr(guard.sys, 'platform', 'darwin')
    def probe(command, **kwargs):
        if command == ['/usr/bin/vm_stat']:
            if failure == 'timeout':
                raise guard.subprocess.TimeoutExpired(command, 5)
            if failure == 'os-error':
                raise OSError('synthetic missing probe')
            return SimpleNamespace(stdout='malformed' if failure == 'bad-snapshot'
                                   else _snapshot())
        return SimpleNamespace(stdout='1')
    monkeypatch.setattr(guard.subprocess, 'run', probe)
    assert not guard.assert_memory_headroom()


@pytest.mark.parametrize('pressure,expected', [('1', True), ('2', False), ('4', False)])
def test_real_guard_requires_normal_pressure(monkeypatch, pressure, expected):
    from types import SimpleNamespace
    guard = launcher.benchmark_batch
    monkeypatch.setattr(guard.sys, 'platform', 'darwin')
    snapshot = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
                'Pages free: 200000.\nPages inactive: 0.\nPages speculative: 0.\n')
    def probe(command, **kwargs):
        assert kwargs['timeout'] == 5
        return SimpleNamespace(stdout=snapshot if command == ['/usr/bin/vm_stat']
                               else pressure)
    monkeypatch.setattr(guard.subprocess, 'run', probe)
    assert guard.assert_memory_headroom() is expected


def test_real_guard_rechecks_pressure_after_snapshot(monkeypatch):
    from types import SimpleNamespace
    guard = launcher.benchmark_batch
    monkeypatch.setattr(guard.sys, 'platform', 'darwin')
    responses = iter(['1', 'Mach Virtual Memory Statistics: (page size of 4096 bytes)\n'
                      'Pages free: 600000.\nPages inactive: 0.\nPages speculative: 0.',
                      '2'])
    monkeypatch.setattr(guard.subprocess, 'run',
                        lambda *a, **kw: SimpleNamespace(stdout=next(responses)))
    assert not guard.assert_memory_headroom()


@pytest.mark.parametrize('outcome', ['admitted', 'timeout', 'hold', 'probe-error'])
def test_memory_wait_emits_start_polls_and_terminal_outcome(tmp_path, monkeypatch, outcome):
    now, sleeps = _fake_clock(monkeypatch)
    hold = tmp_path / 'HOLD'
    log = io.StringIO()
    attempts = []

    def probe():
        attempts.append(True)
        if outcome == 'probe-error':
            raise RuntimeError('synthetic probe failed')
        if outcome == 'hold':
            hold.write_text('pause during probe')
            return True
        return outcome == 'admitted' and len(attempts) == 2

    monkeypatch.setattr(launcher.benchmark_batch, 'assert_memory_headroom', probe)
    if outcome == 'admitted':
        launcher._wait_for_recovery_row_memory(_wait_config(), hold, 'row second', log=log)
    else:
        with pytest.raises(ValueError):
            launcher._wait_for_recovery_row_memory(_wait_config(), hold, 'row second', log=log)
    events = [json.loads(line) for line in log.getvalue().splitlines()]
    assert events[0]['event'] == 'memory-wait-start'
    assert events[0]['timeout_seconds'] == 1800
    assert events[-1]['event'] == 'memory-wait-outcome'
    assert events[-1]['outcome'] == outcome
    assert events[-1]['polls'] == len(attempts)
    polls = [event for event in events if event['event'] == 'memory-wait-poll']
    assert len(polls) == len(attempts) - (outcome == 'probe-error')
    assert all(event['stage'] == 'row second' for event in events)
    if outcome == 'admitted':
        assert sleeps == [60]
        assert events[-1]['elapsed_seconds'] == 60


def _wait_config():
    return {"memory_wait": dict(launcher.RECOVERY_MEMORY_WAIT)}


def _fake_clock(monkeypatch):
    now = [0.0]
    sleeps = []

    monkeypatch.setattr(launcher.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(launcher.time, "sleep", sleep)
    return now, sleeps


def test_recovery_memory_wait_returns_immediately_when_safe(tmp_path, monkeypatch):
    _now, sleeps = _fake_clock(monkeypatch)
    checks = []
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        lambda: checks.append(True) or True)

    launcher._wait_for_recovery_row_memory(
        _wait_config(), tmp_path / "HOLD", "row second dispatch")

    assert checks == [True]
    assert sleeps == []


def test_recovery_memory_wait_polls_then_recovers(tmp_path, monkeypatch):
    _now, sleeps = _fake_clock(monkeypatch)
    levels = iter((False, True))
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        lambda: next(levels))

    launcher._wait_for_recovery_row_memory(
        _wait_config(), tmp_path / "HOLD", "row second dispatch")

    assert sleeps == [60]


def test_recovery_memory_wait_times_out_at_monotonic_deadline(tmp_path, monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        lambda: False)

    with pytest.raises(ValueError, match="unsafe before row second dispatch"):
        launcher._wait_for_recovery_row_memory(
            _wait_config(), tmp_path / "HOLD", "row second dispatch")

    assert now[0] == launcher.RECOVERY_MEMORY_WAIT["timeout_seconds"]
    assert sleeps == [launcher.RECOVERY_MEMORY_WAIT["poll_seconds"]] * 30


def test_recovery_memory_wait_rejects_overslept_poll(tmp_path, monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        lambda: False)

    def oversleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds + launcher.RECOVERY_MEMORY_WAIT["timeout_seconds"]

    monkeypatch.setattr(launcher.time, "sleep", oversleep)
    with pytest.raises(ValueError, match="unsafe before row second dispatch"):
        launcher._wait_for_recovery_row_memory(
            _wait_config(), tmp_path / "HOLD", "row second dispatch")
    assert now[0] > launcher.RECOVERY_MEMORY_WAIT["timeout_seconds"]
    assert sleeps == [launcher.RECOVERY_MEMORY_WAIT["poll_seconds"]]


def test_recovery_memory_wait_rejects_slow_safe_probe(tmp_path, monkeypatch):
    now, sleeps = _fake_clock(monkeypatch)

    def slow_safe_probe():
        now[0] = launcher.RECOVERY_MEMORY_WAIT["timeout_seconds"] + 1
        return True

    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        slow_safe_probe)
    with pytest.raises(ValueError, match="unsafe before row second dispatch"):
        launcher._wait_for_recovery_row_memory(
            _wait_config(), tmp_path / "HOLD", "row second dispatch")
    assert sleeps == []


def test_recovery_memory_wait_honors_hold_on_next_poll(tmp_path, monkeypatch):
    _now, sleeps = _fake_clock(monkeypatch)
    hold = tmp_path / "HOLD"
    checks = []

    def unsafe_then_hold(seconds):
        sleeps.append(seconds)
        hold.write_text("pause")

    monkeypatch.setattr(launcher.time, "sleep", unsafe_then_hold)
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        lambda: checks.append(True) or False)

    with pytest.raises(ValueError, match="HOLD before row dispatch"):
        launcher._wait_for_recovery_row_memory(
            _wait_config(), hold, "row second dispatch")

    assert checks == [True]
    assert sleeps == [60]


def test_recovery_initial_admission_never_waits(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, retention=_retention(tmp_path),
                  **_wait_config(), **_controls())
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        lambda: False)
    monkeypatch.setattr(launcher.time, "sleep",
                        lambda *_: pytest.fail("initial admission waited"))
    monkeypatch.setattr(launcher, "supervise",
                        lambda *args, **kwargs: pytest.fail("provider launched"))

    with pytest.raises(ValueError, match="unsafe before reservation"):
        launcher.run(tmp_path / "config.json", "synthetic", arm=True)
    assert not Path(config["output"]).exists()


def test_recovery_source_fence_and_hold_follow_safe_wait(tmp_path, monkeypatch):
    from shengji.luna import benchmark_terminal

    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, retention=_retention(tmp_path),
                  **_wait_config(), **_controls())
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, "LOCK", tmp_path / "lock")
    levels = iter((True, True, True))
    checks = []

    def memory():
        checks.append(True)
        return next(levels)

    monkeypatch.setattr(launcher.benchmark_batch, "assert_memory_headroom",
                        memory)
    monkeypatch.setattr(
        benchmark_terminal, "validate_scheduled_terminal",
        lambda report, **kwargs: {"status": "scheduled-terminal", "completed": 40,
                                  "failed": 0, "unattempted": 0, "scheduled": 40})
    fences = []
    hold = tmp_path / "HOLD"

    def fence(_stamps):
        fences.append(True)
        if len(fences) == 4:
            hold.write_text("pause after source fence")

    monkeypatch.setattr(launcher, "fence", fence)

    def supervise(command, *, row, output, **kwargs):
        output.mkdir()
        report = _report(config["seeds"])
        report["config"]["retained_attempts"] = _binding()
        (output / "result.json").write_text(json.dumps(report))
        return {"returncode": 0, "status": "exited", "row": row}

    monkeypatch.setattr(launcher, "supervise", supervise)
    with pytest.raises(ValueError, match="HOLD before row dispatch"):
        launcher.run(tmp_path / "config.json", "synthetic", arm=True)
    assert len(fences) == 4
    assert len(checks) == 3
    assert not (Path(config["output"]) / launcher.RECOVERY_ROWS[1]).exists()


@pytest.mark.parametrize("schema,value", [
    (launcher.RECOVERY_SCHEMA, {}),
    (launcher.RECOVERY_SCHEMA, {"timeout_seconds": 1799, "poll_seconds": 60}),
    (launcher.RECOVERY_SCHEMA, {"timeout_seconds": 1800.0, "poll_seconds": 60}),
    (launcher.RECOVERY_SCHEMA, {"timeout_seconds": 1800, "poll_seconds": 60.0}),
    ("sol-nine-policy-campaign-v2", dict(launcher.RECOVERY_MEMORY_WAIT)),
])
def test_memory_wait_config_is_pinned_and_recovery_only(tmp_path, schema, value):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    config.update(schema=schema, memory_wait=value)
    if schema == launcher.RECOVERY_SCHEMA:
        source = tmp_path / "prior"
        source.mkdir()
        (source / "result.json").write_text("{}")
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"source_directory": str(source)}))
        config.update(rows=list(launcher.RECOVERY_ROWS),
                      **_controls(),
                      failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8,
                      retention={"m1-prior": {
                          "plan": str(plan),
                          "sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                      }})
    else:
        config["provider_capacity_retry_delays"] = [15, 30, 60]
    path.write_text(json.dumps(config))

    with pytest.raises(ValueError, match="memory_wait|recovery fields"):
        launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())
