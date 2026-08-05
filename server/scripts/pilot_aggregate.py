"""Aggregate a pilot run into paired contrasts clustered by deal.

The runner deliberately prints per-state means and calls them descriptive. This
is the file that produces an experiment number, and it treats one STATE as one
cluster — the pilot set is one state per deal, so states are independent and
`states x worlds` is not. Pooling worlds as observations would understate the
interval by roughly sqrt(n_worlds), which is the same correlated-cluster error
that killed six strength claims.

Contrasts, in the order they matter:

  * **quota minus random_fill** is PRIMARY. Beating `current` only shows a
    differently shaped ballot helps; beating random fill AT THE SAME BUDGET is
    the selector's actual claim. V3 is the precedent — it widened exactly where
    the coverage audit pointed and its random-fill control scored higher.
  * **quota minus current** is necessary but not sufficient: an arm that beats
    random fill while losing to the deployed ballot has earned nothing.
  * **mc_more minus current** asks whether spending the same work on more
    worlds over the OLD ballot does as well. If it does, the simpler bot wins.
  * `full_universe` is reported but is not a control — it has more compute by
    design and answers "what is reachable", not "is selection working".

Refuses to report when the run recorded work-band violations or replay errors:
a number computed over a run that failed its own invariants is not evidence.

    uv run python scripts/pilot_aggregate.py runs/logs/pilot_smoke.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys

PRIMARY = ("quota", "random_fill")
SECONDARY = [("quota", "current"), ("mc_more", "current"),
             ("random_fill", "current"), ("full_universe", "current")]


def paired(records, a, b, field="regret"):
    """Mean per-STATE difference with a clustered interval.

    Lower regret is better, so the difference is reported as `b - a`: positive
    means `a` has LESS regret than `b`, i.e. `a` is better.
    """
    d = [r["arms"][b][field] - r["arms"][a][field] for r in records
         if a in r["arms"] and b in r["arms"]]
    n = len(d)
    if n < 2:
        return 0.0, float("inf"), n
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    return m, 1.96 * math.sqrt(var / n), n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--allow-failed-run", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.run))
    recs = data["records"]
    problems = []
    if data.get("work_violations"):
        problems.append(f"{len(data['work_violations'])} work-band violations")
    if data.get("replay_errors"):
        problems.append(f"{data['replay_errors']} replay errors")
    if data.get("tree_dirty"):
        problems.append("tree was DIRTY: the git SHA does not describe the run")
    if problems and not args.allow_failed_run:
        print("REFUSING to aggregate a run that failed its own invariants:")
        for p in problems:
            print(f"  - {p}")
        print("A number computed over such a run is not evidence.")
        sys.exit(3)

    seen = {r["state"] for r in recs}
    if len(seen) != len(recs):
        print(f"REFUSING: {len(recs)} records over {len(seen)} distinct states "
              f"— a repeated state is a repeated cluster.")
        sys.exit(3)

    print(f"run {data['git']}  states {len(recs)}  ballot {data['ballot']}")
    print(f"work target {data['work_target']} +/- {data['band']*100:.0f}%\n")
    print(f"{'contrast':34} {'diff':>9} {'95% CI':>10}  n   verdict")

    a, b = PRIMARY
    m, ci, n = paired(recs, a, b)
    verdict = ("FAVOURS " + a if m - ci > 0 else
               "FAVOURS " + b if m + ci < 0 else "INCLUDES 0")
    print(f"{'PRIMARY  ' + a + ' - ' + b:34} {m:+9.3f} {ci:10.3f} {n:3d}  {verdict}")
    for x, y in SECONDARY:
        m, ci, n = paired(recs, x, y)
        v = ("favours " + x if m - ci > 0 else
             "favours " + y if m + ci < 0 else "includes 0")
        print(f"{'  ' + x + ' - ' + y:34} {m:+9.3f} {ci:10.3f} {n:3d}  {v}")

    print(f"\n{'arm':16} {'mean regret':>12} {'oracle match':>13} "
          f"{'mean work':>10}")
    for arm in sorted(recs[0]["arms"]):
        rs = [r["arms"][arm]["regret"] for r in recs]
        mo = [r["arms"][arm]["matched_oracle"] for r in recs]
        wk = [r["arms"][arm]["work"] for r in recs]
        print(f"{arm:16} {sum(rs)/len(rs):12.3f} "
              f"{100*sum(mo)/len(mo):12.1f}% {sum(wk)/len(wk):10.0f}")

    print("\nOne STATE is one cluster; the pilot set is one state per deal. "
          "Worlds are NOT observations.")
    print("Diagnostic only, never a gate: oracle-best recall. Coverage-flavoured "
          "statistics have been measured and known insufficient twice.")


if __name__ == "__main__":
    main()
