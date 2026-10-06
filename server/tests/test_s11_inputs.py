from types import SimpleNamespace

import pytest

from shengji.eval import s11_inputs as module
from shengji.eval.s11_manifest import select_manifest_shards
from test_s11_input_join import input_frame


@pytest.fixture(scope='module')
def frame(tmp_path_factory):
    return input_frame(tmp_path_factory.mktemp('synthetic-frame'))


@pytest.mark.parametrize('damage', [None, 'missing', 'changed', 'public-refusal'])
def test_real_reader_keeps_every_selected_slot(tmp_path, frame, damage, monkeypatch):
    manifest, pin, shards = frame
    (tmp_path / 'shards').mkdir()
    for cluster, raw in shards.items():
        (tmp_path / 'shards' / f'cluster-{cluster:06d}.jsonl').write_bytes(raw)
    selected = select_manifest_shards(manifest, sha256=pin)
    first = tmp_path / selected[0].path
    if damage == 'missing':
        first.unlink()
    elif damage == 'changed':
        first.write_bytes(b'!' + first.read_bytes()[1:])
    elif damage == 'public-refusal':
        original = module.public_s11_fixture
        def refuse(rows, ply, **kwargs):
            if kwargs['root_id'].endswith('draw-00'):
                raise ValueError('synthetic public refusal')
            return original(rows, ply, **kwargs)
        monkeypatch.setattr(module, 'public_s11_fixture', refuse)
    results = module.read_s11_inputs(manifest, sha256=pin, root=tmp_path)
    assert [r['draw_index'] for r in results] == list(range(64))
    assert len({r['root_id'] for r in results}) == 64
    assert sum(r['status'] == 'valid' for r in results) == (64 if damage is None else 63)
    if damage:
        assert results[0]['status'] == 'refused' and results[0]['reason']
        assert 'fixture' not in results[0]
    for result in results:
        if result['status'] == 'valid':
            public = result['fixture'].to_json()
            assert all(k not in public for k in ('deck', 'hands', 'round_seed'))


def test_manifest_refused_before_any_shard_open(frame, monkeypatch):
    manifest, pin, _ = frame
    monkeypatch.setattr(module, '_read_shard', lambda *a: pytest.fail('opened shard'))
    with pytest.raises(ValueError, match='SHA256'):
        module.read_s11_inputs(manifest + b' ', sha256=pin, root='/unused')


@pytest.mark.parametrize('kind', ['file-link', 'directory-link', 'fifo', 'size', 'path'])
def test_shard_file_boundary(tmp_path, kind):
    directory = tmp_path / 'shards'
    directory.mkdir()
    path = directory / 'cluster-000000.jsonl'
    item = SimpleNamespace(cluster=0, path='shards/cluster-000000.jsonl', byte_count=2)
    if kind == 'file-link':
        target = tmp_path / 'target'
        target.write_bytes(b'{}')
        path.symlink_to(target)
    elif kind == 'directory-link':
        directory.rename(tmp_path / 'elsewhere')
        directory.symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    elif kind == 'fifo':
        import os
        os.mkfifo(path)
    else:
        path.write_bytes(b'{}')
        if kind == 'size':
            item.byte_count = 3
        else:
            item.path = '../escape'
    with pytest.raises((ValueError, OSError)):
        module._read_shard(tmp_path, item)
