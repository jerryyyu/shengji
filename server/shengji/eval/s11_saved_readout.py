"""Authenticate a terminal parent's saved S11 summary before exposing it.

The caller supplies externally reviewed pins, limits and the accepted schedule,
owns terminality/exclusive readout and pins this reader/runtime before use.
This adapter neither opens files nor collects, reconstructs or rescores roots.
It authenticates the reviewed producer's summary, not an independent statistical
recalculation. Publication belongs in the existing run_once envelope.
"""
import hashlib
import json

from .s11_cost_handoff import _ACCEPTED_FIELDS, _decode, _guard
from .s11_input_bundle import _unique, _bad_constant
from .s11_phases import FULL, _pin
from .s11_persistence import _encode
from .s11_report import SUMMARY_SCHEMA, VALUE_SCOPE


def read_saved_s11(*, accepted_raw, accepted_sha256, packet_sha256,
                  bundle_sha256, cost_parent_sha256, cost_receipt_sha256,
                  limits, scheduled_root_ids, refused_root_ids, read_result):
    """Call read_result exactly once, only after authenticating parent acceptance.

    No private outcome bytes should be opened by the caller before the callback.
    accepted_sha256 must come from the terminal handoff, never from hashing an
    adjacent mutable file just before calling. Failure text excludes outcomes.
    """
    identity = dict(packet_sha256=_pin(packet_sha256),
                    bundle_sha256=_pin(bundle_sha256), phase=FULL,
                    cost_receipt_sha256=_pin(cost_receipt_sha256))
    _pin(cost_parent_sha256)
    _pin(accepted_sha256)
    if (type(scheduled_root_ids) is not list or len(scheduled_root_ids) != 64
            or any(type(x) is not str or not x for x in scheduled_root_ids)
            or len(set(scheduled_root_ids)) != 64
            or type(refused_root_ids) is not list
            or any(type(x) is not str for x in refused_root_ids)
            or len(set(refused_root_ids)) != len(refused_root_ids)
            or len(refused_root_ids) > 4
            or not set(refused_root_ids) <= set(scheduled_root_ids)):
        raise ValueError('accepted schedule refused')
    if (type(accepted_raw) is not bytes or not 0 < len(accepted_raw) <= 65536
            or hashlib.sha256(accepted_raw).hexdigest() != accepted_sha256):
        raise ValueError('full parent acceptance pin/size refused')
    accepted = _decode(accepted_raw)
    if (type(accepted) is not dict
            or set(accepted) != _ACCEPTED_FIELDS | {'cost_parent_sha256'}
            or accepted['schema'] != 's11-full-parent-accepted-v1'
            or accepted['identity'] != identity
            or accepted['cost_parent_sha256'] != cost_parent_sha256
            or type(accepted['worker_pid']) is not int or accepted['worker_pid'] <= 0):
        raise ValueError('full parent acceptance context refused')
    for name in ('guard_sha256', 'claim_sha256', 'receipt_sha256', 'result_sha256'):
        _pin(accepted[name])
    _guard(accepted['guard'], limits)
    if hashlib.sha256(_encode(accepted['guard'])).hexdigest() != accepted['guard_sha256']:
        raise ValueError('full parent guard digest refused')
    if not callable(read_result):
        raise ValueError('saved result callback required')
    # Parent authenticity and successful bounded exit precede first outcome access.
    try:
        raw = read_result()
        if (type(raw) is not bytes or not 0 < len(raw) <= 64 << 20
                or hashlib.sha256(raw).hexdigest() != accepted['result_sha256']):
            raise ValueError('saved result pin/size refused')
        summary = json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
        n = 64 - len(refused_root_ids)
        expected = dict(schema=SUMMARY_SCHEMA, status='valid',
            provenance_verified=False, value_scope=VALUE_SCOPE,
            scheduled_root_ids=sorted(scheduled_root_ids), scheduled_count=64,
            valid_count=n, failed_count=0, refused_count=len(refused_root_ids),
            missing_count=0, coverage_complete=not refused_root_ids)
        if type(summary) is not dict or any(
                type(summary.get(k)) is not type(v) or summary[k] != v
                for k, v in expected.items()):
            raise ValueError('saved summary coverage/context refused')
        failures = summary['failures']
        if (type(failures) is not list or len(failures) != len(refused_root_ids)
                or any(type(x) is not dict or set(x) != {'root_id', 'status', 'reason'}
                       or x['status'] != 'refused' or type(x['reason']) is not str
                       or not x['reason'].strip() for x in failures)
                or sorted(x['root_id'] for x in failures) != sorted(refused_root_ids)):
            raise ValueError('saved summary refusals mismatch')
        primary = summary['primary']
        if (primary['estimand'] != 'T-C max_saved'
                or primary['denominator'] != 'all_valid_roots'
                or primary['bootstrap'] != dict(seed=0, samples=2000, replicates=2000,
                    percentile_method='sorted replicate index floor(p * (N - 1))')):
            raise ValueError('saved summary estimand mismatch')
        return dict(schema='s11-authenticated-saved-readout-v1', identity=identity,
            accepted_sha256=accepted_sha256, result_sha256=accepted['result_sha256'],
            summary=summary, independent_recalculation=False,
            serving_parity=False, playing_strength_evidence=False)
    except Exception:
        pass
    raise ValueError('saved S11 summary refused; preserve artifacts, no automatic retry')
