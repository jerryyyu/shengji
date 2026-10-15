"""DEV offline measurement of the history-legal world test on store states.

For held-out-style store play decisions, draws 64 worlds two ways with the same
sampler seed: release 45's branch (refusal-aware when the replayed ledger holds a
refusal, else the plain draw) and the same branch with the history-legal test
(`ai.history_legality.sample_worlds_history_legal`).  Per state it writes the
share of release-45 worlds that make an earlier follow illegal (by how many
tricks back the first violated follow lies), the test's rejections, attempts
and fallback worlds, the sampler seconds of both arms, and the soft-oracle card
agreement of both arms against the sealed deal (`pv_soft_oracle.agreement`).

Offline agreement and sampler seconds are not playing strength.

Usage (cwd server/):
  SHENGJI_FAST=1 nice -n 15 .venv/bin/python scripts/s27_world_legality_eval.py \
      --stores /root/traj-out/runPVC4 ... --out OUT.jsonl --rate 0.03 --workers 2
  .venv/bin/python scripts/s27_world_legality_eval.py --summarize OUT.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

W = 64


def _pick(key: str, rate: float) -> bool:
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) / 16 ** 12 < rate


def _seed(key: str) -> int:
    return int(hashlib.sha256((key + "|s27").encode()).hexdigest()[:8], 16)


def measure(rnd, seat, refusals, seed):
    from shengji.ai import history_legality as HL
    from shengji.ai.cwv_policy import sample_worlds
    from shengji.ai.mcbot import MCBot
    from shengji.ai.memory import Memory
    from shengji.ai.refusal import sample_worlds_refusal_aware
    from shengji.train import pv_soft_oracle as so

    out = {}
    bot = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    t0 = time.perf_counter()
    if refusals:
        base, attempts, _ = sample_worlds_refusal_aware(bot, rnd, seat, W, list(refusals), mem=mem)
    else:
        base, attempts = sample_worlds(bot, rnd, seat, W, mem=mem)
    out["base_secs"] = time.perf_counter() - t0
    out["base_attempts"] = attempts
    layout = so.hidden_layout(bot, rnd, seat, mem, rnd.hands, rnd.buried)
    events = HL.follow_events(rnd, seat)
    current = len(rnd.history)
    if HL.first_violation(events, rnd.hands, rnd.ordering) is not None:
        raise AssertionError("the true deal fails the history test")
    by_age = Counter()
    bad = 0
    for hands, _ in base:
        b = HL.first_violation(events, hands, rnd.ordering)
        if b is not None:
            bad += 1
            by_age[current - events[b].trick] += 1
    out["base_illegal"] = bad
    out["base_illegal_by_age"] = dict(by_age)

    def agree(worlds):
        if not layout.hidden:
            return 1.0
        return sum(so.agreement(layout, h, b)[0] for h, b in worlds) / (layout.hidden * len(worlds))
    out["base_agreement"] = agree(base)
    legal = [w for w in base if HL.first_violation(events, w[0], rnd.ordering) is None]
    out["base_legal_subset_agreement"] = agree(legal) if legal else None

    bot = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    t0 = time.perf_counter()
    whl, attempts, stats = HL.sample_worlds_history_legal(bot, rnd, seat, W, tuple(refusals),
                                                          mem=mem)
    out["whl_secs"] = time.perf_counter() - t0
    out["whl_attempts"] = attempts
    out["whl_stats"] = stats
    out["whl_agreement"] = agree(whl)
    out["whl_illegal"] = sum(HL.first_violation(events, h, rnd.ordering) is not None
                             for h, _ in whl)
    out["events"] = len(events)
    out["hidden"] = layout.hidden

    # the draw-time form, same seed; and a second rejection draw on another
    # seed as the noise floor for the marginal comparison
    t0 = time.perf_counter()
    cons = HL.draw_constraints(rnd, seat, events)
    out["derive_secs"] = time.perf_counter() - t0
    bot = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    t0 = time.perf_counter()
    whd, attempts, stats = HL.sample_worlds_history_legal(bot, rnd, seat, W, tuple(refusals),
                                                          mem=mem, constrain=True)
    out["whd_secs"] = time.perf_counter() - t0
    out["whd_attempts"] = attempts
    out["whd_stats"] = stats
    out["whd_agreement"] = agree(whd)
    out["whd_illegal"] = sum(HL.first_violation(events, h, rnd.ordering) is not None
                             for h, _ in whd)
    bot = MCBot(seed=seed ^ 0x5A5A5A)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    whl2, _, _ = HL.sample_worlds_history_legal(bot, rnd, seat, W, tuple(refusals), mem=mem)
    out["whl2_agreement"] = agree(whl2)
    m = [_marginal(ws, seat) for ws in (whl, whl2, whd)]
    out["tv_whl_whl2"] = _tv(m[0], m[1])
    out["tv_whl_whd"] = _tv(m[0], m[2])
    out["tv_whl2_whd"] = _tv(m[1], m[2])
    return out


def _marginal(worlds, seat):
    """Per hidden card code, the share of its copies with each other seat or
    the kitty, over the worlds."""
    counts: dict = {}
    for hands, buried in worlds:
        for s in range(4):
            if s == seat:
                continue
            for c in hands[s]:
                counts.setdefault(c, Counter())[s] += 1
        for c in buried:
            counts.setdefault(c, Counter())["k"] += 1
    return counts


def _tv(a, b):
    """Mean over codes of the total-variation distance between receiver shares."""
    import numpy as np
    out = []
    for c in set(a) | set(b):
        ca, cb = a.get(c, Counter()), b.get(c, Counter())
        na, nb = sum(ca.values()), sum(cb.values())
        if not na or not nb:
            continue
        keys = set(ca) | set(cb)
        out.append(0.5 * sum(abs(ca[k] / na - cb[k] / nb) for k in keys))
    return float(np.mean(out)) if out else 0.0


def _task(args):
    store, si, ci, path, rate = args
    from shengji.train.belief_labels import iter_decisions, role_of
    recs = [json.loads(line) for line in open(path) if line.strip()]
    rows = []
    for d in iter_decisions(recs):
        key = f"{store}|{ci}|{d.round_index}|{d.decision_index}"
        if not _pick(key, rate):
            continue
        rnd = d.rnd
        row = dict(store=si, cluster=ci, round=d.round_index, decision=d.decision_index,
                   trick=len(rnd.history) + 1, role=role_of(rnd, d.seat),
                   refusals=len(d.refusals))
        row.update(measure(rnd, d.seat, d.refusals, _seed(key)))
        rows.append(row)
    return rows


def run(stores, out, rate, workers, stride, offset, limit):
    from shengji.train.belief_labels import cluster_paths
    tasks = []
    for si, store in enumerate(stores):
        paths = cluster_paths(store)
        for ci in range(offset, len(paths), stride)[:limit]:
            tasks.append((store, si, ci, str(paths[ci]), rate))
    print(f"{len(tasks)} clusters", flush=True)
    n = 0
    t0 = time.time()
    with open(out, "a") as fh:
        if workers <= 1:
            it = map(_task, tasks)
        else:
            import multiprocessing as mp
            it = mp.get_context("spawn").Pool(workers).imap_unordered(_task, tasks)
        for i, rows in enumerate(it, 1):
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            n += len(rows)
            fh.flush()
            if i % 10 == 0:
                print(f"{i}/{len(tasks)} clusters, {n} states, {time.time() - t0:.0f}s", flush=True)
    print(f"DONE {n} states", flush=True)


def _q(xs, q):
    import numpy as np
    return float(np.percentile(np.asarray(xs, float), q)) if xs else None


def summarize(paths):
    import numpy as np
    rows = [json.loads(line) for p in paths for line in open(p) if line.strip()]
    S = len(rows)
    print(f"states {S}")
    worlds = S * W
    print(f"release-45 worlds history-illegal: {sum(r['base_illegal'] for r in rows) / worlds:.4f}"
          f"; states with any: {sum(r['base_illegal'] > 0 for r in rows) / S:.3f}")
    bands = [(1, 1), (2, 5), (6, 10), (11, 15), (16, 25)]
    for lo, hi in bands:
        sub = [r for r in rows if lo <= r["trick"] <= hi]
        if not sub:
            continue
        rej = sum(r["whl_stats"]["history_rejections"] for r in sub)
        att = sum(r["whl_attempts"] for r in sub)
        print(f"  tricks {lo:2d}-{hi:2d}: n={len(sub):4d} illegal share "
              f"{sum(r['base_illegal'] for r in sub) / (len(sub) * W):.4f}  rejections/attempt "
              f"{rej / att:.4f}  attempts/state mean {att / len(sub):.1f} "
              f"(base {sum(r['base_attempts'] for r in sub) / len(sub):.1f})  fallback worlds "
              f"{sum(r['whl_stats']['history_fallback_worlds'] for r in sub)}  agreement gain "
              f"{np.mean([r['whl_agreement'] - r['base_agreement'] for r in sub]) * 100:+.2f} pp")
    age = Counter()
    for r in rows:
        for k, v in r["base_illegal_by_age"].items():
            age[int(k)] += v
    tot = sum(age.values())
    print("  first violated follow, tricks back:",
          {k: round(v / tot, 3) for k, v in sorted(age.items())[:8]}, f"(n={tot})")
    extra = [r["whl_secs"] - r["base_secs"] for r in rows]
    for name, xs in (("base", [r["base_secs"] for r in rows]),
                     ("whl", [r["whl_secs"] for r in rows]), ("extra", extra)):
        print(f"  {name:5s} sampler secs p50 {_q(xs, 50):.4f} p90 {_q(xs, 90):.4f} "
              f"p99 {_q(xs, 99):.4f} max {max(xs):.4f}")
    att = [r["whl_attempts"] for r in rows]
    print(f"  whl attempts p50 {_q(att, 50):.0f} p90 {_q(att, 90):.0f} p99 {_q(att, 99):.0f} "
          f"max {max(att)}; states with fallback worlds "
          f"{sum(r['whl_stats']['history_fallback_worlds'] > 0 for r in rows)}; whl worlds "
          f"still illegal {sum(r['whl_illegal'] for r in rows)}")
    g = np.array([r["whl_agreement"] - r["base_agreement"] for r in rows])
    rng = np.random.default_rng(1)
    boots = [g[rng.integers(0, S, S)].mean() for _ in range(4000)]
    print(f"  agreement base {np.mean([r['base_agreement'] for r in rows]):.4f} whl "
          f"{np.mean([r['whl_agreement'] for r in rows]):.4f} gain {g.mean() * 100:+.3f} pp "
          f"[{np.percentile(boots, 2.5) * 100:+.3f}, {np.percentile(boots, 97.5) * 100:+.3f}]")
    sub = [r for r in rows if r["base_legal_subset_agreement"] is not None]
    print(f"  base legal-subset agreement (the zeroing reading) gain "
          f"{np.mean([r['base_legal_subset_agreement'] - r['base_agreement'] for r in sub]) * 100:+.3f} pp")
    if "whd_secs" in rows[0]:
        print("  draw-time form (whd):")
        for name, key in (("whl", "whl_secs"), ("whd", "whd_secs"), ("derive", "derive_secs")):
            xs = [r[key] for r in rows]
            print(f"    {name:6s} secs p50 {_q(xs, 50):.4f} p90 {_q(xs, 90):.4f} p99 {_q(xs, 99):.4f} "
                  f"max {max(xs):.4f}")
        for name in ("whl", "whd"):
            att = [r[f"{name}_attempts"] for r in rows]
            rej = sum(r[f"{name}_stats"]["history_rejections"] for r in rows)
            hits = sum(r[f"{name}_stats"]["history_fallback_worlds"] > 0 for r in rows)
            print(f"    {name} attempts p50 {_q(att, 50):.0f} p90 {_q(att, 90):.0f} p99 {_q(att, 99):.0f} "
                  f"max {max(att)}; rejections/attempt {rej / sum(att):.4f}; budget hits {hits}/{S} "
                  f"({hits / S:.3f}); illegal worlds left {sum(r[f'{name}_illegal'] for r in rows)}")
        d = np.array([r["whd_agreement"] - r["whl_agreement"] for r in rows])
        boots = [d[rng.integers(0, S, S)].mean() for _ in range(4000)]
        print(f"    agreement whd {np.mean([r['whd_agreement'] for r in rows]):.4f} vs whl "
              f"{np.mean([r['whl_agreement'] for r in rows]):.4f}: {d.mean() * 100:+.3f} pp "
              f"[{np.percentile(boots, 2.5) * 100:+.3f}, {np.percentile(boots, 97.5) * 100:+.3f}]; "
              f"whl second seed {np.mean([r['whl2_agreement'] for r in rows]):.4f}")
        print(f"    marginal TV (mean over states): whl vs whl(seed 2) "
              f"{np.mean([r['tv_whl_whl2'] for r in rows]):.4f}; whl vs whd "
              f"{np.mean([r['tv_whl_whd'] for r in rows]):.4f}; whl(seed 2) vs whd "
              f"{np.mean([r['tv_whl2_whd'] for r in rows]):.4f}")
    for role in (0, 1, 2):
        sub = [r for r in rows if r["role"] == role]
        if sub:
            print(f"  role {role}: n={len(sub)} gain "
                  f"{np.mean([r['whl_agreement'] - r['base_agreement'] for r in sub]) * 100:+.2f} pp")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stores", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--rate", type=float, default=0.03)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--stride", type=int, default=40)
    ap.add_argument("--offset", type=int, default=7)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--summarize", nargs="*")
    a = ap.parse_args(argv)
    if a.summarize:
        summarize(a.summarize)
        return
    os.environ.setdefault("SHENGJI_FAST", "1")
    run(a.stores, a.out, a.rate, a.workers, a.stride, a.offset, a.limit)


if __name__ == "__main__":
    main()
