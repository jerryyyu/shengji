#!/usr/bin/env python3
"""Bounded CPU-only cost probe on identical states, not a strength screen.

Each worker owns one deal, profiles production and the hybrid on identical
early/middle states, and never compares gameplay outcomes. Checkpoint loading
and a model warmup are outside decision timing. Keep BLAS threads at one.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
import multiprocessing
import os
from pathlib import Path
import random
import time

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.train.search_screen import _publish, loaded_heads, execution_source_identity
from shengji.train.world_shortlist import WorldShortlistBot, WorldShortlistConfig


def measure_deal(args, index):
    import torch
    torch.set_num_threads(1)
    heads = loaded_heads(args["checkpoint"], args["allow_legacy"], args["batch_size"])
    if heads.metadata["checkpoint_sha256"] != args["checkpoint_sha256"]:
        raise ValueError("checkpoint changed before benchmark worker")
    game = Game(random.Random(args["seed0"] + index))
    rnd, driver = game.start_round(), HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        shown = driver.decide_declare(rnd, seat)
        if shown:
            rnd.declare(seat, shown)
    for seat in range(4):
        shown = driver.decide_declare(rnd, seat, final=True)
        if shown:
            rnd.declare(seat, shown)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, driver.decide_bury(rnd, rnd.banker))
    # Warm each actual numerical backend, not just torch import.
    heads.values([rnd])
    warm = WorldShortlistBot(heads, config=WorldShortlistConfig(value_kind=args["value_kind"]))
    if args["value_kind"] == "points":
        from shengji.rl.encode import encode_obs
        warm._points_head.forward([encode_obs(rnd, rnd.turn)])
    rows = []
    for ply in range(49):
        if rnd.phase != "play":
            break
        if ply in (0, 8, 24, 48):
            # Alternate arm ordering by deal/state; all see identical states.
            doses = [None] + args["cheap_grid"]
            if (index + ply // 8) % 2:
                doses.reverse()
            for cheap in doses:
                if cheap is None:
                    bot = make_bot("mc-s0-report-lcb", seed=args["seed0"] + index)
                else:
                    bot = WorldShortlistBot(heads, seed=args["seed0"] + index,
                        config=WorldShortlistConfig(
                            cheap_worlds=cheap, refine_worlds=args["refine_worlds"],
                            shortlist_size=args["shortlist_size"], leaf_tricks=args["leaf_tricks"],
                            batch_size=args["batch_size"], value_kind=args["value_kind"]))
                state = copy.deepcopy(rnd)
                cpu, wall = time.process_time(), time.perf_counter()
                bot.decide_play(state, state.turn)
                elapsed_cpu, elapsed_wall = time.process_time() - cpu, time.perf_counter() - wall
                record = bot.last_decision_record
                rows.append({"deal": index, "ply": ply, "cheap_worlds": cheap,
                    "cpu_seconds": elapsed_cpu, "wall_seconds": elapsed_wall,
                    "searched": record is not None, "accepted_worlds": bot.accepted_worlds,
                    "legacy_evaluations": bot.rollouts,
                    "counts": dict(getattr(bot, "hybrid_counts", {})),
                    "inference_seconds": getattr(bot, "hybrid_inference_seconds", 0),
                    "short_searches": bot.short_search_decisions})
        rnd.play(rnd.turn, driver.decide_play(rnd, rnd.turn))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--allow-legacy", action="store_true")
    p.add_argument("--value-kind", choices=("levels", "points"), default="levels")
    p.add_argument("--cheap-grid", default="32,64,128")
    p.add_argument("--refine-worlds", type=int, default=16)
    p.add_argument("--shortlist-size", type=int, default=3)
    p.add_argument("--leaf-tricks", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--deals", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed0", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        p.error("SHENGJI_REQUIRE_VOIDS=1 required")
    if not 1 <= args.deals <= 16 or not 1 <= args.workers <= 16:
        p.error("bounded probe requires 1..16 deals/workers")
    if not 1 <= args.refine_worlds <= 64 or not 1 <= args.batch_size <= 512:
        p.error("bounded probe requires refine-worlds <=64 and batch-size <=512")
    grid = [int(n) for n in args.cheap_grid.split(",")]
    if not grid or len(grid) > 4 or len(set(grid)) != len(grid) or any(not 1 <= n <= 256 for n in grid):
        p.error("use at most four distinct doses in 1..256")
    WorldShortlistConfig(cheap_worlds=grid[0], refine_worlds=args.refine_worlds,
        shortlist_size=args.shortlist_size, leaf_tricks=args.leaf_tricks,
        batch_size=args.batch_size, value_kind=args.value_kind)
    heads = loaded_heads(str(Path(args.checkpoint).resolve()), args.allow_legacy, args.batch_size)
    WorldShortlistBot(heads, config=WorldShortlistConfig(value_kind=args.value_kind))
    cfg = dict(vars(args), checkpoint=str(Path(args.checkpoint).resolve()), cheap_grid=grid,
               checkpoint_sha256=heads.metadata["checkpoint_sha256"])
    del cfg["out"]
    if args.out.exists():
        p.error("benchmark output exists; preserve it and use a new path")
    rows = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=min(args.workers, args.deals),
            mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(measure_deal, cfg, i) for i in range(args.deals)]
        for i, future in enumerate(as_completed(futures), 1):
            rows.extend(future.result())
            print(f"{i}/{args.deals} deals ({100*i/args.deals:.1f}%) elapsed={time.perf_counter()-started:.1f}s", flush=True)
    summary = []
    base_cpu = sum(r["cpu_seconds"] for r in rows if r["cheap_worlds"] is None)
    for dose in [None] + grid:
        selected = [r for r in rows if r["cheap_worlds"] == dose]
        summary.append({"cheap_worlds": dose, "states": len(selected),
            "searched": sum(r["searched"] for r in selected),
            "cpu_seconds": sum(r["cpu_seconds"] for r in selected),
            "cpu_ratio": sum(r["cpu_seconds"] for r in selected) / base_cpu,
            "sampled_worlds": sum(r["accepted_worlds"] for r in selected),
            "short_searches": sum(r["short_searches"] for r in selected)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _publish(args.out, {"schema": "world-shortlist-cost-probe-v1", "config": cfg,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
        "wall_seconds": time.perf_counter() - started,
        "claim": "small matched-state cost probe only; no gameplay outcomes or strength claim",
        "summary": summary, "rows": sorted(rows, key=lambda r: (r["deal"], r["ply"], r["cheap_worlds"] or 0))})
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
