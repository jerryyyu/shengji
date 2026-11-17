"""RD1 step 0 reader: the predeclared bar on rd1_probe.py rows.

Usage: python rd1_read.py <expected_deals> <rows.jsonl> [<rows.jsonl> ...]
Bar: PASS iff median over seat-rounds of eligible decisions >= 1 AND median over eligible decisions of
the best-alternative Delta >= 0.5 nats.  Prints one JSON object.
"""
from __future__ import annotations

import json
import sys

import numpy as np


def deltas(e):
    """Per alternative a != c*: (Delta, partner term, opponent term)."""
    seat = e["seat"]
    p, o1, o2 = str((seat + 2) % 4), str((seat + 1) % 4), str((seat + 3) % 4)
    cands = e["cands"]
    chosen = next(c for c in cands if c["cards"] == e["chosen"])
    out = []
    for c in cands:
        if c["cards"] == e["chosen"]:
            continue
        part = chosen["nll"][p] - c["nll"][p]
        opp = ((chosen["nll"][o1] - c["nll"][o1]) + (chosen["nll"][o2] - c["nll"][o2])) / 2
        out.append((part - opp, part, opp))
    return out


def q(a, ps=(10, 25, 50, 75, 90)):
    return {f"p{p}": round(float(np.percentile(a, p)), 4) for p in ps} if len(a) else {}


def main(argv):
    expected = int(argv[0])
    rows = [json.loads(l) for f in argv[1:] for l in open(f)]
    errs = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    seeds = sorted(r["deal_seed"] for r in rows)
    assert len(set(seeds)) == len(seeds), "duplicate deals"
    counts, best, best_part, best_opp, groups, deal_of = [], [], [], [], {}, []
    chosen_in_near = 0
    for r in rows:
        per_seat = [0, 0, 0, 0]
        for e in r["decisions"]:
            if "cands" not in e:
                continue
            per_seat[e["seat"]] += 1
            ds = deltas(e)
            k = int(np.argmax([d[0] for d in ds]))
            best.append(ds[k][0])
            best_part.append(max(d[1] for d in ds))
            best_opp.append(ds[k][2])
            deal_of.append(r["deal_seed"])
            chosen_in_near += int(any(c["cards"] == e["chosen"] and c["v"] is not None for c in e["cands"]))
            for key in (("lead" if e["lead"] else "follow"), ("banker_team" if e["team_banker"] else "defenders"),
                        f"trick{e['trick'] + 1}"):
                groups.setdefault(key, []).append(ds[k][0])
        counts.extend(per_seat)
    best = np.asarray(best)
    med_count = float(np.median(counts)) if counts else 0.0
    med_best = float(np.median(best)) if len(best) else float("nan")
    # deal-cluster bootstrap of the median best-alternative Delta (descriptive)
    rng = np.random.default_rng(1)
    by_deal = {}
    for s, v in zip(deal_of, best):
        by_deal.setdefault(s, []).append(v)
    keys = list(by_deal)
    boots = []
    for _ in range(2000):
        pick = rng.integers(0, len(keys), len(keys))
        boots.append(np.median(np.concatenate([by_deal[keys[i]] for i in pick])))
    res = {
        "deals_ok": len(rows), "deals_error": len(errs), "deals_expected": expected,
        "seat_rounds": len(counts), "eligible_decisions": int(len(best)),
        "eligible_per_seat_round": {"median": med_count, "mean": round(float(np.mean(counts)), 3),
                                    "frac_zero": round(float(np.mean(np.asarray(counts) == 0)), 3)},
        "best_alt_delta_nats": {"median": round(med_best, 4), "mean": round(float(best.mean()), 4),
                                "boot95_median": [round(float(np.percentile(boots, 2.5)), 4),
                                                  round(float(np.percentile(boots, 97.5)), 4)],
                                "frac_ge_0.5": round(float(np.mean(best >= 0.5)), 4),
                                "frac_gt_0": round(float(np.mean(best > 0)), 4), **q(best)},
        "partner_only_best_gain_nats": {"median": round(float(np.median(best_part)), 4), **q(best_part)},
        "opp_term_at_best": {"median": round(float(np.median(best_opp)), 4)},
        "chosen_in_near_set_frac": round(chosen_in_near / max(1, len(best)), 4),
        "groups_median_best_delta": {k: {"n": len(v), "median": round(float(np.median(v)), 4),
                                         "frac_ge_0.5": round(float(np.mean(np.asarray(v) >= 0.5)), 4)}
                                     for k, v in sorted(groups.items())},
    }
    ok = len(rows) == expected and not errs
    res["valid"] = ok
    res["bar"] = {"eligible_median_ge_1": med_count >= 1, "median_best_delta_ge_0.5": med_best >= 0.5}
    res["verdict"] = ("PASS" if all(res["bar"].values()) else "FAIL") if ok else "INVALID"
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
