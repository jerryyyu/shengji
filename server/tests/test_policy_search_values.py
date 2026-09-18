"""The search's per-candidate means, carried into the policy rows (#496 H3).

AlphaGo Zero trains its policy on the MCTS visit distribution; we train on the single
played action and throw the search's relative preference away. The values needed to fix
that are already in every sealed trajectory (`action_values.means`), so this is a
re-extract, not a re-harvest.

THE RISK THIS FILE EXISTS FOR IS ALIGNMENT. `eligible_indices` index the RAW ballot, while
`ballot_tensors` DROPS falsy ballot entries -- so every slot after an empty one shifts. A
misalignment here would not crash: it would train the policy on another candidate's value.
"""
import numpy as np
import pytest

from shengji.train.policy_prior import ballot_tensors, ballot_value_tensor


def _meta(ballot, means, taken):
    return {"ballot": ballot, "means": means, "taken": taken}


def test_slots_line_up_after_empty_ballot_entries_are_dropped():
    """The whole point: an empty entry at position 1 shifts every later slot by one, and
    the means must shift WITH it."""
    ballot = [[1, 2], [], [3], [4, 5]]          # position 1 is dropped by `if a`
    means = [10.0, 99.0, 20.0, 30.0]            # 99.0 belongs to the dropped entry
    meta = [_meta(ballot, means, [3])]
    ball, mask, tgt = ballot_tensors(meta)
    vals, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert mask[0].tolist()[:3] == [True, True, True] and int(mask[0].sum()) == 3
    # slot 0 = [1,2] -> 10.0, slot 1 = [3] -> 20.0, slot 2 = [4,5] -> 30.0; 99.0 is GONE
    assert vals[0, :3].tolist() == [10.0, 20.0, 30.0]
    assert 99.0 not in vals[0].tolist()
    # and the played action [3] is slot 1, whose value is 20.0 -- not 99.0
    assert int(tgt[0]) == 1 and vals[0, int(tgt[0])] == 20.0


def test_a_row_the_search_never_scored_is_marked_unusable_not_zero():
    meta = [_meta([[1], [2]], [float("nan"), float("nan")], [1])]
    ball, _m, _t = ballot_tensors(meta)
    vals, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert not bool(has[0]), "a row with no finite mean must not look like a flat target"
    assert np.isnan(vals[0]).all()


def test_one_finite_mean_is_not_a_distribution():
    meta = [_meta([[1], [2]], [5.0, float("nan")], [1])]
    ball, _m, _t = ballot_tensors(meta)
    _v, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert not bool(has[0]), "one value cannot form a preference over candidates"


def test_two_finite_means_are_usable():
    meta = [_meta([[1], [2]], [5.0, 7.0], [1])]
    ball, _m, _t = ballot_tensors(meta)
    _v, has = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert bool(has[0])


def test_a_short_or_long_means_list_pads_rather_than_zip_truncating():
    """zip() would silently drop the tail; that would misalign every later row's slots."""
    meta = [_meta([[1], [2], [3]], [1.0], [2])]          # far too short
    ball, _m, _t = ballot_tensors(meta)
    vals, _h = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    assert vals[0, 0] == 1.0 and np.isnan(vals[0, 1]) and np.isnan(vals[0, 2])


def test_widths_match_ballot_tensors_so_a_slot_index_is_valid_in_both():
    metas = [_meta([[1, 2], [], [3]], [1.0, 9.0, 2.0], [3]),
             _meta([[4]], [5.0], [4])]
    ball, mask, _t = ballot_tensors(metas)
    vals, _h = ballot_value_tensor(metas, b_max=int(ball.shape[1]))
    assert vals.shape == (len(metas), int(ball.shape[1]))
    assert vals.shape[:2] == mask.shape
