"""Post-inference DEV marginal scoring; hidden truth never goes to the models.

Report per-position multiclass Brier against the actual retained hands. The
N256 empirical reference is debiased; a noisier finite reference must not give
a deterministic model free apparent lift. Not a joint-world likelihood score.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .cwv_bury_diagnostic import reopen_state
from .r4_w32_weight_diagnostic import cell_count
from .search_screen import _publish


def brier(probabilities, target):
    return sum((p-int(i == target))**2 for i,p in enumerate(probabilities))


def debiased_reference_brier(counts, target):
    n = sum(counts)
    if n < 2:
        raise ValueError("Brier debiasing needs at least two worlds")
    probabilities = [c/n for c in counts]
    return brier(probabilities, target)-sum(p*(1-p)/(n-1) for p in probabilities)


def score_position(root):
    capture = json.loads((root/"private-world-values.json").read_bytes())
    prediction = json.loads((root/"r4-marginals.json").read_bytes())
    if capture["actor_sha256"] != prediction["actor_sha256"]:
        raise ValueError("model/position differs")
    raw = Path(capture["record_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != capture["record_sha256"]:
        raise ValueError("retained trajectory changed")
    row = json.loads(raw)
    rnd = reopen_state(row["state"])
    rnd.bury(rnd.banker, row["buried"])
    for play in row["transcript"][:capture["decision"]]:
        rnd.play(play["seat"], play["attempted"])
    world = (rnd.hands, rnd.buried)
    scores = {}
    for name, arm in prediction["arms"].items():
        losses, refs, raw_refs = [], [], []
        for cell in arm["ownership"]["count_probabilities"]:
            card, receiver = cell["card"], cell["receiver"]
            target = cell_count(world, rnd.turn, card, receiver)
            counts = Counter(cell_count(w, rnd.turn, card, receiver) for w in capture["reference_worlds"])
            counts = [counts[i] for i in range(3)]
            if sum(counts) != 256:
                raise ValueError("reference is not N256")
            losses.append(brier([p/1e9 for p in cell["count_probability_ppb"]], target))
            refs.append(debiased_reference_brier(counts, target))
            raw_refs.append(brier([c/256 for c in counts], target))
        scores[name] = {"brier": sum(losses)/len(losses), "reference_brier_debiased": sum(refs)/len(refs),
                        "reference_brier_raw": sum(raw_refs)/len(raw_refs), "cells": len(losses)}
    return {"index": row["state"]["index"], "decision": capture["decision"], "scores": scores}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    args = parser.parse_args(argv)
    plan = json.loads((args.panel/"plan.json").read_bytes())
    rows = [score_position(Path(plan["reuse_first"]) if i == 0 and plan["reuse_first"] else
                           args.panel/f"position-{i:02d}") for i in plan["indices"]]
    result = {"independent_deals": len(rows), "decision": plan["decision"], "positions": rows,
              "scope": "already-open DEV, equal weight per position; not held-out strength",
              "means": {arm: {k: sum(r["scores"][arm][k] for r in rows)/len(rows)
                               for k in ("brier", "reference_brier_debiased", "reference_brier_raw")}
                        for arm in rows[0]["scores"]}}
    target = args.panel/"proper-scores.json"
    if not target.exists():
        _publish(target, result)
    print(json.dumps({k:v for k,v in result.items() if k != "positions"}, indent=2))


if __name__ == "__main__":
    main()
