"""Portable, exact-resume recovery bundles for Value-Afterstate V2.

The bundle is a canonical JSON envelope around the existing portable model
checkpoint and an explicit AdamW state stream.  It deliberately has no
pickle/torch serialization or execution authority.  Reopening always builds
the optimizer through :func:`new_optimizer`, so optimizer code and defaults
cannot be supplied by a bundle or its caller.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_checkpoint import (
    AUTHORITY as CHECKPOINT_AUTHORITY,
    checkpoint_bytes,
    reopen_checkpoint,
)
from .world_afterstate_v2_model import WorldAfterstateValueV2
from .world_afterstate_v2_selection_contract import EpochSelectScoreV2
from .world_afterstate_v2_training import (
    WorldAfterstateV2EpochReceipt,
    WorldAfterstateV2TrainingConfig,
    model_state_sha256,
    new_optimizer,
)


RECOVERY_SCHEMA = "world-afterstate-v2-value-recovery-v1"
_CHECKPOINT_DIGEST_KEYS = (
    "freeze_sha256", "config_sha256", "population_sha256",
    "schedule_sha256", "common_epoch_sha256",
)
_DIGEST_KEYS = (*_CHECKPOINT_DIGEST_KEYS, "selection_population_sha256")
_AUTHORITY = dict(CHECKPOINT_AUTHORITY)
_DTYPE_TO_NP = {"little-endian-float32": np.dtype("<f4"),
                "little-endian-float64": np.dtype("<f8")}
_DTYPE_TO_TORCH = {"little-endian-float32": torch.float32,
                   "little-endian-float64": torch.float64}


class WorldAfterstateV2RecoveryError(ValueError):
    """A recovery envelope, identity, or optimizer state drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2RecoveryError(f"{label} drift")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2RecoveryError(f"{label} drift")
    return value


def _strict_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2RecoveryError("recovery bytes drift")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise WorldAfterstateV2RecoveryError(
                    "recovery duplicate object key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               ValueError(value)))
    except WorldAfterstateV2RecoveryError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2RecoveryError(
            "recovery is not strict canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2RecoveryError("recovery is not canonical JSON")
    return value


def _tensor_row(tensor: object, *, label: str) -> dict[str, object]:
    if type(tensor) is not torch.Tensor or tensor.device.type != "cpu" \
            or tensor.dtype not in (torch.float32, torch.float64) \
            or not bool(torch.all(torch.isfinite(tensor))):
        raise WorldAfterstateV2RecoveryError(f"{label} tensor drift")
    dtype = "little-endian-float32" if tensor.dtype == torch.float32 \
        else "little-endian-float64"
    array = tensor.detach().contiguous().numpy().astype(
        _DTYPE_TO_NP[dtype], copy=False)
    raw = array.tobytes(order="C")
    return {"dtype": dtype, "shape": list(array.shape),
            "byte_count": len(raw),
            "data_base64": base64.b64encode(raw).decode("ascii")}


def _decode_tensor(row: object, *, label: str,
                   expected_shape: tuple[int, ...] | None = None,
                   expected_dtype: torch.dtype | None = None) -> torch.Tensor:
    if type(row) is not dict or set(row) != {
            "dtype", "shape", "byte_count", "data_base64"} \
            or row.get("dtype") not in _DTYPE_TO_NP:
        raise WorldAfterstateV2RecoveryError(f"{label} row drift")
    dtype_name = row["dtype"]
    shape = row["shape"]
    if type(shape) is not list or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in shape):
        raise WorldAfterstateV2RecoveryError(f"{label} shape drift")
    shape_tuple = tuple(shape)
    if expected_shape is not None and shape_tuple != expected_shape:
        raise WorldAfterstateV2RecoveryError(f"{label} shape drift")
    dtype = _DTYPE_TO_TORCH[dtype_name]
    if expected_dtype is not None and dtype != expected_dtype:
        raise WorldAfterstateV2RecoveryError(f"{label} dtype drift")
    count = row["byte_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise WorldAfterstateV2RecoveryError(f"{label} byte-count drift")
    try:
        raw = base64.b64decode(row["data_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2RecoveryError(f"{label} encoding drift") from exc
    expected = math.prod(shape_tuple) * _DTYPE_TO_NP[dtype_name].itemsize
    if len(raw) != count or len(raw) != expected:
        raise WorldAfterstateV2RecoveryError(f"{label} byte-count drift")
    try:
        array = np.frombuffer(raw, dtype=_DTYPE_TO_NP[dtype_name]).reshape(
            shape_tuple)
    except (TypeError, ValueError) as exc:
        raise WorldAfterstateV2RecoveryError(f"{label} shape drift") from exc
    tensor = torch.from_numpy(array.copy())
    if not bool(torch.all(torch.isfinite(tensor))):
        raise WorldAfterstateV2RecoveryError(f"{label} nonfinite")
    return tensor


def _validate_identity(metadata: Mapping[str, Any]) -> None:
    _integer(metadata.get("seed_block"), "recovery seed block")
    if metadata["seed_block"] not in (1, 2):
        raise WorldAfterstateV2RecoveryError("recovery seed block drift")
    _integer(metadata.get("member_index"), "recovery member index")
    if metadata["member_index"] >= 4:
        raise WorldAfterstateV2RecoveryError("recovery member index drift")
    if type(metadata.get("control_name")) is not str \
            or not metadata["control_name"]:
        raise WorldAfterstateV2RecoveryError("recovery control name drift")
    _integer(metadata.get("init_seed"), "recovery initialization seed")
    if metadata["init_seed"] >= 2**63:
        raise WorldAfterstateV2RecoveryError("recovery initialization seed drift")
    _integer(metadata.get("completed_epoch"), "recovery completed epoch", 1)
    for key in _DIGEST_KEYS:
        _digest(metadata.get(key), f"recovery {key}")


def _optimizer_rows(model: WorldAfterstateValueV2,
                    optimizer: torch.optim.Optimizer,
                    config: WorldAfterstateV2TrainingConfig) -> list[dict[str, Any]]:
    if type(optimizer) is not torch.optim.AdamW or len(optimizer.param_groups) != 1:
        raise WorldAfterstateV2RecoveryError("recovery optimizer identity drift")
    expected = new_optimizer(model, config)
    actual_group = optimizer.param_groups[0]
    expected_group = expected.param_groups[0]
    if len(actual_group["params"]) != len(tuple(model.parameters())) \
            or any(left is not right for left, right in zip(
                actual_group["params"], model.parameters(), strict=True)):
        raise WorldAfterstateV2RecoveryError("recovery optimizer parameters drift")
    for key in set(actual_group) | set(expected_group):
        if key != "params" and actual_group.get(key) != expected_group.get(key):
            raise WorldAfterstateV2RecoveryError(
                "recovery optimizer configuration drift")
    named = dict(model.named_parameters())
    state_parameters = tuple(optimizer.state)
    if len(state_parameters) != len(named) or any(
            not any(parameter is candidate for candidate in named.values())
            for parameter in state_parameters):
        raise WorldAfterstateV2RecoveryError(
            "recovery optimizer parameter state population drift")
    rows = []
    for name, parameter in model.named_parameters():
        state = optimizer.state.get(parameter)
        if type(state) is not dict or set(state) != {
                "step", "exp_avg", "exp_avg_sq"}:
            raise WorldAfterstateV2RecoveryError(
                "recovery unsupported optimizer state")
        step = _tensor_row(state["step"], label=f"optimizer {name} step")
        if step["shape"] != []:
            raise WorldAfterstateV2RecoveryError("recovery optimizer step shape drift")
        step_tensor = state["step"]
        if float(step_tensor) < 1 or not float(step_tensor).is_integer():
            raise WorldAfterstateV2RecoveryError("recovery optimizer step drift")
        rows.append({
            "name": name,
            "step": step,
            "exp_avg": _tensor_row(state["exp_avg"],
                                    label=f"optimizer {name} exp_avg"),
            "exp_avg_sq": _tensor_row(state["exp_avg_sq"],
                                       label=f"optimizer {name} exp_avg_sq"),
        })
        for key in ("exp_avg", "exp_avg_sq"):
            value = state[key]
            if type(value) is not torch.Tensor or value.shape != parameter.shape \
                    or value.dtype != parameter.dtype or value.device.type != "cpu":
                raise WorldAfterstateV2RecoveryError(
                    f"recovery optimizer {name} {key} drift")
    return rows


def _payload_body(*, checkpoint_raw: bytes, config: WorldAfterstateV2TrainingConfig,
                  receipt: WorldAfterstateV2EpochReceipt,
                  score: EpochSelectScoreV2, optimizer_rows: list[dict[str, Any]],
                  metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": RECOVERY_SCHEMA,
        "checkpoint_sha256": _sha_bytes(checkpoint_raw),
        "checkpoint_base64": base64.b64encode(checkpoint_raw).decode("ascii"),
        "config": config.payload(),
        "config_sha256": config.sha256(),
        "receipt": receipt.payload(),
        "receipt_sha256": receipt.sha256(),
        "score": score.payload(),
        "score_sha256": _sha(score.payload()),
        "optimizer": {"algorithm": "AdamW", "parameters": optimizer_rows},
        "optimizer_state_sha256": _sha(optimizer_rows),
        "metadata": dict(metadata),
        "authority": dict(_AUTHORITY),
    }


def recovery_bytes(
        model: WorldAfterstateValueV2, optimizer: torch.optim.Optimizer,
        config: WorldAfterstateV2TrainingConfig,
        receipt: WorldAfterstateV2EpochReceipt,
        score: EpochSelectScoreV2, *, seed_block: int, member_index: int,
        control_name: str, init_seed: int, freeze_sha256: str,
        common_epoch_sha256: str) -> bytes:
    """Encode one completed epoch and enough state to resume the next epoch."""
    if type(model) is not WorldAfterstateValueV2 \
            or type(config) is not WorldAfterstateV2TrainingConfig \
            or type(receipt) is not WorldAfterstateV2EpochReceipt \
            or type(score) is not EpochSelectScoreV2:
        raise WorldAfterstateV2RecoveryError("recovery typed input drift")
    config.validate(); receipt.validate(); score.validate()
    if receipt.epoch > config.max_epochs:
        raise WorldAfterstateV2RecoveryError("recovery epoch/config binding drift")
    metadata = {
        "freeze_sha256": freeze_sha256,
        "seed_block": seed_block,
        "member_index": member_index,
        "control_name": control_name,
        "init_seed": init_seed,
        "completed_epoch": receipt.epoch,
        "config_sha256": config.sha256(),
        "population_sha256": receipt.population_sha256,
        "schedule_sha256": receipt.schedule_sha256,
        "common_epoch_sha256": common_epoch_sha256,
        "selection_population_sha256": score.selection_population_sha256,
    }
    _validate_identity(metadata)
    if receipt.config_sha256 != metadata["config_sha256"] \
            or receipt.model_state_sha256_after != model_state_sha256(model) \
            or receipt.cohort != ("primary" if control_name == "natural" else "control") \
            or (score.epoch, score.seed_block, score.member_index,
                score.control_name, score.model_state_sha256) != (
                    receipt.epoch, seed_block, member_index, control_name,
                    receipt.model_state_sha256_after):
        raise WorldAfterstateV2RecoveryError("recovery receipt/score binding drift")
    checkpoint_raw = checkpoint_bytes(
        model, seed_block=seed_block, member_index=member_index,
        control_name=control_name, init_seed=init_seed,
        selected_epoch=receipt.epoch, freeze_sha256=freeze_sha256,
        config_sha256=config.sha256(), population_sha256=receipt.population_sha256,
        schedule_sha256=receipt.schedule_sha256,
        common_epoch_sha256=common_epoch_sha256)
    rows = _optimizer_rows(model, optimizer, config)
    body = _payload_body(checkpoint_raw=checkpoint_raw, config=config,
                         receipt=receipt, score=score, optimizer_rows=rows,
                         metadata=metadata)
    return canonical_json_bytes({
        **body, "recovery_sha256": _sha(body)})


@dataclass(frozen=True)
class WorldAfterstateV2Recovery:
    """Typed in-memory recovery state returned by :func:`reopen_recovery`."""

    model: WorldAfterstateValueV2
    optimizer: torch.optim.AdamW
    config: WorldAfterstateV2TrainingConfig
    receipt: WorldAfterstateV2EpochReceipt
    score: EpochSelectScoreV2
    metadata: dict[str, Any]
    checkpoint_bytes: bytes


def _rebuild_body(value: dict[str, Any], checkpoint_raw: bytes,
                  config: WorldAfterstateV2TrainingConfig,
                  receipt: WorldAfterstateV2EpochReceipt,
                  score: EpochSelectScoreV2) -> dict[str, Any]:
    return _payload_body(
        checkpoint_raw=checkpoint_raw, config=config, receipt=receipt,
        score=score, optimizer_rows=value["optimizer"]["parameters"],
        metadata=value["metadata"])


def reopen_recovery(
        raw: bytes, *, expected_freeze_sha256: str,
        expected_selection_population_sha256: str) \
        -> WorldAfterstateV2Recovery:
    """Validate and reconstruct a canonical recovery bundle."""
    _digest(expected_freeze_sha256, "expected recovery freeze SHA-256")
    _digest(expected_selection_population_sha256,
            "expected recovery selection population SHA-256")
    value = _strict_json(raw)
    required = {
        "schema", "checkpoint_sha256", "checkpoint_base64", "config",
        "config_sha256", "receipt", "receipt_sha256", "score", "score_sha256",
        "optimizer", "optimizer_state_sha256", "metadata", "authority",
        "recovery_sha256",
    }
    if set(value) != required or value["schema"] != RECOVERY_SCHEMA \
            or value["authority"] != _AUTHORITY:
        raise WorldAfterstateV2RecoveryError("recovery schema/authority drift")
    _digest(value["checkpoint_sha256"], "recovery checkpoint SHA-256")
    _digest(value["config_sha256"], "recovery config SHA-256")
    _digest(value["receipt_sha256"], "recovery receipt SHA-256")
    _digest(value["score_sha256"], "recovery score SHA-256")
    _digest(value["optimizer_state_sha256"],
            "recovery optimizer state SHA-256")
    _digest(value["recovery_sha256"], "recovery SHA-256")
    body = {key: item for key, item in value.items() if key != "recovery_sha256"}
    if value["recovery_sha256"] != _sha(body):
        raise WorldAfterstateV2RecoveryError("recovery reconstruction drift")
    try:
        checkpoint_raw = base64.b64decode(value["checkpoint_base64"], validate=True)
    except (ValueError, TypeError) as exc:
        raise WorldAfterstateV2RecoveryError(
            "recovery checkpoint encoding drift") from exc
    if _sha_bytes(checkpoint_raw) != value["checkpoint_sha256"]:
        raise WorldAfterstateV2RecoveryError("recovery checkpoint binding drift")
    model, checkpoint = reopen_checkpoint(checkpoint_raw)
    if checkpoint_bytes(
            model, seed_block=checkpoint["seed_block"],
            member_index=checkpoint["member_index"],
            control_name=checkpoint["control_name"], init_seed=checkpoint["init_seed"],
            selected_epoch=checkpoint["selected_epoch"],
            freeze_sha256=checkpoint["freeze_sha256"],
            config_sha256=checkpoint["config_sha256"],
            population_sha256=checkpoint["population_sha256"],
            schedule_sha256=checkpoint["schedule_sha256"],
            common_epoch_sha256=checkpoint["common_epoch_sha256"]) != checkpoint_raw:
        raise WorldAfterstateV2RecoveryError("recovery checkpoint re-encoding drift")
    config_payload = value["config"]
    if type(config_payload) is not dict or set(config_payload) != {
            "schema", "learning_rate_ppb", "weight_decay_ppb",
            "gradient_norm_milli", "max_epochs", "sigma_pair_squared"}:
        raise WorldAfterstateV2RecoveryError("recovery config payload drift")
    try:
        config = WorldAfterstateV2TrainingConfig(**config_payload)
        config.validate()
    except Exception as exc:
        raise WorldAfterstateV2RecoveryError("recovery config refused") from exc
    if config.sha256() != value["config_sha256"]:
        raise WorldAfterstateV2RecoveryError("recovery config reconstruction drift")
    receipt_payload = value["receipt"]
    if type(receipt_payload) is not dict or set(receipt_payload) != {
            "schema", "epoch", "batch_count", "example_count", "root_count",
            "mean_root_loss_nano", "config_sha256", "population_sha256",
            "schedule_sha256", "model_state_sha256_before",
            "model_state_sha256_after", "split", "cohort",
            "gradient_norm_nano", "update_norm_nano",
            "prediction_entropy_nano", "paired_target_error_nano",
            "authority"} \
            or receipt_payload["authority"] != {
                "training_launch_authorized": False,
                "audit_opening_authorized": False}:
        raise WorldAfterstateV2RecoveryError("recovery receipt payload drift")
    try:
        receipt = WorldAfterstateV2EpochReceipt(**{
            key: item for key, item in receipt_payload.items() if key != "authority"})
        receipt.validate()
    except Exception as exc:
        raise WorldAfterstateV2RecoveryError("recovery receipt refused") from exc
    if receipt.payload() != receipt_payload or receipt.sha256() != value["receipt_sha256"]:
        raise WorldAfterstateV2RecoveryError("recovery receipt reconstruction drift")
    score_payload = value["score"]
    if type(score_payload) is not dict or set(score_payload) != set(
            EpochSelectScoreV2.__dataclass_fields__):
        raise WorldAfterstateV2RecoveryError("recovery score payload drift")
    try:
        score = EpochSelectScoreV2(**score_payload)
        score.validate()
    except Exception as exc:
        raise WorldAfterstateV2RecoveryError("recovery score refused") from exc
    if score.payload() != score_payload or _sha(score_payload) != value["score_sha256"]:
        raise WorldAfterstateV2RecoveryError("recovery score reconstruction drift")
    metadata = value["metadata"]
    if type(metadata) is not dict or set(metadata) != {
            "freeze_sha256", "seed_block", "member_index", "control_name",
            "init_seed", "completed_epoch", "config_sha256",
            "population_sha256", "schedule_sha256", "common_epoch_sha256",
            "selection_population_sha256"}:
        raise WorldAfterstateV2RecoveryError("recovery identity payload drift")
    _validate_identity(metadata)
    if metadata["freeze_sha256"] != expected_freeze_sha256 \
            or metadata["selection_population_sha256"] \
            != expected_selection_population_sha256 \
            or any(metadata[key] != checkpoint[key]
                   for key in _CHECKPOINT_DIGEST_KEYS) \
            or metadata["seed_block"] != checkpoint["seed_block"] \
            or metadata["member_index"] != checkpoint["member_index"] \
            or metadata["control_name"] != checkpoint["control_name"] \
            or metadata["init_seed"] != checkpoint["init_seed"] \
            or metadata["completed_epoch"] != checkpoint["selected_epoch"]:
        raise WorldAfterstateV2RecoveryError("recovery checkpoint identity drift")
    if (receipt.epoch, receipt.config_sha256, receipt.population_sha256,
            receipt.schedule_sha256, receipt.model_state_sha256_after,
            receipt.cohort) != (
                metadata["completed_epoch"], metadata["config_sha256"],
                metadata["population_sha256"], metadata["schedule_sha256"],
                checkpoint["model_state_sha256"],
                "primary" if metadata["control_name"] == "natural"
                else "control"):
        raise WorldAfterstateV2RecoveryError("recovery receipt/checkpoint binding drift")
    if receipt.epoch > config.max_epochs:
        raise WorldAfterstateV2RecoveryError("recovery epoch/config binding drift")
    if (score.epoch, score.seed_block, score.member_index,
            score.control_name, score.model_state_sha256,
            score.selection_population_sha256) != (
                metadata["completed_epoch"], metadata["seed_block"],
                metadata["member_index"], metadata["control_name"],
                checkpoint["model_state_sha256"],
                metadata["selection_population_sha256"]):
        raise WorldAfterstateV2RecoveryError("recovery score/checkpoint binding drift")
    optimizer_payload = value["optimizer"]
    if type(optimizer_payload) is not dict or set(optimizer_payload) != {
            "algorithm", "parameters"} or optimizer_payload["algorithm"] != "AdamW":
        raise WorldAfterstateV2RecoveryError("recovery optimizer schema drift")
    rows = optimizer_payload["parameters"]
    if value["optimizer_state_sha256"] != _sha(rows):
        raise WorldAfterstateV2RecoveryError(
            "recovery optimizer state reconstruction drift")
    names = list(dict(model.named_parameters()))
    if type(rows) is not list or len(rows) != len(names) \
            or [row.get("name") if type(row) is dict else None for row in rows] != names:
        raise WorldAfterstateV2RecoveryError("recovery optimizer population drift")
    optimizer = new_optimizer(model, config)
    for row, (name, parameter) in zip(rows, model.named_parameters(), strict=True):
        if type(row) is not dict or set(row) != {
                "name", "step", "exp_avg", "exp_avg_sq"}:
            raise WorldAfterstateV2RecoveryError("recovery optimizer state drift")
        step = _decode_tensor(row["step"], label=f"optimizer {name} step",
                              expected_shape=(), expected_dtype=None)
        if float(step) < 1 or not float(step).is_integer():
            raise WorldAfterstateV2RecoveryError("recovery optimizer step drift")
        avg = _decode_tensor(row["exp_avg"], label=f"optimizer {name} exp_avg",
                             expected_shape=tuple(parameter.shape),
                             expected_dtype=parameter.dtype)
        sq = _decode_tensor(row["exp_avg_sq"], label=f"optimizer {name} exp_avg_sq",
                            expected_shape=tuple(parameter.shape),
                            expected_dtype=parameter.dtype)
        optimizer.state[parameter] = {"step": step, "exp_avg": avg,
                                      "exp_avg_sq": sq}
    if _rebuild_body(value, checkpoint_raw, config, receipt, score) != body:
        raise WorldAfterstateV2RecoveryError("recovery payload re-encoding drift")
    return WorldAfterstateV2Recovery(
        model=model, optimizer=optimizer, config=config, receipt=receipt,
        score=score, metadata=dict(metadata), checkpoint_bytes=checkpoint_raw)


__all__ = [
    "RECOVERY_SCHEMA", "WorldAfterstateV2Recovery",
    "WorldAfterstateV2RecoveryError", "recovery_bytes", "reopen_recovery",
]
