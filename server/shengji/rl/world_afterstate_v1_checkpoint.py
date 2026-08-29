"""Portable, pickle-free checkpoints for the Value V1 cohort."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import numpy as np
import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_model import CAPACITY_SHAPES
from .world_afterstate_v1_model import (
    WorldAfterstateAdvantageV1, new_world_afterstate_advantage_model)
from .world_afterstate_v1_training import COHORT_SIZE, model_state_sha256


CHECKPOINT_SCHEMA = "world-afterstate-advantage-checkpoint-v1"
AUTHORITY = {
    "warm_start_authorized": False,
    "audit_opening_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1CheckpointError(ValueError):
    """A checkpoint identity, tensor, model state, or authority drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1CheckpointError(f"{label} drift")
    return value


def checkpoint_bytes(
        model: WorldAfterstateAdvantageV1, *, shape_name: str,
        member_index: int, init_seed: int, selected_epoch: int,
        freeze_sha256: str, config_sha256: str,
        subsplit_manifest_sha256: str, training_population_sha256: str,
        common_epoch_sha256: str) -> bytes:
    if type(model) is not WorldAfterstateAdvantageV1 \
            or shape_name not in CAPACITY_SHAPES \
            or model.shape != CAPACITY_SHAPES[shape_name] \
            or isinstance(member_index, bool) \
            or not isinstance(member_index, int) \
            or not 0 <= member_index < COHORT_SIZE \
            or isinstance(init_seed, bool) or not isinstance(init_seed, int) \
            or not 0 <= init_seed < 2**63 \
            or isinstance(selected_epoch, bool) \
            or not isinstance(selected_epoch, int) or selected_epoch <= 0:
        raise WorldAfterstateV1CheckpointError("checkpoint identity drift")
    for label, value in (
            ("checkpoint freeze SHA-256", freeze_sha256),
            ("checkpoint config SHA-256", config_sha256),
            ("checkpoint subsplit manifest SHA-256",
             subsplit_manifest_sha256),
            ("checkpoint training population SHA-256",
             training_population_sha256),
            ("checkpoint common epoch SHA-256", common_epoch_sha256)):
        _digest(value, label)
    parameters = []
    for name, parameter in model.named_parameters():
        if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
            raise WorldAfterstateV1CheckpointError(
                "checkpoint parameter device/dtype drift")
        array = parameter.detach().contiguous().numpy().astype("<f4", copy=False)
        raw = array.tobytes(order="C")
        parameters.append({
            "name": name, "shape": list(array.shape),
            "dtype": "little-endian-float32", "byte_count": len(raw),
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
        "member_index": member_index,
        "init_seed": init_seed,
        "selected_epoch": selected_epoch,
        "freeze_sha256": freeze_sha256,
        "config_sha256": config_sha256,
        "subsplit_manifest_sha256": subsplit_manifest_sha256,
        "training_population_sha256": training_population_sha256,
        "common_epoch_sha256": common_epoch_sha256,
        "model_state_sha256": model_state_sha256(model),
        "parameters": parameters,
        "authority": dict(AUTHORITY),
    }
    return canonical_json_bytes({
        **body, "checkpoint_sha256": _sha(canonical_json_bytes(body))})


def reopen_checkpoint(
        raw: bytes) -> tuple[WorldAfterstateAdvantageV1, dict[str, Any]]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1CheckpointError("checkpoint byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1CheckpointError(
            "checkpoint is not canonical JSON") from exc
    required = {
        "schema", "shape_name", "shape", "member_index", "init_seed",
        "selected_epoch", "freeze_sha256", "config_sha256",
        "subsplit_manifest_sha256", "training_population_sha256",
        "common_epoch_sha256", "model_state_sha256", "parameters",
        "authority", "checkpoint_sha256",
    }
    if type(value) is not dict or canonical_json_bytes(value) != raw \
            or set(value) != required \
            or value.get("schema") != CHECKPOINT_SCHEMA \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1CheckpointError("checkpoint schema drift")
    shape_name = value.get("shape_name")
    if shape_name not in CAPACITY_SHAPES:
        raise WorldAfterstateV1CheckpointError("checkpoint shape drift")
    shape = CAPACITY_SHAPES[shape_name]
    if value.get("shape") != {
            "public_hidden": shape.public_hidden,
            "history_hidden": shape.history_hidden,
            "world_hidden": shape.world_hidden,
            "perspective_hidden": shape.perspective_hidden,
            "head_hidden": shape.head_hidden} \
            or isinstance(value.get("member_index"), bool) \
            or not isinstance(value.get("member_index"), int) \
            or not 0 <= value["member_index"] < COHORT_SIZE \
            or isinstance(value.get("init_seed"), bool) \
            or not isinstance(value.get("init_seed"), int) \
            or not 0 <= value["init_seed"] < 2**63 \
            or isinstance(value.get("selected_epoch"), bool) \
            or not isinstance(value.get("selected_epoch"), int) \
            or value["selected_epoch"] <= 0:
        raise WorldAfterstateV1CheckpointError("checkpoint identity drift")
    for key in (
            "freeze_sha256", "config_sha256", "subsplit_manifest_sha256",
            "training_population_sha256", "common_epoch_sha256",
            "model_state_sha256", "checkpoint_sha256"):
        _digest(value.get(key), f"checkpoint {key}")
    body = {key: item for key, item in value.items()
            if key != "checkpoint_sha256"}
    if value["checkpoint_sha256"] != _sha(canonical_json_bytes(body)):
        raise WorldAfterstateV1CheckpointError(
            "checkpoint reconstruction drift")
    model = new_world_afterstate_advantage_model(value["init_seed"], shape)
    named = dict(model.named_parameters())
    rows = value.get("parameters")
    if type(rows) is not list \
            or [row.get("name") if type(row) is dict else None for row in rows] \
            != list(named):
        raise WorldAfterstateV1CheckpointError(
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
                raise WorldAfterstateV1CheckpointError(
                    "checkpoint parameter row drift")
            try:
                data = base64.b64decode(row["data_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise WorldAfterstateV1CheckpointError(
                    "checkpoint parameter encoding drift") from exc
            if len(data) != row["byte_count"] \
                    or len(data) != named[row["name"]].numel() * 4:
                raise WorldAfterstateV1CheckpointError(
                    "checkpoint parameter byte-count drift")
            array = np.frombuffer(data, dtype="<f4").reshape(row["shape"])
            named[row["name"]].copy_(torch.from_numpy(array.copy()))
    if model_state_sha256(model) != value["model_state_sha256"]:
        raise WorldAfterstateV1CheckpointError(
            "checkpoint model state reconstruction drift")
    return model, value


__all__ = [
    "AUTHORITY", "CHECKPOINT_SCHEMA", "WorldAfterstateV1CheckpointError",
    "checkpoint_bytes", "reopen_checkpoint",
]
