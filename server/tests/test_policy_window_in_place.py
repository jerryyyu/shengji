"""The in-place policy-row window (``PolicyRowsStream._fill_window``): uint8 codes for X when the
corpus has <= 256 distinct float16 values, the off-ballot negatives as a table of their real
slots, one allocation per window.  Every batch must equal the concatenating path's batch array
for array, dtype for dtype and byte for byte, for any rng, window, exclusion and limit."""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("torch")

from shengji.train import served_policy_rows as spr  # noqa: E402
from shengji.train.policy_rows import PolicyRowsStream  # noqa: E402
from test_cwv_train import store_dir  # noqa: E402,F401
from test_policy_rows_served import _records, pv_package, pv_store, served_store  # noqa: E402,F401


@pytest.fixture(scope="module")
def rows_dirs(served_store, tmp_path_factory):  # noqa: F811
    d, _recs, _marks = served_store
    root = tmp_path_factory.mktemp("inplace")
    spr.produce(root / "negs", [d], version=2, chunk_rows=7, legal_negatives=3)
    spr.produce(root / "plain", [d], version=2, chunk_rows=7)
    return root / "negs", root / "plain"


def _batches(stream, seed, size, *, in_place):
    if not in_place:
        stream = _concatenating(stream)
    return list(stream.batches(size, np.random.default_rng(seed)))


def _concatenating(stream):
    """The same stream with the per-chunk layout removed: ``batches`` takes the concatenating path."""
    old = PolicyRowsStream.__new__(PolicyRowsStream)
    old.__dict__.update(stream.__dict__)
    old._meta = None
    return old


def _same(a, b):
    assert len(a) == len(b) and len(a) > 0
    for x, y in zip(a, b):
        assert sorted(x) == sorted(y)
        for k in x:
            assert x[k].dtype == y[k].dtype and x[k].shape == y[k].shape, k
            assert x[k].tobytes() == y[k].tobytes(), k


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("window,size,seed,limit,drop", [(100, 10 ** 6, 0, None, 0), (2, 5, 3, None, 1),
                                                        (1, 3, 7, 11, 0), (3, 4, 1, None, 1)])
def test_in_place_window_batches_equal_the_concatenating_path(rows_dirs, which, window, size, seed, limit, drop):
    d = rows_dirs[which]
    probe = PolicyRowsStream(d, window=window, version=2)
    exclude = frozenset(sorted(probe.deal_keys)[:drop])
    stream = PolicyRowsStream(d, window=window, version=2, exclude=exclude, limit=limit)
    assert stream._x_table is not None and len(stream._x_table) <= 256       # the X codebook applies here
    _same(_batches(stream, seed, size, in_place=True), _batches(stream, seed, size, in_place=False))


def test_raw_x_path_when_the_codebook_does_not_apply(rows_dirs):
    stream = PolicyRowsStream(rows_dirs[0], window=2, version=2)
    stream._x_table = None                      # as for a corpus with more than 256 distinct X values
    _same(_batches(stream, 5, 6, in_place=True), _batches(stream, 5, 6, in_place=False))


def test_window_holds_codes_and_real_negative_slots_only(rows_dirs):
    stream = PolicyRowsStream(rows_dirs[0], window=100, version=2)
    w = stream._fill_window(list(range(len(stream.chunks))))
    assert w["X"].dtype == np.uint8 and w["X"].shape == (stream.n, stream.input_dim)
    assert len(w["neg_rows"]) == int(w["neg_count"].sum()) > 0
    assert not (w["neg_rows"] == -1).all(1).any()                            # no padded negative slot is stored
