import hashlib

import numpy as np
import pytest
import torch

from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateExampleV0,
    WorldAfterstateTensorsV0)
from shengji.rl.world_afterstate_model import CAPACITY_SHAPES
from shengji.rl.world_afterstate_v1_model import (
    AdvantageExampleV1, WorldAfterstateV1ModelError, advantage_loss,
    collate_advantage_examples, collate_successor_tensors,
    new_world_afterstate_advantage_model)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _example(name: str, *, category: int, offset: float) \
        -> WorldAfterstateExampleV0:
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    public[0] = offset
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
    history[0, 0] = offset
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    world[0, 0] = 1.0 if offset > 0 else 0.0
    perspective = np.zeros(PERSPECTIVE_DIM, dtype=np.float32)
    perspective[0] = 1.0
    return WorldAfterstateExampleV0(
        tensors=WorldAfterstateTensorsV0(
            public=public, history=history, world=world,
            perspective=perspective),
        signed_level_category=category,
        successor_sha256=_digest(name))


def _pairs(count: int = 8):
    result = []
    for index in range(count):
        incumbent = _example(
            f"incumbent-{index}", category=100, offset=0.0)
        candidate = _example(
            f"candidate-{index}", category=102, offset=1.0)
        result.append(AdvantageExampleV1(
            incumbent=incumbent, candidate=candidate,
            advantage_levels=2))
    return result


def test_collation_derives_exact_action_relative_targets():
    batch = collate_advantage_examples(_pairs(3))
    batch.validate()
    assert batch.targets.tolist() == [2.0, 2.0, 2.0]
    assert batch.incumbent.size == 3
    assert batch.candidate.size == 3


def test_target_free_successor_collation_matches_training_inputs():
    pairs = _pairs(3)
    training = collate_advantage_examples(pairs)
    target_free = collate_successor_tensors(
        [pair.candidate.tensors for pair in pairs])
    assert torch.equal(target_free.public, training.candidate.public)
    assert torch.equal(target_free.history, training.candidate.history)
    assert torch.equal(target_free.world, training.candidate.world)
    assert torch.equal(target_free.perspective,
                       training.candidate.perspective)
    assert not hasattr(target_free, "targets")


def test_shared_scorer_is_exactly_zero_for_identical_successors():
    batch = collate_advantage_examples(_pairs(4))
    model = new_world_afterstate_advantage_model(17, CAPACITY_SHAPES["small"])
    values = model(batch.incumbent, batch.incumbent)
    assert torch.equal(values, torch.zeros_like(values))


def test_swapping_siblings_exactly_negates_prediction():
    batch = collate_advantage_examples(_pairs(4))
    model = new_world_afterstate_advantage_model(19, CAPACITY_SHAPES["small"])
    forward = model(batch.incumbent, batch.candidate)
    reverse = model(batch.candidate, batch.incumbent)
    assert torch.equal(forward, -reverse)
    assert bool(torch.all(forward >= -203.0))
    assert bool(torch.all(forward <= 203.0))


def test_initialization_is_repeatable_without_advancing_global_rng():
    before = torch.get_rng_state().clone()
    first = new_world_afterstate_advantage_model(
        23, CAPACITY_SHAPES["small"])
    after = torch.get_rng_state().clone()
    second = new_world_afterstate_advantage_model(
        23, CAPACITY_SHAPES["small"])
    assert torch.equal(before, after)
    assert all(torch.equal(left, right) for left, right in zip(
        first.state_dict().values(), second.state_dict().values(), strict=True))


def test_fresh_model_can_reduce_one_paired_advantage_loss():
    torch.set_num_threads(1)
    batch = collate_advantage_examples(_pairs(8))
    model = new_world_afterstate_advantage_model(29, CAPACITY_SHAPES["small"])
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    with torch.no_grad():
        initial = float(advantage_loss(
            model(batch.incumbent, batch.candidate), batch.targets))
    for _ in range(30):
        optimizer.zero_grad(set_to_none=True)
        loss = advantage_loss(
            model(batch.incumbent, batch.candidate), batch.targets)
        loss.backward()
        optimizer.step()
    with torch.no_grad():
        final = float(advantage_loss(
            model(batch.incumbent, batch.candidate), batch.targets))
    assert final < initial * 0.25


def test_example_refuses_label_not_derived_from_siblings():
    pair = _pairs(1)[0]
    bad = AdvantageExampleV1(
        incumbent=pair.incumbent, candidate=pair.candidate,
        advantage_levels=3)
    with pytest.raises(
            WorldAfterstateV1ModelError,
            match="advantage example label drift"):
        bad.validate()


def test_loss_refuses_nonfinite_and_out_of_support_tensors():
    with pytest.raises(
            WorldAfterstateV1ModelError,
            match="advantage loss tensor drift"):
        advantage_loss(
            torch.tensor([float("nan")], dtype=torch.float32),
            torch.tensor([0.0], dtype=torch.float32))
    with pytest.raises(
            WorldAfterstateV1ModelError,
            match="advantage loss tensor drift"):
        advantage_loss(
            torch.tensor([0.0], dtype=torch.float32),
            torch.tensor([204.0], dtype=torch.float32))
