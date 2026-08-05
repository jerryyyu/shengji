"""How far is the enumerable probe population from the DEV-512 scored population?

Every posterior and decision-sensitivity number is measured on states small
enough to enumerate every legal world. The pilot scores deep LEAD states. If
those two populations differ sharply, a clean result on the first says little
about the second — and the gap is measurable rather than a matter of opinion.

This does NOT turn an endgame screen into deep-lead evidence (Codex). It bounds
how much transfer to claim, which is the only honest use of it.

Compared on the axes that plausibly drive both enumerability and decision
difficulty: hidden cards remaining, candidate count, ply/trick index, and role
balance. Hidden-card count is the load-bearing one — it sets the size of the
world space, so it is exactly what makes a state enumerable and exactly what
makes a determinized search hard.

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \\
    uv run python scripts/representativeness.py
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from certify_sampler import constraints, enumerate_legal, toy_states  # noqa: E402
from shengji.ai.mcbot import MCBot                                    # noqa: E402


def summarise(name, vals):
    if not vals:
        return f"  {name:22} (none)"
    vals = sorted(vals)
    return (f"  {name:22} n={len(vals):4d}  min {vals[0]:5.1f}  "
            f"median {st.median(vals):6.1f}  mean {st.fmean(vals):6.2f}  "
            f"max {vals[-1]:5.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="rl_data/pilot_dev512.v3.json")
    ap.add_argument("--scan", type=int, default=120,
                    help="toy states to scan for the probe population")
    ap.add_argument("--max-worlds", type=int, default=2000)
    ap.add_argument("--out", default="runs/logs/representativeness.json")
    args = ap.parse_args()

    with open(args.dev) as fh:
        dev = json.load(fh)
    dev_rows = dev["requested"] if isinstance(dev.get("requested"), list) else None
    if dev_rows is None:
        for v in dev.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) \
                    and "n_candidates" in v[0]:
                dev_rows = v
                break
    if not dev_rows:
        print("REFUSING: could not locate DEV rows; schema changed.")
        sys.exit(3)

    bot = MCBot(seed=4242)
    probe = {"cands": [], "hidden": [], "ply": [], "worlds": [], "roles": []}
    live = degen = 0
    for seed, rnd, seat in toy_states(args.scan):
        try:
            legal = enumerate_legal(rnd, seat, constraints(rnd))
        except RuntimeError:
            continue
        if not legal or len(legal) > args.max_worlds:
            continue
        cands = bot._candidates(rnd, seat)
        if len(cands) < 2:
            continue
        hidden = sum(len(h) for s, h in enumerate(rnd.hands) if s != seat)
        probe["cands"].append(len(cands))
        probe["hidden"].append(hidden)
        probe["worlds"].append(len(legal))
        #  does not exist;  returned empty and
        # printed ply 0 for every state, which cannot be true of a state with
        # 3-7 hidden cards. Read the real attribute and FAIL if it is missing,
        # rather than defaulting to a value that looks like data.
        if not hasattr(rnd, "history"):
            raise AttributeError("Round has no history; ply cannot be read")
        probe["ply"].append(len(rnd.history))
        probe["roles"].append("attacker" if rnd.is_attacker(seat) else "defender")
        live += 1
    degen = live  # census of usable probe states; degeneracy counted elsewhere

    dev_c = [r["n_candidates"] for r in dev_rows if "n_candidates" in r]
    dev_p = [r["ply"] for r in dev_rows if "ply" in r]
    dev_roles = [r.get("role", "?") for r in dev_rows]

    print("=== PROBE population (enumerable toy states) ===")
    print(summarise("candidates", probe["cands"]))
    print(summarise("hidden cards", probe["hidden"]))
    print(summarise("legal worlds", probe["worlds"]))
    print(summarise("ply", probe["ply"]))
    print(f"  roles: {
        {r: probe['roles'].count(r) for r in set(probe['roles'])} }")
    print("\n=== DEV-512 population (what the pilot actually scores) ===")
    print(summarise("candidates", dev_c))
    print(summarise("ply", dev_p))
    print(f"  roles: { {r: dev_roles.count(r) for r in set(dev_roles)} }")

    gap = {}
    if probe["cands"] and dev_c:
        gap["candidates_median"] = st.median(dev_c) - st.median(probe["cands"])
    if probe["ply"] and dev_p:
        gap["ply_median"] = st.median(dev_p) - st.median(probe["ply"])
    print("\n=== TRANSFER GAP (DEV minus probe) ===")
    for k, v in gap.items():
        print(f"  {k:22} {v:+.1f}")
    print("\n  Hidden-card count is the axis that matters most: it sets the "
          "world-space size, so it is simultaneously what makes a state "
          "enumerable and what makes determinized search hard. The DEV set "
          "does not record it, so the comparison above is on the axes both "
          "populations expose; that is itself a limit of this table.")
    print("  This BOUNDS transfer. It cannot supply deep-lead decision "
          "evidence, which needs an exact reference nobody can build there.")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"probe_states": live, "probe": probe,
                   "dev_candidates": dev_c, "dev_ply": dev_p,
                   "gap": gap}, fh, indent=1)
    print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()
