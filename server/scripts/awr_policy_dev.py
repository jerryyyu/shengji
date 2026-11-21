"""S155 DEV: advantage-weighted training of the unified model's root policy head on a frozen trunk.

The trunk is frozen, so the policy head (``p_head``: a per-card tower over the trunk's card states)
trains on cached card states.  ``cache`` runs the served checkpoint once over chosen rows and keeps,
per row, the card states of the cards in hand, the attempted action, the outcome category, the Q
head's expected outcome, the hand-strength features of the actor's first decision of the round, and
the row's trajectory record (legal actions, the search's choice, its per-candidate means).  ``exact``
solves the true world exactly for every legal action of late held-out positions.  ``sweep`` trains
copies of the served head, every arm on the same rows in the same order with the same seed, and
scores each on the validation split; ``final`` scores the control and named arms on the test split.

Metrics: recall@8 = the search's choice is among the 8 legal actions the head ranks highest (an
action scores the count-weighted sum of its cards' log-odds, as the served prior scores it), over
positions with more than 8 complete legal actions; regret = the exact true-world value of the best
legal action minus that of the head's top action (levels, actor's side); CE = the unweighted listwise
policy cross-entropy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.rl.encode import CARD_INDEX  # noqa: E402
from shengji.train import belief_labels as bl  # noqa: E402
from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train import unified_readout as ur  # noqa: E402
from shengji.train import unified_seq as us  # noqa: E402

K = 27                     # card slots per row: distinct cards in hand (at most 25 in play)
N_HS = 13                  # hand-strength features


def _counts(cards) -> Counter:
    return Counter(CARD_INDEX[c] for c in cards)


def hand_strength(hand_counts: np.ndarray, card_feat: np.ndarray) -> np.ndarray:
    """``(N_HS,)``: trumps, trump pairs, jokers, trump-rank cards, off-suit aces, off-suit pairs,
    points, trump tractors (adjacent trump levels both paired), cards, per-suit off lengths (4)."""
    c = hand_counts.astype(np.float32)
    trump = card_feat[:, 0] > 0
    lvl = card_feat[:, 6]
    pts = card_feat[:, 7] * 10
    from shengji.train.belief_history import _CODES
    ace = np.array([code[1:] == "A" if len(code) > 1 else False for code in _CODES])
    pairs = c >= 2
    tl = np.sort(np.unique(lvl[trump & pairs]))
    tractors = float(np.sum(np.diff(tl) < (1.5 / 16.0))) if len(tl) > 1 else 0.0
    suits = [c[(card_feat[:, 1 + s] > 0) & ~trump].sum() for s in range(4)]
    return np.array([c[trump].sum(), pairs[trump].sum(), c[card_feat[:, 8] > 0].sum(), c[card_feat[:, 9] > 0].sum(),
                     c[ace & ~trump].sum(), pairs[~trump].sum(), (c * pts).sum() / 10.0, tractors, c.sum(), *suits],
                    np.float32)


# ------------------------------------------------------------------ cache

class Records:
    """A cluster's play records in table order, sha-checked against its store manifest."""

    def __init__(self, index: us.OutcomeIndex):
        self.index = index
        self.cache: dict = {}

    def get(self, recorded: str, data_dir: str, cluster_index: int) -> list[dict]:
        key = (recorded, data_dir, cluster_index)
        if key in self.cache:
            return self.cache[key]
        st = self.index._store(self.index.resolve(recorded, data_dir))
        sh = st["by_name"][st["names"][int(cluster_index)]]
        raw = (Path(st["local"]) / sh["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sh["sha256"]:
            raise SystemExit(f"{sh['path']}: sha256 differs from the store manifest")
        recs = bl.game_order(json.loads(line) for line in raw.decode().splitlines() if line.strip())
        if len(self.cache) > 64:
            self.cache.clear()
        self.cache[key] = recs
        return recs


def cache_part(model, part, entry, records: Records, *, heldout: bool):
    import torch
    levels = torch.as_tensor(us.outcome_levels(), dtype=torch.float32)
    n = len(part["X"])
    out = {"F": np.zeros((n, K, 192), np.float16), "slot": np.full((n, K), -1, np.int8),
           "hcnt": np.zeros((n, K), np.uint8), "tgt": np.zeros((n, K), np.float32),
           "V": np.zeros(n, np.float32), "logit0": np.zeros((n, K), np.float32)}
    with torch.no_grad():
        for rids, rows in bs.round_batches(part, 32, None):
            b = us.make_unified_batch(part, rids, rows)
            tb = us.to_device(b, "cpu")
            _, enc, q, g = us.trunk_forward(model.trunk, tb)
            frame = tb["rr"] * 4 + tb["seat"]
            ql = model.q_head(torch.cat([enc[frame, tb["ply"]], g], -1).float())
            out["V"][rows] = (torch.softmax(ql.float(), -1) @ levels).numpy()
            pl = model.p_head(q.float()).squeeze(-1).numpy()
            hand = np.rint(2.0 * b["X"][:, :54]).astype(np.int64)     # the hand block is counts / 2
            qn = q.float().numpy()
            for j, r in enumerate(rows):
                idx = np.flatnonzero(hand[j] > 0)
                if len(idx) > K:
                    raise SystemExit("more distinct cards in hand than slots")
                out["slot"][r, :len(idx)] = idx
                out["hcnt"][r, :len(idx)] = hand[j, idx]
                out["F"][r, :len(idx)] = qn[j, idx].astype(np.float16)
                t = b["pol_target"][j, idx]
                out["tgt"][r, :len(idx)] = t / t.sum()
                out["logit0"][r, :len(idx)] = pl[j, idx]
    cf = part["_rounds"]["card_feat"]
    rr = part["row_round"].astype(np.int64)
    seq_key = rr * 4 + part["row_seat"].astype(np.int64)
    hs = np.zeros((n, N_HS), np.float32)
    for k in np.unique(seq_key):
        sel = np.flatnonzero(seq_key == k)
        first = sel[np.argmin(part["row_ply"][sel])]
        hs[sel] = hand_strength(np.rint(2.0 * part["X"][first, :54]), cf[rr[first]])
    out["hs"] = hs
    # trajectory records: legal actions, the search's choice and its per-candidate means
    legal, chosen, complete, cand, cand_mean = [], np.full(n, -1, np.int32), np.zeros(n, bool), [], []
    for r in range(n):
        recs = records.get(entry["stores"][int(part["store"][r])], entry["dir"], int(part["cluster"][r]))
        rec = recs[int(part["decision"][r])]
        if int(rec["seat"]) != int(part["row_seat"][r]) or len(rec.get("plays_prefix") or []) != int(part["row_ply"][r]):
            raise SystemExit("record join: seat or ply differs")
        slot_of = {int(c): i for i, c in enumerate(out["slot"][r]) if c >= 0}
        act = _counts(rec["action"])
        tg = {slot_of[c]: v for c, v in act.items()}
        tot = sum(tg.values())
        if any(abs(out["tgt"][r, s] - v / tot) > 1e-5 for s, v in tg.items()):
            raise SystemExit("record join: the action differs from the row's target")
        acts = [rec["action"]] if not rec.get("legal_actions") else rec["legal_actions"]
        vecs = np.zeros((len(acts), K), np.uint8)
        for i, a in enumerate(acts):
            for c, v in _counts(a).items():
                vecs[i, slot_of[c]] = v
        legal.append(vecs)
        hit = [i for i, a in enumerate(acts) if Counter(a) == Counter(rec["action"])]
        chosen[r] = hit[0] if hit else -1
        complete[r] = bool(rec.get("legal_actions_complete")) and bool(hit)
        # the search's means index its ballot (``eligible_indices``); a late stage may append an
        # unpriced candidate (mean None), which is left out
        av = rec.get("action_values") or {}
        ballot = rec.get("ballot") or []
        el, means = list(av.get("eligible_indices") or []), list(av.get("means") or [])
        if len(el) != len(means):
            el, means = [], []
        keep = [(i, m) for i, m in zip(el, means) if m is not None and 0 <= int(i) < len(ballot)]
        cv = np.zeros((len(keep), K), np.uint8)
        for j, (i, _) in enumerate(keep):
            for c, v in _counts(ballot[int(i)]).items():
                cv[j, slot_of[c]] = v
        cand.append(cv)
        cand_mean.append(np.asarray([m for _, m in keep], np.float32))
    out["L_off"] = np.cumsum([0] + [len(v) for v in legal]).astype(np.int64)
    out["L"] = np.concatenate(legal) if legal else np.zeros((0, K), np.uint8)
    out["chosen"], out["complete"] = chosen, complete
    out["C_off"] = np.cumsum([0] + [len(v) for v in cand]).astype(np.int64)
    out["C_vec"] = np.concatenate(cand) if cand else np.zeros((0, K), np.uint8)
    out["C_mean"] = np.concatenate(cand_mean) if cand_mean else np.zeros(0, np.float32)
    out["qcat"] = part["q_target"].astype(np.int16)
    for k in ("store", "cluster", "round_index", "decision", "row_seat", "row_ply", "deal", "trick", "role"):
        out[k] = np.asarray(part[k]).astype(np.int64)
    out["hand_n"] = np.rint(2.0 * part["X"][:, :54]).sum(1).astype(np.int16)
    out["dir_id"] = np.zeros(n, np.int64)
    return out


def concat(chunks, dir_ids):
    out = {}
    for k in chunks[0]:
        if k in ("L_off", "C_off"):
            continue
        out[k] = np.concatenate([c[k] for c in chunks])
    for off, arr in (("L_off", "L"), ("C_off", "C_vec")):
        offs, base = [np.zeros(1, np.int64)], 0
        for c in chunks:
            offs.append(c[off][1:] + base)
            base += len(c[arr])
        out[off] = np.concatenate(offs)
    out["dir_id"] = np.concatenate([np.full(len(c["V"]), d, np.int64) for c, d in zip(chunks, dir_ids)])
    return out


def cmd_cache(args) -> int:
    import torch
    torch.set_num_threads(args.threads)
    model, saved = ur.load_checkpoint(args.ckpt)
    sha = us.sha256_file(args.ckpt)
    if args.ckpt_sha256 and sha != args.ckpt_sha256:
        raise SystemExit(f"checkpoint sha {sha} != {args.ckpt_sha256}")
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))
    records = Records(index)
    verified = bs._Verified()
    windows = [tuple(int(x) for x in w.split(":")) for w in args.exclude_seed_window]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for split, dirs, want in (("train", args.train_data, args.train_rows), ("test", args.heldout_data, args.heldout_rows)):
        entries = us.entries_for(dirs, split, exclude_seed_windows=windows)
        rng = np.random.default_rng(args.seed)
        picked, n = [], 0
        for i in rng.permutation(len(entries)):
            if n >= want:
                break
            picked.append(entries[i])
            n += entries[i]["rows"]
        chunks, dir_ids, t0 = [], [], time.time()
        for j, e in enumerate(picked):
            part = us.load_unified_part(e, verified, index)
            if not len(part["X"]):
                continue
            chunks.append(cache_part(model, part, e, records, heldout=split == "test"))
            dir_ids.append(dirs.index(e["dir"]))
            if j % 20 == 0:
                print(f"[cache] {split} {j + 1}/{len(picked)} chunks {sum(len(c['V']) for c in chunks)} rows "
                      f"{time.time() - t0:.0f}s", flush=True)
        z = concat(chunks, dir_ids)
        name = "train" if split == "train" else "heldout"
        np.savez(out / f"{name}.npz", **z)
        print(f"[cache] wrote {name}: {len(z['V'])} rows ({time.time() - t0:.0f}s)", flush=True)
    meta = {"ckpt": args.ckpt, "ckpt_sha256": sha, "train_data": args.train_data, "heldout_data": args.heldout_data,
            "store_map": args.store_map, "seed": args.seed, "exclude_seed_window": args.exclude_seed_window}
    (out / "cache_meta.json").write_text(json.dumps(meta, indent=1))
    return 0


# ------------------------------------------------------------------ exact late positions

def _exact_cluster(task):
    from shengji.train.pv_exact_follow import _world_scores, ExactFollowRefusal
    path, sha, wanted, max_nodes = task
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise SystemExit(f"{path}: sha256 differs")
    recs = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    res = {}
    for d in bl.iter_decisions(recs):
        if d.decision_index not in wanted:
            continue
        rnd = d.rnd
        legal = d.record["legal_actions"]
        att = (d.seat % 2) != (int(rnd.banker) % 2)
        t0 = time.time()
        try:
            scores, nodes = _world_scores(rnd, d.seat, legal, ([list(h) for h in rnd.hands], list(rnd.buried)),
                                          7, max_nodes, None, "compact-level", att)
        except ExactFollowRefusal as exc:
            res[d.decision_index] = {"refused": str(exc)[:80]}
            continue
        res[d.decision_index] = {"scores": scores, "nodes": nodes, "s": time.time() - t0}
    return path, res


def cmd_exact(args) -> int:
    from concurrent.futures import ProcessPoolExecutor
    z = dict(np.load(Path(args.cache) / "heldout.npz"))
    meta = json.loads((Path(args.cache) / "cache_meta.json").read_text())
    index = us.OutcomeIndex(us.parse_store_map(meta["store_map"]))
    dirs = meta["heldout_data"]
    stores = {d: json.loads((Path(d) / "manifest.json").read_text())["stores"] for d in dirs}
    nl = np.diff(z["L_off"])
    split = split_of(z)
    rng = np.random.default_rng(args.seed)
    picked = []
    for s in ("val", "test"):
        cand = np.flatnonzero((z["hand_n"] <= 7) & (nl >= 2) & z["complete"] & (split == s))
        picked += list(rng.choice(cand, min(args.per_split, len(cand)), replace=False))
    tasks = {}
    for r in picked:
        d = dirs[int(z["dir_id"][r])]
        st = index._store(index.resolve(stores[d][int(z["store"][r])], d))
        sh = st["by_name"][st["names"][int(z["cluster"][r])]]
        p = str(Path(st["local"]) / sh["path"])
        tasks.setdefault((p, sh["sha256"]), {})[int(z["decision"][r])] = int(r)
    t0 = time.time()
    found = {}
    with ProcessPoolExecutor(args.workers) as ex:
        for path, res in ex.map(_exact_cluster, [(p, s, set(w), args.max_nodes) for (p, s), w in tasks.items()]):
            want = [w for (pp, _), w in tasks.items() if pp == path][0]
            for dec, v in res.items():
                found[want[dec]] = v
    ok = {r: v for r, v in found.items() if "scores" in v}
    print(f"[exact] {len(ok)}/{len(picked)} solved ({len(found) - len(ok)} refused) in {time.time() - t0:.0f}s; "
          f"max {max((v['s'] for v in ok.values()), default=0):.1f}s", flush=True)
    rows = np.asarray(sorted(ok), np.int64)
    flat = np.concatenate([np.asarray(ok[r]["scores"], np.float32) for r in rows])
    for r in rows:
        if len(ok[r]["scores"]) != nl[r]:
            raise SystemExit("exact: score count differs from the legal list")
    np.savez(Path(args.cache) / "exact.npz", rows=rows, scores=flat)
    return 0


# ------------------------------------------------------------------ the sweep

def split_of(z) -> np.ndarray:
    """val or test per held-out row, by a hash of its deal."""
    key = z["dir_id"] * 1_000_003 + z["deal"]
    h = np.array([int(hashlib.sha256(f"s155|{k}".encode()).hexdigest()[:8], 16) for k in key])
    return np.where(h % 2 == 0, "val", "test")


def build_head(ckpt):
    import torch
    saved = torch.load(ckpt, weights_only=False, map_location="cpu")
    m = us.build_unified(saved["config"]["trunk"])
    sd = {k[len("p_head."):]: v for k, v in saved["model"].items() if k.startswith("p_head.")}
    m.p_head.load_state_dict(sd)
    return m.p_head


def head_logits(head, F, slot):
    import torch
    lg = head(F.float()).squeeze(-1)
    return lg.masked_fill(slot < 0, -1e9)


def row_ce(lg, tgt):
    import torch
    return -(tgt * torch.log_softmax(lg, -1)).sum(-1)


def weights_for(arm, A, rank_batch):
    """Per-row weights of one batch from its advantages ``A`` (torch)."""
    import torch
    beta, cap, shape = arm.get("beta"), arm.get("cap", 20.0), arm.get("shape", "exp")
    if beta is None or shape == "none":
        return torch.ones_like(A)
    if shape == "exp":
        return us.awr_weights(A, beta, cap)
    if shape == "pos":
        w = torch.clamp(1.0 + torch.clamp(A, min=0.0) / beta, max=cap)
        return w / w.mean()
    if shape == "rank":
        r = torch.argsort(torch.argsort(A)).float()
        w = (r + 0.5) / len(A)
        return w / w.mean()
    raise SystemExit(f"unknown shape {shape}")


def advantages(z, baseline: str, lam: float, ridge=None) -> np.ndarray:
    out = us.outcome_levels()[z["qcat"].astype(np.int64)]
    if baseline == "none":
        return out
    if baseline == "hand":
        return out - ridge(z)
    if baseline == "search":
        return search_advantage(z)
    seq = (z["dir_id"] * 10**9 + z["store"] * 10**7 + z["cluster"] * 100 + z["round_index"]) * 4 + z["row_seat"]
    if lam == 1.0:
        return out - z["V"].astype(np.float64)
    return us.gae_advantages(z["V"], out, seq, z["row_ply"], lam)


def fit_ridge(z, alpha=1.0):
    """Outcome on the hand-strength features (and the role) by ridge regression, training rows only."""
    def design(zz):
        role = np.eye(3)[np.clip(zz["role"], 0, 2)]
        return np.concatenate([zz["hs"], role, np.ones((len(zz["hs"]), 1))], 1)
    X = design(z)
    y = us.outcome_levels()[z["qcat"].astype(np.int64)]
    mu, sd = X[:, :-1].mean(0), X[:, :-1].std(0) + 1e-6
    Xs = np.concatenate([(X[:, :-1] - mu) / sd, X[:, -1:]], 1)
    w = np.linalg.solve(Xs.T @ Xs + alpha * np.eye(Xs.shape[1]), Xs.T @ y)
    r2 = 1 - np.mean((Xs @ w - y) ** 2) / np.var(y)

    def predict(zz):
        Xz = design(zz)
        return np.concatenate([(Xz[:, :-1] - mu) / sd, Xz[:, -1:]], 1) @ w
    predict.r2 = float(r2)
    return predict


def search_advantage(z) -> np.ndarray:
    """The played action's search mean minus the mean over the priced candidates (levels); 0 where
    the played action is unpriced or fewer than two candidates are priced."""
    out = np.zeros(len(z["V"]), np.float64)
    for r in range(len(out)):
        a, b = z["C_off"][r], z["C_off"][r + 1]
        if b - a < 2:
            continue
        act = z["L"][z["L_off"][r] + z["chosen"][r]]
        hit = np.flatnonzero((z["C_vec"][a:b] == act).all(1))
        if len(hit):
            m = z["C_mean"][a:b].astype(np.float64)
            out[r] = m[hit[0]] - m.mean()
    return out


def search_targets(z, tau: float) -> np.ndarray:
    """``(N, K)`` card targets: a softmax over the searched candidates of (mean - max)/tau, each
    candidate's card multiset normalised; the attempted action where no candidate values exist."""
    out = z["tgt"].copy()
    has = np.zeros(len(out), bool)
    for r in range(len(out)):
        a, b = z["C_off"][r], z["C_off"][r + 1]
        if b - a < 2:
            continue
        m = z["C_mean"][a:b].astype(np.float64)
        p = np.exp((m - m.max()) / tau)
        p /= p.sum()
        c = z["C_vec"][a:b].astype(np.float64)
        t = (p[:, None] * c / c.sum(1, keepdims=True)).sum(0)
        out[r] = t
        has[r] = True
    return out, has


def train_arm(arm, ztr, A, tgt, head0, *, epochs, batch, lr, seed, threads):
    import copy as _copy
    import torch
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    head = _copy.deepcopy(head0)
    opt = torch.optim.AdamW(head.parameters(), lr=lr, weight_decay=0.01)
    n = len(A)
    total = epochs * math.ceil(n / batch)
    F, slot = torch.from_numpy(ztr["F"]), torch.from_numpy(ztr["slot"].astype(np.int64))
    T, At = torch.from_numpy(tgt), torch.from_numpy(A.astype(np.float32))
    step, ws = 0, []
    rng = np.random.default_rng(seed)
    for ep in range(epochs):
        order = rng.permutation(n)
        for i in range(0, n, batch):
            idx = torch.from_numpy(np.sort(order[i:i + batch]))
            for g in opt.param_groups:
                g["lr"] = lr * 0.5 * (1 + math.cos(math.pi * step / total))
            w = weights_for(arm, At[idx], True)
            lg = head_logits(head, F[idx], slot[idx])
            loss = (w * row_ce(lg, T[idx])).mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0)
            opt.step()
            step += 1
            if ep == 0:
                ws.append(w.detach().numpy())
    w = np.concatenate(ws)
    stats = {"wt_mean": float(w.mean()), "wt_max": float(w.max()), "ess": float(w.sum() ** 2 / (w ** 2).sum() / len(w))}
    return head, stats


def evaluate(head, z, rows, exact):
    import torch
    with torch.no_grad():
        lg = head_logits(head, torch.from_numpy(z["F"][rows]), torch.from_numpy(z["slot"][rows].astype(np.int64)))
        ce = float(row_ce(lg, torch.from_numpy(z["tgt"][rows])).mean())
        lg = lg.numpy()
    nl = np.diff(z["L_off"])
    hits, hits_all, top1, n8, nall = 0, 0, 0, 0, 0
    reg, regs = [], []
    ex_rows = dict(zip(exact["rows"].tolist(), range(len(exact["rows"])))) if exact is not None else {}
    ex_off = np.cumsum([0] + [int(nl[r]) for r in exact["rows"]]) if exact is not None else None
    for j, r in enumerate(rows):
        if not z["complete"][r] or nl[r] < 2:
            continue
        L = z["L"][z["L_off"][r]:z["L_off"][r + 1]].astype(np.float32)
        lo = np.where(z["slot"][r] >= 0, lg[j], 0.0)
        sc = L @ lo
        rank = np.argsort(-sc, kind="stable")
        c = int(z["chosen"][r])
        inn = c in rank[:8]
        hits_all += inn
        nall += 1
        top1 += rank[0] == c
        if nl[r] > 8:
            hits += inn
            n8 += 1
        if r in ex_rows:
            k = ex_rows[r]
            s = exact["scores"][ex_off[k]:ex_off[k + 1]]
            reg.append(float(s.max() - s[rank[0]]))
            regs.append(float(s.max() - s[c]))
    return {"recall8": hits / max(n8, 1), "n8": n8, "recall8_all": hits_all / max(nall, 1), "top1": top1 / max(nall, 1),
            "regret": float(np.mean(reg)) if reg else float("nan"), "n_regret": len(reg),
            "regret_search": float(np.mean(regs)) if regs else float("nan"), "ce": ce}


def load_all(cache):
    ztr = dict(np.load(Path(cache) / "train.npz"))
    zho = dict(np.load(Path(cache) / "heldout.npz"))
    ex = Path(cache) / "exact.npz"
    exact = dict(np.load(ex)) if ex.exists() else None
    return ztr, zho, exact


ARMS_BETA = [0.25, 0.5, 1.0, 2.0, 4.0]


def run_arm(name, arm, ztr, zho, rows, exact, head0, args, ridge, cache_A):
    key = (arm.get("baseline", "v"), arm.get("lam", 1.0))
    if key not in cache_A:
        cache_A[key] = advantages(ztr, key[0], key[1], ridge)
    A = cache_A[key]
    a = dict(arm)
    if a.get("beta_mult") is not None:
        a["beta"] = a["beta_mult"] * float(A.std())
    tgt = ztr["tgt"]
    if a.get("tau") is not None:
        tgt = args._search_tgt[a["tau"]]
    t0 = time.time()
    head, st = train_arm(a, ztr, A, tgt, head0, epochs=args.epochs, batch=args.batch, lr=args.lr, seed=args.seed,
                         threads=args.threads)
    ev = evaluate(head, zho, rows, exact)
    res = {"arm": name, **{k: v for k, v in a.items()}, "A_std": float(A.std()), "A_var": float(A.var()), **st, **ev,
           "seconds": round(time.time() - t0, 1)}
    print(json.dumps(res), flush=True)
    return res, head


def cmd_sweep(args) -> int:
    import torch
    ztr, zho, exact = load_all(args.cache)
    split = split_of(zho)
    val = np.flatnonzero(split == "val")
    test = np.flatnonzero(split == "test")
    head0 = build_head(args.ckpt)
    ridge = fit_ridge(ztr)
    print(f"[sweep] train {len(ztr['V'])} rows, val {len(val)}, test {len(test)}, ridge r2 {ridge.r2:.4f}; "
          f"exact rows {0 if exact is None else len(exact['rows'])}", flush=True)
    args._search_tgt = {}
    cache_A: dict = {}
    results = []
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "sweep.jsonl", "a")

    def go(name, arm, rows=val):
        res, head = run_arm(name, arm, ztr, zho, rows, exact, head0, args, ridge, cache_A)
        res["split"] = "val" if rows is val else "test"
        results.append(res)
        log.write(json.dumps(res) + "\n")
        log.flush()
        return res, head

    # the served head as is, and the unweighted control
    base = evaluate(head0, zho, val, exact)
    log.write(json.dumps({"arm": "served", "split": "val", **base}) + "\n")
    print(json.dumps({"arm": "served", **base}), flush=True)
    ctrl, _ = go("control", {"beta": None})

    def score(r):
        """Selection on val: recall@8 gain plus relative regret cut, both vs the control."""
        dr = r["recall8"] - ctrl["recall8"]
        rr = (ctrl["regret"] - r["regret"]) / max(ctrl["regret"], 1e-9)
        return dr * 100 + rr * 20
    knobs = args.knobs.split(",")
    best = {"beta_mult": 1.0, "cap": 20.0, "baseline": "v", "lam": 1.0, "shape": "exp"}
    if "beta" in knobs:
        rs = [go(f"beta{m}", dict(best, beta_mult=m))[0] for m in ARMS_BETA]
        best["beta_mult"] = max(rs, key=score)["beta_mult"]
    if "gae" in knobs:
        rs = [go(f"lam{l}", dict(best, lam=l))[0] for l in (0.0, 0.5, 0.8, 0.95)]
        rs.append(max([r for r in results if r.get("beta_mult") == best["beta_mult"] and r.get("lam", 1.0) == 1.0
                       and r.get("baseline", "v") == "v"], key=score))
        best["lam"] = max(rs, key=score)["lam"]
    if "cap" in knobs:
        rs = [go(f"cap{c}", dict(best, cap=c))[0] for c in (5.0, 100.0)]
        rs += [r for r in results if r.get("beta_mult") == best["beta_mult"] and r.get("lam") == best["lam"]
               and r.get("cap") == 20.0 and r.get("baseline") == "v" and r.get("shape") == "exp"]
        best["cap"] = max(rs, key=score)["cap"]
    if "baseline" in knobs:
        for b in ("hand", "none"):
            go(f"base-{b}", dict(best, baseline=b, lam=1.0))
    if "shape" in knobs:
        for s in ("rank", "pos"):
            go(f"shape-{s}", dict(best, shape=s))
    if "search" in knobs:
        for tau in (0.05, 0.15, 0.5):
            args._search_tgt[tau], has = search_targets(ztr, tau)
            go(f"search-tau{tau}", {"beta": None, "tau": tau, "search_rows": float(has.mean())})
        for m in (0.5, 1.0, 2.0):
            go(f"search-adv{m}", {"beta_mult": m, "cap": 20.0, "baseline": "search", "lam": 1.0, "shape": "exp"})
    cand = [r for r in results if r["arm"] != "control"]
    win = max(cand, key=score) if cand else None
    summary = {"best_chain": best, "winner": win and win["arm"], "ridge_r2": ridge.r2}
    if win is not None and args.final:
        arm = {k: win[k] for k in ("beta", "beta_mult", "cap", "baseline", "lam", "shape", "tau") if k in win}
        arm.pop("beta", None) if arm.get("beta_mult") is not None else None
        summary["test_control"] = go("control", {"beta": None}, rows=test)[0]
        summary["test_winner"] = go(win["arm"], arm, rows=test)[0]
        summary["test_served"] = evaluate(head0, zho, test, exact)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, default=str), flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cache")
    c.add_argument("--ckpt", required=True)
    c.add_argument("--ckpt-sha256", default=None)
    c.add_argument("--train-data", nargs="+", required=True)
    c.add_argument("--heldout-data", nargs="+", required=True)
    c.add_argument("--store-map", action="append", default=[])
    c.add_argument("--exclude-seed-window", action="append", default=[], help="LO:HI")
    c.add_argument("--train-rows", type=int, default=300_000)
    c.add_argument("--heldout-rows", type=int, default=50_000)
    c.add_argument("--seed", type=int, default=1)
    c.add_argument("--threads", type=int, default=4)
    c.add_argument("--out", required=True)
    e = sub.add_parser("exact")
    e.add_argument("--cache", required=True)
    e.add_argument("--per-split", type=int, default=400)
    e.add_argument("--max-nodes", type=int, default=2_000_000)
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--seed", type=int, default=1)
    s = sub.add_parser("sweep")
    s.add_argument("--cache", required=True)
    s.add_argument("--ckpt", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--knobs", default="beta,gae,cap,baseline,shape,search")
    s.add_argument("--epochs", type=int, default=2)
    s.add_argument("--batch", type=int, default=1024)
    s.add_argument("--lr", type=float, default=3e-4)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--threads", type=int, default=4)
    s.add_argument("--final", action="store_true")
    a = p.parse_args(argv)
    return {"cache": cmd_cache, "exact": cmd_exact, "sweep": cmd_sweep}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
