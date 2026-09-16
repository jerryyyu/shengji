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

try:
    from ._cwv_math import erf_array as _native_erf
except ImportError:
    _native_erf = None


PACKAGE_SCHEMA = "shengji-cwv-numpy-mlp-v1"
#: v2 adds the trunk shape (#435): the residual trunk of M1 (Linear stem ->
#: N tabular-ResNet blocks -> LayerNorm -> ReLU) next to the plain two-layer
#: MLP.  v1 packages are unchanged and keep loading byte for byte.
PACKAGE_SCHEMA_V2 = "shengji-cwv-numpy-mlp-v2"
PACKAGE_SCHEMAS = (PACKAGE_SCHEMA, PACKAGE_SCHEMA_V2)
LAYERNORM_EPS = 1e-5
PACKAGE_MAX_BYTES = 128 * 1024 * 1024
OUTCOME_CLASSES = 204
WORLD_RECEIVERS = 5
N_CARDS = 54
PERSPECTIVE_DIM = 2
#: #411 grid trunk (G1's suit x level table) as a v2 package feature: the card
#: planes are gathered through a per-trump index table that the package carries
#: (``grid_table``), two width-3 window reads, row/global summaries, then the
#: same stem + residual blocks as ``trunk_block=residual``.
GRID_ROWS = 5
GRID_COLS = 18
GRID_TABLE_ROWS = 5 * 13          # (trump suit | no-trump) x trump rank
GRID_PLANES = 9 + WORLD_RECEIVERS
GRID_CELL_PROJ = 8
GRID_COL_EMBED = 8
GRID_SUIT_OFFSET = 9 * N_CARDS
GRID_RANK_OFFSET = GRID_SUIT_OFFSET + 5


class CWVNumpyError(ValueError):
    """Malformed package, configuration, weights, or inference batch."""


@dataclass(frozen=True)
class CWVNumpyConfig:
    architecture: str
    width: int
    feedforward_width: int
    public_dim: int
    enc_version: int
    trunk_block: str = "plain"
    trunk_layers: int = 2
    #: #425 joint net served as ONE package: a 54-card policy head on the trunk
    #: features (``policy_weight`` / ``policy_bias``), read by the prior admission.
    policy_head: bool = False
    #: #411 grid trunk: the window-read channel count (``value_model.GridTrunk``);
    #: zero for every other trunk, required positive for ``trunk_block="grid"``.
    grid_channels: int = 0

    def validate(self) -> None:
        if self.architecture != "mlp":
            raise CWVNumpyError("only architecture=mlp is supported")
        if type(self.policy_head) is not bool:
            raise CWVNumpyError("policy_head must be a boolean")
        if type(self.grid_channels) is not int or self.grid_channels < 0 or self.grid_channels > 1024:
            raise CWVNumpyError("invalid grid_channels")
        if self.trunk_block == "plain":
            if self.trunk_layers != 2:
                raise CWVNumpyError("the plain trunk is the two-layer MLP only")
        elif self.trunk_block in ("residual", "grid"):
            if type(self.trunk_layers) is not int or not 1 <= self.trunk_layers <= 64:
                raise CWVNumpyError("invalid residual trunk depth")
        else:
            raise CWVNumpyError("trunk_block must be plain, residual or grid")
        if (self.trunk_block == "grid") != (self.grid_channels > 0):
            raise CWVNumpyError("grid_channels is the grid trunk's width and nothing else's")
        if any(type(v) is not int or v <= 0 for v in
               (self.width, self.feedforward_width, self.public_dim, self.enc_version)):
            raise CWVNumpyError("invalid exported model configuration")
        if self.width < 8 or self.feedforward_width < self.width:
            raise CWVNumpyError("invalid exported model widths")
        # Encoder widths are deliberately checked without importing the
        # training stack; v1/v2 are the only supported identity-preserving
        # public dimensions.
        expected = {1: 532, 2: 561}.get(self.enc_version)
        if expected is None or self.public_dim != expected:
            raise CWVNumpyError("public_dim/enc_version identity mismatch")


def _readonly(value: np.ndarray, shape: tuple[int, ...], label: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype != np.float32 or array.shape != shape or not np.all(np.isfinite(array)):
        raise CWVNumpyError(f"malformed {label} array")
    raw = np.array(array, dtype=np.float32, copy=True, order="C").tobytes()
    return np.frombuffer(raw, dtype=np.float32).reshape(shape)


def _layer_norm(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    # torch.nn.LayerNorm over the last dim: biased variance, eps inside the sqrt.
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(var + LAYERNORM_EPS) * weight + bias


def expected_arrays(config: "CWVNumpyConfig") -> dict[str, tuple[int, ...]]:
    """The exported array names and shapes a configuration requires."""
    inp = config.public_dim + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM
    head = {"head_weight": (OUTCOME_CLASSES, config.width), "head_bias": (OUTCOME_CLASSES,)}
    if config.trunk_block == "plain":
        return _with_policy({"trunk0_weight": (config.feedforward_width, inp),
                             "trunk0_bias": (config.feedforward_width,),
                             "trunk1_weight": (config.width, config.feedforward_width),
                             "trunk1_bias": (config.width,), **head}, config)
    if config.trunk_block == "grid":
        c = config.grid_channels
        cin = GRID_PLANES + GRID_ROWS + GRID_COL_EMBED
        scalar_dim = config.public_dim - 9 * N_CARDS
        feat = (GRID_CELL_PROJ * GRID_ROWS * GRID_COLS + 2 * c * GRID_ROWS + 4 * c
                + scalar_dim + PERSPECTIVE_DIM)
        out = {"grid_table": (GRID_TABLE_ROWS, GRID_ROWS * GRID_COLS),
               "col_embed": (GRID_COLS, GRID_COL_EMBED),
               "win1_weight": (3, cin, c), "win1_bias": (c,),
               "win2_weight": (3, c, c), "win2_bias": (c,),
               "row_proj_weight": (c, 2 * c), "row_proj_bias": (c,),
               "cell_proj_weight": (GRID_CELL_PROJ, c), "cell_proj_bias": (GRID_CELL_PROJ,),
               "stem_weight": (config.width, feat), "stem_bias": (config.width,)}
    else:
        out = {"stem_weight": (config.width, inp), "stem_bias": (config.width,)}
    for i in range(config.trunk_layers):
        out.update({f"block{i}_norm_weight": (config.width,), f"block{i}_norm_bias": (config.width,),
                    f"block{i}_up_weight": (config.feedforward_width, config.width),
                    f"block{i}_up_bias": (config.feedforward_width,),
                    f"block{i}_down_weight": (config.width, config.feedforward_width),
                    f"block{i}_down_bias": (config.width,)})
    out.update({"final_norm_weight": (config.width,), "final_norm_bias": (config.width,), **head})
    return _with_policy(out, config)


def _with_policy(arrays: dict, config: "CWVNumpyConfig") -> dict:
    if config.policy_head:
        arrays.update({"policy_weight": (N_CARDS, config.width), "policy_bias": (N_CARDS,)})
    return arrays


def _gelu_exact(x: np.ndarray) -> np.ndarray:
    # torch.nn.GELU() defaults to the exact erf formulation.  np.erf is not
    # available in all supported NumPy builds. The optional native loop uses
    # libc erf, with the same surrounding NumPy arithmetic; otherwise retain
    # the stdlib fallback. No approximate GELU or changed matmul precision.
    erf = (_native_erf if _native_erf is not None
           else np.vectorize(math.erf, otypes=[np.float64]))
    return (x * (1.0 + erf(x / math.sqrt(2.0))) * 0.5).astype(np.float64)


class CWVNumpyMLP:
    """Validated immutable exported MLP; safe to share across deep copies."""

    def __init__(self, config: CWVNumpyConfig, weights: Mapping[str, np.ndarray], *,
                 metadata: Mapping[str, Any] | None = None,
                 original_checkpoint_sha256: str | None = None):
        config.validate()
        expected = expected_arrays(config)
        if set(weights) != set(expected):
            raise CWVNumpyError("unknown or missing exported weight array")
        self.config = config
        self._weights = MappingProxyType({k: _readonly(weights[k], shape, k)
                                          for k, shape in expected.items()})
        self._grid_slots = None
        if config.trunk_block == "grid":
            table = self._weights["grid_table"]
            if not np.array_equal(table, np.rint(table)) or table.min() < 0 or table.max() > N_CARDS:
                raise CWVNumpyError("malformed grid_table array")
            slots = table.astype(np.int64)
            slots.setflags(write=False)                 # shared across deep copies: immutable
            self._grid_slots = slots
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
    @property
    def trunk_block(self): return self.config.trunk_block
    @property
    def trunk_layers(self): return self.config.trunk_layers

    def __deepcopy__(self, memo):
        del memo
        clone = object.__new__(type(self))
        clone.config = self.config
        clone._weights = self._weights
        clone._math_weights = self._math_weights
        clone._grid_slots = self._grid_slots
        clone.metadata = json.loads(json.dumps(self.metadata, sort_keys=True))
        clone.original_checkpoint_sha256 = self.original_checkpoint_sha256
        clone.package_sha256 = getattr(self, "package_sha256", None)
        return clone

    @property
    def source_checkpoint_sha256(self):
        return self.original_checkpoint_sha256

    @property
    def policy_head(self): return self.config.policy_head

    def _trunk(self, x: np.ndarray) -> np.ndarray:
        """Trunk features of a flat float64 ``(B, public | world | perspective)`` batch."""
        # Keep storage compact, but promote operands explicitly.  Besides
        # making the numerical contract clear, this avoids platform BLAS
        # surprises for mixed float64/float32 matmul.
        w = self._math_weights
        with np.errstate(all="ignore"):
            if self.config.trunk_block == "plain":
                h = _gelu_exact(x @ w["trunk0_weight"].T + w["trunk0_bias"])
                h = _gelu_exact(h @ w["trunk1_weight"].T + w["trunk1_bias"])
            else:
                # value_model.ResidualTrunkBlock: x + down(relu(up(norm(x))));
                # then the trunk's final LayerNorm and ReLU (dropout is identity).
                feat = self._grid_features(x) if self.config.trunk_block == "grid" else x
                h = feat @ w["stem_weight"].T + w["stem_bias"]
                for i in range(self.config.trunk_layers):
                    n = _layer_norm(h, w[f"block{i}_norm_weight"], w[f"block{i}_norm_bias"])
                    n = np.maximum(n @ w[f"block{i}_up_weight"].T + w[f"block{i}_up_bias"], 0.0)
                    h = h + (n @ w[f"block{i}_down_weight"].T + w[f"block{i}_down_bias"])
                h = np.maximum(_layer_norm(h, w["final_norm_weight"], w["final_norm_bias"]), 0.0)
        return h

    def _grid_features(self, x: np.ndarray) -> np.ndarray:
        """``value_model.GridTrunk.forward`` up to the stem input, in float64 NumPy:
        gather the fourteen card planes into the (row, level) table selected by
        the public trump one-hots, two width-3 window reads along the level axis
        (one GEMM per tap, zero-padded), the row summary added back between them,
        then cells | row summaries | global summary | scalars | perspective."""
        w = self._math_weights
        b = x.shape[0]
        pd = self.config.public_dim
        public = x[:, :pd]
        world = x[:, pd:pd + WORLD_RECEIVERS * N_CARDS]
        planes = np.concatenate((public[:, :9 * N_CARDS].reshape(b, 9, N_CARDS),
                                 world.reshape(b, WORLD_RECEIVERS, N_CARDS)), axis=1)
        planes = np.concatenate((planes, np.zeros((b, GRID_PLANES, 1), dtype=np.float64)), axis=2)
        suit = np.argmax(public[:, GRID_SUIT_OFFSET:GRID_SUIT_OFFSET + 5], axis=1)
        rank = np.argmax(public[:, GRID_RANK_OFFSET:GRID_RANK_OFFSET + 13], axis=1)
        slots = self._grid_slots[suit * 13 + rank]                       # (b, rows*cols)
        g = np.take_along_axis(planes, np.broadcast_to(slots[:, None, :], (b, GRID_PLANES, slots.shape[1])), axis=2)
        g = g.reshape(b, GRID_PLANES, GRID_ROWS, GRID_COLS).transpose(0, 2, 3, 1)   # (b, rows, cols, planes)
        row_id = np.broadcast_to(np.eye(GRID_ROWS).reshape(1, GRID_ROWS, 1, GRID_ROWS), (b, GRID_ROWS, GRID_COLS, GRID_ROWS))
        col = np.broadcast_to(w["col_embed"].reshape(1, 1, GRID_COLS, GRID_COL_EMBED), (b, GRID_ROWS, GRID_COLS, GRID_COL_EMBED))

        def window(h, weight, bias):
            hp = np.pad(h, ((0, 0), (0, 0), (1, 1), (0, 0)))
            out = np.broadcast_to(bias, (b, GRID_ROWS, GRID_COLS, bias.shape[0])).copy()
            for k in range(3):
                out = out + hp[:, :, k:k + GRID_COLS] @ weight[k]
            return out

        h = _gelu_exact(window(np.concatenate((g, row_id, col), axis=-1), w["win1_weight"], w["win1_bias"]))
        summary = np.concatenate((h.mean(axis=2), h.max(axis=2)), axis=-1)          # (b, rows, 2C)
        h = _gelu_exact(h + (summary @ w["row_proj_weight"].T + w["row_proj_bias"])[:, :, None, :])
        h = _gelu_exact(window(h, w["win2_weight"], w["win2_bias"]))
        cells = (h @ w["cell_proj_weight"].T + w["cell_proj_bias"]).reshape(b, -1)
        rows = np.concatenate((h.mean(axis=2), h.max(axis=2)), axis=-1)             # (b, rows, 2C)
        glob = np.concatenate((rows.mean(axis=1), rows.max(axis=1)), axis=-1)       # (b, 4C)
        scalars = x[:, 9 * N_CARDS:pd]
        perspective = x[:, -PERSPECTIVE_DIM:]
        return np.concatenate((cells, rows.reshape(b, -1), glob, scalars, perspective), axis=1)

    def policy_log_odds(self, flat) -> np.ndarray:
        """The joint net's policy head over a flat root row (the layout
        ``policy_prior.flat_input`` writes: ``public | world | perspective``),
        i.e. ``ValueNetwork.policy_logits(features_flat(x))`` without Torch."""
        if not self.config.policy_head:
            raise CWVNumpyError("this package carries no policy head")
        x = np.asarray(flat)
        inp = self.public_dim + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM
        if x.ndim != 2 or x.shape[1] != inp:
            raise CWVNumpyError("policy batch shape drift")
        if not (np.issubdtype(x.dtype, np.number) and np.all(np.isfinite(x))):
            raise CWVNumpyError("policy batch contains nonfinite values")
        if x.shape[0] == 0:
            return np.empty((0, N_CARDS), dtype=np.float64)
        h = self._trunk(x.astype(np.float64))
        with np.errstate(all="ignore"):
            logits = h @ self._math_weights["policy_weight"].T + self._math_weights["policy_bias"]
        if not np.all(np.isfinite(logits)):
            raise CWVNumpyError("policy head produced nonfinite logits")
        return logits.astype(np.float64, copy=False)

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
        h = self._trunk(x)
        with np.errstate(all="ignore"):
            logits = h @ self._math_weights["head_weight"].T + self._math_weights["head_bias"]
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
            if "metadata" not in z.files:
                raise CWVNumpyError("export package schema drift")
            raw = z["metadata"]
            if raw.shape != () or raw.dtype.kind not in "SU":
                raise CWVNumpyError("invalid package metadata")
            metadata = json.loads(str(raw.item()))
            if not isinstance(metadata, dict) or set(metadata) != {
                    "schema", "config", "metadata", "original_checkpoint_sha256"} \
                    or metadata.get("schema") not in PACKAGE_SCHEMAS:
                raise CWVNumpyError("invalid package metadata schema")
            sha = metadata["original_checkpoint_sha256"]
            if not isinstance(sha, str) or len(sha) != 64 \
                    or any(c not in "0123456789abcdef" for c in sha):
                raise CWVNumpyError("invalid original checkpoint SHA256")
            base_keys = {"architecture", "width", "feedforward_width", "public_dim", "enc_version"}
            v2_keys = base_keys | {"trunk_block", "trunk_layers"}
            joint_keys = v2_keys | {"policy_head"}
            keys = set(metadata["config"]) if isinstance(metadata["config"], dict) else None
            # ``grid_channels`` may be spelled out (zero) on any package; a grid trunk must name it.
            shapes = (base_keys, v2_keys, joint_keys)
            if keys is None or keys not in shapes + tuple(k | {"grid_channels"} for k in shapes):
                raise CWVNumpyError("invalid package configuration")
            cfg = CWVNumpyConfig(**metadata["config"])
            cfg.validate()
            if cfg.policy_head and metadata["schema"] != PACKAGE_SCHEMA_V2:
                raise CWVNumpyError("a policy head is a v2 package feature")
            if cfg.trunk_block == "grid" and ("grid_channels" not in keys or metadata["schema"] != PACKAGE_SCHEMA_V2):
                raise CWVNumpyError("a grid trunk is a v2 package feature that names its grid_channels")
            # A v1 package is the plain two-layer MLP: the trunk keys may be absent or
            # spell out that default, never anything else.
            if metadata["schema"] == PACKAGE_SCHEMA and (cfg.trunk_block, cfg.trunk_layers) != ("plain", 2):
                raise CWVNumpyError("a v1 package is the plain two-layer MLP only")
            required = set(expected_arrays(cfg)) | {"metadata"}
            if set(z.files) != required:
                raise CWVNumpyError("export package schema drift")
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
