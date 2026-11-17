#!/usr/bin/env python3
"""PL1 single read: cross-fit (tau, alpha) per deal fold, resample 64, q_eff vs base, paired vs B1a, the bar.
usage: analyze.py [--model s136|ft1]... writes results/pl1_results.json (refuses to overwrite)."""
import glob, hashlib, json, sys
from pathlib import Path
import numpy as np

ROOT = Path(__import__("os").environ.get("PL1_ROOT", "/Users/jerryyu/.claude/jobs/d0498cda/tmp/pl1"))
PTS = "/Users/jerryyu/shengji-archive/2026-11-06-s113-belief-teacher-b1a/data/points.jsonl"
PTS_SHA = "d7236fc34938a9d600909bffaf45ca27fe523a3d068326921b291bdf73845f38"
M = 512
K = 64
TAUS = [0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
ALPHAS = [0.0, 0.05, 0.1, 0.25, 0.5]
ESS_MIN = 16.0
BAR_Q, KILL_Q = 0.27, 0.26


def fold(deal):
    return int(hashlib.sha256(f"pl1|fold|{deal}".encode()).hexdigest(), 16) % 2


def weights(ll, tau, alpha):
    fin = np.isfinite(ll)
    z = np.where(fin, tau * np.where(fin, ll, 0.0), -np.inf)
    p = np.where(fin, np.exp(z - z[fin].max()), 0.0)
    p /= p.sum()
    u = fin / fin.sum()                      # the uniform mixture over history-legal candidates
    return (1 - alpha) * p + alpha * u


def kish(w):
    return float(w.sum() ** 2 / (w ** 2).sum())


def load():
    assert hashlib.sha256(open(PTS, "rb").read()).hexdigest() == PTS_SHA
    rows = {}
    for f in glob.glob(str(ROOT / "phase1/main/part-*.jsonl")):
        for l in open(f):
            r = json.loads(l)
            rows[r["point_id"]] = r
    assert len(rows) == 2400
    pts = [r for r in rows.values() if r["hidden"] > 0]
    pts.sort(key=lambda r: r["point_id"])
    return pts


def per_point(pts, model):
    agree, ll = [], []
    for r in pts:
        z = np.load(ROOT / f"phase1/main/cands/{r['point_id']}.npz")
        agree.append(z["agree"][:M])
        a = np.load(ROOT / f"phase2/{model}/ll/{r['point_id']}.npy")
        assert a.shape == (M,) and not np.isnan(a).any() and np.isfinite(a).any()
        ll.append(a)
    return agree, ll


def tune(idx, agree, ll, base):
    """argmax pooled weighted q_eff over the grid on the points idx, subject to median Kish ESS >= 16."""
    best = None
    table = []
    for tau in TAUS:
        for alpha in ALPHAS:
            acc = np.array([float(weights(ll[i], tau, alpha) @ agree[i]) for i in idx])
            ess = np.median([kish(weights(ll[i], tau, alpha)) for i in idx])
            ab = base[idx].mean()
            q = (acc.mean() - ab) / (1 - ab)
            table.append({"tau": tau, "alpha": alpha, "q_weighted": q, "median_ess": ess})
            if ess >= ESS_MIN and (best is None or q > best[0] + 1e-12):
                best = (q, tau, alpha)
    return best, table


def boot(groups, cols, B=2000, seed=112):
    sums = {m: np.array([v[g].sum() for g in groups]) for m, v in cols.items()}
    cnt = np.array([len(g) for g in groups])
    def stat(ix):
        n = cnt[ix].sum()
        acc = {m: sums[m][ix].sum() / n for m in cols}
        return {m: (acc[m] - acc["base"]) / (1 - acc["base"]) for m in cols if m != "base"}, acc
    q0, acc0 = stat(np.arange(len(groups)))
    rng = np.random.default_rng(seed)
    bq = {m: [] for m in q0}
    bd = {m: [] for m in q0 if m != "b1a"}
    for _ in range(B):
        ix = rng.integers(0, len(groups), len(groups))
        q, _ = stat(ix)
        for m in q:
            bq[m].append(q[m])
        for m in bd:
            bd[m].append(q[m] - q["b1a"])
    ci = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return {"acc": {m: float(v) for m, v in acc0.items()},
            "q_eff": {m: {"est": float(q0[m]), "ci95": ci(bq[m])} for m in q0},
            "minus_b1a": {m: {"est": float(q0[m] - q0["b1a"]), "ci95": ci(bd[m])} for m in bd}}


def main():
    out_path = ROOT / "results/pl1_results.json"
    if out_path.exists():
        raise SystemExit("already read once")
    pts = load()
    deals = np.array([r["deal"] for r in pts])
    folds = np.array([fold(d) for d in deals])
    base = np.array([r["acc_base"] for r in pts])
    b1a = np.array([r["acc_b1a"] for r in pts])
    res = {"schema": "pl1-results-v1", "n_points": len(pts), "n_deals": int(len(np.unique(deals))), "M": M, "K": K,
           "grid": {"tau": TAUS, "alpha": ALPHAS}, "models": {}}
    cols = {"base": base, "b1a": b1a}
    ud = np.unique(deals)
    groups = [np.where(deals == d)[0] for d in ud]
    for model in [m for m in ("s136", "ft1") if (ROOT / f"phase2/{m}/ll").exists()]:
        agree, ll = per_point(pts, model)
        chosen, tables = {}, {}
        for f in (0, 1):
            best, table = tune(np.where(folds == f)[0], agree, ll, base)
            chosen[f] = best
            tables[f] = table
        acc_rs, acc_w, ess, distinct = np.zeros(len(pts)), np.zeros(len(pts)), np.zeros(len(pts)), np.zeros(len(pts))
        for i, r in enumerate(pts):
            best = chosen[1 - folds[i]]          # parameters tuned on the OTHER fold
            assert best is not None, "no grid cell met the ESS floor on a tuning fold"
            _, tau, alpha = best
            w = weights(ll[i], tau, alpha)
            rng = np.random.default_rng(int.from_bytes(hashlib.sha256(f"pl1|resample|{model}|{r['point_id']}".encode()).digest()[:8], "big"))
            pick = rng.choice(M, size=K, replace=True, p=w)
            acc_rs[i] = agree[i][pick].mean()
            acc_w[i] = float(w @ agree[i])
            ess[i] = kish(w)
            distinct[i] = len(set(pick.tolist()))
        # descriptive: S113's settings (tau 1, alpha 0), weighted, and the unweighted first-M candidates
        acc_t1 = np.array([float(weights(ll[i], 1.0, 0.0) @ agree[i]) for i in range(len(pts))])
        cols[f"{model}"] = acc_rs
        cols[f"{model}_weighted"] = acc_w
        cols[f"{model}_tau1_weighted"] = acc_t1
        cols["cands_unweighted"] = np.array([a.mean() for a in agree])
        res["models"][model] = {"chosen": {str(f): {"q_weighted_tune": chosen[f][0], "tau": chosen[f][1], "alpha": chosen[f][2]}
                                           for f in (0, 1)},
                                "tune_tables": {str(f): tables[f] for f in (0, 1)},
                                "ess": {"median": float(np.median(ess)), "p10": float(np.percentile(ess, 10)),
                                        "p25": float(np.percentile(ess, 25)), "frac_lt16": float((ess < 16).mean())},
                                "distinct_of_64_median": float(np.median(distinct)),
                                "ess_tau1_median": float(np.median([kish(weights(l, 1.0, 0.0)) for l in ll])),
                                "zero_frac_mean": float(np.mean([(~np.isfinite(l)).mean() for l in ll]))}
    res["main"] = boot(groups, cols)
    trick = np.array([r["trick"] for r in pts])
    kind = np.array([r["kind"] for r in pts])
    res["by_slice"] = {}
    for name, mask in {"early (0-7)": trick <= 7, "mid (8-16)": (trick >= 8) & (trick <= 16), "late (17+)": trick >= 17,
                       "lead": kind == "lead", "follow": kind == "follow"}.items():
        g = [np.intersect1d(x, np.where(mask)[0]) for x in groups]
        g = [x for x in g if len(x)]
        res["by_slice"][name] = boot(g, cols, B=1000)
    if "s136" in res["models"]:
        q = res["main"]["q_eff"]["s136"]["est"]
        lb = res["main"]["minus_b1a"]["s136"]["ci95"][0]
        med_ess = res["models"]["s136"]["ess"]["median"]
        bar = {"q_eff_ge_0.27": q >= BAR_Q, "median_ess_ge_16": med_ess >= ESS_MIN, "paired_lb_gt_0": lb > 0}
        verdict = "PASS" if all(bar.values()) else ("KILL" if q < KILL_Q else "FAIL")
        res["bar"] = bar
        res["verdict"] = verdict
    out_path.parent.mkdir(exist_ok=True)
    json.dump(res, open(out_path, "w"), indent=1, sort_keys=True)
    print(json.dumps({"verdict": res.get("verdict"), "bar": res.get("bar"), "q_eff": res["main"]["q_eff"],
                      "minus_b1a": res["main"]["minus_b1a"],
                      "chosen": {m: v["chosen"] for m, v in res["models"].items()},
                      "ess": {m: v["ess"] for m, v in res["models"].items()}}, indent=1))


if __name__ == "__main__":
    main()
