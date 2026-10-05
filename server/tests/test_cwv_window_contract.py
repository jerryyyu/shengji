"""Independent grouping contract before consolidating the three store paths."""
import random
from types import SimpleNamespace

import pytest

from shengji.train.cwv_data import CwvBlockStore
from shengji.train.cwv_pack import CwvPackStore
from shengji.train.data import BlockStore, TrainDataError


def _oracle(order, sizes, budget, window):
    # Choose the longest admissible prefix, independently of the stores'
    # running-byte accumulator and flush-before-append implementation.
    if budget is not None and any(sizes[i] > budget for i in order):
        raise ValueError("oversized")
    rest = list(order)
    result = []
    while rest:
        ends = range(1, min(len(rest), max(1, int(window))) + 1)
        end = max(n for n in ends
                  if budget is None or sum(sizes[i] for i in rest[:n]) <= budget)
        result.append(rest[:end])
        rest = rest[end:]
    return result


@pytest.mark.parametrize("store", [BlockStore, CwvBlockStore, CwvPackStore])
def test_windows_match_independent_prefix_oracle(store):
    rng = random.Random(707688)
    cases = [
        ([], [], 0, 0),
        ([0, 1, 2], [2, 3, 0], 5, 9),  # exact byte boundary
        ([2, 0, 1], [2, 3, 0], None, 2),
        ([0, 0, 1], [0, 0], 0, -1),  # repeated indices stay repeated
        ([0], [6], 5, 1),
        ([0, 1], [1, 6], 5, 2),  # oversized after a valid prefix
    ]
    for _ in range(200):
        sizes = [rng.randrange(12) for _ in range(rng.randrange(9))]
        order = list(range(len(sizes)))
        rng.shuffle(order)
        cases.append((order, sizes, rng.choice([None, 0, 1, 5, 12, 24]),
                      rng.choice([-2, 0, 1, 2, 4, 20])))
    for order, sizes, budget, window in cases:
        obj = SimpleNamespace(
            sizes=list(sizes), residency=SimpleNamespace(budget=budget),
            entries=[(SimpleNamespace(label=f"shard-{i}"),) for i in range(len(sizes))])
        before = (list(order), list(obj.sizes), rng.getstate())
        try:
            expected = _oracle(order, sizes, budget, window)
        except ValueError:
            first = next(i for i in order if sizes[i] > budget)
            suffix = " or shard the store" if store is BlockStore else ""
            with pytest.raises(TrainDataError) as exc:
                store.windows(obj, order, window)
            assert str(exc.value) == (
                f"shard-{first}: decodes to {sizes[first]} bytes, above the "
                f"residency budget of {budget}; raise --resident-bytes{suffix}")
        else:
            assert store.windows(obj, order, window) == expected
        assert (order, obj.sizes, rng.getstate()) == before
