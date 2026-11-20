"""Banker side-suit void head and the void-first world draw.

The belief model gives one independent receiver distribution per card copy, so
the worlds it draws rarely leave the banker without a side suit even when the
banker buried that suit away.  This head reads the belief model's own final
card states and row context and predicts, for each of the four side suits
(effective suits S, H, D, C that are not trump), the probability that the
banker holds no hidden copy of it.

A suit is a *candidate* at a decision when the actor is not the banker, at
least one hidden copy of the suit may be with the banker (the draw mask), and
no copy of it is publicly pinned to the banker.  Off the candidates the head's
output is undefined and never read.

``VoidFirst`` turns the head's probabilities into a world draw: each world first
draws, per candidate suit, whether the banker is void in it, then draws its
copies from the belief marginals with the banker's receiver masked out of the
void suits (the same forbidden-receiver path the history constraints use).
The probability of forcing the void is corrected for the void the plain draw
already produces, so a world's banker void rate is the head's probability.

Package (``.npz``): ``schema``, ``config`` and ``metadata`` (JSON strings) plus
the MLP weights ``w:l{0,1,2}.weight`` / ``w:l{0,1,2}.bias`` (torch layout).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

SCHEMA = "shengji-void-head-v1"
N_CARDS = 54
N_RECV = 4
N_SIDE = 4
#: per suit: log P(void) and expected copies under independent copies, hidden
#: copies the banker may hold, all hidden copies of the suit, the banker's and
#: the kitty's unknown slots, all hidden copies, the banker's receiver (3)
N_SCALARS = 10
PACKAGE_MAX_BYTES = 8 * 1024 * 1024
#: the clip of a copy's probability of NOT being with the banker in log P(void)
LOG_FLOOR = 1e-6


class VoidHeadError(ValueError):
    """Malformed package or inputs."""


def side_suits(card_feat: np.ndarray) -> np.ndarray:
    """``(..., 54, 4)`` bool: each card's effective side suit (S, H, D, C); trump cards are in none."""
    return np.asarray(card_feat)[..., 1:5] > 0.5


def candidates(M: np.ndarray, n_c: np.ndarray, K: np.ndarray, eff: np.ndarray,
               r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(cand (B,4) bool, w (B,54,4))``: the candidate suits and each card's hidden copies the banker may hold.

    ``M`` (B,54,4) the feasible mask, ``n_c`` (B,54) hidden copies, ``K`` (B,54,4) pinned copies, ``eff``
    (B,54,4) side suits, ``r`` (B,) the banker's receiver index (0..2)."""
    idx = np.arange(len(r))
    Mb = np.asarray(M, bool)[idx, :, r] & (np.asarray(n_c) > 0)
    w = (np.asarray(n_c, np.float64) * Mb)[:, :, None] * eff
    pinned = (np.asarray(K, np.float64)[idx, :, r][:, :, None] * eff).sum(1)
    return (w.sum(1) > 0) & (pinned == 0), w


def features(h: np.ndarray, g: np.ndarray, P: np.ndarray, M: np.ndarray, n_c: np.ndarray,
             sizes: np.ndarray, K: np.ndarray, card_feat: np.ndarray, r: np.ndarray):
    """``(x (B,4,d+dg+N_SCALARS) float32, cand (B,4) bool)`` for B decisions.

    ``h`` (B,54,d): the belief model's final card states after its output layer norm; ``g`` (B,dg): its row
    context; ``P`` (B,54,4): its marginals; the rest as `candidates`, ``sizes`` (B,4) unknown slots."""
    h = np.asarray(h, np.float64)
    B = len(h)
    idx = np.arange(B)
    r = np.asarray(r, np.int64)
    eff = side_suits(card_feat).astype(np.float64)
    cand, w = candidates(M, n_c, K, eff, r)
    n_c = np.asarray(n_c, np.float64)
    hid = w.sum(1)                                                            # B,4
    pool = np.einsum("bcs,bcd->bsd", w, h) / np.maximum(hid, 1.0)[:, :, None]
    Pb = np.asarray(P, np.float64)[idx, :, r]
    lpv = np.einsum("bc,bcs->bs", n_c * np.log(np.clip(1.0 - Pb, LOG_FLOOR, 1.0)), eff)
    exp = np.einsum("bc,bcs->bs", n_c * Pb, eff)
    allh = np.einsum("bc,bcs->bs", n_c, eff)
    sizes = np.asarray(sizes, np.float64)
    per_row = np.stack([sizes[idx, r] / 25.0, sizes[:, 3] / 8.0, n_c.sum(1) / 100.0], 1)   # B,3
    onehot = np.eye(3)[r]
    scal = np.concatenate([np.stack([np.maximum(lpv, -20.0) / 4.0, exp / 4.0, hid / 8.0, allh / 8.0], -1),
                           np.broadcast_to(per_row[:, None], (B, N_SIDE, 3)),
                           np.broadcast_to(onehot[:, None], (B, N_SIDE, 3))], -1)
    gg = np.broadcast_to(np.asarray(g, np.float64)[:, None], (B, N_SIDE, np.shape(g)[-1]))
    return np.concatenate([pool, gg, scal], -1).astype(np.float32), cand


class VoidHead:
    """A validated, read-only void head: ``probs(x) -> (B,4)`` P(banker void in suit)."""

    def __init__(self, config: Mapping[str, Any], weights: Mapping[str, np.ndarray],
                 metadata: Mapping[str, Any]):
        self.config = {"in_dim": int(config["in_dim"]), "hidden": [int(x) for x in config["hidden"]]}
        self.metadata = dict(metadata)
        dims = [self.config["in_dim"]] + self.config["hidden"] + [1]
        want = {}
        for i in range(len(dims) - 1):
            want[f"l{i}.weight"] = (dims[i + 1], dims[i])
            want[f"l{i}.bias"] = (dims[i + 1],)
        if set(weights) != set(want):
            raise VoidHeadError(f"weights differ from the config: {sorted(set(weights) ^ set(want))[:4]}")
        self.w = {}
        for k, shape in want.items():
            a = np.array(weights[k], np.float32)
            if a.shape != shape or not np.isfinite(a).all():
                raise VoidHeadError(f"{k}: shape {a.shape} != {shape} or non-finite")
            a.setflags(write=False)
            self.w[k] = a
        self.n_layers = len(dims) - 1
        self.package_sha256: str | None = None

    def __deepcopy__(self, memo):
        return self

    def logits(self, x: np.ndarray) -> np.ndarray:
        z = np.asarray(x, np.float32)
        for i in range(self.n_layers):
            z = z @ self.w[f"l{i}.weight"].T + self.w[f"l{i}.bias"]
            if i < self.n_layers - 1:
                z = np.maximum(z, 0.0)
        return z[..., 0]

    def probs(self, x: np.ndarray) -> np.ndarray:
        z = self.logits(x).astype(np.float64)
        return 1.0 / (1.0 + np.exp(-z))


def save_package(path: str | os.PathLike, config: Mapping[str, Any], weights: Mapping[str, np.ndarray],
                 metadata: Mapping[str, Any]) -> str:
    """Write a package (validated by constructing it first); returns its sha256."""
    head = VoidHead(config, weights, metadata)
    arrays = {f"w:{k}": np.asarray(v, np.float32) for k, v in head.w.items()}
    arrays["schema"] = np.asarray(SCHEMA)
    arrays["config"] = np.asarray(json.dumps(head.config, sort_keys=True))
    arrays["metadata"] = np.asarray(json.dumps(dict(metadata), sort_keys=True))
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, **arrays)
    os.replace(tmp, path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_void_head(path: str | os.PathLike, sha256: str | None = None) -> VoidHead:
    """Load and validate a package; ``sha256`` (when given) must match its bytes."""
    p = Path(path)
    if p.stat().st_size > PACKAGE_MAX_BYTES:
        raise VoidHeadError("package too large")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if sha256 is not None and digest != sha256:
        raise VoidHeadError(f"package sha256 {digest} != expected {sha256}")
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        if str(z["schema"]) != SCHEMA:
            raise VoidHeadError(f"schema {z['schema']} != {SCHEMA}")
        config = json.loads(str(z["config"]))
        metadata = json.loads(str(z["metadata"]))
        weights = {k[2:]: z[k] for k in z.files if k.startswith("w:")}
    head = VoidHead(config, weights, metadata)
    head.package_sha256 = digest
    return head


# ------------------------------------------------------------------ void-first draw

def hall_feasible(M: np.ndarray, n_c: np.ndarray, sizes: np.ndarray) -> bool:
    """Every hidden copy can be placed on a feasible receiver with every receiver filled to its size."""
    from ..train.belief_seq import _SUB_OF, _SUBSETS
    types = (np.asarray(M, bool) * (1 << np.arange(N_RECV))).sum(-1)
    tc = np.bincount(types, weights=np.asarray(n_c, np.float64), minlength=16)
    if tc[0] > 0:
        return False
    need = _SUB_OF.astype(np.float64) @ tc
    cap = _SUBSETS.astype(np.float64) @ np.asarray(sizes, np.float64)
    return bool((cap >= need).all()) and float(np.asarray(n_c).sum()) == float(np.asarray(sizes).sum())


def plain_void_prob(Q: np.ndarray, n_c: np.ndarray, eff: np.ndarray, r: int) -> np.ndarray:
    """``(4,)``: P(the banker holds no hidden copy of each side suit) under independent copies of ``Q``."""
    lq = np.asarray(n_c, np.float64) * np.log(np.clip(1.0 - np.asarray(Q, np.float64)[:, r], 1e-300, 1.0))
    return np.exp(lq @ eff.astype(np.float64))


class VoidFirst:
    """One decision's void-first plan over the draw mask ``M`` (54,4) and projected marginals ``Q0``.

    ``suits``: the side suits drawn first (candidates under ``M``); ``p``: the head's P(void) per suit;
    ``force``: the per-world probability of masking the banker out of the suit,
    ``clip((p - q) / (1 - q), 0, 1)`` with ``q`` the plain draw's void probability (`plain_void_prob`)."""

    def __init__(self, P: np.ndarray, Q0: np.ndarray, M: np.ndarray, n_c: np.ndarray, sizes: np.ndarray,
                 eff: np.ndarray, r: int, p: np.ndarray, suits: np.ndarray):
        self.P, self.Q0, self.M, self.n_c, self.sizes = P, Q0, np.asarray(M, bool), n_c, sizes
        self.eff, self.r = np.asarray(eff, bool), int(r)
        self.suits = [int(s) for s in np.nonzero(suits)[0]]
        q = plain_void_prob(Q0, n_c, self.eff, self.r)
        self.p = {s: float(p[s]) for s in self.suits}
        self.q = {s: float(q[s]) for s in self.suits}
        self.force = {s: (0.0 if self.q[s] >= 1.0 else
                          float(np.clip((self.p[s] - self.q[s]) / (1.0 - self.q[s]), 0.0, 1.0)))
                      for s in self.suits}
        self._plans: dict[tuple, tuple] = {}

    def pattern_mask(self, pattern: tuple) -> tuple[tuple, np.ndarray]:
        """The feasible pattern actually drawn for ``pattern`` (suits dropped, lowest force first, until
        Hall's condition holds) and its mask."""
        kept = list(pattern)
        order = sorted(kept, key=lambda s: (self.force[s], s))
        while True:
            M = self.M.copy()
            for s in kept:
                M[self.eff[:, s], self.r] = False
            if not kept or hall_feasible(M, self.n_c, self.sizes):
                return tuple(sorted(kept)), M
            kept.remove(order.pop(0))

    def plan(self, pattern: tuple) -> tuple[tuple, np.ndarray, np.ndarray]:
        """``(drawn pattern, mask, projected marginals)`` for a pattern of forced suits (cached)."""
        if pattern not in self._plans:
            from ..train.belief_seq import project_sizes
            kept, M = self.pattern_mask(pattern)
            if not kept:
                self._plans[pattern] = ((), self.M, self.Q0)
            else:
                Pm = np.where(M, self.P, 0.0)
                self._plans[pattern] = (kept, M, project_sizes(Pm, self.n_c, self.sizes, M))
        return self._plans[pattern]

    def draw_patterns(self, n: int, rng: np.random.Generator) -> list[tuple]:
        """One pattern of forced suits per world (uniforms drawn per world and suit, in suit order)."""
        if not self.suits:
            return [()] * n
        u = rng.random((n, len(self.suits)))
        f = np.array([self.force[s] for s in self.suits])
        hit = u < f[None]
        return [tuple(s for s, b in zip(self.suits, row) if b) for row in hit]

    def mixture(self) -> np.ndarray:
        """``(54,4)``: the per-copy marginals of the void-first draw (patterns enumerated exactly)."""
        out = np.zeros_like(np.asarray(self.Q0, np.float64))
        k = len(self.suits)
        for bits in range(1 << k):
            pat = tuple(s for i, s in enumerate(self.suits) if bits >> i & 1)
            pr = 1.0
            for i, s in enumerate(self.suits):
                pr *= self.force[s] if bits >> i & 1 else 1.0 - self.force[s]
            if pr > 0:
                out += pr * self.plan(pat)[2]
        return out


def decision_plan(head: VoidHead, h: np.ndarray, g: np.ndarray, P: np.ndarray, inp: Mapping[str, Any],
                  M_draw: np.ndarray, Q0: np.ndarray) -> VoidFirst | None:
    """The void-first plan of one live decision (None when the actor is the banker or no suit is a candidate).

    ``h``, ``g``, ``P``: the belief forward's card states (54,d), row context (dg,) and marginals (54,4);
    ``inp``: `belief_numpy.decision_inputs`; ``M_draw``: the draw mask (``inp["M"]`` with the history
    constraints removed); ``Q0``: the plain projected marginals."""
    rel = (int(inp["banker"]) - int(inp["seat"])) % 4
    if rel == 0:
        return None
    r = rel - 1
    x, cand = features(h[None], g[None], P[None], inp["M"][None], inp["n_c"][None], inp["sizes"][None],
                       inp["K"][None], inp["card_feat"][None], np.array([r]))
    eff = side_suits(inp["card_feat"])
    cand_draw, _ = candidates(M_draw[None], inp["n_c"][None], inp["K"][None], eff[None].astype(np.float64),
                              np.array([r]))
    suits = cand[0] & cand_draw[0]
    if not suits.any():
        return None
    p = head.probs(x[0])
    return VoidFirst(P, Q0, M_draw, inp["n_c"], inp["sizes"], eff, r, p, suits)


#: the name token of a bot whose belief proposal draws void-first
NAME_TOKEN = "vh"


def install_void_head(bot, path: str | os.PathLike, sha256: str) -> VoidHead:
    """Turn on the void-first draw for ``bot``'s belief proposal (off unless this is called).

    Refuses unless the bot draws from a belief package and the head was trained on that package's
    states (``metadata["belief_package_sha256"]`` equals the bound package's sha256)."""
    belief = getattr(bot, "belief_model", None)
    if belief is None:
        raise VoidHeadError("the bot has no belief package bound")
    if not getattr(bot, "belief_worlds", False):
        raise VoidHeadError("the bot does not draw its worlds from the belief proposal")
    if getattr(bot, "void_head", None) is not None:
        raise VoidHeadError("a void head is already installed")
    head = load_void_head(path, sha256)
    want = head.metadata.get("belief_package_sha256")
    if not want or want != getattr(belief, "package_sha256", None):
        raise VoidHeadError(f"the head was trained on belief package {want!r}, "
                            f"the bot draws from {getattr(belief, 'package_sha256', None)!r}")
    bot.void_head = head
    bot.policy_name = f"{getattr(bot, 'policy_name', None) or type(bot).__name__}-{NAME_TOKEN}{head.package_sha256[:8]}"
    return head
