"""Dependency-light NumPy runtime for exported complete-world MLPs.

The module intentionally imports only NumPy and the standard library.  The
exporter is separate because checkpoint admission remains the canonical
Torch-backed ``ai.cwv_policy.load_cwv_checkpoint`` path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from types import MappingProxyType

import numpy as np


PACKAGE_SCHEMA = "shengji-cwv-numpy-mlp-v1"
PACKAGE_MAX_BYTES = 128 * 1024 * 1024
OUTCOME_CLASSES = 204
WORLD_RECEIVERS = 5
N_CARDS = 54
PERSPECTIVE_DIM = 2


class CWVNumpyError(ValueError):
    """Malformed package, configuration, weights, or inference batch."""


@dataclass(frozen=True)
class CWVNumpyConfig:
    architecture: str
    width: int
    feedforward_width: int
    public_dim: int
    enc_version: int

    def validate(self) -> None:
        if self.architecture != "mlp":
            raise CWVNumpyError("only architecture=mlp is supported")
        if any(type(v) is not int or v <= 0 for v in
               (self.width, self.feedforward_width, self.public_dim, self.enc_version)):
            raise CWVNumpyError("invalid exported model configuration")
        if self.width < 8 or self.feedforward_width < self.width:
            raise CWVNumpyError("invalid exported model widths")
        # Encoder widths are deliberately checked without importing the
        # training stack. Keep this small version table covered by real exports.
        expected = {1: 532, 2: 561, 3: 569}.get(self.enc_version)
        if expected is None or self.public_dim != expected:
            raise CWVNumpyError("public_dim/enc_version identity mismatch")


def _readonly(value: np.ndarray, shape: tuple[int, ...], label: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype != np.float32 or array.shape != shape or not np.all(np.isfinite(array)):
        raise CWVNumpyError(f"malformed {label} array")
    raw = np.array(array, dtype=np.float32, copy=True, order="C").tobytes()
    return np.frombuffer(raw, dtype=np.float32).reshape(shape)


def _gelu_exact(x: np.ndarray) -> np.ndarray:
    # torch.nn.GELU() defaults to the exact erf formulation.  np.erf is not
    # available in all supported NumPy builds, hence the stdlib ufunc.
    erf = np.vectorize(math.erf, otypes=[np.float64])
    return (x * (1.0 + erf(x / math.sqrt(2.0))) * 0.5).astype(np.float64)


class CWVNumpyMLP:
    """Validated immutable exported MLP; safe to share across deep copies."""

    def __init__(self, config: CWVNumpyConfig, weights: Mapping[str, np.ndarray], *,
                 metadata: Mapping[str, Any] | None = None,
                 original_checkpoint_sha256: str | None = None):
        config.validate()
        inp = config.public_dim + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM
        expected = {
            "trunk0_weight": (config.feedforward_width, inp),
            "trunk0_bias": (config.feedforward_width,),
            "trunk1_weight": (config.width, config.feedforward_width),
            "trunk1_bias": (config.width,),
            "head_weight": (OUTCOME_CLASSES, config.width),
            "head_bias": (OUTCOME_CLASSES,),
        }
        if set(weights) != set(expected):
            raise CWVNumpyError("unknown or missing exported weight array")
        self.config = config
        self._weights = MappingProxyType({k: _readonly(weights[k], shape, k)
                                          for k, shape in expected.items()})
        self._math_weights = MappingProxyType({
            k: np.frombuffer(np.asarray(v, dtype=np.float64).tobytes(),
                             dtype=np.float64).reshape(v.shape)
            for k, v in self._weights.items()})
        self.metadata = dict(metadata or {})
        self.original_checkpoint_sha256 = original_checkpoint_sha256

    @property
    def architecture(self): return self.config.architecture
    @property
    def width(self): return self.config.width
    @property
    def feedforward_width(self): return self.config.feedforward_width
    @property
    def public_dim(self): return self.config.public_dim
    @property
    def enc_version(self): return self.config.enc_version

    def __deepcopy__(self, memo):
        del memo
        clone = object.__new__(type(self))
        clone.config = self.config
        clone._weights = self._weights
        clone._math_weights = self._math_weights
        clone.metadata = json.loads(json.dumps(self.metadata, sort_keys=True))
        clone.original_checkpoint_sha256 = self.original_checkpoint_sha256
        clone.package_sha256 = getattr(self, "package_sha256", None)
        return clone

    @property
    def source_checkpoint_sha256(self):
        return self.original_checkpoint_sha256

    def probabilities(self, public, world, perspective) -> np.ndarray:
        p = np.asarray(public)
        w = np.asarray(world)
        q = np.asarray(perspective)
        if p.ndim != 2 or w.ndim != 3 or q.ndim != 2 or p.shape[1:] != (self.public_dim,) \
                or w.shape[1:] != (WORLD_RECEIVERS, N_CARDS) or q.shape[1:] != (PERSPECTIVE_DIM,) \
                or not (p.shape[0] == w.shape[0] == q.shape[0]):
            raise CWVNumpyError("model batch shape drift")
        if not all(np.issubdtype(x.dtype, np.number) and np.all(np.isfinite(x))
                   for x in (p, w, q)):
            raise CWVNumpyError("model batch contains nonfinite values")
        if p.shape[0] == 0:
            return np.empty((0, OUTCOME_CLASSES), dtype=np.float64)
        x = np.concatenate((p, w.reshape(p.shape[0], -1), q), axis=1).astype(np.float64)
        # Keep storage compact, but promote operands explicitly.  Besides
        # making the numerical contract clear, this avoids platform BLAS
        # surprises for mixed float64/float32 matmul.
        with np.errstate(all="ignore"):
            h = _gelu_exact(x @ self._math_weights["trunk0_weight"].T
                            + self._math_weights["trunk0_bias"])
            h = _gelu_exact(h @ self._math_weights["trunk1_weight"].T
                            + self._math_weights["trunk1_bias"])
            logits = h @ self._math_weights["head_weight"].T \
                + self._math_weights["head_bias"]
        if not np.all(np.isfinite(logits)):
            raise CWVNumpyError("model produced nonfinite logits")
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        probs = np.exp(shifted)
        probs /= np.sum(probs, axis=1, keepdims=True)
        if not np.all(np.isfinite(probs)):
            raise CWVNumpyError("model produced nonfinite probabilities")
        return probs.astype(np.float64, copy=False)


def _load_npz(path: str | os.PathLike[str]) -> CWVNumpyMLP:
    resolved = Path(path)
    if not resolved.is_file() or resolved.stat().st_size > PACKAGE_MAX_BYTES:
        raise CWVNumpyError("export package is missing or exceeds size limit")
    try:
        with zipfile.ZipFile(resolved) as zf:
            infos = zf.infolist()
            if len({info.filename for info in infos}) != len(infos):
                raise CWVNumpyError("duplicate package member")
            if any(info.file_size > PACKAGE_MAX_BYTES for info in infos) \
                    or sum(info.file_size for info in infos) > PACKAGE_MAX_BYTES:
                raise CWVNumpyError("export package member exceeds size limit")
        with np.load(resolved, allow_pickle=False) as z:
            required = {"metadata", "trunk0_weight", "trunk0_bias", "trunk1_weight",
                        "trunk1_bias", "head_weight", "head_bias"}
            if set(z.files) != required:
                raise CWVNumpyError("export package schema drift")
            raw = z["metadata"]
            if raw.shape != () or raw.dtype.kind not in "SU":
                raise CWVNumpyError("invalid package metadata")
            metadata = json.loads(str(raw.item()))
            if not isinstance(metadata, dict) or set(metadata) != {
                    "schema", "config", "metadata", "original_checkpoint_sha256"} \
                    or metadata.get("schema") != PACKAGE_SCHEMA:
                raise CWVNumpyError("invalid package metadata schema")
            sha = metadata["original_checkpoint_sha256"]
            if not isinstance(sha, str) or len(sha) != 64 \
                    or any(c not in "0123456789abcdef" for c in sha):
                raise CWVNumpyError("invalid original checkpoint SHA256")
            if not isinstance(metadata["config"], dict) or set(metadata["config"]) != {
                    "architecture", "width", "feedforward_width", "public_dim", "enc_version"}:
                raise CWVNumpyError("invalid package configuration")
            cfg = CWVNumpyConfig(**metadata["config"])
            cfg.validate()
            weights = {k: z[k] for k in required - {"metadata"}}
            model = CWVNumpyMLP(
                cfg, weights, metadata=metadata.get("metadata"),
                original_checkpoint_sha256=metadata.get("original_checkpoint_sha256"))
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            model.package_sha256 = digest
            return model
    except CWVNumpyError:
        raise
    except Exception as exc:
        raise CWVNumpyError("unreadable export package") from exc


def load_cwv_numpy(path: str | os.PathLike[str]) -> CWVNumpyMLP:
    return _load_npz(path)


load_cwv_numpy_package = load_cwv_numpy
load_numpy_checkpoint = load_cwv_numpy
