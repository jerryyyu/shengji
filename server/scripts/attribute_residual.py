"""Where does the REMAINING sampler bias live — count-matrix marginal or cards?

Two named causes were measured. One contributes (`_splits` count-matrix
weighting, `-0.060 +/- 0.031`), one does not (`_deal_suit` first-legal,
`-0.0001 +/- 0.0027`), and repairing the reference explained only ~6%. Mean
excess TV against the repaired physical reference is still `0.046` on the best
arm. Something unnamed carries it.

The sampler makes exactly two kinds of decision, so the bias must be in one of
them:

  1. WHICH count matrix (how many cards of each suit go to each receiver);
  2. WHICH cards, given that matrix.

Splitting TV along that boundary says which to go fix, instead of guessing.
Grouping worlds by their (receiver, effective-suit) count vector gives the
marginal over decision 1; the conditional within a group is decision 2.

Effective suit comes from the round's own `Ordering`, not the card's letter —
trump-rank cards and jokers belong to the trump suit regardless of printed
suit, and grouping by letter would scatter one count matrix across several
groups and charge the difference to card choice. States are regenerated
deterministically for that mapping; the histograms are read from the stored run,
so nothing is resampled.

    uv run python scripts/attribute_residual.py runs/logs/post24_physfill.json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from certify_sampler import toy_states                       # noqa: E402
from reweight_posterior import physical_weight               # noqa: E402


def split_sig(key: tuple, eff) -> tuple:
    """(receiver, effective suit) -> count. The sampler's decision 1."""
    out = []
    for seat, cards in key[0]:
        c = Counter(eff(x) for x in cards)
        out.append((seat, tuple(sorted(c.items()))))
    if len(key) > 1:
        c = Counter(eff(x) for x in key[1])
        out.append(("kitty", tuple(sorted(c.items()))))
    return tuple(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    args = ap.parse_args()

    with open(args.run) as fh:
        d = json.load(fh)
    rows = {r["seed"]: r for r in d["rows"]}

    # Regenerate the same states for their Ordering. Sampler flags cannot
    # matter here (we only need eff_suit), but toy_states is deterministic so
    # the seeds line up with the recorded rows.
    order = {}
    for seed, rnd, seat in toy_states(len(rows) * 3):
        if seed in rows and seed not in order:
            order[seed] = rnd.ordering
        if len(order) == len(rows):
            break

    tot_m, tot_c, tot_t, n = 0.0, 0.0, 0.0, 0
    print(f"  {'seed':>8} {'TV':>7} {'split TV':>9} {'card TV':>8}   dominant")
    for seed, r in sorted(rows.items()):
        if seed not in order:
            continue
        eff = order[seed].eff_suit
        legal = [ast.literal_eval(k) for k in r["legal_keys"]]
        hist = {ast.literal_eval(k): v for k, v in r["sampled_hist"]}
        draws = sum(hist.values())

        w = {k: physical_weight(k) for k in legal}
        tot_w = sum(w.values())
        # Recompute TV against the PHYSICAL reference. The `tv` stored in the
        # raw run is against the flat multiset reference, and printing that
        # beside physical-reference components makes them look non-additive
        # (TV is subadditive across this split, so components below the total
        # would mean a bug). Seed 880001: 0.174 flat vs 0.015 physical.
        tv_total = 0.5 * sum(abs(hist.get(k, 0) / draws - w[k] / tot_w)
                             for k in legal)

        gref: dict = defaultdict(float)
        gemp: dict = defaultdict(float)
        wref: dict = defaultdict(dict)
        wemp: dict = defaultdict(dict)
        for k in legal:
            g = split_sig(k, eff)
            p = w[k] / tot_w
            gref[g] += p
            wref[g][k] = p
        for k, v in hist.items():
            if k not in w:
                continue           # off-support mass is charged to split TV
            g = split_sig(k, eff)
            gemp[g] += v / draws
            wemp[g][k] = v / draws

        # decision 1: marginal over count matrices
        tv_split = 0.5 * sum(abs(gemp.get(g, 0.0) - gref.get(g, 0.0))
                             for g in set(gref) | set(gemp))
        # decision 2: conditional within a matrix, weighted by reference mass
        tv_card = 0.0
        for g, p in gref.items():
            if gemp.get(g, 0.0) <= 0:
                continue
            me = gemp[g]
            inner = 0.5 * sum(
                abs(wemp[g].get(k, 0.0) / me - wref[g][k] / p)
                for k in wref[g])
            tv_card += p * inner
        dom = "SPLIT choice" if tv_split > tv_card else "CARD choice"
        print(f"  {seed:>8} {tv_total:>7.3f} {tv_split:>9.3f} {tv_card:>8.3f}"
              f"   {dom}")
        tot_m += tv_split
        tot_c += tv_card
        tot_t += tv_total
        n += 1
        if tv_total > tv_split + tv_card + 1e-9:
            # FAIL, do not narrate. A violation means the decomposition is
            # wrong, so every number printed above it is wrong too, and a
            # warning buried in a long table is indistinguishable from noise.
            print(f"REFUSING: subadditivity violated at {seed} "
                  f"({tv_total:.4f} > {tv_split:.4f} + {tv_card:.4f}). The "
                  "attribution is invalid; do not read the means.")
            sys.exit(3)

    if not n:
        print("no states matched")
        sys.exit(2)
    print(f"\n  mean TV {tot_t / n:.4f}"
          f"   mean split-choice TV {tot_m / n:.4f}"
          f"   mean card-choice TV {tot_c / n:.4f}")
    print("  These localise discrepancy to the EMITTED count-matrix marginal "
          "versus card choice given it. That is NOT the same as blaming "
          "`_splits`: a matrix can fail the capped fill up to 8 times and be "
          "redrawn, so `_deal_suit` success also reweights the emitted "
          "marginal (Codex). Component TVs are raw and noise-uncorrected, and "
          "TV is only subadditive across this split, so treat them as "
          "localisation, not an exact decomposition.")


if __name__ == "__main__":
    main()
