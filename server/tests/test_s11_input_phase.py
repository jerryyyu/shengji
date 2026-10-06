import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from scripts import s11_input_phase as phase


@pytest.fixture
def phase_packet(tmp_path):
    output, control = tmp_path / 'private', tmp_path / 'control'
    output.mkdir(mode=0o700)
    control.mkdir(mode=0o700)
    config = dict(schema='s11-mini-input-worker-v2', stage_from_perf=False, manifest_path=str(tmp_path / 'manifest'),
        manifest_sha256='a' * 64, root=str(tmp_path), output=str(output),
        wall_seconds=900, max_manifest_bytes=8 << 20)
    packet = tmp_path / 'packet.json'
    raw = json.dumps(config).encode()
    packet.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'RELEASE').write_text(pin + '\n')
    return packet, pin, config, output, control


def invoke(p):
    packet, pin, _, _, control = p
    return phase.run_input_phase(packet, pin, control,
        cwd=Path(__file__).resolve().parents[1], env=os.environ, python=sys.executable)


@pytest.mark.parametrize('cause,code', [('rss-threshold', -9), ('wall-timeout', -9),
    ('census-failed', -15), ('process-exited', 1)])
def test_guard_failure_never_opens_or_accepts_bundle(phase_packet, monkeypatch, cause, code):
    monkeypatch.setattr(phase, 'supervise_s11_input', lambda *a, **kw:
        dict(exit_cause=cause, returncode=code))
    monkeypatch.setattr(phase, '_bundle_digest', lambda *a: pytest.fail('opened bundle'))
    with pytest.raises(ValueError, match='disposition'):
        invoke(phase_packet)
    control = phase_packet[-1]
    assert (control / 'started.json').exists() and (control / 'guard.json').exists()
    assert not (control / 'accepted.json').exists()
    with pytest.raises(ValueError, match='fresh'):
        invoke(phase_packet)


def test_guard_exception_retained_marker_no_retry_no_private_chain(phase_packet, monkeypatch):
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise ValueError('SECRET record')
    monkeypatch.setattr(phase, 'supervise_s11_input', fail)
    with pytest.raises(ValueError) as caught:
        invoke(phase_packet)
    assert caught.value.__context__ is None
    assert 'SECRET' not in str(caught.value)
    with pytest.raises(ValueError, match='fresh'):
        invoke(phase_packet)
    assert calls == [1]


@pytest.mark.parametrize('gate', ['hold', 'release', 'occupied', 'permissions'])
def test_gate_refuses_before_worker(phase_packet, monkeypatch, gate):
    packet, _, _, _, control = phase_packet
    if gate == 'hold':
        (packet.parent / 'HOLD').touch()
    elif gate == 'release':
        (packet.parent / 'RELEASE').write_text('wrong')
    elif gate == 'occupied':
        (control / 'started.json').touch()
    else:
        control.chmod(0o755)
    monkeypatch.setattr(phase, 'supervise_s11_input', lambda *a, **kw: pytest.fail('spawn'))
    with pytest.raises(ValueError):
        invoke(phase_packet)


@pytest.mark.parametrize('damage', [None, 'late-hold', 'bundle', 'partial'])
def test_real_synthetic_worker_acceptance_and_no_reentry(phase_packet, monkeypatch, damage):
    from test_s11_input_join import input_frame
    packet, _, config, output, control = phase_packet
    manifest, manifest_pin, shards = input_frame(packet.parent)
    for cluster, raw in shards.items():
        (packet.parent / 'shards' / f'cluster-{cluster:06d}.jsonl').write_bytes(raw)
    Path(config['manifest_path']).write_bytes(manifest)
    config['manifest_sha256'] = manifest_pin
    raw = json.dumps(config).encode()
    packet.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    (packet.parent / 'RELEASE').write_text(pin + '\n')
    p = packet, pin, config, output, control
    supervise = phase.supervise_s11_input
    def run(*args, **kwargs):
        result = supervise(*args, **kwargs)
        assert result['exit_cause'] == 'process-exited' and result['returncode'] == 0
        if damage == 'late-hold':
            (packet.parent / 'HOLD').touch()
        elif damage == 'bundle':
            bundle = output / 'bundle.json'
            bundle.chmod(0o600)
            bundle.write_bytes(b'damaged')
            bundle.chmod(0o400)
        elif damage == 'partial':
            (output / '.receipt.json.partial').touch()
        return result
    monkeypatch.setattr(phase, 'supervise_s11_input', run)
    if damage:
        with pytest.raises(ValueError, match='disposition'):
            invoke(p)
        assert not (control / 'accepted.json').exists()
        assert (control / 'guard.json').exists() and (output / 'bundle.json').exists()
        return
    accepted = invoke(p)
    assert json.loads((control / 'accepted.json').read_bytes()) == accepted
    assert accepted['bundle_sha256'] == hashlib.sha256((output / 'bundle.json').read_bytes()).hexdigest()
    assert accepted['guard_sha256'] == hashlib.sha256((control / 'guard.json').read_bytes()).hexdigest()
    assert accepted['receipt_sha256'] == hashlib.sha256((output / 'receipt.json').read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='fresh'):
        invoke(p)
