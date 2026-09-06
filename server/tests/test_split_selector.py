"""``keys_mask``/``SplitSelector`` decide exactly what ``np.isin`` decided.

The batch iterators call the split mask once per block per epoch, and the
old implementation rebuilt and rehashed the part's key array on every one of
those calls; on an A+C+D-sized store that hashing was the largest single line
in the epoch. The replacement binary-searches the sorted keys instead, so
these tests pin the equivalence rather than the speed.
"""

import numpy as np
import pytest

from shengji.train.data import SplitSelector, keys_mask, part_keys, split_mask


def _keys(n: int, start: int = 0) -> list[str]:
    return ["deck:" + format(i, "064x") for i in range(start, start + n)]


@pytest.mark.parametrize("n_keys, n_rows", [(0, 5), (1, 1), (1, 7), (37, 0), (37, 200)])
def test_keys_mask_matches_isin(n_keys: int, n_rows: int) -> None:
    rng = np.random.default_rng(11)
    universe = _keys(64)
    keys = np.asarray(sorted(universe[:n_keys]), dtype=str)
    rows = (np.asarray([universe[i] for i in rng.integers(0, len(universe), n_rows)], dtype=str)
            if n_rows else np.asarray([], dtype=str))
    assert np.array_equal(keys_mask(rows, keys), np.isin(rows, keys))


def test_keys_mask_handles_rows_outside_the_key_range() -> None:
    keys = np.asarray(sorted(_keys(8, start=10)), dtype=str)
    rows = np.asarray(_keys(1, start=0) + _keys(1, start=10) + _keys(1, start=99), dtype=str)
    assert list(keys_mask(rows, keys)) == [False, True, False]


class _Block:
    def __init__(self, deal_key):
        self.deal_key = np.asarray(deal_key, dtype=str)
        self.n = self.deal_key.size


def test_split_selector_matches_split_mask_on_every_part() -> None:
    universe = _keys(50)
    assignment = {k: ("train" if i < 30 else "val" if i < 40 else "test")
                  for i, k in enumerate(universe)}
    block = _Block(universe[5:45])
    for part in ("train", "val", "test"):
        selector = SplitSelector(assignment, part)
        expected = split_mask(block, assignment, part)
        assert np.array_equal(selector(block), expected)
        assert np.array_equal(expected, np.isin(block.deal_key, part_keys(assignment, part)))
        assert selector.part == part


def test_split_selector_is_stable_across_calls() -> None:
    universe = _keys(20)
    assignment = {k: ("train" if i % 2 else "val") for i, k in enumerate(universe)}
    selector = SplitSelector(assignment, "train")
    first = selector(_Block(universe))
    assert np.array_equal(first, selector(_Block(universe)))
