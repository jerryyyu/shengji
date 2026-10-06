import hashlib
import json

import pytest

from scripts import s11_input_worker as worker


@pytest.fixture
def packet(tmp_path):
    config = dict(schema='s11-mini-input-worker-v1', manifest_path='/unused/manifest',
                  manifest_sha256='a' * 64, root='/unused/root', output='/unused/private',
                  wall_seconds=900, max_manifest_bytes=8 << 20)
    raw = json.dumps(config).encode()
    path = tmp_path / 'packet.json'
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), config


def test_dry_run_never_enters_worker(packet, monkeypatch, capsys):
    path, pin, _ = packet
    monkeypatch.setattr(worker, 'run_worker', lambda *a: pytest.fail('execution'))
    assert worker.main(['--packet', str(path), '--sha256', pin]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'unarmed'


@pytest.mark.parametrize('gate', ['missing', 'wrong', 'hold', 'dangling-hold'])
def test_release_and_hold_before_execution(packet, monkeypatch, capsys, gate):
    path, pin, _ = packet
    if gate != 'missing':
        (path.parent / 'RELEASE').write_text(('b' * 64 if gate == 'wrong' else pin) + '\n')
    if gate == 'hold':
        (path.parent / 'HOLD').touch()
    if gate == 'dangling-hold':
        (path.parent / 'HOLD').symlink_to(path.parent / 'absent')
    monkeypatch.setattr(worker, 'run_worker', lambda *a: pytest.fail('execution'))
    assert worker.main(['--packet', str(path), '--sha256', pin, '--run']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'


@pytest.mark.parametrize('fail', [False, True])
def test_released_worker_called_once_and_output_is_sanitized(packet, monkeypatch, capsys, fail):
    path, pin, config = packet
    (path.parent / 'RELEASE').write_text(pin + '\n')
    calls = []
    def run(*args):
        calls.append(args)
        if fail:
            raise ValueError('SECRET outcome=42')
    monkeypatch.setattr(worker, 'run_worker', run)
    assert worker.main(['--packet', str(path), '--sha256', pin, '--run']) == int(fail)
    assert calls == [(config, pin)]
    out = capsys.readouterr()
    assert 'SECRET' not in out.out and not out.err


@pytest.mark.parametrize('key,value', [('wall_seconds', True), ('wall_seconds', 901),
    ('max_manifest_bytes', 1), ('root', '../private'), ('output', '/a/../b'),
    ('manifest_sha256', 'bad'), ('extra', 'SECRET')])
def test_invalid_packet_refused(packet, key, value):
    _, _, config = packet
    config[key] = value
    raw = json.dumps(config).encode()
    with pytest.raises(ValueError):
        worker.validate_packet(raw, hashlib.sha256(raw).hexdigest())


def test_digest_before_parse_and_duplicate_fields_refused(packet):
    with pytest.raises(ValueError, match='digest'):
        worker.validate_packet(b'SECRET not JSON', 'a' * 64)
    path, _, _ = packet
    raw = path.read_bytes()[:-1] + b', "wall_seconds":900}'
    with pytest.raises(ValueError, match='duplicate'):
        worker.validate_packet(raw, hashlib.sha256(raw).hexdigest())


def test_worker_sets_limits_before_admission(packet, monkeypatch):
    from shengji.eval import s11_admission_once
    _, pin, config = packet
    events = []
    monkeypatch.setenv('OMP_NUM_THREADS', '99')
    monkeypatch.setattr(worker.os, 'nice', lambda n: events.append(('nice', n)))
    monkeypatch.setattr(worker.signal, 'signal', lambda *a: events.append(('signal', a)))
    monkeypatch.setattr(worker.signal, 'setitimer', lambda *a: events.append(('timer', a)))
    def admit(*args, **kwargs):
        assert worker.os.environ['OMP_NUM_THREADS'] == '1'
        assert [e[0] for e in events] == ['nice', 'signal', 'timer']
        assert args == (config['manifest_path'], config['root'], config['output'])
        assert kwargs['packet_sha256'] == pin
        events.append(('admit',))
    monkeypatch.setattr(s11_admission_once, 'admit_s11_inputs_once', admit)
    worker.run_worker(config, pin)
    assert len(events) == 4


def test_guard_to_cli_to_real_admission_on_synthetic_frame(tmp_path):
    import os
    from pathlib import Path
    import sys
    from scripts.s11_input_guard import supervise_s11_input
    from test_s11_input_join import input_frame
    manifest, manifest_pin, shards = input_frame(tmp_path)
    for cluster, raw in shards.items():
        (tmp_path / 'shards' / f'cluster-{cluster:06d}.jsonl').write_bytes(raw)
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_bytes(manifest)
    output = tmp_path / 'private'
    output.mkdir(mode=0o700)
    config = dict(schema='s11-mini-input-worker-v1', manifest_path=str(manifest_path),
                  manifest_sha256=manifest_pin, root=str(tmp_path), output=str(output),
                  wall_seconds=900, max_manifest_bytes=8 << 20)
    packet = tmp_path / 'packet.json'
    raw = json.dumps(config).encode()
    packet.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'RELEASE').write_text(pin + '\n')
    server = Path(__file__).resolve().parents[1]
    with (tmp_path / 'worker.log').open('wb') as log:
        result = supervise_s11_input([sys.executable, '-m', 'scripts.s11_input_worker',
            '--packet', str(packet), '--sha256', pin, '--run'], cwd=server,
            env=dict(os.environ, PYTHONPATH=str(server), OMP_NUM_THREADS='1'),
            log=log, python=sys.executable, wall_seconds=30)
    assert result['exit_cause'] == 'process-exited' and result['returncode'] == 0
    receipt = json.loads((output / 'receipt.json').read_bytes())
    assert receipt['packet_sha256'] == pin
    assert receipt['counts']['unattempted'] == 64
    assert hashlib.sha256((output / 'bundle.json').read_bytes()).hexdigest() == receipt['bundle_sha256']
    # This proves private staging only. No public promotion or real corpus.
    assert json.loads((tmp_path / 'worker.log').read_text()) == {
        'status': 'private-staging-complete', 'packet_sha256': pin}
