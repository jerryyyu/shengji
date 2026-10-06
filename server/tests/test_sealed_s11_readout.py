import hashlib
import json
from pathlib import Path

import pytest

from scripts import sealed_s11_readout as reader
from shengji.eval.s11_phases import COST, FULL
from test_s11_collection_phase import packet, invoke
from test_s11_schedule import slots, trajectory
from test_s11_model import frozen, package


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def args(packet):
    path, pin, _ = packet
    return dict(packet_path=str(path), packet_sha256=pin,
        cost_parent_sha256='a'*64, full_parent_sha256='b'*64,
        reader_sha256=sha(reader.__file__), output=str(path.parent / 'readout'))


def test_dry_run_never_opens_inputs_parents_or_results(packet, monkeypatch):
    real = reader._manifest
    allowed = {str(packet[0]), str(Path(reader.__file__))}
    def bounded(path, limit):
        assert str(path) in allowed
        return real(path, limit)
    monkeypatch.setattr(reader, '_manifest', bounded)
    assert reader.read_once(**args(packet)) == {'status': 'unarmed'}
    assert not Path(args(packet)['output']).exists()


def test_reader_pin_refuses_before_packet_access(packet, monkeypatch):
    kw = args(packet)
    kw['reader_sha256'] = '0'*64
    real = reader._manifest
    def bounded(path, limit):
        assert str(path) == str(Path(reader.__file__))
        return real(path, limit)
    monkeypatch.setattr(reader, '_manifest', bounded)
    with pytest.raises(ValueError, match='entrypoint digest'): reader.read_once(**kw)


@pytest.mark.parametrize('target', ['capture', 'full-output', 'gate', 'ancestor'])
def test_output_overlap_refuses_even_unarmed(packet, target):
    kw = args(packet)
    config = packet[2]
    kw['output'] = {'capture':config['directory'] + '/readout',
        'full-output':config['phases'][FULL]['output'],
        'gate':str(Path(config['phases'][FULL]['release']).parent / 'readout'),
        'ancestor':str(packet[0].parent)}[target]
    with pytest.raises(ValueError, match='disjoint'): reader.read_once(**kw)


def test_guarded_producer_to_once_cli_and_no_second_read(packet, monkeypatch, capsys):
    invoke(packet)
    config = packet[2]
    cost = Path(config['phases'][COST]['control']) / 'accepted.json'
    invoke(packet, FULL, cost_path=str(cost), cost_sha=sha(cost))
    full = Path(config['phases'][FULL]['control']) / 'accepted.json'
    kw = args(packet)
    kw.update(cost_parent_sha256=sha(cost), full_parent_sha256=sha(full))
    cli = ['--packet',kw['packet_path'], '--packet-sha256',kw['packet_sha256'],
        '--cost-parent-sha256',kw['cost_parent_sha256'],
        '--full-parent-sha256',kw['full_parent_sha256'],
        '--reader-sha256',kw['reader_sha256'], '--output',kw['output'], '--run']
    assert reader.main(cli) == 0
    assert json.loads(capsys.readouterr().out) == {'status':'complete'}
    saved = Path(kw['output']) / 'result.json'
    result = json.loads(saved.read_bytes())
    assert result['summary']['valid_count'] == 64
    before = saved.read_bytes()
    monkeypatch.setattr(reader, 'authenticate_s11_input', lambda **k: pytest.fail('second read'))
    assert reader.main(cli) == 1
    assert 'preserve artifacts' in capsys.readouterr().out
    assert saved.read_bytes() == before


def test_invalid_parent_pin_no_scientific_result_access(packet, monkeypatch):
    invoke(packet)
    config = packet[2]
    cost = Path(config['phases'][COST]['control']) / 'accepted.json'
    invoke(packet, FULL, cost_path=str(cost), cost_sha=sha(cost))
    kw = args(packet)
    kw.update(cost_parent_sha256=sha(cost), execute=True)
    real = reader._manifest
    forbidden = Path(config['phases'][FULL]['output']) / 'result.json'
    def bounded(path, limit):
        assert Path(path) != forbidden
        return real(path, limit)
    monkeypatch.setattr(reader, '_manifest', bounded)
    with pytest.raises(ValueError, match='preserve artifacts') as caught:
        reader.read_once(**kw)
    assert caught.value.__context__ is None
    out = Path(kw['output'])
    assert (out / 'claim.json').exists() and (out / 'refusal.json').exists()
    assert not (out / 'result.json').exists()
