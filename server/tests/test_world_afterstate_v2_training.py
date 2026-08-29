import dataclasses
import hashlib

import numpy as np
import pytest
import torch

from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_model import new_world_afterstate_v2_model
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingError, WorldAfterstateV2TrainingExample,
    WorldAfterstateV2TrainingConfig, collate_training_examples, model_state_sha256,
    new_optimizer, root_balanced_loss, train_epoch,
)


def _hex(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _tensor(seed):
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    public[seed % PUBLIC_DIM] = 1.0
    history = np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32)
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    world[0, seed % N_CARDS] = 1.0
    perspective = np.zeros(PERSPECTIVE_DIM, dtype=np.float32)
    perspective[seed % 2] = 1.0
    return WorldAfterstateTensorsV0(public, history, world, perspective)


def _rows(root, candidates=2, *, cohort="primary", source="natural"):
    deal, slot, state = (_hex(f"{root}:deal"), _hex(f"{root}:slot"),
                         _hex(f"{root}:state"))
    successors = [_hex(f"{root}:successor:{candidate}")
                  for candidate in range(candidates)]
    from shengji.rl.belief_contract import canonical_json_bytes
    cset = hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state, "successor_sha256s": successors,
    })).hexdigest()
    result = []
    for candidate in range(candidates):
        successor = successors[candidate]
        for replica in range(8):
            result.append(WorldAfterstateV2TrainingExample(
                deal, slot, state, cset, candidate, candidate == 0,
                successor, _hex(f"{root}:continuation:{replica}"), replica,
                source, "fit", "attacker", "early", "lead", "2", "S",
                "0-39", _tensor(
                    candidate), (candidate + replica) % 204, cohort))
    return result


def test_complete_root_and_target_free_model_batch():
    batch = collate_training_examples(_rows("one"))
    batch.validate()
    assert batch.root_count == 1 and batch.size == 16
    assert not hasattr(batch.tensors, "target_categories")
    assert not hasattr(batch.tensors, "signed_level_category")


def test_rejects_missing_replica_duplicate_successor_and_split():
    rows = _rows("bad")
    with pytest.raises(WorldAfterstateV2TrainingError, match="incomplete"):
        collate_training_examples(rows[:-1])
    duplicate = rows.copy()
    duplicate[-1] = dataclasses.replace(duplicate[-1],
                                         successor_sha256=duplicate[-9].successor_sha256)
    with pytest.raises(WorldAfterstateV2TrainingError, match="successor"):
        collate_training_examples(duplicate)
    with pytest.raises(WorldAfterstateV2TrainingError, match="split"):
        collate_training_examples([dataclasses.replace(rows[0], split="audit")])


def test_primary_accepts_fit_only_source_diversity_and_control_is_explicit():
    diverse = [dataclasses.replace(item, source="pt-sol")
               for item in _rows("source")]
    assert collate_training_examples(diverse).cohort == "primary"
    control = [dataclasses.replace(item, source="pt-sol", cohort="control")
               for item in _rows("control")]
    assert collate_training_examples(control, cohort="control").cohort == "control"


def test_candidate_set_and_replica_tensor_identity_are_rederived():
    rows = _rows("binding")
    forged_set = [dataclasses.replace(
        row, candidate_set_sha256=_hex("foreign-set")) for row in rows]
    with pytest.raises(WorldAfterstateV2TrainingError,
                       match="candidate-set"):
        collate_training_examples(forged_set)
    forged_tensor = rows.copy()
    forged_tensor[-1] = dataclasses.replace(forged_tensor[-1],
                                             tensors=_tensor(99))
    with pytest.raises(WorldAfterstateV2TrainingError,
                       match="continuation changed"):
        collate_training_examples(forged_tensor)


def test_root_balanced_loss_does_not_overweight_large_root():
    small = collate_training_examples(_rows("small", 2))
    large = collate_training_examples(_rows("large", 5))
    logits_small = torch.zeros((small.size, 204))
    logits_large = torch.zeros((large.size, 204))
    # Both use uniform predictions, so only the category distribution differs.
    loss_small = root_balanced_loss(logits_small, small, 1.0)
    loss_large = root_balanced_loss(logits_large, large, 1.0)
    together = collate_training_examples(_rows("small", 2) + _rows("large", 5))
    # Root-balanced combined loss is the arithmetic mean of root losses.
    combined = root_balanced_loss(torch.zeros((together.size, 204)), together, 1.0)
    assert torch.allclose(combined, (loss_small + loss_large) / 2, atol=1e-6)


def test_paired_target_uses_frozen_eight_replica_mean_not_noisy_rows():
    rows = []
    for row in _rows("replica-mean"):
        category = 100 if row.candidate_index == 0 else (
            101 if row.replica < 4 else 99)
        rows.append(dataclasses.replace(row, signed_level_category=category))
    batch = collate_training_examples(rows)
    loss = root_balanced_loss(torch.zeros((batch.size, 204)), batch, 1.0)
    # A uniform 204-way distribution has normalized absolute loss 1.  The
    # paired target averages to exactly zero, so its contribution is zero.
    assert torch.allclose(loss, torch.tensor(1.0), atol=1e-6)


def test_paired_crn_binding_and_actual_update_are_deterministic():
    batch = collate_training_examples(_rows("train"))
    config = WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=100_000_000, weight_decay_ppb=0,
        gradient_norm_milli=1_000, max_epochs=1, sigma_pair_squared=2.0)
    first = new_world_afterstate_v2_model(22)
    second = new_world_afterstate_v2_model(22)
    receipt1 = train_epoch(first, new_optimizer(first, config), (batch,),
                            epoch=1, config=config)
    receipt2 = train_epoch(second, new_optimizer(second, config), (batch,),
                            epoch=1, config=config)
    assert receipt1.payload() == receipt2.payload()
    assert receipt1.model_state_sha256_before != receipt1.model_state_sha256_after
    assert model_state_sha256(first) == model_state_sha256(second)


def test_root_cannot_be_split_across_optimizer_batches():
    rows = _rows("split")
    left = collate_training_examples(rows)
    right = collate_training_examples(rows)
    config = WorldAfterstateV2TrainingConfig(100_000_000, 0, 1_000, 1, 1.0)
    model = new_world_afterstate_v2_model(1)
    with pytest.raises(WorldAfterstateV2TrainingError, match="root split"):
        train_epoch(model, new_optimizer(model, config), (left, right),
                    epoch=1, config=config)
