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


# ---------------------------------------------------------------- the soft target itself

import torch

from shengji.train.policy_prior import listwise_loss, listwise_loss_soft, soft_ballot_targets


def test_the_target_is_a_distribution_over_masked_finite_slots_only():
    vals = torch.tensor([[10.0, 12.0, float("nan"), 5.0]])
    mask = torch.tensor([[True, True, True, False]])     # slot 3 masked OUT, slot 2 has no value
    probs, usable = soft_ballot_targets(vals, mask, temperature=1.0)
    assert bool(usable[0])
    assert probs[0, 2] == 0.0 and probs[0, 3] == 0.0, "no mass on unscored or unmasked slots"
    assert abs(float(probs[0].sum()) - 1.0) < 1e-6
    assert probs[0, 1] > probs[0, 0], "the higher-valued candidate must carry more mass"


def test_a_row_the_search_did_not_score_is_not_usable_and_gets_no_mass():
    vals = torch.tensor([[float("nan"), float("nan")]])
    mask = torch.tensor([[True, True]])
    probs, usable = soft_ballot_targets(vals, mask, temperature=1.0)
    assert not bool(usable[0]) and float(probs[0].sum()) == 0.0


def test_temperature_moves_the_target_between_one_hot_and_uniform():
    vals = torch.tensor([[0.0, 30.0, 60.0]])
    mask = torch.ones(1, 3, dtype=torch.bool)
    sharp, _ = soft_ballot_targets(vals, mask, temperature=1.0)
    flat, _ = soft_ballot_targets(vals, mask, temperature=100_000.0)
    assert float(sharp[0].max()) > 0.99, "T=1 on a 60-point gap is nearly one-hot"
    # T=1000 still leaves 60/1000 = 0.06 of logit spread, so it approaches uniform without
    # reaching it (max 0.3434). The limit is the claim, so test it at a T where it holds.
    assert abs(float(flat[0].max()) - 1 / 3) < 0.01, "a large T washes out to uniform"


def test_soft_falls_back_to_the_hard_target_where_the_search_scored_nothing():
    """Rows the search never scored keep the played-action target, so the ROW COUNT does not
    change between the hard and soft arms -- otherwise the two would differ in sample size
    as well as in target, and the comparison would be confounded."""
    logits = torch.zeros(1, 54, requires_grad=True)
    ball = torch.tensor([[[0, -1], [1, -1]]], dtype=torch.int64)
    mask = torch.ones(1, 2, dtype=torch.bool)
    tgt = torch.tensor([1])
    vals = torch.full((1, 2), float("nan"))
    soft = listwise_loss_soft(logits, ball, mask, tgt, vals, temperature=1.0)
    hard = listwise_loss(logits, ball, mask, tgt)
    assert torch.allclose(soft, hard, atol=1e-6), "no search values => identical to the hard loss"


def test_soft_differs_from_hard_where_the_search_DID_score():
    # NON-uniform logits are essential: with all-zero logits log_softmax is uniform and ANY
    # normalised target gives the identical loss, so the test could not tell them apart.
    logits = torch.zeros(1, 54)
    logits[0, 0] = 2.0
    logits = logits.clone().requires_grad_(True)
    ball = torch.tensor([[[0, -1], [1, -1]]], dtype=torch.int64)
    mask = torch.ones(1, 2, dtype=torch.bool)
    tgt = torch.tensor([1])
    vals = torch.tensor([[8.0, 10.0]])                 # the search liked BOTH, slot 1 more
    soft = listwise_loss_soft(logits, ball, mask, tgt, vals, temperature=1.0)
    hard = listwise_loss(logits, ball, mask, tgt)
    assert not torch.allclose(soft, hard, atol=1e-6), "a real preference must change the loss"


def test_the_soft_loss_backpropagates():
    logits = torch.zeros(2, 54, requires_grad=True)
    ball = torch.tensor([[[0, -1], [1, -1]], [[2, -1], [3, -1]]], dtype=torch.int64)
    mask = torch.ones(2, 2, dtype=torch.bool)
    tgt = torch.tensor([0, 1])
    vals = torch.tensor([[9.0, 4.0], [1.0, 7.0]])
    listwise_loss_soft(logits, ball, mask, tgt, vals, 1.0).backward()
    assert logits.grad is not None and torch.isfinite(logits.grad).all()
