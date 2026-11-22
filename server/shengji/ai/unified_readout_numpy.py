"""NumPy runtime of the unified model with its per-world readout (``train.unified_readout``).

A `UnifiedReadoutNumpy` is a `unified_numpy.UnifiedNumpy` (the served belief trunk, the outcome and
root-policy heads) plus the readout: ``decision_cache`` projects one decision's card states and row
context once; ``leaf_logits`` scores any number of full-information leaves of that decision from
their nine count planes and twelve scalars (``train.unified_readout``): 204 outcome logits from the
actor's side and 54 reply log-odds for the seat to act.

A package is one ``.npz``: trunk weights under ``w:``, head weights under ``h:``, readout weights
under ``r:``, the config and metadata as JSON, schema ``shengji-unified-readout-numpy-v1``.
``belief_package`` writes the trunk as a served-shape belief package with the metadata's temperature.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from . import belief_numpy as bn
from .unified_numpy import PACKAGE_MAX_BYTES, UnifiedNumpy, UnifiedNumpyError, _ln

try:
    from ._cwv_math import HAVE_LAYER_NORM_288, layer_norm_288 as _native_layer_norm
    if not HAVE_LAYER_NORM_288:
        _native_layer_norm = None
except ImportError:
    _native_layer_norm = None

SCHEMA = "shengji-unified-readout-numpy-v1"
N_CARDS = 54
OUTCOME_CLASSES = 204
N_PLANES = 9
N_SCALARS = 12
POOL_SCALE = 0.25


def leaf_scalars(n_delta, n_trick, points, winner, nxt) -> np.ndarray:
    """The twelve trick scalars of ``L`` leaves, ``(L, 12)``: plays since the decision / 4, plays in
    the current trick / 4, the trick is complete, its points / 50, its winner so far (one-hot, actor's frame), the seat to act next
    (one-hot; the winner when the trick is complete).  A complete trick is the one just finished."""
    n = len(n_delta)
    out = np.zeros((n, N_SCALARS), np.float32)
    out[:, 0] = np.asarray(n_delta, np.float32) / 4.0
    out[:, 1] = np.asarray(n_trick, np.float32) / 4.0
    out[:, 2] = np.asarray(n_trick) == 4
    out[:, 3] = np.asarray(points, np.float32) / 50.0
    out[np.arange(n), 4 + np.asarray(winner, np.int64)] = 1.0
    out[np.arange(n), 8 + np.asarray(nxt, np.int64)] = 1.0
    return out


def _ln_into(x: np.ndarray, w: np.ndarray, b: np.ndarray, out: np.ndarray, square: np.ndarray) -> np.ndarray:
    """`_ln(x, w, b)` written into ``out`` (``square`` is scratch of the same shape): the same
    operations in the same order, so the same bits."""
    if _native_layer_norm is not None and _native_layer_norm(x, w, b, out, square, bn.LAYERNORM_EPS):
        return out
    mu = x.mean(-1, keepdims=True)
    np.subtract(x, mu, out=out)
    np.multiply(out, out, out=square)
    var = square.mean(-1, keepdims=True)
    var += bn.LAYERNORM_EPS
    np.sqrt(var, out=var)
    out /= var
    out *= w
    out += b
    return out


def readout_shapes(config: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    d, xh = int(config["trunk"]["d"]), int(config["trunk"]["x_hidden"])
    r = config["readout"]
    dp, dc, width, hidden = int(r["dp"]), int(r["dc"]), int(r["width"]), int(r["hidden"])
    out = {"card_ln.weight": (d,), "card_ln.bias": (d,), "card_proj.weight": (dp, d), "card_proj.bias": (dp,),
           "ctx.weight": (dc, xh + d), "ctx.bias": (dc,),
           "stem.weight": (width, N_PLANES * N_CARDS + N_SCALARS + N_PLANES * dp + dc), "stem.bias": (width,),
           "out_ln.weight": (width,), "out_ln.bias": (width,),
           "value.weight": (OUTCOME_CLASSES, width), "value.bias": (OUTCOME_CLASSES,),
           "reply.weight": (N_CARDS, width), "reply.bias": (N_CARDS,)}
    for i in range(int(r["blocks"])):
        out.update({f"ln.{i}.weight": (width,), f"ln.{i}.bias": (width,), f"up.{i}.weight": (hidden, width),
                    f"up.{i}.bias": (hidden,), f"down.{i}.weight": (width, hidden), f"down.{i}.bias": (width,)})
    return out


class UnifiedReadoutNumpy(UnifiedNumpy):
    def __init__(self, config, trunk_weights, head_weights, readout_weights, metadata, dtype=np.float32):
        super().__init__(config, trunk_weights, head_weights, metadata, dtype=dtype)
        self.config["readout"] = {k: int(v) for k, v in config["readout"].items()}
        want = readout_shapes(self.config)
        if set(readout_weights) != set(want):
            raise UnifiedNumpyError(f"readout weights differ from the config: {sorted(set(readout_weights) ^ set(want))[:3]}")
        r = {}
        for k, shape in want.items():
            a = np.asarray(readout_weights[k], dtype)
            if a.shape != shape or not np.isfinite(a).all():
                raise UnifiedNumpyError(f"{k}: shape {a.shape} != {shape} or non-finite")
            a = a.copy()
            a.setflags(write=False)
            r[k] = a
        self.r = r
        # the transposed matrices a batch forward multiplies by, contiguous
        self._t = {k: np.ascontiguousarray(r[k].T) for k in r if k.endswith(".weight") and r[k].ndim == 2}
        self.blocks = int(self.config["readout"]["blocks"])

    def decision_cache(self, q: np.ndarray, g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``((54, dp) projected card states, (dc,) context)`` of one decision's ``card_states``."""
        r = self.r
        n = _ln(q, r["card_ln.weight"], r["card_ln.bias"])
        S = n @ self._t["card_proj.weight"] + r["card_proj.bias"]
        c = np.maximum(np.concatenate([g, n.mean(0)]) @ self._t["ctx.weight"] + r["ctx.bias"], 0.0)
        return np.ascontiguousarray(S, self.dtype), c.astype(self.dtype)

    def leaf_hidden(self, cache, planes: np.ndarray, scalars: np.ndarray) -> np.ndarray:
        r, t = self.r, self._t
        S, c = cache
        n = len(planes)
        planes = np.asarray(planes, self.dtype).reshape(n, N_PLANES, N_CARDS)
        pooled = (planes.reshape(n * N_PLANES, N_CARDS) @ S).reshape(n, -1) * self.dtype.type(POOL_SCALE)
        x = np.concatenate([planes.reshape(n, -1), np.asarray(scalars, self.dtype), pooled,
                            np.broadcast_to(c, (n, len(c)))], 1)
        h = np.maximum(x @ t["stem.weight"] + r["stem.bias"], 0.0)
        for i in range(self.blocks):
            u = _ln(h, r[f"ln.{i}.weight"], r[f"ln.{i}.bias"])
            u = np.maximum(u @ t[f"up.{i}.weight"] + r[f"up.{i}.bias"], 0.0)
            h = h + u @ t[f"down.{i}.weight"] + r[f"down.{i}.bias"]
        return _ln(h, r["out_ln.weight"], r["out_ln.bias"])

    def leaf_value_logits(self, cache, planes, scalars) -> np.ndarray:
        """``(n, 204)`` outcome logits from the decision's actor's side."""
        return self.leaf_hidden(cache, planes, scalars) @ self._t["value.weight"] + self.r["value.bias"]

    def leaf_reply_logits(self, cache, planes, scalars) -> np.ndarray:
        """``(n, 54)`` card log-odds for the seat to act at each leaf."""
        return self.leaf_hidden(cache, planes, scalars) @ self._t["reply.weight"] + self.r["reply.bias"]

    def leaf_value_probs(self, cache, planes, scalars) -> np.ndarray:
        z = self.leaf_value_logits(cache, planes, scalars).astype(np.float64)
        z -= z.max(-1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(-1, keepdims=True)

    # ---------------------------------------------------------------- fused stem (the fast readout)
    def fused_stem(self, cache) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """One decision's stem with its card states and context folded in: ``((9 * 54, width) plane
        matrix, (12, width) scalar matrix, (width,) constant)``.  Plane ``p``'s rows are its own stem
        columns plus ``POOL_SCALE * S @`` its pooled columns, so ``planes @ M + scalars @ W + const`` is
        `leaf_hidden`'s stem input times the stem, summed in another order (float32 rounding only).
        The fold is computed in float64 and stored in the model's dtype."""
        S, c = cache
        W = self.r["stem.weight"].astype(np.float64)
        width, dp = W.shape[0], S.shape[1]
        flat = N_PLANES * N_CARDS
        w_planes = W[:, :flat].reshape(width, N_PLANES, N_CARDS)
        w_pool = W[:, flat + N_SCALARS:flat + N_SCALARS + N_PLANES * dp].reshape(width, N_PLANES, dp)
        S64 = np.asarray(S, np.float64)
        M = np.empty((N_PLANES, N_CARDS, width), np.float64)
        for p in range(N_PLANES):
            M[p] = w_planes[:, p, :].T + POOL_SCALE * (S64 @ w_pool[:, p, :].T)
        const = np.asarray(c, np.float64) @ W[:, flat + N_SCALARS + N_PLANES * dp:].T + self.r["stem.bias"]
        return (np.ascontiguousarray(M.reshape(flat, width), self.dtype),
                np.ascontiguousarray(W[:, flat:flat + N_SCALARS].T, self.dtype), const.astype(self.dtype))

    def leaf_hidden_fused(self, fused, planes: np.ndarray, scalars: np.ndarray) -> np.ndarray:
        """`leaf_hidden` through `fused_stem`'s matrices; ``planes`` is ``(n, 9 * 54)``.  Every
        elementwise step writes into one of three buffers, in the same order of operations as
        `leaf_hidden`'s blocks and `_ln`, so the rounding is the fused stem's alone."""
        r, t = self.r, self._t
        M, w_scalars, const = fused
        h = np.asarray(planes, self.dtype) @ M
        h += np.asarray(scalars, self.dtype) @ w_scalars
        h += const
        np.maximum(h, 0.0, out=h)
        n = len(h)
        u = np.empty_like(h)
        square = np.empty_like(h)
        wide = np.empty((n, t["up.0.weight"].shape[1]), self.dtype) if self.blocks else None
        for i in range(self.blocks):
            _ln_into(h, r[f"ln.{i}.weight"], r[f"ln.{i}.bias"], u, square)
            np.matmul(u, t[f"up.{i}.weight"], out=wide)
            wide += r[f"up.{i}.bias"]
            np.maximum(wide, 0.0, out=wide)
            np.matmul(wide, t[f"down.{i}.weight"], out=u)
            h += u
            h += r[f"down.{i}.bias"]
        return _ln_into(h, r["out_ln.weight"], r["out_ln.bias"], u, square)

    def leaf_value_probs_fused(self, fused, planes, scalars) -> np.ndarray:
        """`leaf_value_probs` through `leaf_hidden_fused`."""
        z = self.leaf_hidden_fused(fused, planes, scalars) @ self._t["value.weight"]
        z += self.r["value.bias"]
        e = z.astype(np.float64)
        e -= e.max(-1, keepdims=True)
        np.exp(e, out=e)
        e /= e.sum(-1, keepdims=True)
        return e

    def leaf_reply_logits_fused(self, fused, planes, scalars) -> np.ndarray:
        """`leaf_reply_logits` through `leaf_hidden_fused`."""
        z = self.leaf_hidden_fused(fused, planes, scalars) @ self._t["reply.weight"]
        z += self.r["reply.bias"]
        return z


def save_package(path, config, trunk_weights, head_weights, readout_weights, metadata) -> str:
    model = UnifiedReadoutNumpy(config, trunk_weights, head_weights, readout_weights, metadata)
    arrays = {f"w:{k}": np.asarray(v, np.float32) for k, v in trunk_weights.items()}
    arrays.update({f"h:{k}": np.asarray(v, np.float32) for k, v in head_weights.items()})
    arrays.update({f"r:{k}": np.asarray(v, np.float32) for k, v in readout_weights.items()})
    arrays["schema"] = np.asarray(SCHEMA)
    arrays["config"] = np.asarray(json.dumps(model.config, sort_keys=True))
    arrays["metadata"] = np.asarray(json.dumps(dict(metadata, dims=bn.DIMS), sort_keys=True, default=str))
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, **arrays)
    os.replace(tmp, path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_unified_readout_numpy(path, sha256: str | None = None, dtype=np.float32) -> UnifiedReadoutNumpy:
    p = Path(path)
    if p.stat().st_size > PACKAGE_MAX_BYTES:
        raise UnifiedNumpyError("package too large")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if sha256 is not None and digest != sha256:
        raise UnifiedNumpyError(f"package sha256 {digest} != expected {sha256}")
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        if str(z["schema"]) != SCHEMA:
            raise UnifiedNumpyError(f"schema {z['schema']} != {SCHEMA}")
        config = json.loads(str(z["config"]))
        metadata = json.loads(str(z["metadata"]))
        if metadata.get("dims") != bn.DIMS:
            raise UnifiedNumpyError("package input widths differ from this runtime")
        parts = {p_: {k[2:]: z[k] for k in z.files if k.startswith(p_ + ":")} for p_ in "whr"}
    model = UnifiedReadoutNumpy(config, parts["w"], parts["h"], parts["r"], metadata, dtype=dtype)
    model.package_sha256 = digest
    return model


def belief_package(model: UnifiedReadoutNumpy, path) -> str:
    """The trunk as a served-shape belief package (temperature from the metadata); its sha256."""
    return bn.save_package(path, model.trunk.config, dict(model.trunk.w),
                           {"temperature": float(model.metadata["temperature"]), "source_unified_package": model.package_sha256})
