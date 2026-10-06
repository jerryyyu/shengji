import copy
import json
import os

import pytest

from shengji.eval.s11_collection import collect_s11_fixture
from shengji.eval.s11_public_view import public_s11_fixture
from shengji.eval.s11_persistence import load_s11_root, save_s11_root
from shengji.luna import atomic_io
from test_s11_collection import factory
from test_s11_public_view import trajectory


@pytest.fixture
def capture(trajectory):
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic-store')
    calls = dict(leaves=0, policy=[], bots=[])
    result = collect_s11_fixture(factory(calls), fixture, seed=17)
    return fixture, result


def save(path, capture):
    fixture, result = capture
    save_s11_root(path, result, packet_sha256='a' * 64, fixture=fixture)


def load(path, capture, **changes):
    options = dict(packet_sha256='a' * 64, fixture=capture[0], seed=17)
    options.update(changes)
    return load_s11_root(path, **options)


def test_real_capture_roundtrip_and_no_overwrite(tmp_path, capture):
    path = tmp_path / 'root.json'
    assert load(path, capture) is None
    save(path, capture)
    original = path.read_bytes()
    assert load(path, capture) == json.loads(json.dumps(capture[1]))
    with pytest.raises(ValueError, match='occupied'):
        save(path, capture)
    assert path.read_bytes() == original


@pytest.mark.parametrize('change', [dict(packet_sha256='b' * 64),
    dict(seed=18), dict(fill_seed=1)])
def test_context_drift_refused(tmp_path, capture, change):
    path = tmp_path / 'root.json'
    save(path, capture)
    with pytest.raises(ValueError, match='context mismatch'):
        load(path, capture, **change)


def test_fixture_drift_refused(tmp_path, capture):
    path = tmp_path / 'root.json'
    save(path, capture)
    fixture = copy.deepcopy(capture[0])
    fixture.setup['trump_rank'] = 'A'
    with pytest.raises(ValueError, match='context mismatch'):
        load(path, capture, fixture=fixture)


def test_corruption_refused(tmp_path, capture):
    path = tmp_path / 'root.json'
    save(path, capture)
    envelope = json.loads(path.read_bytes())
    envelope['payload']['result']['seed'] = 99
    path.chmod(0o600)
    path.write_text(json.dumps(envelope))
    path.chmod(0o400)
    with pytest.raises(ValueError, match='SHA256 mismatch'):
        load(path, capture)


def test_interrupted_publication_preserves_completed_bytes(tmp_path, capture, monkeypatch):
    path = tmp_path / 'root.json'
    original = atomic_io.promote_partial
    def crash(*args, **kwargs):
        raise RuntimeError('synthetic crash before publication')
    monkeypatch.setattr(atomic_io, 'promote_partial', crash)
    with pytest.raises(RuntimeError, match='synthetic crash'):
        save(path, capture)
    assert not path.exists()
    before = atomic_io.partial_path(path).read_bytes()
    with pytest.raises(ValueError, match='explicit recovery'):
        load(path, capture)
    # Explicitly republish the already computed capture; no inference rerun.
    monkeypatch.setattr(atomic_io, 'promote_partial', original)
    save(path, capture)
    assert path.read_bytes() == before
    assert load(path, capture)['root_id'] == capture[0].id


def test_crash_after_link_keeps_usable_completion(tmp_path, capture, monkeypatch):
    path = tmp_path / 'root.json'
    original = atomic_io._fsync_dir
    def crash(*args):
        raise OSError('synthetic crash after link')
    monkeypatch.setattr(atomic_io, '_fsync_dir', crash)
    with pytest.raises(OSError, match='after link'):
        save(path, capture)
    before = path.read_bytes()
    assert load(path, capture)['root_id'] == capture[0].id
    monkeypatch.setattr(atomic_io, '_fsync_dir', original)
    save(path, capture)  # finish existing linked-publication cleanup only
    assert path.read_bytes() == before
    assert not atomic_io.partial_path(path).exists()


def test_incomplete_partial_is_not_replaced(tmp_path, capture):
    path = tmp_path / 'root.json'
    staged = atomic_io.partial_path(path)
    staged.write_bytes(b'{"partial":')
    staged.chmod(0o400)
    with pytest.raises(ValueError):
        save(path, capture)
    assert staged.read_bytes() == b'{"partial":' and not path.exists()


@pytest.mark.parametrize('kind', ['symlink', 'fifo'])
def test_special_files_refused_without_blocking(tmp_path, capture, kind):
    path = tmp_path / 'root.json'
    if kind == 'fifo':
        os.mkfifo(path)
    else:
        target = tmp_path / 'target'
        target.write_text('{}')
        path.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        load(path, capture)


@pytest.mark.parametrize('damage', ['root_id', 'seed', 'report', 'model_verified', 'nan',
    'missing-worlds', 'missing-recipe', 'empty-worlds', 'value-count',
    'recipe', 'legal-count', 'legal-complete'])
def test_invalid_capture_not_published(tmp_path, capture, damage):
    fixture, result = capture
    result = copy.deepcopy(result)
    if damage == 'root_id':
        result[damage] = 'wrong'
    elif damage == 'seed':
        result[damage] = True
    elif damage == 'report':
        result[damage] = dict(status='failed')
    elif damage == 'nan':
        result['value_capture']['value_matrix'][0][0] = float('nan')
    elif damage.startswith('missing-'):
        del result[damage.removeprefix('missing-')]
    elif damage == 'empty-worlds':
        result['worlds'] = []
    elif damage == 'value-count':
        result['value_capture']['world_count'] = 63
    elif damage == 'recipe':
        result['recipe']['effective']['worlds'] = 32
    elif damage == 'legal-count':
        result['legal_count'] += 1
    elif damage == 'legal-complete':
        result['legal_complete'] = not result['legal_complete']
    else:
        result[damage] = True
    path = tmp_path / 'root.json'
    with pytest.raises(ValueError):
        save_s11_root(path, result, packet_sha256='a' * 64, fixture=fixture)
    assert not path.exists() and not atomic_io.partial_path(path).exists()


@pytest.mark.parametrize('damage', ['mode', 'link'])
def test_immutable_file_identity_required(tmp_path, capture, damage):
    path = tmp_path / 'root.json'
    save(path, capture)
    if damage == 'mode':
        path.chmod(0o600)
    else:
        os.link(path, tmp_path / 'other')
    with pytest.raises((ValueError, OSError)):
        load(path, capture)
