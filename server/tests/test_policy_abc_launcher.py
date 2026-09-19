import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

spec = importlib.util.spec_from_file_location('abc_launcher',
    Path(__file__).parents[1] / 'scripts' / 'policy_abc_launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_frozen_commands():
    arms = launcher.commands(Path('/python'), Path('/model'), Path('/output'))
    assert [name for name, _ in arms] == ['A', 'B', 'C']
    for name, cmd in arms:
        assert cmd[cmd.index('--seed0') + 1] == '625100000'
        assert cmd[cmd.index('--deals') + 1] == '800'
        assert cmd[cmd.index('--workers') + 1] == '12'
        assert cmd[cmd.index('--checkpoint-sha256') + 1] == launcher.CHECKPOINT
        assert cmd[cmd.index('--out') + 1] == '/output/' + name
    assert arms[1][1][arms[1][1].index('--worlds') + 1] == '16'
    assert arms[2][1][arms[2][1].index('--control') + 1] == 'policy-world'


@pytest.mark.parametrize('patch', [{'complete': 799}, {'errors': ['failed']}, {'expected': 799}])
def test_partial_results_refused(tmp_path, patch):
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(dict(expected=800, complete=800, errors=[]) | patch))
    with pytest.raises(RuntimeError, match='800 clean pairs'):
        launcher.validate_summary(path)


def test_clean_summary(tmp_path):
    path = tmp_path / 'summary.json'
    path.write_text(json.dumps(dict(expected=800, complete=800, errors=[])))
    launcher.validate_summary(path)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process-group supervisor')
def test_timeout_kills_only_owned_group_and_keeps_log(tmp_path):
    log = tmp_path / 'arm.log'
    with pytest.raises(subprocess.TimeoutExpired):
        launcher.run_arm([sys.executable, '-u', '-c',
            'import time; print("partial receipt"); time.sleep(20)'],
            env={}, cwd=tmp_path, log=log, seconds=.3)
    assert log.read_text() == 'partial receipt\n'


def test_nonzero_exit_refuses_and_preserves_log(tmp_path):
    log = tmp_path / 'arm.log'
    with pytest.raises(RuntimeError, match='exited 7'):
        launcher.run_arm([sys.executable, '-c', 'raise SystemExit(7)'],
            env={}, cwd=tmp_path, log=log)
    assert log.exists()


def test_group_cleanup_targets_only_created_pid(monkeypatch):
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(launcher.os, 'killpg', lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(launcher.time, 'sleep', lambda seconds: None)
    process = SimpleNamespace(pid=456, wait=lambda: calls.append('reaped'))
    launcher.stop_owned_group(process)
    assert calls == [(456, launcher.signal.SIGTERM),
                     (456, launcher.signal.SIGKILL), 'reaped']


def test_resource_guard_refuses_occupied_host(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(Path, 'read_text', lambda *a: 'MemAvailable: 32000000 kB\n')
    monkeypatch.setattr(launcher.os, 'sched_getaffinity', lambda *a: set(range(16)), raising=False)
    monkeypatch.setattr(launcher.shutil, 'disk_usage', lambda *a: SimpleNamespace(free=10*1024**3))
    monkeypatch.setattr(launcher, 'busy_processes', lambda: [(123, 'paused peer job')])
    with pytest.raises(RuntimeError, match='occupied'):
        launcher.resource_guard(tmp_path)


@pytest.fixture
def isolated_main(monkeypatch, tmp_path):
    import hashlib
    checkpoint = tmp_path / 'model'
    checkpoint.write_bytes(b'fixture')
    monkeypatch.setattr(launcher, 'CHECKPOINT', hashlib.sha256(b'fixture').hexdigest())
    monkeypatch.setattr(launcher.sys, 'platform', 'linux')
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.SOURCE if 'rev-parse' in cmd else '')
    monkeypatch.setattr(launcher, 'resource_guard', lambda *a: None)
    monkeypatch.setattr(launcher, 'LOCKS', (tmp_path / 'lane', tmp_path / 'screen'))
    args = ['--source', str(tmp_path / 'source'), '--python', sys.executable,
            '--checkpoint', str(checkpoint), '--out', str(tmp_path / 'out')]
    return args, tmp_path / 'out'


def test_default_preflight_does_not_launch_or_write(monkeypatch, isolated_main):
    args, output = isolated_main
    def forbidden(*a, **kw):
        pytest.fail('preflight launched a job')
    monkeypatch.setattr(launcher, 'run_arm', forbidden)
    assert launcher.main(args) == 0
    assert not output.exists()
    assert not any(p.exists() for p in launcher.LOCKS)


def test_serial_arms_hold_both_locks_and_release(monkeypatch, isolated_main):
    args, output = isolated_main
    seen = []
    def fake(cmd, **kwargs):
        assert all(p.is_dir() for p in launcher.LOCKS)
        arm = Path(cmd[cmd.index('--out') + 1])
        seen.append(arm.name)
        arm.mkdir()
        (arm / 'summary.json').write_text(json.dumps(dict(expected=800, complete=800, errors=[])))
        assert kwargs['env'].get('SHENGJI_FAST') is None
    monkeypatch.setattr(launcher, 'run_arm', fake)
    assert launcher.main(args + ['--run']) == 0
    assert seen == ['A', 'B', 'C']
    assert not any(p.exists() for p in launcher.LOCKS)


def test_failed_arm_preserves_partial_and_never_advances(monkeypatch, isolated_main):
    args, output = isolated_main
    seen = []
    def failed(cmd, **kwargs):
        seen.append(cmd)
        kwargs['log'].write_text('partial')
        raise RuntimeError('refused')
    monkeypatch.setattr(launcher, 'run_arm', failed)
    with pytest.raises(RuntimeError, match='refused'):
        launcher.main(args + ['--run'])
    assert len(seen) == 1
    assert (output / 'A.log').read_text() == 'partial'
    assert not any(p.exists() for p in launcher.LOCKS)


def test_peer_lock_is_never_removed(monkeypatch, isolated_main):
    args, output = isolated_main
    peer = launcher.LOCKS[0]
    peer.mkdir()
    (peer / 'pid').write_text('123')
    with pytest.raises(RuntimeError, match='reservation held'):
        launcher.main(args + ['--run'])
    assert (peer / 'pid').read_text() == '123'
    assert not output.exists()
