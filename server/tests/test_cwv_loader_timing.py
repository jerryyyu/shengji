from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import cwv_data
from shengji.train.cwv_data import CwvBlock, CwvBlockStore, N_CARDS, PUBLIC_DIM, WORLD_RECEIVERS


def _block(number: int, rows: int = 2) -> CwvBlock:
    base = number * 100
    text = np.asarray([f"deal-{base + i}" for i in range(rows)])
    arrays = {
        "public": np.full((rows, PUBLIC_DIM), base, dtype=np.float32),
        "world": np.full((rows, WORLD_RECEIVERS, N_CARDS), number, dtype=np.uint8),
        "perspective": np.arange(base, base + rows, dtype=np.uint8),
        "target": np.arange(base, base + rows, dtype=np.int64),
        "utility": np.arange(base, base + rows, dtype=np.float32),
        "attacker_points": np.arange(base, base + rows, dtype=np.float32),
        "points_so_far": np.arange(base, base + rows, dtype=np.float32),
        "ply": np.arange(rows, dtype=np.int32),
        "role_attacker": np.asarray([(i + number) % 2 for i in range(rows)], dtype=bool),
        "seat": np.arange(rows, dtype=np.int8),
        "deal_key": text,
        "cluster": text,
        "source_ref": text,
        "record_sha256": text,
        "input_sha256": text,
        "has_search_means": np.zeros(rows, dtype=bool),
        "n_search": np.zeros(rows, dtype=np.int32),
    }
    return CwvBlock(arrays, {})


def _store(blocks: list[CwvBlock]) -> CwvBlockStore:
    store = object.__new__(CwvBlockStore)
    store.entries = [(SimpleNamespace(label=f"tiny-{i}"), f"tiny-{i}")
                     for i in range(len(blocks))]
    store.sizes = [1] * len(blocks)
    store.residency = SimpleNamespace(budget=None)
    store.block = lambda i, *, pinned=(), decoded=None: blocks[i]
    store.windows = CwvBlockStore.windows.__get__(store)
    store.iter_batches = CwvBlockStore.iter_batches.__get__(store)
    return store


def _collect(store, *, seed: int, stage_secs=None):
    return [{name: np.array(value, copy=True) for name, value in batch.items()}
            for batch in store.iter_batches(
                lambda block: block.target % 2 == 0,
                2,
                rng=np.random.default_rng(seed),
                window=2,
                stage_secs=stage_secs,
            )]


def test_opt_in_timing_preserves_every_batch_field():
    plain = _collect(_store([_block(0), _block(1), _block(2)]), seed=17)
    stages = {"caller": 3.0}
    timed = _collect(_store([_block(0), _block(1), _block(2)]), seed=17,
                     stage_secs=stages)

    assert stages["caller"] == 3.0
    assert set(stages) == {"caller", "setup", "decode", "prepare", "gather", "cleanup"}
    assert len(timed) == len(plain)
    for actual, expected in zip(timed, plain):
        assert set(actual) == set(expected)
        for name in expected:
            np.testing.assert_array_equal(actual[name], expected[name])


def test_default_path_does_not_read_clock(monkeypatch):
    def fail_clock():
        raise AssertionError("default loader path read the timing clock")

    monkeypatch.setattr(cwv_data.time, "perf_counter", fail_clock)
    assert _collect(_store([_block(0), _block(1)]), seed=4)


def test_timing_excludes_consumer_pause_and_partial_close_cleans_pool(monkeypatch):
    now = [0.0]
    future_error = [None]

    class Future:
        def result(self):
            now[0] += 5.0
            if future_error[0] is not None:
                raise future_error[0]
            return None

    class Pool:
        def __init__(self, *, max_workers):
            self.max_workers = max_workers

        def submit(self, *args):
            return Future()

        def shutdown(self, *, cancel_futures):
            assert cancel_futures
            now[0] += 7.0

    monkeypatch.setattr(cwv_data.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(cwv_data, "ProcessPoolExecutor", Pool)
    blocks = [_block(0, rows=1), _block(1, rows=1)]
    store = _store(blocks)
    store.is_resident = lambda i: False
    store._key = lambda i: i
    store.decode_task = lambda i: ("tiny", "sha", False)
    store.decode_submitted = 0
    store.residency.make_room = lambda *args, **kwargs: None
    store.sizes = [1, 1]
    original_block = store.block

    def timed_block(i, *, pinned=(), decoded=None):
        now[0] += 2.0
        return original_block(i, pinned=pinned, decoded=decoded)

    store.block = timed_block
    original_gather = cwv_data.gather

    def timed_gather(*args, **kwargs):
        now[0] += 4.0
        return original_gather(*args, **kwargs)

    monkeypatch.setattr(cwv_data, "gather", timed_gather)
    stages = {}
    batches = store.iter_batches(lambda block: np.ones(block.n, dtype=bool), 1,
                                 rng=np.random.default_rng(2), window=1,
                                 decode_workers=1, stage_secs=stages)
    next(batches)
    now[0] += 100.0  # time spent by the consumer while suspended at yield
    next(batches)
    assert stages["decode"] == 14.0
    assert stages["gather"] == 8.0
    batches.close()
    assert stages["cleanup"] == 7.0

    error = RuntimeError("synthetic decoder failure")
    future_error[0] = error
    failed_stages = {}
    failed = store.iter_batches(lambda block: np.ones(block.n, dtype=bool), 1,
                                rng=np.random.default_rng(2), window=1,
                                decode_workers=1, stage_secs=failed_stages)
    with pytest.raises(RuntimeError) as caught:
        next(failed)
    assert caught.value is error
    assert failed_stages["cleanup"] == 7.0
