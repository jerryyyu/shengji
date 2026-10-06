import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from scripts import s11_collection_phase as controller
from scripts.s11_collection_worker import validate_packet, main
from shengji.eval.s11_input_bundle import publish_s11_input_bundle
from shengji.eval.s11_persistence import _encode
from shengji.eval.s11_phases import COST, FULL
from test_s11_schedule import slots, trajectory, PIN
from test_s11_model import frozen, package


@pytest.fixture
def packet(tmp_path, slots, frozen):
    model, pins = frozen
    bundle = tmp_path / 'bundle.json'
    receipt = publish_s11_input_bundle(slots, bundle, manifest_sha256=PIN, packet_sha256='b'*64)
    accepted = dict(schema='s11-input-phase-accepted-v1', packet_sha256='b'*64,
        manifest_sha256=PIN, bundle_path=str(bundle), bundle_sha256=receipt['bundle_sha256'],
        receipt_sha256=hashlib.sha256(_encode(receipt)).hexdigest(), guard_sha256='d'*64)
    parent = tmp_path / 'input-accepted.json'
    parent.write_bytes(_encode(accepted))
    directory = tmp_path / 'run'
    directory.mkdir(mode=0o700)
    config = dict(schema='s11-collection-packet-v1',
        recipe='release38-unbudgeted-card-play-seed0-fill0',
        accepted_input=dict(path=str(parent), sha256=hashlib.sha256(parent.read_bytes()).hexdigest()),
        bundle=dict(path=str(bundle), sha256=receipt['bundle_sha256']),
        model=dict(path=str(model), **pins), directory=str(directory), phases={})
    for phase in (COST, FULL):
        release_dir = tmp_path / (phase + '-release')
        release_dir.mkdir()
        control = tmp_path / (phase + '-control')
        control.mkdir(mode=0o700)
        config['phases'][phase] = dict(release=str(release_dir / 'RELEASE'),
            control=str(control), output=str(tmp_path / (phase + '-private')),
            limits=dict(wall_seconds=120, rss_threshold_bytes=1 << 30,
                        sample_seconds=.1, term_grace_seconds=.1))
    path = tmp_path / 'packet.json'
    path.write_bytes(_encode(config))
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    for phase in (COST, FULL):
        Path(config['phases'][phase]['release']).write_text(pin + '\n' + phase + '\n')
    return path, pin, config


def invoke(packet, phase=COST, **kwargs):
    path, pin, _ = packet
    return controller.run_collection_phase(path, pin, phase,
        cwd=Path(__file__).resolve().parents[1], env=os.environ,
        python=sys.executable, **kwargs)


def test_actual_guarded_model_cost_then_full(packet):
    accepted = invoke(packet)
    config = packet[2]
    costpath = Path(config['phases'][COST]['control']) / 'accepted.json'
    assert json.loads(costpath.read_bytes()) == accepted
    completed = list(Path(config['directory']).glob('*/completed.json'))
    assert len(completed) == 1
    stamp = completed[0].stat()
    result = invoke(packet, FULL, cost_path=str(costpath),
                    cost_sha=hashlib.sha256(costpath.read_bytes()).hexdigest())
    assert result['schema'] == 's11-full-parent-accepted-v1'
    assert 'max_saved' not in json.dumps(result)
    assert len(list(Path(config['directory']).glob('*/completed.json'))) == 64
    assert all(getattr(completed[0].stat(), k) == getattr(stamp, k)
               for k in ('st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
    with pytest.raises(ValueError, match='fresh'):
        invoke(packet)


@pytest.mark.parametrize('damage', ['hold', 'wrong-phase', 'occupied'])
def test_admission_refusal_never_spawns(packet, monkeypatch, damage):
    config = packet[2]['phases'][COST]
    if damage == 'hold':
        Path(config['release']).with_name('HOLD').touch()
    elif damage == 'wrong-phase':
        Path(config['release']).write_text(packet[1] + '\n' + FULL + '\n')
    else:
        Path(config['output']).mkdir()
    monkeypatch.setattr(controller, 'supervise_s11_input', lambda *a, **k: pytest.fail('spawn'))
    with pytest.raises(ValueError):
        invoke(packet)


@pytest.mark.parametrize('damage', ['late-hold', 'extra-file', 'result-pin'])
def test_parent_refuses_private_success_and_preserves_attempt(packet, monkeypatch, damage):
    real = controller.supervise_s11_input
    def guarded(*args, **kwargs):
        result = real(*args, **kwargs)
        cfg = packet[2]['phases'][COST]
        if damage == 'late-hold':
            Path(cfg['release']).with_name('HOLD').touch()
        elif damage == 'extra-file':
            (Path(cfg['output']) / 'unexpected').touch()
        else:
            p = Path(cfg['output']) / 'result.json'
            p.chmod(0o600)
            p.write_bytes(p.read_bytes() + b' ')
        return result
    monkeypatch.setattr(controller, 'supervise_s11_input', guarded)
    with pytest.raises(ValueError, match='preserve') as caught:
        invoke(packet)
    assert caught.value.__context__ is None
    control = Path(packet[2]['phases'][COST]['control'])
    assert (control / 'started.json').exists() and not (control / 'accepted.json').exists()
    assert len(list(Path(packet[2]['directory']).glob('*/completed.json'))) == 1


def test_guard_failure_does_not_read_private_output(packet, monkeypatch):
    monkeypatch.setattr(controller, 'supervise_s11_input', lambda *a, **k:
        dict(schema='s11-input-guard-v1', exit_cause='wall-timeout', returncode=-9))
    with pytest.raises(ValueError, match='preserve'):
        invoke(packet)
    assert not Path(packet[2]['phases'][COST]['output']).exists()
    with pytest.raises(ValueError, match='fresh'):
        invoke(packet)


def test_worker_dry_run_and_packet_overlap_refusal(packet, capsys):
    path, pin, config = packet
    assert main(['--packet', str(path), '--sha256', pin, '--phase', COST]) == 0
    assert capsys.readouterr().out == '{"status": "unarmed"}\n'
    assert not Path(config['phases'][COST]['output']).exists()
    config['phases'][FULL]['output'] = config['directory']
    raw = _encode(config)
    with pytest.raises(ValueError, match='disjoint'):
        validate_packet(raw, hashlib.sha256(raw).hexdigest())


def test_bad_accepted_input_refuses_before_worker_spawn(packet, monkeypatch):
    Path(packet[2]['accepted_input']['path']).write_bytes(b'bad acceptance')
    monkeypatch.setattr(controller, 'supervise_s11_input', lambda *a, **k: pytest.fail('spawn'))
    with pytest.raises(ValueError, match='preserve'):
        invoke(packet)
    assert not Path(packet[2]['phases'][COST]['output']).exists()


def test_wrong_cost_parent_pin_blocks_full_before_spawn(packet, monkeypatch):
    invoke(packet)
    path = str(Path(packet[2]['phases'][COST]['control']) / 'accepted.json')
    monkeypatch.setattr(controller, 'supervise_s11_input', lambda *a, **k: pytest.fail('spawn'))
    with pytest.raises(ValueError, match='preserve'):
        invoke(packet, FULL, cost_path=path, cost_sha='a'*64)
    assert len(list(Path(packet[2]['directory']).glob('*/completed.json'))) == 1
    assert not Path(packet[2]['phases'][FULL]['output']).exists()


def test_private_guard_exception_suppressed(packet, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('SECRET model values')
    monkeypatch.setattr(controller, 'supervise_s11_input', fail)
    with pytest.raises(ValueError, match='preserve') as caught:
        invoke(packet)
    assert caught.value.__context__ is None and 'SECRET' not in str(caught.value)
