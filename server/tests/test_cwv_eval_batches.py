from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import cwv_eval_batches as batching
from tests.test_cwv_train import store_dir, blocks  # noqa: F401


def fake_store(monkeypatch, lengths, history=False):
    blocks = []
    offset = 0
    for n in lengths:
        blocks.append(SimpleNamespace(n=n, history=history,
            target=np.arange(offset, offset+n), has_search_means=np.ones(n, bool)))
        offset += n
    monkeypatch.setattr(batching, 'collate', lambda block, idx: {'target': block.target[idx]})
    return SimpleNamespace(iter_blocks=lambda **kw: iter(blocks))


def test_packing_preserves_order_masks_and_tail(monkeypatch):
    store = fake_store(monkeypatch, [3, 0, 4, 6])
    mask = lambda b: b.target % 2 == 0
    raw = list(batching.eval_batches(store, mask, 4, pack=True))
    assert [len(r['target']) for r in raw] == [4, 3]
    np.testing.assert_array_equal(np.concatenate([r['target'] for r in raw]), np.arange(0, 13, 2))


def test_legacy_retains_shard_boundaries(monkeypatch):
    store = fake_store(monkeypatch, [3, 4, 6])
    assert [len(r['target']) for r in batching.eval_batches(store, lambda b: np.ones(b.n,bool), 4)] == [3,4,4,2]


def test_small_byte_budget_flushes_and_oversized_piece_refuses(monkeypatch):
    store = fake_store(monkeypatch, [2,2,2])
    mask = lambda b: np.ones(b.n,bool)
    assert [len(r['target']) for r in batching.eval_batches(store,mask,8,pack=True,staging_bytes=20)] == [2,2,2]
    with pytest.raises(ValueError, match='exceeds'):
        list(batching.eval_batches(store,mask,8,pack=True,staging_bytes=10))


def test_unicode_promotion_is_in_memory_estimate():
    parts = [{'target':np.zeros(1,np.int64),'key':np.array(['x'])},
             {'target':np.zeros(1,np.int64),'key':np.array(['longer'])}]
    merged = {k:np.concatenate([p[k] for p in parts]) for k in parts[0]}
    assert batching.merged_bytes(parts) == sum(a.nbytes for a in merged.values())


def test_history_packing_refuses(monkeypatch):
    store = fake_store(monkeypatch,[2],history=True)
    with pytest.raises(ValueError,match='history-free'):
        list(batching.eval_batches(store,lambda b:np.ones(b.n,bool),4,pack=True))


def test_predecode_skip_is_preserved(monkeypatch):
    class Mask:
        def selects_any(self, keys): return 'kept' in keys
    def iterate(*,skip):
        assert skip(['dropped']) and not skip(['kept'])
        return iter([])
    assert list(batching.eval_batches(SimpleNamespace(iter_blocks=iterate),Mask(),8,pack=True)) == []


def test_real_model_and_metadata_parity(blocks):
    import torch
    from shengji.train import train_cwv
    torch.manual_seed(7)
    model = train_cwv.ValueNetwork(train_cwv.model_config('mlp', hidden=32, encoder_version=1))
    store = SimpleNamespace(iter_blocks=lambda **kw: iter(blocks))
    mask = lambda b: np.arange(b.n) % 2 == 0
    a = train_cwv.run_eval(model,store,mask,'cpu',batch_size=128)
    b = train_cwv.run_eval(model,store,mask,'cpu',batch_size=128,pack_shards=True)
    assert a.keys() == b.keys()
    for key in a:
        if a[key].dtype.kind in 'fc':
            np.testing.assert_allclose(a[key],b[key],rtol=1e-6,atol=1e-6,equal_nan=True,err_msg=key)
        else:
            np.testing.assert_array_equal(a[key],b[key],err_msg=key)
