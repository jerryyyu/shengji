"""Small resumable DEV comparison: batched value shortlist, full MC report.

Reuses the existing mirrored driver and atomic pair runner. This is a policy
experiment, not a byte-identical production optimization or an equal-cost
claim. Keep the checkpoint, recipe and completed pairs when restarting.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform

from ..ai.registry import make_bot
from ..oracle import screen as duel
from .leaf_screen import _game_factory_for, cycle_rank, parse_trump_ranks
from .search_screen import (
    TimedPolicy, _publish, _run_pending, bind_output_config,
    execution_source_identity, loaded_heads,
)
from .world_shortlist import WorldShortlistBot, WorldShortlistConfig


class ShortlistTimedPolicy(TimedPolicy):
    def decide_play(self, rnd, seat):
        before = len(self.decisions)
        try:
            return super().decide_play(rnd, seat)
        finally:
            record = self.bot.last_decision_record
            if len(self.decisions) > before and record:
                self.decisions[-1]["world_shortlist"] = copy.deepcopy(
                    record.get("world_shortlist"))
                if record.get("world_shortlist") is not None:
                    # Shortlist indices must address an actual persisted
                    # population, not a candidate list discarded by the timer.
                    self.decisions[-1]["world_shortlist"].update({
                        "candidates": copy.deepcopy(record["candidates"]),
                        "refinement_means": [v if n else None for v, n in zip(
                            record["means"], record["n_by_candidate"])],
                        "refinement_counts": list(record["n_by_candidate"]),
                        "report_candidate_index": record["report_candidate_index"],
                    })


def make_side(config, side, seed):
    if side == "baseline" or config["arm"] != "hybrid":
        bot = make_bot("mc-s0-report-lcb", seed=seed)
        bot.N_DETERMINIZATIONS = (
            config["control_worlds"] if side == "arm" and config["arm"] == "work"
            else config["baseline_worlds"])
    else:
        heads = loaded_heads(config["checkpoint"], config["allow_legacy"],
                             config["hybrid"]["batch_size"])
        if heads.metadata.get("checkpoint_sha256") != config["checkpoint_sha256"]:
            raise ValueError("checkpoint changed between configuration and worker")
        bot = WorldShortlistBot(heads, seed=seed,
                               config=WorldShortlistConfig(**config["hybrid"]))
    bot.REPORT_FOLD_WORLDS = config["report_worlds"]
    return bot


def work_counters(bots):
    out = duel.work_counters(bots)
    for bot in bots:
        for key, value in getattr(bot, "hybrid_counts", {}).items():
            name = "hybrid_" + key
            out[name] = out.get(name, 0) + value
    for key in ("decision_cpu_seconds", "decision_wall_seconds",
                "hybrid_inference_seconds"):
        out[key] = sum(getattr(bot, key, 0.0) for bot in bots)
    # MCBot's legacy counter counts evaluated candidate/world pairs. A cheap
    # predicted leaf is NOT a full heuristic continuation.
    out["candidate_evaluations"] = out["rollouts"]
    out["continuation_rollouts"] = out["rollouts"] - out.get("hybrid_cheap_evaluations", 0)
    out["total_rollouts"] = out["continuation_rollouts"]
    return out


def run_cluster(config, cluster):
    created = []

    def factory(_config, side, seed):
        bot = ShortlistTimedPolicy(make_side(config, side, seed))
        created.append((side, bot))
        return bot

    base = duel.build_config(arm="none", select_worlds=config["baseline_worlds"],
                             report_worlds=config["report_worlds"])
    seed = config["seed0"] + cluster
    rank = cycle_rank(config, cluster)
    rows = [duel.play_screen_round(
        base, cluster, seed, mirror, bot_factory=factory,
        counter_fn=work_counters, game_factory=_game_factory_for(rank))
        for mirror in (0, 1)]
    for record, _ in rows:
        record["arm"] = config["arm"]
    return {
        "cluster": cluster, "seed": seed, "rank": rank,
        "recipe": {key: config[key] for key in (
            "arm", "checkpoint_sha256", "hybrid", "baseline_worlds",
            "control_worlds", "report_worlds")},
        "records": [record for record, _ in rows],
        "timings": [timing for _, timing in rows],
        "decision_traces": [{"mirror": i // 4, "side": side,
                             "decisions": bot.decisions}
                            for i, (side, bot) in enumerate(created)],
    }


def reopen_shard(path, config, cluster):
    shard = json.loads(path.read_text())
    seed, rank = config["seed0"] + cluster, cycle_rank(config, cluster)
    rows = shard.get("records", [])
    recipe = {key: config[key] for key in (
        "arm", "checkpoint_sha256", "hybrid", "baseline_worlds",
        "control_worlds", "report_worlds")}
    if (shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != rank or shard.get("recipe") != recipe
            or len(rows) != 2 or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank or r.get("arm") != config["arm"]
                   for r in rows)):
        raise ValueError("completed shard does not match its mirrored pair and recipe")
    return shard


def summary_for(shards, config):
    base = duel.build_config(arm="none", select_worlds=config["baseline_worlds"],
                             report_worlds=config["report_worlds"])
    result = duel.summarize([r for s in shards for r in s["records"]], base,
                            seed0=config["seed0"], replicates=1000)
    totals = result["work_totals"]

    def ratio(key):
        baseline = totals["baseline"].get(key, 0)
        return totals["arm"].get(key, 0) / baseline if baseline else None

    result.update({
        "schema": "world-shortlist-dev-summary-v1", "config": config,
        "arm": config["arm"],
        "arm_description": {
            "none": "production identity control",
            "work": "production MC with a larger selection-world budget",
            "hybrid": "batched value on many worlds -> full-rollout shortlist -> fresh full report-LCB",
        }[config["arm"]],
        "claim": "exploratory DEV only; no confirmation, promotion or deployment",
        "completed_clusters": len(shards), "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "arm_over_baseline_decision_cpu": ratio("decision_cpu_seconds"),
        "arm_over_baseline_decision_wall": ratio("decision_wall_seconds"),
        "arm_over_baseline_sampled_worlds": ratio("accepted_worlds"),
        "equal_work_strength_claim": False,
        "work_caveat": "Measure total decision CPU and wall. More worlds and fewer full rollouts alone do not prove savings.",
    })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint")
    parser.add_argument("--allow-legacy", action="store_true")
    parser.add_argument("--arm", choices=("hybrid", "none", "work"), default="hybrid")
    parser.add_argument("--value-kind", choices=("levels", "points"), default="levels")
    parser.add_argument("--cheap-worlds", type=int, default=128)
    parser.add_argument("--refine-worlds", type=int, default=16)
    parser.add_argument("--shortlist-size", type=int, default=3)
    parser.add_argument("--leaf-tricks", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--baseline-worlds", type=int, default=30)
    parser.add_argument("--control-worlds", type=int, default=128)
    parser.add_argument("--report-worlds", type=int, default=300)
    parser.add_argument("--trump-ranks", default="2",
                        help="default matches existing rank-2 checkpoints; broader ranks test transfer")
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if (min(args.clusters, args.workers, args.baseline_worlds, args.control_worlds) < 1
            or args.report_worlds < 30):
        parser.error("positive clusters/workers/worlds and >=30 report worlds required")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    try:
        recipe = WorldShortlistConfig(
            cheap_worlds=args.cheap_worlds, refine_worlds=args.refine_worlds,
            shortlist_size=args.shortlist_size, leaf_tricks=args.leaf_tricks,
            batch_size=args.batch_size, value_kind=args.value_kind)
        ranks = parse_trump_ranks(args.trump_ranks)
    except ValueError as exc:
        parser.error(str(exc))
    checkpoint, metadata = None, None
    if args.arm == "hybrid":
        if not args.checkpoint:
            parser.error("hybrid requires --checkpoint")
        checkpoint = str(Path(args.checkpoint).resolve())
        heads = loaded_heads(checkpoint, args.allow_legacy, args.batch_size)
        # Exercise points-head compatibility before publishing or spawning.
        WorldShortlistBot(heads, config=recipe)
        metadata = heads.metadata
    config = {
        "schema": "world-shortlist-dev-config-v1", "arm": args.arm,
        "checkpoint": checkpoint,
        "checkpoint_sha256": metadata["checkpoint_sha256"] if metadata else None,
        "model_metadata": metadata, "allow_legacy": args.allow_legacy,
        "hybrid": asdict(recipe), "baseline_worlds": args.baseline_worlds,
        "control_worlds": args.control_worlds, "report_worlds": args.report_worlds,
        "trump_ranks": list(ranks), "seed0": args.seed0, "clusters": args.clusters,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1]),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "environment": {k: v for k, v in sorted(os.environ.items())
                                    if k.startswith("SHENGJI_") or k in (
                                        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                        "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS")}},
    }
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.clusters):
        path = args.out / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    _run_pending(config, pending, shards, output=args.out, workers=args.workers,
                 task_fn=run_cluster)
    result = summary_for(sorted(shards, key=lambda s: s["cluster"]), config)
    _publish(args.out / "summary.json", result)
    print(json.dumps({k: result[k] for k in (
        "complete", "completed_clusters", "arm_signed_level_utility",
        "arm_over_baseline_decision_cpu", "problems")}, sort_keys=True), flush=True)
    return 0
