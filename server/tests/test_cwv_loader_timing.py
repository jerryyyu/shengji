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
    store.residency = SimpleNamespace(budget=None, loads=0, evictions=0,
                                      make_room=lambda *args, **kwargs: None)
    store.block = lambda i, *, pinned=(), decoded=None: blocks[i]
    store.windows = CwvBlockStore.windows.__get__(store)
    store.iter_batches = CwvBlockStore.iter_batches.__get__(store)
    return store


def _collect(store, *, seed: int, stage_secs=None, decode_stage_secs=None):
    return [{name: np.array(value, copy=True) for name, value in batch.items()}
            for batch in store.iter_batches(
                lambda block: block.target % 2 == 0,
                2,
                rng=np.random.default_rng(seed),
                window=2,
                stage_secs=stage_secs,
                decode_stage_secs=decode_stage_secs,
            )]


def test_opt_in_timing_preserves_every_batch_field():
    plain = _collect(_store([_block(0), _block(1), _block(2)]), seed=17)
    stages = {"caller": 3.0}
    details = {}
    timed = _collect(_store([_block(0), _block(1), _block(2)]), seed=17,
                     stage_secs=stages, decode_stage_secs=details)

    assert stages["caller"] == 3.0
    assert set(stages) == {"caller", "setup", "decode", "prepare", "gather", "cleanup"}
    assert set(details) == {"submit", "future_wait", "block"}
    assert details["future_wait"] == 0.0  # serial loading, not worker wait
    assert all(value >= 0 for value in details.values())
    assert sum(details.values()) <= stages["decode"]
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
            now[0] += 3.0
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
    details = {}
    batches = store.iter_batches(lambda block: np.ones(block.n, dtype=bool), 1,
                                 rng=np.random.default_rng(2), window=1,
                                 decode_workers=1, stage_secs=stages,
                                 decode_stage_secs=details)
    next(batches)
    now[0] += 100.0  # time spent by the consumer while suspended at yield
    next(batches)
    assert stages["decode"] == 20.0
    assert details == {"submit": 6.0, "future_wait": 10.0, "block": 4.0}
    assert stages["gather"] == 8.0
    batches.close()
    assert stages["cleanup"] == 7.0

    error = RuntimeError("synthetic decoder failure")
    future_error[0] = error
    failed_stages = {}
    failed_details = {}
    failed = store.iter_batches(lambda block: np.ones(block.n, dtype=bool), 1,
                                rng=np.random.default_rng(2), window=1,
                                decode_workers=1, stage_secs=failed_stages,
                                decode_stage_secs=failed_details)
    with pytest.raises(RuntimeError) as caught:
        next(failed)
    assert caught.value is error
    assert failed_stages["cleanup"] == 7.0
    assert failed_details == {"submit": 3.0, "future_wait": 5.0, "block": 0.0}


def test_stage_counts_cover_parallel_loader_and_exclude_consumer_residency(monkeypatch):
    class Future:
        def result(self):
            return None

    class Pool:
        def __init__(self, *, max_workers):
            self.max_workers = max_workers

        def submit(self, *args):
            return Future()

        def shutdown(self, *, cancel_futures):
            assert cancel_futures

    monkeypatch.setattr(cwv_data, "ProcessPoolExecutor", Pool)
    store = _store([_block(0, rows=1), _block(1, rows=1)])
    store.is_resident = lambda i: False
    store._key = lambda i: i
    store.decode_task = lambda i: ("tiny", "sha", False)
    store.residency.loads = 0
    store.residency.evictions = 0
    original_block = store.block

    def loading_block(i, *, pinned=(), decoded=None):
        store.residency.loads += 1
        return original_block(i, pinned=pinned, decoded=decoded)

    store.block = loading_block
    counts = {}
    batches = store.iter_batches(lambda block: np.ones(block.n, dtype=bool), 1,
                                 rng=np.random.default_rng(2), window=1,
                                 decode_workers=1, stage_counts=counts)
    next(batches)
    # This simulates consumer-side residency activity while the iterator is suspended.
    store.residency.loads += 100
    store.residency.evictions += 50
    next(batches)
    batches.close()

    assert counts == {
        "windows": 2,
        "requested_shards": 2,
        "decode_submitted": 2,
        "serial_budget_fallback_windows": 0,
        "residency_loads": 2,
        "residency_evictions": 0,
    }


def test_stage_counts_record_oversized_parallel_window_serial_fallback(monkeypatch):
    class Future:
        def result(self):
            return None

    class Pool:
        def __init__(self, *, max_workers):
            self.max_workers = max_workers

        def submit(self, *args):
            return Future()

        def shutdown(self, *, cancel_futures):
            assert cancel_futures

    monkeypatch.setattr(cwv_data, "ProcessPoolExecutor", Pool)
    store = _store([_block(0, rows=1), _block(1, rows=1), _block(2, rows=1)])
    store.sizes = [2, 2, 1]
    store.residency.budget = 3
    store.is_resident = lambda i: False
    store._key = lambda i: i
    store.decode_task = lambda i: ("tiny", "sha", False)
    # windows() normally prevents this branch; keep the test focused on the
    # defensive submit decision without changing normal window construction.
    store.windows = lambda order, window: [[0, 1], [2]]
    counts = {}
    batches = store.iter_batches(lambda block: np.ones(block.n, dtype=bool), 1,
                                 rng=np.random.default_rng(2), window=2,
                                 decode_workers=1, stage_counts=counts)
    list(batches)

    assert counts["windows"] == 2
    assert counts["requested_shards"] == 3
    assert counts["serial_budget_fallback_windows"] == 1
    assert counts["decode_submitted"] == 1


@pytest.mark.parametrize("seed", [1, 17])
@pytest.mark.parametrize("window", [1, 2, 4])
@pytest.mark.parametrize("workers", [0, 2])
@pytest.mark.parametrize("sidecar", [False, True])
def test_split_skips_heldout_decode_without_changing_batches_or_rng(
        monkeypatch, seed, window, workers, sidecar):
    # Mixed-deal shard 2 must still load; shard 1 is entirely held out.
    blocks = [_block(i, rows=3) for i in range(3)]
    for block in blocks:
        block.optional = CwvBlock.OPTIONAL_ARRAYS
        for name in block.optional:
            setattr(block, name, np.full(block.n, float(block.target[0])))
    if not sidecar:
        # A held-out shard can still control gather's optional-column schema.
        blocks[1].optional = ()
    assignment = {key: ("train" if i == 0 or (i == 2 and j == 0) else "val")
                  for i, block in enumerate(blocks)
                  for j, key in enumerate(block.deal_key.tolist())}
    selector = cwv_data.SplitSelector(assignment, "train")
    submissions = []

    class Future:
        def result(self):
            return None

    class Pool:
        def __init__(self, **kw):
            pass

        def submit(self, fn, task):
            submissions.append(task)
            return Future()

        def shutdown(self, **kw):
            pass

    monkeypatch.setattr(cwv_data, "ProcessPoolExecutor", Pool)

    def collect(mask):
        store = _store(blocks)
        store.sidecar_dir = "fixture-sidecar" if sidecar else None
        store._keys = [block.deal_key for block in blocks]
        store.is_resident = lambda i: False
        store._key = lambda i: i
        store.decode_task = lambda i: i
        store.decode_submitted = 0
        loaded = []
        original = store.block

        def block(i, **kw):
            loaded.append(i)
            return original(i, **kw)

        store.block = block
        rng = np.random.default_rng(seed)
        counts = {}
        batches = list(store.iter_batches(mask, 2, rng=rng, window=window,
                                          decode_workers=workers, stage_counts=counts))
        return batches, rng.bit_generator.state, loaded, counts

    old, old_rng, old_loads, _ = collect(lambda block: selector(block))
    submissions.clear()
    new, new_rng, new_loads, counts = collect(selector)
    assert set(old_loads) == {0, 1, 2}
    assert set(new_loads) == ({0, 2} if sidecar else {0, 1, 2})
    if sidecar:
        assert 1 not in submissions
    assert counts["requested_shards"] == (2 if sidecar else 3)
    assert new_rng == old_rng
    assert len(new) == len(old)
    for actual, expected in zip(new, old):
        assert actual.keys() == expected.keys()
        for name in actual:
            np.testing.assert_array_equal(actual[name], expected[name])
