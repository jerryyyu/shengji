"""Aggregate sharded evaluator runs — with the guards that hand-globbing lacked.

A block of six shards was aggregated by globbing `runs/logs/eval_*.jsonl` and
summing `level_utility` per seed. An ABORTED earlier attempt had left 40 arm
records on disk covering seeds already produced by the complete rerun, so the
arm side had 544 records against 504 for reference and control, twenty seeds
were counted twice on one side only, and the published effect was inflated
from +0.274 to +0.282 (Codex found this; it reproduces exactly).

Nothing about that was subtle — it was invisible because the aggregation had
no invariants. This script refuses rather than reports when:

  * a label's record count differs from another's (asymmetric coverage);
  * a (label, seed, flip) appears more than once (a rerun mixed in);
  * shards disagree about the git SHA they ran at;
  * any record carries a zero-world decision, which the evaluator already
    treats as a protocol failure — reading a paired mean out of a run whose
    own verdict was forced to NOT CONFIRMED is how the N=10-over-N=5 claim
    was overstated.

    uv run python scripts/aggregate_shards.py --lo 94000000 --hi 95999999 \\
        --policy mc-strong --label-a arm --label-b reference
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import Counter, defaultdict


class AggregationRefused(RuntimeError):
    pass


def load_records(pattern, policy, lo, hi, exclude_sha=()):
    """Every record in [lo, hi] for `policy`, tagged with its source file."""
    out = []
    for path in sorted(glob.glob(pattern)):
        if any(s in path for s in exclude_sha):
            continue
        try:
            recs = [json.loads(l) for l in open(path)]
        except (json.JSONDecodeError, OSError):
            continue
        if not recs or recs[0].get("policy") != policy:
            continue
        seeds = [r["seed"] for r in recs]
        if min(seeds) < lo or max(seeds) > hi:
            continue
        for r in recs:
            r["_src"] = os.path.basename(path)
        out += recs
    return out


def check(records):
    """Refuse on any condition that makes a pooled number untrustworthy."""
    problems = []
    counts = Counter(r["label"] for r in records)
    if len(set(counts.values())) > 1:
        problems.append(
            f"labels have unequal record counts {dict(counts)} — arms did not "
            f"cover the same deals, so a paired contrast is not paired")
    seen = defaultdict(list)
    for r in records:
        seen[(r["label"], r["seed"], r["flip"])].append(r["_src"])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        srcs = sorted({s for v in dupes.values() for s in v})
        problems.append(
            f"{len(dupes)} (label, seed, flip) keys appear more than once, "
            f"across {srcs} — an aborted or rerun shard is mixed in and its "
            f"seeds are double-counted")
    shas = {r["run"].split("_")[-1] for r in records}
    if len(shas) > 1:
        problems.append(f"shards ran at different commits {sorted(shas)}")
    # Older shards predate counters that were added later. A missing key is
    # not a zero — it means the record cannot attest to that invariant at all,
    # and mixing schemas is itself a reason to distrust a pooled number.
    stale = [r["_src"] for r in records if "zero_world" not in r.get("arm", {})]
    if stale:
        problems.append(
            f"{len(stale)} records from {sorted(set(stale))} predate the "
            f"zero-world counter, so they cannot attest that their searches "
            f"ran; they are from a different code generation than the rest")
    zw = sum(r["arm"].get("zero_world", 0) + r["opp"].get("zero_world", 0)
             for r in records)
    if zw:
        by = Counter()
        for r in records:
            z = r["arm"].get("zero_world", 0) + r["opp"].get("zero_world", 0)
            if z:
                by[r["label"]] += z
        problems.append(
            f"{zw} zero-world decisions ({dict(by)}) — the evaluator forces "
            f"NOT CONFIRMED on these runs, and exposure is unequal across "
            f"arms, so this contrast is provisional at best")
    return problems


def paired(records, a, b):
    by = {}
    for r in records:
        by.setdefault(r["label"], {}).setdefault(r["seed"], 0)
        by[r["label"]][r["seed"]] += r["level_utility"]
    if a not in by or b not in by:
        raise AggregationRefused(f"missing label {a!r} or {b!r}")
    seeds = sorted(set(by[a]) & set(by[b]))
    d = [by[a][s] - by[b][s] for s in seeds]
    n = len(d)
    if n < 2:
        return 0.0, float("inf"), n
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    return m, 1.96 * math.sqrt(var / n), n


def win_rate(records, label):
    v = [r["level_utility"] for r in records if r["label"] == label]
    return 100.0 * sum(1 for x in v if x > 0) / max(len(v), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="runs/logs/eval_*.jsonl")
    ap.add_argument("--policy", required=True)
    ap.add_argument("--lo", type=int, required=True)
    ap.add_argument("--hi", type=int, required=True)
    ap.add_argument("--contrast", action="append", default=[],
                    help="A:B, repeatable; A minus B paired by seed")
    ap.add_argument("--exclude-sha", action="append", default=[])
    ap.add_argument("--allow-problems", action="store_true",
                    help="report anyway, marked PROVISIONAL — never for a claim")
    args = ap.parse_args()

    recs = load_records(args.pattern, args.policy, args.lo, args.hi,
                        args.exclude_sha)
    if not recs:
        print("no records matched")
        sys.exit(2)
    srcs = sorted({r["_src"] for r in recs})
    print(f"{len(recs):,} records from {len(srcs)} shard files, "
          f"seeds {args.lo}-{args.hi}")
    print(f"  labels: {dict(Counter(r['label'] for r in recs))}")

    problems = check(recs)
    if problems:
        print("\nAGGREGATION PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        if not args.allow_problems:
            print("\nREFUSING to report a pooled number. Re-run with "
                  "--exclude-sha to drop an aborted shard, or --allow-problems "
                  "to print it marked PROVISIONAL.")
            sys.exit(3)
        print("\n*** PROVISIONAL — problems above are unresolved; this is not "
              "a confirmable result ***")

    print()
    for c in args.contrast or ["arm:reference"]:
        a, b = c.split(":")
        m, ci, n = paired(recs, a, b)
        verdict = "excludes 0" if abs(m) - ci > 0 else "INCLUDES 0"
        print(f"  {a} minus {b:12} {m:+.3f} +/- {ci:.3f}  n={n}  {verdict}")
    print()
    for lab in sorted({r["label"] for r in recs}):
        print(f"  win rate {lab:10} {win_rate(recs, lab):5.1f}%")
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
