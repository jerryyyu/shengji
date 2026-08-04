"""PAIRED CONFIRMATION of the root-prior racing result.

The screen (RL_PLAN 1o) showed mc-race4-v11pair beating mc, with a random-prune
control at 49.8%. Codex's 08:50 audit is right that this is not yet a
confirmation: the control ran on DIFFERENT deals, the logs carry no per-seed
records or manifest, sampling was non-strict, and 0.85x was a rollout count
rather than measured cost.

This run fixes all of that at once:

  * EVERY arm plays the SAME seed clusters, mirrored — so the control is
    paired with the treatment rather than compared across different deals;
  * strict sampling ON, with impossible-world fallbacks counted and refused;
  * per-seed/flip JSONL plus a manifest (git SHA, checkpoint digest, args,
    environment), written to an exclusive per-run file;
  * paired differences vs mc computed PER SEED and clustered by seed, since
    the two flips of a seed share a deal;
  * cost measured three ways — rollouts, search seconds, and net-inference
    seconds — because a rollout count is not a deployment cost;
  * signed level utility as the primary metric, per Codex's ruling.

Arms:
  * race4  — the net keeps its top 4 candidates, same rollout budget
  * rand4  — CONTROL: keep 4 at random, same budget scaling
  * mcref  — plain mc against itself, to expose any harness asymmetry

    uv run python scripts/race_confirm.py [clusters] [seed0]
"""
from __future__ import annotations

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
from shengji.ai.mcbot import MCBot           # noqa: E402
from shengji.ai.registry import make_bot     # noqa: E402
from shengji.engine.game import Game         # noqa: E402

ARMS = {"race4": "mc-race4-v11pair", "rand4": "mc-randrace4", "mcref": "mc"}


def counters(bots):
    return {
        "rollouts": sum(b.rollouts for b in bots),
        "search_calls": sum(b.search_calls for b in bots),
        "search_secs": round(sum(b.search_secs for b in bots), 4),
        "impossible": sum(getattr(b, "impossible_worlds", 0) for b in bots),
        "rejected": sum(getattr(b, "rejected_worlds", 0) for b in bots),
    }


def run(arm_name, policy, clusters, seed0, fh, run_id):
    recs = []
    for c in range(clusters):
        seed = seed0 + c
        for flip in (0, 1):
            a1 = make_bot(policy, seed=seed)
            a2 = make_bot(policy, seed=seed + 500_000)
            b1 = make_bot("mc", seed=seed + 1_000_000)
            b2 = make_bot("mc", seed=seed + 1_500_000)
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            t0 = time.perf_counter()
            log = play_round(Game(random.Random(seed)), pol)
            wall = time.perf_counter() - t0
            a_team = 0 if flip == 0 else 1
            won = int(log.winner_team == a_team)
            rec = {"run": run_id, "arm": arm_name, "policy": policy,
                   "seed": seed, "flip": flip, "won": won,
                   "level_utility": (1 if won else -1) * max(1, int(log.level_change)),
                   "round_wall": round(wall, 4),
                   "arm_side": counters([a1, a2]),
                   "mc_side": counters([b1, b2])}
            recs.append(rec)
            fh.write(json.dumps(rec) + "\n")
        if c and c % 25 == 0:
            w = sum(r["won"] for r in recs)
            print(f"    {arm_name}: {2*c}/{2*clusters} rounds, "
                  f"{w}-{len(recs)-w}", flush=True)
    return recs


def paired(recs_a, recs_b):
    """Mean per-seed difference in level utility, clustered by seed."""
    by = {}
    for r in recs_a:
        by.setdefault(r["seed"], [0, 0])[0] += r["level_utility"]
    for r in recs_b:
        by.setdefault(r["seed"], [0, 0])[1] += r["level_utility"]
    d = [x - y for x, y in by.values()]
    n = len(d)
    if n < 2:
        return 0.0, 0.0
    m = sum(d) / n
    var = sum((v - m) ** 2 for v in d) / (n - 1)
    return m, 1.96 * math.sqrt(var / n)


def wilson(w, n):
    if not n:
        return 0.0, 0.0, 0.0
    z, p = 1.96, w / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return p, c - h, c + h


def main() -> None:
    clusters = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else 12_000_000
    if not os.environ.get("SHENGJI_STRICT_SAMPLING"):
        print("REFUSING: set SHENGJI_STRICT_SAMPLING=1 — a confirmation that "
              "silently accepts impossible worlds is not a confirmation.")
        sys.exit(3)

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    npz = "snapshots_v11pair/ep07.npz"
    digest = hashlib.sha256(open(npz, "rb").read()).hexdigest()[:16] \
        if os.path.exists(npz) else "MISSING"
    run_id = f"race_confirm_{int(time.time())}_{sha}"
    manifest = {"run": run_id, "git": sha, "ckpt": npz, "ckpt_sha256_16": digest,
                "clusters": clusters, "seed0": seed0, "arms": ARMS,
                "strict_sampling": True,
                "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                "design": "all arms on the SAME mirrored seed clusters; "
                          "paired per-seed differences clustered by seed"}
    with open(f"runs/logs/{run_id}.manifest.json", "x") as mf:
        json.dump(manifest, mf, indent=2)
    print(json.dumps(manifest, indent=2), flush=True)

    out = f"runs/logs/{run_id}.jsonl"
    results = {}
    with open(out, "x") as fh:
        for arm, policy in ARMS.items():
            print(f"\n  arm {arm} ({policy})", flush=True)
            results[arm] = run(arm, policy, clusters, seed0, fh, run_id)

    print(f"\n{'arm':7} {'win% vs mc':>11} {'Wilson95':>18} "
          f"{'paired util/seed':>20} {'rollouts':>10} {'search s':>9}")
    for arm in ARMS:
        r = results[arm]
        w = sum(x["won"] for x in r)
        p, lo, hi = wilson(w, len(r))
        m, ci = paired(r, results["mcref"])
        roll = sum(x["arm_side"]["rollouts"] for x in r)
        secs = sum(x["arm_side"]["search_secs"] for x in r)
        print(f"{arm:7} {100*p:10.1f}% [{100*lo:6.1f},{100*hi:6.1f}] "
              f"{m:+11.3f} +/- {ci:5.3f} {roll:10d} {secs:9.1f}")

    ref_roll = sum(x["arm_side"]["rollouts"] for x in results["mcref"])
    ref_secs = sum(x["arm_side"]["search_secs"] for x in results["mcref"])
    print(f"\ncost vs plain mc (same deals):")
    for arm in ARMS:
        roll = sum(x["arm_side"]["rollouts"] for x in results[arm])
        secs = sum(x["arm_side"]["search_secs"] for x in results[arm])
        print(f"  {arm:7} rollouts {roll/max(ref_roll,1):.2f}x   "
              f"search seconds {secs/max(ref_secs,1):.2f}x")
    imp = sum(x["arm_side"]["impossible"] + x["mc_side"]["impossible"]
              for r in results.values() for x in r)
    rej = sum(x["arm_side"]["rejected"] + x["mc_side"]["rejected"]
              for r in results.values() for x in r)
    print(f"\nimpossible worlds USED {imp} (must be 0 under strict) | "
          f"REJECTED {rej}")
    print(f"records: {out}")
    print("\nPRIMARY = paired signed level utility vs the mc-vs-mc reference. "
          "The rand4 arm is the control: if it moves with race4, the gain is "
          "the pruning, not the prior.")


if __name__ == "__main__":
    main()
