"""Portable, pickle-free checkpoints for the V0 value cohort."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping

import numpy as np
import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_model import (
    CAPACITY_SHAPES, WorldAfterstateValueV0, new_world_afterstate_model)
from .world_afterstate_training import model_state_sha256


CHECKPOINT_SCHEMA = "world-afterstate-value-checkpoint-v0"
CHECKPOINT_AUTHORITY = {
    "warm_start_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateCheckpointError(ValueError):
    """A checkpoint identity, tensor, state hash, or authority drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateCheckpointError(f"{label} drift")
    return value


def checkpoint_bytes(
        model: WorldAfterstateValueV0, *, shape_name: str, init_seed: int,
        selected_epoch: int, freeze_sha256: str,
        config_sha256: str) -> bytes:
    if type(model) is not WorldAfterstateValueV0 \
            or shape_name not in CAPACITY_SHAPES \
            or model.shape != CAPACITY_SHAPES[shape_name] \
            or isinstance(init_seed, bool) or not isinstance(init_seed, int) \
            or isinstance(selected_epoch, bool) \
            or not isinstance(selected_epoch, int) or selected_epoch <= 0:
        raise WorldAfterstateCheckpointError("checkpoint identity drift")
    _digest(freeze_sha256, "checkpoint freeze SHA-256")
    _digest(config_sha256, "checkpoint config SHA-256")
    parameters = []
    for name, parameter in model.named_parameters():
        if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
            raise WorldAfterstateCheckpointError(
                "checkpoint parameter device/dtype drift")
        array = parameter.detach().contiguous().numpy().astype("<f4", copy=False)
        raw = array.tobytes(order="C")
        parameters.append({
            "name": name,
            "shape": list(array.shape),
            "dtype": "little-endian-float32",
            "byte_count": len(raw),
            "data_base64": base64.b64encode(raw).decode("ascii"),
        })
    body = {
        "schema": CHECKPOINT_SCHEMA,
        "shape_name": shape_name,
        "shape": {
            "public_hidden": model.shape.public_hidden,
            "history_hidden": model.shape.history_hidden,
            "world_hidden": model.shape.world_hidden,
            "perspective_hidden": model.shape.perspective_hidden,
            "head_hidden": model.shape.head_hidden,
        },
        "init_seed": init_seed,
        "selected_epoch": selected_epoch,
        "freeze_sha256": freeze_sha256,
        "config_sha256": config_sha256,
        "model_state_sha256": model_state_sha256(model),
        "parameters": parameters,
        "authority": dict(CHECKPOINT_AUTHORITY),
    }
    return canonical_json_bytes({
        **body, "checkpoint_sha256": _sha_bytes(canonical_json_bytes(body))})


def reopen_checkpoint(raw: bytes) -> tuple[WorldAfterstateValueV0, dict[str, Any]]:
    if type(raw) is not bytes:
        raise WorldAfterstateCheckpointError("checkpoint byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateCheckpointError(
            "checkpoint is not canonical JSON") from exc
    required = {
        "schema", "shape_name", "shape", "init_seed", "selected_epoch",
        "freeze_sha256", "config_sha256", "model_state_sha256",
        "parameters", "authority", "checkpoint_sha256",
    }
    if type(value) is not dict or canonical_json_bytes(value) != raw \
            or set(value) != required or value.get("schema") != CHECKPOINT_SCHEMA \
            or value.get("authority") != CHECKPOINT_AUTHORITY:
        raise WorldAfterstateCheckpointError("checkpoint schema drift")
    shape_name = value["shape_name"]
    if shape_name not in CAPACITY_SHAPES:
        raise WorldAfterstateCheckpointError("checkpoint shape drift")
    shape = CAPACITY_SHAPES[shape_name]
    if value["shape"] != {
            "public_hidden": shape.public_hidden,
            "history_hidden": shape.history_hidden,
            "world_hidden": shape.world_hidden,
            "perspective_hidden": shape.perspective_hidden,
            "head_hidden": shape.head_hidden} \
            or isinstance(value["init_seed"], bool) \
            or not isinstance(value["init_seed"], int) \
            or isinstance(value["selected_epoch"], bool) \
            or not isinstance(value["selected_epoch"], int) \
            or value["selected_epoch"] <= 0:
        raise WorldAfterstateCheckpointError("checkpoint identity drift")
    for key in ("freeze_sha256", "config_sha256", "model_state_sha256",
                "checkpoint_sha256"):
        _digest(value[key], key)
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    if value["checkpoint_sha256"] != _sha_bytes(canonical_json_bytes(body)):
        raise WorldAfterstateCheckpointError(
            "checkpoint reconstruction drift")
    model = new_world_afterstate_model(value["init_seed"], shape)
    named = dict(model.named_parameters())
    rows = value["parameters"]
    if type(rows) is not list or [row.get("name") for row in rows] \
            != list(named):
        raise WorldAfterstateCheckpointError(
            "checkpoint parameter population drift")
    with torch.no_grad():
        for row in rows:
            if type(row) is not dict or set(row) != {
                    "name", "shape", "dtype", "byte_count", "data_base64"} \
                    or row["dtype"] != "little-endian-float32" \
                    or row["shape"] != list(named[row["name"]].shape) \
                    or isinstance(row["byte_count"], bool) \
                    or not isinstance(row["byte_count"], int) \
                    or row["byte_count"] <= 0:
                raise WorldAfterstateCheckpointError(
                    "checkpoint parameter row drift")
            try:
                data = base64.b64decode(row["data_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise WorldAfterstateCheckpointError(
                    "checkpoint parameter encoding drift") from exc
            if len(data) != row["byte_count"] \
                    or len(data) != named[row["name"]].numel() * 4:
                raise WorldAfterstateCheckpointError(
                    "checkpoint parameter byte count drift")
            array = np.frombuffer(data, dtype="<f4").reshape(row["shape"])
            named[row["name"]].copy_(torch.from_numpy(array.copy()))
    if model_state_sha256(model) != value["model_state_sha256"]:
        raise WorldAfterstateCheckpointError(
            "checkpoint model state reconstruction drift")
    return model, value


__all__ = [
    "CHECKPOINT_AUTHORITY", "CHECKPOINT_SCHEMA",
    "WorldAfterstateCheckpointError", "checkpoint_bytes",
    "reopen_checkpoint",
]
