"""NumPy runtime of the S134 unified model: the served belief trunk plus its outcome (Q) and policy heads.

The trunk and belief head are a `belief_numpy.BeliefNumpy` (the served runtime, validated and run
unchanged); this module adds the two heads of ``train.unified_seq`` on top of its internals:

* ``card_states`` -- the 54 card states and the row context after the trunk's cross-attention and
  card self-attention (``BeliefNumpy.logits`` computes the same and applies the belief output to them;
  ``belief_logits`` here equals it);
* ``q_probs`` -- the 204-category outcome distribution at the actor's own play token: the encoder runs
  over the plays before the decision plus the actor's play (its token last), and the head reads the
  last state with the row context;
* ``policy_logits`` -- 54 card log-odds before the play; an action scores the sum of its cards'.

A package is one ``.npz``: the trunk weights under ``w:`` (``belief_numpy`` names), the head weights
under ``h:``, the config and metadata as JSON, schema ``shengji-unified-numpy-v1``.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .belief_numpy import DIMS, BeliefNumpy, _attend, _gelu, _ln

SCHEMA = "shengji-unified-numpy-v1"
OUTCOME_CLASSES = 204
N_CARDS = 54
PACKAGE_MAX_BYTES = 96 * 1024 * 1024


class UnifiedNumpyError(ValueError):
    pass


def head_shapes(config: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    d, xh = int(config["trunk"]["d"]), int(config["trunk"]["x_hidden"])
    qh, ph = int(config["heads"]["q_hidden"]), int(config["heads"]["policy_hidden"])
    history = config["heads"].get("outcome_history_width", d)
    if type(history) is not int or not 0 < history <= d:
        raise UnifiedNumpyError("outcome history width outside trunk width")
    return {"q_head.0.weight": (history + xh,), "q_head.0.bias": (history + xh,),
            "q_head.1.weight": (qh, history + xh), "q_head.1.bias": (qh,),
            "q_head.3.weight": (qh, qh), "q_head.3.bias": (qh,),
            "q_head.5.weight": (OUTCOME_CLASSES, qh), "q_head.5.bias": (OUTCOME_CLASSES,),
            "p_head.0.weight": (d,), "p_head.0.bias": (d,),
            "p_head.1.weight": (ph, d), "p_head.1.bias": (ph,),
            "p_head.3.weight": (1, ph), "p_head.3.bias": (1,)}


class UnifiedNumpy:
    """A validated, read-only unified model."""

    def __init__(self, config: Mapping[str, Any], trunk_weights: Mapping[str, np.ndarray],
                 head_weights: Mapping[str, np.ndarray], metadata: Mapping[str, Any], dtype=np.float32):
        self.config = {"trunk": dict(config["trunk"]), "heads": dict(config["heads"])}
        self.metadata = dict(metadata)
        self.trunk = BeliefNumpy(self.config["trunk"], trunk_weights, {"temperature": 1.0}, dtype=dtype)
        want = head_shapes(self.config)
        if set(head_weights) != set(want):
            raise UnifiedNumpyError(f"head weights differ from the config: {sorted(set(head_weights) ^ set(want))[:3]}")
        h = {}
        for k, shape in want.items():
            a = np.asarray(head_weights[k], dtype)
            if a.shape != shape or not np.isfinite(a).all():
                raise UnifiedNumpyError(f"{k}: shape {a.shape} != {shape} or non-finite")
            a = a.copy()
            a.setflags(write=False)
            h[k] = a
        self.h = h
        self.dtype = np.dtype(dtype)
        self.package_sha256: str | None = None

    def __deepcopy__(self, memo):
        return self

    # ---------------------------------------------------------------- trunk internals
    def row_context(self, inp) -> np.ndarray:
        w = self.trunk.w
        X = np.asarray(inp["X"], self.dtype)
        g = np.maximum(X @ w["x_mlp.0.weight"].T + w["x_mlp.0.bias"], 0.0)
        return np.maximum(g @ w["x_mlp.2.weight"].T + w["x_mlp.2.bias"], 0.0)

    def card_states(self, inp, enc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """``((54, d) card states, (x_hidden,) row context)``; ``enc`` holds the plays BEFORE the
        decision only (``BeliefNumpy.encode_history`` of them)."""
        t = self.trunk
        w = t.w
        d, heads = t.d, t.heads
        ce = t._card_table(inp)
        g = self.row_context(inp)
        M = np.asarray(inp["M"], bool)
        rc = np.concatenate([np.asarray(inp["row_card"], self.dtype), M.astype(self.dtype)], -1)
        q = ce + rc @ w["row_card.weight"].T + w["row_card.bias"] + (g @ w["x_to_q.weight"].T + w["x_to_q.bias"])
        mem = np.concatenate([w["null_kv"][0], enc], 0)
        for i in range(int(t.config["xattn_layers"])):
            kv = mem @ w[f"kv.{i}.weight"].T + w[f"kv.{i}.bias"]
            qi = _ln(q, w[f"ln_q.{i}.weight"], w[f"ln_q.{i}.bias"])
            qi = qi @ w[f"xattn.{i}.q.weight"].T + w[f"xattn.{i}.q.bias"]
            a = _attend(qi, kv[:, :d], kv[:, d:], heads, None)
            q = q + a @ w[f"xattn.{i}.o.weight"].T + w[f"xattn.{i}.o.bias"]
            f = _ln(q, w[f"ff.{i}.0.weight"], w[f"ff.{i}.0.bias"])
            f = _gelu(f @ w[f"ff.{i}.1.weight"].T + w[f"ff.{i}.1.bias"])
            q = q + f @ w[f"ff.{i}.3.weight"].T + w[f"ff.{i}.3.bias"]
        if t.config["card_self_attn"]:
            x = _ln(q, w["self_ln.weight"], w["self_ln.bias"])
            q = q + t._mha("self_attn.", x, None)
            f = _ln(q, w["self_ff.0.weight"], w["self_ff.0.bias"])
            f = _gelu(f @ w["self_ff.1.weight"].T + w["self_ff.1.bias"])
            q = q + f @ w["self_ff.3.weight"].T + w["self_ff.3.bias"]
        return q, g

    def belief_logits(self, inp, enc=None) -> np.ndarray:
        """``(54, 4)``: equal to ``BeliefNumpy.logits`` (the served belief head)."""
        w = self.trunk.w
        if enc is None:
            enc = self.trunk.encode_history(inp)
        q, g = self.card_states(inp, enc)
        out = (g @ w["x_logits.weight"].T + w["x_logits.bias"]).reshape(N_CARDS, 4)
        o = _ln(q, w["out.0.weight"], w["out.0.bias"])
        return out + o @ w["out.1.weight"].T + w["out.1.bias"]

    # ---------------------------------------------------------------- heads
    def policy_logits(self, inp, enc=None) -> np.ndarray:
        """``(54,)`` card log-odds before the play."""
        h = self.h
        if enc is None:
            enc = self.trunk.encode_history(inp)
        q, _ = self.card_states(inp, enc)
        x = _ln(q, h["p_head.0.weight"], h["p_head.0.bias"])
        x = _gelu(x @ h["p_head.1.weight"].T + h["p_head.1.bias"])
        return (x @ h["p_head.3.weight"].T + h["p_head.3.bias"])[:, 0]

    def q_logits_at(self, inp_with_play) -> np.ndarray:
        """``(204,)`` outcome logits; ``inp_with_play``'s tokens end with the actor's own play."""
        h = self.h
        enc = self.trunk.encode_history(inp_with_play)
        if not len(enc):
            raise UnifiedNumpyError("the token list must end with the actor's play")
        g = self.row_context(inp_with_play)
        history = self.config["heads"].get("outcome_history_width")
        x = np.concatenate([enc[-1, :history], g])
        x = _ln(x, h["q_head.0.weight"], h["q_head.0.bias"])
        x = _gelu(x @ h["q_head.1.weight"].T + h["q_head.1.bias"])
        x = _gelu(x @ h["q_head.3.weight"].T + h["q_head.3.bias"])
        return x @ h["q_head.5.weight"].T + h["q_head.5.bias"]

    def q_probs(self, inp_with_play) -> np.ndarray:
        z = self.q_logits_at(inp_with_play).astype(np.float64)
        z = z - z.max()
        e = np.exp(z)
        return e / e.sum()


def save_package(path: str | os.PathLike, config: Mapping[str, Any], trunk_weights: Mapping[str, np.ndarray],
                 head_weights: Mapping[str, np.ndarray], metadata: Mapping[str, Any]) -> str:
    model = UnifiedNumpy(config, trunk_weights, head_weights, metadata)
    arrays = {f"w:{k}": np.asarray(v, np.float32) for k, v in trunk_weights.items()}
    arrays.update({f"h:{k}": np.asarray(v, np.float32) for k, v in head_weights.items()})
    arrays["schema"] = np.asarray(SCHEMA)
    arrays["config"] = np.asarray(json.dumps(model.config, sort_keys=True))
    arrays["metadata"] = np.asarray(json.dumps(dict(metadata, dims=DIMS), sort_keys=True, default=str))
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, **arrays)
    os.replace(tmp, path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_unified_numpy(path: str | os.PathLike, sha256: str | None = None, dtype=np.float32) -> UnifiedNumpy:
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
        if metadata.get("dims") != DIMS:
            raise UnifiedNumpyError("package input widths differ from this runtime")
        trunk = {k[2:]: z[k] for k in z.files if k.startswith("w:")}
        heads = {k[2:]: z[k] for k in z.files if k.startswith("h:")}
    model = UnifiedNumpy(config, trunk, heads, metadata, dtype=dtype)
    model.package_sha256 = digest
    return model


def batch_inputs(batch: Mapping[str, np.ndarray], i: int, *, with_play: bool) -> dict[str, Any]:
    """One row of a ``belief_seq.make_batch`` batch as a runtime input: the round's tokens before the
    row's ply (``with_play``: through the ply, the actor's own play last)."""
    r = int(batch["rr"][i])
    ply = int(batch["ply"][i])
    T = ply + 1 if with_play else ply
    return {"tok_int": batch["tok_int"][r, :T], "tok_f": batch["tok_f"][r, :T], "tok_cards": batch["tok_cards"][r, :T],
            "tok_att": batch["tok_att"][r, :T], "card_feat": batch["card_feat"][r], "banker": int(batch["banker"][r]),
            "seat": int(batch["seat"][i]), "X": batch["X"][i], "row_card": batch["row_card"][i], "M": batch["M"][i]}
