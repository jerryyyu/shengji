import random

import pytest

from shengji.eval.s11_selection import select_deals, select_mirror, select_ply


PIN = "a" * 64


def test_frozen_v1_selection_vector():
    assert select_deals(PIN, list(range(80))) == [
        49, 41, 52, 50, 48, 69, 33, 73, 61, 59, 34, 63, 10, 35, 75, 70,
        46, 30, 36, 27, 13, 58, 45, 42, 0, 5, 16, 31, 51, 77, 2, 17,
        3, 65, 24, 7, 14, 4, 53, 62, 23, 37, 64, 40, 79, 19, 26, 47,
        25, 12, 18, 22, 71, 8, 39, 66, 28, 20, 56, 1, 67, 54, 38, 57,
    ]
    assert [(select_mirror(PIN, s), select_ply(PIN, s, select_mirror(PIN, s), 100))
            for s in (0, 1, 79)] == [(0, 98), (1, 13), (1, 15)]


@pytest.mark.parametrize("mirror", [False, True, None, 0.0, "0", -1, 2])
def test_invalid_mirror_refuses(mirror):
    with pytest.raises(ValueError, match="mirror"):
        select_ply(PIN, 0, mirror, 20)


def test_selection_is_order_invariant_and_does_not_mutate_or_use_rng():
    seeds = list(range(16000))
    before = seeds.copy(), random.getstate()
    selected = select_deals(PIN, seeds)
    assert selected == select_deals(PIN, seeds[::-1])
    assert len(selected) == len(set(selected)) == 64
    assert (seeds, random.getstate()) == before
    for seed in selected:
        mirror = select_mirror(PIN, seed)
        assert mirror in (0, 1)
        assert 0 <= select_ply(PIN, seed, mirror, 100) < 100
        assert select_ply(PIN, seed, mirror, 1) == 0


@pytest.mark.parametrize("seeds", [[], list(range(63)), list(range(64)) + [0],
                                   list(range(63)) + [True], list(range(63)) + [-1],
                                   list(range(63)) + [1.5], set(range(64))])
def test_bad_or_short_inventory_refuses_without_replacement(seeds):
    with pytest.raises(ValueError):
        select_deals(PIN, seeds)


@pytest.mark.parametrize("pin", [None, True, "A" * 64, "g" * 64, "a" * 63])
def test_invalid_manifest_pin_refuses(pin):
    with pytest.raises(ValueError):
        select_deals(pin, list(range(64)))


@pytest.mark.parametrize("count", [0, -1, 101, True, 1.5, None])
def test_bad_play_count_refuses(count):
    with pytest.raises(ValueError):
        select_ply(PIN, 0, select_mirror(PIN, 0), count)


def test_selected_mirror_cannot_be_replaced_by_available_other_mirror():
    with pytest.raises(ValueError, match="mirror"):
        select_ply(PIN, 0, 1 - select_mirror(PIN, 0), 20)


def test_manifest_changes_selection():
    assert select_deals(PIN, list(range(1000))) != select_deals("b" * 64, list(range(1000)))
