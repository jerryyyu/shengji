"""Infoset-Q distillation (#707 M11, tier-i DEV): an actor-view head trained on
true-world candidate values.

Stored self-play decisions come from the same policy that dealt them, so the true
deal of a stored decision is a draw from the correct posterior over worlds given
the actor's view.  Regressing the complete-world value of each admitted candidate
ON THE TRUE WORLD onto actor-visible inputs therefore learns
``E_{w ~ posterior}[V(w, a)]`` (the PerfectDou / PTIE logic), which the served
64-world mean estimates with a uniform constraint-consistent sampler.

Per decision of a trajectory store (``belief_labels.iter_decisions`` replays the
records in table order):

* **candidates** -- the production ballot: the record's ``ballot`` minus the
  exploration draws (``exploration.added``), so the served admitted set.  Decisions
  with fewer than two are skipped.
* **target** ``T`` -- each candidate's value on the TRUE world through serving's
  own leaf and reducer (``PVSearchBot.value_matrix`` with one world, the replayed
  deal completed by ``MCBot._complete_determinized_hands`` as the oracle-worlds
  diagnostic does).  Units: ``expected-signed-level-half-integer``, acting team.
* **baseline** ``W`` -- the record's own ``action_values.means``: the 64-world mean
  the data-generation bot computed with the served sampler and package (the store
  must name the package this module scores with; asserted).
* **inputs** -- actor-visible only: ``belief_labels.belief_features`` (the v4
  observation plus burial/declaration/pin/refusal/cap blocks) and
  ``history_summary`` (per-seat lead, ruff, feed and trick counts and the previous
  trick's cards); per candidate its card counts and ``candidate_features``.  The
  stored policy log-odds ``P`` is kept for the re-rank variant (it is computed on
  sampled worlds, so it is actor-visible too).

Splits are by deal (``belief_labels.split_of``, the S17 salt) and registered
non-trajectory seed windows are excluded, as in ``belief_labels``.

CLI: ``extract`` (resumable per chunk), ``train`` (torch), ``bench`` (serving cost).
Offline agreement is not strength.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.cards import SUITS, TRUMP, points
from ..rl.encode import CARD_INDEX, N_CARDS
from .belief_labels import (FEATURE_DIM, BeliefLabelError, _read_records, actor_memory,
                            belief_features, cluster_paths, excluded_windows, iter_decisions,
                            role_of, seed_excluded, split_of)
from .data import deal_key

SCHEMA = "shengji-infoset-q-v1"
KMAX = 12
EFF = tuple(SUITS) + (TRUMP,)
#: per relative seat: leads by effective suit, then six counters
SEAT_STATS = ("ruffs", "fed_partner_winning", "fed_opponent_winning", "tricks_won",
              "offsuit_discards", "trumps_played")
SEAT_DIM = len(EFF) + len(SEAT_STATS)
HIST_DIM = 4 * SEAT_DIM + 4 * N_CARDS + 4
CAND_FEATURES = ("n_cards", "points", "n_trump", "takes_trick", "leading", "trick_points")
CAND_DIM = len(CAND_FEATURES)
IN_DIM = FEATURE_DIM + HIST_DIM


class InfosetQError(ValueError):
    """A store, record or extract this module refuses."""


# ------------------------------------------------------------------ actor-view features

def _winner_so_far(plays, ordering) -> int | None:
    """The seat currently taking a trick whose plays so far are ``plays``."""
    from ..engine.combos import decompose
    from ..engine.legal import beats, uniform_suit
    if not plays:
        return None
    lead = plays[0].cards
    inc_suit = uniform_suit(lead, ordering)
    if inc_suit is None:
        return plays[0].seat
    inc_top = decompose(lead, ordering).top_level()
    winner = plays[0].seat
    for tp in plays[1:]:
        won, top = beats(tp.cards, lead, inc_suit, inc_top, ordering)
        if won:
            winner, inc_top = tp.seat, top
            inc_suit = ordering.eff_suit(tp.cards[0])
    return winner


def history_summary(rnd, seat: int) -> np.ndarray:
    """``HIST_DIM`` floats from the public play record, actor-relative seats."""
    o = rnd.ordering
    stats = np.zeros((4, SEAT_DIM), np.float32)
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick is not None and rnd.trick.plays else [])
    for trick in tricks:
        plays = trick.plays
        if not plays:
            continue
        lead_eff = o.eff_suit(plays[0].cards[0])
        stats[(plays[0].seat - seat) % 4, EFF.index(lead_eff)] += 1.0
        for pos, tp in enumerate(plays):
            rel = (tp.seat - seat) % 4
            effs = [o.eff_suit(c) for c in tp.cards]
            n_trump = sum(e == TRUMP for e in effs)
            stats[rel, len(EFF) + 5] += n_trump
            if pos == 0:
                continue
            short = sum(e != lead_eff for e in effs)
            if short and lead_eff != TRUMP and n_trump == len(effs):
                stats[rel, len(EFF) + 0] += 1.0
            elif short:
                stats[rel, len(EFF) + 4] += 1.0
            pts = sum(points(c) for c in tp.cards)
            if pts:
                before = _winner_so_far(plays[:pos], o)
                if before is not None and (before - tp.seat) % 4 == 2:
                    stats[rel, len(EFF) + 1] += pts
                elif before is not None and (before - tp.seat) % 2 == 1:
                    stats[rel, len(EFF) + 2] += pts
        if trick.winner is not None:
            stats[(trick.winner - seat) % 4, len(EFF) + 3] += 1.0
    scale = np.asarray([10.0] * len(EFF) + [10.0, 100.0, 100.0, 25.0, 10.0, 25.0], np.float32)
    stats /= scale
    last = np.zeros((4, N_CARDS), np.float32)
    leader = np.zeros(4, np.float32)
    if rnd.history:
        prev = rnd.history[-1]
        leader[(prev.leader - seat) % 4] = 1.0
        for tp in prev.plays:
            for c in tp.cards:
                last[(tp.seat - seat) % 4, CARD_INDEX[c]] += 0.5
    return np.concatenate([stats.ravel(), last.ravel(), leader])


def candidate_features(rnd, seat: int, action: Sequence[str]) -> np.ndarray:
    """``CAND_DIM`` floats for one candidate, from the actor's view."""
    from ..engine.round import TrickPlay
    o = rnd.ordering
    plays = list(rnd.trick.plays) if rnd.trick is not None else []
    leading = not plays
    n_trump = sum(o.eff_suit(c) == TRUMP for c in action)
    if leading:
        takes = 1.0
    else:
        takes = float(_winner_so_far(plays + [TrickPlay(seat, list(action))], o) == seat)
    trick_pts = sum(points(c) for tp in plays for c in tp.cards)
    return np.asarray([len(action) / 8.0, sum(points(c) for c in action) / 40.0, n_trump / 8.0,
                       takes, float(leading), trick_pts / 50.0], np.float32)


def card_counts(action: Sequence[str]) -> np.ndarray:
    out = np.zeros(N_CARDS, np.uint8)
    for c in action:
        out[CARD_INDEX[c]] += 1
    return out


def actor_inputs(rnd, seat: int, refusals=()) -> np.ndarray:
    """The ``IN_DIM`` actor-view row (what serving would compute once per decision)."""
    mem = actor_memory(rnd, seat, refusals)
    return np.concatenate([belief_features(rnd, seat, refusals, mem=mem),
                           history_summary(rnd, seat)])


# ------------------------------------------------------------------ targets

def production_ballot(rec: Mapping[str, Any]) -> tuple[list[list[str]], list[int]]:
    """The served admitted set (ballot minus exploration draws) and each one's
    index in the record's ballot."""
    ballot = [list(a) for a in rec.get("ballot") or []]
    added = Counter(tuple(sorted(a)) for a in ((rec.get("exploration") or {}).get("added") or []))
    keep, idx = [], []
    for i, a in enumerate(ballot):
        k = tuple(sorted(a))
        if added.get(k):
            added[k] -= 1
            continue
        keep.append(a)
        idx.append(i)
    if sum(added.values()):
        raise InfosetQError("an exploration draw is missing from the ballot")
    return keep, idx


def true_world(bot, rnd, seat: int):
    """The replayed deal as one world through production's world contract."""
    hands = bot.sampler._complete_determinized_hands(
        rnd, seat, {s: list(rnd.hands[s]) for s in range(4) if s != seat},
        buried=sorted(rnd.buried))
    return [(hands, sorted(rnd.buried))]


_BOT = None


def _bot(package: str, sha256: str):
    global _BOT
    if _BOT is None:
        from .pv_search_policy import make_pv_search_bot
        _BOT = make_pv_search_bot(package, sha256=sha256, seed=0, serving_budget_seconds=None,
                                  threads=1)
    return _BOT


def extract_cluster(path: Path, bot, *, store_index: int, cluster_index: int, calib: float,
                    test: float, windows, package_sha: str) -> dict | None:
    records = _read_records(path)
    plays = [r for r in records if r.get("decision_kind") == "play"]
    if not plays:
        return None
    if any(seed_excluded(r.get("round_seed"), windows) for r in plays):
        return {"excluded": True}
    key = deal_key(list(plays[0]["deck"]))
    split = split_of(key, calib, test)
    deal_hash = np.uint64(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    rows: dict[str, list] = {k: [] for k in ("X", "A", "AF", "M", "T", "W", "P", "played",
                                             "meta")}
    stats = Counter()
    for d in iter_decisions(plays):
        rec, rnd, seat = d.record, d.rnd, d.seat
        if package_sha not in str(rec.get("policy") or "") and package_sha[:8] not in str(
                rec.get("policy") or ""):
            raise InfosetQError(f"{path}: record policy {rec.get('policy')!r} is not package "
                                f"{package_sha[:8]}")
        stats["decisions"] += 1
        cands, idx = production_ballot(rec)
        if len(cands) < 2:
            stats["single_candidate"] += 1
            continue
        if len(cands) > KMAX:
            stats["over_kmax"] += 1
            cands, idx = cands[:KMAX], idx[:KMAX]
        av = rec.get("action_values") or {}
        means = av.get("means")
        if not means or int(av.get("worlds") or 0) != 64 or len(means) != len(rec["ballot"]):
            stats["no_w64_means"] += 1
            continue
        logodds = av.get("policy_log_odds") or [0.0] * len(means)
        matrix, sums, _ = bot.value_matrix(rnd, seat, cands, true_world(bot, rnd, seat))
        k = len(cands)
        A = np.zeros((KMAX, N_CARDS), np.uint8)
        AF = np.zeros((KMAX, CAND_DIM), np.float32)
        M = np.zeros(KMAX, bool)
        T = np.zeros(KMAX, np.float32)
        W = np.zeros(KMAX, np.float32)
        P = np.zeros(KMAX, np.float32)
        for j, a in enumerate(cands):
            A[j] = card_counts(a)
            AF[j] = candidate_features(rnd, seat, a)
        M[:k] = True
        T[:k] = sums
        W[:k] = [means[i] for i in idx]
        P[:k] = [logodds[i] for i in idx]
        played = rec.get("action")
        pk = tuple(sorted(played)) if played else None
        pi = next((j for j, a in enumerate(cands) if tuple(sorted(a)) == pk), -1)
        rows["X"].append(actor_inputs(rnd, seat, d.refusals).astype(np.float16))
        rows["A"].append(A)
        rows["AF"].append(AF)
        rows["M"].append(M)
        rows["T"].append(T)
        rows["W"].append(W)
        rows["P"].append(P)
        rows["played"].append(pi)
        rows["meta"].append((len(rnd.history) + 1, role_of(rnd, seat),
                             int(not rnd.trick.plays), d.round_index, d.decision_index, k))
        stats["rows"] += 1
    if not rows["X"]:
        return {"excluded": False, "split": split, "empty": True, "stats": dict(stats)}
    meta = np.asarray(rows["meta"], np.int64)
    n = len(rows["X"])
    return {
        "excluded": False, "split": split, "empty": False, "stats": dict(stats),
        "X": np.stack(rows["X"]), "A": np.stack(rows["A"]), "AF": np.stack(rows["AF"]),
        "M": np.stack(rows["M"]), "T": np.stack(rows["T"]), "W": np.stack(rows["W"]),
        "P": np.stack(rows["P"]), "played": np.asarray(rows["played"], np.int8),
        "trick": meta[:, 0].astype(np.int16), "role": meta[:, 1].astype(np.int8),
        "leading": meta[:, 2].astype(np.int8), "round_index": meta[:, 3].astype(np.int8),
        "decision": meta[:, 4].astype(np.int16), "k": meta[:, 5].astype(np.int8),
        "deal": np.full(n, deal_hash, np.uint64), "store": np.full(n, store_index, np.int16),
        "cluster": np.full(n, cluster_index, np.int32),
    }


ARRAY_KEYS = ("X", "A", "AF", "M", "T", "W", "P", "played", "trick", "role", "leading",
              "round_index", "decision", "k", "deal", "store", "cluster")


def _extract_task(args: tuple) -> dict:
    (paths, store_index, cluster_indices, out_dir, chunk, calib, test, windows, package,
     package_sha) = args
    done = Path(out_dir) / f"{chunk}.json"
    if done.exists():                         # resumable: a finished chunk is kept
        return json.loads(done.read_text())
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    bot = _bot(package, package_sha)
    t0 = time.time()
    per_split: dict[str, list[dict]] = {}
    stats = Counter()
    failed = []
    for path, ci in zip(paths, cluster_indices):
        try:
            got = extract_cluster(Path(path), bot, store_index=store_index, cluster_index=ci,
                                  calib=calib, test=test, windows=windows,
                                  package_sha=package_sha)
        except (BeliefLabelError, InfosetQError) as exc:
            failed.append({"path": str(path), "error": str(exc)[:300]})
            continue
        if got is None:
            continue
        if got["excluded"]:
            stats["excluded_clusters"] += 1
            continue
        stats.update(got["stats"])
        if not got["empty"]:
            per_split.setdefault(got["split"], []).append(got)
    files = {}
    for split, parts in per_split.items():
        arrays = {k: np.concatenate([p[k] for p in parts]) for k in ARRAY_KEYS}
        name = f"{split}-{chunk}.npz"
        tmp = Path(out_dir) / f".{name}.tmp.npz"
        np.savez_compressed(tmp, **arrays)
        os.replace(tmp, Path(out_dir) / name)
        files[split] = {"file": name, "rows": int(arrays["X"].shape[0]),
                        "sha256": hashlib.sha256((Path(out_dir) / name).read_bytes()).hexdigest()}
    res = {"chunk": chunk, "files": files, "stats": dict(stats), "failed": failed,
           "seconds": time.time() - t0}
    tmp = Path(out_dir) / f".{chunk}.json.tmp"
    tmp.write_text(json.dumps(res))
    os.replace(tmp, done)
    return res


def extract(stores: Sequence[str], out: str, *, package: str, package_sha: str,
            cluster_stride: int, cluster_offset: int, max_clusters_per_store: int | None,
            calib: float, test: float, workers: int, task_clusters: int, log=print) -> dict:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    actual = hashlib.sha256(Path(package).read_bytes()).hexdigest()
    if actual != package_sha:
        raise InfosetQError(f"package sha256 {actual} != {package_sha}")
    windows = excluded_windows()
    tasks = []
    for si, store in enumerate(stores):
        chosen = [(ci, p) for ci, p in enumerate(cluster_paths(store))
                  if ci % cluster_stride == cluster_offset]
        if max_clusters_per_store is not None:
            chosen = chosen[:max_clusters_per_store]
        for start in range(0, len(chosen), task_clusters):
            group = chosen[start:start + task_clusters]
            tasks.append(([str(p) for _, p in group], si, [ci for ci, _ in group], str(out_dir),
                          f"s{si:02d}-{start // task_clusters:05d}", calib, test, windows,
                          package, package_sha))
    stats = Counter()
    chunks = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_extract_task, tasks)):
            chunks.append(res)
            stats.update(res["stats"])
            if (i + 1) % 5 == 0 or i + 1 == len(tasks):
                log(f"[extract] {i + 1}/{len(tasks)} chunks {time.time() - t0:.0f}s "
                    f"{dict(stats)}", flush=True)
    manifest = {"schema": SCHEMA, "in_dim": IN_DIM, "feature_dim": FEATURE_DIM,
                "hist_dim": HIST_DIM, "cand_features": CAND_FEATURES, "kmax": KMAX,
                "stores": list(stores), "package": package, "package_sha256": package_sha,
                "cluster_stride": cluster_stride, "cluster_offset": cluster_offset,
                "max_clusters_per_store": max_clusters_per_store,
                "split": {"salt": "belief_labels.SPLIT_SALT", "calib": calib, "test": test},
                "excluded_windows": windows, "chunks": chunks, "stats": dict(stats),
                "failed": sum(len(c["failed"]) for c in chunks), "seconds": time.time() - t0}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=list))
    return manifest


def load_split(dirs: Sequence[str], split: str) -> dict[str, np.ndarray]:
    parts: dict[str, list] = {k: [] for k in ARRAY_KEYS}
    for d in dirs:
        manifest = json.loads((Path(d) / "manifest.json").read_text())
        if manifest.get("schema") != SCHEMA:
            raise InfosetQError(f"{d} is not an infoset-q extract")
        for c in manifest["chunks"]:
            f = c["files"].get(split)
            if not f:
                continue
            path = Path(d) / f["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
                raise InfosetQError(f"{path}: sha256 mismatch")
            with np.load(path) as z:
                for k in ARRAY_KEYS:
                    parts[k].append(z[k])
    if not parts["X"]:
        raise InfosetQError(f"split {split} is empty")
    return {k: np.concatenate(v) for k, v in parts.items()}


# ------------------------------------------------------------------ metrics

NEG = -1e9
TIE = 1e-6


def choose(scores: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return np.where(mask, scores, NEG).argmax(axis=1)


def outcome(choice: np.ndarray, T: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(agree, regret): ``agree`` is True when the chosen candidate's true-world value
    equals the true-world best (ties count: equal cards price equally); ``regret`` is
    best minus chosen, in value units."""
    best = np.where(mask, T, NEG).max(axis=1)
    got = T[np.arange(len(T)), choice]
    return got >= best - TIE, best - got


def trick_bucket(trick: np.ndarray) -> np.ndarray:
    edges = np.asarray([5, 10, 15, 20])
    return np.searchsorted(edges, trick, side="right")


TRICK_BUCKETS = ("t01-05", "t06-10", "t11-15", "t16-20", "t21+")


def bootstrap_diff(a: np.ndarray, b: np.ndarray, groups: np.ndarray, *, n: int = 1000,
                   seed: int = 0) -> tuple[float, float, float]:
    """Mean of ``a - b`` with a 95% percentile interval, resampling whole deals."""
    diff = a.astype(np.float64) - b.astype(np.float64)
    uniq, inv = np.unique(groups, return_inverse=True)
    sums = np.bincount(inv, weights=diff, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(np.float64)
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        stats.append(sums[pick].sum() / cnts[pick].sum())
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)


def report(name_scores: Mapping[str, np.ndarray], data: Mapping[str, np.ndarray],
           baseline: str = "w64") -> dict:
    T, M = data["T"], data["M"]
    deal = data["deal"]
    bucket = trick_bucket(data["trick"])
    out: dict[str, Any] = {"rows": int(len(T)), "deals": int(len(np.unique(deal)))}
    results = {}
    for name, s in name_scores.items():
        agree, regret = outcome(choose(s, M), T, M)
        results[name] = (agree, regret)
    base_a, base_r = results[baseline]
    for name, (agree, regret) in results.items():
        row = {"agree": float(agree.mean()), "regret": float(regret.mean())}
        if name != baseline:
            row["agree_minus_w64"] = bootstrap_diff(agree, base_a, deal)
            row["regret_minus_w64"] = bootstrap_diff(regret, base_r, deal)
        by = {}
        for b, label in enumerate(TRICK_BUCKETS):
            sel = bucket == b
            if sel.any():
                by[label] = {"n": int(sel.sum()), "agree": float(agree[sel].mean()),
                             "agree_w64": float(base_a[sel].mean()),
                             "regret": float(regret[sel].mean()),
                             "regret_w64": float(base_r[sel].mean())}
        for label, sel in (("lead", data["leading"] == 1), ("follow", data["leading"] == 0)):
            by[label] = {"n": int(sel.sum()), "agree": float(agree[sel].mean()),
                         "agree_w64": float(base_a[sel].mean()),
                         "regret": float(regret[sel].mean()),
                         "regret_w64": float(base_r[sel].mean())}
        row["by"] = by
        out[name] = row
    return out


# ------------------------------------------------------------------ model (torch)

def _torch():
    import torch
    return torch


def build_model(in_dim: int, rerank: bool, hidden: int = 512):
    torch = _torch()
    nn = torch.nn
    extra = 3 if rerank else 0

    class InfosetQ(nn.Module):
        def __init__(self):
            super().__init__()
            self.state = nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(),
                                       nn.Linear(hidden, 256), nn.ReLU())
            self.act = nn.Sequential(nn.Linear(N_CARDS + CAND_DIM + extra, 128), nn.ReLU())
            self.head = nn.Sequential(nn.Linear(256 + 128 + 256, 256), nn.ReLU(),
                                      nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, 1))
            self.mix = nn.Linear(128, 256, bias=False)

        def forward(self, x, a):
            s = self.state(x)                               # (B, 256)
            e = self.act(a)                                 # (B, K, 128)
            sk = s[:, None, :].expand(-1, a.shape[1], -1)
            h = torch.cat([sk, e, sk * self.mix(e)], dim=-1)
            return self.head(h).squeeze(-1)                 # (B, K)

    return InfosetQ()


def _cand_tensor(data, sel, rerank: bool):
    A = data["A"][sel].astype(np.float32)
    AF = data["AF"][sel].astype(np.float32)
    parts = [A, AF]
    if rerank:
        M = data["M"][sel]
        W = data["W"][sel].astype(np.float32)
        P = data["P"][sel].astype(np.float32)
        k = M.sum(1, keepdims=True).clip(1)
        wc = W - (W * M).sum(1, keepdims=True) / k
        pc = P - (P * M).sum(1, keepdims=True) / k
        parts += [W[..., None], wc[..., None] * 5.0, pc[..., None] / 5.0]
    return np.concatenate(parts, axis=-1)


def train(dirs: Sequence[str], out: str, *, rerank: bool, epochs: int, batch: int, lr: float,
          threads: int, max_train: int | None, seed: int, log=print) -> dict:
    torch = _torch()
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tr = load_split(dirs, "train")
    ca = load_split(dirs, "calib")
    n = len(tr["X"]) if max_train is None else min(len(tr["X"]), max_train)
    rng_np = np.random.default_rng(seed)
    log(f"[train] rows train={len(tr['X'])} (using {n}) calib={len(ca['X'])}", flush=True)
    sample = np.sort(rng_np.choice(n, min(n, 200_000), replace=False))
    X32 = tr["X"][sample].astype(np.float32)
    mu = X32.mean(0)
    sd = X32.std(0) + 1e-3
    del X32
    np.savez(out_dir / "norm.npz", mu=mu, sd=sd)
    model = build_model(IN_DIM, rerank)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-5)
    steps = epochs * math.ceil(n / batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps,
                                                pct_start=0.05)
    rng = np.random.default_rng(seed)

    def tensors(data, sel):
        x = torch.from_numpy(((data["X"][sel].astype(np.float32) - mu) / sd))
        a = torch.from_numpy(_cand_tensor(data, sel, rerank))
        m = torch.from_numpy(data["M"][sel])
        t = torch.from_numpy(data["T"][sel].astype(np.float32))
        return x, a, m, t

    def predict(data):
        model.eval()
        outs = []
        with torch.no_grad():
            for s in range(0, len(data["X"]), 4096):
                sel = np.arange(s, min(s + 4096, len(data["X"])))
                x, a, _, _ = tensors(data, sel)
                outs.append(model(x, a).numpy())
        model.train()
        return np.concatenate(outs)

    history = []
    best = None
    for ep in range(epochs):
        perm = rng.permutation(n)
        t0 = time.time()
        tot = 0.0
        for s in range(0, n, batch):
            sel = np.sort(perm[s:s + batch])
            x, a, m, t = tensors(tr, sel)
            pred = model(x, a)
            mf = m.float()
            k = mf.sum(1, keepdim=True).clamp(min=1)
            err = (pred - t) * mf
            centered = err - (err.sum(1, keepdim=True) / k) * mf
            loss = ((err ** 2).sum() + (centered ** 2).sum()) / mf.sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += float(loss) * len(sel)
        pc = predict(ca)
        agree, regret = outcome(choose(pc, ca["M"]), ca["T"], ca["M"])
        w_agree, w_regret = outcome(choose(ca["W"], ca["M"]), ca["T"], ca["M"])
        rec = {"epoch": ep, "train_loss": tot / n, "calib_agree": float(agree.mean()),
               "calib_agree_w64": float(w_agree.mean()), "calib_regret": float(regret.mean()),
               "calib_regret_w64": float(w_regret.mean()), "seconds": time.time() - t0}
        history.append(rec)
        log(f"[train] {json.dumps(rec)}", flush=True)
        if best is None or rec["calib_agree"] > best["calib_agree"]:
            best = rec
            torch.save(model.state_dict(), out_dir / "model.pt")
    model.load_state_dict(torch.load(out_dir / "model.pt"))
    summary = {"schema": SCHEMA + "-train", "rerank": rerank, "rows_train": int(n),
               "rows_calib": int(len(ca["X"])), "epochs": epochs, "batch": batch, "lr": lr,
               "history": history, "best": best, "dirs": list(dirs)}
    (out_dir / "train.json").write_text(json.dumps(summary, indent=1))
    return summary


def load_model(out: str, rerank: bool):
    torch = _torch()
    model = build_model(IN_DIM, rerank)
    model.load_state_dict(torch.load(Path(out) / "model.pt"))
    model.eval()
    z = np.load(Path(out) / "norm.npz")
    return model, z["mu"], z["sd"]


def predict_split(model, mu, sd, data, rerank: bool) -> np.ndarray:
    torch = _torch()
    outs = []
    with torch.no_grad():
        for s in range(0, len(data["X"]), 4096):
            sel = np.arange(s, min(s + 4096, len(data["X"])))
            x = torch.from_numpy((data["X"][sel].astype(np.float32) - mu) / sd)
            a = torch.from_numpy(_cand_tensor(data, sel, rerank))
            outs.append(model(x, a).numpy())
    return np.concatenate(outs)


def evaluate(dirs: Sequence[str], heads: Mapping[str, tuple[str, bool]], out: str,
             alphas: Sequence[float] = (0.25, 0.5, 0.75), log=print) -> dict:
    """Test-split agreement and regret: W64 (the stored served means), the policy
    log-odds argmax, every head, and alpha-blends of each head with W64 (alpha
    picked on calib, all reported)."""
    torch = _torch()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    res: dict[str, Any] = {}
    for split in ("calib", "test"):
        data = load_split(dirs, split)
        scores = {"w64": data["W"].astype(np.float64), "policy": data["P"].astype(np.float64)}
        for name, (path, rerank) in heads.items():
            model, mu, sd = load_model(path, rerank)
            h = predict_split(model, mu, sd, data, rerank).astype(np.float64)
            scores[name] = h
            for al in alphas:
                scores[f"{name}_blend{al:g}"] = al * h + (1 - al) * scores["w64"]
        res[split] = report(scores, data)
        log(f"[eval] {split} " + json.dumps({k: (v["agree"] if isinstance(v, dict) and "agree" in v
                                                  else v) for k, v in res[split].items()}),
            flush=True)
    Path(out).write_text(json.dumps(res, indent=1))
    return res


# ------------------------------------------------------------------ serving cost

def bench(store: str, head: str, *, clusters: int, rerank: bool, log=print) -> dict:
    """Wall time of what serving would add per decision: the actor-view row
    (``actor_inputs``), the per-candidate features, and one head forward over the
    candidates (torch, one thread), on replayed store decisions."""
    torch = _torch()
    torch.set_num_threads(1)
    model, mu, sd = load_model(head, rerank)
    feat_t, cand_t, fwd_t, ks = [], [], [], []
    for path in cluster_paths(store)[:clusters]:
        plays = [r for r in _read_records(path) if r.get("decision_kind") == "play"]
        for d in iter_decisions(plays):
            cands, _ = production_ballot(d.record)
            if len(cands) < 2:
                continue
            cands = cands[:KMAX]
            t0 = time.perf_counter()
            x = actor_inputs(d.rnd, d.seat, d.refusals)
            t1 = time.perf_counter()
            a = np.zeros((1, len(cands), N_CARDS + CAND_DIM + (3 if rerank else 0)), np.float32)
            for j, c in enumerate(cands):
                a[0, j, :N_CARDS] = card_counts(c)
                a[0, j, N_CARDS:N_CARDS + CAND_DIM] = candidate_features(d.rnd, d.seat, c)
            t2 = time.perf_counter()
            with torch.no_grad():
                model(torch.from_numpy(((x - mu) / sd)[None].astype(np.float32)),
                      torch.from_numpy(a))
            t3 = time.perf_counter()
            feat_t.append(t1 - t0)
            cand_t.append(t2 - t1)
            fwd_t.append(t3 - t2)
            ks.append(len(cands))

    def q(v):
        v = np.asarray(v) * 1000.0
        return {"p50_ms": float(np.percentile(v, 50)), "p95_ms": float(np.percentile(v, 95)),
                "max_ms": float(v.max()), "mean_ms": float(v.mean())}

    total = np.asarray(feat_t) + np.asarray(cand_t) + np.asarray(fwd_t)
    out = {"decisions": len(ks), "mean_candidates": float(np.mean(ks)),
           "actor_inputs": q(feat_t), "candidate_features": q(cand_t), "head_forward": q(fwd_t),
           "total": q(total), "threads": 1}
    log(json.dumps(out))
    return out


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="infoset_q", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("--store", action="append", required=True)
    ex.add_argument("--out", required=True)
    ex.add_argument("--package", required=True)
    ex.add_argument("--package-sha256", required=True)
    ex.add_argument("--cluster-stride", type=int, default=1)
    ex.add_argument("--cluster-offset", type=int, default=0)
    ex.add_argument("--max-clusters-per-store", type=int, default=None)
    ex.add_argument("--calib", type=float, default=0.06)
    ex.add_argument("--test", type=float, default=0.12)
    ex.add_argument("--workers", type=int, default=4)
    ex.add_argument("--task-clusters", type=int, default=20)
    tr = sub.add_parser("train")
    tr.add_argument("--data", nargs="+", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--rerank", action="store_true")
    tr.add_argument("--epochs", type=int, default=8)
    tr.add_argument("--batch", type=int, default=512)
    tr.add_argument("--lr", type=float, default=1e-3)
    tr.add_argument("--threads", type=int, default=4)
    tr.add_argument("--max-train", type=int, default=None)
    tr.add_argument("--seed", type=int, default=0)
    ev = sub.add_parser("eval")
    ev.add_argument("--data", nargs="+", required=True)
    ev.add_argument("--head", action="append", required=True,
                    help="NAME=DIR or NAME=DIR:rerank")
    ev.add_argument("--out", required=True)
    be = sub.add_parser("bench")
    be.add_argument("--store", required=True)
    be.add_argument("--head", required=True)
    be.add_argument("--rerank", action="store_true")
    be.add_argument("--clusters", type=int, default=4)
    be.add_argument("--out", required=True)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        m = extract(args.store, args.out, package=args.package, package_sha=args.package_sha256,
                    cluster_stride=args.cluster_stride, cluster_offset=args.cluster_offset,
                    max_clusters_per_store=args.max_clusters_per_store, calib=args.calib,
                    test=args.test, workers=args.workers, task_clusters=args.task_clusters)
        print(json.dumps({"stats": m["stats"], "failed": m["failed"], "seconds": m["seconds"]}))
        return 0
    if args.command == "train":
        train(args.data, args.out, rerank=args.rerank, epochs=args.epochs, batch=args.batch,
              lr=args.lr, threads=args.threads, max_train=args.max_train, seed=args.seed)
        return 0
    if args.command == "eval":
        heads = {}
        for spec in args.head:
            name, _, rest = spec.partition("=")
            path, _, flag = rest.partition(":")
            heads[name] = (path, flag == "rerank")
        evaluate(args.data, heads, args.out)
        return 0
    if args.command == "bench":
        r = bench(args.store, args.head, clusters=args.clusters, rerank=args.rerank)
        Path(args.out).write_text(json.dumps(r, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
