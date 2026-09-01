import inspect

import numpy as np
import pytest
import torch

from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateError,
    WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_model import (
    OUTCOME_CLASSES,
    WorldAfterstateV2Batch,
    WorldAfterstateV2ModelError,
    absolute_cross_entropy_rows,
    combined_value_loss,
    collate_world_afterstate_tensors,
    count_trainable_parameters,
    expected_signed_utility,
    new_world_afterstate_v2_model,
    paired_expectation_loss,
)


def _tensor(history_length=0):
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    public[0] = 1.0
    history = np.zeros((history_length, HISTORY_EVENT_DIM), dtype=np.float32)
    if history_length:
        history[0, 0] = 0.5
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    world[0, 0] = 1.0
    world[2, 1] = 0.5
    perspective = np.zeros(PERSPECTIVE_DIM, dtype=np.float32)
    perspective[0] = 1.0
    return WorldAfterstateTensorsV0(public, history, world, perspective)


def test_architecture_output_and_parameter_cap():
    model = new_world_afterstate_v2_model(17)
    assert count_trainable_parameters(model) == sum(
        p.numel() for p in model.parameters() if p.requires_grad)
    assert count_trainable_parameters(model) < 50_000
    output = model(collate_world_afterstate_tensors([_tensor(), _tensor(2)]))
    assert output.shape == (2, OUTCOME_CLASSES)
    assert torch.isfinite(output).all()


def test_validated_forward_is_bit_exact_with_the_public_boundary():
    model = new_world_afterstate_v2_model(17)
    batch = collate_world_afterstate_tensors([_tensor(), _tensor(2)])
    with torch.no_grad():
        public = model(batch)
        validated = model._forward_validated(batch)
    assert torch.equal(public, validated)


def test_uniform_absolute_rows_are_one():
    rows = absolute_cross_entropy_rows(
        torch.zeros((3, OUTCOME_CLASSES)), torch.tensor([0, 1, 203]))
    assert torch.allclose(rows, torch.ones(3), atol=1e-6)


def test_expected_utility_and_identical_pair_are_zero():
    logits = torch.randn((4, OUTCOME_CLASSES), generator=torch.Generator().manual_seed(3))
    assert torch.equal(expected_signed_utility(logits),
                       expected_signed_utility(logits))
    target = torch.zeros(4)
    assert float(paired_expectation_loss(logits, logits, target, 0.0)) == 0.0


def test_collator_supports_empty_and_nonempty_history():
    batch = collate_world_afterstate_tensors([_tensor(), _tensor(3)])
    assert isinstance(batch, WorldAfterstateV2Batch)
    assert batch.history.shape == (2, 3, HISTORY_EVENT_DIM)
    assert batch.history_lengths.tolist() == [0, 3]
    output = new_world_afterstate_v2_model(4)(batch)
    assert output.shape == (2, OUTCOME_CLASSES)


def test_initialization_does_not_drift_global_rng():
    before = torch.get_rng_state().clone()
    first = new_world_afterstate_v2_model(23)
    after = torch.get_rng_state().clone()
    second = new_world_afterstate_v2_model(23)
    assert torch.equal(before, after)
    assert all(torch.equal(a, b) for a, b in zip(
        first.state_dict().values(), second.state_dict().values(), strict=True))


def test_receiver_roles_survive_partnership_aggregation():
    tensor = _tensor()
    permuted = WorldAfterstateTensorsV0(
        tensor.public.copy(), tensor.history.copy(), tensor.world[[2, 1, 0, 3, 4]].copy(),
        tensor.perspective.copy())
    model = new_world_afterstate_v2_model(29)
    left = model(collate_world_afterstate_tensors([tensor]))
    right = model(collate_world_afterstate_tensors([permuted]))
    assert not torch.equal(left, right)


def test_malformed_and_nonfinite_inputs_refused():
    bad = _tensor()
    bad.public[0] = np.nan
    with pytest.raises(WorldAfterstateError):
        collate_world_afterstate_tensors([bad])
    with pytest.raises(WorldAfterstateV2ModelError):
        absolute_cross_entropy_rows(
            torch.full((1, OUTCOME_CLASSES), float("nan")), torch.tensor([0]))
    with pytest.raises(WorldAfterstateV2ModelError):
        collate_world_afterstate_tensors([])
    malformed = _tensor()
    malformed.public[0] = 0.25
    with pytest.raises(WorldAfterstateV2ModelError,
                       match="card-plane encoding"):
        collate_world_afterstate_tensors([malformed])
    with pytest.raises(WorldAfterstateV2ModelError,
                       match="pair variance"):
        paired_expectation_loss(
            torch.zeros((1, OUTCOME_CLASSES)),
            torch.zeros((1, OUTCOME_CLASSES)), torch.zeros(1),
            torch.tensor(-1.0))


def test_combined_loss_is_absolute_plus_pair_one_to_one():
    logits = torch.zeros((2, OUTCOME_CLASSES))
    candidate = torch.zeros_like(logits)
    incumbent = torch.zeros_like(logits)
    labels = torch.tensor([0, 1])
    targets = torch.zeros(2)
    expected = absolute_cross_entropy_rows(logits, labels).mean()
    assert torch.equal(combined_value_loss(
        logits, labels, candidate, incumbent, targets, 9.0), expected)


def test_forward_contract_has_no_action_metadata():
    signature = inspect.signature(new_world_afterstate_v2_model(1).forward)
    assert "action" not in signature.parameters
    batch = collate_world_afterstate_tensors([_tensor()])
    with pytest.raises(TypeError):
        new_world_afterstate_v2_model(1)(batch, action=3)
