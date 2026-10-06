import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from shengji.eval import s11_cost_handoff as handoff
from shengji.eval.s11_phases import COST, FULL, run_s11_phase
from shengji.eval.s11_persistence import _encode
from test_s11_phases import setup, cost, full
from test_s11_schedule import slots, trajectory

LIMITS = dict(wall_seconds=900, rss_threshold_bytes=512 << 20,
              sample_seconds=.25, term_grace_seconds=.5)


def prepared(tmp_path, slots):
    args, calls = setup(tmp_path, slots)
    result, raw, pin = cost(tmp_path, args)
    guard = dict(schema='s11-input-guard-v1', pid=42, exit_cause='process-exited',
        returncode=0, peak_sampled_rss_bytes=1024, sample_count=4,
        elapsed_seconds=60, memory_measure=handoff._MEASURE, **LIMITS)
    inputs = dict(guard_raw=_encode(guard),
        claim_raw=(tmp_path / 'cost/claim.json').read_bytes(),
        receipt_raw=(tmp_path / 'cost/receipt.json').read_bytes(),
        result_raw=raw, packet_sha256=args['packet_sha256'],
        bundle_sha256=args['bundle_sha256'], first_slot=slots[1], limits=LIMITS)
    return args, calls, inputs


def authenticate(accepted, inputs):
    raw = _encode(accepted)
    return handoff.authenticate_cost(accepted_raw=raw,
        accepted_sha256=hashlib.sha256(raw).hexdigest(),
        **{k: inputs[k] for k in ('result_raw', 'packet_sha256', 'bundle_sha256',
                                  'first_slot', 'limits')})


def test_phase_to_parent_to_full_reuses_one_capture(tmp_path, slots):
    args, calls, inputs = prepared(tmp_path, slots)
    accepted = handoff.accept_cost(**inputs)
    pin = authenticate(accepted, inputs)
    assert pin == hashlib.sha256(inputs['result_raw']).hexdigest()
    assert set(accepted) == handoff._ACCEPTED_FIELDS
    assert set(accepted['guard']) == handoff._GUARD_FIELDS
    assert 'max_saved' not in json.dumps(accepted)
    # Authentication is not phase RELEASE: the original marker still refuses.
    with pytest.raises(ValueError, match='release mismatch'):
        full(tmp_path, args, inputs['result_raw'], pin)
    args['release_path'].write_text(args['packet_sha256'] + '\n' + FULL + '\n')
    summary = full(tmp_path, args, inputs['result_raw'], pin)
    assert summary['valid_count'] == 63 and len(calls['policy']) == 63


@pytest.mark.parametrize('key,value', [
    ('exit_cause', 'wall-timeout'), ('returncode', 1), ('returncode', False),
    ('sample_count', 0), ('peak_sampled_rss_bytes', 1 << 30),
    ('elapsed_seconds', 901), ('elapsed_seconds', float('nan')),
    ('wall_seconds', 1800), ('sample_seconds', True),
    ('private_error', 'secret model values'),
])
def test_bad_guard_refuses_before_private_result_parse(key, value, monkeypatch):
    guard = dict(schema='s11-input-guard-v1', pid=42, exit_cause='process-exited',
        returncode=0, peak_sampled_rss_bytes=1024, sample_count=1,
        elapsed_seconds=1, memory_measure=handoff._MEASURE, **LIMITS)
    guard[key] = value
    monkeypatch.setattr(handoff, '_cost_seal', lambda *a: pytest.fail('private access'))
    with pytest.raises(ValueError):
        handoff.accept_cost(guard_raw=json.dumps(guard).encode(), claim_raw=b'bad',
            receipt_raw=b'bad', result_raw=b'bad', packet_sha256='a'*64,
            bundle_sha256='b'*64, first_slot={}, limits=LIMITS)


@pytest.mark.parametrize('damage', ['receipt-pid', 'claim-pid', 'phase', 'result-pin',
                                   'result-bytes', 'timing', 'first-slot'])
def test_private_worker_evidence_mismatch_refuses(tmp_path, slots, damage):
    _, _, inputs = prepared(tmp_path, slots)
    receipt = json.loads(inputs['receipt_raw'])
    if damage == 'receipt-pid':
        receipt['pid'] += 1
    elif damage == 'claim-pid':
        claim = json.loads(inputs['claim_raw'])
        claim['pid'] = True
        inputs['claim_raw'] = _encode(claim)
    elif damage == 'phase':
        receipt['identity']['phase'] = FULL
    elif damage == 'result-pin':
        receipt['result_sha256'] = 'a' * 64
    elif damage == 'result-bytes':
        inputs['result_raw'] += b' '
    elif damage == 'timing':
        guard = json.loads(inputs['guard_raw'])
        guard['elapsed_seconds'] = 1e-12
        inputs['guard_raw'] = _encode(guard)
    else:
        inputs['first_slot'] = slots[2]
    inputs['receipt_raw'] = _encode(receipt)
    with pytest.raises(ValueError):
        handoff.accept_cost(**inputs)


def test_full_handoff_requires_parent_pin_not_private_worker_receipt(tmp_path, slots):
    _, _, inputs = prepared(tmp_path, slots)
    accepted = handoff.accept_cost(**inputs)
    raw = _encode(accepted)
    kwargs = {k: inputs[k] for k in ('result_raw', 'packet_sha256', 'bundle_sha256',
                                    'first_slot', 'limits')}
    with pytest.raises(ValueError, match='digest'):
        handoff.authenticate_cost(accepted_raw=raw, accepted_sha256='a'*64, **kwargs)
    private = inputs['receipt_raw']
    with pytest.raises(ValueError, match='context'):
        handoff.authenticate_cost(accepted_raw=private,
            accepted_sha256=hashlib.sha256(private).hexdigest(), **kwargs)
    accepted['identity']['packet_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='context'):
        authenticate(accepted, inputs)


def test_actual_guard_receipt_schema_supported(tmp_path):
    from scripts.s11_input_guard import supervise_s11_input
    with (tmp_path / 'private.log').open('xb') as log:
        guard = supervise_s11_input([sys.executable, '-c',
            'import time; time.sleep(.3)'], cwd=Path(__file__).resolve().parents[1],
            env=os.environ, log=log, **LIMITS)
    handoff._guard(guard, LIMITS)
