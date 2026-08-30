from __future__ import annotations

import base64
import hashlib
import json

import numpy as np
import pytest
import torch

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS
from shengji.rl.world_afterstate_v2_model import new_world_afterstate_v2_model
from shengji.rl.world_afterstate_v2_recovery import (
    WorldAfterstateV2RecoveryError, recovery_bytes, reopen_recovery)
from shengji.rl.world_afterstate_v2_selection_contract import EpochSelectScoreV2
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig, WorldAfterstateV2TrainingExample,
    collate_training_examples, model_state_sha256, new_optimizer, train_epoch)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _batch():
    result = []
    for candidate in range(2):
        deal, slot, state = (_sha("deal"), _sha("slot"), _sha("state"))
        successors = [_sha(f"successor:{index}") for index in range(2)]
        cset = hashlib.sha256(canonical_json_bytes({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": state, "successor_sha256s": successors,
        })).hexdigest()
        for replica in range(8):
            public = np.zeros(PUBLIC_DIM, dtype=np.float32)
            public[candidate] = 1
            world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
            world[0, candidate] = 1
            perspective = np.zeros(PERSPECTIVE_DIM, dtype=np.float32)
            perspective[0] = 1
            from shengji.rl.world_afterstate import WorldAfterstateTensorsV0
            result.append(WorldAfterstateV2TrainingExample(
                deal, slot, state, cset, candidate, candidate == 0,
                successors[candidate], _sha(f"continuation:{replica}"), replica,
                "natural", "fit", "attacker", "early", "lead", "2", "S",
                "0-39", WorldAfterstateTensorsV0(
                    public, np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
                    world, perspective), (candidate + replica) % 204))
    return collate_training_examples(result)


def _fixture():
    config = WorldAfterstateV2TrainingConfig(100_000_000, 0, 1_000, 2, 1.0)
    model = new_world_afterstate_v2_model(22)
    optimizer = new_optimizer(model, config)
    receipt = train_epoch(model, optimizer, (_batch(),), epoch=1, config=config)
    # The compact fixture does not exercise every embedding row.  Materialize
    # the untouched parameter states as AdamW would, so the test also covers
    # the codec's every-named-parameter requirement.
    for parameter in model.parameters():
        if not any(parameter is existing for existing in optimizer.state):
            optimizer.state[parameter] = {
                "step": torch.tensor(1.0),
                "exp_avg": torch.zeros_like(parameter),
                "exp_avg_sq": torch.zeros_like(parameter),
            }
    score = EpochSelectScoreV2(
        epoch=1, seed_block=1, member_index=0, control_name="natural",
        model_state_sha256=model_state_sha256(model),
        selection_population_sha256=_sha("selection"),
        prediction_manifest_sha256=_sha("predictions"), loss_nano=1)
    raw = recovery_bytes(
        model, optimizer, config, receipt, score, seed_block=1, member_index=0,
        control_name="natural", init_seed=22, freeze_sha256=_sha("freeze"),
        common_epoch_sha256=_sha("common"))
    return model, optimizer, config, receipt, score, raw


def _rehash(value):
    value["recovery_sha256"] = hashlib.sha256(canonical_json_bytes(
        {key: item for key, item in value.items() if key != "recovery_sha256"}
    )).hexdigest()
    return canonical_json_bytes(value)


def _reopen(raw):
    return reopen_recovery(
        raw, expected_freeze_sha256=_sha("freeze"),
        expected_selection_population_sha256=_sha("selection"))


def test_recovery_round_trip_is_byte_stable_and_exact():
    model, optimizer, config, receipt, score, raw = _fixture()
    reopened = _reopen(raw)
    assert recovery_bytes(
        reopened.model, reopened.optimizer, reopened.config, reopened.receipt,
        reopened.score, seed_block=reopened.metadata["seed_block"],
        member_index=reopened.metadata["member_index"],
        control_name=reopened.metadata["control_name"],
        init_seed=reopened.metadata["init_seed"],
        freeze_sha256=reopened.metadata["freeze_sha256"],
        common_epoch_sha256=reopened.metadata["common_epoch_sha256"]) == raw
    assert model_state_sha256(reopened.model) == model_state_sha256(model)
    assert reopened.receipt.payload() == receipt.payload()
    assert reopened.score.payload() == score.payload()
    assert len(reopened.optimizer.state) == len(tuple(model.parameters()))


def test_epoch_two_matches_uninterrupted_training_after_reopen():
    model, optimizer, config, _receipt, _score, raw = _fixture()
    uninterrupted = train_epoch(model, optimizer, (_batch(),), epoch=2,
                                config=config)
    reopened = _reopen(raw)
    resumed = train_epoch(reopened.model, reopened.optimizer, (_batch(),),
                          epoch=2, config=config)
    assert model_state_sha256(reopened.model) == model_state_sha256(model)
    assert resumed == uninterrupted
    assert model_state_sha256(reopened.model) == model_state_sha256(model)


def test_nested_mutations_and_model_only_resume_refuse():
    _model, _optimizer, _config, _receipt, _score, raw = _fixture()
    value = json.loads(raw)
    decoded = bytearray(base64.b64decode(value["checkpoint_base64"]))
    decoded[-1] ^= 1
    value["checkpoint_base64"] = base64.b64encode(decoded).decode()
    with pytest.raises(WorldAfterstateV2RecoveryError):
        _reopen(_rehash(value))

    value = json.loads(raw)
    value["receipt"]["gradient_norm_nano"] += 1
    with pytest.raises(WorldAfterstateV2RecoveryError):
        _reopen(_rehash(value))

    value = json.loads(raw)
    state = value["optimizer"]["parameters"][0]["exp_avg"]
    decoded = bytearray(base64.b64decode(state["data_base64"]))
    decoded[0] ^= 1
    state["data_base64"] = base64.b64encode(decoded).decode()
    with pytest.raises(WorldAfterstateV2RecoveryError):
        _reopen(_rehash(value))

    value = json.loads(raw)
    value["optimizer"]["parameters"].pop()
    with pytest.raises(WorldAfterstateV2RecoveryError):
        _reopen(_rehash(value))

    value = json.loads(raw)
    value["receipt"]["model_state_sha256_after"] = _sha("foreign")
    with pytest.raises(WorldAfterstateV2RecoveryError):
        _reopen(_rehash(value))


def test_missing_optimizer_state_is_not_model_resume():
    _model, _optimizer, _config, _receipt, _score, raw = _fixture()
    value = json.loads(raw)
    value["optimizer"]["parameters"] = []
    with pytest.raises(WorldAfterstateV2RecoveryError, match="optimizer"):
        _reopen(_rehash(value))


def test_coordinated_provenance_rehash_cannot_change_cohort_or_selection():
    _model, _optimizer, _config, _receipt, _score, raw = _fixture()
    value = json.loads(raw)
    value["receipt"]["cohort"] = "control"
    value["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(value["receipt"])).hexdigest()
    with pytest.raises(WorldAfterstateV2RecoveryError,
                       match="receipt/checkpoint binding"):
        _reopen(_rehash(value))

    value = json.loads(raw)
    foreign = _sha("foreign-selection")
    value["score"]["selection_population_sha256"] = foreign
    value["score_sha256"] = hashlib.sha256(
        canonical_json_bytes(value["score"])).hexdigest()
    value["metadata"]["selection_population_sha256"] = foreign
    with pytest.raises(WorldAfterstateV2RecoveryError,
                       match="checkpoint identity"):
        _reopen(_rehash(value))
