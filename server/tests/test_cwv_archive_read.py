import json
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import cwv_data as c
from shengji.train.data import TrainDataError
from test_cwv_loader_timing import _block


@pytest.fixture
def cache(tmp_path):
    block = _block(0, rows=4)
    arrays = {name: getattr(block, name) for name in c.CwvBlock.ARRAYS}
    meta = dict(schema=c.CACHE_SCHEMA, encoder=c.cwv_encoder_identity(),
                shard={'sha256': 'fixture'}, sees_hidden_hands=True, history=False,
                nbytes=sum(a.nbytes for a in arrays.values()))
    path = tmp_path / 'cache.npz'
    np.savez_compressed(path, meta=json.dumps(meta), **arrays)
    return path, arrays, meta


@pytest.mark.parametrize('reader', ['block', 'worker', 'columns'])
def test_decoder_checks_metadata_and_reads_arrays_in_one_archive(cache, monkeypatch, reader):
    path, arrays, meta = cache
    original = c.zipfile.ZipFile
    opens = []

    def tracked(*args, **kwargs):
        opens.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(c.zipfile, 'ZipFile', tracked)
    if reader == 'block':
        block = c.load_block(path, shard_sha256='fixture', history=False)
        got = {name: getattr(block, name) for name in arrays}
        assert block.meta == meta
    elif reader == 'worker':
        got, got_meta = c.decode_arrays((str(path), 'fixture', False))
        assert got_meta == meta
    else:
        got = c.read_columns((str(path), 'fixture', False, ('target', 'deal_key'), None))
    assert len(opens) == 1
    for name, value in got.items():
        np.testing.assert_array_equal(value, arrays[name])
        assert value.dtype == arrays[name].dtype


@pytest.mark.parametrize('reader', ['block', 'worker', 'columns'])
def test_wrong_metadata_refuses_before_tensor_members(cache, monkeypatch, reader):
    path, _, _ = cache
    names = []
    original = c._read_member

    def tracked(archive, name):
        names.append(name)
        return original(archive, name)

    monkeypatch.setattr(c, '_read_member', tracked)
    with pytest.raises(TrainDataError, match='another shard'):
        if reader == 'block':
            c.load_block(path, shard_sha256='wrong')
        elif reader == 'worker':
            c.decode_arrays((str(path), 'wrong', False))
        else:
            c.read_columns((str(path), 'wrong', False, ('target',), None))
    assert names == ['meta']


def test_actual_store_iterator_reaches_batch_consumer(cache):
    path, arrays, _ = cache
    store = c.CwvBlockStore([(SimpleNamespace(sha256='fixture', label='fixture'), str(path))])
    batches = list(store.iter_batches(lambda block: np.ones(block.n, bool), 2,
                                     window=1, decode_workers=0))
    assert len(batches) == 2
    for name in ('public', 'world', 'target', 'deal_key', 'source_ref', 'input_sha256'):
        np.testing.assert_array_equal(np.concatenate([b[name] for b in batches]), arrays[name])


def test_object_metadata_remains_forbidden(tmp_path):
    path = tmp_path / 'object.npz'
    np.savez(path, meta=np.asarray({'unexpected': True}, dtype=object))
    with pytest.raises(ValueError, match='Object arrays cannot be loaded'):
        c.read_meta(path)
