"""Capture deep LEAD states, to Codex's preregistration.

The corpus cannot supply a balanced broad-lead gate: only 3 DEV deals hold any
lead state at trick index >= 12, because the late supplement's depth is in
PLIES and most of its deep rows are follows. So the states are captured rather
than mined.

**The cell structure is fixed in advance and filled exactly.**

    768 accepted states, one per deal
      = 3 splits (DEV / CALIB / REPORT)
      x 8 exact trick indices (12..19)
      x 2 leader roles (attacker / defender)
      x 16 states per cell

**Split and target trick are derived from a named hash stream BEFORE the deal
is played.** That is the whole point: choosing them afterwards would let the
capture prefer deals that happened to reach a convenient depth, and the depth
distribution is exactly what is being controlled. If a deal does not reach its
assigned target with the required leader role, it is REJECTED and counted —
never substituted with an easier depth.

Raw setup and history only. No candidate values, no worlds, no arm scores;
REPORT is frozen at capture and must stay untouched until a design and its
gate are locked.

Fail-closed: refuses a dirty tree, requires strict void-respecting sampling,
and stops at a predeclared maximum seed rather than running until the cells
happen to fill.

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \\
    uv run python scripts/capture_deep_leads.py --max-seeds 40000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.registry import make_bot          # noqa: E402
from shengji.engine.game import Game              # noqa: E402

SPLITS = ("dev", "calib", "report")
TRICKS = tuple(range(12, 20))          # exact trick indices
ROLES = ("attacker", "defender")
PER_CELL = 16                          # 3 x 8 x 2 x 16 = 768


def cell_targets(seed: int, salt: str):
    """(split, target trick) for a deal, decided BEFORE it is played.

    Hash-derived so the assignment cannot drift with what the deal turns out to
    contain. The leader ROLE is not assigned — it is whatever the deal produces
    at that trick — so role cells fill by rejection, not by steering.
    """
    h = hashlib.sha256(f"{salt}|deal|{seed}".encode()).digest()
    split = SPLITS[h[0] % len(SPLITS)]
    trick = TRICKS[h[1] % len(TRICKS)]
    return split, trick


def play_to_trick(seed: int, target: int, bot_name: str):
    """Self-play a deal to the START of `target`, returning the lead state.

    Returns None if the round ends first — that deal is rejected, not retried
    at a shallower depth.
    """
    game = Game(random.Random(seed))
    rnd = game.start_round()
    # deterministic per-seat RNGs, distinct per seat and per deal
    pol = [make_bot(bot_name, seed=seed * 4 + s) for s in range(4)]
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        cs = pol[s].decide_declare(rnd, s)
        if cs:
            rnd.declare(s, cs)
    for s in range(4):
        cs = pol[s].decide_declare(rnd, s, final=True)
        if cs:
            rnd.declare(s, cs)
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = pol[rnd.banker].decide_bury(rnd, rnd.banker)
    setup = {"deck": list(rnd.deck), "banker": rnd.banker,
             "trump_rank": rnd.trump_rank, "buried": list(buried)}
    rnd.bury(rnd.banker, buried)
    plays: list[dict] = []
    while rnd.phase == "play":
        if len(rnd.history) == target and rnd.trick is not None \
                and not rnd.trick.plays:
            seat = rnd.turn
            return rnd, seat, setup, plays, pol
        s = rnd.turn
        if s is None:
            break
        cards = pol[s].decide_play(rnd, s)
        rnd.play(s, list(cards))
        plays.append({"seat": s, "cards": list(cards)})
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed0", type=int, default=92_000_000)
    ap.add_argument("--max-seeds", type=int, default=60_000,
                    help="PREDECLARED ceiling; the run fails closed here "
                         "rather than searching until the cells fill")
    ap.add_argument("--bot", default="mc-strong")
    ap.add_argument("--salt", default="deep-leads-v1")
    ap.add_argument("--out", default="rl_data/deep_leads.v1.jsonl")
    ap.add_argument("--limit-cells", type=int, default=PER_CELL,
                    help="smoke runs may fill smaller cells; a real capture "
                         "must use the preregistered 16")
    args = ap.parse_args()

    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        print("REFUSING: set SHENGJI_REQUIRE_VOIDS=1 — a capture whose search "
              "used impossible worlds is not the distribution we want.")
        sys.exit(3)
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("REFUSING: dirty tree. A frozen capture must be tied to the code "
              "that produced it.")
        sys.exit(3)
    if os.path.exists(args.out):
        print(f"REFUSING: {args.out} exists; a capture is never rewritten.")
        sys.exit(3)

    need = {(sp, tr, ro): args.limit_cells
            for sp in SPLITS for tr in TRICKS for ro in ROLES}
    total_needed = sum(need.values())
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    print(f"target {total_needed} states  ({len(SPLITS)} splits x "
          f"{len(TRICKS)} tricks x {len(ROLES)} roles x {args.limit_cells})",
          flush=True)

    accepted = rejected = zero_world = illegal = 0
    reject_reason: Counter = Counter()
    t0 = time.time()
    fh = open(args.out, "x")
    seed = args.seed0 - 1
    last = args.seed0 + args.max_seeds
    while sum(need.values()) > 0 and seed < last:
        seed += 1
        split, target = cell_targets(seed, args.salt)
        if not any(need[(split, target, ro)] for ro in ROLES):
            reject_reason["cell_already_full"] += 1
            rejected += 1
            continue
        try:
            got = play_to_trick(seed, target, args.bot)
        except Exception:
            reject_reason["engine_error"] += 1
            rejected += 1
            continue
        if got is None:
            reject_reason["round_ended_before_target"] += 1
            rejected += 1
            continue
        rnd, seat, setup, plays, pol = got
        role = "attacker" if rnd.is_attacker(seat) else "defender"
        if not need[(split, target, role)]:
            reject_reason["role_cell_full"] += 1
            rejected += 1
            continue
        zw = sum(getattr(b, "zero_world_decisions", 0) for b in pol)
        if zw:
            zero_world += zw
            reject_reason["zero_world_decision"] += 1
            rejected += 1
            continue
        need[(split, target, role)] -= 1
        accepted += 1
        fh.write(json.dumps({
            "seed": seed, "split": split, "trick": target, "role": role,
            "seat": seat, "ply": len(plays),
            "setup": setup, "plays": plays,
        }) + "\n")
        if accepted % 25 == 0:
            fh.flush()
            print(f"  {accepted}/{total_needed} accepted, {rejected} rejected, "
                  f"seed {seed}, {time.time()-t0:.0f}s", flush=True)
    fh.close()

    filled = total_needed - sum(need.values())
    complete = sum(need.values()) == 0
    manifest = {
        "git": sha, "tree_dirty": False, "bot": args.bot, "salt": args.salt,
        "seed0": args.seed0, "last_seed": seed, "max_seeds": args.max_seeds,
        "per_cell": args.limit_cells, "target_states": total_needed,
        "accepted": accepted, "rejected": rejected,
        "reject_reasons": dict(reject_reason),
        "zero_world_decisions": zero_world, "illegal_actions": illegal,
        "complete": complete,
        "unfilled_cells": {f"{sp}/{tr}/{ro}": n
                           for (sp, tr, ro), n in need.items() if n},
        "require_voids": True,
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(args.out.replace(".jsonl", ".manifest.json"), "x") as mf:
        json.dump(manifest, mf, indent=2)

    print(f"\naccepted {accepted}   rejected {rejected}   "
          f"seeds {args.seed0}-{seed}   {time.time()-t0:.0f}s")
    print(f"reject reasons: {dict(reject_reason)}")
    print(f"zero-world decisions: {zero_world}  (any >0 is a rejected deal)")
    if not complete:
        print(f"\nINCOMPLETE: {sum(need.values())} of {total_needed} cells "
              f"unfilled at the predeclared seed ceiling. This is a fail-closed "
              f"stop, not a result — raise --max-seeds and rerun to a NEW path, "
              f"or accept that the depth is unreachable and say so.")
    print(f"\nwrote {args.out}")
    sys.exit(0 if complete else 1)


if __name__ == "__main__":
    main()
