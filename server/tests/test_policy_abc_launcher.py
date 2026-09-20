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
    assert launcher.ARM_SECONDS == 3600
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


@pytest.mark.parametrize('qualify', [False, True])
def test_wk_commands(qualify):
    arms = launcher.commands(Path('/python'), Path('/model'), Path('/output'),
                             suite='wk-screen', qualify=qualify)
    assert [name for name, _ in arms] == ['W4_K8', 'W16_K8', 'W4_K16']
    for (_, cmd), (w, k) in zip(arms, [(4, 8), (16, 8), (4, 16)]):
        for key, value in {'--worlds': str(w), '--candidates': str(k),
                           '--mode': 'policy-value', '--control': 'mc-lcb',
                           '--seed0': '625490000' if qualify else '625500000',
                           '--deals': '12' if qualify else '800'}.items():
            assert cmd[cmd.index(key)+1] == value
    assert launcher.WK_QUALIFY_SEED + 12 < launcher.WK_SEED


@pytest.mark.parametrize('qualify', [False, True])
def test_wk_preflight_budget_and_no_launch(monkeypatch, isolated_main, capsys, qualify):
    args, output = isolated_main
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.REFERENCE_SOURCE if 'rev-parse' in cmd else '')
    monkeypatch.setattr(launcher, 'run_arm', lambda *a, **kw: pytest.fail('launch'))
    assert launcher.main(args + ['--suite', 'wk-screen'] + (['--qualify'] if qualify else [])) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['source'] == launcher.REFERENCE_SOURCE
    assert receipt['arm_timeout_seconds'] == (900 if qualify else 10800)
    assert receipt['analysis']['optional_extension'] is False
    assert not output.exists()


def test_strength_commands_share_fresh_deals_and_mc_lcb():
    arms = launcher.commands(Path('/python'), Path('/model'), Path('/output'),
                             suite='strength-screen')
    assert [name for name, _ in arms] == ['PV', 'PV_MC', 'PV_TREE']
    assert [cmd[cmd.index('--mode')+1] for _, cmd in arms] == [
        'policy-value', 'policy-selective-mc', 'policy-lookahead']
    for _, cmd in arms:
        for key, value in {'--seed0': '625400000', '--deals': '800',
                           '--control': 'mc-lcb', '--worlds': '4',
                           '--candidates': '8', '--workers': '12'}.items():
            assert cmd[cmd.index(key)+1] == value
        assert '--production-checkpoint' not in cmd
    assert launcher.STRENGTH_SEED >= launcher.REFERENCE_SEED + launcher.QUALIFY_DEALS


def test_strength_qualification_refused_before_io():
    with pytest.raises(ValueError, match='not qualification'):
        launcher.main(['--source', '/missing', '--python', '/missing',
                       '--checkpoint', '/missing', '--out', '/missing',
                       '--suite', 'strength-screen', '--run', '--qualify'])


def test_strength_cannot_relabel_as_qualification():
    with pytest.raises(ValueError, match='not qualification'):
        launcher.commands(Path('/python'), Path('/model'), Path('/output'),
                          suite='strength-screen', qualify=True)


def test_strength_preflight_retains_analysis_without_launch(monkeypatch, isolated_main, capsys):
    args, output = isolated_main
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.REFERENCE_SOURCE if 'rev-parse' in cmd else '')
    monkeypatch.setattr(launcher, 'run_arm', lambda *a, **kw: pytest.fail('launch'))
    assert launcher.main(args + ['--suite', 'strength-screen']) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['source'] == launcher.REFERENCE_SOURCE
    assert receipt['mode'] == 'strength-screen'
    assert receipt['launch_hold'] is False
    assert receipt['seed_reservation'] == '625400000:625400800; peer confirmed on PR521'
    assert receipt['arm_timeout_seconds'] == 10800
    assert receipt['total_arm_timeout_seconds'] == 32400
    assert receipt['analysis']['qualification_rows_excluded'] is True
    assert receipt['analysis']['optional_extension'] is False
    assert not output.exists()
    assert not any(p.exists() for p in launcher.LOCKS)


def test_strength_run_uses_approved_serial_budget(monkeypatch, isolated_main):
    args, output = isolated_main
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.REFERENCE_SOURCE if 'rev-parse' in cmd else '')
    seen = []
    def fake(cmd, **kwargs):
        assert all(p.is_dir() for p in launcher.LOCKS)
        assert kwargs['seconds'] == 10800
        assert cmd[cmd.index('--deals')+1] == '800'
        assert cmd[cmd.index('--control')+1] == 'mc-lcb'
        assert kwargs['env'].get('SHENGJI_FAST') is None
        arm = Path(cmd[cmd.index('--out')+1])
        seen.append(arm.name)
        arm.mkdir()
        (arm/'summary.json').write_text(json.dumps(dict(expected=800, complete=800, errors=[])))
    monkeypatch.setattr(launcher, 'run_arm', fake)
    assert launcher.main(args + ['--suite', 'strength-screen', '--run']) == 0
    assert seen == ['PV', 'PV_MC', 'PV_TREE']
    assert not any(p.exists() for p in launcher.LOCKS)


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


def test_preflight_preserves_venv_interpreter_symlink(isolated_main, tmp_path, capsys):
    args, output = isolated_main
    interpreter = tmp_path / 'venv-python'
    interpreter.symlink_to(sys.executable)
    args[args.index('--python') + 1] = str(interpreter)
    assert launcher.main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert all(cmd[0] == str(interpreter) for _, cmd in receipt['commands'])
    assert not output.exists()


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


@pytest.mark.parametrize('run', [False, True])
def test_qualification_is_bounded_and_never_promotes(monkeypatch, isolated_main, run):
    args, output = isolated_main
    seen = []
    def fake(cmd, **kwargs):
        assert all(p.is_dir() for p in launcher.LOCKS)
        assert cmd[cmd.index('--deals')+1] == '12'
        assert cmd[cmd.index('--workers')+1] == '12'
        assert kwargs['seconds'] == 900
        arm = Path(cmd[cmd.index('--out')+1])
        seen.append(arm.name)
        arm.mkdir()
        (arm/'summary.json').write_text(json.dumps(dict(expected=12, complete=12, errors=[])))
    monkeypatch.setattr(launcher, 'run_arm', fake)
    assert launcher.main(args+['--qualify']+(['--run'] if run else [])) == 0
    assert seen == (['A','B','C'] if run else [])
    assert not any(p.exists() for p in launcher.LOCKS)
    if run:
        receipt = json.loads((output/'launch-plan.json').read_text())
        assert receipt['mode'] == 'runtime-qualification'
        assert receipt['automatic_promotion'] is False
    else:
        assert not output.exists()


def test_qualification_partial_summary_refuses(tmp_path):
    path = tmp_path/'summary.json'
    path.write_text(json.dumps(dict(expected=12,complete=11,errors=[])))
    with pytest.raises(RuntimeError, match='12 clean pairs'):
        launcher.validate_summary(path, expected=12)


def test_followup_frozen_qualification_commands():
    arms = launcher.commands(Path('/python'), Path('/model'), Path('/out'),
                             qualify=True, suite='search-followup')
    assert [name for name, _ in arms] == ['D', 'E']
    for _, cmd in arms:
        assert cmd[cmd.index('--seed0')+1] == '625200000'
        assert cmd[cmd.index('--deals')+1] == '12'
        assert cmd[cmd.index('--worlds')+1] == '4'
        assert cmd[cmd.index('--candidates')+1] == '8'
    assert arms[0][1][-1] == 'mc-lcb'
    assert arms[1][1][-1] == 'policy-value'
    assert arms[1][1][arms[1][1].index('--mode')+1] == 'policy-selective-mc'


def test_followup_full_run_refused_before_any_io(isolated_main):
    args, output = isolated_main
    with pytest.raises(ValueError, match='qualification-only'):
        launcher.main(args + ['--suite', 'search-followup', '--run'])
    with pytest.raises(ValueError, match='qualification-only'):
        launcher.commands(Path('/python'), Path('/model'), output, suite='search-followup')
    assert not output.exists()


def test_followup_rejects_abc_source(isolated_main):
    args, _ = isolated_main
    with pytest.raises(RuntimeError, match='clean frozen'):
        launcher.main(args + ['--suite', 'search-followup', '--qualify'])


def test_followup_serial_qualification(monkeypatch, isolated_main):
    args, output = isolated_main
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.FOLLOWUP_SOURCE if 'rev-parse' in cmd else '')
    seen = []
    def fake(cmd, **kwargs):
        assert all(p.is_dir() for p in launcher.LOCKS)
        assert kwargs['seconds'] == 900
        arm = Path(cmd[cmd.index('--out')+1])
        seen.append(arm.name)
        arm.mkdir()
        (arm/'summary.json').write_text(json.dumps(dict(expected=12, complete=12, errors=[])))
    monkeypatch.setattr(launcher, 'run_arm', fake)
    assert launcher.main(args + ['--suite', 'search-followup', '--qualify', '--run']) == 0
    assert seen == ['D', 'E']
    receipt = json.loads((output/'launch-plan.json').read_text())
    assert receipt['source'] == launcher.FOLLOWUP_SOURCE
    assert receipt['automatic_promotion'] is False
    assert not any(p.exists() for p in launcher.LOCKS)


def test_reference_commands_separate_models_and_preserve_controls():
    arms = launcher.commands(Path('/python'), Path('/soft'), Path('/out'),
        suite='search-reference', qualify=True, production=Path('/prod.npz'))
    assert [name for name, _ in arms] == ['F', 'G']
    assert '--production-checkpoint' not in arms[0][1]
    assert arms[0][1][-1] == 'policy-value'
    assert arms[0][1][arms[0][1].index('--mode')+1] == 'policy-lookahead'
    for _, cmd in arms:
        assert cmd[cmd.index('--seed0')+1] == '625300000'
        assert cmd[cmd.index('--deals')+1] == '12'
        assert cmd[cmd.index('--checkpoint')+1] == '/soft'
    assert arms[1][1][-2:] == ['--production-checkpoint', '/prod.npz']


@pytest.mark.parametrize('suite,production', [('abc', '/prod'), ('search-reference', None)])
def test_reference_requires_exact_model_argument(suite, production):
    with pytest.raises(ValueError, match='required exactly'):
        launcher.commands(Path('/python'), Path('/soft'), Path('/out'),
                          qualify=True, suite=suite, production=production)


def test_reference_full_run_refused(isolated_main):
    args, _ = isolated_main
    with pytest.raises(ValueError, match='qualification-only'):
        launcher.main(args + ['--suite', 'search-reference', '--run'])


def test_reference_model_hash_checked_before_output(monkeypatch, isolated_main, tmp_path, capsys):
    import hashlib
    args, output = isolated_main
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.REFERENCE_SOURCE if 'rev-parse' in cmd else '')
    production = tmp_path/'prod.npz'
    production.write_bytes(b'production-fixture')
    argv = args + ['--suite', 'search-reference', '--qualify',
                   '--production-checkpoint', str(production)]
    with pytest.raises(RuntimeError, match='production checkpoint mismatch'):
        launcher.main(argv)
    assert not output.exists()
    monkeypatch.setattr(launcher, 'PRODUCTION_SHA256', hashlib.sha256(production.read_bytes()).hexdigest())
    assert launcher.main(argv) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['source'] == launcher.REFERENCE_SOURCE
    assert receipt['production_checkpoint_sha256'] == launcher.PRODUCTION_SHA256
    assert receipt['automatic_promotion'] is False
    assert not output.exists()
