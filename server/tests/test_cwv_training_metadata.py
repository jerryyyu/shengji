"""Training may omit provenance strings, never tensors or batch ordering."""
import json
import numpy as np
import pytest

from shengji.train import cwv_data as D
from shengji.train.cwv_pack import CwvPackStore, build_pack
from tests.test_cwv_train import THIRDS, records, store_dir  # noqa: F401
from tests.test_cwv_train_policy_head import policy_rows  # noqa: F401


def block(n=64, seed=7, history=False):
    rng = np.random.default_rng(seed)
    arrays = {name: np.zeros(n, dtype=np.int64) for name in D.CwvBlock.ARRAYS}
    arrays.update(public=rng.random((n, 561), dtype=np.float32),
                  world=rng.integers(0, 3, (n, D.WORLD_RECEIVERS, D.N_CARDS), dtype=np.uint8),
                  perspective=rng.integers(0, 2, n, dtype=np.uint8),
                  target=rng.integers(0, 2, n),
                  search_mean_played=rng.random(n, dtype=np.float32))
    for name in D._STRING_COLUMNS:
        arrays[name] = np.array([f'{name}-{seed}-{i:064d}' for i in range(n)])
    if history:
        arrays.update(history_offsets=np.arange(n + 1),
                      history_cards=rng.integers(0, 3, (n, D.N_CARDS), dtype=np.uint8),
                      history_meta=np.zeros((n, 4), dtype=np.uint8))
    return D.CwvBlock(arrays, {})


def assert_equal(full, lean):
    assert set(full) - set(lean) == set(D._STRING_COLUMNS)
    for key in lean:
        np.testing.assert_array_equal(lean[key], full[key])
        assert lean[key].dtype == full[key].dtype


@pytest.mark.parametrize('history', [False, True])
def test_gather_retains_every_numeric_field_and_optional_target(history):
    blocks = [block(history=history), block(seed=8, history=history)]
    which = np.array([1, 0, 1, 0, 0])
    rows = np.array([3, 8, 3, 1, 63])
    full = D.gather(blocks, which, rows)
    lean = D.gather(blocks, which, rows, include_metadata=False)
    assert_equal(full, lean)
    torch = pytest.importorskip('torch')
    a, b = D.tensors_of(full, 'cpu'), D.tensors_of(lean, 'cpu')
    assert a.keys() == b.keys()
    for key in a:
        assert torch.equal(a[key], b[key])
    # Same actual optimizer update, not just equal labels.
    torch.manual_seed(7)
    initial = torch.nn.Linear(561, 2).state_dict()
    results = []
    for tensors in (a, b):
        net = torch.nn.Linear(561, 2)
        net.load_state_dict(initial)
        opt = torch.optim.Adam(net.parameters(), lr=.001)
        loss = torch.nn.functional.cross_entropy(net(tensors['public']), tensors['target'])
        loss.backward()
        opt.step()
        results.append(net.state_dict())
    for key in results[0]:
        assert torch.equal(results[0][key], results[1][key])


@pytest.mark.parametrize('store_type', [D.CwvBlockStore, CwvPackStore])
def test_iter_batches_keeps_rng_order_and_default_metadata(store_type):
    blocks = [block(), block(seed=8)]
    store = object.__new__(store_type)
    store.entries = [None, None]
    store.windows = lambda order, window: [list(order)]
    store.block = lambda i, **kw: blocks[i]
    batches = []
    for metadata in (True, False):
        batches.append(list(store.iter_batches(lambda b: np.arange(b.n) % 2 == 0,
            11, rng=np.random.default_rng(19), include_metadata=metadata)))
    assert len(batches[0]) == len(batches[1]) == 6
    for full, lean in zip(*batches, strict=True):
        assert_equal(full, lean)


@pytest.mark.parametrize('packed', [False, True])
def test_real_joint_training_matches_with_and_without_metadata(packed, store_dir, policy_rows,
                                                              tmp_path, monkeypatch):
    """Actual mixed policy/value trainer, not a surrogate optimizer update."""
    import torch
    from shengji.train import train_cwv
    from shengji.ai.cwv_policy import load_cwv_checkpoint
    store_type = CwvPackStore if packed else D.CwvBlockStore
    original = store_type.iter_batches
    train_kw = {}
    if packed:
        cache = tmp_path / 'cache'
        pack = tmp_path / 'pack'
        prepared = D.prepare_stores([str(store_dir)], cache, limit_clusters=None,
            version=2, history=False, witness_seed=7, cache_workers=1)
        build_pack(prepared.block_store.entries, pack, classify_shards=3)
        train_kw = {'cache_dir': cache, 'pack_dir': str(pack)}
    models, receipts, auxiliaries = [], [], []
    for include in (True, False):
        calls = []
        def batches(self, *args, **kwargs):
            # Only override explicit optimizer opt-out; evaluation keeps metadata.
            if kwargs.get('include_metadata') is False:
                calls.append(True)
                kwargs['include_metadata'] = include
            return original(self, *args, **kwargs)
        monkeypatch.setattr(store_type, 'iter_batches', batches)
        out = tmp_path / ('full' if include else 'lean')
        receipts.append(train_cwv.train(data=[str(store_dir)], out=out,
            arch='mlp', device='cpu', epochs=1, seed=7, batch_size=64,
            n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1,
            bench_batch=32, val_rank_records=50, encoder_version=2,
            policy_head=True, policy_rows=policy_rows, policy_eval=policy_rows,
            aux_points=True, **train_kw, **THIRDS))
        assert calls, 'the actual optimizer iterator must exercise this option'
        model, meta, _ = load_cwv_checkpoint(out / 'best.pt')
        models.append(model.state_dict())
        aux = meta.get('aux_points_head')
        assert aux is not None
        auxiliaries.append(aux)
        # Reopen the terminal producer outputs: an epoch/checkpoint alone is
        # not a completed end-to-end run, and final evaluation must be kept.
        saved = json.loads((out / 'receipt.json').read_text())
        metrics = json.loads((out / 'metrics.json').read_text())
        assert saved['final'] == metrics['final'] == receipts[-1]['final']
        assert saved['exposure'] == receipts[-1]['exposure']
    assert models[0].keys() == models[1].keys()
    for name in models[0]:
        assert torch.equal(models[0][name], models[1][name]), name
    assert receipts[0]['population'] == receipts[1]['population']
    assert receipts[0]['exposure'] == receipts[1]['exposure']
    assert auxiliaries[0] == auxiliaries[1]
    assert receipts[0]['epochs'][0]['val']['policy'] == receipts[1]['epochs'][0]['val']['policy']
    # Throughput is deliberately not an equivalence target. Every reported
    # quality headline, including candidate ranking and points, is.
    for name, value in receipts[0]['headline_numbers'].items():
        if name != 'forward_positions_per_second_cpu_1024':
            assert value == receipts[1]['headline_numbers'][name], name
