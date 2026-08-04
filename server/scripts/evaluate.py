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


def _arm_ballots(names):
    """Which ballot each arm enumerates, recorded so a mismatch is visible.

    Every failure here is fatal. The previous version swallowed a construction
    error with `continue` (silently dropping an arm from the manifest) and
    fell back to "unknown" on any other error. Codex showed the result was
    worse than useless: `smart`, `heuristic`, `mc` and the narrow historical
    `mc-20260802am` were all reported as the same ballot, so the manifest
    looked authoritative while being false. A manifest that cannot establish
    what was on the ballot has not recorded the experiment.
    """
    from shengji.engine.ballot import ballot_for_policy
    out = {}
    for n in names:
        try:
            out[n] = str(ballot_for_policy(n))
        except Exception as exc:
            print(f"REFUSING: cannot determine the ballot for arm {n!r}: "
                  f"{type(exc).__name__}: {exc}\nAn experiment whose action "
                  f"sets are unknown cannot support a strength claim.")
            sys.exit(3)
    return out


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] \
        if os.path.exists(path) else None


def counters(bots):
    return {"rollouts": sum(getattr(b, "rollouts", 0) for b in bots),
            "searches": sum(getattr(b, "search_calls", 0) for b in bots),
            "search_secs": round(sum(getattr(b, "search_secs", 0.0)
                                     for b in bots), 4),
            "void_fallbacks": sum(getattr(b, "impossible_worlds", 0)
                                  for b in bots),
            "zero_world": sum(getattr(b, "zero_world_decisions", 0)
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
                    help="ENFORCED, not decorative: '<metric> > <value>' with "
                         "metric in {paired_utility, win_rate}. The clustered "
                         "interval must exclude the value to CONFIRM.")
    ap.add_argument("--allow-no-control", action="store_true")
    ap.add_argument("--allow-lenient-voids", action="store_true")
    ap.add_argument("--ckpt", action="append", default=[],
                    help="checkpoint paths to digest into the manifest")
    args = ap.parse_args()

    seed0 = args.seed0 if args.seed0 is not None else int(time.time()) % 5_000_000 * 7
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    # Second-resolution ids COLLIDE when parallel shards start in the same
    # second, and the manifest is opened with "x" — so a six-shard launch
    # would fail or overwrite (Codex). Include the pid.
    plan_names = [args.arm, args.opponent] + ([args.control] if args.control else [])
    run_id = f"eval_{int(time.time())}_{os.getpid()}_{sha}"
    manifest = {
        "run": run_id, "arm": args.arm, "opponent": args.opponent,
        "control": args.control, "clusters": args.clusters, "seed0": seed0,
        "declared_bar": args.bar,
        "git": sha, "tree_dirty": bool(dirty),
        "dirty_files": dirty.split("\n")[:20] if dirty else [],
        "script_sha256_16": digest(__file__),
        "ckpt_digests": {c: digest(c) for c in args.ckpt},
        "ballots": _arm_ballots(plan_names),
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    t_start = time.time()
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

    # ---- ENFORCE the declared bar, rather than printing it as prose ----
    import re as _re
    mt = _re.match(r"\s*(paired_utility|win_rate)\s*>\s*(-?[\d.]+)\s*$", args.bar)
    if not mt:
        print("\nREFUSING: --bar must be enforceable, e.g. 'paired_utility > 0' "
              "or 'win_rate > 0.5'. Free text cannot gate anything, and a bar "
              "that is recorded but not applied is theatre (Codex).")
        sys.exit(3)
    metric, threshold = mt.group(1), float(mt.group(2))
    m, ci = stats["arm"]
    if metric == "paired_utility":
        value, half = m, ci
    else:
        r = results["arm"]
        by = {}
        for x in r:
            by.setdefault(x["seed"], []).append(x["won"])
        per = [sum(v) / len(v) for v in by.values()]
        value = sum(per) / len(per)
        var = sum((p - value) ** 2 for p in per) / max(len(per) - 1, 1)
        half = 1.96 * math.sqrt(var / len(per))
    clears = value - half > threshold

    problems = []
    if not args.control and not args.allow_no_control:
        problems.append("no --control: a positive result is unattributable")
    if not os.environ.get("SHENGJI_REQUIRE_VOIDS") and not args.allow_lenient_voids:
        problems.append("SHENGJI_REQUIRE_VOIDS unset: sampled worlds may "
                        "violate observed voids")
    if not args.ckpt and any(("rl" in p or "v11" in p) for _, p in plan):
        problems.append("a net arm ran with no --ckpt digest recorded")
    if dirty:
        problems.append("tree was DIRTY: the git SHA does not describe the run")
    zw = sum(x["arm"]["zero_world"] + x["opp"]["zero_world"]
             for r in results.values() for x in r)
    if zw:
        problems.append(f"{zw} decisions searched ZERO worlds and fell back to "
                        f"candidate 0 — the search did not run there")

    print(f"\nDECLARED BAR: {metric} > {threshold}")
    print(f"MEASURED:     {value:+.3f} +/- {half:.3f}  -> "
          f"{'clears' if clears else 'does NOT clear'}")
    if args.control:
        cm, cci = stats["control"]
        # The DIRECT contrast, paired on the same seeds. Reporting each arm
        # against the reference leaves the actual question — is the arm better
        # than the control? — uncomputed. Codex had to work it out by hand for
        # the v13 duel (v13 minus v7 = -0.028 +/- 0.185), which is exactly the
        # number that should have been printed here.
        dm, dci, _ = paired_by_seed(results["arm"], results["control"])
        print(f"ARM MINUS CONTROL (paired, same seeds): {dm:+.3f} +/- {dci:.3f}"
              + ("  <-- excludes 0: the arm genuinely differs from its control"
                 if abs(dm) - dci > 0 else
                 "  <-- includes 0: arm and control are not distinguishable"))
        if abs(dm) - dci <= 0:
            problems.append("arm and control are not distinguishable from each "
                            "other")
        if cm - cci > threshold:
            print(f"CONTROL {args.control}: {cm:+.3f} +/- {cci:.3f}  <-- ALSO "
                  f"clears; the effect is not attributable to the arm")
            problems.append("the control clears the same bar")
        else:
            print(f"CONTROL {args.control}: {cm:+.3f} +/- {cci:.3f} (does not clear)")
    if problems:
        print("\nPROTOCOL FAILURES — verdict forced to NOT CONFIRMED:")
        for p_ in problems:
            print(f"  - {p_}")
    confirmed = clears and not problems
    print(f"\nVERDICT: {'CONFIRMED' if confirmed else 'NOT CONFIRMED'}")
    fb = sum(x["arm"]["void_fallbacks"] + x["opp"]["void_fallbacks"]
             for r in results.values() for x in r)
    sr = sum(x["arm"]["searches"] + x["opp"]["searches"]
             for r in results.values() for x in r)
    print(f"void fallbacks: {fb} over {sr} searches | wall "
          f"{(time.time()-t_start)/60:.1f} min")
    print(f"records: {out}\nmanifest: runs/logs/{run_id}.manifest.json")
    sys.exit(0 if confirmed else 1)


if __name__ == "__main__":
    main()
