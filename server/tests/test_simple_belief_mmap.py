import numpy as np
import pytest
import torch

from shengji.train.simple_belief_mmap import load_split_disk
from shengji.train import simple_belief_train as train
from test_simple_belief_train import _make_cache


def test_disk_training_is_bit_identical_and_never_opens_check(tmp_path, monkeypatch):
    _make_cache(tmp_path)
    original = train.np.load
    def guarded(path, *args, **kwargs):
        assert 'check.npz' not in str(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(train.np, 'load', guarded)
    for disk in (False, True):
        train.train_simple_belief(tmp_path, tmp_path/str(disk), epochs=3,
            threads=1, batch_size=4, width=12, hidden=8, seed=3, disk_backed=disk)
    a = torch.load(tmp_path/'False'/'last.pt', weights_only=False)
    b = torch.load(tmp_path/'True'/'last.pt', weights_only=False)
    assert all(torch.equal(a['model'][k], b['model'][k]) for k in a['model'])
    assert [r['loss'] for r in a['curves']] == [r['loss'] for r in b['curves']]
    assert a['best_dev_ce'] == b['best_dev_ce']
    with pytest.raises(ValueError, match='refuses check'):
        load_split_disk(tmp_path, 'check')


def test_committed_disk_cache_reuses_without_opening_npz(tmp_path, monkeypatch):
    _make_cache(tmp_path)
    a = load_split_disk(tmp_path, 'train')
    expected = tuple(np.asarray(x).copy() for x in a)
    monkeypatch.setattr(train, '_load_file', lambda *a: pytest.fail('completed rows reloaded'))
    b = load_split_disk(tmp_path, 'train')
    assert all(np.array_equal(x, y) for x, y in zip(expected, b))
    (tmp_path/'dense-train'/'targets.npy').unlink()
    with pytest.raises(ValueError, match='committed disk array is missing'):
        load_split_disk(tmp_path, 'train')


def test_chunked_count_prior_is_exact_for_multiple_chunks():
    targets = np.random.default_rng(1).integers(0, 3, (8200, 4, 54), dtype=np.uint8)
    counts = np.stack([(targets == cls).sum(axis=0) for cls in range(3)], axis=-1)
    expected = counts.astype(np.float32)+1e-6
    expected /= expected.sum(axis=-1, keepdims=True)
    assert np.array_equal(train._count_prior(targets).numpy(), expected[None])
