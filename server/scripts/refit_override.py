"""EXPERIMENT: refit the override's decision rule against UNBIASED labels.

The high-N reference showed v11's failure is calibration, not knowledge: it
picks the 240-world best MORE often than deployed mc (29.7% vs 23.6%) while
carrying WORSE mean regret (3.025 vs 2.803). Its hits are as good as a 30-world
search; its misses cost more. The net's scores are therefore worth keeping —
it is the DECISION RULE wrapped around them that is wrong.

The deployed rule is a single margin: override candidate 0 when the predicted
gain exceeds 0.02 (a threshold that was itself fitted on the teacher's own
biased estimates). Here it is refitted against the high-N reference, which is
the first label set in this project that is stronger than the incumbent.

Discipline, because a threshold fitted and reported on the same states proves
nothing:
  * states are split by SEED into halves A and B;
  * every rule is fitted on A only;
  * every number reported comes from B, which no fitting touched.

Rules compared:
  * margin       — the deployed shape, refitted
  * margin+cands — allow the bar to depend on how many candidates exist, since
    a fixed bar means something different among 3 candidates than among 14
  * top2gap      — override only when the net separates its top two choices,
    i.e. when it is confident about WHICH alternative, not merely that one exists

    uv run python scripts/refit_override.py [file]
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")


def load(path):
    return [json.loads(l) for l in open(path)]


def net_scores(rec, net):
    """The net's predicted gain per candidate, in the record's order."""
    import random

    from scripts.highn_analyze import rebuild
    from shengji.rl.encode import encode_action, encode_obs

    rnd, seat = rebuild(rec)
    obs = encode_obs(rnd, seat)
    enc = [encode_action(list(c), rnd) for c in rec["candidates"]]
    d = net.value_candidates(obs, enc)
    del random
    return [float(x) - float(d[0]) for x in d]


def regret_of(rec, idx):
    return max(rec["mean"]) - rec["mean"][idx]


def apply_rule(rec, gains, rule, thr):
    """Index of the chosen candidate under `rule`."""
    k = len(gains)
    j = max(range(k), key=lambda i: gains[i])
    if rule == "margin":
        return j if gains[j] > thr else 0
    if rule == "margin+cands":
        # Scale the bar with the ballot size: a fixed bar is a different
        # standard of evidence among 3 candidates than among 14.
        return j if gains[j] > thr * (k / 6.0) else 0
    if rule == "top2gap":
        rest = sorted(gains[1:], reverse=True)
        sep = rest[0] - (rest[1] if len(rest) > 1 else 0.0)
        return j if gains[j] > 0 and sep > thr else 0
    raise ValueError(rule)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "rl_data/highn_diag.jsonl"
    recs = load(path)
    from shengji.rl.npnet import NpNet
    net = NpNet("snapshots_v11pair/ep07.npz")

    scored = []
    for r in recs:
        try:
            scored.append((r, net_scores(r, net)))
        except Exception:
            continue
    A = [(r, g) for r, g in scored if r["seed"] % 2 == 0]
    B = [(r, g) for r, g in scored if r["seed"] % 2 == 1]
    sigA = [(r, g) for r, g in A if r["significant"]]
    sigB = [(r, g) for r, g in B if r["significant"]]
    print(f"{len(scored)} states rebuilt: fit on {len(A)} (A, {len(sigA)} "
          f"significant), report on {len(B)} (B, {len(sigB)} significant)\n")

    grids = {"margin": [0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.3],
             "margin+cands": [0.0, 0.005, 0.01, 0.02, 0.04, 0.08, 0.15, 0.3],
             "top2gap": [0.0, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1]}

    best = {}
    for rule, grid in grids.items():
        scores = []
        for thr in grid:
            reg = sum(regret_of(r, apply_rule(r, g, rule, thr))
                      for r, g in sigA) / max(len(sigA), 1)
            scores.append((reg, thr))
        scores.sort()
        best[rule] = scores[0][1]
        print(f"  {rule:14} fitted thr={scores[0][1]:<6g} (A regret "
              f"{scores[0][0]:.3f})")

    print("\nREPORTED ON B — states never used for fitting:")
    print(f"  {'rule':22} {'mean regret':>12} {'picks best':>12}")
    baseline = sum(regret_of(r, 0) for r, _ in sigB) / max(len(sigB), 1)
    print(f"  {'keep candidate 0':22} {baseline:12.3f} {0.0:11.1f}%")
    deployed = sum(regret_of(r, apply_rule(r, g, "margin", 0.02))
                   for r, g in sigB) / max(len(sigB), 1)
    dep_best = 100 * sum(apply_rule(r, g, "margin", 0.02) == r["best"]
                         for r, g in sigB) / max(len(sigB), 1)
    print(f"  {'v11 @0.02 (deployed)':22} {deployed:12.3f} {dep_best:11.1f}%")
    for rule in grids:
        thr = best[rule]
        reg = sum(regret_of(r, apply_rule(r, g, rule, thr))
                  for r, g in sigB) / max(len(sigB), 1)
        hit = 100 * sum(apply_rule(r, g, rule, thr) == r["best"]
                        for r, g in sigB) / max(len(sigB), 1)
        flag = "  <-- beats deployed" if reg < deployed else ""
        print(f"  {rule + ' @' + f'{thr:g}':22} {reg:12.3f} {hit:11.1f}%{flag}")

    # The significant subset is selected BY the reference as states where
    # candidate 0 is provably beatable — a selection that FAVOURS overriding.
    # The deployment question is regret over EVERY decision, so report both.
    print("\n  --- same rules over ALL of B, not just the significant states "
          "(this is what a game actually faces) ---")
    allbase = sum(regret_of(r, 0) for r, _ in B) / max(len(B), 1)
    alldep = sum(regret_of(r, apply_rule(r, g, "margin", 0.02))
                 for r, g in B) / max(len(B), 1)
    print(f"  {'keep candidate 0':22} {allbase:12.3f}")
    print(f"  {'v11 @0.02 (deployed)':22} {alldep:12.3f}")
    for rule in grids:
        thr = best[rule]
        reg = sum(regret_of(r, apply_rule(r, g, rule, thr))
                  for r, g in B) / max(len(B), 1)
        print(f"  {rule + ' @' + f'{thr:g}':22} {reg:12.3f}"
              + ("  <-- beats deployed" if reg < alldep else ""))
    # And refit on ALL of A rather than its significant subset, since that is
    # the objective a deployed rule actually optimises.
    print("\n  --- refitted on ALL of A, reported on ALL of B ---")
    for rule, grid in grids.items():
        fitted = min(grid, key=lambda t: sum(
            regret_of(r, apply_rule(r, g, rule, t)) for r, g in A))
        reg = sum(regret_of(r, apply_rule(r, g, rule, fitted))
                  for r, g in B) / max(len(B), 1)
        print(f"  {rule + ' @' + f'{fitted:g}':22} {reg:12.3f}"
              + ("  <-- beats deployed" if reg < alldep else ""))

    print("\nFor scale, measured on the SAME reference (all states, both "
          "halves): mc N=10 regret 2.803, mc N=30 2.419.")
    print("A rule that lands below 2.803 on B is choosing better than the "
          "DEPLOYED search on the states where it matters — at 0.25ms.")


if __name__ == "__main__":
    main()
