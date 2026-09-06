#!/usr/bin/env python3
"""Outcome-blind cost probe on production states, INCLUDING tractor locks.

This is a small timing diagnostic, not a strength screen or launch gate.
No round outcome or value prediction is written. Each measured state/recipe
is published as it finishes so an interrupted probe still teaches us cost.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from dataclasses import asdict
import json
import hashlib
import os
from pathlib import Path
import platform
import random
import resource
import sys
import time

from shengji.ai.cwv_policy import shared_evaluator
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.evaluation import play_round
from shengji.luna.game import _round_from_snapshot
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


class ScoreTrace:
    """Hash exact ordered scores, without publishing predictions or changing batches."""

    def __init__(self, evaluator):
        self.evaluator = evaluator
        self.digest = hashlib.sha256()
        self.batches = Counter()

    def score(self, positions, seat):
        values = self.evaluator.score(positions, seat)
        self.batches[len(positions)] += 1
        self.digest.update(len(positions).to_bytes(8, "little"))
        self.digest.update(values.astype("<f8", copy=False).tobytes())
        return values


def encoding_parity(rows):
    """Compare real consumers, not just tensors; timing is deliberately excluded."""
    pairs = {}
    for row in rows:
        if row.get("encoding") is None:
            continue
        key = (row["state"], json.dumps(row["config"], sort_keys=True))
        pairs.setdefault(key, {})[row["encoding"]] = row
    checked = 0
    for pair in pairs.values():
        if set(pair) == {"reference", "mlp-static"}:
            if pair["reference"]["semantic"] != pair["mlp-static"]["semantic"]:
                raise ValueError("encoding changed scores, shortlist, decision or RNG")
            checked += 1
    return checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed0", type=int, default=89260904)
    parser.add_argument("--deals", type=int, default=2)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--world-grid", default="1,2")
    parser.add_argument("--selection-grid", default="1,30,90")
    parser.add_argument("--encoding-grid", default="reference")
    parser.add_argument("--states-json", type=Path,
                        help="reuse a private JSON list of existing Luna engine snapshots; no recapture")
    args = parser.parse_args(argv)
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    worlds = [int(w) for w in args.world_grid.split(",")]
    selections = [int(n) for n in args.selection_grid.split(",")]
    encodings = args.encoding_grid.split(",")
    if (not encodings or len(set(encodings)) != len(encodings)
            or any(e not in ("reference", "mlp-static") for e in encodings)):
        parser.error("encoding-grid must contain distinct reference and/or mlp-static")
    if min(args.deals, args.stride, *worlds, *selections) < 1:
        parser.error("positive grids, deals, and stride required")
    evaluators = {e: shared_evaluator(args.checkpoint, threads=1, encoding=e)
                  for e in encodings}
    states_raw = None if args.states_json is None else args.states_json.read_bytes()
    config = {
        "checkpoint": {e: v.identity() for e, v in evaluators.items()}, "seed0": args.seed0,
        "encodings": encodings,
        "states_json_sha256": None if states_raw is None else hashlib.sha256(states_raw).hexdigest(),
        "deals": args.deals, "stride": args.stride,
        "worlds": worlds, "selection_worlds": selections,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1] / "shengji"),
        "cost_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "outcomes_read": False, "all_decisions_including_locks": True,
        "state_selection": ("caller-supplied ordered snapshots; no resampling" if states_raw is not None else
                            "one fixed-seed uniform position per stride-sized chronological block; stride1=census"),
    }
    bind_output_config(args.out, config)
    states = []
    if states_raw is not None:
        snapshots = json.loads(states_raw)
        if type(snapshots) is not list or not snapshots:
            raise ValueError("states-json requires a nonempty snapshot list")
        states = [(rnd, rnd.turn) for rnd in map(_round_from_snapshot, snapshots)]
    for index in range(args.deals if states_raw is None else 0):
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
    recipes = [("production", None, None), ("production-3x", None, None)]
    recipes += [(f"learned-w{w}-n{n}-{e}", CWVShortlistConfig(worlds=w, selection_worlds=n), e)
                for w in worlds for n in selections for e in encodings]
    recipes += [(f"uniform-n{n}", CWVShortlistConfig(selection_worlds=n, uniform=True), None)
                for n in selections]
    rows = []
    for index, (snapshot, seat) in enumerate(states):
        # Counterbalance timing order independently of scores/outcomes.
        order = list(recipes)
        random.Random(args.seed0 + index).shuffle(order)
        for name, recipe, encoding in order:
            path = args.out / f"state-{index:04}-{name}.json"
            if path.exists():
                row = json.loads(path.read_text())
                if row["state"] != index or row["recipe"] != name:
                    raise ValueError("cost row identity drift")
                rows.append(row)
                continue
            seed = args.seed0 + index
            trace = None if encoding is None else ScoreTrace(evaluators[encoding])
            if recipe is None:
                bot = make_bot("mc-s0-report-lcb-x3" if name.endswith("3x") else "mc-s0-report-lcb", seed=seed)
            else:
                bot = CWVShortlistBot(trace, seed=seed, config=recipe)
            rnd = copy.deepcopy(snapshot)
            wall, cpu = time.perf_counter(), time.process_time()
            played = bot.decide_play(rnd, seat)
            wall_elapsed, cpu_elapsed = time.perf_counter() - wall, time.process_time() - cpu
            detail = getattr(bot, "last_shortlist", None)
            semantic = {
                "played": played,
                "rng_sha256": hashlib.sha256(repr(bot.rng.getstate()).encode()).hexdigest(),
                "shortlist": None if detail is None else {
                    k: v for k, v in detail.items() if k != "wall_seconds"},
                "scores_sha256": None if trace is None else trace.digest.hexdigest(),
                "batch_sizes": None if trace is None else dict(trace.batches),
            }
            # Normalize integer dictionary keys just as publication/reopen does.
            semantic = json.loads(json.dumps(semantic, sort_keys=True))
            row = {
                "state": index, "recipe": name, "trick": len(snapshot.history),
                "encoding": encoding, "semantic": semantic,
                "seat": seat, "is_lead": not bool(snapshot.trick.plays),
                "wall_seconds": wall_elapsed,
                "cpu_seconds": cpu_elapsed,
                "effective_cpu_cores": cpu_elapsed / max(wall_elapsed, 1e-12),
                "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                    (1 if sys.platform == "darwin" else 1024),
                "config": None if recipe is None else asdict(recipe),
                "counts": getattr(bot, "shortlist_counts", None),
                "shortlist_wall_seconds": getattr(bot, "shortlist_wall_seconds", None),
            }
            _publish(path, row)
            rows.append(row)
        encoding_parity(rows)
        print(f"{index + 1}/{len(states)} states ({100*(index+1)/len(states):.1f}%)", flush=True)
    totals = {name: sum(r["wall_seconds"] for r in rows if r["recipe"] == name)
              for name, _, _ in recipes}
    result = {"config": config, "states": len(states), "totals_wall_seconds": totals,
              "encoding_pairs_bit_identical": encoding_parity(rows),
              "wall_ratio": {n: t / totals["production"] for n, t in totals.items()},
              "note": "State-matched timing only; not strength evidence. RSS is process-lifetime high-water, not per-arm memory savings. CPU/wall measures effective cores; each evaluator uses one thread. No equality inferred from N."}
    _publish(args.out / "summary.json", result)
    print(json.dumps(result["wall_ratio"], sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
