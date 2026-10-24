import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from failure import project, KEY


def row():
    return dict(schema='w32-llm-benchmark-mirror-v1', key=KEY, arm='sol-perfect', model='sol',
                information='perfect', seed=142060913, flip=0, complete=False,
                error='TransportError: provider unavailable',
                calls=[dict(error_type='provider_capacity',error='provider_capacity',
                            returncode=1, wall_ms=12, evidence_path='DO_NOT_EXPORT',
                            response_binding={'hidden': 'DO_NOT_EXPORT'})],
                events=[{'hidden': 'DO_NOT_EXPORT'}])


def test_only_failure_and_transport_projection():
    result = project(row())
    assert result['transport_categories'] == {'provider_capacity': 1}
    assert result['failed_transport_count'] == 1
    assert 'DO_NOT_EXPORT' not in json.dumps(result)
    assert result['error'] == row()['error']


@pytest.mark.parametrize('key,value', [('seed',142060914),('flip',1),('complete',True),
    ('signed_levels',1),('error',''),('calls',None)])
def test_wrong_identity_outcome_and_missing_failure_refuse(key,value):
    data=row();data[key]=value
    with pytest.raises(ValueError):project(data)


def test_transport_output_is_bounded():
    data=row();data['calls'] *= 20
    result=project(data)
    assert len(result['failed_transport_tail']) == 8 and result['failed_transport_count'] == 20
    data['error']='x'*2049
    with pytest.raises(ValueError):project(data)


def test_one_shot_exact_target_and_terminal_gate(tmp_path, monkeypatch):
    import hashlib
    import failure
    root=tmp_path/'root';root.mkdir();(root/'benchmark').mkdir()
    terminal=b'{}';(root/'terminal.json').write_bytes(terminal)
    (root/'benchmark'/failure.TARGET).write_text(json.dumps(row()))
    (root/'benchmark'/'result.json').write_text('must not open aggregate')
    monkeypatch.setattr(failure,'ROOT',root)
    monkeypatch.setattr(failure,'OUTPUT',tmp_path/'output')
    monkeypatch.setattr(failure,'TERMINAL_SHA',hashlib.sha256(terminal).hexdigest())
    failure.run()
    result=json.loads((failure.OUTPUT/'result.json').read_text())
    assert result['mirror']==KEY and (failure.OUTPUT/'claim.json').exists()
    with pytest.raises(FileExistsError):failure.run()
    monkeypatch.setattr(failure,'OUTPUT',tmp_path/'new-output')
    monkeypatch.setattr(failure,'TERMINAL_SHA','0'*64)
    with pytest.raises(ValueError,match='terminal drift'):failure.run()
    assert not failure.OUTPUT.exists()
