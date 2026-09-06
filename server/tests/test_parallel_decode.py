"""Decoding a window in worker processes must not change a single batch.

`iter_batches` documents its batch sequence as a function of the rng alone.
Moving the decode into a pool must leave that true, and must keep the
fail-closed hash check, which is why `decode_arrays` verifies in the child
rather than trusting the parent.

Built on a real generated store and the real `CwvBlockStore`, not a double.
"""
import hashlib
from pathlib import Path

import numpy as np
import pytest

from shengji.harvest import trajectory
from shengji.train import cwv_data
from shengji.train.data import Residency, SplitSelector, split_deals

SEED0 = 4_300_000
ROUNDS = 8
WORK = {"select_worlds": 2, "report_worlds": 30}
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}


@pytest.fixture(scope="module")
def store_and_selector(tmp_path_factory):
    out = tmp_path_factory.mktemp("pdec-traj") / "run"
    trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out, workers=1,
                        merge=False, allow_seed_overlap=True, **WORK, **EXPLORE)
    cache = tmp_path_factory.mktemp("pdec-cache")
    prepared = cwv_data.prepare_stores([str(out)], Path(cache), limit_clusters=None,
                                       history=False, witness_seed=1, cache_workers=1,
                                       residency=Residency(64_000_000))
    store = prepared.block_store
    assignment = split_deals(store.keys(), seed=1, val_fraction=0.25, test_fraction=0.25)
    return store, SplitSelector(assignment, "train")


def _digest(store, selector, workers, seed=1):
    h = hashlib.sha256()
    batches = 0
    for raw in store.iter_batches(selector, 16, rng=np.random.default_rng(seed),
                                  window=2, decode_workers=workers):
        batches += 1
        for key in sorted(raw):
            h.update(key.encode())
            h.update(np.ascontiguousarray(raw[key]).tobytes())
    return h.hexdigest(), batches


def test_worker_count_does_not_change_the_batches(store_and_selector):
    store, selector = store_and_selector
    base, n = _digest(store, selector, 0)
    assert n > 1, "the fixture must produce several batches"
    for workers in (1, 2):
        assert _digest(store, selector, workers) == (base, n), \
            f"{workers} worker(s) changed the batch stream"


def test_the_comparison_can_fail(store_and_selector):
    """Prove the equality above can fail: a different rng must be detected."""
    store, selector = store_and_selector
    base, _ = _digest(store, selector, 0)
    other, _ = _digest(store, selector, 2, seed=99)
    assert other != base


def test_decode_arrays_refuses_a_wrong_hash(store_and_selector):
    """The fail-closed check must run in the worker, not only in load_block."""
    store, _ = store_and_selector
    path, sha, history = store.decode_task(0)
    arrays, meta = cwv_data.decode_arrays((path, sha, history))
    assert arrays and meta
    with pytest.raises(Exception):
        cwv_data.decode_arrays((path, "0" * 64, history))
