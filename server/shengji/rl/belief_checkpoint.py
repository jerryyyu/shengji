"""Canonical in-memory BELIEF-V1 model checkpoint package and reopener.

PyTorch's general-purpose serialization is not the evidence format.  A B2
checkpoint stores one strict canonical manifest plus ordered raw little-endian
float32 parameter blocks.  It binds the fixed protocol, initialization seed,
selected epoch, final epoch receipt, exact parameter names/shapes/hashes, and
the independent state-stream digest.  Reopening reconstructs the frozen model
architecture and byte-compares the state digest.

The package contains trained weights but no corpus row, privileged target,
optimizer/resume state, filesystem path, policy, sampler, outcome, or execution
authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch

from .belief_b2_protocol import TRAIN_MAX_EPOCHS, protocol_sha256
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_model import (MODEL_SCHEMA, HistoryOwnershipModelV1,
                           new_from_scratch_model)
from .belief_trainer import (EpochTrainingReceiptV1, model_state_sha256)


CHECKPOINT_MANIFEST_SCHEMA = "belief-v1-history-ownership-checkpoint-v1"


class BeliefCheckpointError(ValueError):
    """A B2 checkpoint manifest or parameter byte stream drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _reject_number(value: str) -> None:
    raise BeliefCheckpointError(f"checkpoint contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefCheckpointError("checkpoint manifest has duplicate key")
        result[key] = value
    return result


def _strict_manifest(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise BeliefCheckpointError("checkpoint manifest must be nonempty bytes")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefCheckpointError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefCheckpointError("checkpoint manifest is not strict JSON") \
            from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise BeliefCheckpointError("checkpoint manifest is not canonical")
    return payload


@dataclass(frozen=True)
class FrozenModelCheckpointV1:
    manifest_bytes: bytes
    parameter_blocks: tuple[bytes, ...]

    def sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(len(self.manifest_bytes).to_bytes(8, "big"))
        digest.update(self.manifest_bytes)
        for block in self.parameter_blocks:
            digest.update(len(block).to_bytes(8, "big"))
            digest.update(block)
        return digest.hexdigest()


def build_model_checkpoint(
        model: HistoryOwnershipModelV1, *, initialization_seed: int,
        selected_epoch: int,
        final_epoch_receipt: EpochTrainingReceiptV1) \
        -> FrozenModelCheckpointV1:
    if initialization_seed not in COHORT_SEEDS \
            or type(initialization_seed) is not int \
            or type(selected_epoch) is not int \
            or not 1 <= selected_epoch <= TRAIN_MAX_EPOCHS \
            or type(final_epoch_receipt) is not EpochTrainingReceiptV1 \
            or final_epoch_receipt.epoch != selected_epoch \
            or final_epoch_receipt.model_state_sha256_after \
            != model_state_sha256(model):
        raise BeliefCheckpointError("checkpoint training identity drift")
    rows = []
    blocks = []
    for name, parameter in model.named_parameters():
        if parameter.device.type != "cpu" or parameter.dtype != torch.float32:
            raise BeliefCheckpointError("checkpoint parameter device/dtype drift")
        array = parameter.detach().contiguous().numpy().astype(
            "<f4", copy=False)
        raw = array.tobytes(order="C")
        blocks.append(raw)
        rows.append({
            "name": name,
            "shape": list(array.shape),
            "dtype": "little-endian-float32",
            "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    manifest = {
        "schema": CHECKPOINT_MANIFEST_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "model_schema": MODEL_SCHEMA,
        "initialization_seed": initialization_seed,
        "selected_epoch": selected_epoch,
        "final_epoch_receipt_sha256": final_epoch_receipt.sha256(),
        "model_state_sha256": model_state_sha256(model),
        "parameters": rows,
        "contains_corpus_rows": False,
        "contains_privileged_targets": False,
        "contains_optimizer_resume_state": False,
        "runtime_research_package": True,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    checkpoint = FrozenModelCheckpointV1(
        manifest_bytes=canonical_json_bytes(manifest),
        parameter_blocks=tuple(blocks))
    validate_model_checkpoint(
        checkpoint, final_epoch_receipt=final_epoch_receipt)
    return checkpoint


def validate_model_checkpoint(
        checkpoint: FrozenModelCheckpointV1, *,
        final_epoch_receipt: EpochTrainingReceiptV1) -> None:
    if type(checkpoint) is not FrozenModelCheckpointV1 \
            or type(checkpoint.parameter_blocks) is not tuple \
            or not checkpoint.parameter_blocks \
            or any(type(block) is not bytes or not block
                   for block in checkpoint.parameter_blocks) \
            or type(final_epoch_receipt) is not EpochTrainingReceiptV1:
        raise BeliefCheckpointError("checkpoint package population drift")
    payload = _strict_manifest(checkpoint.manifest_bytes)
    expected_keys = {
        "schema", "protocol_sha256", "model_schema", "initialization_seed",
        "selected_epoch", "final_epoch_receipt_sha256",
        "model_state_sha256", "parameters", "contains_corpus_rows",
        "contains_privileged_targets", "contains_optimizer_resume_state",
        "runtime_research_package", "gameplay_authorized",
        "strength_claim_authorized", "deployment_authorized",
    }
    if set(payload) != expected_keys \
            or payload["schema"] != CHECKPOINT_MANIFEST_SCHEMA \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["model_schema"] != MODEL_SCHEMA \
            or type(payload["initialization_seed"]) is not int \
            or payload["initialization_seed"] not in COHORT_SEEDS \
            or type(payload["selected_epoch"]) is not int \
            or not 1 <= payload["selected_epoch"] <= TRAIN_MAX_EPOCHS \
            or payload["selected_epoch"] != final_epoch_receipt.epoch \
            or payload["final_epoch_receipt_sha256"] \
            != final_epoch_receipt.sha256() \
            or not _is_sha256(payload["model_state_sha256"]) \
            or payload["contains_corpus_rows"] is not False \
            or payload["contains_privileged_targets"] is not False \
            or payload["contains_optimizer_resume_state"] is not False \
            or payload["runtime_research_package"] is not True \
            or any(payload[key] is not False for key in (
                "gameplay_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefCheckpointError("checkpoint manifest identity/authority drift")
    parameters = payload["parameters"]
    if type(parameters) is not list \
            or len(parameters) != len(checkpoint.parameter_blocks):
        raise BeliefCheckpointError("checkpoint parameter population drift")
    prototype = new_from_scratch_model(payload["initialization_seed"])
    expected = tuple(prototype.named_parameters())
    if len(expected) != len(parameters):
        raise BeliefCheckpointError("checkpoint architecture population drift")
    for row, raw, (name, parameter) in zip(
            parameters, checkpoint.parameter_blocks, expected, strict=True):
        if type(row) is not dict or set(row) != {
                "name", "shape", "dtype", "byte_count", "sha256"} \
                or row["name"] != name \
                or row["shape"] != list(parameter.shape) \
                or row["dtype"] != "little-endian-float32" \
                or type(row["byte_count"]) is not int \
                or row["byte_count"] != len(raw) \
                or len(raw) != parameter.numel() * 4 \
                or row["sha256"] != hashlib.sha256(raw).hexdigest():
            raise BeliefCheckpointError("checkpoint parameter binding drift")


def reopen_model_checkpoint(
        checkpoint: FrozenModelCheckpointV1, *,
        final_epoch_receipt: EpochTrainingReceiptV1) \
        -> HistoryOwnershipModelV1:
    validate_model_checkpoint(
        checkpoint, final_epoch_receipt=final_epoch_receipt)
    payload = _strict_manifest(checkpoint.manifest_bytes)
    model = new_from_scratch_model(payload["initialization_seed"])
    with torch.no_grad():
        for raw, (_, parameter) in zip(
                checkpoint.parameter_blocks, model.named_parameters(),
                strict=True):
            array = np.frombuffer(raw, dtype="<f4").reshape(
                tuple(parameter.shape)).copy()
            parameter.copy_(torch.from_numpy(array))
    if model_state_sha256(model) != payload["model_state_sha256"] \
            or final_epoch_receipt.model_state_sha256_after \
            != payload["model_state_sha256"]:
        raise BeliefCheckpointError("checkpoint state reconstruction drift")
    return model
