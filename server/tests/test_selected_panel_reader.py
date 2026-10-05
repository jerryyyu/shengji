import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.eval import selected_panel_reader as reader
from test_m9_panel_artifact_reader import bundle


def inputs(monkeypatch, tmp_path, index=0):
    pins, _, records = bundle(monkeypatch, tmp_path)
    packet = {'schema': 'm9-panel-admission-v1', 'status': pins['owner']['path'],
              'recipe': {'output_dir': str(tmp_path / 'collection'),
                         'evidence': str(tmp_path),
                         'saved_readout': pins['saved_readout']['path'],
                         'saved_readout_sha256': pins['saved_readout']['sha256']}}
    path = tmp_path / 'packet.json'
    path.write_text(json.dumps(packet))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    owner_path = Path(pins['owner']['path'])
    owner = json.loads(owner_path.read_text())
    owner['packet_sha256'] = sha
    owner_path.write_text(json.dumps(owner))
    pins['owner']['sha256'] = hashlib.sha256(owner_path.read_bytes()).hexdigest()
    selected = {name: pins[name] for name in reader.META if name != 'packet'}
    selected['packet'] = {'path': str(path), 'sha256': sha}
    selected['panel'] = pins[f'validated-{index:03d}.json']
    return selected, sha, records[index]


def repin(pins, name, mutate):
    path = Path(pins[name]['path'])
    value = json.loads(path.read_text())
    mutate(value)
    # Synthetic publisher seals these files; only this test-owned fixture is changed.
    path.chmod(0o600)
    path.write_text(json.dumps(value))
    pins[name]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('index', [0, 3, 14])
def test_only_selected_panel_read_and_order_preserved(monkeypatch, tmp_path, index):
    pins, sha, record = inputs(monkeypatch, tmp_path, index)
    from shengji.eval import m9_panel_readout, m9_panel_worker
    monkeypatch.setattr(m9_panel_readout, 'read_completed_m9_panels',
                        lambda *a, **kw: pytest.fail('full readout'))
    monkeypatch.setattr(m9_panel_worker, 'collect_m9_panels',
                        lambda *a, **kw: pytest.fail('collection'))
    before = copy.deepcopy(pins)
    opened = []
    stable = reader.guards._stable_read
    def track(path, limit):
        opened.append(str(path))
        return stable(path, limit)
    monkeypatch.setattr(reader.guards, '_stable_read', track)
    result = reader.read_selected_panel(pins, packet_sha256=sha, index=index)
    assert result['panel'] == record['panel']
    assert result['job'] == record['job']
    assert result['provenance_verified'] is False
    assert len(opened) == len(set(opened)) == 7
    assert set(opened) == {pin['path'] for pin in pins.values()}
    assert result['input_sha256'] == {key: pin['sha256'] for key, pin in pins.items()}
    assert pins == before


@pytest.mark.parametrize('bad', ['owner', 'plan', 'path', 'packet_pin', 'metadata_hash'])
def test_metadata_refuses_before_panel_open(monkeypatch, tmp_path, bad):
    pins, sha, _ = inputs(monkeypatch, tmp_path)
    if bad == 'owner':
        repin(pins, 'owner', lambda v: v.update(returncode=1))
    elif bad == 'plan':
        repin(pins, 'plan', lambda v: v.update(provenance_verified=True))
    elif bad == 'path':
        pins['panel']['path'] = str(tmp_path / 'elsewhere.json')
    elif bad == 'metadata_hash':
        pins['process']['sha256'] = '0' * 64
    else:
        pins['packet']['sha256'] = '0' * 64
    stable = reader.guards._stable_read
    def guarded(path, limit):
        assert 'validated-' not in path.name
        return stable(path, limit)
    monkeypatch.setattr(reader.guards, '_stable_read', guarded)
    with pytest.raises(ValueError):
        reader.read_selected_panel(pins, packet_sha256=sha, index=0)


@pytest.mark.parametrize('bad', ['status', 'job', 'mode', 'worlds', 'hash',
                               'missing_failure', 'cadence', 'tape', 'tape_bool', 'ledger'])
def test_selected_record_drift_refuses(monkeypatch, tmp_path, bad):
    pins, sha, _ = inputs(monkeypatch, tmp_path)
    if bad == 'hash':
        pins['panel']['sha256'] = '0' * 64
    else:
        def mutate(v):
            if bad == 'status':
                v['validation_status'] = 'failed'
            elif bad == 'job':
                v['job']['seed'] = 99
            elif bad == 'mode':
                v['panel']['mode'] = 'wrong'
            elif bad == 'missing_failure':
                del v['replay_failure']
            elif bad == 'cadence':
                v['ledger_cadence'] = 'wrong'
            elif bad == 'tape':
                v['panel']['tape_receipt']['checkpoint_sha256'] = '0' * 64
            elif bad == 'tape_bool':
                v['panel']['tape_receipt']['fill_seed'] = False
            elif bad == 'ledger':
                v['panel']['tape_receipt']['ledger_receipt']['mode'] = 'wrong'
            else:
                v['panel']['worlds'].pop()
        repin(pins, 'panel', mutate)
    with pytest.raises(ValueError):
        reader.read_selected_panel(pins, packet_sha256=sha, index=0)


@pytest.mark.parametrize('index', [True, -1, 15, 0.0])
def test_invalid_index_never_reads(monkeypatch, index):
    monkeypatch.setattr(reader.guards, '_stable_read', lambda *a: pytest.fail('read'))
    with pytest.raises(ValueError):
        reader.read_selected_panel({}, packet_sha256='a' * 64, index=index)


@pytest.mark.parametrize('index', [0, 3])
@pytest.mark.parametrize('bad', ['means', 'batches', 'points', 'summary',
                               'schema', 'replay', 'world_card', 'world_hands'])
def test_selected_capture_and_world_validation(monkeypatch, tmp_path, index, bad):
    pins, sha, _ = inputs(monkeypatch, tmp_path, index)
    def mutate(record):
        panel = record['panel']
        collection = panel['collection']
        full = (collection['captures']['full_pool'] if index == 0
                else collection['full_pool_capture'])
        if bad == 'means':
            full['serving_value_means'].pop()
        elif bad == 'batches':
            full['batches'] += 1
        elif bad == 'points':
            full['signed_trick_points'][-1].pop()
        elif bad == 'summary':
            collection['shared_matrix_summary'] = {}
        elif bad == 'schema':
            collection['schema'] = 'wrong-mode'
        elif bad == 'replay':
            record['replay_consistency'] = {'unverified': True}
        elif bad == 'world_card':
            panel['worlds'][-1][0][0].append('NOT-A-CARD')
        else:
            panel['worlds'][-1][0].pop()
    repin(pins, 'panel', mutate)
    with pytest.raises(ValueError):
        reader.read_selected_panel(pins, packet_sha256=sha, index=index)
