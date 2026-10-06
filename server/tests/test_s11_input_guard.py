import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import s11_input_guard as guard


def test_census_counts_only_owned_group():
    assert guard.group_rss('10 1 10 20\n11 10 10 30\n99 1 99 90000\n', 10) == 50 * 1024


def test_terminal_census_rejects_leftover_even_zero_rss_member():
    assert guard.group_rss('99 1 99 90000\n', 10, finished=True) == 0
    with pytest.raises(ValueError):
        guard.group_rss('11 1 10 0\n', 10, finished=True)


@pytest.mark.parametrize('snapshot', ['', '10 1 10 20', '10 1 10\n',
    '10 1 10 -2\n', '10 1 10 20\n10 1 10 30\n', '11 1 10 20\n',
    '10 1 99 20\n', '10 1 10 20\n11 10 11 30\n'])
def test_incomplete_or_escaped_census_refused(snapshot):
    with pytest.raises(ValueError):
        guard.group_rss(snapshot, 10)


def test_ps_failure_is_not_empty_safe_census(monkeypatch):
    def fail(*a, **kw):
        raise subprocess.CalledProcessError(1, ['/bin/ps'])
    monkeypatch.setattr(guard.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        guard.sample_group_rss(123, 0.25)


def test_no_signal_after_leader_reaped(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(guard.os, 'killpg', lambda *a: pytest.fail('stale PGID signal'))
    with pytest.raises(ValueError, match='reaped'):
        guard._terminate(SimpleNamespace(pid=123, returncode=0), 0.01)


def test_cleanup_signals_before_any_reap(monkeypatch):
    events = []
    class Child:
        pid = 123
        returncode = None
        def poll(self):
            pytest.fail('reaped before final signal')
        def wait(self):
            events.append('reap')
    monkeypatch.setattr(guard.os, 'killpg', lambda *a: events.append(a[1]))
    guard._terminate(Child(), 0.001)
    import signal
    assert events == [signal.SIGTERM, signal.SIGKILL, 'reap']


@pytest.mark.parametrize('mode', ['success', 'error', 'deadline', 'rss', 'census'])
def test_real_disposable_process_guard(tmp_path, monkeypatch, mode):
    code = 'import time; time.sleep(0.5)'
    if mode == 'error':
        code += '; raise SystemExit(7)'
    if mode in ('deadline', 'rss', 'census'):
        code = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(10)'
    if mode == 'census':
        def fail(*a):
            raise ValueError('private census diagnostic')
        monkeypatch.setattr(guard, 'sample_group_rss', fail)
    server = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(server))
    with (tmp_path / 'worker.log').open('wb') as log:
        result = guard.supervise_s11_input([sys.executable, '-c', code],
            cwd=server, env=env, log=log, python=sys.executable,
            wall_seconds=0.4 if mode == 'deadline' else 5,
            rss_threshold_bytes=1 if mode == 'rss' else 512 << 20,
            sample_seconds=0.05, term_grace_seconds=0.1)
    expected = {'deadline': 'wall-timeout', 'rss': 'rss-threshold',
                'census': 'census-failed'}.get(mode, 'process-exited')
    assert result['exit_cause'] == expected
    if mode in ('success', 'error'):
        assert result['returncode'] == (0 if mode == 'success' else 7)
        assert result['sample_count'] > 0 and result['peak_sampled_rss_bytes'] > 0
    else:
        assert result['returncode'] != 0
    assert result['elapsed_seconds'] < 5
    with pytest.raises(ProcessLookupError):
        os.kill(result['pid'], 0)
    assert 'private' not in str(result)


def test_term_ignoring_worker_is_not_left_live(tmp_path):
    marker = tmp_path / 'child-pid'
    code = ('import os,signal,time; from pathlib import Path; '
            'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
            f'Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(10)')
    server = Path(__file__).resolve().parents[1]
    with (tmp_path / 'log').open('wb') as log:
        result = guard.supervise_s11_input([sys.executable, '-c', code],
            cwd=server, env=dict(os.environ, PYTHONPATH=str(server)), log=log,
            wall_seconds=0.5, sample_seconds=0.05, term_grace_seconds=0.1)
    assert result['exit_cause'] == 'wall-timeout'
    assert marker.exists()
    pid = int(marker.read_text())
    state = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat='],
        capture_output=True, text=True, timeout=1)
    # Reparented zombies may await OS reaping, but no worker remains live.
    assert state.returncode == 1 or state.stdout.strip().startswith('Z')
