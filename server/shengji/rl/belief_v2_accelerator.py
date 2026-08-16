"""Device-neutral BELIEF-V1 V2 training boundary.

V1 remains CPU-pinned.  V2 may train the same exact model and batches on a
reviewed CPU, MPS, or indexed CUDA device, while checkpoint identity is always
defined over a canonical CPU float32 byte stream.  A batch is transferred once
before it is shared by all eight cohort members.

This module selects no device, performs no benchmark, reads no corpus, writes
no checkpoint, and grants no training or execution authority.
"""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass, fields, replace
from typing import Any, Iterable

import torch

from .belief_b2_protocol import TRAIN_LEARNING_RATE, TRAIN_WEIGHT_DECAY
from .belief_contract import canonical_json_bytes
from .belief_model import HistoryOwnershipModelV1, new_from_scratch_model
from .belief_trainer import (
    CHECKPOINT_SCHEMA,
    EpochTrainingReceiptV1,
    _evaluate_calibration_cohort_stream_nanonats,
    _train_cohort_epoch_stream,
)
from .belief_training import BeliefTrainingBatchV1


TRAINING_TENSOR_FIELDS = tuple(
    field.name for field in fields(BeliefTrainingBatchV1)
    if field.type == "torch.Tensor")
TRAINING_DEVICE_PROFILE_SCHEMA = "belief-v1-v2-training-device-profile-v1"


class BeliefV2AcceleratorError(ValueError):
    """The selected device, batch transfer, or checkpoint binding drifted."""


@dataclass(frozen=True)
class V2TrainingDeviceProfileV1:
    """Exact accelerator identity bound into the host-specific freeze.

    The normal runtime profile already binds the host, OS, Torch bytes, and
    Torch build configuration.  This companion profile closes the remaining
    device-specific gap for MPS/CUDA execution.  It deliberately records no
    benchmark result and grants no training authority.
    """

    requested_device: str
    device_type: str
    device_index: int | None
    hardware_name: str
    total_memory_bytes: int
    runtime_version: str
    compute_capability_major: int | None
    compute_capability_minor: int | None
    backend_built: bool = True
    backend_available: bool = True
    schema: str = TRAINING_DEVICE_PROFILE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "requested_device": self.requested_device,
            "device_type": self.device_type,
            "device_index": self.device_index,
            "hardware_name": self.hardware_name,
            "total_memory_bytes": self.total_memory_bytes,
            "runtime_version": self.runtime_version,
            "compute_capability_major": self.compute_capability_major,
            "compute_capability_minor": self.compute_capability_minor,
            "backend_built": self.backend_built,
            "backend_available": self.backend_available,
        }

    def sha256(self) -> str:
        validate_training_device_profile(self)
        return hashlib.sha256(canonical_json_bytes(self.to_dict())).hexdigest()


def canonical_training_device(value: str) -> str:
    """Return one exact supported device name without implicit defaults."""
    if type(value) is not str or not value:
        raise BeliefV2AcceleratorError("V2 training device is invalid")
    try:
        device = torch.device(value)
    except (RuntimeError, ValueError) as exc:
        raise BeliefV2AcceleratorError(
            "V2 training device is invalid") from exc
    if str(device) != value or device.type not in {"cpu", "mps", "cuda"} \
            or (device.type in {"cpu", "mps"} and device.index is not None) \
            or (device.type == "cuda" and device.index is None):
        raise BeliefV2AcceleratorError(
            "V2 training device must be cpu, mps, or indexed cuda")
    return value


def require_training_device(value: str) -> torch.device:
    """Resolve an exact device and fail if this runtime cannot execute it."""
    name = canonical_training_device(value)
    device = torch.device(name)
    available = device.type == "cpu"
    if device.type == "mps":
        available = bool(torch.backends.mps.is_built()) \
            and bool(torch.backends.mps.is_available())
    elif device.type == "cuda":
        available = bool(torch.cuda.is_available()) \
            and device.index is not None \
            and device.index < torch.cuda.device_count()
    if not available:
        raise BeliefV2AcceleratorError(
            "V2 training device is unavailable")
    if not torch.are_deterministic_algorithms_enabled():
        raise BeliefV2AcceleratorError(
            "V2 deterministic algorithms are not enabled")
    return device


def validate_training_device_profile(
        profile: V2TrainingDeviceProfileV1) -> None:
    """Validate one exact, available, non-CPU accelerator identity."""
    if type(profile) is not V2TrainingDeviceProfileV1 \
            or profile.schema != TRAINING_DEVICE_PROFILE_SCHEMA:
        raise BeliefV2AcceleratorError(
            "V2 training device profile identity drift")
    requested = canonical_training_device(profile.requested_device)
    parsed = torch.device(requested)
    capability = (
        profile.compute_capability_major,
        profile.compute_capability_minor)
    expected_capability_shape = (
        all(type(value) is int and value >= 0 for value in capability)
        if parsed.type == "cuda" else capability == (None, None))
    if requested == "cpu" \
            or profile.device_type != parsed.type \
            or profile.device_index != parsed.index \
            or type(profile.hardware_name) is not str \
            or not profile.hardware_name \
            or type(profile.total_memory_bytes) is not int \
            or profile.total_memory_bytes <= 0 \
            or type(profile.runtime_version) is not str \
            or not profile.runtime_version \
            or profile.backend_built is not True \
            or profile.backend_available is not True \
            or not expected_capability_shape:
        raise BeliefV2AcceleratorError(
            "V2 training device profile identity drift")


def build_training_device_profile(
        requested_device: str) -> V2TrainingDeviceProfileV1:
    """Probe the exact accelerator selected for the future qualification."""
    device = require_training_device(requested_device)
    if device.type == "cpu":
        raise BeliefV2AcceleratorError(
            "V2 training device profile requires an accelerator")
    if device.type == "mps":
        memory = int(torch.mps.recommended_max_memory())
        profile = V2TrainingDeviceProfileV1(
            requested_device=str(device), device_type="mps",
            device_index=None,
            hardware_name=(
                f"Apple-{platform.machine()}-{platform.processor() or 'unknown'}"),
            total_memory_bytes=memory,
            runtime_version=f"macOS-{platform.mac_ver()[0]}",
            compute_capability_major=None,
            compute_capability_minor=None,
            backend_built=bool(torch.backends.mps.is_built()),
            backend_available=bool(torch.backends.mps.is_available()))
    elif device.type == "cuda":
        assert device.index is not None
        properties = torch.cuda.get_device_properties(device.index)
        profile = V2TrainingDeviceProfileV1(
            requested_device=str(device), device_type="cuda",
            device_index=device.index,
            hardware_name=str(properties.name),
            total_memory_bytes=int(properties.total_memory),
            runtime_version=f"CUDA-{torch.version.cuda or 'unknown'}",
            compute_capability_major=int(properties.major),
            compute_capability_minor=int(properties.minor),
            backend_built=True,
            backend_available=bool(torch.cuda.is_available()))
    else:  # pragma: no cover - canonical_training_device closes this branch.
        raise BeliefV2AcceleratorError(
            "V2 training device profile type drift")
    validate_training_device_profile(profile)
    return profile


def _model_device(model: HistoryOwnershipModelV1) -> torch.device:
    if type(model) is not HistoryOwnershipModelV1:
        raise BeliefV2AcceleratorError("V2 training model identity drift")
    parameters = tuple(model.parameters())
    devices = {parameter.device for parameter in parameters}
    if not parameters or len(devices) != 1 \
            or any(parameter.dtype != torch.float32
                   for parameter in parameters):
        raise BeliefV2AcceleratorError(
            "V2 training model device/dtype drift")
    return next(iter(devices))


def move_models_to_device(
        models: tuple[HistoryOwnershipModelV1, ...], *,
        device: str) -> tuple[HistoryOwnershipModelV1, ...]:
    """Move an exact model population to one already-available device."""
    target = require_training_device(device)
    if type(models) is not tuple or not models \
            or len({id(model) for model in models}) != len(models):
        raise BeliefV2AcceleratorError("V2 model population drift")
    for model in models:
        _model_device(model)
    for model in models:
        model.to(device=target, dtype=torch.float32)
        if _model_device(model) != target:
            raise BeliefV2AcceleratorError("V2 model transfer drift")
    return models


def portable_model_state_sha256(model: HistoryOwnershipModelV1) -> str:
    """Hash device state through the exact canonical CPU checkpoint stream."""
    _model_device(model)
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({
        "schema": CHECKPOINT_SCHEMA,
        "parameter_names": [name for name, _ in model.named_parameters()],
    }))
    for name, parameter in model.named_parameters():
        value = parameter.detach().to(
            device="cpu", dtype=torch.float32, copy=True).contiguous()
        header = canonical_json_bytes({
            "name": name,
            "shape": list(value.shape),
            "dtype": "float32",
            "byte_count": value.numel() * value.element_size(),
        })
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        raw = value.view(torch.uint8).numpy().tobytes(order="C")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def cpu_checkpoint_clone(
        model: HistoryOwnershipModelV1) -> HistoryOwnershipModelV1:
    """Copy one trained device model into the unchanged CPU checkpoint type."""
    expected = portable_model_state_sha256(model)
    state = {name: value.detach().to(
        device="cpu", dtype=torch.float32, copy=True).contiguous()
             for name, value in model.state_dict().items()}
    clone = new_from_scratch_model(0)
    clone.load_state_dict(state, strict=True)
    if portable_model_state_sha256(clone) != expected:
        raise BeliefV2AcceleratorError(
            "V2 canonical CPU checkpoint export drift")
    return clone


def move_training_batch_to_device(
        batch: BeliefTrainingBatchV1, *, device: str) \
        -> BeliefTrainingBatchV1:
    """Transfer every and only tensor field while preserving batch identity."""
    target = require_training_device(device)
    if type(batch) is not BeliefTrainingBatchV1:
        raise BeliefV2AcceleratorError("V2 training batch identity drift")
    tensor_fields = tuple(
        field.name for field in fields(batch)
        if isinstance(getattr(batch, field.name), torch.Tensor))
    if tensor_fields != TRAINING_TENSOR_FIELDS:
        raise BeliefV2AcceleratorError(
            "V2 training tensor field population drift")
    moved = replace(batch, **{
        name: getattr(batch, name).to(
            device=target, non_blocking=False, copy=False)
        for name in tensor_fields
    })
    if any(getattr(moved, name).device != target
           for name in tensor_fields) \
            or any(getattr(moved, field.name) != getattr(batch, field.name)
                   for field in fields(batch)
                   if field.name not in tensor_fields):
        raise BeliefV2AcceleratorError("V2 training batch transfer drift")
    return moved


def new_v2_optimizer(model: HistoryOwnershipModelV1) -> torch.optim.AdamW:
    """Build the unchanged optimizer on the model's exact selected device."""
    _model_device(model)
    return torch.optim.AdamW(
        model.parameters(), lr=float(TRAIN_LEARNING_RATE),
        weight_decay=float(TRAIN_WEIGHT_DECAY), foreach=False, fused=False)


def train_v2_cohort_epoch_stream(
        models: tuple[HistoryOwnershipModelV1, ...],
        optimizers: tuple[torch.optim.Optimizer, ...],
        batches: Iterable[BeliefTrainingBatchV1], *,
        epoch: int, device: str) -> tuple[EpochTrainingReceiptV1, ...]:
    """Transfer each batch once and train the complete cohort on one device."""
    target = require_training_device(device)
    if type(models) is not tuple or not models \
            or any(_model_device(model) != target for model in models):
        raise BeliefV2AcceleratorError("V2 cohort device drift")
    moved = (move_training_batch_to_device(batch, device=device)
             for batch in batches)
    return _train_cohort_epoch_stream(
        models, optimizers, moved, epoch=epoch,
        state_sha256=portable_model_state_sha256)


def evaluate_v2_calibration_cohort_stream_nanonats(
        models: tuple[HistoryOwnershipModelV1, ...],
        batches: Iterable[BeliefTrainingBatchV1], *,
        device: str) -> tuple[int, ...]:
    """Evaluate the complete cohort on the same exact selected device."""
    target = require_training_device(device)
    if type(models) is not tuple or not models \
            or any(_model_device(model) != target for model in models):
        raise BeliefV2AcceleratorError("V2 cohort device drift")
    moved = (move_training_batch_to_device(batch, device=device)
             for batch in batches)
    return _evaluate_calibration_cohort_stream_nanonats(
        models, moved, state_sha256=portable_model_state_sha256)
