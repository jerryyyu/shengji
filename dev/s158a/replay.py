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
import hashlib, itertools, json, math, os, random, sys

D_DEFAULT = 1.95
N_WORLDS = 64
#: the predeclared split (PREDECLARE_S158A.md); a CLI interval must equal one of them
SPLITS = {"tune": (1011400000, 1011401500), "read": (1011401500, 1011403000)}
CAPTURE_SPAN = (1011400000, 1011403000)
TERMINAL_LINE = "RUN DONE 3000/3000 deals"
HAND = 25          # cards per seat after the bury
CAPTURE_HAND = 8   # capture.py records every follow whose pre-play max hand is this


class ReplayInputError(ValueError):
    pass
GRID = dict(Wmin=[0, 8, 12, 16, 24], z=[None, 1.5, 2.0, 2.5], prune=[0.0, 0.2, 0.3, 0.4], cap=[None, 0.1, 0.25])


def _req(cond, msg):
    if not cond:
        raise ReplayInputError(msg)


def validate_row(r, seed):
    """A malformed captured row raises; a well-formed one is returned unchanged."""
    _req(r.get("seed") == seed, f"row seed {r.get('seed')} != deal seed {seed}")
    n = r.get("n_adm")
    _req(type(n) is int and n >= 0, f"seed {seed}: bad n_adm {n!r}")
    for key in ("trick", "pos", "seat"):
        _req(type(r.get(key)) is int, f"seed {seed}: row {key}")
    if n <= 1:
        # n_adm 0: a served play fallback (no ballot); 1: a single candidate. Ineligible, kept for the census.
        return r
    _req(isinstance(r.get("admitted"), list) and len(r["admitted"]) == n, f"seed {seed}: admitted length")
    _req(type(r.get("served_idx")) is int and 0 <= r["served_idx"] < n, f"seed {seed}: served_idx")
    _req(isinstance(r.get("attacker"), bool), f"seed {seed}: attacker")
    if r.get("capture_error"):
        return r
    vm = r.get("value_means")
    _req(isinstance(vm, list) and len(vm) == n and all(isinstance(v, (int, float)) for v in vm),
         f"seed {seed}: value_means")
    _req(r.get("n_worlds") == N_WORLDS, f"seed {seed}: n_worlds {r.get('n_worlds')} != {N_WORLDS}")
    wd = r.get("worlds_done")
    _req(type(wd) is int and 0 <= wd <= N_WORLDS, f"seed {seed}: worlds_done")
    _req(wd == N_WORLDS or r.get("censored") is True, f"seed {seed}: {wd} worlds without a censor flag")
    for key in ("L", "N", "T"):
        m = r.get(key)
        _req(isinstance(m, list) and len(m) == wd and all(isinstance(x, list) and len(x) == n for x in m),
             f"seed {seed}: {key} shape")
    _req(all(v is None or isinstance(v, (int, float)) for x in r["L"] for v in x), f"seed {seed}: L values")
    _req(all(isinstance(v, int) and v >= 0 for x in r["T"] for v in x), f"seed {seed}: T values")
    _req(isinstance(r.get("nodecap"), list), f"seed {seed}: nodecap")
    _req(isinstance(r.get("pi"), list) and all(isinstance(v, int) for v in r["pi"]), f"seed {seed}: pi")
    _req(len(r["pi"]) == n or r.get("pi_censored") is True, f"seed {seed}: pi incomplete without a censor flag")
    return r


def expected_rows(plays):
    """The (trick, pos, seat, cards) of every follow capture.py records, from the complete play history.
    Tricks are four consecutive plays in seat rotation; every seat holds HAND cards after the bury; each
    trick removes the followers' width from every seat (a refused throw's lead records the attempted cards,
    wider than what was played)."""
    _req(isinstance(plays, list) and plays and len(plays) % 4 == 0, "play history is not whole tricks")
    count = {s: HAND for s in range(4)}
    out = []
    for t in range(0, len(plays), 4):
        trick = plays[t:t + 4]
        for x in trick:
            _req(isinstance(x, list) and len(x) == 2 and x[0] in count and isinstance(x[1], list) and x[1],
                 "malformed play")
        seats = [x[0] for x in trick]
        _req(all((seats[i + 1] - seats[i]) % 4 == 1 for i in range(3)), f"trick {t // 4 + 1}: seats out of turn")
        w = len(trick[1][1])
        _req(all(len(x[1]) == w for x in trick[1:]), f"trick {t // 4 + 1}: follow widths differ")
        _req(len(trick[0][1]) >= w, f"trick {t // 4 + 1}: lead narrower than the follows")
        for pos in range(1, 4):
            before = {s: count[s] - (w if s in seats[:pos] else 0) for s in range(4)}
            if max(before.values()) == CAPTURE_HAND:
                out.append((t // 4 + 1, pos, seats[pos], sorted(trick[pos][1])))
        for s in seats:
            count[s] -= w
    _req(all(v == 0 for v in count.values()), f"play history incomplete: cards left {count}")
    return out


def validate_deal(deal, seed):
    """A complete instrumented deal whose rows are exactly the follows its play history says were captured."""
    _req(isinstance(deal, dict) and deal.get("seed") == seed, f"deal file {seed} holds seed {deal.get('seed')}")
    _req(deal.get("plain") is False, f"deal {seed} is not an instrumented capture")
    _req(isinstance(deal.get("decisions"), list), f"deal {seed}: no decisions list")
    try:
        want = expected_rows(deal.get("plays"))
    except ReplayInputError as exc:
        raise ReplayInputError(f"deal {seed}: {exc}")
    rows = deal["decisions"]
    for r in rows:
        _req(isinstance(r, dict), f"deal {seed}: row is not an object")
        validate_row(r, seed)
    keys = [(r["trick"], r["pos"], r["seat"]) for r in rows]
    _req(len(set(keys)) == len(keys), f"deal {seed}: duplicate captured rows")
    wk = {(t, p, s): c for t, p, s, c in want}
    _req(set(keys) == set(wk), f"deal {seed}: captured rows {sorted(set(keys) ^ set(wk))} do not match the history")
    for r in rows:
        if r["n_adm"] > 1 and not r.get("capture_error"):
            _req(r.get("played") == wk[(r["trick"], r["pos"], r["seat"])],
                 f"deal {seed}: row {r['trick']}/{r['pos']} played cards differ from the history")
    return rows


def ineligible_census(rows_all):
    """n_adm <= 1 positions by class, faults visible."""
    from collections import Counter
    c = Counter()
    for r in rows_all:
        if r["n_adm"] <= 1:
            c[f"n_adm={r['n_adm']} schema={r.get('schema')} fallback={r.get('fallback')} "
              f"reason={r.get('fallback_reason')}"] += 1
    return dict(c)


def load(d, lo, hi, splits=None, census=None):
    """Every deal of [lo, hi) exactly once, complete and non-plain, or ReplayInputError before scoring."""
    splits = SPLITS if splits is None else splits
    _req((lo, hi) in splits.values(), f"[{lo}, {hi}) is not a declared split {splits}")
    names = set(os.listdir(d))
    rows = []
    for seed in range(lo, hi):
        _req(f"{seed}.json" in names, f"missing deal {seed}")
        stray = [x for x in names if x.startswith(f"{seed}.json.tmp")]
        _req(not stray, f"unfinished temp file for {seed}: {stray}")
        try:
            deal = json.load(open(os.path.join(d, f"{seed}.json")))
        except ValueError as exc:
            raise ReplayInputError(f"deal {seed}: unreadable ({exc})")
        for r in validate_deal(deal, seed):
            if census is not None:
                census.append(r)
            if r["n_adm"] > 1:
                rows.append(r)
    return rows, hi - lo


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def check_read_preconditions(d, rule_path, sha_path):
    """Before the held-out CLI opens any deal file: the capture's terminal line and the frozen rule's
    recorded sha256."""
    log = os.path.join(d, "status.log")
    _req(os.path.exists(log), "no status.log: capture not terminal")
    lines = [x.rstrip("\n") for x in open(log) if x.strip()]
    _req(lines and lines[-1].endswith(TERMINAL_LINE), f"capture not terminal: last line {lines[-1:]!r}")
    _req(os.path.exists(sha_path), f"no recorded freeze sha {sha_path}")
    want = open(sha_path).read().split()[0]
    got = file_sha256(rule_path)
    _req(want == got, f"frozen rule sha {got} != recorded {want}")


def pick(means, alive, base):
    w = max(alive, key=lambda i: (means[i], -i))
    return base if means[w] <= means[base] else w


def prefix_means(L, worlds, idx):
    """Mean over ``worlds`` of each candidate in ``idx`` only (a node-capped null outside ``idx`` is never read)."""
    k = len(worlds)
    return {i: sum(L[w][i] for w in worlds) / k for i in idx}


def full_ref(r):
    """Full 64-world exact pick, or None when the capture was censored, node-capped or PI is missing."""
    if r.get("capture_error") or r.get("censored") or r.get("nodecap") or r.get("pi_censored"):
        return None
    if r["worlds_done"] != N_WORLDS or len(r["L"]) != N_WORLDS or len(r["pi"]) != r["n_adm"]:
        return None
    if any(v is None for x in r["L"] for v in x):
        return None
    n = r["n_adm"]
    return pick(prefix_means(r["L"], range(N_WORLDS), range(n)), list(range(n)), r["served_idx"])


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
    if r.get("capture_error"):
        return None, None, None
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
            m = prefix_means(L, done, alive)
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
    return pick(prefix_means(L, done, alive), alive, base), False, t


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
    """Every eligible follow (more than one admitted candidate) is in E: confirmed abandons A, unresolved U
    (capture error, capture stopped before the rule would, or a null cell the rule needs). The abandon rate
    is the interval [A/E, (A+U)/E]. PI loss and regret use the paired subset with a full 64-world exact
    reference and complete PI (coverage reported)."""
    D = rule.get("D", D_DEFAULT)
    E = len(rows); A = U = 0; times = []; loss = {}; reg = {}; best_pruned = 0; nref = 0; cpu_ratio = []
    for r in rows:
        pk, abd, t = sim(r, D, rule["Wmin"], rule["z"], rule["prune"], rule["cap"])
        if pk is None:
            U += 1; continue
        A += bool(abd); times.append(t)
        if r.get("stage_cpu") and not r.get("censored"):
            cpu_ratio.append(t / max(r["stage_cpu"], 1e-9))
        ref = full_ref(r)
        if ref is not None:
            nref += 1
            best_pruned += ref in pruned_set(r, rule["prune"])
            loss.setdefault(r["seed"], []).append(side(r, ref) - side(r, pk))
            reg.setdefault(r["seed"], []).append(side(r, r["served_idx"]) - side(r, pk))
    times.sort()
    lo_rate = A / E if E else None; hi_rate = (A + U) / E if E else None
    out = dict(rule=rule, eligible=E, abandons=A, unresolved=U,
               abandon_interval=[lo_rate, hi_rate],
               p99_s_resolved=times[min(len(times) - 1, int(math.ceil(0.99 * len(times))) - 1)] if times else None,
               mean_cpu_ratio=sum(cpu_ratio) / len(cpu_ratio) if cpu_ratio else None,
               ref_decisions=nref, pi_coverage=nref / E if E else None,
               exact_best_pruned=best_pruned / nref if nref else None)
    flat = [v for vs in loss.values() for v in vs]
    out["pi_loss"] = sum(flat) / len(flat) if flat else None
    flat2 = [v for vs in reg.values() for v in vs]
    out["pi_regret_vs_served"] = sum(flat2) / len(flat2) if flat2 else None
    if with_ci:
        out["pi_loss_ci"] = boot(loss)[1:]
        out["pi_regret_vs_served_ci"] = boot(reg)[1:]
    out["abandon_bar"] = abandon_verdict(out)
    return out


def abandon_verdict(x, bar=0.02):
    """PASS only when the upper end of the abandon interval clears the bar; FAIL when the lower end
    exceeds it; else INCONCLUSIVE."""
    lo, hi = x["abandon_interval"]
    if hi is None:
        return "INCONCLUSIVE"
    if hi <= bar:
        return "PASS"
    return "FAIL" if lo > bar else "INCONCLUSIVE"


def stage_a_verdict(x):
    """The plan's stop rule on the frozen rule: abandons PASS (upper bound <= 2%) and PI loss <= +0.05."""
    if x["abandon_bar"] == "FAIL" or (x["pi_loss"] is not None and x["pi_loss"] > 0.05):
        return "PARK"
    if x["abandon_bar"] == "PASS" and x["pi_loss"] is not None:
        return "PASS"
    return "INCONCLUSIVE"


def capture_summary(rows, deals):
    elig = [r for r in rows if not r.get("capture_error")]
    cens = sum(bool(r.get("censored")) for r in elig)
    nref = sum(full_ref(r) is not None for r in rows)
    st = sorted(r["stage_cpu"] for r in elig if not r.get("censored"))
    q = lambda p: st[min(len(st) - 1, int(p * len(st)))] if st else None
    return dict(deals=deals, eligible=len(rows), capture_errors=len(rows) - len(elig), censored=cens,
                full_reference=nref,
                nodecap=sum(bool(r.get("nodecap")) for r in elig),
                pi_censored=sum(bool(r.get("pi_censored")) for r in elig),
                full_stage_cpu=dict(p50=q(.5), p90=q(.9), p98=q(.98), p99=q(.99), max=st[-1] if st else None))


def rules():
    for Wmin, z, prune, cap in itertools.product(*GRID.values()):
        yield dict(D=D_DEFAULT, Wmin=Wmin, z=z, prune=prune, cap=cap)


def choose(results):
    """Predeclared: abandons <= 2% on the tune half; minimum PI-loss point estimate; ties -> fewer abandons,
    then lower mean CPU ratio, then fewer active components."""
    ok = [x for x in results if x["abandon_bar"] == "PASS" and x["pi_loss"] is not None]
    if not ok:
        return None
    comp = lambda r: (r["Wmin"] > 0) + (r["z"] is not None) + (r["prune"] > 0) + (r["cap"] is not None)
    return min(ok, key=lambda x: (round(x["pi_loss"], 9), x["abandon_interval"][1], x["mean_cpu_ratio"] or 0,
                                  comp(x["rule"])))


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    mode, d, lo, hi = a[0], a[1], int(a[2]), int(a[3])
    if mode == "tune":
        _req((lo, hi) == SPLITS["tune"], f"tune needs the tune split {SPLITS['tune']}")
        allr = []
        rows, deals = load(d, lo, hi, census=allr)
        summ = dict(capture_summary(rows, deals), ineligible=ineligible_census(allr))
        res = [evaluate(rows, r) for r in rules()]
        best = choose(res)
        refs = {f"prune{int(p*100)}_only": evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=p, cap=None), True)
                for p in GRID["prune"]}
        if best is not None:
            best = evaluate(rows, best["rule"], True)
        out = dict(summary=summ, chosen=best, references=refs, all=res)
        json.dump(out, open(a[4], "w"), indent=1)
        print(json.dumps(dict(summary=summ, chosen=best), indent=1))
        return out
    _req(mode == "read", f"unknown mode {mode!r}")
    _req((lo, hi) == SPLITS["read"], f"read needs the read split {SPLITS['read']}")
    rule_path, out_path = a[4], a[5]
    sha_path = a[a.index("--rule-sha") + 1] if "--rule-sha" in a else rule_path + ".sha256"
    check_read_preconditions(d, rule_path, sha_path)      # before any deal file is opened
    rule = json.load(open(rule_path))["rule"]
    allr = []
    rows, deals = load(d, lo, hi, census=allr)
    out = dict(summary=dict(capture_summary(rows, deals), ineligible=ineligible_census(allr)), rule_sha256=file_sha256(rule_path),
               frozen=evaluate(rows, rule, True))
    out["verdict"] = stage_a_verdict(out["frozen"])
    out["references"] = {f"prune{int(p*100)}_only": evaluate(rows, dict(D=1.95, Wmin=0, z=None, prune=p, cap=None), True)
                         for p in GRID["prune"]}
    out["frozen_prune_sweep"] = {f"prune{int(p*100)}": evaluate(rows, dict(rule, prune=p), True) for p in GRID["prune"]}
    json.dump(out, open(out_path, "w"), indent=1)
    print(json.dumps(dict(summary=out["summary"], frozen=out["frozen"], verdict=out["verdict"]), indent=1))
    return out


if __name__ == "__main__":
    main()
