"""THE evaluator. Every strength claim goes through this and no other path.

Three claims died in one day — vleaf 60%, v11pair 52%, root-prior racing 54.8%
— and none of them died from a bad idea. They died because a screen on
UNPAIRED blocks looked good and several blocks agreeing was read as
reproduction. Rounds inside a mirrored pair, and inside a seed cluster, are
correlated; binomial intervals do not know that, so agreeing blocks can be
correlated draws from a distribution wide enough to produce them by luck.

What this enforces, rather than describes:

  * the arm, its CONTROL, and an opponent-vs-opponent reference all play the
    SAME mirrored deals — a control on different deals proves nothing;
  * the primary statistic is PAIRED per-seed level utility, clustered BY SEED,
    because the two flips of a seed share a deal;
  * a bar must be declared on the command line BEFORE the run and is recorded
    in the manifest — a bar chosen after seeing the number is not a bar;
  * the manifest records the git SHA, whether the tree was DIRTY, the digest
    of this script and of every checkpoint, so a run cannot claim provenance
    it does not have;
  * per-seed/flip records go to an exclusive file that reruns cannot mix into;
  * the verdict is CONFIRMED or NOT CONFIRMED. There is no "promising".

    uv run python scripts/evaluate.py ARM OPPONENT --clusters 250 \\
        --bar "paired level utility > 0 with the interval excluding 0" \\
        [--control ARM] [--seed0 N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, ".")

from shengji.ai.env import play_round        # noqa: E402
from shengji.ai.registry import make_bot     # noqa: E402
from shengji.engine.game import Game         # noqa: E402


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] \
        if os.path.exists(path) else None


def counters(bots):
    return {"rollouts": sum(getattr(b, "rollouts", 0) for b in bots),
            "searches": sum(getattr(b, "search_calls", 0) for b in bots),
            "search_secs": round(sum(getattr(b, "search_secs", 0.0)
                                     for b in bots), 4),
            "void_fallbacks": sum(getattr(b, "impossible_worlds", 0)
                                  for b in bots)}


def run_arm(label, policy, opponent, clusters, seed0, fh, run_id):
    recs = []
    for c in range(clusters):
        seed = seed0 + c
        for flip in (0, 1):
            a1 = make_bot(policy, seed=seed)
            a2 = make_bot(policy, seed=seed + 500_000)
            b1 = make_bot(opponent, seed=seed + 1_000_000)
            b2 = make_bot(opponent, seed=seed + 1_500_000)
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            log = play_round(Game(random.Random(seed)), pol)
            won = int(log.winner_team == (0 if flip == 0 else 1))
            rec = {"run": run_id, "label": label, "policy": policy,
                   "seed": seed, "flip": flip, "won": won,
                   "level_utility": (1 if won else -1) * max(1, int(log.level_change)),
                   "arm": counters([a1, a2]), "opp": counters([b1, b2])}
            recs.append(rec)
            fh.write(json.dumps(rec) + "\n")
        if c and c % 50 == 0:
            w = sum(r["won"] for r in recs)
            print(f"    {label}: {2*c}/{2*clusters} rounds, {w}-{len(recs)-w}",
                  flush=True)
    return recs


def paired_by_seed(a_recs, b_recs):
    """Mean per-SEED difference in level utility, with a clustered interval.

    Clustering by seed is the whole point: the two flips of a seed share a
    deal, so treating 2*clusters rounds as independent understates the spread.
    """
    by = {}
    for r in a_recs:
        by.setdefault(r["seed"], [0, 0])[0] += r["level_utility"]
    for r in b_recs:
        by.setdefault(r["seed"], [0, 0])[1] += r["level_utility"]
    d = [x - y for x, y in by.values()]
    n = len(d)
    if n < 2:
        return 0.0, 0.0, n
    m = sum(d) / n
    var = sum((v - m) ** 2 for v in d) / (n - 1)
    return m, 1.96 * math.sqrt(var / n), n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm")
    ap.add_argument("opponent")
    ap.add_argument("--clusters", type=int, default=250)
    ap.add_argument("--seed0", type=int, default=None)
    ap.add_argument("--control", default=None,
                    help="an arm that SHOULD NOT work; without one, a positive "
                         "result cannot be attributed to the thing you changed")
    ap.add_argument("--bar", required=True,
                    help="declared BEFORE the run and recorded in the manifest")
    ap.add_argument("--ckpt", action="append", default=[],
                    help="checkpoint paths to digest into the manifest")
    args = ap.parse_args()

    seed0 = args.seed0 if args.seed0 is not None else int(time.time()) % 5_000_000 * 7
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    run_id = f"eval_{int(time.time())}_{sha}"
    manifest = {
        "run": run_id, "arm": args.arm, "opponent": args.opponent,
        "control": args.control, "clusters": args.clusters, "seed0": seed0,
        "declared_bar": args.bar,
        "git": sha, "tree_dirty": bool(dirty),
        "dirty_files": dirty.split("\n")[:20] if dirty else [],
        "script_sha256_16": digest(__file__),
        "ckpt_digests": {c: digest(c) for c in args.ckpt},
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs("runs/logs", exist_ok=True)
    with open(f"runs/logs/{run_id}.manifest.json", "x") as mf:
        json.dump(manifest, mf, indent=2)
    print(json.dumps(manifest, indent=2), flush=True)
    if dirty:
        print("\nWARNING: tree is DIRTY — this run's git SHA does not describe "
              "the code that ran. Recorded in the manifest.", flush=True)

    plan = [("arm", args.arm), ("reference", args.opponent)]
    if args.control:
        plan.append(("control", args.control))
    out = f"runs/logs/{run_id}.jsonl"
    results = {}
    with open(out, "x") as fh:
        for label, policy in plan:
            print(f"\n  {label}: {policy} vs {args.opponent}", flush=True)
            results[label] = run_arm(label, policy, args.opponent,
                                     args.clusters, seed0, fh, run_id)

    ref = results["reference"]
    print(f"\n{'':10} {'win%':>7} {'paired level utility/seed':>28} "
          f"{'rollouts':>10} {'search s':>9}")
    stats = {}
    for label, _ in plan:
        r = results[label]
        w = sum(x["won"] for x in r)
        m, ci, nseed = paired_by_seed(r, ref)
        stats[label] = (m, ci)
        print(f"{label:10} {100*w/len(r):6.1f}% {m:+16.3f} +/- {ci:6.3f} "
              f"{sum(x['arm']['rollouts'] for x in r):10d} "
              f"{sum(x['arm']['search_secs'] for x in r):9.1f}")

    m, ci = stats["arm"]
    confirmed = m - ci > 0
    print(f"\nDECLARED BAR: {args.bar}")
    print(f"VERDICT: {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} "
          f"(paired {m:+.3f} +/- {ci:.3f} vs the reference)")
    if args.control:
        cm, cci = stats["control"]
        print(f"CONTROL {args.control}: {cm:+.3f} +/- {cci:.3f}"
              + ("  <-- moves WITH the arm: the effect is not attributable "
                 "to what you changed" if cm - cci > 0 else ""))
    else:
        print("NO CONTROL was run. A positive result here cannot be attributed "
              "to the thing you changed.")
    fb = sum(x["arm"]["void_fallbacks"] + x["opp"]["void_fallbacks"]
             for r in results.values() for x in r)
    sr = sum(x["arm"]["searches"] + x["opp"]["searches"]
             for r in results.values() for x in r)
    print(f"void fallbacks: {fb} over {sr} searches")
    print(f"records: {out}\nmanifest: runs/logs/{run_id}.manifest.json")
    sys.exit(0 if confirmed else 1)


if __name__ == "__main__":
    main()
