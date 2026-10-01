"""Offline prototype: action-aware reranker over the policy head's ballot (#676 cat. 2, #677 s3, board C7).

Baseline = the served factorised score: a candidate's score is the SUM of its cards' log-odds from a
frozen joint-package policy head (``policy_prior.score_candidates``).  Reranker = a small MLP over
(frozen trunk features of the root, candidate multi-hot + structure, baseline score) -> an additive
correction, trained with the trainer's own listwise loss against the search's soft targets
(``policy_prior.soft_ballot_targets``, T=1 on the stored points-scale values) on the ballot's own slots.

Arms (all on the same held-out rows, paired, deal-clustered bootstrap):
  A  reranker (root + cards + structure + baseline), all rows
  B  A trained on wrong-or-close rows only
  C  baseline + structure only (no root, no cards): does structure alone add signal?
  D  no baseline input, from scratch
  E  A at a second seed
  F  CONTROL: the baseline's own factorised form (per-card logits from the frozen trunk, summed over the
     candidate) re-fit on the same rows -- separates "adapted to these rows" from "action-aware"
  G  F with an MLP

Everything here is measured on the search's OWN ballots against the search's OWN values (offline
ranking); nothing is a served-strength number and no admission over the full legal set is simulated.
CPU only, one process; ~2 minutes for 200k training rows + 400k held-out rows.

    CUDA_VISIBLE_DEVICES= nice -n 19 python scripts/policy_reranker_proto.py \
        --checkpoint train-out/cwv/<run>/best.pt --rows <policy-rows chunk dir> \
        --train-chunks 0-3 --heldout-chunks 130-139 --out reranker.json
"""
from __future__ import annotations
import argparse, json, time, sys
from pathlib import Path
import numpy as np
import torch

N_CARDS = 54
TRICK0 = slice(270, 324)        # encode_obs: hand(54) + 4*played_by(54) + trick plane 0
TRUMP_SUIT = slice(486, 491)    # S H D C NT
TRUMP_RANK = slice(491, 504)
FEAT_NAMES = ["n_cards", "n_pairs", "tractor_len", "all_trump", "single_plain", "mixed_throw",
              "has_joker", "n_trump_rank", "n_distinct", "max_rank", "is_lead", "n_suits_plain"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------- candidate features

def ballot_counts(ball: np.ndarray) -> np.ndarray:
    """(n, B, 54) uint8 card multiplicity of every ballot slot."""
    n, B, C = ball.shape
    counts = np.zeros((n * B, N_CARDS), np.uint8)
    flat = ball.reshape(n * B, C).astype(np.int64)
    rows = np.repeat(np.arange(n * B), C)
    cards = flat.ravel()
    ok = cards >= 0
    np.add.at(counts, (rows[ok], cards[ok]), 1)
    return counts.reshape(n, B, N_CARDS)


def structure_features(counts: np.ndarray, X: np.ndarray) -> np.ndarray:
    """(n, B, len(FEAT_NAMES)) float32.  Counts are card MULTIPLICITIES (a Counter over the candidate's
    cards, ``ballot_counts``); every per-candidate total is taken over them, never over distinct cards.  Tractor length = longest run of ADJACENT-rank pairs in one
    suit (natural rank order, trump-rank gaps not bridged: an approximation of the engine's tractor)."""
    n, B, _ = counts.shape
    c = counts.astype(np.int16)
    n_cards = c.sum(2)
    pairs = (c >= 2)
    n_pairs = pairs.sum(2)
    present = c > 0
    n_distinct = present.sum(2)
    has_joker = present[:, :, 52:54].any(2)
    tsuit = X[:, TRUMP_SUIT].argmax(1)                      # 4 = NT
    tsuit = np.where(X[:, TRUMP_SUIT].max(1) > 0, tsuit, 4)
    trank = X[:, TRUMP_RANK].argmax(1)
    suit_of = np.minimum(np.arange(N_CARDS) // 13, 4)       # 0..3 plain, 4 jokers
    rank_of = np.where(np.arange(N_CARDS) < 52, np.arange(N_CARDS) % 13, 13)
    is_trump = (suit_of[None, :] == tsuit[:, None]) | (suit_of[None, :] == 4) | (rank_of[None, :] == trank[:, None])   # (n, 54)
    is_trump_b = np.broadcast_to(is_trump[:, None, :], present.shape)
    # MULTIPLICITY, not distinct cards: D3 D3 D4 D4 under trump D is four trump cards (a pair-run),
    # not two -- counting `present` here made every candidate with a trump pair a "mixed throw".
    n_trump = (c * is_trump_b).sum(2)
    n_trump_rank = (c * (rank_of[None, None, :] == trank[:, None, None])).sum(2)
    plain_suits = np.zeros((n, B, 4), bool)
    for s in range(4):
        plain_suits[:, :, s] = (present[:, :, s * 13:(s + 1) * 13] & ~is_trump_b[:, :, s * 13:(s + 1) * 13]).any(2)
    n_suits_plain = plain_suits.sum(2)
    all_trump = (n_trump == n_cards) & (n_cards > 0)
    single_plain = (n_trump == 0) & (n_suits_plain == 1)
    mixed = (n_cards > 0) & ~all_trump & ~single_plain
    # longest run of adjacent-rank pairs within a plain suit (jokers/trump-rank excluded)
    pr = pairs[:, :, :52].reshape(n, B, 4, 13)
    best = np.zeros((n, B), np.int16); run = np.zeros((n, B, 4), np.int16)
    for r in range(13):
        run = np.where(pr[:, :, :, r], run + 1, 0)
        best = np.maximum(best, run.max(2))
    tractor_len = np.where(best >= 2, best, 0)
    max_rank = np.where(present[:, :, :52].any(2),
                        (present[:, :, :52] * (np.arange(52) % 13)[None, None, :]).max(2), 0)
    is_lead = (X[:, TRICK0].max(1) <= 0)
    is_lead_b = np.broadcast_to(is_lead[:, None], (n, B))
    f = np.stack([n_cards, n_pairs, tractor_len, all_trump, single_plain, mixed, has_joker, n_trump_rank,
                  n_distinct, max_rank / 12.0, is_lead_b, n_suits_plain], axis=2).astype(np.float32)
    return f


def baseline_scores(lo: np.ndarray, counts: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """policy_prior.score_candidates on every ballot slot: sum of card log-odds with multiplicity."""
    s = np.einsum("nc,nbc->nb", lo.astype(np.float32), counts.astype(np.float32))
    return np.where(mask, s, -1e9).astype(np.float32)


# ----------------------------------------------------------------------------- data

def load_chunks(model, directory: Path, chunk_ids, max_rows=None, exclude_deals=frozenset()):
    """Score chunks with the frozen head; keep trunk features, log-odds, ballot arrays, strata."""
    from shengji.train.policy_rows import policy_log_odds
    out = {k: [] for k in ("feat", "lo", "counts", "mask", "vals", "tgt", "deal", "sf", "lead")}
    total = 0
    for ci in chunk_ids:
        z = np.load(directory / f"chunk-{ci:05d}.npz")
        keep = z["has_vals"] & (z["tgt"] >= 0)
        if exclude_deals:
            dk = z["deal_key"].astype(str)
            keep &= np.fromiter((k not in exclude_deals for k in dk), bool, len(dk))
        X = z["X"][keep].astype(np.float32); ball = z["ball"][keep]; mask = z["mask"][keep]
        vals = z["vals"][keep]; tgt = z["tgt"][keep]; deal = z["deal_key"][keep].astype(str)
        with torch.no_grad():
            feats, los = [], []
            for s in range(0, len(X), 4096):
                x = torch.from_numpy(X[s:s + 4096])
                f = model.features_flat(x)
                feats.append(f.numpy()); los.append(model.policy_logits(f).numpy())
        feat = np.concatenate(feats); lo = np.concatenate(los)
        counts = ballot_counts(ball)
        sf = structure_features(counts, X)
        lead = X[:, TRICK0].max(1) <= 0
        out["feat"].append(feat); out["lo"].append(lo); out["counts"].append(counts); out["mask"].append(mask)
        out["vals"].append(vals); out["tgt"].append(tgt); out["deal"].append(deal); out["sf"].append(sf); out["lead"].append(lead)
        total += len(X)
        log(f"  chunk {ci}: {len(X)} usable rows (has_vals & in-ballot), running {total}")
        if max_rows and total >= max_rows:
            break
    B = max(a.shape[1] for a in out["mask"])
    def pad2(a, fill):
        if a.shape[1] == B: return a
        o = np.full((a.shape[0], B) + a.shape[2:], fill, a.dtype); o[:, :a.shape[1]] = a; return o
    d = {"feat": np.concatenate(out["feat"]), "lo": np.concatenate(out["lo"]),
         "counts": np.concatenate([pad2(a, 0) for a in out["counts"]]),
         "mask": np.concatenate([pad2(a, False) for a in out["mask"]]),
         "vals": np.concatenate([pad2(a, np.nan) for a in out["vals"]]),
         "sf": np.concatenate([pad2(a, 0.0) for a in out["sf"]]),
         "tgt": np.concatenate(out["tgt"]), "deal": np.concatenate(out["deal"]), "lead": np.concatenate(out["lead"])}
    if max_rows:
        d = {k: v[:max_rows] for k, v in d.items()}
    d["base"] = baseline_scores(d["lo"], d["counts"], d["mask"])
    d["multi"] = ((d["counts"].sum(2) > 1) & d["mask"]).any(1)        # ballot contains a multi-card candidate
    return d


def exclude_deals_from(d: dict, deals: frozenset, label: str) -> tuple[dict, int]:
    """Drop every row of ``d`` whose deal is in ``deals`` (the training deals) and report the count: an
    extra held-out extract is NOT assumed disjoint from the training chunks."""
    keep = np.fromiter((k not in deals for k in d["deal"]), bool, len(d["deal"]))
    dropped = int((~keep).sum())
    if dropped:
        log(f"  {label}: dropped {dropped} rows on {len(set(d['deal'][~keep].tolist()))} training deals (overlap guard)")
    if not keep.any():
        raise ValueError(f"{label}: every row is on a training deal")
    return {k: (v[keep] if isinstance(v, np.ndarray) and v.shape[:1] == keep.shape else v) for k, v in d.items()}, dropped


# ----------------------------------------------------------------------------- metrics

def soft_targets_np(vals, mask, T=1.0):
    from shengji.train.policy_prior import soft_ballot_targets
    p, usable = soft_ballot_targets(torch.from_numpy(vals), torch.from_numpy(mask), T)
    return p.numpy(), usable.numpy()


def row_metrics(scores: np.ndarray, d: dict) -> dict[str, np.ndarray]:
    """Per-row: top1 hit (argmax of scores is one of the search's tied argmaxes), listwise CE vs the
    soft targets, regret in half-levels (values are half-level*40, #668 units)."""
    vals = d["vals"]; mask = d["mask"]
    finite = np.isfinite(vals) & mask
    v = np.where(finite, vals, -np.inf)
    best = v.max(1)
    pick = np.where(mask, scores, -1e9).argmax(1)
    pv = v[np.arange(len(v)), pick]
    top1 = np.isclose(pv, best, atol=1e-4) & np.isfinite(pv)
    regret = np.where(np.isfinite(pv), (best - pv) / 40.0, np.nan)
    tgt, _ = soft_targets_np(vals, mask)
    s = np.where(mask, scores, -1e9).astype(np.float64)
    s = s - s.max(1, keepdims=True)
    logp = s - np.log(np.exp(s).sum(1, keepdims=True))
    ce = -(tgt * logp).sum(1)
    return {"top1": top1.astype(np.float64), "ce": ce, "regret": regret}


def strata(d):
    lead, multi = d["lead"], d["multi"]
    return {"all": np.ones_like(lead), "lead-multi": lead & multi, "lead-single": lead & ~multi,
            "follow-multi": ~lead & multi, "follow-single": ~lead & ~multi}


def summarize(m: dict, st: dict) -> dict:
    return {name: {"n": int(sel.sum()), "top1": float(m["top1"][sel].mean()), "ce": float(m["ce"][sel].mean()),
                   "regret": float(np.nanmean(m["regret"][sel]))} for name, sel in st.items() if sel.sum()}


def paired_bootstrap(ma, mb, st, deals, n_boot=300, seed=0):
    """Deal-clustered bootstrap of the paired difference (b - a) in top1 and regret per stratum."""
    rng = np.random.default_rng(seed)
    udeals, inv = np.unique(deals, return_inverse=True)
    nd = len(udeals)
    out = {}
    d_top1 = mb["top1"] - ma["top1"]; d_reg = np.nan_to_num(mb["regret"] - ma["regret"]); d_ce = mb["ce"] - ma["ce"]
    for name, sel in st.items():
        if sel.sum() == 0: continue
        # per-deal sums of the differences and counts
        cnt = np.bincount(inv, weights=sel.astype(float), minlength=nd)
        s1 = np.bincount(inv, weights=d_top1 * sel, minlength=nd)
        s2 = np.bincount(inv, weights=d_reg * sel, minlength=nd)
        s3 = np.bincount(inv, weights=d_ce * sel, minlength=nd)
        res = []
        for _ in range(n_boot):
            w = rng.multinomial(nd, np.full(nd, 1.0 / nd)).astype(float)
            c = (w * cnt).sum()
            res.append(((w * s1).sum() / c, (w * s2).sum() / c, (w * s3).sum() / c))
        res = np.asarray(res)
        out[name] = {"d_top1": float(d_top1[sel].mean()), "d_top1_ci": [float(x) for x in np.percentile(res[:, 0], [2.5, 97.5])],
                     "d_regret": float(d_reg[sel].mean()), "d_regret_ci": [float(x) for x in np.percentile(res[:, 1], [2.5, 97.5])],
                     "d_ce": float(d_ce[sel].mean()), "d_ce_ci": [float(x) for x in np.percentile(res[:, 2], [2.5, 97.5])],
                     "deals": int((cnt > 0).sum())}
    return out


# ----------------------------------------------------------------------------- reranker

class Reranker(torch.nn.Module):
    def __init__(self, feat_dim: int, use_base: bool, hidden=(128, 64), use_root=True, use_cards=True):
        super().__init__()
        self.use_base = use_base; self.use_root = use_root; self.use_cards = use_cards
        din = (feat_dim if use_root else 0) + (N_CARDS if use_cards else 0) + len(FEAT_NAMES) + (2 if use_base else 0)
        layers = []
        for h in hidden:
            layers += [torch.nn.Linear(din, h), torch.nn.GELU()]; din = h
        layers.append(torch.nn.Linear(din, 1))
        self.net = torch.nn.Sequential(*layers)
        torch.nn.init.zeros_(self.net[-1].weight); torch.nn.init.zeros_(self.net[-1].bias)   # starts AT the baseline

    def forward(self, feat, counts, sf, base, mask):
        n, B = mask.shape
        parts = []
        if self.use_root: parts.append(feat.unsqueeze(1).expand(n, B, feat.shape[1]))
        if self.use_cards: parts.append(counts)
        parts.append(sf)
        if self.use_base:
            bm = torch.where(mask, base, torch.full_like(base, -1e9)).max(1, keepdim=True).values
            parts.append(torch.stack([base / 10.0, (base - bm) / 10.0], dim=2))
        x = torch.cat(parts, dim=2)
        corr = self.net(x).squeeze(2)
        s = base + corr if self.use_base else corr
        return torch.where(mask, s, torch.full_like(s, -1e9))


class Factorised(torch.nn.Module):
    """CONTROL: the baseline's own functional form re-fit on the same rows -- per-card logits from the
    frozen trunk features, candidate correction = sum of its cards' logits (with multiplicity), added to
    the baseline score.  Cannot represent pair/tractor interactions; isolates 'adapted to these rows'
    from 'action-aware'."""
    def __init__(self, feat_dim: int, hidden=()):
        super().__init__()
        layers = []; din = feat_dim
        for h in hidden:
            layers += [torch.nn.Linear(din, h), torch.nn.GELU()]; din = h
        layers.append(torch.nn.Linear(din, N_CARDS))
        self.net = torch.nn.Sequential(*layers)
        torch.nn.init.zeros_(self.net[-1].weight); torch.nn.init.zeros_(self.net[-1].bias)

    def forward(self, feat, counts, sf, base, mask):
        logits = self.net(feat)                                  # (n, 54)
        s = base + torch.einsum("nc,nbc->nb", logits, counts)
        return torch.where(mask, s, torch.full_like(s, -1e9))


def tensors(d, idx):
    return (torch.from_numpy(d["feat"][idx]), torch.from_numpy(d["counts"][idx].astype(np.float32)),
            torch.from_numpy(d["sf"][idx]), torch.from_numpy(d["base"][idx]), torch.from_numpy(d["mask"][idx]),
            torch.from_numpy(d["vals"][idx]), torch.from_numpy(d["tgt"][idx]))


def listwise_soft_on_scores(scores, mask, tgt, vals):
    from shengji.train.policy_prior import soft_ballot_targets
    soft, usable = soft_ballot_targets(vals, mask, 1.0)
    hard = torch.zeros_like(soft); hard[torch.arange(len(tgt)), tgt] = 1.0
    target = torch.where(usable.unsqueeze(1), soft, hard)
    return -(target * torch.log_softmax(scores, dim=1)).sum(1).mean()


def train_reranker(d, train_idx, *, use_base=True, epochs, lr, batch, seed, use_root=True, use_cards=True, factorised=None, log_every=200):
    torch.manual_seed(seed)
    if factorised is not None:
        m = Factorised(d["feat"].shape[1], hidden=factorised)
    else:
        m = Reranker(d["feat"].shape[1], use_base, use_root=use_root, use_cards=use_cards)
    opt = torch.optim.Adam(m.parameters(), lr=lr, weight_decay=1e-5)
    rng = np.random.default_rng(seed)
    for ep in range(epochs):
        perm = rng.permutation(train_idx); tot = 0.0; nb = 0
        m.train()
        for s in range(0, len(perm), batch):
            idx = np.sort(perm[s:s + batch])
            feat, counts, sf, base, mask, vals, tgt = tensors(d, idx)
            scores = m(feat, counts, sf, base, mask)
            loss = listwise_soft_on_scores(scores, mask, tgt, vals)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item(); nb += 1
        log(f"    epoch {ep + 1}/{epochs} listwise CE {tot / max(nb, 1):.4f}")
    m.eval()
    return m


def predict(m, d, batch=8192):
    out = []
    with torch.no_grad():
        for s in range(0, len(d["tgt"]), batch):
            idx = np.arange(s, min(s + batch, len(d["tgt"])))
            feat, counts, sf, base, mask, vals, tgt = tensors(d, idx)
            out.append(m(feat, counts, sf, base, mask).numpy())
    return np.concatenate(out)


# ----------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--rows", required=True, help="chunked policy-rows directory")
    ap.add_argument("--train-chunks", default="0-3")
    ap.add_argument("--heldout-chunks", default="134-139")
    ap.add_argument("--max-train-rows", type=int, default=200000)
    ap.add_argument("--max-heldout-rows", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--close-margin", type=float, default=1.0, help="nats: baseline top-2 gap below which a row is 'close'")
    ap.add_argument("--boot", type=int, default=300)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--extra-heldout", action="append", default=[], help="NAME=DIR:lo-hi second held-out extract")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    torch.set_num_threads(a.threads)
    from shengji.train.train_cwv import load_cwv_checkpoint
    rows = Path(a.rows)
    rng_chunks = lambda s: list(range(int(s.split("-")[0]), int(s.split("-")[1]) + 1))
    t0 = time.time()
    model, meta, _ = load_cwv_checkpoint(a.checkpoint, "cpu")
    log("checkpoint loaded", a.checkpoint)
    log("held-out chunks", a.heldout_chunks)
    H = load_chunks(model, rows, rng_chunks(a.heldout_chunks), a.max_heldout_rows or None)
    held_deals = frozenset(H["deal"].tolist())
    log("train chunks", a.train_chunks, "(rows on held-out deals excluded)")
    Tr = load_chunks(model, rows, rng_chunks(a.train_chunks), a.max_train_rows, exclude_deals=held_deals)
    log(f"rows: train {len(Tr['tgt'])} held-out {len(H['tgt'])} ({len(held_deals)} deals); scoring took {time.time() - t0:.0f}s")

    # baseline on held-out
    st = strata(H)
    base_m = row_metrics(H["base"], H)
    report = {"checkpoint": a.checkpoint, "rows": str(rows), "train_chunks": a.train_chunks, "heldout_chunks": a.heldout_chunks,
              "n_train": int(len(Tr["tgt"])), "n_heldout": int(len(H["tgt"])), "heldout_deals": len(held_deals),
              "strata_n": {k: int(v.sum()) for k, v in st.items()},
              "baseline": summarize(base_m, st), "arms": {}}
    log("baseline", json.dumps(report["baseline"]))

    # training subsets: all rows vs wrong-or-close
    bt = row_metrics(Tr["base"], Tr)
    sb = np.sort(np.where(Tr["mask"], Tr["base"], -1e9), axis=1)
    gap = sb[:, -1] - sb[:, -2]
    wrong_or_close = (bt["top1"] < 1) | (gap < a.close_margin)
    report["train_wrong_or_close_frac"] = float(wrong_or_close.mean())
    report["train_baseline_top1"] = float(bt["top1"].mean())
    log(f"train rows: baseline top1 {bt['top1'].mean():.4f}, wrong-or-close {wrong_or_close.mean():.3f}")

    extras = {}
    train_deals = frozenset(Tr["deal"].tolist())
    for spec in a.extra_heldout:
        name, rest = spec.split("=", 1); dpath, rng_ = rest.rsplit(":", 1)
        extras[name], dropped = exclude_deals_from(load_chunks(model, Path(dpath), rng_chunks(rng_), None), train_deals, name)
        report.setdefault("extra_overlap_rows_dropped", {})[name] = dropped
        extras[name]["_metrics_base"] = row_metrics(extras[name]["base"], extras[name])
        report.setdefault("extra_baseline", {})[name] = summarize(extras[name]["_metrics_base"], strata(extras[name]))

    all_idx = np.arange(len(Tr["tgt"]))
    arms = [("A rerank+base (root+cards+structure) / all rows", dict(use_base=True), all_idx),
            ("B rerank+base / wrong-or-close rows", dict(use_base=True), np.flatnonzero(wrong_or_close)),
            ("C base+structure only (no root, no cards) / all", dict(use_base=True, use_root=False, use_cards=False), all_idx),
            ("D no-baseline input (root+cards+structure, from scratch) / all", dict(use_base=False), all_idx),
            ("E = A, seed 2", dict(use_base=True), all_idx),
            ("F CONTROL factorised linear refit (base + counts.(W feat)) / all", dict(factorised=()), all_idx),
            ("G CONTROL factorised MLP refit (base + counts.MLP(feat)) / all", dict(factorised=(128, 64)), all_idx),
            ]
    arm_metrics: dict[str, dict] = {}
    for name, kw, idx in arms:
        t1 = time.time()
        log(f"arm {name}: training on {len(idx)} rows")
        seed = 2 if name.startswith("E") else 1
        m = train_reranker(Tr, idx, epochs=a.epochs, lr=a.lr, batch=a.batch, seed=seed, **kw)
        sc = predict(m, H)
        mm = row_metrics(sc, H)
        arm = {"train_rows": int(len(idx)), "train_secs": round(time.time() - t1, 1), "params": sum(p.numel() for p in m.parameters()),
               "metrics": summarize(mm, st), "paired_vs_baseline": paired_bootstrap(base_m, mm, st, H["deal"], a.boot)}
        for ename, E in extras.items():
            em = row_metrics(predict(m, E), E)
            arm.setdefault("extra", {})[ename] = {"metrics": summarize(em, strata(E)),
                                                  "paired_vs_baseline": paired_bootstrap(E["_metrics_base"], em, strata(E), E["deal"], a.boot)}
        report["arms"][name] = arm
        arm_metrics[name[0]] = mm
        log(f"arm {name} done in {time.time() - t1:.0f}s:", json.dumps({k: (round(v['top1'], 4), round(v['regret'], 4)) for k, v in arm["metrics"].items()}),
            "paired", json.dumps({k: (round(v["d_top1"], 4), [round(x, 4) for x in v["d_top1_ci"]]) for k, v in arm["paired_vs_baseline"].items()}))
    # pairwise: the action-aware arms against the factorised controls (same rows, same trunk)
    report["pairwise"] = {}
    for a_, b_ in (("A", "F"), ("E", "F"), ("B", "F"), ("A", "G"), ("D", "F"), ("A", "E")):
        if a_ in arm_metrics and b_ in arm_metrics:
            report["pairwise"][f"{a_} minus {b_}"] = paired_bootstrap(arm_metrics[b_], arm_metrics[a_], st, H["deal"], a.boot)
            log(f"pairwise {a_}-{b_}", json.dumps({k: (round(v["d_top1"], 4), [round(x, 4) for x in v["d_top1_ci"]]) for k, v in report["pairwise"][f"{a_} minus {b_}"].items()}))
    # serving cost: multiply-accumulates per candidate for the reranker vs one trunk call
    feat_dim = H["feat"].shape[1]
    din = feat_dim + N_CARDS + len(FEAT_NAMES) + 2
    rer_mac = din * 128 + 128 * 64 + 64
    trunk_mac = sum(p.numel() for n_, p in model.named_parameters() if n_.startswith("trunk") and p.dim() == 2)
    head_mac = feat_dim * N_CARDS
    report["cost"] = {"reranker_mac_per_candidate": rer_mac, "trunk_mac_per_root": trunk_mac, "policy_head_mac_per_root": head_mac,
                      "rerank_top32_mac": 32 * rer_mac, "rerank_4000_mac": 4000 * rer_mac}
    log("cost", json.dumps(report["cost"]))
    report["wall_secs"] = round(time.time() - t0, 1)
    Path(a.out).write_text(json.dumps(report, indent=1))
    log("wrote", a.out, f"wall {report['wall_secs']}s")


if __name__ == "__main__":
    main()
