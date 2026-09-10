from __future__ import annotations

import copy

import pytest
import torch

from shengji.train.simple_belief_model import (
    SimpleBeliefMLP,
    masked_count_loss,
    masked_count_probabilities,
)


def _allowed(batch=2):
    return torch.ones(batch, 4, 54, 3, dtype=torch.bool)


def test_dimensions_and_finite_forward():
    model = SimpleBeliefMLP(7, width=16, hidden=8)
    logits = model(torch.randn(3, 7))
    assert logits.shape == (3, 4, 54, 3)
    assert torch.isfinite(logits).all()


def test_masked_probabilities_forbidden_and_known_cells():
    logits = torch.zeros(2, 4, 54, 3)
    allowed = _allowed()
    allowed[0, 0, 0] = torch.tensor([False, True, False])
    probs = masked_count_probabilities(logits, allowed)
    assert torch.equal(probs[0, 0, 0], torch.tensor([0.0, 1.0, 0.0]))
    assert torch.equal(probs[~allowed], torch.zeros_like(probs[~allowed]))
    assert torch.allclose(probs.sum(-1), torch.ones(2, 4, 54))


def test_invalid_masks_and_targets_refused():
    logits = torch.zeros(1, 4, 54, 3)
    allowed = _allowed(1)
    allowed[0, 0, 0] = False
    with pytest.raises(ValueError):
        masked_count_probabilities(logits, allowed)
    with pytest.raises(ValueError):
        masked_count_loss(logits, torch.zeros(1, 4, 54, dtype=torch.int32),
                          _allowed(1))
    bad = torch.zeros(1, 4, 54, dtype=torch.int64)
    bad[0, 0, 0] = 3
    with pytest.raises(ValueError):
        masked_count_loss(logits, bad, _allowed(1))
    forbidden = _allowed(1)
    forbidden[0, 0, 0, 0] = False
    with pytest.raises(ValueError):
        masked_count_loss(logits, torch.zeros(1, 4, 54, dtype=torch.int64),
                          forbidden)


def test_loss_gradients_are_finite_and_known_cells_are_zero():
    logits = torch.randn(2, 4, 54, 3, requires_grad=True)
    allowed = _allowed()
    targets = torch.zeros(2, 4, 54, dtype=torch.int64)
    loss = masked_count_loss(logits, targets, allowed)
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(logits.grad).all()

    known_logits = torch.randn(1, 4, 54, 3, requires_grad=True)
    known_allowed = torch.zeros_like(known_logits, dtype=torch.bool)
    known_allowed[..., 2] = True
    known_targets = torch.full((1, 4, 54), 2, dtype=torch.int64)
    known_loss = masked_count_loss(known_logits, known_targets, known_allowed)
    assert known_loss.item() == 0.0
    known_loss.backward()
    assert torch.equal(known_logits.grad, torch.zeros_like(known_logits))


def test_tiny_synthetic_learning_lowers_loss():
    torch.manual_seed(4)
    model = SimpleBeliefMLP(5, width=16, hidden=8)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.5)
    features = torch.randn(4, 5)
    targets = torch.zeros(4, 4, 54, dtype=torch.int64)
    allowed = _allowed(4)
    first = masked_count_loss(model(features), targets, allowed).item()
    for _ in range(30):
        optimizer.zero_grad()
        loss = masked_count_loss(model(features), targets, allowed)
        loss.backward()
        optimizer.step()
    assert masked_count_loss(model(features), targets, allowed).item() < first


def test_state_dict_reload_reproduces_probabilities_exactly():
    torch.manual_seed(7)
    first = SimpleBeliefMLP(6, width=12, hidden=7)
    features = torch.randn(2, 6)
    allowed = _allowed()
    expected = masked_count_probabilities(first(features), allowed)
    state = copy.deepcopy(first.state_dict())
    second = SimpleBeliefMLP(6, width=12, hidden=7)
    second.load_state_dict(state)
    actual = masked_count_probabilities(second(features), allowed)
    assert torch.equal(expected, actual)
