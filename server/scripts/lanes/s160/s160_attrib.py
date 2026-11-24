#!/usr/bin/env python3
"""S160 attribution (PREDECLARE_S160.md "Bar"): the label from the sealed arm reads, computed once.

    s160_attrib.py --recipe RECIPE.json --readout DIR --ref-joint R4H.read.json --out ATTRIB.json

It refuses (rc 2, no output) unless B4 and U4 are VALID ``utx-read-r1`` reads of this recipe by the recipe's reader, the joint
reference is the pinned R4H read, and --out does not exist.  D4 is not an input: its own read reports it.  The bar: a slot
carries iff its swap arm's paired mean >= CARRY_SHARE x J and its LB80 > 0, with J the R4H all-deal mean.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

SCHEMA = "s160-attrib-r1"
CARRY_SHARE = 0.6
JOINT_REF_SHA256 = "ffe2b98624bd97aae59a71782a3e43b433ea65482c774cc2be402dba4155277b"
JOINT_MEAN = 0.06887755102040816
R2H_MEAN = 0.0285
SLOTS = {"B4": "belief", "U4": "heads"}
LABELS = {(True, False): "BELIEF-CARRIES", (False, True): "HEADS-CARRY", (True, True): "BOTH-CARRY", (False, False): "NEITHER-CARRIES"}


class Refusal(Exception):
    pass


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def carries(levels: dict, joint: float) -> bool:
    """The predeclared slot bar on one arm's paired levels/round summary."""
    return levels["mean"] >= CARRY_SHARE * joint and levels["lb80"] > 0


def se_from_ci(levels: dict) -> float:
    """Normal-approximation standard error from the 95% bootstrap interval (descriptive use only)."""
    lo, hi = levels["ci95"]
    return (hi - lo) / (2 * 1.959964)


def attribute(b4: dict, u4: dict, joint: float) -> dict:
    """The label and the descriptive figures from the B4 and U4 levels summaries."""
    cb, cu = carries(b4, joint), carries(u4, joint)
    inter = joint - b4["mean"] - u4["mean"]
    res = dict(label=LABELS[(cb, cu)], joint=joint, threshold=CARRY_SHARE * joint,
               slots={"belief": dict(arm="B4", carries=cb, share=b4["mean"] / joint, **{k: b4[k] for k in ("n", "mean", "ci95", "lb80")}),
                      "heads": dict(arm="U4", carries=cu, share=u4["mean"] / joint, **{k: u4[k] for k in ("n", "mean", "ci95", "lb80")})},
               interaction=dict(point=inter, se_swaps_only=math.hypot(se_from_ci(b4), se_from_ci(u4)), note="J - B4 - U4; descriptive"),
               next_retrain="no change" if not (cb or cu) else "see label",
               context=dict(r4h_minus_r2h=JOINT_MEAN - R2H_MEAN, note="beside D4 (RT4 - RT2); descriptive"))
    return res


def load_read(path: Path, arm: str, recipe_sha: str, reader_sha: str) -> dict:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refusal(f"{path}: {type(exc).__name__}") from None
    v = d.get("validity") if isinstance(d.get("validity"), dict) else {}
    b = d.get("binding") if isinstance(d.get("binding"), dict) else {}
    bad = [m for ok, m in ((d.get("schema") == "utx-read-r1", "schema"), (d.get("arm") == arm, "arm"), (d.get("duel") == "UTX", "duel"),
                           (d.get("reader_sha256") == reader_sha, "reader"), (b.get("recipe_sha256") == recipe_sha, "recipe"),
                           (v.get("verdict") == "VALID", "validity"),
                           (isinstance(d.get("outcome"), dict) and isinstance(d["outcome"].get("levels"), dict), "outcome")) if not ok]
    if bad:
        raise Refusal(f"{path} is not a VALID read of arm {arm} of this recipe: {bad}")
    return d["outcome"]["levels"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True); ap.add_argument("--readout", required=True)
    ap.add_argument("--ref-joint", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        if os.path.exists(a.out):
            raise Refusal(f"{a.out} exists; the attribution runs once")
        rc = json.loads(Path(a.recipe).read_text())
        if rc.get("schema") != "utd-mix-recipe-r1" or rc.get("lane") != "S160":
            raise Refusal("not an S160 recipe")
        if sha(a.ref_joint) != JOINT_REF_SHA256:
            raise Refusal("the joint reference is not the pinned R4H read")
        joint = json.loads(Path(a.ref_joint).read_text())["outcome"]["all"]["levels"]["mean"]
        if joint != JOINT_MEAN:
            raise Refusal(f"R4H all-deal mean {joint} is not the predeclared {JOINT_MEAN}")
        rsha, dsha = sha(a.recipe), rc["reader_sha256"]
        lv = {arm: load_read(Path(a.readout, f"{arm}.read.json"), arm, rsha, dsha) for arm in ("B4", "U4")}
    except Refusal as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    res = dict(schema=SCHEMA, attrib_sha256=sha(__file__), recipe_sha256=rsha, predeclare_sha256=rc.get("predeclare_sha256"),
               reads={arm: sha(Path(a.readout, f"{arm}.read.json")) for arm in ("B4", "U4")},
               **attribute(lv["B4"], lv["U4"], joint))
    with open(a.out, "x") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps(dict(label=res["label"], threshold=res["threshold"], belief=res["slots"]["belief"]["mean"],
                          heads=res["slots"]["heads"]["mean"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
