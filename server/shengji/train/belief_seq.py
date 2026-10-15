"""S17: a history-input belief model (offline, tier-i DEV).

The #1002 models (``belief_eval``) read one summary row per decision and
plateau near +4% hands log-loss over production's sampler.  This model adds the
ORDERED play history (``belief_history``): who led what, who followed with
what, who was winning when, which throws were refused.

Architecture (``HistoryBelief``):

* **cards** -- a per-round card table: a learned id embedding plus the card's
  role under this round's trump (``belief_history.CARD_FEATURES``);
* **history encoder** -- each play is a token (the card table summed over its
  cards, the refused-throw cards, its public play facts, the seat relative to
  the actor and to the banker, the trick and position); a causal transformer
  encodes the round once per actor frame (4 frames), so a decision at ply ``p``
  reads encoder states ``< p`` only;
* **row context** -- an MLP over the #1002 summary row (``belief_labels``
  features) plus the residual receiver sizes; it also emits direct
  ``54 x 4`` logits (the h256x2 baseline lives inside the model);
* **card queries** -- one query per card (card table + the card's own row
  planes + its feasible mask + the row context) cross-attends to the actor's
  history (plus an always-visible null slot), then a self-attention over the 54
  cards, and adds ``4`` logits per card to the direct ones.

``--no-history`` keeps the same network with every history slot masked (null
only): the ablation that isolates what the play ORDER adds.

Training/eval reuse ``belief_eval``'s target, metrics and baselines exactly:
unknown copies only (``residualize``), per-copy cross-entropy over the feasible
receivers, temperature on calib, log-loss / true-holder mass / ECE vs the
production sampler's smoothed marginals and the uniform reference, deal
bootstrap CIs.  Added here: a per-trick table, the permuted-label control, and
**sampled worlds** -- legal worlds drawn from the model's marginals (every hidden
copy placed, receiver sizes and void masks honoured by a Hall-condition
sequential sampler) scored by v83's card agreement.

CLI: ``python -m shengji.train.belief_seq {train,evaluate,latency}``.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .belief_eval import (SUBSETS, copy_terms, deal_bootstrap, fit_scalar, masked_softmax,
                          mean_ll, permute_within_strata, reliability, residualize,
                          sampler_probs, strata_of, summarize, uniform_probs)
from .belief_history import MAX_PLAYS, N_CARD_FEATURES, N_TOKEN_FLOAT
from .belief_history import SCHEMA as HIST_SCHEMA
from .belief_labels import FEATURE_BLOCKS, FEATURE_DIM, KITTY, N_RECV, PHASES, ROLES, phase_of_trick

N_CARDS = 54
ROW_KEYS = ("X", "Y", "M", "sizes", "trick", "role", "deal")
EVAL_KEYS = ROW_KEYS + ("S", "S_n", "decision", "cluster")
HIST_KEYS = ("row_round", "row_ply", "row_seat", "tok_int", "tok_f", "tok_cards", "tok_att",
             "round_n", "card_feat", "banker")
#: the 54-wide planes of the summary row a card query reads for its own card
_OBS_PLANES = 9                                   # hand, played rel0..3, trick 0..2, unseen
_CARD_BLOCKS = ("own_kitty", "declared_cards", "pinned_rel1", "pinned_rel2", "pinned_rel3",
                "throw_unplayed_rel1", "throw_unplayed_rel2", "throw_unplayed_rel3")
N_ROW_CARD = _OBS_PLANES + len(_CARD_BLOCKS)
EPS = 1e-12


class BeliefSeqError(ValueError):
    pass


def _block_at(name: str) -> int:
    at = 0
    for block, width in FEATURE_BLOCKS:
        if block == name:
            return at
        at += width
    raise BeliefSeqError(f"no block {name}")


_ROW_CARD_IDX = np.concatenate(
    [np.arange(_OBS_PLANES * N_CARDS)]
    + [np.arange(_block_at(b), _block_at(b) + N_CARDS) for b in _CARD_BLOCKS])


def row_card_planes(X: np.ndarray) -> np.ndarray:
    """``(N, 54, N_ROW_CARD)``: each card's own entries of the summary row."""
    return np.asarray(X[:, _ROW_CARD_IDX], np.float32).reshape(len(X), N_ROW_CARD, N_CARDS
                                                               ).transpose(0, 2, 1)


# ------------------------------------------------------------------ data

def extract_entries(dirs: Sequence[str], split: str) -> list[dict[str, Any]]:
    """Every chunk of ``split`` with its history file (and both sha256s)."""
    out = []
    for d in dirs:
        man = json.loads((Path(d) / "manifest.json").read_text())
        hman = json.loads((Path(d) / "hist" / "manifest.json").read_text())
        if hman.get("schema") != HIST_SCHEMA:
            raise BeliefSeqError(f"{d}: no history extract")
        if hman["source_extract_manifest_sha256"] != hashlib.sha256(
                (Path(d) / "manifest.json").read_bytes()).hexdigest():
            raise BeliefSeqError(f"{d}: history was built from another extract")
        for c in man["chunks"]:
            e = c["files"].get(split)
            if e is None:
                continue
            out.append({"path": str(Path(d) / e["file"]), "sha256": e["sha256"],
                        "rows": int(e["rows"]), "hist": str(Path(d) / "hist" / e["file"]),
                        "hist_sha256": hman["files"][e["file"]], "dir": d})
    return out


class _Verified:
    def __init__(self):
        self.seen: set[str] = set()
        self.lock = threading.Lock()

    def read(self, path: str, sha: str) -> bytes:
        b = Path(path).read_bytes()
        with self.lock:
            fresh = path not in self.seen
        if fresh:
            if hashlib.sha256(b).hexdigest() != sha:
                raise BeliefSeqError(f"{path}: sha256 mismatch")
            with self.lock:
                self.seen.add(path)
        return b


def load_part(entry: Mapping[str, Any], keys: Sequence[str], verified: _Verified, *,
              sampler_rows_only: bool = False) -> dict[str, np.ndarray]:
    """One chunk's rows (residualized: unknown copies only) joined with its
    history; round arrays keep their chunk-local indices."""
    with np.load(io.BytesIO(verified.read(entry["path"], entry["sha256"]))) as z:
        part = {k: z[k] for k in keys}
    with np.load(io.BytesIO(verified.read(entry["hist"], entry["hist_sha256"]))) as z:
        hist = {k: z[k] for k in HIST_KEYS}
    n = len(part["X"])
    if n != entry["rows"] or len(hist["row_round"]) != n:
        raise BeliefSeqError(f"{entry['path']}: row count mismatch with manifest/history")
    if part["X"].shape[1] != FEATURE_DIM:
        raise BeliefSeqError("feature width differs")
    part.update({k: hist[k] for k in ("row_round", "row_ply", "row_seat")})
    part["_dir"] = np.full(n, entry["dir"], dtype=object)
    if sampler_rows_only:
        keep = part["S_n"] > 0
        part = {k: v[keep] for k, v in part.items()}
    if len(part["X"]):
        residualize(part)
        if np.any((part["Y"] > 0) & ~part["M"]):
            raise BeliefSeqError("a true holder is outside the feasible mask")
        # the actor of a row is the seat of the play it is about to make
        tok_seat = hist["tok_int"][part["row_round"], part["row_ply"], 0]
        if np.any(tok_seat != part["row_seat"]):
            raise BeliefSeqError("history token seat differs from the row's actor")
    part["_rounds"] = {k: hist[k] for k in ("tok_int", "tok_f", "tok_cards", "tok_att", "round_n",
                                           "card_feat", "banker")}
    return part


def concat_parts(parts: Sequence[dict]) -> dict[str, Any]:
    """Rows of several parts with their rounds renumbered into one table."""
    rows: dict[str, list] = {}
    rounds: dict[str, list] = {}
    base = 0
    for p in parts:
        for k, v in p.items():
            if k == "_rounds":
                continue
            rows.setdefault(k, []).append(v + base if k == "row_round" else v)
        for k, v in p["_rounds"].items():
            rounds.setdefault(k, []).append(v)
        base += len(p["_rounds"]["round_n"])
    out = {k: np.concatenate(v) for k, v in rows.items()}
    out["_rounds"] = {k: np.concatenate(v) for k, v in rounds.items()}
    return out


def round_batches(part: Mapping[str, Any], rounds_per_batch: int, rng: np.random.Generator | None,
                  row_frac: float = 1.0):
    """Index batches ``(round ids, row ids)``: whole rounds, shuffled when ``rng``."""
    rr = part["row_round"]
    order = np.argsort(rr, kind="stable")
    uniq, starts = np.unique(rr[order], return_index=True)
    ends = np.append(starts[1:], len(order))
    ids = np.arange(len(uniq))
    if rng is not None:
        ids = rng.permutation(ids)
    for i in range(0, len(ids), rounds_per_batch):
        sel = ids[i:i + rounds_per_batch]
        rows = np.concatenate([order[starts[j]:ends[j]] for j in sel])
        if row_frac < 1.0 and rng is not None:
            rows = rows[rng.random(len(rows)) < row_frac]
            if not len(rows):
                continue
        yield uniq[sel], np.sort(rows)


def make_batch(part: Mapping[str, Any], round_ids: np.ndarray, rows: np.ndarray,
               no_history: bool = False) -> dict[str, np.ndarray]:
    """Numpy tensors for one batch (rounds renumbered 0..R-1)."""
    R = part["_rounds"]
    local = {int(r): i for i, r in enumerate(round_ids)}
    T = int(max(1, R["round_n"][round_ids].max()))
    X = np.asarray(part["X"][rows], np.float32)
    sizes = part["sizes"][rows].astype(np.float32)
    return {
        "tok_int": R["tok_int"][round_ids, :T].astype(np.int64),
        "tok_f": R["tok_f"][round_ids, :T].astype(np.float32),
        "tok_cards": R["tok_cards"][round_ids, :T].astype(np.float32),
        "tok_att": R["tok_att"][round_ids, :T].astype(np.float32),
        "card_feat": R["card_feat"][round_ids].astype(np.float32),
        "banker": R["banker"][round_ids].astype(np.int64),
        "X": np.concatenate([X, sizes / 25.0], axis=1),
        "row_card": row_card_planes(X),
        "M": part["M"][rows],
        "Y": part["Y"][rows].astype(np.float32),
        "rr": np.asarray([local[int(r)] for r in part["row_round"][rows]], np.int64),
        "seat": part["row_seat"][rows].astype(np.int64),
        "ply": (np.zeros(len(rows), np.int64) if no_history
                else part["row_ply"][rows].astype(np.int64)),
    }


# ------------------------------------------------------------------ model

def build_model(*, d: int = 64, heads: int = 4, enc_layers: int = 1, xattn_layers: int = 2,
                x_hidden: int = 256, card_self_attn: bool = True):
    import torch
    from torch import nn

    class Attn(nn.Module):
        """Multi-head attention with separately supplied (precomputed) K/V."""

        def __init__(self):
            super().__init__()
            self.q = nn.Linear(d, d)
            self.o = nn.Linear(d, d)

        def forward(self, x, k, v, mask=None):
            B, L, _ = x.shape
            h = heads
            q = self.q(x).view(B, L, h, d // h).transpose(1, 2)
            out = torch.nn.functional.scaled_dot_product_attention(q, k, v, attn_mask=mask)
            return self.o(out.transpose(1, 2).reshape(B, L, d))

    class HistoryBelief(nn.Module):
        def __init__(self):
            super().__init__()
            self.config = dict(d=d, heads=heads, enc_layers=enc_layers, xattn_layers=xattn_layers,
                               x_hidden=x_hidden, card_self_attn=card_self_attn)
            self.card_id = nn.Parameter(torch.randn(N_CARDS, d) * 0.1)
            self.card_feat = nn.Linear(N_CARD_FEATURES, d)
            self.att_proj = nn.Linear(d, d, bias=False)
            self.tok_meta = nn.Linear(4 + 5 + N_TOKEN_FLOAT + 4, d)
            self.trick_emb = nn.Embedding(25, d)
            self.rel_emb = nn.Embedding(4, d)
            self.pos_emb = nn.Embedding(MAX_PLAYS, d)
            layer = nn.TransformerEncoderLayer(d, heads, 2 * d, dropout=0.0, batch_first=True,
                                               norm_first=True)
            self.encoder = nn.TransformerEncoder(layer, enc_layers, enable_nested_tensor=False)
            self.enc_norm = nn.LayerNorm(d)
            self.null_kv = nn.Parameter(torch.zeros(1, 1, d))
            self.x_mlp = nn.Sequential(nn.Linear(FEATURE_DIM + 4, x_hidden), nn.ReLU(),
                                       nn.Linear(x_hidden, x_hidden), nn.ReLU())
            self.x_logits = nn.Linear(x_hidden, N_CARDS * N_RECV)
            self.x_to_q = nn.Linear(x_hidden, d)
            self.row_card = nn.Linear(N_ROW_CARD + N_RECV, d)
            self.kv = nn.ModuleList(nn.Linear(d, 2 * d) for _ in range(xattn_layers))
            self.xattn = nn.ModuleList(Attn() for _ in range(xattn_layers))
            self.ln_q = nn.ModuleList(nn.LayerNorm(d) for _ in range(xattn_layers))
            self.ff = nn.ModuleList(nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 2 * d), nn.GELU(),
                                                  nn.Linear(2 * d, d)) for _ in range(xattn_layers))
            if card_self_attn:
                self.self_ln = nn.LayerNorm(d)
                self.self_attn = nn.MultiheadAttention(d, heads, batch_first=True)
                self.self_ff = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 2 * d), nn.GELU(),
                                             nn.Linear(2 * d, d))
            self.out = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, N_RECV))

        def forward(self, b):
            R, T = b["tok_int"].shape[:2]
            ce = self.card_id[None] + self.card_feat(b["card_feat"])          # R,54,d
            ti = b["tok_int"]
            seat, pos, trick, lead = ti[..., 0], ti[..., 1], ti[..., 2], ti[..., 3]
            role = (seat - b["banker"][:, None]) % 4
            meta = torch.cat([nn.functional.one_hot(pos, 4).float(),
                              nn.functional.one_hot(lead, 5).float(), b["tok_f"],
                              nn.functional.one_hot(role, 4).float()], -1)
            base = (self.tok_meta(meta) + self.trick_emb(trick)
                    + torch.bmm(b["tok_cards"], ce) + self.att_proj(torch.bmm(b["tok_att"], ce))
                    + self.pos_emb.weight[:T][None])                          # R,T,d
            frames = torch.arange(4, device=base.device)
            rel = (seat[:, None, :] - frames[None, :, None]) % 4               # R,4,T
            tok = (base[:, None] + self.rel_emb(rel)).reshape(R * 4, T, d)
            causal = torch.triu(torch.ones(T, T, dtype=torch.bool, device=base.device), 1)
            enc = self.enc_norm(self.encoder(tok, mask=causal, is_causal=True))  # R*4,T,d
            # rows
            g = self.x_mlp(b["X"])
            B = g.shape[0]
            logits = self.x_logits(g).view(B, N_CARDS, N_RECV)
            q = (ce[b["rr"]] + self.row_card(torch.cat([b["row_card"], b["M"].float()], -1))
                 + self.x_to_q(g)[:, None])                                   # B,54,d
            frame = b["rr"] * 4 + b["seat"]
            # key t is visible to a row iff t < ply; slot 0 is the always-visible null
            steps = torch.arange(T, device=base.device)
            visible = torch.cat([torch.ones(B, 1, dtype=torch.bool, device=base.device),
                                 steps[None, :] < b["ply"][:, None]], 1)       # B,T+1
            mask = visible[:, None, None, :]                                   # B,1,1,T+1
            h = heads
            for i in range(len(self.xattn)):
                kv = self.kv[i](torch.cat([self.null_kv.expand(R * 4, 1, d), enc], 1))  # R*4,T+1,2d
                kv = kv[frame]                                                # B,T+1,2d
                k, v = kv.split(d, -1)
                k = k.view(B, T + 1, h, d // h).transpose(1, 2)
                v = v.view(B, T + 1, h, d // h).transpose(1, 2)
                q = q + self.xattn[i](self.ln_q[i](q), k, v, mask)
                q = q + self.ff[i](q)
            if hasattr(self, "self_attn"):
                x = self.self_ln(q)
                q = q + self.self_attn(x, x, x, need_weights=False)[0]
                q = q + self.self_ff(q)
            return logits + self.out(q)

    return HistoryBelief()


def to_torch(b: Mapping[str, np.ndarray]):
    import torch
    return {k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in b.items()}


def batch_loss(model, tb):
    import torch
    logits = model(tb).masked_fill(~tb["M"], -1e9)
    logp = torch.log_softmax(logits, -1)
    return -(tb["Y"] * logp).sum(), tb["Y"].sum()


def n_params(model) -> int:
    return int(sum(p.numel() for p in model.parameters()))


# ------------------------------------------------------------------ streaming

class Stream:
    """The train split: chunks in a seeded order per epoch, loaded ahead by
    threads, pooled ``buffer_chunks`` at a time, cut into shuffled whole-round
    batches.  ``permute`` re-permutes labels+masks within (trick, role) strata
    inside each buffer (the permuted control: no real (input, label) pair)."""

    def __init__(self, entries, *, verified: _Verified, threads: int, buffer_chunks: int,
                 rounds_per_batch: int, row_frac: float, no_history: bool, permute: bool):
        self.entries = list(entries)
        self.verified = verified
        self.threads = threads
        self.buffer_chunks = buffer_chunks
        self.rounds_per_batch = rounds_per_batch
        self.row_frac = row_frac
        self.no_history = no_history
        self.permute = permute
        self.rows = sum(e["rows"] for e in self.entries)

    def order(self, seed: int, epoch: int) -> list[int]:
        return np.random.default_rng([seed, epoch]).permutation(len(self.entries)).tolist()

    def batches(self, seed: int, epoch: int, start_buffer: int = 0, prefetch: int = 6):
        """Yields ``(buffer_index, batch dict)``; resumes at ``start_buffer``."""
        order = self.order(seed, epoch)
        groups = [order[i:i + self.buffer_chunks] for i in range(0, len(order), self.buffer_chunks)]
        q: queue.Queue = queue.Queue(maxsize=prefetch)
        done = object()

        def produce():
            try:
                with ThreadPoolExecutor(self.threads) as ex:
                    pending = []
                    gi = start_buffer
                    def submit(g):
                        return [ex.submit(load_part, self.entries[j], ROW_KEYS, self.verified)
                                for j in groups[g]]
                    if gi < len(groups):
                        pending = submit(gi)
                    while gi < len(groups):
                        parts = [f.result() for f in pending]
                        if gi + 1 < len(groups):
                            pending = submit(gi + 1)
                        cat = concat_parts(parts)
                        rng = np.random.default_rng([seed, epoch, gi])
                        if self.permute:
                            perm = permute_within_strata(strata_of(cat["trick"], cat["role"]),
                                                         int(rng.integers(2 ** 31)))
                            cat["Y"], cat["M"] = cat["Y"][perm], cat["M"][perm]
                        for rids, rows in round_batches(cat, self.rounds_per_batch, rng,
                                                        self.row_frac):
                            q.put((gi, make_batch(cat, rids, rows, self.no_history)))
                        gi += 1
                q.put(done)
            except BaseException as exc:
                q.put(exc)
        th = threading.Thread(target=produce, daemon=True)
        th.start()
        while True:
            item = q.get()
            if item is done:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
        th.join()


def load_eval(dirs, split, verified, *, max_rows: int | None = None, seed: int = 0,
              threads: int = 4, log=print) -> dict[str, Any]:
    """Calib/test rows where the sampler was drawn (as ``belief_eval``), with history.
    ``max_rows`` subsamples whole chunks (deals), seeded."""
    entries = extract_entries(dirs, split)
    if max_rows is not None:
        rng = np.random.default_rng(seed)
        picked, n = [], 0
        for i in rng.permutation(len(entries)):
            if n >= max_rows * 4:          # sampler rows are ~1/4 of a chunk's rows
                break
            picked.append(entries[i])
            n += entries[i]["rows"]
        entries = picked
    with ThreadPoolExecutor(threads) as ex:
        parts = list(ex.map(lambda e: load_part(e, EVAL_KEYS, verified, sampler_rows_only=True),
                            entries))
    parts = [p for p in parts if len(p["X"])]
    out = concat_parts(parts)
    log(f"[data] {split}: {len(out['X'])} sampler rows, {len(np.unique(out['deal']))} deals, "
        f"{len(out['_rounds']['round_n'])} rounds", flush=True)
    return out


def predict_logits(model, part, *, no_history: bool, rounds_per_batch: int = 32) -> np.ndarray:
    import torch
    out = np.empty((len(part["X"]), N_CARDS, N_RECV), np.float32)
    model.eval()
    with torch.no_grad():
        for rids, rows in round_batches(part, rounds_per_batch, None):
            out[rows] = model(to_torch(make_batch(part, rids, rows, no_history))).numpy()
    return out


# ------------------------------------------------------------------ legal worlds from marginals

_SUBSETS = np.array([[(s >> r) & 1 for r in range(N_RECV)] for s in range(16)], bool)   # 16,4
_SUB_OF = np.array([[(t & ~s) == 0 for t in range(16)] for s in range(16)], bool)        # S,t: t ⊆ S


def project_sizes(P: np.ndarray, n_c: np.ndarray, sizes: np.ndarray, M: np.ndarray,
                  iters: int = 20) -> np.ndarray:
    """Sinkhorn: rescale receiver columns so expected copies per receiver equal
    its size, rows staying distributions over the feasible receivers."""
    P = np.where(M, np.maximum(P, 1e-9), 0.0)
    P = P / np.maximum(P.sum(-1, keepdims=True), EPS)
    for _ in range(iters):
        col = (P * n_c[:, None]).sum(0)
        scale = np.where(col > 0, sizes / np.maximum(col, EPS), 1.0)
        P = P * scale[None]
        P = P / np.maximum(P.sum(-1, keepdims=True), EPS)
    return P


def sample_worlds(P: np.ndarray, n_c: np.ndarray, M: np.ndarray, sizes: np.ndarray, W: int,
                  rng: np.random.Generator) -> np.ndarray:
    """``(W, 54, 4)`` copy counts: W legal worlds.  Every hidden copy is placed on
    a feasible receiver, every receiver gets exactly its size.  Copies are drawn
    one at a time (a random order per call) from ``P`` restricted to the
    receivers that keep the rest completable (Hall's condition over the 16
    receiver subsets). If no model mass remains, use uniform completable mass."""
    if not np.isfinite(P).all() or (P < 0).any():
        raise BeliefSeqError("world probabilities must be finite and nonnegative")
    copies = np.repeat(np.arange(N_CARDS), n_c.astype(np.int64))
    copies = copies[rng.permutation(len(copies))]
    types = (M[copies] * (1 << np.arange(N_RECV))).sum(-1)                      # per copy
    tc = np.bincount(types, minlength=16).astype(np.int64)
    cap = np.broadcast_to(sizes.astype(np.int64), (W, N_RECV)).copy()
    out = np.zeros((W, N_CARDS, N_RECV), np.int16)
    eye = np.eye(N_RECV, dtype=np.int64)
    for c, t in zip(copies, types):
        tc[t] -= 1
        need = _SUB_OF.astype(np.int64) @ tc                                      # 16
        capS = (cap[:, None, :] - eye[None]) @ _SUBSETS.T.astype(np.int64)       # W,4,16
        ok = (capS >= need[None, None]).all(-1) & M[c][None] & (cap > 0)          # W,4
        w = np.where(ok, P[c][None], 0.0)
        if not ok.any(-1).all():
            raise BeliefSeqError("no completable receiver (infeasible state)")
        # Normalize relative to the largest remaining mass, not an absolute
        # epsilon: tiny but positive feasible mass must still sum to one.
        peak = w.max(-1, keepdims=True)
        w = np.where(peak > 0, w / np.where(peak > 0, peak, 1), ok)
        cdf = np.cumsum(w, -1)
        cdf /= cdf[:, -1:]
        u = rng.random(W)[:, None]
        # Right-open bins skip leading zero mass even when u is exactly zero.
        # The normalized terminal CDF is one; never clip an invalid index.
        r = (cdf <= u).sum(-1)
        if (r >= N_RECV).any() or not ok[np.arange(W), r].all():
            raise BeliefSeqError("categorical draw selected an infeasible receiver")
        out[np.arange(W), c, r] += 1
        cap[np.arange(W), r] -= 1
    return out


def world_agreement(worlds: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """v83's ``oracle_card_agreement`` per world: unknown copies with their true
    receiver (multiset intersection per receiver) over all unknown copies."""
    return np.minimum(worlds, Y[None]).sum((1, 2)) / max(int(Y.sum()), 1)


# ------------------------------------------------------------------ training

def _status(path: str | None, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    if path:
        with open(path, "a") as fh:
            fh.write(line + "\n")


def train(args) -> int:
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = str(out / "status.log")
    verified = _Verified()
    entries = extract_entries(args.data, "train")
    if args.max_train_rows:
        rng = np.random.default_rng(args.seed)
        picked, n = [], 0
        for i in rng.permutation(len(entries)):
            if n >= args.max_train_rows:
                break
            picked.append(entries[i])
            n += entries[i]["rows"]
        entries = picked
    stream = Stream(entries, verified=verified, threads=args.loader_threads,
                    buffer_chunks=args.buffer_chunks, rounds_per_batch=args.rounds_per_batch,
                    row_frac=args.row_frac, no_history=args.no_history, permute=args.permute)
    calib = load_eval(args.data, "calib", verified, max_rows=args.calib_rows, seed=args.seed)
    if args.permute:
        perm = permute_within_strata(strata_of(calib["trick"], calib["role"]), args.seed + 2)
        calib["Y"], calib["M"] = calib["Y"][perm], calib["M"][perm]
    model = build_model(d=args.d, heads=args.heads, enc_layers=args.enc_layers,
                        xattn_layers=args.xattn_layers, x_hidden=args.x_hidden,
                        card_self_attn=not args.no_card_self_attn)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    n_buffers = math.ceil(len(stream.entries) / args.buffer_chunks)
    total_steps = args.epochs * n_buffers
    ck = out / "checkpoint.pt"
    state = {"epoch": 0, "buffer": 0, "history": [], "best": float("inf"), "bad": 0}
    if ck.exists():
        saved = torch.load(ck, weights_only=False)
        model.load_state_dict(saved["model"])
        opt.load_state_dict(saved["opt"])
        state = saved["state"]
        _status(status, f"RESUME epoch {state['epoch']} buffer {state['buffer']}")
    else:
        _status(status, f"START params={n_params(model)} train_rows={stream.rows} "
                        f"chunks={len(stream.entries)} config={json.dumps(vars(args), default=str)}")

    def lr_at(step):
        warm = max(1, int(0.02 * total_steps))
        if step < warm:
            return args.lr * (step + 1) / warm
        return args.lr * 0.5 * (1 + math.cos(math.pi * min(1.0, step / total_steps)))

    def save():
        tmp = out / "checkpoint.pt.tmp"
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "state": state,
                    "config": model.config, "args": vars(args)}, tmp)
        os.replace(tmp, ck)

    last_save = time.time()
    while state["epoch"] < args.epochs:
        epoch = state["epoch"]
        t0 = time.time()
        tot = cnt = 0.0
        cur_buffer = state["buffer"]
        model.train()
        for gi, b in stream.batches(args.seed, epoch, state["buffer"]):
            if gi != cur_buffer:
                state["buffer"] = cur_buffer = gi
                if time.time() - last_save > args.save_every:
                    save()
                    last_save = time.time()
                    _status(status, f"epoch {epoch + 1} buffer {gi}/{n_buffers} "
                                    f"train {tot / max(cnt, 1):.4f} ({time.time() - t0:.0f}s)")
                if (out / "STOP").exists():
                    save()
                    _status(status, "STOPPED (STOP file); checkpoint saved")
                    return 3
            for group in opt.param_groups:
                group["lr"] = lr_at(epoch * n_buffers + gi)
            tb = to_torch(b)
            loss, n = batch_loss(model, tb)
            opt.zero_grad()
            (loss / n.clamp_min(1.0)).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += float(loss.detach())
            cnt += float(n)
        lc = predict_logits(model, calib, no_history=args.no_history)
        cll = mean_ll(masked_softmax(lc, calib["M"]), calib["Y"])
        state["history"].append({"epoch": epoch + 1, "train_ll": tot / max(cnt, 1), "calib_ll": cll,
                                 "seconds": time.time() - t0})
        _status(status, f"EPOCH {epoch + 1} train {tot / max(cnt, 1):.4f} calib {cll:.4f} "
                        f"({time.time() - t0:.0f}s)")
        if cll < state["best"] - 1e-5:
            state["best"], state["bad"] = cll, 0
            torch.save({"model": model.state_dict(), "config": model.config, "args": vars(args),
                        "epoch": epoch + 1, "calib_ll": cll}, out / "best.pt")
        else:
            state["bad"] += 1
        state["epoch"] += 1
        state["buffer"] = 0
        save()
        last_save = time.time()
        if state["bad"] >= args.patience:
            break
    _status(status, "=== TRAIN DONE ===")
    return 0


# ------------------------------------------------------------------ evaluation

def load_trained(path: str):
    import torch
    saved = torch.load(path, weights_only=False)
    model = build_model(**saved["config"])
    model.load_state_dict(saved["model"])
    model.eval()
    return model, saved


def evaluate(args) -> int:
    import torch
    torch.set_num_threads(args.threads)
    verified = _Verified()
    t_start = time.time()
    calib = load_eval(args.data, "calib", verified, max_rows=args.calib_rows, seed=args.seed)
    test = load_eval(args.data, "test", verified, max_rows=args.test_rows, seed=args.seed + 1)
    train_deals = set()
    for e in extract_entries(args.data, "train")[: args.deal_check_chunks]:
        with np.load(io.BytesIO(verified.read(e["path"], e["sha256"]))) as z:
            train_deals.update(np.unique(z["deal"]).tolist())
    if train_deals & set(np.unique(test["deal"]).tolist()):
        raise BeliefSeqError("a train deal is in the test split")
    Y, Mt = test["Y"], test["M"]
    methods: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {}
    for spec in args.model:
        name, path = spec.split("=", 1)
        model, saved = load_trained(path)
        nh = bool(saved["args"].get("no_history"))
        perm = bool(saved["args"].get("permute"))
        Mc, Yc = calib["M"], calib["Y"]
        if perm:   # the control is calibrated on permuted calib labels too (belief_eval)
            p = permute_within_strata(strata_of(calib["trick"], calib["role"]),
                                      int(saved["args"]["seed"]) + 2)
            Mc, Yc = Mc[p], Yc[p]
        lc = predict_logits(model, calib, no_history=nh)
        T = fit_scalar(lambda t: mean_ll(masked_softmax(lc, Mc, t), Yc), 0.25, 4.0)
        methods[name] = masked_softmax(predict_logits(model, test, no_history=nh), Mt, T)
        meta[name] = {"path": path, "T": T, "params": n_params(model), "epoch": saved.get("epoch"),
                      "calib_ll_raw": saved.get("calib_ll"), "no_history": nh, "permuted": perm,
                      "config": saved["config"]}
        print(f"[eval] {name}: T={T:.3f}", flush=True)
    alpha = fit_scalar(lambda a: mean_ll(sampler_probs(calib["S"], calib["S_n"], calib["M"], a),
                                         calib["Y"]), 1e-3, 64.0)
    methods["sampler"] = sampler_probs(test["S"], test["S_n"], Mt, alpha)
    methods["uniform"] = uniform_probs(test["sizes"], Mt)
    terms = {k: copy_terms(P, Y) for k, P in methods.items()}
    phase = np.asarray([phase_of_trick(int(t)) for t in test["trick"]])
    groups = ([("overall", np.ones(len(Y), bool))] + [(n, phase == n) for n, _, _ in PHASES]
              + [(ROLES[i], test["role"] == i) for i in range(len(ROLES))])
    res: dict[str, Any] = {"models": meta, "alpha_sampler": alpha, "test_rows": int(len(Y)),
                           "test_deals": int(len(np.unique(test["deal"]))),
                           "calib_rows": int(len(calib["Y"])), "tables": {}}
    for g, rows in groups:
        res["tables"][g] = {k: summarize(terms[k], rows) for k in methods}
    # per trick: true-holder mass (expected per-copy agreement of a marginal draw)
    tk = test["trick"].astype(int)
    res["by_trick"] = {}
    for t in range(1, 26):
        rows = tk == t
        if rows.sum() < 50:
            continue
        res["by_trick"][t] = {k: summarize(terms[k], rows)["all"] for k in methods}
    res["ece"] = {k: reliability(P, Y, Mt)[0] for k, P in methods.items()}
    res["bootstrap"] = {}
    names = [k for k in methods if k != "sampler"]
    for subset, _, ll_key, _ in SUBSETS:
        ci = deal_bootstrap(test["deal"], [terms[k][ll_key] for k in names],
                            terms["sampler"][ll_key], seed=args.seed)
        res["bootstrap"][subset] = dict(zip(names, ci))
    # paired: each model vs the first named model (e.g. history vs no-history)
    if len(args.model) >= 2:
        ref = args.model[0].split("=", 1)[0]
        res["paired_vs"] = {"ref": ref}
        for k in [m.split("=", 1)[0] for m in args.model[1:]]:
            for subset, _, ll_key, _ in SUBSETS:
                ci = deal_bootstrap(test["deal"], [terms[k][ll_key]], terms[ref][ll_key],
                                    seed=args.seed)[0]
                res["paired_vs"].setdefault(k, {})[subset] = ci
    # sampled legal worlds: v83 agreement
    rng = np.random.default_rng(args.seed)
    pick = rng.choice(len(Y), size=min(args.world_states, len(Y)), replace=False)
    res["worlds"] = {}
    for k in [m.split("=", 1)[0] for m in args.model] + ["sampler", "uniform"]:
        agree, best, distinct, ms = [], [], [], []
        per_phase: dict[str, list] = {n: [] for n, _, _ in PHASES}
        for i in pick:
            n_c = Y[i].sum(-1).astype(np.int64)
            if not n_c.sum():
                continue
            sizes = test["sizes"][i].astype(np.int64)
            t0 = time.perf_counter()
            P = project_sizes(methods[k][i], n_c, sizes, Mt[i]) if args.project else methods[k][i]
            W = sample_worlds(P, n_c, Mt[i], sizes, args.worlds, rng)
            ms.append((time.perf_counter() - t0) * 1e3)
            a = world_agreement(W, Y[i])
            agree.append(a.mean())
            best.append(a.max())
            distinct.append(len({w.tobytes() for w in W}))
            per_phase[phase[i]].append(a.mean())
        agree = np.asarray(agree)
        res["worlds"][k] = {
            "states": int(len(agree)), "mean": float(agree.mean()),
            "quantiles": {q: float(np.quantile(agree, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            "best_of_W_mean": float(np.mean(best)), "distinct_mean": float(np.mean(distinct)),
            "sample_ms_p50": float(np.median(ms)),
            "by_phase": {n: float(np.mean(v)) if v else float("nan") for n, v in per_phase.items()}}
        print(f"[worlds] {k}: mean {agree.mean():.4f}", flush=True)
    res["seconds"] = time.time() - t_start
    Path(args.out_json).write_text(json.dumps(res, indent=1, default=float))
    md = report(res)
    Path(args.out_md).write_text(md)
    print(md)
    return 0


def _pct(x: float) -> str:
    return "nan" if x != x else f"{100 * x:+.2f}%"


def report(res: Mapping[str, Any]) -> str:
    models = list(res["models"])
    methods = models + ["sampler", "uniform"]
    L = ["# S17 history-input belief: offline test (unknown copies only)\n",
         "Generated by `python -m shengji.train.belief_seq evaluate`. Tier-i DEV: offline "
         "log-loss / agreement only; no strength claim.\n",
         f"- test: {res['test_rows']} sampler rows, {res['test_deals']} deals; calib "
         f"{res['calib_rows']} rows; sampler alpha {res['alpha_sampler']:.3f}"]
    for k, m in res["models"].items():
        L.append(f"- {k}: params {m['params']}, epoch {m['epoch']}, T {m['T']:.3f}, "
                 f"no_history={m['no_history']}, permuted={m['permuted']}")
    L.append("")
    ov = res["tables"]["overall"]
    L.append("## Log-loss gain over the production sampler (overall)\n")
    L.append("| method | hands LL | hands gain [95% deal CI] | kitty gain | all gain | hands mass | all mass |")
    L.append("|---|---:|---|---:|---:|---:|---:|")
    for k in methods:
        t = ov[k]
        s = ov["sampler"]
        ci = res["bootstrap"]["hands"].get(k)
        cis = f" [{_pct(ci[0])} .. {_pct(ci[1])}]" if ci else ""
        L.append(f"| {k} | {t['hands']['logloss']:.4f} | "
                 f"{_pct(1 - t['hands']['logloss'] / s['hands']['logloss'])}{cis} | "
                 f"{_pct(1 - t['kitty']['logloss'] / s['kitty']['logloss'])} | "
                 f"{_pct(1 - t['all']['logloss'] / s['all']['logloss'])} | "
                 f"{t['hands']['mass']:.4f} | {t['all']['mass']:.4f} |")
    if "paired_vs" in res:
        ref = res["paired_vs"]["ref"]
        L.append(f"\nPaired deal-bootstrap log-loss gain over **{ref}**:\n")
        L.append("| model | hands | kitty | all |")
        L.append("|---|---|---|---|")
        for k, v in res["paired_vs"].items():
            if k == "ref":
                continue
            L.append(f"| {k} | " + " | ".join(f"{_pct(v[s][0])} .. {_pct(v[s][1])}"
                                              for s in ("hands", "kitty", "all")) + " |")
    L.append("\n## Hands log-loss gain over the sampler by phase and role\n")
    gs = [g for g in res["tables"] if g != "overall"]
    L.append("| method | " + " | ".join(gs) + " |")
    L.append("|---|" + "---:|" * len(gs))
    for k in methods:
        L.append(f"| {k} | " + " | ".join(
            _pct(1 - res["tables"][g][k]["hands"]["logloss"] / res["tables"][g]["sampler"]["hands"]["logloss"])
            for g in gs) + " |")
    L.append("\n## True-holder mass (all unknown copies, = expected per-copy agreement) by phase\n")
    L.append("| method | overall | " + " | ".join(gs) + " |")
    L.append("|---|---:|" + "---:|" * len(gs))
    for k in methods:
        L.append(f"| {k} | {ov[k]['all']['mass']:.4f} | " + " | ".join(
            f"{res['tables'][g][k]['all']['mass']:.4f}" for g in gs) + " |")
    L.append("\n## True-holder mass by trick (all unknown copies)\n")
    L.append("| trick | copies | " + " | ".join(methods) + " |")
    L.append("|---:|---:|" + "---:|" * len(methods))
    for t, row in res["by_trick"].items():
        L.append(f"| {t} | {int(row[methods[0]]['copies'])} | " +
                 " | ".join(f"{row[k]['mass']:.4f}" for k in methods) + " |")
    L.append("\n## Sampled legal worlds: v83 card agreement\n")
    L.append("v83 arms (mean agreement): production-drawn ~0.42, K4 ~0.46, K16 ~0.57, Q50 ~0.72.\n")
    L.append("| method | states | mean | p10 | p25 | p50 | p75 | p90 | best-of-W | distinct/W | early | mid | late | sample ms p50 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k, w in res["worlds"].items():
        qs = w["quantiles"]
        bp = w["by_phase"]
        L.append(f"| {k} | {w['states']} | {w['mean']:.4f} | " +
                 " | ".join(f"{qs[q]:.3f}" for q in sorted(qs)) +
                 f" | {w['best_of_W_mean']:.3f} | {w['distinct_mean']:.1f} | "
                 f"{bp['early']:.3f} | {bp['mid']:.3f} | {bp['late']:.3f} | {w['sample_ms_p50']:.1f} |")
    L.append("\n## Calibration (ECE)\n")
    L.append("| method | ECE |")
    L.append("|---|---:|")
    for k in methods:
        L.append(f"| {k} | {res['ece'][k]:.4f} |")
    L.append(f"\nWall time {res['seconds']:.0f} s.")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ latency

def latency(args) -> int:
    """One decision at a time (batch 1), CPU, ``--threads`` torch threads."""
    import torch
    torch.set_num_threads(args.threads)
    verified = _Verified()
    test = load_eval(args.data, "test", verified, max_rows=2000, seed=args.seed)
    model, _ = load_trained(args.model)
    rng = np.random.default_rng(args.seed)
    rows = rng.choice(len(test["X"]), size=args.n, replace=False)
    times, plies = [], []
    with torch.no_grad():
        for i in rows:
            rr = test["row_round"][i]
            b = make_batch(test, np.asarray([rr]), np.asarray([i]))
            tb = to_torch(b)
            t0 = time.perf_counter()
            model(tb)
            times.append((time.perf_counter() - t0) * 1e3)
            plies.append(int(b["ply"][0]))
    times = np.asarray(times[5:])
    out = {"threads": args.threads, "n": len(times), "p50_ms": float(np.median(times)),
           "p90_ms": float(np.quantile(times, 0.9)), "p99_ms": float(np.quantile(times, 0.99)),
           "mean_ms": float(times.mean())}
    print(json.dumps(out))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(out, indent=1))
    return 0


# ------------------------------------------------------------------ production worlds

def _production_cluster(task) -> list[dict]:
    """Replay one test cluster and draw production's worlds at the chosen decisions."""
    from ..ai.cwv_policy import sample_worlds as prod_sample
    from ..ai.memory import Memory
    from ..ai.mcbot import MCBot
    from ..ai.refusal import sample_worlds_refusal_aware
    from ..rl.encode import CARD_INDEX
    from .belief_eval import known_counts
    from .belief_labels import _read_records, iter_decisions
    shard, wanted, W, seed = task
    recs = [r for r in _read_records(Path(shard)) if r.get("decision_kind") == "play"]
    out = []
    for d in iter_decisions(recs):
        if d.decision_index not in wanted:
            continue
        X, Y = wanted[d.decision_index]
        bot = MCBot(seed=seed + d.decision_index)
        mem = Memory(d.rnd, d.seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
        t0 = time.perf_counter()
        if d.refusals:
            worlds, _, _ = sample_worlds_refusal_aware(bot, d.rnd, d.seat, W, list(d.refusals), mem=mem)
        else:
            worlds, _ = prod_sample(bot, d.rnd, d.seat, W, mem=mem)
        ms = (time.perf_counter() - t0) * 1e3
        K = known_counts(X[None])[0]
        agree = []
        for hands, buried in worlds:
            c = np.zeros((N_CARDS, N_RECV), np.int64)
            for rel in (1, 2, 3):
                for card in hands[(d.seat + rel) % 4]:
                    c[CARD_INDEX[card], rel - 1] += 1
            if not mem.own_kitty_known:
                for card in buried:
                    c[CARD_INDEX[card], KITTY] += 1
            agree.append(np.minimum(np.maximum(c - K, 0), Y).sum() / max(int(Y.sum()), 1))
        out.append({"decision": d.decision_index, "trick": len(d.rnd.history) + 1,
                    "mean": float(np.mean(agree)), "best": float(np.max(agree)),
                    "worlds": len(worlds), "ms": ms})
    return out


def production_worlds(args) -> int:
    """v83 agreement of production's own drawn worlds on test states (the same
    states ``evaluate`` samples: ``--seed``/``--world-states`` must match)."""
    from concurrent.futures import ProcessPoolExecutor
    from .belief_labels import cluster_paths
    verified = _Verified()
    test = load_eval(args.data, "test", verified, max_rows=args.test_rows, seed=args.seed + 1)
    rng = np.random.default_rng(args.seed)
    pick = rng.choice(len(test["Y"]), size=min(args.world_states, len(test["Y"])), replace=False)
    # rows -> (dir, cluster, decision): dirs from the store column of each chunk
    tasks: dict[tuple[str, int], dict] = {}
    for i in pick:
        if not test["Y"][i].sum():
            continue
        d = test["_dir"][i]
        key = (d, int(test["cluster"][i]))
        tasks.setdefault(key, {})[int(test["decision"][i])] = (test["X"][i].astype(np.float32),
                                                               test["Y"][i].astype(np.int64))
    shard_cache: dict[str, list] = {}
    work = []
    for (d, c), wanted in tasks.items():
        if d not in shard_cache:
            man = json.loads((Path(d) / "manifest.json").read_text())
            store = Path(args.stores_root) / Path(man["stores"][0]).name
            shard_cache[d] = [str(p) for p in cluster_paths(store)]
        work.append((shard_cache[d][c], wanted, args.worlds, args.seed))
    rows = []
    with ProcessPoolExecutor(args.workers) as ex:
        for got in ex.map(_production_cluster, work):
            rows += got
    a = np.asarray([r["mean"] for r in rows])
    ph = np.asarray([phase_of_trick(r["trick"]) for r in rows])
    res = {"states": len(rows), "mean": float(a.mean()),
           "quantiles": {q: float(np.quantile(a, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
           "best_of_W_mean": float(np.mean([r["best"] for r in rows])),
           "worlds_mean": float(np.mean([r["worlds"] for r in rows])),
           "sample_ms_p50": float(np.median([r["ms"] for r in rows])),
           "by_phase": {n: float(a[ph == n].mean()) for n, _, _ in PHASES if (ph == n).any()}}
    print(json.dumps(res, indent=1))
    Path(args.out_json).write_text(json.dumps(res, indent=1))
    return 0


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="belief_seq", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--epochs", type=int, default=3)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--weight-decay", type=float, default=0.01)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--threads", type=int, default=12)
    t.add_argument("--loader-threads", type=int, default=3)
    t.add_argument("--buffer-chunks", type=int, default=24)
    t.add_argument("--rounds-per-batch", type=int, default=16)
    t.add_argument("--row-frac", type=float, default=1.0)
    t.add_argument("--max-train-rows", type=int, default=None)
    t.add_argument("--calib-rows", type=int, default=60000)
    t.add_argument("--patience", type=int, default=2)
    t.add_argument("--save-every", type=float, default=600.0)
    t.add_argument("--no-history", action="store_true")
    t.add_argument("--permute", action="store_true")
    t.add_argument("--d", type=int, default=64)
    t.add_argument("--heads", type=int, default=4)
    t.add_argument("--enc-layers", type=int, default=1)
    t.add_argument("--xattn-layers", type=int, default=2)
    t.add_argument("--x-hidden", type=int, default=256)
    t.add_argument("--no-card-self-attn", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("--data", nargs="+", required=True)
    e.add_argument("--model", action="append", required=True, help="name=path/best.pt")
    e.add_argument("--threads", type=int, default=12)
    e.add_argument("--seed", type=int, default=0)
    e.add_argument("--calib-rows", type=int, default=None)
    e.add_argument("--test-rows", type=int, default=None)
    e.add_argument("--deal-check-chunks", type=int, default=10 ** 9)
    e.add_argument("--world-states", type=int, default=4000)
    e.add_argument("--worlds", type=int, default=64)
    e.add_argument("--project", action="store_true", help="Sinkhorn the marginals to the sizes first")
    e.add_argument("--out-json", required=True)
    e.add_argument("--out-md", required=True)
    pw = sub.add_parser("production-worlds")
    pw.add_argument("--data", nargs="+", required=True)
    pw.add_argument("--stores-root", required=True)
    pw.add_argument("--seed", type=int, default=0)
    pw.add_argument("--test-rows", type=int, default=None)
    pw.add_argument("--world-states", type=int, default=4000)
    pw.add_argument("--worlds", type=int, default=64)
    pw.add_argument("--workers", type=int, default=12)
    pw.add_argument("--out-json", required=True)
    la = sub.add_parser("latency")
    la.add_argument("--data", nargs="+", required=True)
    la.add_argument("--model", required=True)
    la.add_argument("--threads", type=int, default=1)
    la.add_argument("--n", type=int, default=300)
    la.add_argument("--seed", type=int, default=0)
    la.add_argument("--out-json", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"train": train, "evaluate": evaluate, "latency": latency,
            "production-worlds": production_worlds}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
