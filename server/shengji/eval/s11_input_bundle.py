"""Seal/reload the input-only S11 schedule, without raw or model access.

The caller supplies slots from the reviewed input reader under an admitted
packet. This adapter does not establish exposure clearance or launch authority.
Receipts contain only pins, slot identities/states and counts, never fixtures.
"""
import hashlib
import json
from pathlib import Path
import re

from .s11_persistence import _encode
from .s11_schedule import _bind_s11_schedule
from .public_refusal_history import public_root_with_ledger
from .tactical import fixture_from_json
from ..engine.cards import RANKS, SUITS, make_deck
from ..luna.atomic_io import publish_exclusive_bytes

SCHEMA = 's11-input-bundle-v1'
_BINDING = {'manifest_sha256', 'packet_sha256', 'seed', 'fill_seed',
            'max_public_refusals'}
_CARDS = frozenset(make_deck())


def _cards(value):
    return type(value) is list and all(type(c) is str and c in _CARDS for c in value)


def _seat(value):
    return type(value) is int and value in range(4)


def _public_fixture(row):
    """Reject unknown/private payloads and lossy fixture deserialization."""
    fx = fixture_from_json(row)
    if _encode(fx.to_json()) != _encode(row):
        raise ValueError('fixture round-trip mismatch')
    if (fx.category != 'observation' or
            fx.source != {'kind': 's11-public-projection', 'cadence': 'per-seat-decision'} or
            fx.observed != {} or fx.args != {} or fx.current_bot is not None or
            fx.notes != '' or fx.why !=
            'Outcome-blind scheduled S11 decision; not a known-mistake label.'):
        raise ValueError('non-public S11 fixture metadata')
    if set(fx.setup) != {'trump_rank', 'trump_suit', 'trump_is_nt', 'banker',
                         'declarations', 'buried'}:
        raise ValueError('non-public S11 setup')
    setup = fx.setup
    if (type(setup['trump_rank']) is not str or setup['trump_rank'] not in RANKS or
            setup['trump_suit'] not in (None, *SUITS) or
            type(setup['trump_is_nt']) is not bool or not _seat(setup['banker']) or
            type(setup['declarations']) is not list or
            not _seat(fx.seat) or not _cards(fx.hand) or
            (setup['buried'] is not None and not _cards(setup['buried']))):
        raise ValueError('non-public S11 setup values')
    for declaration in fx.setup['declarations']:
        if (type(declaration) is not dict or set(declaration) != {'seat', 'cards'} or
                not _seat(declaration['seat']) or not _cards(declaration['cards'])):
            raise ValueError('non-public declaration')
    for play in fx.plays:
        if (set(play) not in ({'seat', 'cards'}, {'seat', 'cards', 'attempted'}) or
                not _seat(play['seat']) or not _cards(play['cards']) or
                ('attempted' in play and not _cards(play['attempted']))):
            raise ValueError('non-public play')
    # Validate chronology/legality and retained refusal notices before a later
    # collect-once caller can create started state or construct a model.
    public_root_with_ledger(fx, mode='history-primed', fill_seed=0)
    return fx


def _build(slots, binding):
    # This is the frozen S11 design, not a general configurable draw/ceiling.
    if any(type(binding[k]) is not int or binding[k] != v for k, v in
           (('seed', 0), ('fill_seed', 0), ('max_public_refusals', 4))):
        raise ValueError('S11 requires seed0/fill0/refusal ceiling4')
    _, inventory, refused = _bind_s11_schedule(slots, **binding)
    if any(slot['stage'] != 'public-projection' for slot in refused):
        raise ValueError('input integrity refusal blocks publication')
    if len(refused) > 4:
        raise ValueError('public refusal ceiling exceeded')
    for slot in inventory:
        if slot['status'] == 'valid':
            _public_fixture(slot['fixture'])
    ledger = [dict(root_id=s['root_id'], draw_index=s['draw_index'],
                   status='unattempted' if s['status'] == 'valid' else 'refused')
              for s in inventory]
    return dict(schema=SCHEMA, **binding, slots=inventory, ledger=ledger,
                counts=dict(completed=0, interrupted=0, refused=len(refused),
                            unattempted=64-len(refused)))


def _receipt(bundle, pin):
    # Deliberately no fixture, arbitrary refusal message, or outcome payload.
    return dict(schema='s11-input-receipt-v1', bundle_sha256=pin,
                **{k: bundle[k] for k in _BINDING},
                ledger=bundle['ledger'], counts=bundle['counts'])


def publish_s11_input_bundle(slots, path, *, manifest_sha256, packet_sha256):
    """Publish once; integrity/ceiling/privacy validation precedes any write."""
    bundle = _build(slots, dict(manifest_sha256=manifest_sha256,
        packet_sha256=packet_sha256, seed=0, fill_seed=0, max_public_refusals=4))
    raw = _encode(bundle)
    publish_exclusive_bytes(Path(path), raw)
    return _receipt(bundle, hashlib.sha256(raw).hexdigest())


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate bundle key')
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError('nonfinite bundle number')


def load_s11_input_bundle(raw, *, sha256):
    """Verify exact bytes before parsing; return slots and outcome-free receipt.

    The caller obtains the expected digest from the reviewed next-phase packet,
    not from this bundle or a mutable adjacent file. No raw reconstruction.
    """
    if (type(raw) is not bytes or type(sha256) is not str or
            not re.fullmatch('[0-9a-f]{64}', sha256) or
            hashlib.sha256(raw).hexdigest() != sha256):
        raise ValueError('input bundle SHA256 mismatch')
    bundle = json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
    if (type(bundle) is not dict or set(bundle) !=
            {'schema', 'slots', 'ledger', 'counts'} | _BINDING or
            bundle['schema'] != SCHEMA):
        raise ValueError('input bundle schema mismatch')
    if type(bundle['slots']) is not list:
        raise ValueError('input bundle slots required')
    slots = []
    for slot in bundle['slots']:
        if type(slot) is not dict:
            raise ValueError('input bundle slot required')
        slots.append({**slot, 'fixture': _public_fixture(slot['fixture'])}
                     if slot.get('status') == 'valid' else slot)
    expected = _build(slots, {k: bundle[k] for k in _BINDING})
    if _encode(expected) != _encode(bundle):
        raise ValueError('input bundle ledger/counts mismatch')
    return slots, _receipt(expected, sha256)
