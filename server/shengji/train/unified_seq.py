"""S134 stage 1: outcome (Q) and policy heads on the served belief transformer's trunk (tier-i DEV).

The served belief net B1a (``belief_seq.HistoryBelief``, package ``028131a0``) is the only served net that
reads the ordered public history.  This module keeps its architecture, inputs and belief head unchanged
and adds two heads on the same trunk:

* **Q head** -- the round outcome from the acting seat's side, a distribution over the 204 signed-level
  categories the served value predicts (``rl.value_afterstate.signed_level_category``; the same target
  and support, so the two outcome NLLs compare).  It reads the encoder state AT the actor's own play
  token (the causal encoder has then seen the play, never a later one) joined with the row context
  (the summary-row MLP).  No sampled world enters it: it predicts from the information set.
* **policy head** -- 54 card log-odds from the card states before the play (after the cross-attention
  and card self-attention, before the belief output), through its own small tower; an action scores as
  the sum of its cards' log-odds (count-weighted), as the served prior scores an action.  The belief
  extracts carry no legal-action lists, so it trains listwise over the cards in hand: the target is the
  attempted action's card multiset, normalised (``policy_loss``).

Loss: belief per-copy cross-entropy (``belief_seq.batch_loss``, weight 1.0) + Q per-row cross-entropy
(weight 1.0) + policy per-row cross-entropy (weight 0.2).  For the first ``--head-warmup-buffers`` buffers
only the new heads train (the trunk's learning rate is 0), so randomly initialised heads do not push
gradients through the served trunk.  ``--policy-detach`` stops the policy loss at
the tower input, so it cannot move the trunk.

Suit symmetry: every training batch is relabeled by one of the 24 suit permutations, drawn uniformly
from a seeded stream (``suit_perm``), trump suit included.

Outcome labels come from each trajectory store's shard sidecars (``cluster-NNNNNN.json`` "rounds":
seed, banker, attacker points, decisions), sha-checked against the store manifest and joined per row
by (store, cluster, round index); the join refuses a seed, banker or decision-count disagreement.

CLI: ``python -m shengji.train.unified_seq {train,export,parity}``; ``train --dryrun`` checks every input and
runs a few steps without writing a checkpoint.  Status lines (``OUT/status.log``):
``S134U START`` / ``RESUME`` / ``EPOCH`` / ``S134U DONE ...`` / ``S134U ABORT ...``.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from . import belief_seq as bs
from . import suit_perm
from .belief_eval import masked_softmax, mean_ll
from .belief_history import TOKEN_FLOAT
from .belief_labels import FEATURE_DIM, KITTY, N_RECV

N_CARDS = 54
OUTCOME_CLASSES = 204
SCHEMA = "shengji-unified-numpy-v1"
CKPT_SCHEMA = "shengji-unified-seq-ckpt-v1"
LANE = "S134U"
OUTCOME_KEYS = ("store", "cluster", "round_index", "seed", "decision")
TRAIN_KEYS = bs.ROW_KEYS + OUTCOME_KEYS
_FAILED = TOKEN_FLOAT.index("failed_throw")
#: the head architecture (fixed for stage 1; recorded in every checkpoint and package)
HEAD_ARCH = {"q_hidden": 256, "policy_hidden": 192}


class UnifiedSeqError(ValueError):
    pass


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ outcome labels

def outcome_category(attacker_points: int, root_is_attacker: bool) -> int:
    """The served value's target for one outcome (``cwv_data.target_category``)."""
    from ..rl.value_afterstate import signed_level_category
    return signed_level_category(int(attacker_points), bool(root_is_attacker))


def parse_store_map(items: Sequence[str]) -> list[tuple[str, str, str]]:
    """``[DATA_PREFIX@]RECORDED_PREFIX=LOCAL_PREFIX`` rules: for an extract dir starting with DATA_PREFIX
    (any dir when omitted), a recorded store path starting with RECORDED_PREFIX is read at LOCAL_PREFIX
    plus the rest of the path.  Two extracts can record the same path for two hosts' stores."""
    out = []
    for it in items:
        if "=" not in it:
            raise UnifiedSeqError(f"--store-map {it!r}: expected [DATA_PREFIX@]RECORDED_PREFIX=LOCAL_PREFIX")
        left, local = it.split("=", 1)
        data, _, recorded = left.rpartition("@")
        out.append((data, recorded, local))
    return out


class OutcomeIndex:
    """Per-round outcomes of trajectory stores, read from their shard sidecars.

    ``store_map`` (``parse_store_map``) rewrites the store path an extract manifest recorded (the
    producing host's) to this host's copy.  A store's manifest is read once; every sidecar read is
    checked against the manifest's ``sidecar_sha256``.  ``manifests`` records each store used (local
    path -> manifest sha256, run id, seed0, shard count)."""

    def __init__(self, store_map: Sequence[tuple[str, str, str]] = ()):
        self.store_map = [tuple(r) if len(r) == 3 else ("",) + tuple(r) for r in store_map]
        self.lock = threading.Lock()
        self._stores: dict[str, dict] = {}
        self.manifests: dict[str, dict] = {}

    def resolve(self, recorded: str, data_dir: str = "") -> str:
        for data, a, b in self.store_map:
            if str(data_dir).startswith(data) and recorded.startswith(a):
                return b + recorded[len(a):]
        return recorded

    def _store(self, local: str) -> dict:
        with self.lock:
            got = self._stores.get(local)
        if got is not None:
            return got
        mpath = Path(local) / "manifest.json"
        if not mpath.is_file():
            raise UnifiedSeqError(f"store {local}: no manifest.json")
        raw = mpath.read_bytes()
        man = json.loads(raw)
        from .belief_labels import cluster_paths
        paths = cluster_paths(local)
        by_name = {Path(s["path"]).name: s for s in man["shards"]}
        names = [p.name for p in paths]
        if set(names) != set(by_name):
            raise UnifiedSeqError(f"store {local}: shard files differ from its manifest")
        got = {"local": local, "names": names, "by_name": by_name, "seed0": int(man["seed0"])}
        with self.lock:
            self._stores[local] = got
            self.manifests[local] = {"manifest_sha256": hashlib.sha256(raw).hexdigest(), "run_id": man.get("run_id"),
                                     "seed0": int(man["seed0"]), "shards": len(man["shards"])}
        return got

    def rounds(self, recorded: str, cluster_index: int, data_dir: str = "") -> list[dict]:
        """The cluster's rounds in mirror order (the extractor's ``round_index`` order)."""
        st = self._store(self.resolve(recorded, data_dir))
        name = st["names"][int(cluster_index)]
        sh = st["by_name"][name]
        side_path = Path(st["local"]) / sh["sidecar"]
        raw = side_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sh["sidecar_sha256"]:
            raise UnifiedSeqError(f"{side_path}: sidecar sha256 differs from the store manifest")
        side = json.loads(raw)
        if int(side["cluster"]) != int(sh["cluster"]) or side["sha256"] != sh["sha256"]:
            raise UnifiedSeqError(f"{side_path}: sidecar names another shard")
        return sorted((r for r in side["rounds"] if int(r["decisions"]) > 0), key=lambda r: int(r["mirror"]))


def join_targets(part: Mapping[str, Any], stores: Sequence[str], index: OutcomeIndex,
                 data_dir: str = "") -> np.ndarray:
    """``(N,)`` int16 outcome categories of a loaded part's rows, from the actor's side.

    Refuses a row whose seed or banker differs from its round's sidecar, or a round whose row count
    is not its sidecar's decision count (every play decision of a kept deal is a row)."""
    n = len(part["X"])
    out = np.full(n, -1, np.int16)
    if not n:
        return out
    banker_of_row = part["_rounds"]["banker"][part["row_round"]].astype(np.int64)
    key = np.stack([part["store"].astype(np.int64), part["cluster"].astype(np.int64)], 1)
    for s, c in np.unique(key, axis=0):
        sel = np.flatnonzero((key[:, 0] == s) & (key[:, 1] == c))
        rounds = index.rounds(stores[int(s)], int(c), data_dir)
        ri = part["round_index"][sel].astype(np.int64)
        for r in np.unique(ri):
            if not 0 <= r < len(rounds):
                raise UnifiedSeqError(f"store {s} cluster {c}: round index {r} not in its sidecar")
            rd = rounds[int(r)]
            rows = sel[ri == r]
            if len(rows) != int(rd["decisions"]):
                raise UnifiedSeqError(f"store {s} cluster {c} round {r}: {len(rows)} rows, sidecar "
                                      f"{rd['decisions']} decisions")
            if np.any(part["seed"][rows].astype(np.int64) != int(rd["seed"])):
                raise UnifiedSeqError(f"store {s} cluster {c} round {r}: row seed differs from the sidecar")
            if np.any(banker_of_row[rows] != int(rd["banker"])):
                raise UnifiedSeqError(f"store {s} cluster {c} round {r}: banker differs from the sidecar")
            seats = part["row_seat"][rows].astype(np.int64)
            for att in (True, False):
                m = (seats % 2 != int(rd["banker"]) % 2) == att
                out[rows[m]] = outcome_category(int(rd["attacker_points"]), att)
    if np.any(out < 0):
        raise UnifiedSeqError("rows without an outcome")
    return out


# ------------------------------------------------------------------ data

def entries_for(dirs: Sequence[str], split: str, *, exclude_seed_windows=()) -> list[dict]:
    out = bs.extract_entries(dirs, split, exclude_seed_windows=exclude_seed_windows)
    stores = {d: list(json.loads((Path(d) / "manifest.json").read_text())["stores"]) for d in dirs}
    for e in out:
        e["stores"] = stores[e["dir"]]
    return out


def load_unified_part(entry: Mapping[str, Any], verified, index: OutcomeIndex) -> dict:
    part = bs.load_part(entry, TRAIN_KEYS, verified)
    part["q_target"] = join_targets(part, entry["stores"], index, entry["dir"])
    w = entry.get("corpus_w")
    if w is not None:
        # per-row loss weights of the entry's corpus, one column per head (unified_readout.CORPUS_HEADS)
        part["row_w"] = np.tile(np.asarray(w, np.float32), (len(part["X"]), 1))
    return part


def policy_target(batch: Mapping[str, np.ndarray]) -> np.ndarray:
    """``(B, 54)``: the card multiset each row's actor ATTEMPTED (a refused throw's attempt, else
    its play), read from the actor's own token; refuses a card outside the actor's hand."""
    rr, ply = batch["rr"], batch["ply"]
    failed = batch["tok_f"][rr, ply, _FAILED] > 0
    att = batch["tok_att"][rr, ply]
    played = batch["tok_cards"][rr, ply]
    tgt = np.where(failed[:, None], att, played).astype(np.float32)
    hand = batch["X"][:, :N_CARDS] > 0
    if np.any((tgt > 0) & ~hand) or np.any(tgt.sum(-1) <= 0):
        raise UnifiedSeqError("an action card is outside the actor's hand (or an empty action)")
    return tgt


def make_unified_batch(part, round_ids, rows, *, perm=None) -> dict[str, np.ndarray]:
    b = bs.make_batch(part, round_ids, rows)
    if perm is not None:
        b = suit_perm.apply(b, perm)
    b["q_target"] = part["q_target"][rows].astype(np.int64)
    b["pol_target"] = policy_target(b)
    if "row_w" in part:
        b["row_w"] = part["row_w"][rows]
    return b


class Stream(bs.Stream):
    """``belief_seq.Stream`` with outcome labels joined and one suit relabeling per batch.  The
    relabeling stream is seeded by (seed, epoch, buffer), so a resumed run draws the same ones."""

    def __init__(self, entries, *, index: OutcomeIndex, suit_aug: bool, **kw):
        super().__init__(entries, no_history=False, permute=False, **kw)
        self.index = index
        self.suit_aug = suit_aug

    def batches(self, seed: int, epoch: int, start_buffer: int = 0, prefetch: int = 6):
        order = self.order(seed, epoch)
        groups = [order[i:i + self.buffer_chunks] for i in range(0, len(order), self.buffer_chunks)]
        q: queue.Queue = queue.Queue(maxsize=prefetch)
        done = object()
        stopped = threading.Event()

        def offer(item):
            while not stopped.is_set():
                try:
                    q.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    pass
            return False

        def produce():
            try:
                with ThreadPoolExecutor(self.threads) as ex:
                    def submit(g):
                        return [ex.submit(load_unified_part, self.entries[j], self.verified, self.index)
                                for j in groups[g]]
                    gi = start_buffer
                    pending = submit(gi) if gi < len(groups) else []
                    while gi < len(groups) and not stopped.is_set():
                        parts = [f.result() for f in pending]
                        if gi + 1 < len(groups):
                            pending = submit(gi + 1)
                        cat = bs.concat_parts(parts)
                        rng = np.random.default_rng([seed, epoch, gi])
                        prng = np.random.default_rng([seed, epoch, gi, 24])
                        for rids, rows in bs.round_batches(cat, self.rounds_per_batch, rng, self.row_frac):
                            perm = suit_perm.draw(prng) if self.suit_aug else None
                            if stopped.is_set() or not offer((gi, make_unified_batch(cat, rids, rows, perm=perm))):
                                return
                        gi += 1
                offer(done)
            except BaseException as exc:
                offer(exc)
        th = threading.Thread(target=produce, daemon=True, name="unified-batch-loader")
        th.start()
        try:
            while True:
                item = q.get()
                if item is done:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stopped.set()
            th.join()


def load_calib(dirs, verified, index, *, max_rows, seed, threads=4, exclude_seed_windows=(), log=print):
    """Every row of the calib split's chunks, the chunk subset chosen exactly as ``belief_seq.load_eval``
    chooses it for ``rows="all"`` (so B1a's calib split and its calib LL reproduce)."""
    entries = entries_for(dirs, "calib", exclude_seed_windows=exclude_seed_windows)
    if max_rows is not None:
        rng = np.random.default_rng(seed)
        picked, n = [], 0
        for i in rng.permutation(len(entries)):
            if n >= max_rows:
                break
            picked.append(entries[i])
            n += entries[i]["rows"]
        entries = picked
    with ThreadPoolExecutor(threads) as ex:
        parts = list(ex.map(lambda e: load_unified_part(e, verified, index), entries))
    parts = [p for p in parts if len(p["X"])]
    if not parts:
        raise UnifiedSeqError("calib: no rows")
    out = bs.concat_parts(parts)
    log(f"[data] calib: {len(out['X'])} rows, {len(np.unique(out['deal']))} deals", flush=True)
    return out


# ------------------------------------------------------------------ model

def trunk_forward(m, b):
    """``HistoryBelief.forward`` exposing its internals: ``(belief logits (B,54,4), encoder states
    (R*4, T, d), card states (B,54,d), row context (B, x_hidden))``.  The belief logits are exactly
    ``m(b)``'s (tested)."""
    import torch
    from torch import nn
    d, heads = m.config["d"], m.config["heads"]
    R, T = b["tok_int"].shape[:2]
    ce = m.card_id[None] + m.card_feat(b["card_feat"])
    ti = b["tok_int"]
    seat, pos, trick, lead = ti[..., 0], ti[..., 1], ti[..., 2], ti[..., 3]
    role = (seat - b["banker"][:, None]) % 4
    meta = torch.cat([nn.functional.one_hot(pos, 4).float(), nn.functional.one_hot(lead, 5).float(),
                      b["tok_f"], nn.functional.one_hot(role, 4).float()], -1)
    base = (m.tok_meta(meta) + m.trick_emb(trick) + torch.bmm(b["tok_cards"], ce)
            + m.att_proj(torch.bmm(b["tok_att"], ce)) + m.pos_emb.weight[:T][None])
    frames = torch.arange(4, device=base.device)
    rel = (seat[:, None, :] - frames[None, :, None]) % 4
    tok = (base[:, None] + m.rel_emb(rel)).reshape(R * 4, T, d)
    causal = torch.triu(torch.ones(T, T, dtype=torch.bool, device=base.device), 1)
    enc = m.enc_norm(m.encoder(tok, mask=causal, is_causal=True))
    g = m.x_mlp(b["X"])
    B = g.shape[0]
    q = (ce[b["rr"]] + m.row_card(torch.cat([b["row_card"], b["M"].float()], -1)) + m.x_to_q(g)[:, None])
    frame = b["rr"] * 4 + b["seat"]
    steps = torch.arange(T, device=base.device)
    visible = torch.cat([torch.ones(B, 1, dtype=torch.bool, device=base.device),
                         steps[None, :] < b["ply"][:, None]], 1)
    if m.grouped_xattn:
        q = m._xattn_grouped(q, enc, frame, visible, R, T)
    else:
        mask = visible[:, None, None, :]
        for i in range(len(m.xattn)):
            kv = m.kv[i](torch.cat([m.null_kv.expand(R * 4, 1, d), enc], 1))[frame]
            k, v = kv.split(d, -1)
            k = k.view(B, T + 1, heads, d // heads).transpose(1, 2)
            v = v.view(B, T + 1, heads, d // heads).transpose(1, 2)
            q = q + m.xattn[i](m.ln_q[i](q), k, v, mask)
            q = q + m.ff[i](q)
    if hasattr(m, "self_attn"):
        x = m.self_ln(q)
        q = q + m.self_attn(x, x, x, need_weights=False)[0]
        q = q + m.self_ff(q)
    logits = m.x_logits(g.float()).view(B, N_CARDS, N_RECV) + m.out(q.float())
    return logits, enc, q, g


def build_unified(arch: Mapping[str, Any], *, policy_detach: bool = False):
    import torch
    from torch import nn
    trunk = bs.build_model(**arch)
    d, xh = int(arch["d"]), int(arch["x_hidden"])
    qh, ph = HEAD_ARCH["q_hidden"], HEAD_ARCH["policy_hidden"]

    class Unified(nn.Module):
        def __init__(self):
            super().__init__()
            self.trunk = trunk
            self.config = {"trunk": dict(trunk.config), "heads": dict(HEAD_ARCH)}
            self.policy_detach = bool(policy_detach)
            self.q_head = nn.Sequential(nn.LayerNorm(d + xh), nn.Linear(d + xh, qh), nn.GELU(),
                                        nn.Linear(qh, qh), nn.GELU(), nn.Linear(qh, OUTCOME_CLASSES))
            self.p_head = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, ph), nn.GELU(), nn.Linear(ph, 1))

        def forward(self, b):
            logits, enc, q, g = trunk_forward(self.trunk, b)
            frame = b["rr"] * 4 + b["seat"]
            at = enc[frame, b["ply"]]                                    # B,d: the actor's own play token
            ql = self.q_head(torch.cat([at, g], -1).float())
            pq = q.detach() if self.policy_detach else q
            pl = self.p_head(pq.float()).squeeze(-1)                     # B,54
            return {"belief": logits, "q": ql, "policy": pl}

    return Unified()


def policy_loss_terms(pl, tb):
    """Per-row listwise cross-entropy over the cards in hand: target = the action's normalised card
    multiset, prediction = softmax of the card log-odds over the hand."""
    import torch
    hand = tb["X"][:, :N_CARDS] > 0
    logp = torch.log_softmax(pl.masked_fill(~hand, -1e9), -1)
    t = tb["pol_target"]
    t = t / t.sum(-1, keepdim=True)
    return -(t * logp).sum(-1)


def losses(model, tb, *, kitty_weight: float = 1.0) -> dict:
    """Summed belief CE and its copy count, per-row Q CE and per-row policy CE (sums, counts)."""
    import torch
    out = model(tb)
    logits = out["belief"].float().masked_fill(~tb["M"], -1e9)
    logp = torch.log_softmax(logits, -1)
    y = tb["Y"]
    if kitty_weight != 1.0:
        w = torch.ones(N_RECV, dtype=y.dtype, device=y.device)
        w[KITTY] = kitty_weight
        y = y * w
    q_ce = torch.nn.functional.cross_entropy(out["q"], tb["q_target"], reduction="none")
    p_ce = policy_loss_terms(out["policy"], tb)
    return {"belief_sum": -(y * logp).sum(), "belief_n": y.sum(), "q_sum": q_ce.sum(), "p_sum": p_ce.sum(),
            "rows": torch.tensor(float(len(q_ce)), device=q_ce.device), "out": out}


def to_device(b, device):
    import torch
    return {k: torch.from_numpy(np.ascontiguousarray(v)).to(device) for k, v in b.items()}


def predict(model, part, *, device="cpu", rounds_per_batch: int = 32) -> dict[str, np.ndarray]:
    """Belief logits, Q probabilities and policy logits of every row (identity relabeling)."""
    import torch
    n = len(part["X"])
    out = {"belief": np.empty((n, N_CARDS, N_RECV), np.float32),
           "q": np.empty((n, OUTCOME_CLASSES), np.float64), "policy": np.empty((n, N_CARDS), np.float32)}
    model.eval()
    with torch.no_grad():
        for rids, rows in bs.round_batches(part, rounds_per_batch, None):
            b = make_unified_batch(part, rids, rows)
            o = model(to_device(b, device))
            out["belief"][rows] = o["belief"].float().cpu().numpy()
            out["q"][rows] = torch.softmax(o["q"].double(), -1).cpu().numpy()
            out["policy"][rows] = o["policy"].float().cpu().numpy()
    model.train()
    return out


def calib_metrics(pred, part) -> dict[str, float]:
    p = pred["q"][np.arange(len(part["q_target"])), part["q_target"].astype(np.int64)]
    return {"belief_ll": mean_ll(masked_softmax(pred["belief"], part["M"]), part["Y"]),
            "q_nll": float(-np.log(np.maximum(p, 1e-300)).mean())}


# ------------------------------------------------------------------ provenance

def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def code_identity() -> dict[str, Any]:
    here = Path(__file__).resolve().parent
    files = {f"shengji/train/{n}": sha256_file(here / n) for n in ("unified_seq.py", "suit_perm.py", "belief_seq.py",
                                                                  "belief_history.py", "belief_labels.py",
                                                                  "belief_eval.py")}
    return {"git_head": _git_head(), "files": files}


def input_manifest(args, entries, calib_entries_dirs, init_sha, index: OutcomeIndex) -> dict[str, Any]:
    dirs = {}
    for d in args.data:
        dirs[d] = {"manifest_sha256": sha256_file(Path(d) / "manifest.json"),
                   "hist_manifest_sha256": sha256_file(Path(d) / "hist" / "manifest.json")}
    return {"schema": "s134u-inputs-v1", "init": {"path": args.init, "sha256": init_sha},
            "data": dirs, "train_chunks": len(entries), "train_rows": int(sum(e["rows"] for e in entries)),
            "chunk_sha256_digest": hashlib.sha256("\n".join(f"{e['sha256']} {e['hist_sha256']}" for e in entries)
                                                  .encode()).hexdigest(),
            "stores": index.manifests, "exclude_seed_windows": [list(w) for w in args.exclude_seed_window],
            "code": code_identity()}


# ------------------------------------------------------------------ training

def _status(path: str | None, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    if path:
        with open(path, "a") as fh:
            fh.write(line + "\n")


def _pick_entries(entries, max_rows, seed):
    if not max_rows:
        return entries
    rng = np.random.default_rng(seed)
    picked, n = [], 0
    for i in rng.permutation(len(entries)):
        if n >= max_rows:
            break
        picked.append(entries[i])
        n += entries[i]["rows"]
    return picked


def train(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = str(out / ("dryrun.log" if args.dryrun else "status.log"))
    if not args.dryrun and (out / "status.log").exists() and any(
            f" {LANE} DONE" in line for line in (out / "status.log").read_text().splitlines()):
        print(f"refusing: {out}/status.log already has {LANE} DONE", file=sys.stderr)
        return 2
    try:
        return _train(args, out, status)
    except Exception as exc:
        _status(status, f"{LANE} ABORT {type(exc).__name__}: {str(exc)[:300]}")
        traceback.print_exc()
        return 1


def _train(args, out: Path, status: str) -> int:
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    verified = bs._Verified()
    index = OutcomeIndex(parse_store_map(args.store_map))
    entries = _pick_entries(entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window),
                            args.max_train_rows, args.seed)
    if not entries:
        raise UnifiedSeqError("no train chunks")
    init = bs.load_init(args.init)
    if args.init_sha256 and init["sha256"] != args.init_sha256:
        raise UnifiedSeqError(f"--init sha256 {init['sha256']} != --init-sha256 {args.init_sha256}")
    bs.check_init_identity(init, args.data)
    arch = {k: init["config"][k] for k in bs.DEFAULT_ARCH}
    model = build_unified(arch, policy_detach=args.policy_detach)
    bs.apply_init(model.trunk, init)
    model.to(device)
    stream = Stream(entries, index=index, suit_aug=not args.no_suit_aug, verified=verified,
                    threads=args.loader_threads, buffer_chunks=args.buffer_chunks,
                    rounds_per_batch=args.rounds_per_batch, row_frac=1.0)
    calib = load_calib(args.data, verified, index, max_rows=args.calib_rows, seed=args.seed,
                       exclude_seed_windows=args.exclude_seed_window)
    head_params = [p for n, p in model.named_parameters() if not n.startswith("trunk.")]
    opt = torch.optim.AdamW([{"params": list(model.trunk.parameters()), "lr": args.lr, "base_lr": args.lr},
                             {"params": head_params, "lr": args.head_lr, "base_lr": args.head_lr}],
                            weight_decay=args.weight_decay)
    n_buffers = math.ceil(len(stream.entries) / args.buffer_chunks)
    total_steps = args.epochs * n_buffers

    def lr_scale(step):
        warm = max(1, int(0.02 * total_steps))
        if step < warm:
            return (step + 1) / warm
        return 0.5 * (1 + math.cos(math.pi * min(1.0, step / total_steps)))

    def step_on(b, scale, step=None):
        for g in opt.param_groups:
            g["lr"] = g["base_lr"] * scale
        if step is not None and step < args.head_warmup_buffers:
            opt.param_groups[0]["lr"] = 0.0             # the new heads fit a frozen trunk first
        tb = to_device(b, device)
        opt.zero_grad()
        L = losses(model, tb, kitty_weight=args.kitty_weight)
        bl = L["belief_sum"] / L["belief_n"].clamp_min(1.0)
        ql = L["q_sum"] / L["rows"]
        pl = L["p_sum"] / L["rows"]
        (args.belief_weight * bl + args.q_weight * ql + args.policy_weight * pl).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        return tuple(float(L[k].detach()) for k in ("belief_sum", "belief_n", "q_sum", "p_sum", "rows"))

    if args.dryrun:
        _status(status, f"{LANE} DRYRUN start chunks={len(entries)} rows={stream.rows} buffers={n_buffers} "
                        f"init={init['sha256']} device={device}")
        # every data dir's store mapping and outcome join, on its first train chunk
        for d in args.data:
            first = next(e for e in entries_for([d], "train", exclude_seed_windows=args.exclude_seed_window))
            load_unified_part(first, verified, index)
        _status(status, f"{LANE} DRYRUN joined one chunk of each of {len(args.data)} data dirs")
        pred = predict(model, calib, device=device)
        dry_calib = calib_metrics(pred, calib)
        _status(status, f"{LANE} DRYRUN init calib {json.dumps(dry_calib)}")
        check_init_belief_ll(dry_calib, args.expect_init_belief_ll)
        t0, rows_seen, steps = time.time(), 0, 0
        it = stream.batches(args.seed, 0, 0)
        try:
            for gi, b in it:
                r = step_on(b, lr_scale(0))
                rows_seen += int(r[4])
                steps += 1
                if steps >= args.dryrun_steps:
                    break
        finally:
            it.close()
        dt = time.time() - t0
        rate = rows_seen / max(dt, 1e-9)
        _status(status, f"{LANE} DRYRUN OK steps={steps} rows={rows_seen} seconds={dt:.1f} rows_per_s={rate:.0f} "
                        f"projected_pass_h={stream.rows / max(rate, 1e-9) / 3600:.2f} stores={json.dumps(index.manifests)}")
        return 0

    ck = out / "checkpoint.pt"
    state = {"epoch": 0, "buffer": 0, "history": [], "best": float("inf")}
    if ck.exists():
        saved = torch.load(ck, weights_only=False, map_location="cpu")
        # The saved cursor (epoch, buffer) only means the same thing under the same recipe and inputs, so every
        # semantic setting and the input identity must match before any weight is loaded or any update runs.
        want = _run_identity(args, init["sha256"])
        have = saved.get("run", {})
        for k in sorted(set(want) | set(have)):
            if have.get(k) != want.get(k):
                raise UnifiedSeqError(f"resume: {k} differs from the run's ({have.get(k)!r} != {want.get(k)!r})")
        recorded = json.loads((out / "inputs.json").read_text())
        recorded.pop("init_calib", None)
        now_inputs = json.loads(json.dumps(input_manifest(args, entries, args.data, init["sha256"], index),
                                           default=str))
        for k in sorted(set(recorded) | set(now_inputs)):
            if recorded.get(k) != now_inputs.get(k):
                raise UnifiedSeqError(f"resume: input {k} differs from the run's inputs.json")
        model.load_state_dict(saved["model"])
        opt.load_state_dict(saved["opt"])
        state = saved["state"]
        check_init_belief_ll(state.get("init_calib"), args.expect_init_belief_ll)
        _status(status, f"RESUME epoch {state['epoch']} buffer {state['buffer']}")
    else:
        manifest = input_manifest(args, entries, args.data, init["sha256"], index)
        pred = predict(model, calib, device=device)
        state["init_calib"] = calib_metrics(pred, calib)
        manifest["init_calib"] = state["init_calib"]
        (out / "inputs.json").write_text(json.dumps(manifest, indent=1, default=str))
        _status(status, f"{LANE} START params={sum(p.numel() for p in model.parameters())} rows={stream.rows} "
                        f"chunks={len(entries)} buffers={n_buffers} init={init['sha256']} "
                        f"inputs_sha256={sha256_file(out / 'inputs.json')} device={device}")
        _status(status, f"INIT calib {json.dumps(state['init_calib'])}")
        check_init_belief_ll(state["init_calib"], args.expect_init_belief_ll)

    def save():
        tmp = out / "checkpoint.pt.tmp"
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "state": state,
                    "config": model.config, "run": _run_identity(args, init["sha256"])}, tmp)
        os.replace(tmp, ck)

    last_save = time.time()
    while state["epoch"] < args.epochs:
        epoch = state["epoch"]
        t0 = time.time()
        sums = np.zeros(5)
        cur = state["buffer"]
        steps = 0
        for gi, b in stream.batches(args.seed, epoch, state["buffer"]):
            if gi != cur:
                state["buffer"] = cur = gi
                if time.time() - last_save > args.save_every:
                    save()
                    last_save = time.time()
                    _status(status, f"epoch {epoch + 1} buffer {gi}/{n_buffers} " + _means(sums)
                            + f" ({time.time() - t0:.0f}s)")
                if (out / "STOP").exists():
                    save()
                    _status(status, "STOPPED (STOP file); checkpoint saved")
                    return 3
            sums += np.asarray(step_on(b, lr_scale(epoch * n_buffers + gi), epoch * n_buffers + gi))
            steps += 1
            if args.max_steps and steps >= args.max_steps:
                break
        pred = predict(model, calib, device=device)
        cm = calib_metrics(pred, calib)
        state["history"].append({"epoch": epoch + 1, "train": _means(sums), "calib": cm,
                                 "seconds": time.time() - t0})
        _status(status, f"EPOCH {epoch + 1} {_means(sums)} calib {json.dumps(cm)} ({time.time() - t0:.0f}s)")
        score = cm["belief_ll"] + cm["q_nll"]
        state["epoch"] += 1
        state["buffer"] = 0
        if score < state["best"]:
            state["best"] = score
            torch.save({"schema": CKPT_SCHEMA, "model": model.state_dict(), "config": model.config,
                        "epoch": epoch + 1, "calib": cm, "init_calib": state.get("init_calib"),
                        "run": _run_identity(args, init["sha256"])}, out / "best.pt")
        save()
        last_save = time.time()
    _status(status, f"{LANE} DONE best={out / 'best.pt'} sha256={sha256_file(out / 'best.pt')}")
    return 0


def check_init_belief_ll(init_calib, expect) -> None:
    """The run starts from the init package's own calibration loss: a different, malformed or non-finite INIT
    belief_ll means another trunk, split or loader, and refuses before any update or checkpoint."""
    if expect is None:
        return
    ll = (init_calib or {}).get("belief_ll")
    if not isinstance(ll, (int, float)) or not math.isfinite(ll):
        raise UnifiedSeqError(f"INIT belief_ll {ll!r} is not a finite number (expected {expect:.5f})")
    if f"{round(float(ll), 5):.5f}" != f"{expect:.5f}":
        raise UnifiedSeqError(f"INIT belief_ll {ll!r} does not round to the expected {expect:.5f}")


def _means(s) -> str:
    return (f"belief {s[0] / max(s[1], 1):.4f} q {s[2] / max(s[4], 1):.4f} policy {s[3] / max(s[4], 1):.4f}")


def _run_identity(args, init_sha) -> dict:
    return {"init_sha256": init_sha, "seed": args.seed, "exclude_seed_window": [list(w) for w in args.exclude_seed_window],
            "q_weight": args.q_weight, "policy_weight": args.policy_weight, "belief_weight": args.belief_weight,
            "policy_detach": args.policy_detach, "no_suit_aug": args.no_suit_aug, "epochs": args.epochs,
            "max_train_rows": args.max_train_rows, "lr": args.lr, "head_lr": args.head_lr,
            "head_warmup_buffers": args.head_warmup_buffers, "weight_decay": args.weight_decay,
            "kitty_weight": args.kitty_weight, "buffer_chunks": args.buffer_chunks,
            "rounds_per_batch": args.rounds_per_batch, "calib_rows": args.calib_rows, "max_steps": args.max_steps,
            "store_map": list(args.store_map), "expect_init_belief_ll": args.expect_init_belief_ll,
            "data": list(args.data)}


# ------------------------------------------------------------------ export

def load_checkpoint(path: str):
    import torch
    saved = torch.load(path, weights_only=False, map_location="cpu")
    if saved.get("schema") != CKPT_SCHEMA:
        raise UnifiedSeqError(f"{path}: not a {CKPT_SCHEMA} checkpoint")
    model = build_unified(saved["config"]["trunk"], policy_detach=bool(saved["run"].get("policy_detach")))
    model.load_state_dict(saved["model"])
    model.eval()
    return model, saved


def export(args) -> int:
    """best.pt -> a NumPy package (``ai.unified_numpy``) and a ``belief_seq``-format checkpoint of
    the trunk + belief head (``belief_seq evaluate`` / ``belief_sampler.export`` read it)."""
    import torch
    from ..ai import unified_numpy as un
    model, saved = load_checkpoint(args.ckpt)
    sd = {k: v.detach().cpu().float().numpy() for k, v in model.state_dict().items()}
    trunk = {k[len("trunk."):]: v for k, v in sd.items() if k.startswith("trunk.")}
    heads = {k: v for k, v in sd.items() if not k.startswith("trunk.")}
    meta = {"source_checkpoint_sha256": sha256_file(args.ckpt), "epoch": saved.get("epoch"),
            "calib": saved.get("calib"), "init_sha256": saved["run"]["init_sha256"], "note": args.note}
    sha = un.save_package(args.out, saved["config"], trunk, heads, meta)
    print(json.dumps({"package": args.out, "sha256": sha}))
    if args.belief_ckpt:
        torch.save({"model": model.trunk.state_dict(), "config": dict(saved["config"]["trunk"]),
                    "args": {"no_history": False, "permute": False, "seed": saved["run"]["seed"],
                             "exclude_seed_window": saved["run"]["exclude_seed_window"]},
                    "epoch": saved.get("epoch"), "calib_ll": (saved.get("calib") or {}).get("belief_ll")},
                   args.belief_ckpt)
        print(json.dumps({"belief_ckpt": args.belief_ckpt, "sha256": sha256_file(args.belief_ckpt)}))
    return 0


def parity(args) -> int:
    """Max |torch - NumPy| of the belief logits, policy logits and Q probabilities over ``--rows`` rows of
    a split (identity relabeling), for a checkpoint and the package exported from it."""
    from ..ai import unified_numpy as un
    model, _ = load_checkpoint(args.ckpt)
    rt = un.load_unified_numpy(args.pkg, sha256=args.sha256)
    idx = OutcomeIndex(parse_store_map(args.store_map))
    v = bs._Verified()
    part = bs.concat_parts([load_unified_part(e, v, idx) for e in entries_for(args.data, args.split)[:args.chunks]])
    pred = predict(model, part)
    rng = np.random.default_rng(0)
    pick = set(rng.choice(len(part["X"]), size=min(args.rows, len(part["X"])), replace=False).tolist())
    diff = {"belief": 0.0, "policy": 0.0, "q": 0.0}
    n = 0
    for rids, rows in bs.round_batches(part, 8, None):
        b = make_unified_batch(part, rids, rows)
        for k, i in enumerate(rows):
            if int(i) not in pick:
                continue
            pre = un.batch_inputs(b, k, with_play=False)
            diff["belief"] = max(diff["belief"], float(np.abs(rt.belief_logits(pre) - pred["belief"][i]).max()))
            diff["policy"] = max(diff["policy"], float(np.abs(rt.policy_logits(pre) - pred["policy"][i]).max()))
            diff["q"] = max(diff["q"], float(np.abs(rt.q_probs(un.batch_inputs(b, k, with_play=True)) - pred["q"][i]).max()))
            n += 1
    ok = max(diff.values()) <= args.tol
    print(json.dumps({"rows": n, "max_abs_diff": diff, "tol": args.tol, "package": rt.package_sha256,
                      "verdict": "PARITY OK" if ok else "PARITY FAIL"}))
    return 0 if ok else 1


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="unified_seq", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--init", required=True, help="the served belief package (B1a) to warm the trunk from")
    t.add_argument("--init-sha256", default=None)
    t.add_argument("--store-map", action="append", default=[],
                   help="[DATA_PREFIX@]RECORDED_PREFIX=LOCAL_PREFIX: where this host holds the stores the "
                        "extracts name (per extract dir when DATA_PREFIX is given); repeatable")
    t.add_argument("--epochs", type=int, default=1)
    t.add_argument("--lr", type=float, default=1.5e-4, help="trunk learning rate (B1a's)")
    t.add_argument("--head-lr", type=float, default=1e-3, help="learning rate of the new heads")
    t.add_argument("--expect-init-belief-ll", type=float, default=None,
                   help="refuse before any update unless the INIT calib belief_ll rounds (5 places) to this")
    t.add_argument("--head-warmup-buffers", type=int, default=4,
                   help="buffers at the start of the run in which only the new heads train (trunk lr 0)")
    t.add_argument("--weight-decay", type=float, default=0.01)
    t.add_argument("--belief-weight", type=float, default=1.0)
    t.add_argument("--q-weight", type=float, default=1.0)
    t.add_argument("--policy-weight", type=float, default=0.2)
    t.add_argument("--policy-detach", action="store_true")
    t.add_argument("--no-suit-aug", action="store_true")
    t.add_argument("--kitty-weight", type=float, default=1.0)
    t.add_argument("--seed", type=int, default=1)
    t.add_argument("--threads", type=int, default=12)
    t.add_argument("--loader-threads", type=int, default=3)
    t.add_argument("--device", default="cpu", help="cpu or mps")
    t.add_argument("--buffer-chunks", type=int, default=24)
    t.add_argument("--rounds-per-batch", type=int, default=16)
    t.add_argument("--max-train-rows", type=int, default=None)
    t.add_argument("--max-steps", type=int, default=None, help="stop each epoch after this many steps (smoke)")
    t.add_argument("--calib-rows", type=int, default=180000)
    t.add_argument("--save-every", type=float, default=600.0)
    t.add_argument("--dryrun", action="store_true")
    t.add_argument("--dryrun-steps", type=int, default=20)
    t.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    e = sub.add_parser("export")
    e.add_argument("--ckpt", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--belief-ckpt", default=None)
    e.add_argument("--note", default="")
    p = sub.add_parser("parity")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--pkg", required=True)
    p.add_argument("--sha256", default=None)
    p.add_argument("--data", nargs="+", required=True)
    p.add_argument("--split", default="calib")
    p.add_argument("--chunks", type=int, default=4)
    p.add_argument("--rows", type=int, default=200)
    p.add_argument("--tol", type=float, default=1e-4)
    p.add_argument("--store-map", action="append", default=[])
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"train": train, "export": export, "parity": parity}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
