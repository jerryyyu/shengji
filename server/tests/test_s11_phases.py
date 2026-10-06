import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval import s11_phases as phases
from shengji.eval.s11_input_bundle import publish_s11_input_bundle
from test_s11_schedule import slots, trajectory, refusal, PIN
from test_s11_collection import factory

PACKET = 'c' * 64


def setup(tmp_path, slots):
    # First valid selection must skip refusals, not replace or examine values.
    slots[0] = refusal(slots[0])
    path = tmp_path / 'bundle.json'
    admitted = publish_s11_input_bundle(slots, path, manifest_sha256=PIN,
                                        packet_sha256='b' * 64)
    run = tmp_path / 'run'
    run.mkdir(mode=0o700)
    release = tmp_path / 'RELEASE'
    release.write_text(PACKET + '\n' + phases.COST + '\n')
    calls = dict(leaves=0, policy=[], bots=[])
    args = dict(release_path=release, packet_sha256=PACKET,
                bundle_raw=path.read_bytes(), bundle_sha256=admitted['bundle_sha256'],
                directory=run, bot_factory=factory(calls, seed=0))
    return args, calls


def cost(tmp_path, args):
    result = phases.run_s11_phase(**args, phase=phases.COST, output_dir=tmp_path / 'cost')
    raw = (tmp_path / 'cost/result.json').read_bytes()
    return result, raw, hashlib.sha256(raw).hexdigest()


def full(tmp_path, args, raw, pin):
    return phases.run_s11_phase(**args, phase=phases.FULL,
        output_dir=tmp_path / 'full', cost_receipt_raw=raw, cost_receipt_sha256=pin)


def test_cost_release_never_unlocks_full_and_full_reuses_exact_capture(tmp_path, slots):
    args, calls = setup(tmp_path, slots)
    result, raw, pin = cost(tmp_path, args)
    assert result['draw_index'] == 1 and result['root_id'] == slots[1]['root_id']
    assert len(calls['policy']) == 1 and len(calls['bots']) == 2
    assert not (args['directory'] / 'summary.json').exists()
    with pytest.raises(ValueError, match='phase release mismatch'):
        full(tmp_path, args, raw, pin)
    assert len(calls['policy']) == 1 and not (tmp_path / 'full').exists()
    args['release_path'].write_text(PACKET + '\n' + phases.FULL + '\n')
    summary = full(tmp_path, args, raw, pin)
    assert summary['valid_count'] == 63 and summary['refused_count'] == 1
    assert len(calls['policy']) == 63  # NOT 64: first valid root was reused.
    assert len(calls['bots']) == 126


def test_cost_receipt_exact_outcome_blind_whitelist(tmp_path, slots, capsys):
    args, calls = setup(tmp_path, slots)
    result, _, _ = cost(tmp_path, args)
    assert set(result) == {'schema', 'packet_sha256', 'bundle_sha256', 'root_id',
                           'draw_index', 'capture_sha256', 'metrics'}
    assert set(result['metrics']) == {'status', 'elapsed_seconds', 'batches', 'cells'}
    assert result['metrics']['cells'] == calls['leaves']
    assert result['metrics']['status'] == 'completed'
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('damage', ['missing', 'changed', 'self-resealed'])
def test_damaged_pilot_cannot_recollect_or_start_next_root(tmp_path, slots, damage):
    args, calls = setup(tmp_path, slots)
    result, raw, pin = cost(tmp_path, args)
    capture = args['directory'] / hashlib.sha256(result['root_id'].encode()).hexdigest() / 'completed.json'
    capture.chmod(0o600)
    if damage == 'missing':
        capture.unlink()
    elif damage == 'changed':
        capture.write_bytes(b'not JSON; digest must refuse before parsing')
    else:
        envelope = json.loads(capture.read_bytes())
        envelope['payload']['result']['value_capture']['batches'] += 1
        canonical = json.dumps(envelope['payload'], sort_keys=True, separators=(',', ':')).encode()
        envelope['sha256'] = hashlib.sha256(canonical).hexdigest()
        capture.write_text(json.dumps(envelope))
    if capture.exists():
        capture.chmod(0o400)
    args['release_path'].write_text(PACKET + '\n' + phases.FULL + '\n')
    with pytest.raises(ValueError, match='completion'):
        full(tmp_path, args, raw, pin)
    assert len(calls['policy']) == 1
    assert not (args['directory'] / 'summary.json').exists()


@pytest.mark.parametrize('mutation', ['phase', 'packet', 'hold', 'fifo', 'symlink'])
def test_release_refusal_precedes_bundle_or_model_access(tmp_path, slots, mutation):
    args, calls = setup(tmp_path, slots)
    release = args['release_path']
    if mutation == 'phase':
        release.write_text(PACKET + '\n' + phases.FULL + '\n')
    elif mutation == 'packet':
        release.write_text('d' * 64 + '\n' + phases.COST + '\n')
    elif mutation == 'hold':
        (tmp_path / 'HOLD').touch()
    elif mutation == 'fifo':
        import os
        release.unlink(); os.mkfifo(release)
    else:
        release.rename(tmp_path / 'elsewhere')
        release.symlink_to(tmp_path / 'elsewhere')
    args['bundle_raw'] = b'not json'
    with pytest.raises((ValueError, OSError)):
        cost(tmp_path, args)
    assert not calls['bots'] and not (tmp_path / 'cost').exists()


def test_cost_failure_preserves_claim_and_never_retries(tmp_path, slots):
    args, calls = setup(tmp_path, slots)
    def fail():
        raise RuntimeError('synthetic inference failure; max_saved=99')
    args['bot_factory'] = fail
    with pytest.raises(ValueError, match='cost incomplete'):
        cost(tmp_path, args)
    assert len(list(args['directory'].glob('*/failed.json'))) == 1
    assert not (tmp_path / 'cost/result.json').exists()
    assert 'max_saved' not in (tmp_path / 'cost/refusal.json').read_text()
    with pytest.raises(FileExistsError):
        cost(tmp_path, args)
    # Even a different output path cannot reuse/retry this collection directory.
    with pytest.raises(ValueError, match='cost incomplete'):
        phases.run_s11_phase(**args, phase=phases.COST, output_dir=tmp_path / 'second')


def test_wrong_cost_receipt_pin_blocks_before_capture_parse(tmp_path, slots):
    args, calls = setup(tmp_path, slots)
    _, raw, pin = cost(tmp_path, args)
    args['release_path'].write_text(PACKET + '\n' + phases.FULL + '\n')
    with pytest.raises(ValueError, match='cost receipt digest'):
        full(tmp_path, args, raw + b' ', pin)
    assert len(calls['policy']) == 1


@pytest.mark.parametrize('stop', ['hold', 'budget'])
def test_late_stop_keeps_capture_but_never_publishes_cost_success(tmp_path, slots, stop):
    args, calls = setup(tmp_path, slots)
    def budget():
        if list(args['directory'].glob('*/completed.json')):
            if stop == 'hold':
                (tmp_path / 'HOLD').touch()
            else:
                raise TimeoutError('synthetic deadline')
    args['check_budget'] = budget
    with pytest.raises(ValueError, match='cost incomplete'):
        cost(tmp_path, args)
    assert len(calls['policy']) == 1
    assert len(list(args['directory'].glob('*/completed.json'))) == 1
    assert not (tmp_path / 'cost/result.json').exists()
    assert not (tmp_path / 'cost/receipt.json').exists()
