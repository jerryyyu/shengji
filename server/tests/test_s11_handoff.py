import hashlib

import pytest

from shengji.eval import s11_handoff as handoff
from shengji.eval.s11_input_bundle import publish_s11_input_bundle
from shengji.eval.s11_persistence import _encode
from test_s11_schedule import slots, trajectory, PIN


def prepared(tmp_path, slots):
    path = tmp_path / 'bundle.json'
    receipt = publish_s11_input_bundle(slots, path, manifest_sha256=PIN,
                                       packet_sha256='b' * 64)
    accepted = dict(schema='s11-input-phase-accepted-v1',
        packet_sha256=receipt['packet_sha256'], manifest_sha256=PIN,
        bundle_path='/original/mini/private/bundle.json',
        bundle_sha256=receipt['bundle_sha256'],
        receipt_sha256=hashlib.sha256(_encode(receipt)).hexdigest(),
        guard_sha256='d' * 64)
    return accepted, dict(bundle_raw=path.read_bytes(),
                          bundle_sha256=receipt['bundle_sha256'])


def invoke(accepted, args):
    raw = _encode(accepted)
    return handoff.authenticate_s11_input(accepted_raw=raw,
        accepted_sha256=hashlib.sha256(raw).hexdigest(), **args)


def test_accepted_origin_is_identity_not_path_to_open(tmp_path, slots):
    accepted, args = prepared(tmp_path, slots)
    loaded, receipt = invoke(accepted, args)
    assert len(loaded) == 64
    assert receipt['counts']['unattempted'] == 64
    assert receipt['packet_sha256'] == 'b' * 64


@pytest.mark.parametrize('key,value', [
    ('schema', 's11-input-receipt-v1'), ('extra', 'private payload'),
    ('packet_sha256', 'a' * 64), ('manifest_sha256', 'e' * 64),
    ('bundle_sha256', 'a' * 64), ('receipt_sha256', 'a' * 64),
    ('guard_sha256', None), ('bundle_path', '/a/../b'),
    ('bundle_path', 'relative'), ('bundle_path', '/a//b'),
])
def test_mismatched_handoff_refused(tmp_path, slots, key, value):
    accepted, args = prepared(tmp_path, slots)
    accepted[key] = value
    with pytest.raises(ValueError):
        invoke(accepted, args)


def test_bad_parent_pin_precedes_bundle_validation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('bundle accessed before parent authentication')
    monkeypatch.setattr(handoff, 'load_s11_input_bundle', forbidden)
    with pytest.raises(ValueError, match='digest'):
        handoff.authenticate_s11_input(accepted_raw=b'not json',
            accepted_sha256='a' * 64, bundle_raw=b'', bundle_sha256='b' * 64)


@pytest.mark.parametrize('raw', [b'{"schema":1,"schema":2}',
                               b'{"schema":NaN}', b'[]'])
def test_invalid_parent_json_refuses(raw):
    with pytest.raises(ValueError):
        handoff.authenticate_s11_input(accepted_raw=raw,
            accepted_sha256=hashlib.sha256(raw).hexdigest(),
            bundle_raw=b'', bundle_sha256='b' * 64)


def test_bundle_bytes_cannot_be_replaced(tmp_path, slots):
    accepted, args = prepared(tmp_path, slots)
    args['bundle_raw'] += b' '
    with pytest.raises(ValueError, match='SHA256'):
        invoke(accepted, args)
