"""Authenticate an accepted input handoff before collection or model access.

Pins must come from the independently reviewed collection packet. This pure
adapter grants no execution authority and opens no paths: bundle_path records
the original Mini publication, not a cloud destination to follow automatically.
The controller owns transport, phase RELEASE, runtime and guard qualification.
"""
import hashlib
import json
import re
from pathlib import PurePosixPath

from .s11_input_bundle import load_s11_input_bundle, _unique, _bad_constant
from .s11_persistence import _encode

_FIELDS = {'schema', 'packet_sha256', 'manifest_sha256', 'bundle_path',
           'bundle_sha256', 'receipt_sha256', 'guard_sha256'}


def _pin(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('SHA256 required')
    return value


def authenticate_s11_input(*, accepted_raw, accepted_sha256,
                           bundle_raw, bundle_sha256):
    """Return validated slots/receipt only after exact parent acceptance binds.

    Digest admission precedes JSON parsing. Reconstructing the small public
    input receipt verifies its pin without reopening raw shards or the original
    private worker directory. The guard digest is authenticated by the pinned
    parent acceptance, not independently re-evaluated by this adapter.
    """
    if (type(accepted_raw) is not bytes or not 0 < len(accepted_raw) <= 65536
            or hashlib.sha256(accepted_raw).hexdigest() != _pin(accepted_sha256)):
        raise ValueError('accepted input digest/size refused')
    accepted = json.loads(accepted_raw, object_pairs_hook=_unique,
                          parse_constant=_bad_constant)
    if (type(accepted) is not dict or set(accepted) != _FIELDS
            or accepted['schema'] != 's11-input-phase-accepted-v1'):
        raise ValueError('accepted input schema refused')
    for key in _FIELDS - {'schema', 'bundle_path'}:
        _pin(accepted[key])
    origin = accepted['bundle_path']
    if (type(origin) is not str or '\x00' in origin
            or not PurePosixPath(origin).is_absolute()
            or '..' in PurePosixPath(origin).parts
            or str(PurePosixPath(origin)) != origin):
        raise ValueError('accepted input origin path refused')
    if accepted['bundle_sha256'] != _pin(bundle_sha256):
        raise ValueError('accepted input bundle pin mismatch')
    if type(bundle_raw) is not bytes or not 0 < len(bundle_raw) <= 64 << 20:
        raise ValueError('accepted input bundle size refused')
    slots, receipt = load_s11_input_bundle(bundle_raw, sha256=bundle_sha256)
    if (any(receipt[key] != accepted[key]
            for key in ('packet_sha256', 'manifest_sha256', 'bundle_sha256'))
            or hashlib.sha256(_encode(receipt)).hexdigest() != accepted['receipt_sha256']):
        raise ValueError('accepted input context/receipt mismatch')
    return slots, receipt
