from __future__ import annotations

import base64
import hashlib
import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_checkpoint import (
    AUTHORITY, CHECKPOINT_SCHEMA, WorldAfterstateV2CheckpointError,
    checkpoint_bytes, reopen_checkpoint,
)
from shengji.rl.world_afterstate_v2_model import new_world_afterstate_v2_model
from shengji.rl.world_afterstate_v2_training import model_state_sha256


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _checkpoint(seed: int = 71):
    model = new_world_afterstate_v2_model(seed)
    raw = checkpoint_bytes(
        model, seed_block=1, member_index=2, control_name="natural",
        init_seed=seed, selected_epoch=3,
        freeze_sha256=_hash("freeze"), config_sha256=_hash("config"),
        population_sha256=_hash("population"),
        schedule_sha256=_hash("schedule"),
        common_epoch_sha256=_hash("common"))
    return model, raw


def _rehash(value: dict[str, object]) -> bytes:
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    value["checkpoint_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    return canonical_json_bytes(value)


def test_v2_checkpoint_is_canonical_pickle_free_and_round_trips_state():
    model, raw = _checkpoint()
    reopened, metadata = reopen_checkpoint(raw)
    assert raw == canonical_json_bytes(json.loads(raw))
    assert not raw.startswith(b"\x80")
    assert model_state_sha256(reopened) == model_state_sha256(model)
    assert metadata["seed_block"] == 1
    assert metadata["member_index"] == 2
    assert metadata["control_name"] == "natural"
    assert metadata["parameter_count"] == sum(
        parameter.numel() for parameter in model.parameters())
    assert metadata["authority"] == AUTHORITY


def test_tensor_byte_mutation_is_detected_after_resealing():
    _model, raw = _checkpoint(72)
    value = json.loads(raw)
    row = value["parameters"][0]
    decoded = bytearray(base64.b64decode(row["data_base64"]))
    decoded[0] ^= 1
    row["data_base64"] = base64.b64encode(decoded).decode("ascii")
    with pytest.raises(WorldAfterstateV2CheckpointError,
                       match="model state reconstruction"):
        reopen_checkpoint(_rehash(value))


def test_model_schema_and_authority_mutations_refuse():
    _model, raw = _checkpoint(73)
    value = json.loads(raw)
    value["model_schema"] = "wrong-model"
    with pytest.raises(WorldAfterstateV2CheckpointError, match="schema"):
        reopen_checkpoint(_rehash(value))
    value = json.loads(raw)
    value["authority"]["gameplay_authorized"] = True
    with pytest.raises(WorldAfterstateV2CheckpointError, match="schema"):
        reopen_checkpoint(_rehash(value))


@pytest.mark.parametrize(("field", "replacement"), (
    ("seed_block", 3), ("member_index", 4),
    ("control_name", "unknown-control"), ("selected_epoch", 0),
    ("init_seed", 2**63),
))
def test_checkpoint_cohort_and_epoch_identity_mutations_refuse(field, replacement):
    _model, raw = _checkpoint(74)
    value = json.loads(raw)
    value[field] = replacement
    with pytest.raises(WorldAfterstateV2CheckpointError, match="drift"):
        reopen_checkpoint(_rehash(value))


@pytest.mark.parametrize("mutation", ("drop", "extra", "duplicate"))
def test_parameter_population_mutations_refuse(mutation):
    _model, raw = _checkpoint(75)
    value = json.loads(raw)
    rows = value["parameters"]
    if mutation == "drop":
        rows.pop()
    elif mutation == "extra":
        rows.append(dict(rows[-1], name="not-a-model-parameter"))
    else:
        rows[1]["name"] = rows[0]["name"]
    with pytest.raises(WorldAfterstateV2CheckpointError,
                       match="parameter population"):
        reopen_checkpoint(_rehash(value))
