#!/usr/bin/env python3
"""Outcome-blind cost probe on production states, INCLUDING tractor locks.

This is a small timing diagnostic, not a strength screen or launch gate.
No round outcome or value prediction is written. Each measured state/recipe
is published as it finishes so an interrupted probe still teaches us cost.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
import hashlib
import os
from pathlib import Path
import platform
import random
import time

from shengji.ai.cwv_policy import shared_evaluator
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.evaluation import play_round
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.train.search_screen import _publish, bind_output_config, execution_source_identity


class Capture:
    def __init__(self, bot, states):
        self.bot, self.states = bot, states

    def __getattr__(self, key):
        return getattr(self.bot, key)

    def decide_play(self, rnd, seat):
        # Every actual play decision, even when production skips its search.
        self.states.append((copy.deepcopy(rnd), seat))
        return self.bot.decide_play(rnd, seat)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed0", type=int, default=89260904)
    parser.add_argument("--deals", type=int, default=2)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--world-grid", default="1,2")
    parser.add_argument("--selection-grid", default="1,30,90")
    args = parser.parse_args(argv)
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    worlds = [int(w) for w in args.world_grid.split(",")]
    selections = [int(n) for n in args.selection_grid.split(",")]
    if min(args.deals, args.stride, *worlds, *selections) < 1:
        parser.error("positive grids, deals, and stride required")
    evaluator = shared_evaluator(args.checkpoint, threads=1)
    config = {
        "checkpoint": evaluator.identity(), "seed0": args.seed0,
        "deals": args.deals, "stride": args.stride,
        "worlds": worlds, "selection_worlds": selections,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
        "cost_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "outcomes_read": False, "all_decisions_including_locks": True,
        "state_selection": "one fixed-seed uniform position per stride-sized chronological block; stride1=census",
    }
    bind_output_config(args.out, config)
    states = []
    for index in range(args.deals):
        seed = args.seed0 + index
        captured = []
        bots = [Capture(make_bot("mc-s0-report-lcb", seed=seed + s * 500_000), captured)
                for s in range(4)]
        play_round(Game(random.Random(seed)), bots, record=False)
        # A fixed [::8] or [::12] aliases four-seat tricks and can select
        # exclusively leads. Sample within each block without seeing outcomes.
        chooser = random.Random(seed ^ 0x435756)
        states.extend(chooser.choice(captured[start:start + args.stride])
                      for start in range(0, len(captured), args.stride))
        print(f"captured deal {index + 1}/{args.deals}: {len(captured)} decisions", flush=True)
    recipes = [("production", None), ("production-3x", None)]
    recipes += [(f"learned-w{w}-n{n}", CWVShortlistConfig(worlds=w, selection_worlds=n))
                for w in worlds for n in selections]
    recipes += [(f"uniform-n{n}", CWVShortlistConfig(selection_worlds=n, uniform=True))
                for n in selections]
    rows = []
    for index, (snapshot, seat) in enumerate(states):
        # Counterbalance timing order independently of scores/outcomes.
        order = list(recipes)
        random.Random(args.seed0 + index).shuffle(order)
        for name, recipe in order:
            path = args.out / f"state-{index:04}-{name}.json"
            if path.exists():
                row = json.loads(path.read_text())
                if row["state"] != index or row["recipe"] != name:
                    raise ValueError("cost row identity drift")
                rows.append(row)
                continue
            seed = args.seed0 + index
            if recipe is None:
                bot = make_bot("mc-s0-report-lcb-x3" if name.endswith("3x") else "mc-s0-report-lcb", seed=seed)
            else:
                bot = CWVShortlistBot(evaluator, seed=seed, config=recipe)
            rnd = copy.deepcopy(snapshot)
            wall, cpu = time.perf_counter(), time.process_time()
            bot.decide_play(rnd, seat)
            row = {
                "state": index, "recipe": name, "trick": len(snapshot.history),
                "seat": seat, "is_lead": not bool(snapshot.trick.plays),
                "wall_seconds": time.perf_counter() - wall,
                "cpu_seconds": time.process_time() - cpu,
                "config": None if recipe is None else asdict(recipe),
                "counts": getattr(bot, "shortlist_counts", None),
                "shortlist_wall_seconds": getattr(bot, "shortlist_wall_seconds", None),
            }
            _publish(path, row)
            rows.append(row)
        print(f"{index + 1}/{len(states)} states ({100*(index+1)/len(states):.1f}%)", flush=True)
    totals = {name: sum(r["wall_seconds"] for r in rows if r["recipe"] == name)
              for name, _ in recipes}
    result = {"config": config, "states": len(states), "totals_wall_seconds": totals,
              "wall_ratio": {n: t / totals["production"] for n, t in totals.items()},
              "note": "State-matched timing only. Confirm actual round-level cost in the DEV screen; no equality inferred from N."}
    _publish(args.out / "summary.json", result)
    print(json.dumps(result["wall_ratio"], sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
