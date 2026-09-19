"""Bounded parity tests for omitting identity strings from training batches."""

from __future__ import annotations

import copy
from concurrent.futures import Future

import numpy as np

from shengji.train import cwv_data as data
from shengji.train import train_cwv
from tests.test_cwv_train import store_dir


def _block(n: int = 6, *, history: bool = True) -> data.CwvBlock:
    arrays = {
        "public": np.arange(n * 4, dtype=np.float32).reshape(n, 4),
        "world": (np.arange(n * data.WORLD_RECEIVERS * data.N_CARDS, dtype=np.uint8)
                  .reshape(n, data.WORLD_RECEIVERS, data.N_CARDS) % 3),
        "perspective": np.arange(n, dtype=np.uint8) % 2,
        "target": np.arange(n, dtype=np.int16),
        "utility": np.arange(n, dtype=np.float32) + .25,
        "attacker_points": np.arange(n, dtype=np.float32) + 40,
        "points_so_far": np.arange(n, dtype=np.float32) + 10,
        "ply": np.arange(n, dtype=np.int16) + 3,
        "role_attacker": (np.arange(n) % 2).astype(bool),
        "seat": np.arange(n, dtype=np.int8) % 4,
        "deal_key": np.asarray([f"deal-{i}" for i in range(n)], dtype=str),
        "cluster": np.asarray([f"cluster-{i}" for i in range(n)], dtype=str),
        "source_ref": np.asarray([f"source-{i}" for i in range(n)], dtype=str),
        "record_sha256": np.asarray([f"record-{i}" for i in range(n)], dtype="S64"),
        "input_sha256": np.asarray([f"input-{i}" for i in range(n)], dtype="S64"),
        "has_search_means": (np.arange(n) % 2).astype(bool),
        "n_search": np.arange(n, dtype=np.int16) + 1,
        "search_mean_played": np.arange(n, dtype=np.float32) + .5,
    }
    if history:
        lengths = np.asarray([1, 2, 3, 1, 2, 3][:n], dtype=np.int64)
        total = int(lengths.sum())
        arrays["history_cards"] = (
            np.arange(total * data.N_CARDS, dtype=np.uint8)
            .reshape(total, data.N_CARDS) % 3)
        arrays["history_meta"] = np.arange(total * data.HISTORY_META_DIM,
                                            dtype=np.uint8).reshape(
                                                total, data.HISTORY_META_DIM) % 4
        arrays["history_offsets"] = np.concatenate(([0], np.cumsum(lengths)))
    return data.CwvBlock(arrays, {"history": history})


def _bytes_equal(left, right):
    assert set(left) == set(right)
    for name in left:
        assert left[name].shape == right[name].shape, name
        assert left[name].dtype == right[name].dtype, name
        assert left[name].tobytes() == right[name].tobytes(), name


def test_gather_skip_strings_preserves_numeric_optional_history_and_partial_rows():
    block = _block()
    which = np.asarray([0, 0, 0, 0], dtype=np.int64)
    rows = np.asarray([5, 0, 3, 1], dtype=np.int64)
    full = data.gather([block], which, rows)
    explicit = data.gather([block], which, rows, include_strings=True)
    numeric = data.gather([block], which, rows, include_strings=False)

    _bytes_equal(full, explicit)
    assert set(full) - set(numeric) == set(data._STRING_COLUMNS)
    _bytes_equal({k: full[k] for k in numeric}, numeric)
    assert "search_mean_played" in numeric
    assert "history" in numeric and "history_mask" in numeric
    assert numeric["lengths"].tolist() == [3, 1, 1, 2]


class _FakeResidency:
    budget = None

    def make_room(self, *args, **kwargs):
        pass

    def get(self, key):
        return None


class _FakeStore:
    def __init__(self, blocks):
        self.blocks = blocks
        self.entries = [(object(), f"block-{i}") for i in range(len(blocks))]
        self.sizes = [1] * len(blocks)
        self.residency = _FakeResidency()
        self.history = bool(blocks[0].history)
        self.decode_submitted = 0

    def windows(self, order, window):
        return [[int(i)] for i in order]

    def is_resident(self, i):
        return False

    def _key(self, i):
        return ("fake", i)

    def decode_task(self, i):
        return (f"block-{i}", None, self.history)

    def block(self, i, *, pinned=(), decoded=None):
        return self.blocks[i]


class _ReadyPool:
    instances = []

    def __init__(self, max_workers):
        self.max_workers = max_workers
        self.submitted = []
        self.__class__.instances.append(self)

    def submit(self, fn, task):
        self.submitted.append((fn, task))
        future = Future()
        future.set_result(({}, {}))
        return future

    def shutdown(self, **kwargs):
        pass


def _batch_bytes(batches):
    return [[(name, value.dtype.str, value.shape, value.tobytes())
             for name, value in sorted(batch.items())]
            for batch in batches]


def test_iter_batches_forwards_skip_in_serial_and_parallel_without_order_drift(monkeypatch):
    blocks = [_block(4), _block(4)]
    calls = []
    real_gather = data.gather

    def traced_gather(*args, **kwargs):
        calls.append(kwargs.get("include_strings"))
        return real_gather(*args, **kwargs)

    monkeypatch.setattr(data, "gather", traced_gather)
    store = _FakeStore(blocks)
    mask = lambda block: np.ones(block.n, dtype=bool)  # noqa: E731
    serial_rng = np.random.default_rng(71)
    serial = list(data.CwvBlockStore.iter_batches(
        store, mask, 3, rng=serial_rng, window=2, include_strings=False))
    serial_state = copy.deepcopy(serial_rng.bit_generator.state)

    _ReadyPool.instances.clear()
    monkeypatch.setattr(data, "ProcessPoolExecutor", _ReadyPool)
    parallel_rng = np.random.default_rng(71)
    parallel = list(data.CwvBlockStore.iter_batches(
        store, mask, 3, rng=parallel_rng, window=2, decode_workers=2,
        include_strings=False))
    assert _batch_bytes(serial) == _batch_bytes(parallel)
    assert serial_state == parallel_rng.bit_generator.state
    assert calls and not any(calls)
    assert _ReadyPool.instances[0].submitted
    assert all("deal_key" not in batch for batch in parallel)


def test_tiny_training_consumer_runs_with_string_free_batches(store_dir, tmp_path, monkeypatch):
    """Exercise the real train loop, not only the gather implementation."""
    original = data.CwvBlockStore.iter_batches
    seen = []

    def traced(store, *args, **kwargs):
        seen.append(kwargs.get("include_strings"))
        for batch in original(store, *args, **kwargs):
            assert not (set(data._STRING_COLUMNS) & set(batch))
            yield batch

    monkeypatch.setattr(data.CwvBlockStore, "iter_batches", traced)
    receipt = train_cwv.train(
        data=[str(store_dir)], out=tmp_path / "tiny", device="cpu", epochs=1,
        seed=23, batch_size=64, hidden=16, n_boot=2, patience=1,
        val_fraction=1 / 3, test_fraction=1 / 3, cache_workers=1,
        eval_workers=1, val_rank_records=0, log=None)
    assert receipt["command"] == "train"
    assert seen and all(value is False for value in seen)
