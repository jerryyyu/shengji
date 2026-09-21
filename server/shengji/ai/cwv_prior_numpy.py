"""Dependency-light NumPy runtime for an exported policy prior (#435).

The prior is the #419 net: ``Linear(833, h0) -> GELU -> Linear(h0, h1) ->
GELU -> Linear(h1, 54)`` applied to ``(X - mu) / sd``; its outputs are the
54 card log-odds the shortlist admission sums per candidate.  This module
imports only NumPy and the standard library; the exporter lives in
``scripts/export_policy_prior_numpy.py`` and is the only Torch-touching step.
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import zipfile
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from .cwv_numpy import CWVNumpyError, PACKAGE_MAX_BYTES, _frozen, _gelu_exact, _readonly

PRIOR_PACKAGE_SCHEMA = "shengji-policy-prior-numpy-v1"
SOURCE_SCHEMA = "shengji-policy-prior-v1"
N_CARDS = 54
_ARRAYS = ("w0", "b0", "w1", "b1", "w2", "b2", "mu", "sd")


class CWVNumpyPrior:
    """Validated, immutable exported prior; ``log_odds`` is the served forward."""

    def __init__(self, input_dim: int, hidden: tuple[int, int], weights: Mapping[str, np.ndarray], *,
                 enc_version: int, metadata: Mapping[str, Any] | None = None,
                 original_checkpoint_sha256: str | None = None):
        if type(input_dim) is not int or input_dim < 1 or type(enc_version) is not int:
            raise CWVNumpyError("invalid prior configuration")
        if (len(hidden) != 2 or any(type(h) is not int or h < 1 for h in hidden)):
            raise CWVNumpyError("invalid prior hidden widths")
        h0, h1 = hidden
        expected = {"w0": (h0, input_dim), "b0": (h0,), "w1": (h1, h0), "b1": (h1,),
                    "w2": (N_CARDS, h1), "b2": (N_CARDS,), "mu": (input_dim,), "sd": (input_dim,)}
        if set(weights) != set(expected):
            raise CWVNumpyError("unknown or missing exported prior array")
        self.input_dim, self.hidden, self.enc_version = input_dim, (h0, h1), enc_version
        self._weights = MappingProxyType({k: _readonly(weights[k], shape, k) for k, shape in expected.items()})
        if not np.all(self._weights["sd"] > 0):
            raise CWVNumpyError("prior sd must be positive")
        self._math = MappingProxyType({k: np.frombuffer(np.asarray(v, dtype=np.float64).tobytes(),
                                                        dtype=np.float64).reshape(v.shape)
                                       for k, v in self._weights.items()})
        self.metadata = dict(metadata or {})
        self.original_checkpoint_sha256 = original_checkpoint_sha256
        self.package_sha256: str | None = None

    def __deepcopy__(self, memo):
        # Server turn snapshots isolate bot state, but these bytes-backed,
        # read-only arrays can safely be shared. Mapping proxies themselves
        # are not pickleable, so the generic deepcopy path fails before search.
        clone = object.__new__(type(self))
        memo[id(self)] = clone
        for name, value in vars(self).items():
            setattr(clone, name, value if name in ("_weights", "_math")
                    else copy.deepcopy(value, memo))
        return clone

    # Pickle support (the screen's deadline worker sends ``vars(bot)`` over IPC per
    # move): proxies pickle as plain dicts and are rebuilt read-only on load.
    _PROXIED = ("_weights", "_math")

    def __getstate__(self):
        state = dict(vars(self))
        for name in self._PROXIED:
            state[name] = dict(state[name])
        return state

    def __setstate__(self, state):
        state = dict(state)
        for name in self._PROXIED:
            state[name] = MappingProxyType({k: _frozen(v) for k, v in state[name].items()})
        vars(self).update(state)

    def log_odds(self, X) -> np.ndarray:
        x = np.asarray(X)
        if x.ndim != 2 or x.shape[1] != self.input_dim:
            raise CWVNumpyError("prior batch shape drift")
        if not (np.issubdtype(x.dtype, np.number) and np.all(np.isfinite(x))):
            raise CWVNumpyError("prior batch contains nonfinite values")
        if x.shape[0] == 0:
            return np.empty((0, N_CARDS), dtype=np.float64)
        w = self._math
        with np.errstate(all="ignore"):
            h = (x.astype(np.float64) - w["mu"]) / w["sd"]
            h = _gelu_exact(h @ w["w0"].T + w["b0"])
            h = _gelu_exact(h @ w["w1"].T + w["b1"])
            out = h @ w["w2"].T + w["b2"]
        if not np.all(np.isfinite(out)):
            raise CWVNumpyError("prior produced nonfinite log-odds")
        return out.astype(np.float64, copy=False)


def load_numpy_prior(path: str | os.PathLike[str]) -> CWVNumpyPrior:
    resolved = Path(path)
    if not resolved.is_file() or resolved.stat().st_size > PACKAGE_MAX_BYTES:
        raise CWVNumpyError("prior package is missing or exceeds size limit")
    try:
        with zipfile.ZipFile(resolved) as zf:
            infos = zf.infolist()
            if len({i.filename for i in infos}) != len(infos) or sum(i.file_size for i in infos) > PACKAGE_MAX_BYTES:
                raise CWVNumpyError("prior package member drift")
        with np.load(resolved, allow_pickle=False) as z:
            if set(z.files) != set(_ARRAYS) | {"metadata"}:
                raise CWVNumpyError("prior package schema drift")
            raw = z["metadata"]
            if raw.shape != () or raw.dtype.kind not in "SU":
                raise CWVNumpyError("invalid prior package metadata")
            meta = json.loads(str(raw.item()))
            if (not isinstance(meta, dict) or set(meta) != {"schema", "source_schema", "input_dim", "hidden",
                                                           "enc_version", "original_checkpoint_sha256", "metadata"}
                    or meta["schema"] != PRIOR_PACKAGE_SCHEMA or meta["source_schema"] != SOURCE_SCHEMA):
                raise CWVNumpyError("invalid prior package metadata schema")
            sha = meta["original_checkpoint_sha256"]
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise CWVNumpyError("invalid original prior checkpoint SHA256")
            model = CWVNumpyPrior(int(meta["input_dim"]), tuple(int(h) for h in meta["hidden"]),
                                  {k: z[k] for k in _ARRAYS}, enc_version=int(meta["enc_version"]),
                                  metadata=meta.get("metadata"), original_checkpoint_sha256=sha)
            model.package_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
            return model
    except CWVNumpyError:
        raise
    except Exception as exc:
        raise CWVNumpyError("unreadable prior package") from exc


__all__ = ["CWVNumpyPrior", "PRIOR_PACKAGE_SCHEMA", "load_numpy_prior"]
