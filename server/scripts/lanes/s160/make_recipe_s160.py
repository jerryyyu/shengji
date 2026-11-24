#!/usr/bin/env python3
"""S160 recipe maker (PREDECLARE_S160.md) = claude-rt2-attrib/make_recipe_mix.py with this lane's root and inputs, the three
arms B4, U4, D4 (each with its own defender), the same schema utd-mix-recipe-r1 / duel UTX and the same mix adapter and reader.

usage (on the Ultra, cwd TREE/server, in s160_run.sh's producer environment PENV with UT_PKG / UT_SHA256 unset):
    make_recipe_s160.py OUT.json
It refuses unless every kit file equals the RT2-attrib kit's bytes and every package re-hashes to its pinned digest.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

BLOCK = ("rt4-attrib-dev-2666000000", 2666000000, 4000)
# arm: exploiter (package, belief, mode), defender (package, belief, mode), seed0, pilot_seed0, timing_seed0
ARMS = {
    "B4": (("R54", "RT4", "root"), ("R54", "R54", "shared"), 2666000000, 2666003000, 2666003060),
    "U4": (("RT4", "R54", "root"), ("R54", "R54", "shared"), 2666001000, 2666003020, 2666003070),
    "D4": (("RT4", "RT4", "shared"), ("RT2", "RT2", "shared"), 2666002000, 2666003040, 2666003080),
}
DEALS, PILOT_DEALS, TIMING_DEALS = 1000, 20, 6
PKG = {   # model: (unified file, unified sha256, belief file, belief sha256) under inputs/
    "R54": ("ut-all-97c07be8.npz", "97c07be8614ed5c42e47882ff2ad4e68ffb6f174d071f14469f1d0a96f5490af",
            "ut-all-belief-1b1fd2de.npz", "1b1fd2deb43b109bd4577af6ffdb98977ad90525de8914c6cbae20e0d5ac77f4"),
    "RT4": ("ut-rt4-e2951d35.npz", "e2951d35eeabd167347c3b5608a8065dffb9bd304b51aa4759eabbba1ce05883",
            "ut-rt4-belief-35e225cf.npz", "35e225cf3afd460d231a44192e60be8595a5d7fce81c860f0bfe3153506f66e3"),
    "RT2": ("ut-rt2-47175c99.npz", "47175c99c2d7d5f3eb0740d8ebaef838e122b151399c372ad1fae556b5a874f2",
            "ut-rt2-belief-bed32f87.npz", "bed32f87dc4dd6310d17b818a1a1e10e5e8cd808dd3cc63e301a014261459ce3"),
}
KIT = ("exploit_duel_s61.py", "hypotheses.py", "x1a_adapter.py", "ut_adapter.py", "probe_names.ut.py", "ut_read.py",
       "ut_h2h_adapter.py", "ut_h2h_read.py", "ut_mix_adapter.py", "ut_mix_read.py", "mix_pilot_check.py")
TREE_HEAD = "063bf4706bb93b39985fb309ae2165c8881b9015"


def arm_spans():
    """Every dealt span [lo, hi) by role; all lie inside BLOCK and none overlap (tested)."""
    out = []
    for arm, (_, _, seed0, pseed, tseed) in ARMS.items():
        out += [(arm, "duel", seed0, seed0 + DEALS), (arm, "pilot", pseed, pseed + PILOT_DEALS), (arm, "timing", tseed, tseed + TIMING_DEALS)]
    return out


def main(argv):
    out = argv[1]
    lane = Path(__file__).resolve().parent
    ref_kit = Path("/Users/jeryyu/fleet/claude-rt2-attrib/kit")
    tree = Path("/Users/jeryyu/fleet/claude-ut-retrain2/src")
    py = "/Users/jeryyu/Projects/shengji/server/.venv/bin/python"
    inp = lane / "inputs"

    def sha(p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    head = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(tree), "status", "--porcelain"], check=True, capture_output=True, text=True).stdout
    if head != TREE_HEAD or dirty:
        sys.exit(f"tree {tree} is at {head} (want {TREE_HEAD}) or dirty")
    for k in KIT:
        if sha(lane / "kit" / k) != sha(ref_kit / k):
            sys.exit(f"kit/{k} is not the RT2-attrib kit's bytes")
    for model, (u, us, b, bs) in PKG.items():
        if sha(inp / u) != us or sha(inp / b) != bs:
            sys.exit(f"{model} package bytes differ from the pins")
    spec = importlib.util.spec_from_file_location("ut_mix_read_words", str(lane / "kit/ut_mix_read.py"))
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)
    base = [f"SHENGJI_PV_CKPT={inp}/g3a-e04-f4f4127e.npz", "SHENGJI_PV_SHA256=f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd",
            f"SHENGJI_PV_PRIOR_CKPT={inp}/p0-ft1-1fa201b2.npz", "SHENGJI_PV_PRIOR_SHA256=1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf",
            f"SHENGJI_PV_BELIEF_CKPT={inp}/b1a-028131a0.npz", "SHENGJI_PV_BELIEF_SHA256=028131a03de0c69b5164cdd0f65369950340f58fe226f75d6d877aeda2ca8fc8",
            "SHENGJI_PV_BURY_BELIEF_WORLDS=1", "SHENGJI_PV_LEAD_CONFIRM=0"]
    env = {k: v for k, v in os.environ.items() if k not in ("UT_PKG", "UT_SHA256")}

    def side(pkg_model, bel_model, mode):
        p, b = str(inp / PKG[pkg_model][0]), str(inp / PKG[bel_model][2])
        return p, b, mode, rd.side_words(base, b, sha(b), p, sha(p), mode)

    arms = {}
    for arm, (ex, de, seed0, pseed, tseed) in ARMS.items():
        xp, xb, xm, xw = side(*ex)
        dp, db, dm, dw = side(*de)
        probe = subprocess.run([py, "-B", str(lane / "kit/probe_names.ut.py"), str(lane / "kit/ut_mix_adapter.py"), ",".join(dw), ",".join(xw)],
                               cwd=f"{tree}/server", env=env, check=True, capture_output=True, text=True)
        names = json.loads(probe.stdout.strip().splitlines()[-1])
        arms[arm] = {"defender_words": dw, "exploiter_words": xw, "defender_name": names[0], "exploiter_name": names[1],
                     "seed0": seed0, "deals": DEALS, "pilot_seed0": pseed, "timing_seed0": tseed,
                     "ut_package": None, "ut_package_sha256": None, "ex_mode": xm, "def_mode": dm,
                     "ex_label": f"{ex[0]} unified + {ex[1]} belief", "def_label": f"{de[0]} unified + {de[1]} belief",
                     "ex_package": xp, "ex_package_sha256": sha(xp), "ex_belief": xb, "ex_belief_sha256": sha(xb),
                     "def_package": dp, "def_package_sha256": sha(dp), "def_belief": db, "def_belief_sha256": sha(db),
                     "out_root": str(lane / "out" / arm), "status": str(lane / f"{arm}.status"),
                     "pins": {q: sha(q) for q in (xp, xb, dp, db)}}
    pins = [inp / "g3a-e04-f4f4127e.npz", inp / "p0-ft1-1fa201b2.npz", inp / "b1a-028131a0.npz"] + [lane / "kit" / k for k in KIT] + \
           [lane / "s160_run.sh", tree / "fly.toml", tree / "server/shengji/train/unified_slots.py", tree / "server/shengji/train/unified_readout.py",
            tree / "server/shengji/ai/unified_readout_numpy.py", tree / "server/shengji/ai/unified_numpy.py", tree / "server/shengji/ai/belief_numpy.py",
            tree / "server/shengji/train/pv_search_policy.py", tree / "server/scripts/expert_labels/validity.py"] + sorted((tree / "server/shengji").rglob("*.so"))
    rc = {"schema": "utd-mix-recipe-r1", "duel": "UTX", "lane": "S160", "block": list(BLOCK),
          "predeclare_sha256": sha(lane / "PREDECLARE_S160.md"), "round_plan": "r2", "tree": str(tree), "tree_head": head, "arms": arms,
          "r52_words": base, "reader": str(lane / "kit/ut_mix_read.py"), "reader_sha256": sha(lane / "kit/ut_mix_read.py"),
          "pins": {str(p): sha(p) for p in pins}}
    Path(out).write_text(json.dumps(rc, indent=1, sort_keys=True) + "\n")
    print(sha(out), rc["reader_sha256"], json.dumps({a: [v["defender_name"][-60:], v["exploiter_name"][-60:]] for a, v in arms.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
