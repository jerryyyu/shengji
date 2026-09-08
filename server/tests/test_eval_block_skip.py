"""Evaluating one split must not decode the shards of the other splits.

A shard holds exactly one deal and `split_deals` assigns by deal, so an
evaluation over `val` can reach every row it needs while declining ~90% of
the store. These tests pin the equivalence (same rows) and the saving
(shards actually declined), and the last one shows the equivalence check
fails when the filter is wrong.
"""
import numpy as np
import pytest

from shengji.train.data import SplitSelector, keys_mask


class _Block:
    def __init__(self, key, n):
        self.deal_key = np.asarray([key] * n, dtype=str)
        self.n = n


class _Store:
    """Minimal stand-in with the two things the skip relies on."""

    def __init__(self, keys, rows=3):
        self.entries = list(range(len(keys)))
        self._keys = keys
        self.rows = rows
        self.decoded = []

    def keys_of(self, i):
        return [self._keys[i]]

    def block(self, i):
        self.decoded.append(i)
        return _Block(self._keys[i], self.rows)

    def iter_blocks(self, *, skip=None):
        for i in range(len(self.entries)):
            if skip is not None and skip(self.keys_of(i)):
                continue
            yield self.block(i)


def _fixture(n=50):
    keys = ["deck:" + format(i, "064x") for i in range(n)]
    assignment = {k: ("train" if i % 10 else "val") for i, k in enumerate(keys)}
    return keys, assignment


def _collect(store, selector, skip):
    rows = []
    for block in store.iter_blocks(skip=skip):
        for r in np.flatnonzero(selector(block)):
            rows.append((block.deal_key[r], int(r)))
    return rows


def test_skipping_reaches_the_same_rows_and_declines_most_shards():
    keys, assignment = _fixture()
    selector = SplitSelector(assignment, "val")

    plain = _Store(keys)
    expected = _collect(plain, selector, None)

    filtered = _Store(keys)
    got = _collect(filtered, selector,
                   lambda deal_keys: not selector.selects_any(deal_keys))

    assert got == expected and expected, "the filter must not lose or add a row"
    assert len(filtered.decoded) < len(plain.decoded), "it must decline shards"
    assert len(filtered.decoded) == 5, "one shard in ten holds a val deal"
    assert len(plain.decoded) == 50


def test_selects_any_agrees_with_the_row_mask():
    keys, assignment = _fixture()
    for part in ("train", "val"):
        selector = SplitSelector(assignment, part)
        for key in keys:
            block = _Block(key, 3)
            assert selector.selects_any([key]) == bool(selector(block).any())


def test_an_empty_part_selects_nothing():
    keys, _ = _fixture()
    selector = SplitSelector({k: "train" for k in keys}, "val")
    assert selector.selects_any(keys) is False
    assert not selector(_Block(keys[0], 3)).any()


def test_the_equivalence_check_fails_when_the_filter_is_wrong():
    """Prove the check can fail: a filter that drops one real val shard."""
    keys, assignment = _fixture()
    selector = SplitSelector(assignment, "val")
    expected = _collect(_Store(keys), selector, None)
    dropped = keys[10]                      # a genuine val deal

    def broken(deal_keys):
        return not selector.selects_any(deal_keys) or dropped in deal_keys

    got = _collect(_Store(keys), selector, broken)
    assert got != expected, "a wrong filter must be caught by this comparison"
    assert len(got) == len(expected) - 3
