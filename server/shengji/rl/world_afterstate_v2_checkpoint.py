"""Portable, pickle-free checkpoints for the Value-Afterstate V2 model.

This module serializes only the fixed V2 model parameters and the identities
needed to keep a checkpoint attached to one reviewed training execution.  It
does not read or write files, select epochs, or grant any execution or
consumer authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping

import numpy as np
import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_inference import MEMBERS_PER_BLOCK, SEED_BLOCKS
from .world_afterstate_v2_model import (
    MODEL_SCHEMA, WorldAfterstateValueV2, new_world_afterstate_v2_model,
    count_trainable_parameters,
)
from .world_afterstate_v2_controls import CONTROL_NAMES as _CONTROL_NAMES
from .world_afterstate_v2_training import model_state_sha256
from .world_afterstate_v2_schedule import MAX_EPOCHS


CHECKPOINT_SCHEMA = "world-afterstate-absolute-leaf-checkpoint-v2"
CONTROL_NAMES = ("natural", *_CONTROL_NAMES)
AUTHORITY = {
    "data_collection_authorized": False,
    "capacity_execution_authorized": False,
    "warm_start_authorized": False,
    "training_authorized": False,
    "audit_opening_authorized": False,
    "consumer_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}
# Descriptive compatibility name for callers that use the V1 convention.
CHECKPOINT_AUTHORITY = AUTHORITY


class WorldAfterstateV2CheckpointError(ValueError):
    """A V2 checkpoint identity, tensor, state, or authority drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2CheckpointError(f"{label} drift")
    return value


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2CheckpointError(f"{label} drift")
    return value


def _shape(parameter: torch.Tensor) -> list[int]:
    return [int(value) for value in parameter.shape]


def _parameter_rows(model: WorldAfterstateValueV2) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, parameter in model.named_parameters():
        if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
            raise WorldAfterstateV2CheckpointError(
                "checkpoint parameter device/dtype drift")
        array = parameter.detach().contiguous().numpy().astype(
            "<f4", copy=False)
        raw = array.tobytes(order="C")
        rows.append({
            "name": name,
            "shape": _shape(parameter),
            "dtype": "little-endian-float32",
            "byte_count": len(raw),
            "data_base64": base64.b64encode(raw).decode("ascii"),
        })
    return rows


def _check_identity(*, seed_block: object, member_index: object,
                    control_name: object, init_seed: object,
                    selected_epoch: object, freeze_sha256: object,
                    config_sha256: object, population_sha256: object,
                    schedule_sha256: object,
                    common_epoch_sha256: object) -> None:
    _strict_int(seed_block, "checkpoint seed block")
    if seed_block not in SEED_BLOCKS:
        raise WorldAfterstateV2CheckpointError("checkpoint seed block drift")
    _strict_int(member_index, "checkpoint member index")
    if member_index >= MEMBERS_PER_BLOCK:
        raise WorldAfterstateV2CheckpointError("checkpoint member index drift")
    if control_name not in CONTROL_NAMES:
        raise WorldAfterstateV2CheckpointError("checkpoint control name drift")
    _strict_int(init_seed, "checkpoint initialization seed")
    if init_seed >= 2**63:
        raise WorldAfterstateV2CheckpointError(
            "checkpoint initialization seed drift")
    _strict_int(selected_epoch, "checkpoint selected epoch", minimum=1)
    if selected_epoch > MAX_EPOCHS:
        raise WorldAfterstateV2CheckpointError(
            "checkpoint selected epoch drift")
    for label, value in (
            ("checkpoint freeze SHA-256", freeze_sha256),
            ("checkpoint config SHA-256", config_sha256),
            ("checkpoint population SHA-256", population_sha256),
            ("checkpoint schedule SHA-256", schedule_sha256),
            ("checkpoint common epoch SHA-256", common_epoch_sha256)):
        _digest(value, label)


def checkpoint_bytes(
        model: WorldAfterstateValueV2, *, seed_block: int,
        member_index: int, control_name: str, init_seed: int,
        selected_epoch: int, freeze_sha256: str, config_sha256: str,
        population_sha256: str, schedule_sha256: str,
        common_epoch_sha256: str) -> bytes:
    """Encode one fixed V2 model as canonical JSON with raw float32 bytes."""
    if type(model) is not WorldAfterstateValueV2:
        raise WorldAfterstateV2CheckpointError("checkpoint model identity drift")
    _check_identity(
        seed_block=seed_block, member_index=member_index,
        control_name=control_name, init_seed=init_seed,
        selected_epoch=selected_epoch, freeze_sha256=freeze_sha256,
        config_sha256=config_sha256, population_sha256=population_sha256,
        schedule_sha256=schedule_sha256,
        common_epoch_sha256=common_epoch_sha256)
    parameter_count = count_trainable_parameters(model)
    rows = _parameter_rows(model)
    if parameter_count != sum(
            int(row["byte_count"]) // 4 for row in rows):
        raise WorldAfterstateV2CheckpointError("checkpoint parameter count drift")
    body = {
        "schema": CHECKPOINT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "seed_block": seed_block,
        "member_index": member_index,
        "control_name": control_name,
        "init_seed": init_seed,
        "selected_epoch": selected_epoch,
        "freeze_sha256": freeze_sha256,
        "config_sha256": config_sha256,
        "population_sha256": population_sha256,
        "schedule_sha256": schedule_sha256,
        "common_epoch_sha256": common_epoch_sha256,
        "parameter_count": parameter_count,
        "model_state_sha256": model_state_sha256(model),
        "parameters": rows,
        "authority": dict(AUTHORITY),
    }
    return canonical_json_bytes({
        **body, "checkpoint_sha256": _sha_bytes(canonical_json_bytes(body))})


def reopen_checkpoint(raw: bytes) -> tuple[WorldAfterstateValueV2, dict[str, Any]]:
    """Reconstruct and validate one canonical V2 checkpoint byte string."""
    if type(raw) is not bytes:
        raise WorldAfterstateV2CheckpointError("checkpoint byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2CheckpointError(
            "checkpoint is not canonical JSON") from exc
    required = {
        "schema", "model_schema", "seed_block", "member_index",
        "control_name", "init_seed", "selected_epoch", "freeze_sha256",
        "config_sha256", "population_sha256", "schedule_sha256",
        "common_epoch_sha256", "parameter_count", "model_state_sha256",
        "parameters", "authority", "checkpoint_sha256",
    }
    if (type(value) is not dict or canonical_json_bytes(value) != raw
            or set(value) != required
            or value.get("schema") != CHECKPOINT_SCHEMA
            or value.get("model_schema") != MODEL_SCHEMA
            or value.get("authority") != AUTHORITY):
        raise WorldAfterstateV2CheckpointError("checkpoint schema drift")
    _check_identity(
        seed_block=value["seed_block"], member_index=value["member_index"],
        control_name=value["control_name"], init_seed=value["init_seed"],
        selected_epoch=value["selected_epoch"],
        freeze_sha256=value["freeze_sha256"],
        config_sha256=value["config_sha256"],
        population_sha256=value["population_sha256"],
        schedule_sha256=value["schedule_sha256"],
        common_epoch_sha256=value["common_epoch_sha256"])
    parameter_count = _strict_int(value["parameter_count"],
                                  "checkpoint parameter count", minimum=1)
    _digest(value["model_state_sha256"], "checkpoint model state SHA-256")
    _digest(value["checkpoint_sha256"], "checkpoint SHA-256")
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    if value["checkpoint_sha256"] != _sha_bytes(canonical_json_bytes(body)):
        raise WorldAfterstateV2CheckpointError(
            "checkpoint reconstruction drift")

    model = new_world_afterstate_v2_model(value["init_seed"])
    named = dict(model.named_parameters())
    expected_count = count_trainable_parameters(model)
    if parameter_count != expected_count:
        raise WorldAfterstateV2CheckpointError("checkpoint parameter count drift")
    rows = value["parameters"]
    if (type(rows) is not list
            or [row.get("name") if type(row) is dict else None for row in rows]
            != list(named)
            or len(rows) != len(named)):
        raise WorldAfterstateV2CheckpointError(
            "checkpoint parameter population drift")
    with torch.no_grad():
        for row in rows:
            if (type(row) is not dict or set(row) != {
                    "name", "shape", "dtype", "byte_count", "data_base64"}
                    or row["dtype"] != "little-endian-float32"
                    or row["shape"] != list(named[row["name"]].shape)
                    or isinstance(row["byte_count"], bool)
                    or not isinstance(row["byte_count"], int)
                    or row["byte_count"] <= 0):
                raise WorldAfterstateV2CheckpointError(
                    "checkpoint parameter row drift")
            try:
                data = base64.b64decode(row["data_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise WorldAfterstateV2CheckpointError(
                    "checkpoint parameter encoding drift") from exc
            expected_bytes = named[row["name"]].numel() * 4
            if len(data) != row["byte_count"] or len(data) != expected_bytes:
                raise WorldAfterstateV2CheckpointError(
                    "checkpoint parameter byte-count drift")
            try:
                array = np.frombuffer(data, dtype="<f4").reshape(
                    row["shape"])
            except (TypeError, ValueError) as exc:
                raise WorldAfterstateV2CheckpointError(
                    "checkpoint parameter shape drift") from exc
            named[row["name"]].copy_(torch.from_numpy(array.copy()))
    if model_state_sha256(model) != value["model_state_sha256"]:
        raise WorldAfterstateV2CheckpointError(
            "checkpoint model state reconstruction drift")
    return model, value


__all__ = [
    "AUTHORITY", "CHECKPOINT_AUTHORITY", "CHECKPOINT_SCHEMA",
    "CONTROL_NAMES", "WorldAfterstateV2CheckpointError",
    "checkpoint_bytes", "reopen_checkpoint",
]
