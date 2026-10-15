"""S17 step 1: offline fit of a small belief model against production's sampler.

Reads a ``belief_labels`` extract and reports, on held-out deals:

* **model** -- a factorized logistic (``--hidden 0``) or a 2-layer MLP emitting
  54 x 4 holder logits (next / partner / previous / kitty), masked to the
  feasible receivers, trained with per-copy cross-entropy, then one temperature
  fitted on the calibration split;
* **sampler** -- production's empirical per-copy marginals from M worlds per
  state (``belief_labels.sampler_counts``: release 45's refusal-aware branch),
  add-``alpha`` smoothed over the feasible receivers with ``alpha`` fitted on
  the calibration split (an unsmoothed empirical marginal can be 0 on the truth);
* **uniform** -- the analytic constraint-aware reference: each copy spread over
  the feasible receivers in proportion to the cards they hold;
* **permuted control** -- the same model and pipeline trained on labels permuted
  across rows within (trick, role) strata, in the training AND calibration
  splits, so it never sees a real (input, label) pair; evaluated on real labels.

The target is the genuinely UNKNOWN copies (``residualize``): a copy whose
holder is public -- a declared card still with the declarer, a failed-throw
pin, i.e. ``Memory.known``, which production's sampler already places exactly
-- is subtracted from the labels, the sampler counts and the receiver sizes
before any fit, smoothing or score, so no method can gain on a fact the sampler
already honours. A partly pinned duplicate code keeps its other copy. This
matches the step-2 / q-pin hidden layout.

Metrics per hidden copy: log-loss, true-holder mass (mean probability on the
true holder) and ECE over reliability bins of the per-(card, receiver)
probabilities.  Every table is split by phase (tricks 1-5, 6-15, 16+) and by
where the copy truly is:

* ``all`` -- every hidden copy;
* ``hands`` -- copies in another seat's hand, scored by the probability
  CONDITIONAL on not being in the kitty (p[seat] / sum over seats), so a model
  cannot gain here by shifting mass off the kitty;
* ``hands_raw`` -- the same copies scored by the raw p[seat];
* ``kitty`` -- copies in the kitty (non-banker actors only).

Stop rule (design note (c) step 1, judgement thresholds): STOP when the model's
log-loss gain over the sampler on ``hands`` is under 3%, or the permuted control
recovers more than half of that gain.  Deal-level bootstrap CIs are printed for
the gains.  Offline log-loss is a perf claim only; it authorizes nothing about
search strength.

CLI: ``python -m shengji.train.belief_eval run --data DIR``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .belief_labels import (FEATURE_BLOCKS, KITTY, N_RECV, PHASES, ROLES, FEATURE_DIM,
                            load_split, phase_of_trick)

N_CARDS = 54
EVAL_KEYS = ("X", "Y", "M", "sizes", "trick", "role", "deal", "S", "S_n", "n_refusals")
TRAIN_KEYS = ("X", "Y", "M", "sizes", "trick", "role", "deal")
EPS = 1e-12
STOP_GAIN = 0.03


class BeliefEvalError(ValueError):
    pass


# ------------------------------------------------------------------ probabilities

def masked_softmax(logits: np.ndarray, mask: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Softmax over receivers restricted to ``mask``; rows with no feasible
    receiver come out all-zero (they carry no hidden copy)."""
    z = np.where(mask, logits.astype(np.float64) / temperature, -np.inf)
    zmax = np.max(z, axis=-1, keepdims=True)
    zmax = np.where(np.isfinite(zmax), zmax, 0.0)
    e = np.where(mask, np.exp(z - zmax), 0.0)
    s = e.sum(axis=-1, keepdims=True)
    return np.where(s > 0, e / np.where(s > 0, s, 1.0), 0.0)


def sampler_probs(S: np.ndarray, S_n: np.ndarray, mask: np.ndarray, alpha: float) -> np.ndarray:
    """The sampler's per-copy empirical marginal, add-``alpha`` smoothed over the
    feasible receivers.  ``S[i, c, r]`` counts copies of ``c`` at ``r`` over
    ``S_n[i]`` worlds; dividing by the copy count gives a distribution per card."""
    S = S.astype(np.float64)
    m = mask.astype(np.float64)
    tot = S.sum(axis=-1, keepdims=True)                 # S_n * hidden copies of the card
    p = (S + alpha * m) / np.maximum(tot + alpha * m.sum(axis=-1, keepdims=True), EPS)
    return np.where(m > 0, p, 0.0)


def uniform_probs(sizes: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Analytic constraint-aware uniform: feasible receivers weighted by the
    number of cards they hold."""
    w = mask * np.maximum(sizes.astype(np.float64), 0.0)[:, None, :]
    s = w.sum(axis=-1, keepdims=True)
    fallback = mask / np.maximum(mask.sum(axis=-1, keepdims=True), 1)
    return np.where(s > 0, w / np.where(s > 0, s, 1.0), fallback)


# ------------------------------------------------------------------ public pins

def _block_slice(name: str) -> slice:
    at = 0
    for block, width in FEATURE_BLOCKS:
        if block == name:
            return slice(at, at + width)
        at += width
    raise BeliefEvalError(f"no feature block {name}")


def known_counts(X: np.ndarray) -> np.ndarray:
    """``(N, 54, 4)`` copies whose holder is PUBLIC: the ``Memory.known`` pins
    (declared cards still with the declarer, the failed-throw pins of
    `ai.refusal.pin_unplayed_attempt`) as the extract wrote them into the
    ``pinned_rel1..3`` input blocks.  Production's sampler places exactly these
    copies with these holders in every world; the kitty never holds a pin."""
    K = np.zeros((len(X), N_CARDS, N_RECV), np.int64)
    for rel in (1, 2, 3):
        block = np.asarray(X[:, _block_slice(f"pinned_rel{rel}")], np.float32)
        if np.any(block != np.round(block)) or np.any(block < 0):
            raise BeliefEvalError("pinned counts are not whole copies")
        K[:, :, rel - 1] = np.round(block).astype(np.int64)
    return K


def residualize(part: dict[str, np.ndarray]) -> dict[str, int]:
    """Restrict a split IN PLACE to the genuinely unknown copies: subtract the
    public known-holder counts from the labels, from the sampler's counts
    (``S_n`` copies per pin, one per world) and from the receivers' sizes; a
    code with no unknown copy left leaves the mask, and so does a receiver with
    no unknown slot left (all its cards are pinned). A partly pinned duplicate
    code keeps its other copy, with every receiver it could be with. Nothing is
    smoothed onto, or scored on, a known copy."""
    K = known_counts(part["X"])
    Y = part["Y"].astype(np.int64) - K
    if np.any(Y < 0):
        raise BeliefEvalError("a public pin is not in its holder's true hand")
    part["Y"] = Y.astype(np.uint8)
    residual = Y.sum(axis=-1)
    # residual capacity: the unknown slots each receiver has left once its pinned
    # copies are placed; a receiver with no unknown slot
    # cannot hold an unknown copy, so it leaves the mask for every card
    sizes = part["sizes"].astype(np.int64) - K.sum(axis=1)
    if np.any(sizes < 0):
        raise BeliefEvalError("a receiver holds more pinned copies than cards")
    part["sizes"] = sizes.astype(np.int16)
    part["M"] = part["M"] & (residual > 0)[..., None] & (sizes > 0)[:, None, :]
    if "S" in part:
        S = part["S"].astype(np.int64) - K * part["S_n"].astype(np.int64)[:, None, None]
        if np.any(S[part["S_n"] > 0] < 0):
            raise BeliefEvalError("the sampler did not place a pinned copy with its holder")
        part["S"] = np.maximum(S, 0).astype(np.uint16)
    return {"known_copies": int(K.sum()), "residual_copies": int(Y.sum())}


# ------------------------------------------------------------------ metrics

def copy_terms(P: np.ndarray, Y: np.ndarray) -> dict[str, np.ndarray]:
    """Per-row sums for every subset: copies, -log p, p on the truth."""
    Y = Y.astype(np.float64)
    logp = np.log(np.maximum(P, EPS))
    seats = P[..., :KITTY]
    cond = seats / np.maximum(seats.sum(axis=-1, keepdims=True), EPS)
    ys = Y[..., :KITTY]
    yk = Y[..., KITTY]
    return {
        "all_n": Y.sum(axis=(1, 2)),
        "all_ll": -(Y * logp).sum(axis=(1, 2)),
        "all_mass": (Y * P).sum(axis=(1, 2)),
        "hands_n": ys.sum(axis=(1, 2)),
        "hands_ll": -(ys * np.log(np.maximum(cond, EPS))).sum(axis=(1, 2)),
        "hands_mass": (ys * cond).sum(axis=(1, 2)),
        "hands_raw_ll": -(ys * logp[..., :KITTY]).sum(axis=(1, 2)),
        "hands_raw_mass": (ys * P[..., :KITTY]).sum(axis=(1, 2)),
        "kitty_n": yk.sum(axis=1),
        "kitty_ll": -(yk * logp[..., KITTY]).sum(axis=1),
        "kitty_mass": (yk * P[..., KITTY]).sum(axis=1),
    }


SUBSETS = (("all", "all_n", "all_ll", "all_mass"),
           ("hands", "hands_n", "hands_ll", "hands_mass"),
           ("hands_raw", "hands_n", "hands_raw_ll", "hands_raw_mass"),
           ("kitty", "kitty_n", "kitty_ll", "kitty_mass"))


def summarize(terms: Mapping[str, np.ndarray], rows: np.ndarray) -> dict[str, dict[str, float]]:
    out = {}
    for name, n_key, ll_key, mass_key in SUBSETS:
        n = float(terms[n_key][rows].sum())
        out[name] = {"copies": n,
                     "logloss": float(terms[ll_key][rows].sum()) / n if n else float("nan"),
                     "mass": float(terms[mass_key][rows].sum()) / n if n else float("nan")}
    return out


def reliability(P: np.ndarray, Y: np.ndarray, M: np.ndarray, bins: int = 10
                ) -> tuple[float, list[dict[str, float]]]:
    """ECE and the bin table over every (row, card, feasible receiver) with a
    hidden copy, weighted by the card's hidden copies."""
    n_c = Y.sum(axis=-1).astype(np.float64)              # copies per card
    sel = M & (n_c[..., None] > 0)
    p = P[sel]
    w = np.broadcast_to(n_c[..., None], P.shape)[sel]
    obs = (Y.astype(np.float64) / np.maximum(n_c, 1)[..., None])[sel]
    idx = np.minimum((p * bins).astype(int), bins - 1)
    table = []
    ece = 0.0
    total = w.sum()
    for b in range(bins):
        k = idx == b
        wb = w[k].sum()
        if wb <= 0:
            table.append({"bin": b, "weight": 0.0, "conf": float("nan"), "freq": float("nan")})
            continue
        conf = float((w[k] * p[k]).sum() / wb)
        freq = float((w[k] * obs[k]).sum() / wb)
        ece += wb / total * abs(conf - freq)
        table.append({"bin": b, "weight": float(wb / total), "conf": conf, "freq": freq})
    return float(ece), table


def fit_scalar(loss_of, lo: float, hi: float, *, log_space: bool = True, iters: int = 40) -> float:
    """Golden-section minimum of a unimodal 1-D loss on [lo, hi]."""
    f = (lambda t: loss_of(math.exp(t))) if log_space else loss_of
    a, b = (math.log(lo), math.log(hi)) if log_space else (lo, hi)
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    x = (a + b) / 2
    return math.exp(x) if log_space else x


def mean_ll(P: np.ndarray, Y: np.ndarray) -> float:
    t = copy_terms(P, Y)
    return float(t["all_ll"].sum() / t["all_n"].sum())


# ------------------------------------------------------------------ permutation control

def permute_within_strata(strata: np.ndarray, seed: int) -> np.ndarray:
    """An index permutation that maps each row to a random row of the same stratum."""
    rng = np.random.default_rng(seed)
    perm = np.arange(len(strata))
    order = np.argsort(strata, kind="stable")
    s_sorted = strata[order]
    bounds = np.flatnonzero(np.diff(s_sorted)) + 1
    for group in np.split(order, bounds):
        perm[group] = rng.permutation(group)
    return perm


def strata_of(trick: np.ndarray, role: np.ndarray) -> np.ndarray:
    return trick.astype(np.int64) * 8 + role.astype(np.int64)


# ------------------------------------------------------------------ model

def build_model(in_dim: int, hidden: int):
    import torch
    from torch import nn
    if hidden <= 0:
        return nn.Linear(in_dim, N_CARDS * N_RECV)
    return nn.Sequential(nn.Linear(in_dim, hidden), nn.ReLU(), nn.Linear(hidden, N_CARDS * N_RECV))


def n_params(model) -> int:
    return int(sum(p.numel() for p in model.parameters()))


def _batch_loss(model, xb, yb, mb):
    import torch
    logits = model(xb).view(-1, N_CARDS, N_RECV)
    logits = logits.masked_fill(~mb, -1e9)
    logp = torch.log_softmax(logits, dim=-1)
    return -(yb * logp).sum(), yb.sum()


def predict_logits(model, X: np.ndarray, batch: int = 8192) -> np.ndarray:
    import torch
    out = np.empty((len(X), N_CARDS, N_RECV), np.float32)
    model.eval()
    with torch.no_grad():
        for i in range(0, len(X), batch):
            xb = torch.from_numpy(np.asarray(X[i:i + batch], np.float32))
            out[i:i + batch] = model(xb).view(-1, N_CARDS, N_RECV).numpy()
    return out


def train_model(X: np.ndarray, Y: np.ndarray, M: np.ndarray, Xc: np.ndarray, Yc: np.ndarray,
                Mc: np.ndarray, *, hidden: int, epochs: int, lr: float, batch: int, seed: int,
                weight_decay: float = 0.0, patience: int = 2, log=print, label: str = "model"):
    """Adam on per-copy cross-entropy; keeps the epoch with the best calibration loss."""
    import torch
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = build_model(X.shape[1], hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    best, best_state, bad = float("inf"), None, 0
    history = []
    for epoch in range(epochs):
        model.train()
        t0 = time.time()
        order = rng.permutation(len(X))
        tot, cnt = 0.0, 0.0
        for i in range(0, len(order), batch):
            idx = np.sort(order[i:i + batch])
            xb = torch.from_numpy(np.asarray(X[idx], np.float32))
            yb = torch.from_numpy(np.asarray(Y[idx], np.float32))
            mb = torch.from_numpy(np.asarray(M[idx]))
            loss, n = _batch_loss(model, xb, yb, mb)
            opt.zero_grad()
            (loss / n.clamp_min(1.0)).backward()
            opt.step()
            tot += float(loss.detach())
            cnt += float(n)
        calib = mean_ll(masked_softmax(predict_logits(model, Xc), Mc), Yc)
        history.append({"epoch": epoch + 1, "train_ll": tot / cnt, "calib_ll": calib,
                        "seconds": time.time() - t0})
        log(f"[{label}] epoch {epoch + 1}: train {tot / cnt:.4f} calib {calib:.4f} "
            f"({time.time() - t0:.0f}s)", flush=True)
        if calib < best - 1e-5:
            best, bad = calib, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    model.load_state_dict(best_state)
    return model, history


# ------------------------------------------------------------------ bootstrap

def deal_bootstrap(deal: np.ndarray, num: Sequence[np.ndarray], den: np.ndarray, *,
                   reps: int = 1000, seed: int = 0) -> list[tuple[float, float]]:
    """95% deal-resampled CIs of ``1 - num_k / den`` (sums over resampled deals)."""
    uniq, inv = np.unique(deal, return_inverse=True)
    den_d = np.bincount(inv, weights=den, minlength=len(uniq))
    num_d = [np.bincount(inv, weights=n, minlength=len(uniq)) for n in num]
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(reps, len(uniq)))
    w = np.stack([np.bincount(d, minlength=len(uniq)) for d in draws]).astype(np.float64)
    den_b = w @ den_d
    out = []
    for n in num_d:
        g = 1.0 - (w @ n) / den_b
        out.append((float(np.quantile(g, 0.025)), float(np.quantile(g, 0.975))))
    return out


# ------------------------------------------------------------------ report

def _fmt(x: float, nd: int = 4) -> str:
    return "nan" if x != x else f"{x:.{nd}f}"


def _pct(x: float) -> str:
    return "nan" if x != x else f"{100 * x:+.2f}%"


def run(data: str, *, hidden: int, epochs: int, lr: float, batch: int, seed: int,
        threads: int, weight_decay: float, max_train_rows: int | None, log=print
        ) -> tuple[str, dict[str, Any]]:
    import torch
    torch.set_num_threads(threads)
    t_start = time.time()
    manifest = json.loads((Path(data) / "manifest.json").read_text())
    tr = load_split(data, "train", TRAIN_KEYS)
    if max_train_rows is not None and len(tr["X"]) > max_train_rows:
        # subsample by DEAL, never by row
        uniq = np.unique(tr["deal"])
        rng = np.random.default_rng(seed)
        keep_deals = rng.permutation(uniq)
        frac = max_train_rows / len(tr["X"])
        keep = np.isin(tr["deal"], keep_deals[:max(1, int(len(uniq) * frac))])
        tr = {k: v[keep] for k, v in tr.items()}
    ca = load_split(data, "calib", EVAL_KEYS)
    te = load_split(data, "test", EVAL_KEYS)
    if tr["X"].shape[1] != FEATURE_DIM:
        raise BeliefEvalError("extract feature width differs from this module's")
    for name, part in (("train", tr), ("calib", ca), ("test", te)):
        log(f"[data] {name}: {len(part['X'])} rows, {len(np.unique(part['deal']))} deals", flush=True)
    # every comparison is on rows where the sampler was drawn
    ca = {k: v[ca["S_n"] > 0] for k, v in ca.items()}
    te = {k: v[te["S_n"] > 0] for k, v in te.items()}
    # the target is the genuinely unknown copies: public pins come out of labels,
    # sampler counts and sizes alike, before any fit
    pins = {name: residualize(part) for name, part in (("train", tr), ("calib", ca), ("test", te))}
    for part in (tr, ca, te):
        if np.any((part["Y"] > 0) & ~part["M"]):
            raise BeliefEvalError("a true holder is outside the feasible mask")
    # deal-disjointness of the splits (the extract splits by deal_key)
    if (np.intersect1d(tr["deal"], te["deal"]).size or np.intersect1d(tr["deal"], ca["deal"]).size
            or np.intersect1d(ca["deal"], te["deal"]).size):
        raise BeliefEvalError("a deal appears in two splits")

    Yc = ca["Y"].astype(np.float32)
    Mc = ca["M"]
    # ---- the model
    model, hist = train_model(tr["X"], tr["Y"], tr["M"], ca["X"], Yc, Mc, hidden=hidden,
                              epochs=epochs, lr=lr, batch=batch, seed=seed,
                              weight_decay=weight_decay, log=log, label="model")
    lc = predict_logits(model, ca["X"])
    T = fit_scalar(lambda t: mean_ll(masked_softmax(lc, Mc, t), Yc), 0.25, 4.0)
    P_model = masked_softmax(predict_logits(model, te["X"]), te["M"], T)
    # ---- the permuted control: labels AND masks permuted within (trick, role) strata in
    # train and calib; it never sees a real (input, label) pair, then faces real test labels
    perm_tr = permute_within_strata(strata_of(tr["trick"], tr["role"]), seed + 1)
    perm_ca = permute_within_strata(strata_of(ca["trick"], ca["role"]), seed + 2)
    Yp, Mp = tr["Y"][perm_tr], tr["M"][perm_tr]
    Ycp, Mcp = Yc[perm_ca], Mc[perm_ca]
    control, hist_c = train_model(tr["X"], Yp, Mp, ca["X"], Ycp, Mcp, hidden=hidden,
                                  epochs=epochs, lr=lr, batch=batch, seed=seed,
                                  weight_decay=weight_decay, log=log, label="control")
    del Yp, Mp
    lcc = predict_logits(control, ca["X"])
    Tc = fit_scalar(lambda t: mean_ll(masked_softmax(lcc, Mcp, t), Ycp), 0.25, 4.0)
    P_control = masked_softmax(predict_logits(control, te["X"]), te["M"], Tc)
    # ---- baselines
    alpha = fit_scalar(lambda a: mean_ll(sampler_probs(ca["S"], ca["S_n"], Mc, a), Yc), 1e-3, 64.0)
    P_sampler = sampler_probs(te["S"], te["S_n"], te["M"], alpha)
    P_uniform = uniform_probs(te["sizes"], te["M"])
    methods = {"model": P_model, "sampler": P_sampler, "control": P_control, "uniform": P_uniform}
    Y = te["Y"]
    terms = {k: copy_terms(P, Y) for k, P in methods.items()}
    phase = np.asarray([phase_of_trick(int(t)) for t in te["trick"]])
    groups = [("overall", np.ones(len(Y), bool))] + [(name, phase == name) for name, _, _ in PHASES]
    roles = [(ROLES[i], te["role"] == i) for i in range(len(ROLES))]
    results: dict[str, Any] = {"pins": pins, "T_model": T, "T_control": Tc, "alpha_sampler": alpha,
                               "params": n_params(model), "hidden": hidden,
                               "history_model": hist, "history_control": hist_c, "tables": {}}
    for gname, rows in groups + roles:
        results["tables"][gname] = {k: summarize(terms[k], rows) for k in methods}
    ece = {k: reliability(P, Y, te["M"]) for k, P in methods.items()}
    results["ece"] = {k: v[0] for k, v in ece.items()}
    # deal bootstrap of the gains over the sampler
    boots = {}
    for subset, n_key, ll_key, _ in SUBSETS:
        ci = deal_bootstrap(te["deal"], [terms["model"][ll_key], terms["control"][ll_key]],
                            terms["sampler"][ll_key], seed=seed)
        boots[subset] = {"model": ci[0], "control": ci[1]}
    results["bootstrap"] = boots
    ov = results["tables"]["overall"]
    gain_m = 1 - ov["model"]["hands"]["logloss"] / ov["sampler"]["hands"]["logloss"]
    gain_c = 1 - ov["control"]["hands"]["logloss"] / ov["sampler"]["hands"]["logloss"]
    stop = (gain_m < STOP_GAIN) or (gain_c > 0.5 * gain_m)
    results["stop_rule"] = {"gain_model_hands": gain_m, "gain_control_hands": gain_c,
                            "threshold": STOP_GAIN, "control_ceiling": 0.5 * gain_m,
                            "control_improves": gain_c > 0, "verdict": "STOP" if stop else "PASS"}
    results["seconds"] = time.time() - t_start

    # ---- markdown
    L: list[str] = []
    L.append("# S17 step 1 DEV: belief model vs production sampler (offline, unknown copies only)\n")
    L.append("Generated by `python -m shengji.train.belief_eval run`; every number below is printed "
             "by the script. Tier-i DEV: perf claim only (offline log-loss), no strength claim.\n")
    st = manifest.get("stats", {})
    L.append("## Data\n")
    L.append(f"- stores: {', '.join(Path(s).name for s in manifest['stores'])}; cluster stride "
             f"{manifest['cluster_stride']} (one deal = one cluster = two mirrored rounds)")
    L.append(f"- deals: train {st.get('deals_train', 0)}, calib {st.get('deals_calib', 0)}, "
             f"test {st.get('deals_test', 0)}; split by salted deal_key hash "
             f"(calib {manifest['split']['calib']}, test {manifest['split']['test']}); "
             f"rows used: train {len(tr['X'])}, calib {len(ca['X'])}, test {len(te['X'])}")
    L.append(f"- excluded windows (registered non-trajectory seed windows): "
             f"{len(manifest['excluded_windows'])}; clusters excluded: "
             f"{len(manifest['excluded_clusters'])}; clusters that failed replay: "
             f"{len(manifest.get('failed_clusters', []))}")
    L.append(f"- sampler: {manifest['sampler']['worlds']} worlds/state on calib+test through "
             f"{manifest['sampler']['path']}; states {st.get('sampler_states', 0)}, refusal "
             f"rejections {st.get('refusal_rejections', 0)}, refusal fallback worlds "
             f"{st.get('refusal_fallback_worlds', 0)}; states with a refusal on the ledger "
             f"{st.get('refusal_states', 0)}")
    L.append(f"- model: {'MLP hidden ' + str(hidden) if hidden > 0 else 'factorized logistic'}, "
             f"{n_params(model)} params, input {FEATURE_DIM} columns (no world block); "
             f"epochs run {len(hist)} (best calib kept); T = {T:.3f}")
    L.append(f"- permuted control: same pipeline, labels+masks permuted within (trick, role) "
             f"strata in train and calib; epochs {len(hist_c)}; T = {Tc:.3f}")
    L.append("- target: the genuinely UNKNOWN copies only. Public known-holder copies (declared "
             "cards still with the declarer, failed-throw pins; `Memory.known`) are subtracted from "
             "labels, sampler counts and receiver sizes before training, smoothing and scoring: "
             + ", ".join(f"{k} {v['known_copies']} known / {v['residual_copies']} unknown copies"
                         for k, v in pins.items()))
    L.append(f"- sampler smoothing alpha (fitted on calib) = {alpha:.4f}; uniform = feasible "
             f"receivers weighted by cards held\n")
    sr = results["stop_rule"]
    L.append("## Stop rule (hands, kitty excluded; conditional on not-in-kitty)\n")
    L.append(f"- model gain over sampler: {_pct(sr['gain_model_hands'])} "
             f"(deal-bootstrap 95% CI {_pct(boots['hands']['model'][0])} .. "
             f"{_pct(boots['hands']['model'][1])}); threshold +3.00%")
    L.append(f"- permuted-control gain over sampler: {_pct(sr['gain_control_hands'])} "
             f"(CI {_pct(boots['hands']['control'][0])} .. {_pct(boots['hands']['control'][1])}); "
             f"ceiling half the model's gain = {_pct(sr['control_ceiling'])}")
    L.append(f"- **verdict: {sr['verdict']}**\n")
    for gname, _ in groups + roles:
        tab = results["tables"][gname]
        L.append(f"## {gname}\n")
        L.append("| subset | copies | model LL | sampler LL | control LL | uniform LL | model gain vs sampler "
                 "| control gain vs sampler | model mass | sampler mass | control mass | uniform mass |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for subset, *_ in SUBSETS:
            m, s, c, u = (tab[k][subset] for k in ("model", "sampler", "control", "uniform"))
            if not m["copies"]:
                continue
            L.append(f"| {subset} | {int(m['copies'])} | {_fmt(m['logloss'])} | {_fmt(s['logloss'])} | "
                     f"{_fmt(c['logloss'])} | {_fmt(u['logloss'])} | "
                     f"{_pct(1 - m['logloss'] / s['logloss'])} | {_pct(1 - c['logloss'] / s['logloss'])} | "
                     f"{_fmt(m['mass'])} | {_fmt(s['mass'])} | {_fmt(c['mass'])} | {_fmt(u['mass'])} |")
        L.append("")
    L.append("## Deal-bootstrap 95% CIs of the log-loss gain over the sampler (overall)\n")
    L.append("| subset | model | control |")
    L.append("|---|---|---|")
    for subset, *_ in SUBSETS:
        b = boots[subset]
        L.append(f"| {subset} | {_pct(b['model'][0])} .. {_pct(b['model'][1])} | "
                 f"{_pct(b['control'][0])} .. {_pct(b['control'][1])} |")
    L.append("")
    L.append("## Calibration (ECE over per-(card, receiver) probabilities, copy-weighted, 10 bins)\n")
    L.append("| method | ECE |")
    L.append("|---|---:|")
    for k in methods:
        L.append(f"| {k} | {_fmt(results['ece'][k])} |")
    L.append("")
    L.append("### Reliability bins (overall test)\n")
    L.append("| bin | " + " | ".join(f"{k} weight / conf / freq" for k in methods) + " |")
    L.append("|---|" + "---|" * len(methods))
    for b in range(10):
        cells = []
        for k in methods:
            row = ece[k][1][b]
            cells.append(f"{_fmt(row['weight'], 3)} / {_fmt(row['conf'], 3)} / {_fmt(row['freq'], 3)}")
        L.append(f"| {b / 10:.1f}-{(b + 1) / 10:.1f} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("## Training curves\n")
    L.append("| run | epoch | train LL | calib LL | seconds |")
    L.append("|---|---:|---:|---:|---:|")
    for label, h in (("model", hist), ("control", hist_c)):
        for e in h:
            L.append(f"| {label} | {e['epoch']} | {_fmt(e['train_ll'])} | {_fmt(e['calib_ll'])} | "
                     f"{e['seconds']:.0f} |")
    L.append(f"\nWall time {results['seconds']:.0f} s.")
    return "\n".join(L) + "\n", results


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="belief_eval", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="train, calibrate and compare on held-out deals")
    r.add_argument("--data", required=True)
    r.add_argument("--hidden", type=int, default=80, help="0 = factorized logistic")
    r.add_argument("--epochs", type=int, default=8)
    r.add_argument("--lr", type=float, default=1e-3)
    r.add_argument("--batch", type=int, default=1024)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--threads", type=int, default=2)
    r.add_argument("--weight-decay", type=float, default=0.0)
    r.add_argument("--max-train-rows", type=int, default=None)
    r.add_argument("--out-md", default=None)
    r.add_argument("--out-json", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    md, results = run(args.data, hidden=args.hidden, epochs=args.epochs, lr=args.lr,
                      batch=args.batch, seed=args.seed, threads=args.threads,
                      weight_decay=args.weight_decay, max_train_rows=args.max_train_rows)
    print(md)
    if args.out_md:
        Path(args.out_md).write_text(md)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(results, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
