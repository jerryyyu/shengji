"""AV1 step 0 reader: control-variate estimators of levels/round on paired seat-swapped duels.

Input: the per-row value cache from replay_values.py (one line per mirror: seed, mirror, ex_team, ex_levels,
u = [[seat, u_t], ...] in exploiter-team signed levels, feat = seven pre-treatment deal features).

Per deal d: x_d = (ex_levels m0 + ex_levels m1) / 2 (the duel's raw outcome).
Primary (PREDECLARE + AMENDMENT_AV1_1): C_m = sum over play decisions t >= 1 made by R52 seats (seat % 2 != ex_team) of
u_t - u_{t-1}; C = (C_0 + C_1) / 2; x'_d = x_d - beta * C_d, beta = OLS slope (with intercept) of x on C fitted on the
OTHER seed-parity half (cross-fit).  The control is NOT re-centred at its sample mean: the estimator is unbiased iff E[C] = 0
under the arms compared (exactly so under the null by seat symmetry; see AV1_RESULTS.md for the limit).
Secondary: x'_d = x_d - beta . (f_d - mu_pop), f = the seven pre-treatment deal features, mu_pop from pop_features.py
(200k simulated deals), cross-fit the same way.  Unbiased for any effect (f is fixed before any bot acts and mu is known).
Descriptive (not the bar): both sides (C_R52 and C_ex jointly), all increments (C_all = sum of every Delta).

Usage: av1_reader.py --pop POP.json NAME=U.jsonl [NAME=U.jsonl ...] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load_deals(path):
    by = {}
    for line in open(path):
        r = json.loads(line)
        by.setdefault(r["seed"], {})[r["mirror"]] = r
    deals = []
    for seed in sorted(by):
        m = by[seed]
        if set(m) != {0, 1}:
            raise SystemExit(f"{path}: seed {seed} lacks a mirror")
        deals.append((seed, m[0], m[1]))
    return deals


def increments(row):
    """(C_R52, C_ex, C_all) for one mirror: sums of u_t - u_{t-1}, t >= 1, by the acting seat's side."""
    u = row["u"]
    ex_team = row["ex_team"]
    c_r = c_e = 0.0
    for t in range(1, len(u)):
        d = u[t][1] - u[t - 1][1]
        if u[t][0] % 2 == ex_team:
            c_e += d
        else:
            c_r += d
    return c_r, c_e, c_r + c_e


def table(deals):
    seeds = np.array([s for s, _, _ in deals])
    x = np.array([(a["ex_levels"] + b["ex_levels"]) / 2 for _, a, b in deals], float)
    inc = np.array([[(p + q) / 2 for p, q in zip(increments(a), increments(b))] for _, a, b in deals], float)
    feat = np.array([a["feat"] for _, a, _ in deals], float)
    for _, a, b in deals:
        if a["feat"] != b["feat"]:
            raise SystemExit("mirror deal features differ: not the same deal")
    return seeds, x, inc, feat


def crossfit(x, Z, halves):
    """x - Z @ beta_(other half); Z is the (already centred, where a known mean exists) control matrix.
    beta from OLS with an intercept on the other half; the intercept is never subtracted."""
    adj = x.copy()
    betas = []
    for h in (0, 1):
        tr, te = halves != h, halves == h
        A = np.column_stack([np.ones(tr.sum()), Z[tr]])
        coef, *_ = np.linalg.lstsq(A, x[tr], rcond=None)
        beta = coef[1:]
        adj[te] = x[te] - Z[te] @ beta
        betas.append(beta.tolist())
    return adj, betas


def r2_insample(x, Z):
    A = np.column_stack([np.ones(len(x)), Z])
    coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    res = x - A @ coef
    return 1 - res.var() / x.var()


def summarize(x, adj, betas, Z, reps=2000, seed=1):
    n = len(x)
    se = x.std(ddof=1) / np.sqrt(n)
    se_a = adj.std(ddof=1) / np.sqrt(n)
    ratio = adj.var(ddof=1) / x.var(ddof=1)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(reps, n))
    br = adj[idx].var(1, ddof=1) / x[idx].var(1, ddof=1)
    return {"n": n, "raw_mean": x.mean(), "raw_se": se, "adj_mean": adj.mean(), "adj_se": se_a,
            "var_ratio": ratio, "var_ratio_ci95": np.percentile(br, [2.5, 97.5]).tolist(),
            "shift_se": (adj.mean() - x.mean()) / se, "beta_halves": betas, "r2_insample": r2_insample(x, Z)}


def analyse(path, pop):
    deals = load_deals(path)
    seeds, x, inc, feat = table(deals)
    halves = seeds % 2
    out = {}
    Z = inc[:, [0]]
    out["primary_value_cv_r52"] = summarize(x, *crossfit(x, Z, halves), Z)
    Zf = feat - np.asarray(pop["mean"])
    out["secondary_deal_covariates"] = summarize(x, *crossfit(x, Zf, halves), Zf)
    Zb = inc[:, [0, 1]]
    out["descr_both_sides"] = summarize(x, *crossfit(x, Zb, halves), Zb)
    Za = inc[:, [2]]
    out["descr_all_increments"] = summarize(x, *crossfit(x, Za, halves), Za)
    out["mean_C_r52"] = float(inc[:, 0].mean())
    out["se_C_r52"] = float(inc[:, 0].std(ddof=1) / np.sqrt(len(x)))
    out["frac_x_nonzero"] = float((x != 0).mean())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", required=True)
    ap.add_argument("--json")
    ap.add_argument("inputs", nargs="+")
    a = ap.parse_args(argv)
    pop = json.loads(Path(a.pop).read_text())
    res = {}
    for item in a.inputs:
        name, path = item.split("=", 1)
        res[name] = analyse(path, pop)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=float))
    hdr = f"{'duel':6} {'estimator':28} {'n':>5} {'raw':>8} {'rawSE':>7} {'adj':>8} {'adjSE':>7} {'ratio':>6} {'ratio95':>15} {'shiftSE':>7} {'R2in':>6}"
    print(hdr)
    for name, r in res.items():
        for k, s in r.items():
            if not isinstance(s, dict):
                continue
            print(f"{name:6} {k:28} {s['n']:5d} {s['raw_mean']:+8.4f} {s['raw_se']:7.4f} {s['adj_mean']:+8.4f} "
                  f"{s['adj_se']:7.4f} {s['var_ratio']:6.3f} [{s['var_ratio_ci95'][0]:.3f},{s['var_ratio_ci95'][1]:.3f}] "
                  f"{s['shift_se']:+7.3f} {s['r2_insample']:6.3f}  beta={s['beta_halves']}")
        print(f"{name:6} mean C_R52 {r['mean_C_r52']:+.4f} (se {r['se_C_r52']:.4f}); frac x!=0 {r['frac_x_nonzero']:.3f}")


if __name__ == "__main__":
    main()
