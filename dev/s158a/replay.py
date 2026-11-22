"""S158A offline replay of exact-follow approximation rules on captured rows (no re-solving).

usage:
  replay.py tune  DIR SEED_LO SEED_HI OUT_JSON           # every rule on the tune half; picks the rule
  replay.py read  DIR SEED_LO SEED_HI RULE_JSON OUT_JSON  # one frozen rule (plus references) on the read half

A rule: deadline D (stage CPU seconds), Wmin (0 = all-or-nothing as served today), racing z (None = off;
from world 8, every 4 worlds, drop candidates more than z paired SEs behind the leader; the baseline is
never dropped), prune p (drop the bottom round(p*n) candidates by served value mean before the stage; the
baseline is never dropped), world cap c (a world whose alive-candidate CPU exceeds c seconds is charged c
and left out of the mean). Worlds run in draw order, every alive candidate per world. A deadline trip
mid-world discards that world; with at least Wmin complete worlds the prefix mean is published, else the
stage is abandoned to the served pick. Pick: max mean over alive candidates, ties to the lower index, and
the baseline (served pick) unless strictly beaten -- as `rerank_follow`.

Costs are the recorded per-cell CPU in the full shared-table session: a dropped candidate's later cells
cost 0 and the survivors keep their recorded cost (an approximation: the dropped candidates' solves had
warmed the survivors' table, so a live arm can cost more; stage B measures it).
PI: true-deal exact points of each admitted candidate; side points = points (attacker) or -points.
loss vs full = side(full-exact pick) - side(rule pick); regret vs served = side(served) - side(rule)
(negative = rule better). Bootstrap by deal, 10,000 resamples, seed 1.
"""
import glob, itertools, json, math, os, random, sys

D_DEFAULT = 1.95
GRID = dict(Wmin=[0, 8, 12, 16, 24], z=[None, 1.5, 2.0, 2.5], prune=[0.0, 0.2, 0.3, 0.4], cap=[None, 0.1, 0.25])


def load(d, lo, hi):
    rows, deals = [], 0
    for s in range(lo, hi):
        f = os.path.join(d, f"{s}.json")
        if not os.path.exists(f):
            continue
        deals += 1
        for r in json.load(open(f))["decisions"]:
            if r.get("n_adm", 0) > 1:
                rows.append(r)
    return rows, deals


def pick(means, alive, base):
    w = max(alive, key=lambda i: (means[i], -i))
    return base if means[w] <= means[base] else w


def prefix_means(L, worlds, n):
    k = len(worlds)
    return [sum(L[w][i] for w in worlds) / k for i in range(n)] if k else [0.0] * n


def full_ref(r):
    """Full 64-world exact pick, or None when the capture was censored, node-capped or PI is missing."""
    if r.get("capture_error") or r.get("censored") or r.get("nodecap") or r.get("pi_censored"):
        return None
    if r["worlds_done"] != r["n_worlds"] or len(r["pi"]) != r["n_adm"]:
        return None
    n = r["n_adm"]
    return pick(prefix_means(r["L"], range(r["worlds_done"]), n), list(range(n)), r["served_idx"])


def pruned_set(r, p):
    n, base = r["n_adm"], r["served_idx"]
    k = int(round(p * n))
    if k == 0:
        return set()
    vm = r["value_means"]
    order = sorted((i for i in range(n) if i != base), key=lambda i: (vm[i], -i))   # worst first
    return set(order[:min(k, n - 1)])


def sim(r, D, Wmin, z, prune, cap):
    """(pick, abandoned, stage_cpu_s) of one rule on one captured decision; pick None if undetermined
    (the capture stopped before the rule would)."""
    n, base, L, T = r["n_adm"], r["served_idx"], r["L"], r["T"]
    alive = [i for i in range(n) if i not in pruned_set(r, prune)]
    t, done, tripped = 0.0, [], False
    W = r["n_worlds"]
    for w in range(W):
        if w >= len(L):
            return None, None, None            # capture censored before this rule finished
        if any(L[w][i] is None for i in alive):
            return None, None, None            # node-capped cell
        cost = sum(T[w][i] for i in alive) / 1e6
        if cap is not None and cost > cap:
            if t + cap > D:
                tripped = True; break
            t += cap; continue
        if t + cost > D:
            tripped = True; break
        t += cost; done.append(w)
        k = len(done)
        if z is not None and k >= 8 and (k - 8) % 4 == 0 and len(alive) > 1:
            m = prefix_means(L, done, n)
            lead = max(alive, key=lambda i: (m[i], -i)); keep = []
            for i in alive:
                d = [L[x][lead] - L[x][i] for x in done]; mu = sum(d) / k
                se = math.sqrt(sum((v - mu) ** 2 for v in d) / (k - 1) / k)
                if i == lead or i == base or mu == 0 or mu <= z * se:
                    keep.append(i)
            alive = keep
    if tripped:
        if Wmin == 0 or len(done) < Wmin:
            return base, True, D
        t = D
    if not done:
        return base, True, t
    return pick(prefix_means(L, done, n), alive, base), False, t


def side(r, i):
    p = r["pi"][i]
    return p if r["attacker"] else -p


def boot(vals_by_deal, reps=10_000, seed=1):
    keys = list(vals_by_deal)
    rng = random.Random(seed)
    tot = sum(sum(v) for v in vals_by_deal.values()); cnt = sum(len(v) for v in vals_by_deal.values())
    if not cnt:
        return None, None, None
    sums = [(sum(vals_by_deal[k]), len(vals_by_deal[k])) for k in keys]
    means = []
    for _ in range(reps):
        s = c = 0
        for _ in keys:
            a, b = sums[rng.randrange(len(keys))]; s += a; c += b
        means.append(s / c if c else 0.0)
    means.sort()
    return tot / cnt, means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def evaluate(rows, rule, with_ci=False):
    D = rule.get("D", D_DEFAULT)
    ab = n = 0; times = []; loss = {}; reg = {}; best_pruned = 0; nref = 0; undetermined = 0; cpu_ratio = []
    for r in rows:
        if r.get("capture_error"):
            continue
        pk, abd, t = sim(r, D, rule["Wmin"], rule["z"], rule["prune"], rule["cap"])
        ref = full_ref(r)
        if pk is None:
            undetermined += 1; continue
        n += 1; ab += bool(abd); times.append(t)
        if r.get("stage_cpu") and not r.get("censored"):
            cpu_ratio.append(t / max(r["stage_cpu"], 1e-9))
        if ref is not None:
            nref += 1
            best_pruned += ref in pruned_set(r, rule["prune"])
            loss.setdefault(r["seed"], []).append(side(r, ref) - side(r, pk))
            reg.setdefault(r["seed"], []).append(side(r, r["served_idx"]) - side(r, pk))
    times.sort()
    out = dict(rule=rule, decisions=n, undetermined=undetermined, abandons=ab,
               abandon_rate=ab / n if n else None, p99_s=times[min(len(times) - 1, int(math.ceil(0.99 * len(times))) - 1)] if times else None,
               mean_cpu_ratio=sum(cpu_ratio) / len(cpu_ratio) if cpu_ratio else None,
               ref_decisions=nref, exact_best_pruned=best_pruned / nref if nref else None)
    flat = [v for vs in loss.values() for v in vs]
    out["pi_loss"] = sum(flat) / len(flat) if flat else None
    flat2 = [v for vs in reg.values() for v in vs]
    out["pi_regret_vs_served"] = sum(flat2) / len(flat2) if flat2 else None
    if with_ci:
        out["pi_loss_ci"] = boot(loss)[1:]
        out["pi_regret_vs_served_ci"] = boot(reg)[1:]
    return out


def capture_summary(rows, deals):
    elig = [r for r in rows if not r.get("capture_error")]
    cens = sum(bool(r.get("censored")) for r in elig)
    st = sorted(r["stage_cpu"] for r in elig if not r.get("censored"))
    q = lambda p: st[min(len(st) - 1, int(p * len(st)))] if st else None
    return dict(deals=deals, eligible=len(elig), capture_errors=len(rows) - len(elig), censored=cens,
                nodecap=sum(bool(r.get("nodecap")) for r in elig),
                pi_censored=sum(bool(r.get("pi_censored")) for r in elig),
                full_stage_cpu=dict(p50=q(.5), p90=q(.9), p98=q(.98), p99=q(.99), max=st[-1] if st else None))


def rules():
    for Wmin, z, prune, cap in itertools.product(*GRID.values()):
        yield dict(D=D_DEFAULT, Wmin=Wmin, z=z, prune=prune, cap=cap)


def choose(results):
    """Predeclared: abandons <= 2% on the tune half; minimum PI-loss point estimate; ties -> fewer abandons,
    then lower mean CPU ratio, then fewer active components."""
    ok = [x for x in results if x["abandon_rate"] is not None and x["abandon_rate"] <= 0.02 and x["pi_loss"] is not None]
    if not ok:
        return None
    comp = lambda r: (r["Wmin"] > 0) + (r["z"] is not None) + (r["prune"] > 0) + (r["cap"] is not None)
    return min(ok, key=lambda x: (round(x["pi_loss"], 9), x["abandon_rate"], x["mean_cpu_ratio"] or 0, comp(x["rule"])))


def main():
    mode, d, lo, hi = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    rows, deals = load(d, lo, hi)
    summ = capture_summary(rows, deals)
    if mode == "tune":
        res = [evaluate(rows, r) for r in rules()]
        best = choose(res)
        refs = {"all_or_nothing_D1.95": evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=0.0, cap=None), True)}
        for p in GRID["prune"]:
            refs[f"prune{int(p*100)}_only"] = evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=p, cap=None), True)
        if best is not None:
            best = evaluate(rows, best["rule"], True)
        json.dump(dict(summary=summ, chosen=best, references=refs, all=res), open(sys.argv[5], "w"), indent=1)
        print(json.dumps(dict(summary=summ, chosen=best), indent=1))
    else:
        rule = json.load(open(sys.argv[5]))["rule"]
        out = dict(summary=summ, frozen=evaluate(rows, rule, True))
        out["references"] = {f"prune{int(p*100)}_only": evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=p, cap=None), True)
                             for p in GRID["prune"]}
        out["references"]["all_or_nothing_D1.95"] = out["references"]["prune0_only"]
        out["frozen_prune_sweep"] = {f"prune{int(p*100)}": evaluate(rows, dict(rule, prune=p), True) for p in GRID["prune"]}
        json.dump(out, open(sys.argv[6], "w"), indent=1)
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
