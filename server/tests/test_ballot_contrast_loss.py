"""Structural coverage boundaries against the actual loss, tiny CPU tensors only."""
import pytest
import torch

from shengji.train.policy_prior import CARD_INDEX, ballot_tensors, listwise_loss_soft
from shengji.train.ballot_contrast import summarize_ballot_contrasts


def loss_and_gradient(actions, values, taken=None):
    index = lambda action: [CARD_INDEX[c] for c in action]
    meta = [{"ballot": [index(a) for a in actions],
             "taken": index(actions[0] if taken is None else taken)}]
    ball, mask, target = ballot_tensors(meta)
    logits = torch.zeros((1, 54), requires_grad=True)
    loss = listwise_loss_soft(logits, ball, mask, target, torch.tensor([values]))
    loss.backward()
    return loss, logits.grad


@pytest.mark.parametrize("values", [[0.0, 1.0], [float("nan"), float("nan")]])
def test_constant_pair_cancels_in_soft_and_hard_fallback(values):
    actions = [["S6", "S6", "C4"], ["S6", "S6", "C9"]]
    assert summarize_ballot_contrasts(actions)["common_positive_constant_cards"] == ["S6"]
    _, gradient = loss_and_gradient(actions, values)
    assert gradient[0, CARD_INDEX["S6"]].item() == pytest.approx(0.0, abs=1e-7)
    assert gradient.abs().max().item() > 0.1


def test_structural_variation_is_not_sufficient_for_nonzero_gradient():
    # Equal target and predicted probabilities: structural opportunity, no update.
    actions = [["S6"], ["C9"]]
    assert summarize_ballot_contrasts(actions)["varying_card_count"] == 2
    _, gradient = loss_and_gradient(actions, [0.0, 0.0])
    assert gradient.abs().max().item() == pytest.approx(0.0, abs=1e-7)


def test_missing_value_slot_still_participates_in_prediction_normalizer():
    # Filtering nonfinite targets BEFORE counting candidate contrasts would
    # incorrectly report S6 as common. The actual prediction includes slot 3.
    actions = [["S6", "C4"], ["S6", "C9"], ["H3", "H4"]]
    assert summarize_ballot_contrasts(actions)["per_card"]["S6"]["preserve_spend"]
    assert summarize_ballot_contrasts(actions[:2])["common_positive_constant_cards"] == ["S6"]
    _, gradient = loss_and_gradient(actions, [0.0, 0.0, float("nan")])
    assert gradient[0, CARD_INDEX["S6"]].item() == pytest.approx(-1.0 / 3.0)


def test_taken_action_absent_skips_even_structurally_varying_row():
    actions = [["S6"], ["C9"]]
    assert summarize_ballot_contrasts(actions)["varying_card_count"] == 2
    loss, gradient = loss_and_gradient(actions, [0.0, 1.0], taken=["HA"])
    assert loss.item() == 0.0
    assert gradient.abs().max().item() == 0.0
