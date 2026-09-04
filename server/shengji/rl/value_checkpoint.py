"""Minimal weights-only checkpoint interface for :mod:`value_model`."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import torch

from .value_model import (
    ValueModelConfig,
    ValueModelError,
    ValueNetwork,
    model_state_sha256,
)


CHECKPOINT_SCHEMA = "shengji-value-checkpoint-v1"


class ValueCheckpointError(ValueError):
    """A checkpoint container, configuration, or logical state drifted."""


def file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    try:
        result = {} if value is None else dict(value)
        json.dumps(result, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueCheckpointError("checkpoint metadata must be finite JSON") from exc
    return result


def save_checkpoint(path: str | os.PathLike[str], model: ValueNetwork, *,
                    metadata: Mapping[str, Any] | None = None) -> str:
    """Atomically publish a weights-only checkpoint and return its file hash."""
    if type(model) is not ValueNetwork:
        raise ValueCheckpointError("checkpoint requires an exact ValueNetwork")
    model.config.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "config": model.config.payload(),
        "state_sha256": model_state_sha256(model),
        "state_dict": {
            key: value.detach().cpu().clone()
            for key, value in model.state_dict().items()},
        "metadata": _metadata(metadata),
    }
    try:
        with temporary.open("wb") as handle:
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return file_sha256(target)


def load_checkpoint(path: str | os.PathLike[str], *,
                    map_location: torch.device | str = "cpu"
                    ) -> tuple[ValueNetwork, dict[str, Any]]:
    """Load only tensors/simple values, validate the state hash, and rebuild."""
    try:
        payload = torch.load(
            Path(path), map_location=map_location, weights_only=True)
    except Exception as exc:
        raise ValueCheckpointError("checkpoint is unreadable") from exc
    if type(payload) is not dict or set(payload) != {
            "schema", "config", "state_sha256", "state_dict", "metadata"} \
            or payload.get("schema") != CHECKPOINT_SCHEMA \
            or not isinstance(payload.get("state_dict"), dict) \
            or type(payload.get("state_sha256")) is not str:
        raise ValueCheckpointError("checkpoint schema drift")
    try:
        config = ValueModelConfig.from_payload(payload["config"])
        model = ValueNetwork(config)
        model.load_state_dict(payload["state_dict"], strict=True)
    except (ValueModelError, RuntimeError, TypeError) as exc:
        raise ValueCheckpointError("checkpoint model state drift") from exc
    if model_state_sha256(model) != payload["state_sha256"]:
        raise ValueCheckpointError("checkpoint logical state hash drift")
    metadata = _metadata(payload["metadata"])
    model.to(map_location)
    model.eval()
    return model, metadata
