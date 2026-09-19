"""`gather(..., strings=False)` omits the identity columns; the default keeps them.

The training step reads only the numeric tensors (`tensors_of`), so the
train loop passes `strings=False` to skip the per-row Python build of
`deal_key` / `source_ref` / `input_sha256` (~1.3 ms of ~7.6 ms per
1024-row history batch, measured Sep 2026).  Eval keeps the default:
it clusters by `deal_key`.
"""
import numpy as np
import pytest
import torch

from shengji.train import cwv_data
from shengji.train.cwv_data import CwvBlock, gather, tensors_of
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS

WORLD_RECEIVERS = cwv_data.WORLD_RECEIVERS
PUBLIC_DIM = 32  # synthetic width; gather reads it off the block


def _block(n, seed, history=True):
    rng = np.random.default_rng(seed)
    arrays = {
        "public": rng.random((n, PUBLIC_DIM)).astype(np.float32),
        "world": rng.integers(0, 3, size=(n, WORLD_RECEIVERS, N_CARDS)).astype(np.uint8),
        "perspective": rng.integers(0, 2, size=n).astype(np.uint8),
        "target": rng.integers(0, 204, size=n).astype(np.int64),
        "utility": rng.random(n).astype(np.float32),
        "attacker_points": rng.integers(0, 200, size=n).astype(np.float32),
        "points_so_far": rng.integers(0, 200, size=n).astype(np.float32),
        "ply": rng.integers(0, 40, size=n).astype(np.int32),
        "role_attacker": rng.integers(0, 2, size=n).astype(bool),
        "seat": rng.integers(0, 4, size=n).astype(np.int8),
        "deal_key": np.asarray([f"deck:{i:064x}" for i in range(seed * 1000, seed * 1000 + n)],
                               dtype=str),
        "cluster": np.asarray([f"c{i % 3}" for i in range(n)], dtype=str),
        "source_ref": np.asarray([f"shard/deal{i}" for i in range(n)], dtype=str),
        "record_sha256": np.asarray([f"{i:064x}" for i in range(n)], dtype=str),
        "input_sha256": np.asarray([f"in{i:060x}" for i in range(n)], dtype=str),
        "has_search_means": np.zeros(n, dtype=bool),
        "n_search": np.zeros(n, dtype=np.int64),
    }
    if history:
        lengths = rng.integers(1, 6, size=n)
        offsets = np.zeros(n + 1, dtype=np.int64)
        offsets[1:] = np.cumsum(lengths)
        total = int(lengths.sum())
        arrays["history_cards"] = rng.integers(0, 3, size=(total, N_CARDS)).astype(np.uint8)
        arrays["history_meta"] = np.stack(
            [rng.integers(0, 4, size=total), rng.integers(0, 4, size=total),
             rng.integers(0, 25, size=total), rng.integers(0, 41, size=total)],
            axis=1).astype(np.uint8)
        arrays["history_offsets"] = offsets
    return CwvBlock(arrays, {"encoder": "synthetic"})


@pytest.fixture()
def two_blocks():
    return [_block(24, seed=1), _block(30, seed=2)]


def _plan(blocks, b=40, seed=7):
    rng = np.random.default_rng(seed)
    which = rng.integers(0, len(blocks), size=b).astype(np.int64)
    rows = np.array([rng.integers(0, blocks[int(w)].n) for w in which], dtype=np.int64)
    return which, rows


def test_default_keeps_string_columns(two_blocks):
    which, rows = _plan(two_blocks)
    out = gather(two_blocks, which, rows)
    for name in cwv_data._STRING_COLUMNS:
        assert name in out, f"default gather must keep {name}"
        col = out[name]
        assert col.shape == (len(rows),)
        for j, (w, r) in enumerate(zip(which.tolist(), rows.tolist())):
            assert col[j] == getattr(two_blocks[w], name)[r]


def test_strings_false_omits_only_the_identity_columns(two_blocks):
    which, rows = _plan(two_blocks)
    full = gather(two_blocks, which, rows)
    slim = gather(two_blocks, which, rows, strings=False)
    for name in cwv_data._STRING_COLUMNS:
        assert name not in slim, f"strings=False must omit {name}"
    assert set(slim) == set(full) - set(cwv_data._STRING_COLUMNS)
    for name, arr in slim.items():
        other = full[name]
        assert arr.shape == other.shape and arr.dtype == other.dtype
        np.testing.assert_array_equal(np.ascontiguousarray(arr),
                                      np.ascontiguousarray(other))


def test_tensors_of_accepts_the_slim_batch(two_blocks):
    # the train step's whole read of a batch
    which, rows = _plan(two_blocks)
    slim = gather(two_blocks, which, rows, strings=False)
    t = tensors_of(slim, torch.device("cpu"))
    assert t["public"].shape == (len(rows), PUBLIC_DIM)
    assert t["history"].shape[0] == len(rows)
    assert t["target"].shape == (len(rows),)


def test_strings_false_without_history():
    blocks = [_block(16, seed=3, history=False), _block(20, seed=4, history=False)]
    which, rows = _plan(blocks, b=24)
    out = gather(blocks, which, rows, strings=False)
    for name in cwv_data._STRING_COLUMNS:
        assert name not in out
    assert "history" not in out
    assert out["public"].shape == (24, PUBLIC_DIM)
    t = tensors_of(out, torch.device("cpu"))
    assert t["history"].shape == (24, 1, HISTORY_EVENT_DIM)  # the all-zero fallback
