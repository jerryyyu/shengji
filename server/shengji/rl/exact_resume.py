"""Fail-closed checkpoints for quiescent synchronous RL learners.

This module deliberately does not checkpoint in-flight actor work.  An exact
resume boundary has ``pending_jobs == 0`` and binds all state that can affect
the next learner update: learner and optimizer state, replay-ring layout,
named RNG streams, progress counters, and immutable actor/candidate bytes.
"""
from __future__ import annotations

import copy
import hashlib
import os
import platform
import random
import struct
import sys
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .selfplay_contract import CheckpointRef, sha256_file


EXACT_RESUME_SCHEMA = "shengji-synchronous-exact-resume-v1"
REPLAY_RING_SCHEMA = "shengji-replay-ring-v1"
RNG_STREAMS_SCHEMA = "shengji-resume-rng-streams-v1"


class ResumeContractError(RuntimeError):
    """The checkpoint cannot prove an exact next learner transition."""


class ResumeRollbackError(ResumeContractError):
    """Restore and rollback both failed; the caller must terminate."""


def _type_name(value: object) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _frame(digest: Any, tag: bytes, payload: bytes = b"") -> None:
    digest.update(struct.pack(">Q", len(tag)))
    digest.update(tag)
    digest.update(struct.pack(">Q", len(payload)))
    digest.update(payload)


def _digest_value(digest: Any, value: Any) -> None:
    """Hash supported state by value rather than by pickle representation."""
    if value is None:
        _frame(digest, b"none")
    elif isinstance(value, bool):
        _frame(digest, b"bool", b"1" if value else b"0")
    elif isinstance(value, np.generic):
        scalar = np.asarray(value)
        _frame(digest, b"numpy-scalar-dtype", scalar.dtype.str.encode())
        _frame(digest, b"numpy-scalar", scalar.tobytes())
    elif isinstance(value, int):
        _frame(digest, b"int", str(value).encode("ascii"))
    elif isinstance(value, float):
        _frame(digest, b"float", struct.pack(">d", value))
    elif isinstance(value, str):
        _frame(digest, b"str", value.encode("utf-8"))
    elif isinstance(value, bytes):
        _frame(digest, b"bytes", value)
    elif isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise TypeError("object-dtype arrays are not valid resume state")
        array = np.ascontiguousarray(value)
        _frame(digest, b"numpy-dtype", array.dtype.str.encode())
        _frame(digest, b"numpy-shape", repr(array.shape).encode("ascii"))
        _frame(digest, b"numpy-strides", repr(value.strides).encode("ascii"))
        _frame(digest, b"numpy-array", array.tobytes())
    elif isinstance(value, torch.Tensor):
        if value.layout != torch.strided:
            raise TypeError("only strided tensors are valid resume state")
        tensor = value.detach().cpu().contiguous().reshape(-1)
        raw = tensor.view(torch.uint8).numpy().tobytes()
        _frame(digest, b"torch-dtype", str(value.dtype).encode("ascii"))
        _frame(digest, b"torch-shape", repr(tuple(value.shape)).encode("ascii"))
        _frame(digest, b"torch-device", str(value.device).encode("ascii"))
        _frame(digest, b"torch-layout", str(value.layout).encode("ascii"))
        _frame(digest, b"torch-stride", repr(value.stride()).encode("ascii"))
        _frame(digest, b"torch-grad",
               b"1" if value.requires_grad else b"0")
        _frame(digest, b"torch-tensor", raw)
    elif isinstance(value, Mapping):
        encoded_keys: list[tuple[str, Any]] = []
        for key in value:
            key_digest = state_digest(key)
            encoded_keys.append((key_digest, key))
        _frame(digest, b"mapping", str(len(encoded_keys)).encode("ascii"))
        for key_digest, key in sorted(encoded_keys, key=lambda item: item[0]):
            _frame(digest, b"mapping-key", key_digest.encode("ascii"))
            _digest_value(digest, value[key])
    elif isinstance(value, tuple):
        _frame(digest, b"tuple", str(len(value)).encode("ascii"))
        for item in value:
            _digest_value(digest, item)
    elif isinstance(value, list):
        _frame(digest, b"list", str(len(value)).encode("ascii"))
        for item in value:
            _digest_value(digest, item)
    else:
        raise TypeError(
            f"unsupported resume-state value {_type_name(value)}")


def state_digest(value: Any) -> str:
    """Return a deterministic digest for the supported checkpoint state."""
    digest = hashlib.sha256()
    _digest_value(digest, value)
    return digest.hexdigest()


def _require_exact_keys(value: object, expected: set[str], label: str) -> None:
    if not isinstance(value, Mapping):
        raise ResumeContractError(f"{label} must be a mapping")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ResumeContractError(
            f"{label} fields mismatch: missing={missing}, extra={extra}")


def _require_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResumeContractError(f"{label} must be a nonnegative integer")
    return value


def _require_sha256(value: object, label: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ResumeContractError(f"{label} must be a lowercase SHA-256")
    return value


def _runtime_identity() -> dict[str, Any]:
    """Capture the numerical execution context relevant to the next update."""
    numpy_config = copy.deepcopy(getattr(np.__config__, "CONFIG", {}))
    cuda_devices = []
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            cuda_devices.append({
                "index": index,
                "name": properties.name,
                "capability": list(torch.cuda.get_device_capability(index)),
                "total_memory": int(properties.total_memory),
                "multi_processor_count": int(
                    properties.multi_processor_count),
            })
    cpu_backend = getattr(torch.backends, "cpu", None)
    cpu_capability = None
    if cpu_backend is not None \
            and hasattr(cpu_backend, "get_cpu_capability"):
        cpu_capability = cpu_backend.get_cpu_capability()
    deterministic_warn_only = False
    if hasattr(torch, "is_deterministic_algorithms_warn_only_enabled"):
        deterministic_warn_only = \
            torch.is_deterministic_algorithms_warn_only_enabled()
    default_device = "cpu"
    if hasattr(torch, "get_default_device"):
        default_device = str(torch.get_default_device())
    mps_backend = getattr(torch.backends, "mps", None)
    return {
        "schema": "shengji-numerical-runtime-v1",
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "full_version": sys.version,
            "byteorder": sys.byteorder,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "numpy": {
            "version": np.__version__,
            "build_sha256": state_digest(numpy_config),
        },
        "torch": {
            "version": str(torch.__version__),
            "git_version": getattr(torch.version, "git_version", None),
            "cuda_build": getattr(torch.version, "cuda", None),
            "hip_build": getattr(torch.version, "hip", None),
            "build_sha256": hashlib.sha256(
                torch.__config__.show().encode("utf-8")).hexdigest(),
        },
        "settings": {
            "deterministic_algorithms":
                torch.are_deterministic_algorithms_enabled(),
            "deterministic_warn_only": deterministic_warn_only,
            "default_dtype": str(torch.get_default_dtype()),
            "default_device": default_device,
            "float32_matmul_precision":
                torch.get_float32_matmul_precision(),
            "num_threads": torch.get_num_threads(),
            "num_interop_threads": torch.get_num_interop_threads(),
            "cudnn_enabled": bool(torch.backends.cudnn.enabled),
            "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
            "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
            "cudnn_allow_tf32": bool(torch.backends.cudnn.allow_tf32),
            "mkldnn_enabled": bool(torch.backends.mkldnn.enabled),
            "mkldnn_deterministic": bool(
                getattr(torch.backends.mkldnn, "deterministic", False)),
        },
        "devices": {
            "cpu_capability": cpu_capability,
            "cuda_available": torch.cuda.is_available(),
            "cuda_devices": cuda_devices,
            "mps_built": bool(mps_backend and mps_backend.is_built()),
            "mps_available": bool(
                mps_backend and mps_backend.is_available()),
        },
        "environment": {
            name: os.environ.get(name)
            for name in (
                "CUBLAS_WORKSPACE_CONFIG",
                "MKL_NUM_THREADS",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "PYTHONHASHSEED",
                "PYTORCH_ENABLE_MPS_FALLBACK",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
    }


def _validate_deterministic_runtime(runtime: object) -> None:
    if not isinstance(runtime, Mapping):
        raise ResumeContractError("runtime identity must be a mapping")
    settings = runtime.get("settings")
    if not isinstance(settings, Mapping):
        raise ResumeContractError("runtime settings must be a mapping")
    if settings.get("deterministic_algorithms") is not True:
        raise ResumeContractError(
            "exact resume requires Torch deterministic algorithms")
    if settings.get("deterministic_warn_only") is not False:
        raise ResumeContractError(
            "exact resume refuses deterministic warn-only mode")


def _tensor_schema(name: str, tensor: torch.Tensor, *,
                   requires_grad: bool) -> dict[str, Any]:
    if not isinstance(tensor, torch.Tensor):
        raise ResumeContractError(
            f"learner state {name!r} is not a tensor")
    stride = None
    if tensor.layout == torch.strided:
        stride = list(tensor.stride())
    return {
        "name": name,
        "shape": list(tensor.shape),
        "dtype": str(tensor.dtype),
        "device": str(tensor.device),
        "layout": str(tensor.layout),
        "stride": stride,
        "requires_grad": requires_grad,
    }


_MODULE_CONTAINER_ATTRIBUTES = {
    "training",
    "_parameters",
    "_buffers",
    "_non_persistent_buffers_set",
    "_modules",
}
_MODULE_HOOK_ATTRIBUTES = {
    "_backward_pre_hooks",
    "_backward_hooks",
    "_forward_hooks",
    "_forward_hooks_with_kwargs",
    "_forward_hooks_always_called",
    "_forward_pre_hooks",
    "_forward_pre_hooks_with_kwargs",
    "_state_dict_hooks",
    "_state_dict_pre_hooks",
    "_load_state_dict_pre_hooks",
    "_load_state_dict_post_hooks",
}
_RNN_DERIVED_CACHE_ATTRIBUTES = {
    "_flat_weight_refs",
    "_flat_weights",
}
_OPTIMIZER_CONTAINER_ATTRIBUTES = {
    "state",
    "param_groups",
}
_OPTIMIZER_HOOK_ATTRIBUTES = {
    "_optimizer_step_pre_hooks",
    "_optimizer_step_post_hooks",
    "_optimizer_state_dict_pre_hooks",
    "_optimizer_state_dict_post_hooks",
    "_optimizer_load_state_dict_pre_hooks",
    "_optimizer_load_state_dict_post_hooks",
}
_OPTIMIZER_DERIVED_CACHE_ATTRIBUTES = {
    "_warned_capturable_if_run_uncaptured",
}


def _reject_nested_module_references(value: Any, *, label: str,
                                     seen: set[int] | None = None) -> None:
    """Refuse hidden state that belongs in a registered module/state_dict."""
    if isinstance(value, (torch.Tensor, torch.nn.Module,
                          weakref.ReferenceType, *weakref.ProxyTypes)):
        raise ResumeContractError(
            f"unregistered nested tensor/module/reference in {label}")
    if not isinstance(value, (Mapping, list, tuple)):
        return
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        raise ResumeContractError(f"cyclic Python module attribute in {label}")
    seen.add(identity)
    try:
        if isinstance(value, Mapping):
            for key, item in value.items():
                _reject_nested_module_references(
                    key, label=label, seen=seen)
                _reject_nested_module_references(
                    item, label=label, seen=seen)
        else:
            for item in value:
                _reject_nested_module_references(
                    item, label=label, seen=seen)
    finally:
        seen.remove(identity)


def _is_proven_derived_module_cache(module: torch.nn.Module,
                                    attribute: str) -> bool:
    # RNNBase rebuilds these references from its registered parameters.  They
    # must not be value-bound before tensor restore, but the constructor fields,
    # `_flat_weights_names`, and `_all_weights` remain in the config schema.
    return isinstance(module, torch.nn.modules.rnn.RNNBase) \
        and attribute in _RNN_DERIVED_CACHE_ATTRIBUTES


def optimizer_config_schema(
        optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    """Bind optimizer Python configuration outside ``state_dict()``.

    Parameter groups and per-parameter state are persisted by PyTorch.  Hooks
    are refused, the warning-only capturable cache is explicitly ignored, and
    every other instance attribute must be deterministic configuration without
    hidden tensors, modules, or object references.
    """
    active_hooks = sorted(
        attribute for attribute in _OPTIMIZER_HOOK_ATTRIBUTES
        if optimizer.__dict__.get(attribute))
    if active_hooks:
        raise ResumeContractError(
            f"optimizer hooks are unsupported for exact resume: {active_hooks}")
    config = {}
    for attribute, value in sorted(optimizer.__dict__.items()):
        if attribute in _OPTIMIZER_CONTAINER_ATTRIBUTES \
                or attribute in _OPTIMIZER_HOOK_ATTRIBUTES \
                or attribute in _OPTIMIZER_DERIVED_CACHE_ATTRIBUTES:
            continue
        try:
            label = f"optimizer attribute {attribute!r}"
            _reject_nested_module_references(value, label=label)
            copied = copy.deepcopy(value)
            state_digest(copied)
        except ResumeContractError:
            raise
        except Exception as exc:
            raise ResumeContractError(
                f"unsupported Python optimizer attribute {attribute!r}: "
                f"{_type_name(value)}") from exc
        config[attribute] = copied
    schema = {
        "schema": "shengji-optimizer-config-v1",
        "type": _type_name(optimizer),
        "config": config,
    }
    state_digest(schema)
    return schema


def learner_module_config_schema(learner: torch.nn.Module) -> dict[str, Any]:
    """Bind Python-side module topology and configuration by value.

    ``state_dict()`` covers registered parameters and persistent buffers, but
    not stateless submodule types, constructor options, or arbitrary mutable
    attributes.  Those values can change the very next forward/update.  Exact
    resume therefore records every remaining supported instance attribute and
    refuses hooks, non-persistent buffers, and values that cannot be hashed by
    the checkpoint's deterministic state codec.

    The schema is a validation contract, not a second serializer.  A resumed
    learner must be constructed with the same Python-side configuration before
    its tensor state is restored.
    """
    modules_by_identity: dict[int, dict[str, Any]] = {}
    for name, module in learner.named_modules(remove_duplicate=False):
        identity = id(module)
        if identity not in modules_by_identity:
            modules_by_identity[identity] = {
                "module": module,
                "names": [],
            }
        modules_by_identity[identity]["names"].append(name)

    modules = []
    for entry in modules_by_identity.values():
        module = entry["module"]
        names = entry["names"]
        non_persistent = module.__dict__.get(
            "_non_persistent_buffers_set", set())
        if non_persistent:
            raise ResumeContractError(
                f"non-persistent buffers are unsupported for module {names}")
        active_hooks = sorted(
            attribute for attribute in _MODULE_HOOK_ATTRIBUTES
            if module.__dict__.get(attribute))
        if active_hooks:
            raise ResumeContractError(
                f"module hooks are unsupported for exact resume at {names}: "
                f"{active_hooks}")

        config = {}
        for attribute, value in sorted(module.__dict__.items()):
            if attribute in _MODULE_CONTAINER_ATTRIBUTES \
                    or attribute in _MODULE_HOOK_ATTRIBUTES:
                continue
            if _is_proven_derived_module_cache(module, attribute):
                continue
            try:
                label = f"attribute {attribute!r} for module {names}"
                _reject_nested_module_references(value, label=label)
                copied = copy.deepcopy(value)
                state_digest(copied)
            except ResumeContractError:
                raise
            except Exception as exc:
                raise ResumeContractError(
                    f"unsupported Python module attribute {attribute!r} for "
                    f"module {names}: {_type_name(value)}") from exc
            config[attribute] = copied
        modules.append({
            "names": names,
            "type": _type_name(module),
            "training": module.training,
            "config": config,
        })
    schema = {
        "schema": "shengji-learner-module-config-v1",
        "modules": modules,
    }
    # Keep this public helper fail-closed if a future edit adds an unsupported
    # value to the schema itself.
    state_digest(schema)
    return schema


def learner_resume_schema(learner: torch.nn.Module,
                          optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    """Bind tensor schema and optimizer-to-parameter topology by name."""
    parameters = list(learner.named_parameters(remove_duplicate=False))
    buffers = list(learner.named_buffers(remove_duplicate=False))
    live_gradients = sorted(
        name for name, parameter in parameters if parameter.grad is not None)
    if live_gradients:
        raise ResumeContractError(
            "exact resume requires a gradient-free learner boundary: "
            f"{live_gradients}")
    state = learner.state_dict()
    non_tensor_state = [
        name for name, value in state.items()
        if not isinstance(value, torch.Tensor)
    ]
    if non_tensor_state:
        raise ResumeContractError(
            "non-tensor learner state is unsupported: "
            f"{non_tensor_state}")
    state_keys = set(state)
    absent = sorted(
        name for name, _ in parameters + buffers if name not in state_keys)
    if absent:
        raise ResumeContractError(
            "non-persistent or custom learner tensors are unsupported: "
            f"{absent}")

    parameter_names: dict[int, list[str]] = {}
    for name, parameter in parameters:
        parameter_names.setdefault(id(parameter), []).append(name)
    optimizer_groups = []
    seen_optimizer_parameters: set[int] = set()
    for group_index, group in enumerate(optimizer.param_groups):
        names = []
        for parameter in group["params"]:
            identity = id(parameter)
            if identity not in parameter_names:
                raise ResumeContractError(
                    "optimizer contains a parameter outside the learner")
            if identity in seen_optimizer_parameters:
                raise ResumeContractError(
                    "optimizer parameter occurs in more than one position")
            seen_optimizer_parameters.add(identity)
            names.append(sorted(parameter_names[identity]))
        optimizer_groups.append({
            "index": group_index,
            "parameter_names": names,
        })

    return {
        "schema": "shengji-learner-schema-v3",
        "parameters": [
            _tensor_schema(name, parameter,
                           requires_grad=parameter.requires_grad)
            for name, parameter in parameters
        ],
        "buffers": [
            _tensor_schema(name, buffer,
                           requires_grad=buffer.requires_grad)
            for name, buffer in buffers
        ],
        "state": [
            _tensor_schema(name, value,
                           requires_grad=value.requires_grad)
            for name, value in state.items()
        ],
        "module_modes": [
            {"name": name, "training": module.training}
            for name, module in learner.named_modules()
        ],
        "module_config": learner_module_config_schema(learner),
        "optimizer_config": optimizer_config_schema(optimizer),
        "optimizer_groups": optimizer_groups,
    }


class ReplayRing:
    """A replay ring whose physical slots, logical order, and cursor persist."""

    def __init__(self, capacity: int):
        if isinstance(capacity, bool) or not isinstance(capacity, int) \
                or capacity <= 0:
            raise ValueError("replay capacity must be a positive integer")
        self.capacity = capacity
        self.cursor = 0
        self._slots: list[Any] = []

    def __len__(self) -> int:
        return len(self._slots)

    def __getitem__(self, index: int) -> Any:
        return self._slots[index]

    def append(self, item: Any) -> None:
        if len(self._slots) < self.capacity:
            if self.cursor != len(self._slots):
                raise ResumeContractError("replay cursor drift before append")
            self._slots.append(item)
        else:
            self._slots[self.cursor % self.capacity] = item
        self.cursor += 1

    def physical_items(self) -> list[Any]:
        return copy.deepcopy(self._slots)

    def logical_items(self) -> list[Any]:
        if len(self._slots) < self.capacity:
            ordered = self._slots
        else:
            start = self.cursor % self.capacity
            ordered = self._slots[start:] + self._slots[:start]
        return copy.deepcopy(ordered)

    def state_dict(self) -> dict[str, Any]:
        slots = self.physical_items()
        logical = self.logical_items()
        return {
            "schema": REPLAY_RING_SCHEMA,
            "capacity": self.capacity,
            "cursor": self.cursor,
            "slots": slots,
            "logical_order_sha256": state_digest(logical),
        }

    @staticmethod
    def validate_state_dict(state: object, *, expected_capacity: int) -> None:
        expected = {
            "schema", "capacity", "cursor", "slots",
            "logical_order_sha256",
        }
        _require_exact_keys(state, expected, "replay")
        assert isinstance(state, Mapping)
        if state["schema"] != REPLAY_RING_SCHEMA:
            raise ResumeContractError("unsupported replay schema")
        capacity = _require_nonnegative_int(state["capacity"],
                                            "replay capacity")
        if capacity == 0 or capacity != expected_capacity:
            raise ResumeContractError(
                f"replay capacity mismatch: {capacity}, "
                f"expected {expected_capacity}")
        cursor = _require_nonnegative_int(state["cursor"], "replay cursor")
        slots = state["slots"]
        if not isinstance(slots, list):
            raise ResumeContractError("replay slots must be a list")
        if len(slots) > capacity:
            raise ResumeContractError("replay contains more slots than capacity")
        if len(slots) < capacity and cursor != len(slots):
            raise ResumeContractError(
                "partially filled replay cursor must equal its size")
        if len(slots) == capacity and cursor < capacity:
            raise ResumeContractError(
                "full replay cursor cannot precede its capacity")
        if len(slots) < capacity:
            logical = slots
        else:
            start = cursor % capacity
            logical = slots[start:] + slots[:start]
        expected_order = _require_sha256(
            state["logical_order_sha256"], "replay logical-order digest")
        if state_digest(logical) != expected_order:
            raise ResumeContractError("replay logical order digest mismatch")

    def load_state_dict(self, state: object) -> None:
        self.validate_state_dict(state, expected_capacity=self.capacity)
        assert isinstance(state, Mapping)
        self._slots = copy.deepcopy(state["slots"])
        self.cursor = int(state["cursor"])


class ResumeRNGStreams:
    """Named local RNG streams; no process-global RNG state is implicit."""

    def __init__(self, python_rng: random.Random,
                 numpy_rng: np.random.Generator,
                 torch_generator: torch.Generator):
        self.python = python_rng
        self.numpy = numpy_rng
        self.torch = torch_generator

    @classmethod
    def seeded(cls, seed: int) -> "ResumeRNGStreams":
        generator = torch.Generator(device="cpu")
        generator.manual_seed(seed)
        return cls(random.Random(seed), np.random.default_rng(seed), generator)

    def state_dict(self) -> dict[str, Any]:
        bit_generator = self.numpy.bit_generator
        return {
            "schema": RNG_STREAMS_SCHEMA,
            "python_engine": _type_name(self.python),
            "python_state": copy.deepcopy(self.python.getstate()),
            "numpy_engine": _type_name(bit_generator),
            "numpy_state": copy.deepcopy(bit_generator.state),
            "torch_device": str(self.torch.device),
            "torch_state": self.torch.get_state().clone(),
        }

    def validate_state_dict(self, state: object) -> None:
        expected = {
            "schema", "python_engine", "python_state", "numpy_engine",
            "numpy_state", "torch_device", "torch_state",
        }
        _require_exact_keys(state, expected, "rng")
        assert isinstance(state, Mapping)
        if state["schema"] != RNG_STREAMS_SCHEMA:
            raise ResumeContractError("unsupported RNG-stream schema")
        if state["python_engine"] != _type_name(self.python):
            raise ResumeContractError("Python RNG engine mismatch")
        if state["numpy_engine"] != _type_name(self.numpy.bit_generator):
            raise ResumeContractError("NumPy RNG engine mismatch")
        if state["torch_device"] != str(self.torch.device):
            raise ResumeContractError("Torch RNG device mismatch")
        try:
            random.Random().setstate(copy.deepcopy(state["python_state"]))
            numpy_probe = copy.deepcopy(self.numpy.bit_generator)
            numpy_probe.state = copy.deepcopy(state["numpy_state"])
            torch_probe = torch.Generator(device=self.torch.device)
            torch_probe.set_state(state["torch_state"].clone())
        except Exception as exc:
            raise ResumeContractError(f"invalid RNG state: {exc}") from exc

    def load_state_dict(self, state: object) -> None:
        self.validate_state_dict(state)
        assert isinstance(state, Mapping)
        self.python.setstate(copy.deepcopy(state["python_state"]))
        self.numpy.bit_generator.state = copy.deepcopy(state["numpy_state"])
        self.torch.set_state(state["torch_state"].clone())


@dataclass(frozen=True)
class ResumeProgress:
    next_iteration: int
    next_batch: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.next_iteration, "next iteration")
        _require_nonnegative_int(self.next_batch, "next batch")

    def as_dict(self) -> dict[str, int]:
        return {
            "next_iteration": self.next_iteration,
            "next_batch": self.next_batch,
        }


@dataclass(frozen=True)
class ResumeReceipt:
    progress: ResumeProgress
    actor_ref: CheckpointRef
    candidate_ref: CheckpointRef
    experiment: str
    contract_sha256: str


_TOP_LEVEL_FIELDS = {
    "schema", "complete", "experiment", "contract_sha256", "types",
    "runtime", "learner_schema", "progress", "pending_jobs", "artifacts",
    "learner", "optimizer", "replay", "rng", "component_sha256",
}
_COMPONENT_FIELDS = {
    "binding", "execution", "progress", "boundary", "artifacts",
    "learner", "optimizer", "replay", "rng",
}


def _artifact_ref(value: object, label: str) -> CheckpointRef:
    _require_exact_keys(value, {"path", "sha256"}, f"{label} artifact")
    assert isinstance(value, Mapping)
    if not isinstance(value["path"], str) or not value["path"]:
        raise ResumeContractError(f"{label} artifact path must be nonempty")
    digest = _require_sha256(value["sha256"], f"{label} artifact digest")
    return CheckpointRef(value["path"], digest)


def _component_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "binding": {
            "schema": payload["schema"],
            "complete": payload["complete"],
            "experiment": payload["experiment"],
            "contract_sha256": payload["contract_sha256"],
            "types": payload["types"],
        },
        "execution": {
            "runtime": payload["runtime"],
            "learner_schema": payload["learner_schema"],
        },
        "progress": payload["progress"],
        "boundary": {"pending_jobs": payload["pending_jobs"]},
        "artifacts": payload["artifacts"],
        "learner": payload["learner"],
        "optimizer": payload["optimizer"],
        "replay": payload["replay"],
        "rng": payload["rng"],
    }


def _validate_payload(payload: object) -> None:
    _require_exact_keys(payload, _TOP_LEVEL_FIELDS, "resume checkpoint")
    assert isinstance(payload, Mapping)
    if payload["schema"] != EXACT_RESUME_SCHEMA:
        raise ResumeContractError("unsupported exact-resume schema")
    if payload["complete"] is not True:
        raise ResumeContractError("resume checkpoint is not complete")
    if not isinstance(payload["experiment"], str) or not payload["experiment"]:
        raise ResumeContractError("experiment identity must be nonempty")
    _require_sha256(payload["contract_sha256"], "contract digest")
    _require_exact_keys(payload["types"], {"learner", "optimizer"},
                        "state types")
    assert isinstance(payload["types"], Mapping)
    if not all(isinstance(value, str) and value
               for value in payload["types"].values()):
        raise ResumeContractError("learner and optimizer types must be named")
    _validate_deterministic_runtime(payload["runtime"])
    if not isinstance(payload["learner_schema"], Mapping):
        raise ResumeContractError("learner schema must be a mapping")
    _require_exact_keys(payload["progress"],
                        {"next_iteration", "next_batch"}, "progress")
    assert isinstance(payload["progress"], Mapping)
    _require_nonnegative_int(payload["progress"]["next_iteration"],
                             "next iteration")
    _require_nonnegative_int(payload["progress"]["next_batch"],
                             "next batch")
    pending = _require_nonnegative_int(payload["pending_jobs"],
                                       "pending jobs")
    if pending != 0:
        raise ResumeContractError(
            "exact resume requires a quiescent boundary with no pending jobs")
    _require_exact_keys(payload["artifacts"], {"actor", "candidate"},
                        "artifact bindings")
    assert isinstance(payload["artifacts"], Mapping)
    _artifact_ref(payload["artifacts"]["actor"], "actor")
    _artifact_ref(payload["artifacts"]["candidate"], "candidate")
    if not isinstance(payload["learner"], Mapping):
        raise ResumeContractError("learner state must be a mapping")
    if not isinstance(payload["optimizer"], Mapping):
        raise ResumeContractError("optimizer state must be a mapping")
    if not isinstance(payload["replay"], Mapping):
        raise ResumeContractError("replay state must be a mapping")
    replay_capacity = payload["replay"].get("capacity")
    if isinstance(replay_capacity, bool) or not isinstance(replay_capacity, int):
        raise ResumeContractError("replay capacity must be an integer")
    ReplayRing.validate_state_dict(
        payload["replay"], expected_capacity=replay_capacity)
    if not isinstance(payload["rng"], Mapping):
        raise ResumeContractError("RNG state must be a mapping")
    _require_exact_keys(payload["component_sha256"], _COMPONENT_FIELDS,
                        "component digests")
    assert isinstance(payload["component_sha256"], Mapping)
    for name, component in _component_values(payload).items():
        expected = _require_sha256(payload["component_sha256"][name],
                                   f"{name} component digest")
        if state_digest(component) != expected:
            raise ResumeContractError(f"{name} component digest mismatch")


def _load_torch_payload(path: str | os.PathLike) -> Any:
    # Replay samples and Python/NumPy RNG tuples intentionally exceed the
    # tensors-only format, so this local trusted artifact is explicit about
    # full checkpoint loading.
    # Device placement is part of the exactness contract, so loading does not
    # remap tensors.  An unavailable saved device must fail closed.
    return torch.load(path, weights_only=False)


def save_exact_resume(
        path: str | os.PathLike, *, learner: torch.nn.Module,
        optimizer: torch.optim.Optimizer, replay: ReplayRing,
        rng: ResumeRNGStreams, progress: ResumeProgress,
        actor_ref: CheckpointRef, candidate_ref: CheckpointRef,
        experiment: str, contract_sha256: str,
        pending_jobs: int = 0) -> CheckpointRef:
    """Publish one immutable exact-resume checkpoint.

    Saving with in-flight work is refused because result arrival order is not
    represented by this synchronous contract.
    """
    _require_sha256(contract_sha256, "contract digest")
    if not isinstance(experiment, str) or not experiment:
        raise ResumeContractError("experiment identity must be nonempty")
    pending_jobs = _require_nonnegative_int(pending_jobs, "pending jobs")
    if pending_jobs != 0:
        raise ResumeContractError(
            "exact resume requires a quiescent boundary with no pending jobs")
    actor_ref.verify()
    candidate_ref.verify()
    runtime = _runtime_identity()
    _validate_deterministic_runtime(runtime)
    learner_schema = learner_resume_schema(learner, optimizer)

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.partial")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite resume checkpoint {target}")
    payload: dict[str, Any] = {
        "schema": EXACT_RESUME_SCHEMA,
        "complete": True,
        "experiment": experiment,
        "contract_sha256": contract_sha256,
        "types": {
            "learner": _type_name(learner),
            "optimizer": _type_name(optimizer),
        },
        "runtime": runtime,
        "learner_schema": learner_schema,
        "progress": progress.as_dict(),
        "pending_jobs": pending_jobs,
        "artifacts": {
            "actor": actor_ref.as_dict(),
            "candidate": candidate_ref.as_dict(),
        },
        "learner": copy.deepcopy(learner.state_dict()),
        "optimizer": copy.deepcopy(optimizer.state_dict()),
        "replay": replay.state_dict(),
        "rng": rng.state_dict(),
    }
    payload["component_sha256"] = {
        name: state_digest(component)
        for name, component in _component_values(payload).items()
    }
    _validate_payload(payload)

    try:
        with partial.open("xb") as handle:
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing stale or concurrently owned resume partial "
            f"{partial}") from exc
    try:
        _validate_payload(_load_torch_payload(partial))
        actor_ref.verify()
        candidate_ref.verify()
        os.link(partial, target)
        partial.unlink()
    except BaseException:
        # A remaining partial is a loud signal that publication did not
        # finish.  Never silently reuse it on the next attempt.
        raise
    ref = CheckpointRef(str(target), sha256_file(target))
    ref.verify()
    return ref


def load_exact_resume(
        ref: CheckpointRef, *, learner: torch.nn.Module,
        optimizer: torch.optim.Optimizer, replay: ReplayRing,
        rng: ResumeRNGStreams, expected_actor_ref: CheckpointRef,
        expected_candidate_ref: CheckpointRef, expected_experiment: str,
        expected_contract_sha256: str) -> ResumeReceipt:
    """Validate and transactionally restore a synchronous learner boundary.

    Ordinary failures restore the caller's original state before raising.  A
    :class:`ResumeRollbackError` means rollback itself could not be proven and
    the caller must terminate without performing another learner transition.
    """
    _require_sha256(expected_contract_sha256, "expected contract digest")
    ref.verify()
    payload = _load_torch_payload(ref.path)
    ref.verify()
    _validate_payload(payload)
    assert isinstance(payload, Mapping)

    if payload["experiment"] != expected_experiment:
        raise ResumeContractError("experiment identity mismatch")
    if payload["contract_sha256"] != expected_contract_sha256:
        raise ResumeContractError("contract digest mismatch")
    if payload["types"]["learner"] != _type_name(learner):
        raise ResumeContractError("learner type mismatch")
    if payload["types"]["optimizer"] != _type_name(optimizer):
        raise ResumeContractError("optimizer type mismatch")
    current_runtime = _runtime_identity()
    _validate_deterministic_runtime(current_runtime)
    if state_digest(payload["runtime"]) != state_digest(current_runtime):
        raise ResumeContractError("numerical runtime identity mismatch")
    current_learner_schema = learner_resume_schema(learner, optimizer)
    if state_digest(payload["learner_schema"]) != state_digest(
            current_learner_schema):
        raise ResumeContractError("learner or optimizer schema mismatch")

    stored_actor = _artifact_ref(payload["artifacts"]["actor"], "actor")
    stored_candidate = _artifact_ref(
        payload["artifacts"]["candidate"], "candidate")
    if stored_actor != expected_actor_ref:
        raise ResumeContractError("actor artifact identity mismatch")
    if stored_candidate != expected_candidate_ref:
        raise ResumeContractError("candidate artifact identity mismatch")
    for artifact in (stored_actor, stored_candidate):
        artifact.verify()

    ReplayRing.validate_state_dict(
        payload["replay"], expected_capacity=replay.capacity)
    rng.validate_state_dict(payload["rng"])

    original = {
        "learner": copy.deepcopy(learner.state_dict()),
        "optimizer": copy.deepcopy(optimizer.state_dict()),
        "replay": replay.state_dict(),
        "rng": rng.state_dict(),
    }
    original_digests = {
        name: state_digest(value) for name, value in original.items()
    }
    try:
        learner.load_state_dict(payload["learner"], strict=True)
        optimizer.load_state_dict(payload["optimizer"])
        replay.load_state_dict(payload["replay"])
        rng.load_state_dict(payload["rng"])
        restored = {
            "learner": learner.state_dict(),
            "optimizer": optimizer.state_dict(),
            "replay": replay.state_dict(),
            "rng": rng.state_dict(),
        }
        for name, value in restored.items():
            expected = payload["component_sha256"][name]
            if state_digest(value) != expected:
                raise ResumeContractError(
                    f"restored {name} state does not match checkpoint")
        if state_digest(_runtime_identity()) != state_digest(payload["runtime"]):
            raise ResumeContractError(
                "numerical runtime changed during restore")
        ref.verify()
        for artifact in (stored_actor, stored_candidate):
            artifact.verify()
    except BaseException as exc:
        try:
            learner.load_state_dict(original["learner"], strict=True)
            optimizer.load_state_dict(original["optimizer"])
            replay.load_state_dict(original["replay"])
            rng.load_state_dict(original["rng"])
            rolled_back = {
                "learner": learner.state_dict(),
                "optimizer": optimizer.state_dict(),
                "replay": replay.state_dict(),
                "rng": rng.state_dict(),
            }
            for name, value in rolled_back.items():
                if state_digest(value) != original_digests[name]:
                    raise RuntimeError(f"{name} rollback digest mismatch")
        except BaseException as rollback_exc:
            raise ResumeRollbackError(
                "resume restore and rollback both failed; caller must "
                "terminate before another learner transition") from rollback_exc
        if not isinstance(exc, Exception):
            # Interrupts and process-exit requests still propagate, but only
            # after the caller's original mutable state has been proven back
            # in place.  Otherwise a caught KeyboardInterrupt could expose a
            # half-restored learner/optimizer/replay/RNG bundle.
            raise
        if isinstance(exc, ResumeContractError):
            raise
        raise ResumeContractError(
            f"resume state restore failed; original state restored: {exc}") \
            from exc

    progress = ResumeProgress(
        next_iteration=payload["progress"]["next_iteration"],
        next_batch=payload["progress"]["next_batch"],
    )
    return ResumeReceipt(
        progress=progress,
        actor_ref=stored_actor,
        candidate_ref=stored_candidate,
        experiment=payload["experiment"],
        contract_sha256=payload["contract_sha256"],
    )
