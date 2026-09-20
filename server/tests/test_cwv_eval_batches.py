from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import cwv_eval_batches as batching
from tests.test_cwv_train import store_dir, blocks, luna, other_dir, other_records  # noqa: F401
from tests.test_cwv_train_policy_head import policy_rows  # noqa: F401


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


@pytest.mark.parametrize('joint,version', [(False, 2), (True, 2), (True, 5)],
                         ids=['value', 'joint-v2', 'joint-v5'])
def test_packing_preserves_training_selection_and_weights(
        store_dir, luna, policy_rows, tmp_path, monkeypatch, joint, version):
    import torch
    from shengji.train import train_cwv
    from tests.test_cwv_train import train_v0, THIRDS
    train_v0.train(data=[str(store_dir)], out=tmp_path/'public', device='cpu', epochs=1,
        seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
        encoder_version=train_cwv.DEFAULTS['encoder_version'], **THIRDS)
    real_eval = train_cwv.run_eval
    def evaluate(model, store, mask, device, **kwargs):
        # Split real cached rows contiguously to ensure this tiny fixture
        # exercises cross-shard packing even when validation holds one deal.
        def pieces(**kw):
            for block in store.iter_blocks(**kw):
                for start in range(0,block.n,17):
                    yield block.subset(np.arange(start,min(start+17,block.n)))
        return real_eval(model,SimpleNamespace(iter_blocks=pieces),mask,device,
                         **kwargs)
    monkeypatch.setattr(train_cwv,'run_eval',evaluate)
    kwargs=dict(data=[str(store_dir)],eval_luna=str(luna[0]),arch='mlp',device='cpu',
        epochs=2,seed=7,batch_size=64,n_boot=20,hidden=32,log=None,
        cache_workers=1,eval_workers=1,bench_batch=32,
        public_head=str(tmp_path/'public'/'best.pt'),**THIRDS)
    if joint:
        from shengji.train import search_mean_sidecar
        if version == 5:
            from shengji.train import policy_prior
            rows = tmp_path/'policy-rows-v5'
            extracted = policy_prior.extract(rows, [str(store_dir)], lo=0.0, hi=1.01,
                thin=1.0, max_rows=400, workers=1, version=5)
            assert extracted['rows'] > 20
            policy_rows = str(rows)
        side = tmp_path/'sidecar'
        built = [search_mean_sidecar.build_sidecar(p, side, level_objective=False)
                 for p in sorted(store_dir.rglob('*.jsonl'))]
        assert sum(row['with_mean'] for row in built) > 0
        kwargs.update(encoder_version=version, aux_points=True, search_head=True,
                      search_mean_sidecar=str(side),
                      policy_head=True, policy_rows=policy_rows, policy_eval=policy_rows,
                      policy_weight=0.2, policy_batch_fraction=0.5)
    a=train_cwv.train(out=tmp_path/'legacy',**kwargs)
    b=train_cwv.train(out=tmp_path/'packed',pack_validation_shards=True,**kwargs)
    assert 'validation_packing' not in a['config']
    assert b['config']['validation_packing']['scope'] == 'epoch-outcome-validation-only'
    if joint:
        for result in (a, b):
            assert result['model']['config']['enc_version'] == version
            assert result['model']['config']['policy_head']
            assert result['model']['config']['search_head']
            assert all(epoch['train']['policy_rows'] > 0 for epoch in result['epochs'])
        for left, right in zip(a['epochs'], b['epochs']):
            assert left['val']['policy'] == right['val']['policy']
    assert a['selection']['best_epoch']==b['selection']['best_epoch']
    assert a['selection']['best_loss']==pytest.approx(b['selection']['best_loss'],abs=1e-7)
    ma,_,aa=train_cwv.load_cwv_checkpoint(tmp_path/'legacy'/'best.pt')
    mb,_,ab=train_cwv.load_cwv_checkpoint(tmp_path/'packed'/'best.pt')
    for name,tensor in ma.state_dict().items():
        assert torch.equal(tensor,mb.state_dict()[name]), name
    assert (aa is None) == (ab is None)
    if aa is not None:
        for name,tensor in aa.state_dict().items():
            assert torch.equal(tensor,ab.state_dict()[name]), name


def test_packing_cli_is_explicit_and_rejects_non_mlp(tmp_path):
    from shengji.train import train_cwv
    args = ['train', '--data', str(tmp_path), '--out', str(tmp_path/'out')]
    assert not train_cwv.build_parser().parse_args(args).pack_validation_shards
    assert train_cwv.build_parser().parse_args(args+['--pack-validation-shards']).pack_validation_shards
    with pytest.raises(train_cwv.TrainError, match='MLP only'):
        train_cwv.train(data=[str(tmp_path)], out=tmp_path/'out', arch='seq',
                        pack_validation_shards=True)
    assert not (tmp_path/'out').exists()
