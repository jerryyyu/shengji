"""NumPy runtime for the S17 history belief model (``train.belief_seq.HistoryBelief``).

One decision at a time: per hidden card copy, the probability that each
seat-relative receiver (next, partner, previous, kitty) holds it.  The module
imports only NumPy and the standard library at load time; the live featurizer
(``decision_inputs``) imports the engine-side feature code lazily.

Package (``.npz``): ``schema``, ``config`` and ``metadata`` (JSON strings) plus
one array per torch parameter under its ``state_dict`` name.  ``metadata``
carries the source checkpoint's sha256 and the calibration temperature.

The forward is the torch model specialised to one row:

* the history encoder runs on the actor's frame only, over the plays before the
  decision (``T = ply``); the encoder is causal and the cross-attention masks
  every slot at or after ``ply``, so the later tokens a training batch carries
  never reach a row and dropping them leaves the output unchanged;
* inputs are rounded through float16 exactly as the extract stores them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

try:
    from ._cwv_math import erf_array as _native_erf
except ImportError:
    _native_erf = None

SCHEMA = "shengji-belief-numpy-v1"
N_CARDS = 54
N_RECV = 4
LAYERNORM_EPS = 1e-5
PACKAGE_MAX_BYTES = 64 * 1024 * 1024
CONFIG_KEYS = ("d", "heads", "enc_layers", "xattn_layers", "x_hidden", "card_self_attn")


class BeliefNumpyError(ValueError):
    """Malformed package, weights or decision inputs."""


def _ln(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + LAYERNORM_EPS) * w + b


def _gelu(x: np.ndarray) -> np.ndarray:
    erf = _native_erf if _native_erf is not None else np.vectorize(math.erf, otypes=[np.float64])
    return x * (1.0 + erf(x / math.sqrt(2.0)).astype(x.dtype, copy=False)) * 0.5


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(-1, keepdims=True)


def _attend(q: np.ndarray, k: np.ndarray, v: np.ndarray, heads: int,
            mask: np.ndarray | None) -> np.ndarray:
    """Scaled dot-product attention; ``q`` (L, d), ``k``/``v`` (S, d); ``mask``
    (L, S) bool, True where a key is visible."""
    L, d = q.shape
    S = k.shape[0]
    dh = d // heads
    qh = q.reshape(L, heads, dh).transpose(1, 0, 2)
    kh = k.reshape(S, heads, dh).transpose(1, 0, 2)
    vh = v.reshape(S, heads, dh).transpose(1, 0, 2)
    s = qh @ kh.transpose(0, 2, 1) / math.sqrt(dh)
    if mask is not None:
        s = np.where(mask[None], s, -np.inf)
    return (_softmax(s) @ vh).transpose(1, 0, 2).reshape(L, d)


def expected_shapes(config: Mapping[str, Any], *, feature_dim: int, n_card_features: int,
                    n_token_float: int, n_row_card: int, max_plays: int) -> dict[str, tuple]:
    d = int(config["d"])
    xh = int(config["x_hidden"])
    out: dict[str, tuple] = {
        "card_id": (N_CARDS, d), "null_kv": (1, 1, d),
        "card_feat.weight": (d, n_card_features), "card_feat.bias": (d,),
        "att_proj.weight": (d, d),
        "tok_meta.weight": (d, 4 + 5 + n_token_float + 4), "tok_meta.bias": (d,),
        "trick_emb.weight": (25, d), "rel_emb.weight": (4, d), "pos_emb.weight": (max_plays, d),
        "enc_norm.weight": (d,), "enc_norm.bias": (d,),
        "x_mlp.0.weight": (xh, feature_dim + 4), "x_mlp.0.bias": (xh,),
        "x_mlp.2.weight": (xh, xh), "x_mlp.2.bias": (xh,),
        "x_logits.weight": (N_CARDS * N_RECV, xh), "x_logits.bias": (N_CARDS * N_RECV,),
        "x_to_q.weight": (d, xh), "x_to_q.bias": (d,),
        "row_card.weight": (d, n_row_card + N_RECV), "row_card.bias": (d,),
        "out.0.weight": (d,), "out.0.bias": (d,), "out.1.weight": (N_RECV, d),
        "out.1.bias": (N_RECV,),
    }
    for i in range(int(config["enc_layers"])):
        p = f"encoder.layers.{i}."
        out.update({p + "self_attn.in_proj_weight": (3 * d, d), p + "self_attn.in_proj_bias": (3 * d,),
                    p + "self_attn.out_proj.weight": (d, d), p + "self_attn.out_proj.bias": (d,),
                    p + "linear1.weight": (2 * d, d), p + "linear1.bias": (2 * d,),
                    p + "linear2.weight": (d, 2 * d), p + "linear2.bias": (d,),
                    p + "norm1.weight": (d,), p + "norm1.bias": (d,),
                    p + "norm2.weight": (d,), p + "norm2.bias": (d,)})
    for i in range(int(config["xattn_layers"])):
        out.update({f"kv.{i}.weight": (2 * d, d), f"kv.{i}.bias": (2 * d,),
                    f"xattn.{i}.q.weight": (d, d), f"xattn.{i}.q.bias": (d,),
                    f"xattn.{i}.o.weight": (d, d), f"xattn.{i}.o.bias": (d,),
                    f"ln_q.{i}.weight": (d,), f"ln_q.{i}.bias": (d,),
                    f"ff.{i}.0.weight": (d,), f"ff.{i}.0.bias": (d,),
                    f"ff.{i}.1.weight": (2 * d, d), f"ff.{i}.1.bias": (2 * d,),
                    f"ff.{i}.3.weight": (d, 2 * d), f"ff.{i}.3.bias": (d,)})
    if config["card_self_attn"]:
        out.update({"self_ln.weight": (d,), "self_ln.bias": (d,),
                    "self_attn.in_proj_weight": (3 * d, d), "self_attn.in_proj_bias": (3 * d,),
                    "self_attn.out_proj.weight": (d, d), "self_attn.out_proj.bias": (d,),
                    "self_ff.0.weight": (d,), "self_ff.0.bias": (d,),
                    "self_ff.1.weight": (2 * d, d), "self_ff.1.bias": (2 * d,),
                    "self_ff.3.weight": (d, 2 * d), "self_ff.3.bias": (d,)})
    return out


#: the input widths this runtime is built for (``train.belief_history`` /
#: ``train.belief_labels`` / ``train.belief_seq``); a package records them and
#: the loader refuses a package whose widths differ
DIMS = {"feature_dim": 1111, "n_card_features": 11, "n_token_float": 10, "n_row_card": 17,
        "max_plays": 100}


class BeliefNumpy:
    """A validated, read-only S17 belief model."""

    def __init__(self, config: Mapping[str, Any], weights: Mapping[str, np.ndarray],
                 metadata: Mapping[str, Any], dtype=np.float32):
        self.config = {k: config[k] for k in CONFIG_KEYS}
        self.metadata = dict(metadata)
        self.temperature = float(self.metadata.get("temperature", 1.0))
        if not (0.1 <= self.temperature <= 10.0):
            raise BeliefNumpyError("temperature out of range")
        want = expected_shapes(self.config, **DIMS)
        if set(weights) != set(want):
            raise BeliefNumpyError(f"weights differ from the config: "
                                   f"missing {sorted(set(want) - set(weights))[:3]}, "
                                   f"extra {sorted(set(weights) - set(want))[:3]}")
        w = {}
        for k, shape in want.items():
            a = np.asarray(weights[k], dtype)
            if a.shape != shape or not np.isfinite(a).all():
                raise BeliefNumpyError(f"{k}: shape {a.shape} != {shape} or non-finite")
            a = a.copy()
            a.setflags(write=False)
            w[k] = a
        self.w = w
        self.dtype = np.dtype(dtype)
        self._eye = {n: np.eye(n, dtype=dtype) for n in (4, 5)}
        self.d = int(self.config["d"])
        self.heads = int(self.config["heads"])
        self.package_sha256: str | None = None

    def __deepcopy__(self, memo):
        # immutable (read-only weights): a bot snapshot shares it
        return self

    # ---------------------------------------------------------------- forward
    def _mha(self, prefix: str, x: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
        w = self.w
        d = self.d
        qkv = x @ w[prefix + "in_proj_weight"].T + w[prefix + "in_proj_bias"]
        out = _attend(qkv[:, :d], qkv[:, d:2 * d], qkv[:, 2 * d:], self.heads, mask)
        return out @ w[prefix + "out_proj.weight"].T + w[prefix + "out_proj.bias"]

    def encode_history(self, inp: Mapping[str, np.ndarray]) -> np.ndarray:
        """``(T, d)``: the actor-frame encoder states of the plays before the decision."""
        w = self.w
        ti = np.asarray(inp["tok_int"], np.int64)
        T = len(ti)
        if T == 0:
            return np.zeros((0, self.d), self.dtype)
        if T > DIMS["max_plays"]:
            raise BeliefNumpyError("too many plays")
        ce = self._card_table(inp)
        seat, pos, trick, lead = ti[:, 0], ti[:, 1], ti[:, 2], ti[:, 3]
        role = (seat - int(inp["banker"])) % 4
        f = self.dtype
        meta = np.concatenate([self._eye[4][pos], self._eye[5][lead],
                               np.asarray(inp["tok_f"], f), self._eye[4][role]], -1)
        x = (meta @ w["tok_meta.weight"].T + w["tok_meta.bias"] + w["trick_emb.weight"][trick]
             + np.asarray(inp["tok_cards"], f) @ ce
             + (np.asarray(inp["tok_att"], f) @ ce) @ w["att_proj.weight"].T
             + w["pos_emb.weight"][:T])
        x = x + w["rel_emb.weight"][(seat - int(inp["seat"])) % 4]
        causal = np.tril(np.ones((T, T), bool))
        for i in range(int(self.config["enc_layers"])):
            p = f"encoder.layers.{i}."
            x = x + self._mha(p + "self_attn.", _ln(x, w[p + "norm1.weight"], w[p + "norm1.bias"]),
                              causal)
            h = _ln(x, w[p + "norm2.weight"], w[p + "norm2.bias"])
            h = np.maximum(h @ w[p + "linear1.weight"].T + w[p + "linear1.bias"], 0.0)
            x = x + h @ w[p + "linear2.weight"].T + w[p + "linear2.bias"]
        return _ln(x, w["enc_norm.weight"], w["enc_norm.bias"])

    def _card_table(self, inp) -> np.ndarray:
        w = self.w
        return (w["card_id"] + np.asarray(inp["card_feat"], self.dtype) @ w["card_feat.weight"].T
                + w["card_feat.bias"])

    def logits(self, inp: Mapping[str, np.ndarray], enc: np.ndarray | None = None) -> np.ndarray:
        """``(54, 4)`` raw logits for one decision (``decision_inputs``)."""
        w = self.w
        d, h = self.d, self.heads
        if enc is None:
            enc = self.encode_history(inp)
        ce = self._card_table(inp)
        X = np.asarray(inp["X"], self.dtype)
        g = np.maximum(X @ w["x_mlp.0.weight"].T + w["x_mlp.0.bias"], 0.0)
        g = np.maximum(g @ w["x_mlp.2.weight"].T + w["x_mlp.2.bias"], 0.0)
        out = (g @ w["x_logits.weight"].T + w["x_logits.bias"]).reshape(N_CARDS, N_RECV)
        M = np.asarray(inp["M"], bool)
        rc = np.concatenate([np.asarray(inp["row_card"], self.dtype), M.astype(self.dtype)], -1)
        q = ce + rc @ w["row_card.weight"].T + w["row_card.bias"] + (
            g @ w["x_to_q.weight"].T + w["x_to_q.bias"])
        mem = np.concatenate([w["null_kv"][0], enc], 0)                      # T+1, d
        for i in range(int(self.config["xattn_layers"])):
            kv = mem @ w[f"kv.{i}.weight"].T + w[f"kv.{i}.bias"]
            qi = _ln(q, w[f"ln_q.{i}.weight"], w[f"ln_q.{i}.bias"])
            qi = qi @ w[f"xattn.{i}.q.weight"].T + w[f"xattn.{i}.q.bias"]
            a = _attend(qi, kv[:, :d], kv[:, d:], h, None)
            q = q + a @ w[f"xattn.{i}.o.weight"].T + w[f"xattn.{i}.o.bias"]
            f = _ln(q, w[f"ff.{i}.0.weight"], w[f"ff.{i}.0.bias"])
            f = _gelu(f @ w[f"ff.{i}.1.weight"].T + w[f"ff.{i}.1.bias"])
            q = q + f @ w[f"ff.{i}.3.weight"].T + w[f"ff.{i}.3.bias"]
        if self.config["card_self_attn"]:
            x = _ln(q, w["self_ln.weight"], w["self_ln.bias"])
            q = q + self._mha("self_attn.", x, None)
            f = _ln(q, w["self_ff.0.weight"], w["self_ff.0.bias"])
            f = _gelu(f @ w["self_ff.1.weight"].T + w["self_ff.1.bias"])
            q = q + f @ w["self_ff.3.weight"].T + w["self_ff.3.bias"]
        o = _ln(q, w["out.0.weight"], w["out.0.bias"])
        return out + o @ w["out.1.weight"].T + w["out.1.bias"]

    def marginals(self, inp: Mapping[str, np.ndarray]) -> np.ndarray:
        """``(54, 4)``: per hidden copy, a distribution over its feasible
        receivers (temperature applied); a card with no unknown copy is all zero."""
        M = np.asarray(inp["M"], bool)
        z = np.where(M, self.logits(inp).astype(np.float64) / self.temperature, -np.inf)
        top = z.max(-1, keepdims=True)
        top = np.where(np.isfinite(top), top, 0.0)
        e = np.where(M, np.exp(z - top), 0.0)
        s = e.sum(-1, keepdims=True)
        return np.where(s > 0, e / np.where(s > 0, s, 1.0), 0.0)


# ------------------------------------------------------------------ package

def save_package(path: str | os.PathLike, config: Mapping[str, Any],
                 weights: Mapping[str, np.ndarray], metadata: Mapping[str, Any]) -> str:
    """Write a package (validated by constructing it first); returns its sha256."""
    model = BeliefNumpy(config, weights, metadata)
    arrays = {f"w:{k}": np.asarray(v, np.float32) for k, v in weights.items()}
    arrays["schema"] = np.asarray(SCHEMA)
    arrays["config"] = np.asarray(json.dumps(model.config, sort_keys=True))
    arrays["metadata"] = np.asarray(json.dumps(dict(metadata, dims=DIMS), sort_keys=True))
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, **arrays)
    os.replace(tmp, path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_belief_numpy(path: str | os.PathLike, sha256: str | None = None,
                      dtype=np.float32) -> BeliefNumpy:
    """Load and validate a package; ``sha256`` (when given) must match its bytes."""
    p = Path(path)
    if p.stat().st_size > PACKAGE_MAX_BYTES:
        raise BeliefNumpyError("package too large")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if sha256 is not None and digest != sha256:
        raise BeliefNumpyError(f"package sha256 {digest} != expected {sha256}")
    import io
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        if str(z["schema"]) != SCHEMA:
            raise BeliefNumpyError(f"schema {z['schema']} != {SCHEMA}")
        config = json.loads(str(z["config"]))
        metadata = json.loads(str(z["metadata"]))
        if metadata.get("dims") != DIMS:
            raise BeliefNumpyError("package input widths differ from this runtime")
        weights = {k[2:]: z[k] for k in z.files if k.startswith("w:")}
    model = BeliefNumpy(config, weights, metadata, dtype=dtype)
    model.package_sha256 = digest
    return model


# ------------------------------------------------------------------ live inputs

def history_tokens(rnd, refusals: Sequence[Any] = ()) -> dict[str, np.ndarray]:
    """The round's plays so far as tokens (``train.belief_history`` columns),
    rebuilt from ``rnd.history`` and ``rnd.trick``.  A refused throw's attempt
    comes from the actor's refusal ledger (``ai.refusal.Refusal``)."""
    from collections import Counter
    from ..engine.cards import SUITS, TRUMP, points
    from ..rl.encode import CARD_INDEX
    from ..train.belief_history import N_TOKEN_FLOAT, _winner_so_far
    eff_order = tuple(SUITS) + (TRUMP,)
    o = rnd.ordering
    attempts = {(int(r.trick_index), int(r.seat)): tuple(r.attempted) for r in refusals}
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick is not None and rnd.trick.plays else [])
    ints, fs, cards, atts = [], [], [], []
    for t_index, trick in enumerate(tricks):
        lead_eff = o.eff_suit(trick.plays[0].cards[0])
        for pos, tp in enumerate(trick.plays):
            played = list(tp.cards)
            before = type(trick)(leader=trick.leader, plays=list(trick.plays[:pos]))
            after = type(trick)(leader=trick.leader, plays=list(trick.plays[:pos + 1]))
            prev_winner = _winner_so_far(before, o) if pos else None
            now_winner = _winner_so_far(after, o)
            attempted = attempts.get((t_index, int(tp.seat))) if pos == 0 else None
            failed = attempted is not None and Counter(attempted) != Counter(played)
            n_lead = sum(o.eff_suit(c) == lead_eff for c in played)
            f = np.zeros(N_TOKEN_FLOAT, np.float32)
            f[0] = len(played) / 8.0
            f[1] = n_lead / len(played)
            f[2] = all(o.eff_suit(c) == TRUMP for c in played)
            f[3] = pos > 0 and n_lead < len(played)
            f[4] = pos > 0 and now_winner == tp.seat
            if prev_winner is not None:
                f[5] = (prev_winner - tp.seat) % 4 == 2
                f[6] = (prev_winner - tp.seat) % 2 == 1
            f[7] = sum(points(c) for c in played) / 25.0
            f[8] = sum(points(c) for p in trick.plays[:pos] for c in p.cards) / 50.0
            f[9] = failed
            c = np.zeros(N_CARDS, np.float32)
            for code in played:
                c[CARD_INDEX[code]] += 1
            a = np.zeros(N_CARDS, np.float32)
            if failed:
                for code in attempted:
                    a[CARD_INDEX[code]] += 1
            ints.append((int(tp.seat), pos, t_index, eff_order.index(lead_eff)))
            fs.append(f)
            cards.append(c)
            atts.append(a)
    T = len(ints)
    return {"tok_int": np.asarray(ints, np.int64).reshape(T, 4),
            # the extract stores token floats at float16
            "tok_f": np.asarray(fs, np.float16).astype(np.float32).reshape(T, N_TOKEN_FLOAT),
            "tok_cards": np.asarray(cards, np.float32).reshape(T, N_CARDS),
            "tok_att": np.asarray(atts, np.float32).reshape(T, N_CARDS)}


def decision_inputs(rnd, seat: int, refusals: Sequence[Any] = (), mem=None) -> dict[str, Any]:
    """Everything the model reads at one live decision, plus the residual
    bookkeeping a world sampler needs: ``n_c`` (unknown copies per card),
    ``sizes`` (unknown slots per receiver) and ``K`` (pinned copies per card and
    receiver, placed with their holder in every world)."""
    from ..train.belief_eval import known_counts
    from ..train.belief_history import card_features
    from ..train.belief_labels import (actor_memory, belief_features, feasible_mask,
                                       hidden_counts, receiver_sizes)
    from ..train.belief_seq import row_card_planes
    if mem is None:
        mem = actor_memory(rnd, seat, refusals)
    x = belief_features(rnd, seat, refusals, mem=mem).astype(np.float16).astype(np.float32)
    K = known_counts(x[None])[0]
    n_c = hidden_counts(mem) - K.sum(-1)
    sizes = receiver_sizes(rnd, seat, mem).astype(np.int64) - K.sum(0)
    if (n_c < 0).any() or (sizes < 0).any():
        raise BeliefNumpyError("pinned copies exceed the hidden copies or a receiver")
    M = feasible_mask(rnd, seat, mem) & (n_c > 0)[:, None] & (sizes > 0)[None, :]
    inp = history_tokens(rnd, refusals)
    inp.update({
        "card_feat": card_features(rnd.ordering).astype(np.float16).astype(np.float32),
        "banker": int(rnd.banker), "seat": int(seat),
        "X": np.concatenate([x, sizes.astype(np.float32) / 25.0]),
        "row_card": row_card_planes(x[None])[0], "M": M,
        "n_c": n_c, "sizes": sizes, "K": K,
    })
    return inp


# ------------------------------------------------------------------ served proposal

#: the proposal's identity in a recipe: the marginals, projected to the receiver
#: sizes, drawn copy by copy under Hall's condition (sizes, voids, pins exact)
PROPOSAL = "s17-marginals-sinkhorn-hall-v1"
#: the same proposal with the bury-rule kitty (`ai.kitty_rule`): a seat that
#: is not the banker re-splits each world's banker hand plus kitty with the
#: served bury's incumbent rule, so the kitty is the discard the rule makes
#: from what the marginals dealt the banker, not eight cards drawn on their
#: own kitty mass
PROPOSAL_KITTY_RULE = "s17-marginals-sinkhorn-hall-kitty-rule-v1"
#: batches the kitty rule may draw per refill before the rest of the refill
#: comes from the plain draw (so a state the rule rarely accepts cannot stall
#: the search); each batch is ``batch`` worlds
KITTY_RULE_BATCHES = 16
#: the per-decision preparation (featurize + forward + projection) must finish
#: within this many seconds, else the caller falls back to its own draw
PREP_SECONDS = 0.25

_CODES: list[str] | None = None


def _codes() -> list[str]:
    global _CODES
    if _CODES is None:
        from ..rl.encode import CARD_INDEX
        _CODES = sorted(CARD_INDEX, key=CARD_INDEX.get)
    return _CODES


def draw_mask(inp: Mapping[str, Any], rnd, seat: int, forbidden: Mapping | None) -> np.ndarray:
    """``inp["M"]`` with every forbidden (card, seat) receiver removed."""
    M = np.array(inp["M"], bool)
    if not forbidden:
        return M
    from ..rl.encode import CARD_INDEX
    for (other, _suit), codes in forbidden.items():
        rel = (int(other) - int(seat)) % 4
        if rel == 0:
            raise BeliefNumpyError("a draw constraint names the acting seat")
        for code in codes:
            M[CARD_INDEX[code], rel - 1] = False
    return M


class BeliefProposal:
    """One decision's world proposal for ``ai.history_legality``'s ``propose``
    hook: ``(rnd, seat, mem) -> (hands, buried)`` with ``hands`` a dict over the
    three other seats (the shape of ``MCBot._sample_hands``).

    The marginals are computed once (at construction); worlds are drawn
    ``batch`` at a time and handed out one per call.  Every world places each
    unknown copy on a receiver the public facts allow, fills every receiver to
    its size, keeps the public pins with their holders and the actor's own
    burial when it is known.  ``kitty_rule`` selects the bury-rule kitty
    (``PROPOSAL_KITTY_RULE``): for a seat that is not the banker, each drawn
    world's banker hand plus kitty is re-split by `ai.kitty_rule.
    kitty_rule_split`, a world the rule rejects is redrawn, and after
    ``KITTY_RULE_BATCHES`` batches the rest of the refill is the plain draw
    (counted in ``kitty_fallback``); off, the draw and its stream are
    ``PROPOSAL``'s, unchanged.  Errors propagate: the caller falls back."""

    def __init__(self, model: BeliefNumpy, rnd, seat: int, refusals: Sequence[Any] = (), *,
                 seed: int, batch: int, forbidden: Mapping | None = None,
                 check_budget=None, kitty_rule: bool = False):
        from ..train.belief_seq import project_sizes
        import time
        t0 = time.perf_counter()
        if check_budget is not None:
            check_budget()
        self.rnd, self.seat = rnd, int(seat)
        self.kitty_rule = bool(kitty_rule)
        # the banker's own draw-constraint codes, which the rule's hand may not hold
        self.banker_forbidden = frozenset(
            code for (other, _suit), codes in (forbidden or {}).items()
            if int(other) == int(rnd.banker) for code in codes)
        self.kitty_worlds = self.kitty_rejections = self.kitty_fallback = 0
        self.inp = decision_inputs(rnd, seat, refusals)
        if check_budget is not None:
            check_budget()
        P = model.marginals(self.inp)
        # the model reads the public mask; the draw also honours the forbidden
        # cards (``ai.history_legality.draw_constraints``: {(seat, effective
        # suit): codes}) by masking those receivers after the model
        if check_budget is not None:
            check_budget()
        self.M = draw_mask(self.inp, rnd, seat, forbidden)
        P = np.where(self.M, P, 0.0)
        self.Q = project_sizes(P, self.inp["n_c"], self.inp["sizes"], self.M)
        if check_budget is not None:
            check_budget()
        self.kitty_hidden = bool(self.inp["M"][:, 3].any()) or int(self.inp["sizes"][3]) > 0
        self.rng = np.random.default_rng(int(seed))
        self.batch = int(batch)
        self.queue: list = []
        self.drawn = 0
        self.prep_seconds = time.perf_counter() - t0
        if self.prep_seconds > PREP_SECONDS:
            raise BeliefNumpyError(f"belief preparation took {self.prep_seconds:.3f}s")

    def _draw(self) -> list:
        """One batch of plain worlds, in draw order."""
        from ..train.belief_seq import sample_worlds
        inp, rnd, seat = self.inp, self.rnd, self.seat
        W = sample_worlds(self.Q, inp["n_c"], self.M, inp["sizes"], self.batch, self.rng)
        codes = _codes()
        idx = np.arange(N_CARDS)
        K = inp["K"]
        out = []
        for w in W:
            hands = {}
            for rel in (1, 2, 3):
                cnt = w[:, rel - 1].astype(np.int64) + K[:, rel - 1]
                hands[(seat + rel) % 4] = [codes[c] for c in np.repeat(idx, cnt)]
            if self.kitty_hidden:
                buried = [codes[c] for c in np.repeat(idx, w[:, 3].astype(np.int64))]
            else:
                buried = list(rnd.buried)
            out.append((hands, buried))
        return out

    def _refill(self, mem=None) -> None:
        rnd, seat = self.rnd, self.seat
        banker = int(rnd.banker)
        if not (self.kitty_rule and self.kitty_hidden and seat != banker):
            worlds = self._draw()
        else:
            from .kitty_rule import kitty_rule_split
            if mem is None:
                raise BeliefNumpyError("the kitty rule needs the actor's memory")
            played = sorted(mem.played_by[banker].elements())
            order = {code: i for i, code in enumerate(_codes())}
            worlds, rejected = [], []
            for _ in range(KITTY_RULE_BATCHES):
                rejected = []
                for hands, buried in self._draw():
                    if len(worlds) == self.batch:
                        break
                    split = kitty_rule_split(rnd, mem, hands[banker] + buried, played,
                                             self.banker_forbidden, len(buried))
                    if split is None:
                        self.kitty_rejections += 1
                        rejected.append((hands, buried))
                        continue
                    hand, kitty = split
                    worlds.append(({**hands, banker: sorted(hand, key=order.get)},
                                   sorted(kitty, key=order.get)))
                    self.kitty_worlds += 1
                if len(worlds) == self.batch:
                    break
            # the budget is spent: the last batch's rejected worlds, plain, fill the rest
            rest = rejected[:self.batch - len(worlds)]
            self.kitty_fallback += len(rest)
            worlds.extend(rest)
        self.queue.extend(worlds)
        self.queue.reverse()

    def __call__(self, rnd, seat, mem):
        if rnd is not self.rnd or int(seat) != self.seat:
            raise BeliefNumpyError("a proposal serves the decision it was built for")
        if not self.queue:
            self._refill(mem)
        self.drawn += 1
        return self.queue.pop()
