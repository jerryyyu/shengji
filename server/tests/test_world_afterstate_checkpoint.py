from __future__ import annotations

import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_checkpoint import (
    WorldAfterstateCheckpointError, checkpoint_bytes, reopen_checkpoint)
from shengji.rl.world_afterstate_model import (
    CAPACITY_SHAPES, new_world_afterstate_model)
from shengji.rl.world_afterstate_training import model_state_sha256


def test_checkpoint_is_canonical_portable_and_pickle_free():
    model = new_world_afterstate_model(91, CAPACITY_SHAPES["small"])
    raw = checkpoint_bytes(
        model, shape_name="small", init_seed=91, selected_epoch=3,
        freeze_sha256="f" * 64, config_sha256="c" * 64)
    reopened, metadata = reopen_checkpoint(raw)
    assert model_state_sha256(reopened) == model_state_sha256(model)
    assert metadata["selected_epoch"] == 3
    assert raw == canonical_json_bytes(json.loads(raw))
    assert not raw.startswith(b"\x80")


def test_checkpoint_state_and_parameter_population_are_load_bearing():
    model = new_world_afterstate_model(92, CAPACITY_SHAPES["small"])
    raw = checkpoint_bytes(
        model, shape_name="small", init_seed=92, selected_epoch=2,
        freeze_sha256="f" * 64, config_sha256="c" * 64)
    value = json.loads(raw)
    value["parameters"] = value["parameters"][:-1]
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    import hashlib
    value["checkpoint_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(WorldAfterstateCheckpointError,
                       match="parameter population drift"):
        reopen_checkpoint(canonical_json_bytes(value))

    value = json.loads(raw)
    value["model_state_sha256"] = "0" * 64
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    value["checkpoint_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(WorldAfterstateCheckpointError,
                       match="model state reconstruction drift"):
        reopen_checkpoint(canonical_json_bytes(value))
