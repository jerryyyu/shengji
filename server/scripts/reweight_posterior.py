"""Recompute posterior TV against the PHYSICAL-DEAL reference, from stored runs.

`sampler_posterior.py` scored against a reference that is flat over
DEDUPLICATED MULTISET keys: `enumerate_legal()` collapses physical index
assignments into a set key and gives every key `1/n` (Codex). That is not the
sampler's stated target. Determinization assumes an uninformative prior over
DEALS consistent with the public record, and a deal is physical — with a double
deck, one multiset world can be produced by many distinct physical deals.

Under a uniform-over-physical-deals prior the correct reference is

    P(w) proportional to  prod_c  m_c! / prod_r k_{c,r}!

for card code `c` with `m_c` hidden copies and `k_{c,r}` of them at receiver
`r` (the unseen seats plus the kitty). Every hidden copy goes somewhere, so
`sum_r k_{c,r} = m_c` and the multinomial is exact rather than an approximation.

Worked example, the one Codex named: `AABB` split 2/2 between two receivers has
three multiset outcomes but SIX physical deals — `AA|BB` and `BB|AA` arise one
way each, `AB|AB` four ways. The flat reference calls these 1/3 each; the true
prior is 1/6, 4/6, 1/6. The flat reference therefore UNDER-weights balanced
worlds, which is the same direction the weighted-splits repair pushes, so the
confirmed `-0.0514` had to be rechecked here before it could be believed.

This reads the `sampled_hist` and `legal_keys` recorded in each run, so no
resampling is needed and existing blocks stay usable.

    uv run python scripts/reweight_posterior.py runs/logs/post24_*.json
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict


def parse_key(s: str) -> tuple:
    """Recover the world key from its `repr` as stored in the JSON."""
    return ast.literal_eval(s)


def physical_weight(key: tuple) -> int:
    """Number of distinct physical deals that yield this multiset world."""
    receivers = [cards for _seat, cards in key[0]]
    if len(key) > 1:
        receivers.append(tuple(key[1]))
    per_code: dict[str, list[int]] = defaultdict(list)
    for cards in receivers:
        for code, k in Counter(cards).items():
            per_code[code].append(k)
    w = 1
    for code, ks in per_code.items():
        m = sum(ks)
        num = math.factorial(m)
        for k in ks:
            num //= math.factorial(k)
        w *= num
    return w


def tv_noise_band(probs: list[float], draws: int, reps: int = 200,
                  seed: int = 12345) -> float:
    """95th-percentile TV a PERFECT sampler from `probs` shows at this n.

    Must sample from the WEIGHTED reference, not a uniform one: the floor
    depends on the reference's shape, and a peaked reference has a different
    floor than a flat one at the same support size.
    """
    rng = random.Random(seed)
    idx = list(range(len(probs)))
    tvs = []
    for _ in range(reps):
        c = Counter(rng.choices(idx, weights=probs, k=draws))
        tvs.append(0.5 * sum(abs(c.get(i, 0) / draws - probs[i]) for i in idx))
    tvs.sort()
    return tvs[int(0.95 * len(tvs))]


def reweight(path: str) -> dict:
    with open(path) as fh:
        d = json.load(fh)
    out_rows = []
    for r in d["rows"]:
        if "legal_keys" not in r or "sampled_hist" not in r:
            print(f"  SKIP {os.path.basename(path)} seed {r['seed']}: "
                  "predates histogram recording")
            continue
        legal = [parse_key(k) for k in r["legal_keys"]]
        w = [physical_weight(k) for k in legal]
        tot = sum(w)
        probs = [x / tot for x in w]
        hist = {parse_key(k): v for k, v in r["sampled_hist"]}
        draws = sum(hist.values())

        tv = 0.5 * sum(abs(hist.get(k, 0) / draws - p)
                       for k, p in zip(legal, probs))
        tv += 0.5 * sum(v / draws for k, v in hist.items()
                        if k not in set(legal))
        band = tv_noise_band(probs, draws)
        out_rows.append({"seed": r["seed"], "n_legal": len(legal),
                         "draws": draws,
                         "tv_flat": r["tv"],
                         "tv_excess_flat": r["tv_excess"],
                         "tv": tv, "tv_noise_95": band,
                         "tv_excess": max(0.0, tv - band),
                         "weight_ratio_max": max(w) / min(w),
                         "legal_keys": r["legal_keys"],
                         "sampled_hist": r["sampled_hist"]})
    d["rows"] = out_rows
    d["reference"] = "uniform-over-PHYSICAL-DEALS (repaired)"
    d["mean_tv"] = sum(r["tv"] for r in out_rows) / len(out_rows)
    d["mean_tv_excess"] = sum(r["tv_excess"] for r in out_rows) / len(out_rows)
    d["biased_states"] = sum(1 for r in out_rows if r["tv_excess"] > 0.05)
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    args = ap.parse_args()
    for path in args.runs:
        d = reweight(path)
        out = path.replace(".json", ".phys.json")
        if out == path:
            print(f"REFUSING to overwrite {path} in place")
            sys.exit(3)
        with open(out, "w") as fh:
            json.dump(d, fh, indent=1)
        n = len(d["rows"])
        mf = sum(r["tv_excess_flat"] for r in d["rows"]) / n
        mp = d["mean_tv_excess"]
        wr = max(r["weight_ratio_max"] for r in d["rows"])
        print(f"  {os.path.basename(path):34} n={n:2d}  "
              f"excess flat {mf:.4f} -> physical {mp:.4f}   "
              f"max weight ratio {wr:.0f}x")
        print(f"  {'':34} wrote {os.path.basename(out)}")


if __name__ == "__main__":
    main()
