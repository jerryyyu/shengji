from __future__ import annotations

import hashlib
import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_model import CAPACITY_SHAPES
from shengji.rl.world_afterstate_v1_checkpoint import (
    AUTHORITY, WorldAfterstateV1CheckpointError, checkpoint_bytes,
    reopen_checkpoint)
from shengji.rl.world_afterstate_v1_model import (
    new_world_afterstate_advantage_model)
from shengji.rl.world_afterstate_v1_training import model_state_sha256


def _bytes(seed=71):
    model = new_world_afterstate_advantage_model(
        seed, CAPACITY_SHAPES["small"])
    return model, checkpoint_bytes(
        model, shape_name="small", member_index=2, init_seed=seed,
        selected_epoch=3, freeze_sha256="f" * 64,
        config_sha256="c" * 64, subsplit_manifest_sha256="b" * 64,
        training_population_sha256="a" * 64,
        common_epoch_sha256="e" * 64)


def _rehash(value):
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    value["checkpoint_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    return canonical_json_bytes(value)


def test_checkpoint_is_canonical_portable_pickle_free_and_bound():
    model, raw = _bytes()
    reopened, metadata = reopen_checkpoint(raw)
    assert model_state_sha256(reopened) == model_state_sha256(model)
    assert metadata["selected_epoch"] == 3
    assert metadata["member_index"] == 2
    assert metadata["authority"] == AUTHORITY
    assert raw == canonical_json_bytes(json.loads(raw))
    assert not raw.startswith(b"\x80")


def test_parameter_population_and_state_hash_have_teeth():
    _model, raw = _bytes(72)
    value = json.loads(raw)
    value["parameters"] = value["parameters"][:-1]
    with pytest.raises(WorldAfterstateV1CheckpointError,
                       match="parameter population drift"):
        reopen_checkpoint(_rehash(value))
    value = json.loads(raw)
    value["model_state_sha256"] = "0" * 64
    with pytest.raises(WorldAfterstateV1CheckpointError,
                       match="model state reconstruction drift"):
        reopen_checkpoint(_rehash(value))


def test_external_identity_bindings_are_round_tripped_for_caller():
    _model, raw = _bytes(73)
    for field in (
            "freeze_sha256", "subsplit_manifest_sha256",
            "training_population_sha256", "common_epoch_sha256"):
        value = json.loads(raw)
        value[field] = "0" * 64
        # Self-rehashing cannot recover the expected external binding; reopen
        # faithfully exposes the altered metadata for its caller to compare.
        _reopened, metadata = reopen_checkpoint(_rehash(value))
        assert metadata[field] == "0" * 64
        assert metadata[field] != json.loads(raw)[field]


def test_checkpoint_refuses_member_and_parameter_byte_mutations():
    _model, raw = _bytes(74)
    value = json.loads(raw)
    value["member_index"] = 8
    with pytest.raises(WorldAfterstateV1CheckpointError,
                       match="identity drift"):
        reopen_checkpoint(_rehash(value))
    value = json.loads(raw)
    value["parameters"][0]["data_base64"] = "AAAA"
    with pytest.raises(WorldAfterstateV1CheckpointError,
                       match="byte-count drift"):
        reopen_checkpoint(_rehash(value))
