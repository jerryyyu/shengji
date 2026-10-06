"""Outcome-blind acceptance boundary for S11's private cost worker.

Only the owning controller calls accept_cost after its contained child exits.
It supplies its own guard bytes, not worker-supplied evidence. Before publishing
the returned envelope it must recheck HOLD/phase RELEASE and publish exclusively.
This pure adapter neither launches nor publishes, and never opens a capture.
Full-phase callers pin that published envelope in a separately reviewed handoff.
"""
import hashlib
import json
import math

from .s11_input_bundle import _unique, _bad_constant
from .s11_phases import COST, _cost_seal, _pin

_LIMITS = {'wall_seconds', 'rss_threshold_bytes', 'sample_seconds', 'term_grace_seconds'}
_GUARD_FIELDS = _LIMITS | {'schema', 'pid', 'exit_cause', 'returncode',
    'peak_sampled_rss_bytes', 'sample_count', 'elapsed_seconds', 'memory_measure'}
_ACCEPTED_FIELDS = {'schema', 'identity', 'guard_sha256', 'claim_sha256',
    'receipt_sha256', 'result_sha256', 'worker_pid', 'guard'}
_MEASURE = 'sampled process-group RSS; overshoot between samples possible'


def _decode(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise ValueError('cost handoff size refused')
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _guard(value, limits):
    if (type(limits) is not dict or set(limits) != _LIMITS
            or any(not _positive(v) for v in limits.values())):
        raise ValueError('reviewed cost guard limits required')
    if (type(value) is not dict or set(value) != _GUARD_FIELDS
            or value['schema'] != 's11-input-guard-v1'
            or value['exit_cause'] != 'process-exited'
            or type(value['returncode']) is not int or value['returncode'] != 0
            or value['memory_measure'] != _MEASURE
            or any(not _positive(value[k]) or value[k] != limits[k] for k in _LIMITS)
            or any(type(value[k]) is not int or value[k] <= 0
                   for k in ('pid', 'sample_count', 'peak_sampled_rss_bytes'))
            or value['peak_sampled_rss_bytes'] > limits['rss_threshold_bytes']
            or not _positive(value['elapsed_seconds'])
            or value['elapsed_seconds'] > limits['wall_seconds']):
        raise ValueError('cost guard did not accept worker under reviewed limits')


def _identity(packet, bundle):
    return dict(packet_sha256=_pin(packet), bundle_sha256=_pin(bundle), phase=COST)


def accept_cost(*, guard_raw, claim_raw, receipt_raw, result_raw,
                packet_sha256, bundle_sha256, first_slot, limits):
    """Validate operational parent evidence before returning a publishable value.

    The guard leader can be the watchdog, so it is NOT equated to worker_pid.
    Claim and terminal worker receipt must agree on their own PID and identity.
    Caller owns exclusive inventory checks, process containment and publication.
    """
    guard = _decode(guard_raw)
    _guard(guard, limits)  # Guard refusal precedes private worker parsing.
    identity = _identity(packet_sha256, bundle_sha256)
    claim, receipt = _decode(claim_raw), _decode(receipt_raw)
    if (type(claim) is not dict or set(claim) != {'identity', 'pid'}
            or claim['identity'] != identity
            or type(claim['pid']) is not int or claim['pid'] <= 0
            or type(receipt) is not dict or set(receipt) != {
                'status', 'identity', 'pid', 'result_sha256'}
            or receipt['status'] != 'complete' or receipt['identity'] != identity
            or type(receipt['pid']) is not int or receipt['pid'] != claim['pid']):
        raise ValueError('cost worker claim/receipt context refused')
    _cost_seal(result_raw, receipt['result_sha256'], packet_sha256, bundle_sha256, first_slot)
    if _decode(result_raw)['metrics']['elapsed_seconds'] > guard['elapsed_seconds']:
        raise ValueError('cost timing exceeds guarded lifetime')
    return dict(schema='s11-cost-parent-accepted-v1', identity=identity,
        guard_sha256=_sha(guard_raw), claim_sha256=_sha(claim_raw),
        receipt_sha256=_sha(receipt_raw), result_sha256=_sha(result_raw),
        worker_pid=claim['pid'], guard=guard)


def authenticate_cost(*, accepted_raw, accepted_sha256, result_raw,
                      packet_sha256, bundle_sha256, first_slot, limits):
    """Return the worker-result pin only after externally pinned parent acceptance.

    A private result/receipt alone cannot satisfy this interface. The exact
    accepted digest must originate in the reviewed full-phase handoff, never
    be obtained by hashing a mutable adjacent file at invocation time.
    """
    if (type(accepted_raw) is not bytes or not 0 < len(accepted_raw) <= 65536
            or _sha(accepted_raw) != _pin(accepted_sha256)):
        raise ValueError('accepted cost digest/size refused')
    accepted = _decode(accepted_raw)
    if (type(accepted) is not dict or set(accepted) != _ACCEPTED_FIELDS
            or accepted['schema'] != 's11-cost-parent-accepted-v1'
            or accepted['identity'] != _identity(packet_sha256, bundle_sha256)
            or type(accepted['worker_pid']) is not int or accepted['worker_pid'] <= 0):
        raise ValueError('accepted cost context refused')
    for key in ('guard_sha256', 'claim_sha256', 'receipt_sha256', 'result_sha256'):
        _pin(accepted[key])
    _guard(accepted['guard'], limits)
    _cost_seal(result_raw, accepted['result_sha256'], packet_sha256, bundle_sha256, first_slot)
    if _decode(result_raw)['metrics']['elapsed_seconds'] > accepted['guard']['elapsed_seconds']:
        raise ValueError('accepted cost timing refused')
    return accepted['result_sha256']
