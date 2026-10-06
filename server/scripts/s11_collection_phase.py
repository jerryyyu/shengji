"""Guarded single-attempt S11 phase, called only by the admitted host owner.

Caller pins this source/runtime and packet, holds the fleet's shared host lock,
and supplies the separately reviewed accepted-cost pin for full collection.
This controller creates neither RELEASE nor reservations and never retries.
It returns operational acceptance only; full results and logs remain private.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

from scripts.s11_collection_worker import validate_packet, authenticate_inputs, authenticate_pilot
from scripts.s11_input_guard import supervise_s11_input
from scripts.s11_input_phase import _private_empty
from shengji.eval.s11_admission_once import _manifest
from shengji.eval.s11_cost_handoff import accept_cost, _guard
from shengji.eval.s11_input_bundle import _unique, _bad_constant
from shengji.eval.s11_phases import COST, require_phase_release
from shengji.eval.s11_persistence import _encode
from shengji.luna.atomic_io import publish_exclusive_bytes
from shengji.luna.benchmark_readout_receipt import _exclusive_json


def run_collection_phase(packet_path, pin, phase, *, cwd, env,
                         cost_path=None, cost_sha=None, python=sys.executable):
    """Execute one exact phase; success acceptance is always published last.

    Does not return scientific outcomes, even on full completion. Guard and
    worker logs stay in mode0700 directories. Failure text is fixed and no
    exception chain escapes. A failed start marker permanently blocks reentry.
    """
    packet_path = Path(packet_path)
    config = validate_packet(_manifest(packet_path, 65536), pin)
    selected = config['phases'][phase]
    require_phase_release(selected['release'], pin, phase)
    control = _private_empty(selected['control'])
    output = Path(selected['output'])
    if os.path.lexists(output):
        raise ValueError('private collection output already occupied')
    identity = dict(packet_sha256=pin, bundle_sha256=config['bundle']['sha256'], phase=phase)
    if phase != COST:
        # This pin belongs to a separately reviewed full invocation, not the
        # stable collection packet (which predates its cost result).
        from shengji.eval.s11_handoff import _pin
        _pin(cost_sha)
    _exclusive_json(control / 'started.json', dict(identity=identity, cost_parent_sha256=cost_sha))
    fd = os.open(control, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        _, first = authenticate_inputs(config)
        _, pilot_pin = authenticate_pilot(config, pin, phase, first, cost_path, cost_sha)
        if phase != COST:
            identity['cost_receipt_sha256'] = pilot_pin
        command = [python, '-B', '-m', 'scripts.s11_collection_worker',
                   '--packet', str(packet_path), '--sha256', pin, '--phase', phase, '--run']
        if phase != COST:
            command += ['--accepted-cost', str(cost_path), '--accepted-cost-sha256', cost_sha]
        with (control / 'worker.log').open('xb') as log:
            guard = supervise_s11_input(command, cwd=cwd,
                env=dict(env, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'),
                log=log, python=python, **selected['limits'])
        guard_raw = _encode(guard)
        publish_exclusive_bytes(control / 'guard.json', guard_raw)
        _guard(guard, selected['limits'])  # Nothing private is admitted before guard success.
        if {p.name for p in output.iterdir()} != {'claim.json', 'result.json', 'receipt.json'}:
            raise ValueError('private collection inventory incomplete')
        claim_raw = _manifest(output / 'claim.json', 65536)
        receipt_raw = _manifest(output / 'receipt.json', 65536)
        # The bounded worker summary is sealed, not interpreted here. Cost is
        # small and outcome-blind; full remains private for the pinned reader.
        result_raw = _manifest(output / 'result.json', 64 << 20)
        if phase == COST:
            accepted = accept_cost(guard_raw=guard_raw, claim_raw=claim_raw,
                receipt_raw=receipt_raw, result_raw=result_raw, packet_sha256=pin,
                bundle_sha256=config['bundle']['sha256'], first_slot=first,
                limits=selected['limits'])
        else:
            claim = json.loads(claim_raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
            receipt = json.loads(receipt_raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
            if (type(claim) is not dict or set(claim) != {'identity', 'pid'}
                    or claim['identity'] != identity or type(claim['pid']) is not int or claim['pid'] <= 0
                    or type(receipt) is not dict or set(receipt) != {
                        'status', 'identity', 'pid', 'result_sha256'}
                    or receipt['status'] != 'complete' or receipt['identity'] != identity
                    or type(receipt['pid']) is not int or receipt['pid'] != claim['pid']
                    or receipt['result_sha256'] != hashlib.sha256(result_raw).hexdigest()):
                raise ValueError('full worker identity/result mismatch')
            accepted = dict(schema='s11-full-parent-accepted-v1', identity=identity,
                cost_parent_sha256=cost_sha, worker_pid=claim['pid'], guard=guard,
                result_sha256=receipt['result_sha256'],
                receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
                claim_sha256=hashlib.sha256(claim_raw).hexdigest(),
                guard_sha256=hashlib.sha256(guard_raw).hexdigest())
        require_phase_release(selected['release'], pin, phase)
        publish_exclusive_bytes(control / 'accepted.json', _encode(accepted))
        return accepted
    except Exception:
        pass
    raise ValueError('collection incomplete; preserve private artifacts for explicit disposition')
