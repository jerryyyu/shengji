import copy
import hashlib
from pathlib import Path

import pytest

from shengji.eval.s11_saved_readout import read_saved_s11
from shengji.eval.s11_persistence import _encode
from shengji.eval.s11_phases import COST, FULL
from shengji.eval.s11_report import project_s11, summarize_s11
from shengji.eval.s11_cost_handoff import _MEASURE
from test_fixed_tape_policy import _admission_fixture
from test_s11_collection_phase import packet, invoke
from test_s11_schedule import slots, trajectory
from test_s11_model import frozen, package

def sha(raw):
    return hashlib.sha256(raw).hexdigest()
LIMITS = dict(wall_seconds=120, rss_threshold_bytes=1 << 30,
              sample_seconds=.1, term_grace_seconds=.1)


@pytest.fixture
def prepared():
    _, root, _, capture = _admission_fixture('follow')
    report = project_s11('root', root, root.turn, capture, capture['actions'],
                        [0.] * len(capture['actions']))
    ids = [f'root-{i:02d}' for i in range(64)]
    reports = [dict(copy.deepcopy(report), root_id=k) for k in ids[:-2]]
    reports += [dict(root_id=k, status='refused', reason='public projection') for k in ids[-2:]]
    summary = summarize_s11(reports, ids)
    result = _encode(summary)
    identity = dict(packet_sha256='a'*64, bundle_sha256='b'*64,
                    cost_receipt_sha256='c'*64, phase=FULL)
    guard = dict(schema='s11-input-guard-v1', pid=42, exit_cause='process-exited',
        returncode=0, peak_sampled_rss_bytes=1024, sample_count=4,
        elapsed_seconds=1, memory_measure=_MEASURE, **LIMITS)
    accepted = dict(schema='s11-full-parent-accepted-v1', identity=identity,
        cost_parent_sha256='d'*64, worker_pid=43, guard=guard,
        guard_sha256=sha(_encode(guard)), claim_sha256='e'*64,
        receipt_sha256='f'*64, result_sha256=sha(result))
    kwargs = dict(accepted_raw=_encode(accepted), accepted_sha256=sha(_encode(accepted)),
        packet_sha256='a'*64, bundle_sha256='b'*64, cost_receipt_sha256='c'*64,
        cost_parent_sha256='d'*64, limits=LIMITS, scheduled_root_ids=ids,
        refused_root_ids=ids[-2:], read_result=lambda: result)
    return kwargs, accepted, summary


def test_saved_summary_not_recomputed_and_refusals_not_missing(prepared):
    args, _, summary = prepared
    calls = []
    args['read_result'] = lambda: calls.append(1) or _encode(summary)
    output = read_saved_s11(**args)
    assert calls == [1]
    assert output['summary'] == summary
    assert not output['summary']['coverage_complete']
    assert output['summary']['missing_count'] == 0
    assert output['summary']['primary']['interval95'] == [0., 0.]
    assert output['independent_recalculation'] is False
    assert not output['serving_parity'] and not output['playing_strength_evidence']


def test_existing_once_envelope_prevents_second_saved_read(tmp_path, prepared):
    from shengji.luna.benchmark_readout_receipt import run_once
    args, _, summary = prepared
    calls = []
    args['read_result'] = lambda: calls.append(1) or _encode(summary)
    output = tmp_path / 'readout'
    run_once(output, {'accepted_sha256': args['accepted_sha256']},
             lambda: read_saved_s11(**args))
    before = (output / 'result.json').read_bytes()
    with pytest.raises(FileExistsError):
        run_once(output, {'accepted_sha256': args['accepted_sha256']},
                 lambda: read_saved_s11(**args))
    assert calls == [1] and (output / 'result.json').read_bytes() == before


@pytest.mark.parametrize('damage', ['accepted-pin', 'cost-pin', 'packet', 'guard',
                                   'guard-digest', 'pid', 'extra'])
def test_parent_refusal_precedes_first_outcome_access(prepared, damage):
    args, accepted, _ = prepared
    if damage == 'accepted-pin':
        args['accepted_sha256'] = '0'*64
    elif damage == 'cost-pin':
        args['cost_parent_sha256'] = '0'*64
    else:
        if damage == 'packet': accepted['identity']['packet_sha256'] = '0'*64
        if damage == 'guard': accepted['guard']['exit_cause'] = 'wall-timeout'
        if damage == 'guard-digest': accepted['guard']['sample_count'] += 1
        if damage == 'pid': accepted['worker_pid'] = True
        if damage == 'extra': accepted['extra'] = 1
        args.update(accepted_raw=_encode(accepted), accepted_sha256=sha(_encode(accepted)))
    args['read_result'] = lambda: pytest.fail('private outcome access')
    with pytest.raises(ValueError): read_saved_s11(**args)


@pytest.mark.parametrize('damage', ['bytes', 'coverage', 'refusal', 'bootstrap', 'duplicate', 'callback'])
def test_result_refusals_are_fixed_and_preserve_caller_artifacts(prepared, damage):
    args, accepted, summary = prepared
    if damage == 'coverage': summary['valid_count'] = 61
    if damage == 'refusal': summary['failures'][0]['status'] = 'failed'
    if damage == 'bootstrap': summary['primary']['bootstrap']['seed'] = 1
    raw = _encode(summary)
    if damage == 'duplicate': raw = b'{"schema":1,"schema":2}'
    accepted['result_sha256'] = sha(raw)
    args.update(accepted_raw=_encode(accepted), accepted_sha256=sha(_encode(accepted)))
    if damage == 'bytes': raw += b' '
    args['read_result'] = lambda: raw
    if damage == 'callback':
        def fail(): raise RuntimeError('SECRET outcome')
        args['read_result'] = fail
    with pytest.raises(ValueError, match='preserve artifacts') as caught:
        read_saved_s11(**args)
    assert caught.value.__context__ is None


def test_actual_guarded_producer_to_saved_readout(packet):
    invoke(packet)
    path, pin, config = packet
    cost = Path(config['phases'][COST]['control']) / 'accepted.json'
    accepted = invoke(packet, FULL, cost_path=str(cost), cost_sha=sha(cost.read_bytes()))
    result = Path(config['phases'][FULL]['output']) / 'result.json'
    import json
    saved = json.loads(result.read_bytes())
    out = read_saved_s11(accepted_raw=_encode(accepted), accepted_sha256=sha(_encode(accepted)),
        packet_sha256=pin, bundle_sha256=config['bundle']['sha256'],
        cost_parent_sha256=sha(cost.read_bytes()),
        cost_receipt_sha256=accepted['identity']['cost_receipt_sha256'],
        limits=config['phases'][FULL]['limits'], scheduled_root_ids=saved['scheduled_root_ids'],
        refused_root_ids=[], read_result=result.read_bytes)
    assert out['summary'] == saved and saved['valid_count'] == 64
