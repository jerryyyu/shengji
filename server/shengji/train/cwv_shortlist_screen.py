"""Resumable mirrored screen for the exhaustive complete-world shortlist."""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform

from ..ai.cwv_policy import shared_evaluator
from ..ai.registry import make_bot
from ..oracle import screen as duel
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from .leaf_screen import _game_factory_for
from .search_screen import (
    TimedPolicy, _publish, _run_pending, bind_output_config,
    execution_source_identity,
)

BASELINE_SELECT_WORLDS = 30
BASELINE_REPORT_WORLDS = 300
RANK = "2"
ARMS = ("learned", "uniform", "production", "identity")


class CwvTimedPolicy(TimedPolicy):
    """Attach the shortlist receipt, including forced singleton decisions."""

    def decide_play(self, rnd, seat):
        before = len(self.decisions)
        try:
            return super().decide_play(rnd, seat)
        finally:
            detail = copy.deepcopy(getattr(self.bot, "last_shortlist", None))
            if detail is not None:
                if len(self.decisions) > before:
                    self.decisions[-1]["cwv_shortlist"] = detail
                else:
                    # TimedPolicy records only decisions with the inherited MC
                    # record. A forced singleton still needs a durable trace.
                    self.decisions.append({
                        "seat": seat,
                        "trick": len(rnd.history),
                        "forced": True,
                        "cwv_shortlist": detail,
                    })


def _shortlist_config(config: dict) -> CWVShortlistConfig:
    return CWVShortlistConfig(**config["shortlist"])


def _encoding(config: dict) -> str:
    """Reopen legacy configs as reference-encoded screens."""
    return config.get("encoding", "reference")


def make_side(config: dict, side: str, seed: int):
    arm = config["arm"]
    if side == "baseline" or arm == "identity" or arm == "production":
        bot = make_bot("mc-s0-report-lcb", seed=seed)
        if side == "arm" and arm == "production":
            multiplier = int(config["production_multiplier"])
            bot.N_DETERMINIZATIONS = BASELINE_SELECT_WORLDS * multiplier
            bot.REPORT_FOLD_WORLDS = BASELINE_REPORT_WORLDS * multiplier
        else:
            bot.N_DETERMINIZATIONS = BASELINE_SELECT_WORLDS
            bot.REPORT_FOLD_WORLDS = BASELINE_REPORT_WORLDS
        return bot

    evaluator = None
    if arm == "learned":
        evaluator = shared_evaluator(config["checkpoint"], threads=1,
                                     max_batch=config.get(
                                         "batch_size",
                                         config["shortlist"]["batch_size"]),
                                     encoding=_encoding(config))
        if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
            raise ValueError("checkpoint changed between configuration and worker")
    bot = CWVShortlistBot(evaluator, seed=seed,
                          config=_shortlist_config(config),
                          reuse_successors=config.get("reuse_successors", False))
    bot.REPORT_FOLD_WORLDS = int(config["report_worlds"])
    return bot


def work_counters(bots):
    out = duel.work_counters(bots)
    for bot in bots:
        for key, value in getattr(bot, "shortlist_counts", {}).items():
            name = "cwv_" + key
            out[name] = out.get(name, 0) + int(value)
    for key in ("decision_cpu_seconds", "decision_wall_seconds",
                "shortlist_wall_seconds"):
        out[key] = float(sum(getattr(bot, key, 0.0) for bot in bots))
    # Cheap complete-world evaluations are intentionally separate from the
    # inherited full heuristic continuations; they never inflate rollouts.
    out["cheap_evaluations"] = int(out.get("cwv_cheap_evaluations", 0))
    out["full_rollout_accepted_worlds"] = int(out["accepted_worlds"] - out.get("cwv_cheap_worlds", 0))
    out["continuation_rollouts"] = int(out["rollouts"])
    out["total_rollouts"] = int(out["rollouts"])
    return out


def _recipe(config):
    recipe = {
        "schema": config["schema"], "arm": config["arm"],
        "checkpoint_sha256": config["checkpoint_sha256"],
        "shortlist": config["shortlist"],
        "report_worlds": config["report_worlds"],
        "production_multiplier": config["production_multiplier"],
        "target_wall_multiplier": config["target_wall_multiplier"],
        "rank": RANK,
    }
    # New receipts bind the requested mode.  A pre-mode config has no such
    # field and must continue to reopen its legacy shards as reference.
    if "encoding" in config:
        recipe["encoding"] = _encoding(config)
    if "reuse_successors" in config:
        recipe["reuse_successors"] = config["reuse_successors"]
    return recipe


def run_cluster(config, cluster):
    created = []

    def factory(_config, side, seed):
        wrapped = CwvTimedPolicy(make_side(config, side, seed))
        created.append((side, wrapped))
        return wrapped

    base = duel.build_config(arm="none", select_worlds=BASELINE_SELECT_WORLDS,
                             report_worlds=BASELINE_REPORT_WORLDS)
    seed = config["seed0"] + cluster
    rows = [duel.play_screen_round(
        base, cluster, seed, mirror, bot_factory=factory,
        counter_fn=work_counters, game_factory=_game_factory_for(RANK))
            for mirror in (0, 1)]
    for record, _ in rows:
        record["arm"] = config["arm"]
    return {
        "schema": "cwv-shortlist-shard-v1", "cluster": cluster,
        "seed": seed, "rank": RANK, "recipe": _recipe(config),
        "records": [record for record, _ in rows],
        "timings": [timing for _, timing in rows],
        "decision_traces": [{"mirror": i // 4, "side": side,
                             "decisions": policy.decisions}
                            for i, (side, policy) in enumerate(created)],
    }


def reopen_shard(path, config, cluster):
    shard = json.loads(path.read_text())
    rows = shard.get("records", [])
    seed = config["seed0"] + cluster
    if (shard.get("schema") != "cwv-shortlist-shard-v1"
            or shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != RANK or shard.get("recipe") != _recipe(config)
            or len(rows) != 2 or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != RANK
                   or r.get("arm") != config["arm"] for r in rows)):
        raise ValueError("completed shard does not match its mirrored pair and recipe")
    return shard


def summary_for(shards, config):
    base = duel.build_config(arm="none", select_worlds=BASELINE_SELECT_WORLDS,
                             report_worlds=BASELINE_REPORT_WORLDS)
    result = duel.summarize(
        [record for shard in shards for record in shard["records"]], base,
        seed0=config["seed0"], replicates=1000)
    totals = result.get("work_totals", {})

    def ratio(key):
        denominator = totals.get("baseline", {}).get(key, 0)
        return (totals.get("arm", {}).get(key, 0) / denominator
                if denominator else None)

    wall_ratio = ratio("decision_wall_seconds")
    target = int(config["target_wall_multiplier"])
    result.update({
        "schema": "cwv-shortlist-summary-v1", "config": config,
        "arm": config["arm"], "rank": RANK,
        "claim": "exploratory DEV paired screen; no equal-work or strength claim",
        "completed_clusters": len(shards),
        "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "arm_over_baseline_decision_cpu": ratio("decision_cpu_seconds"),
        "arm_over_baseline_decision_wall": wall_ratio,
        "target_wall_multiplier": target,
        "decision_wall_target_status": (
            "over_target" if wall_ratio is not None and wall_ratio > target
            else "within_target" if wall_ratio is not None else "unknown"),
        "equal_work_strength_claim": False,
        "work_caveat": "Decision wall/CPU and cheap evaluations are measured separately; "
                        "a target overrun does not censor or invalidate outcomes.",
    })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--worlds", type=int, default=1)
    parser.add_argument("--selection-worlds", type=int, default=30)
    parser.add_argument("--alternatives", type=int, default=4)
    parser.add_argument("--report-worlds", type=int, default=300)
    parser.add_argument("--production-multiplier", type=int, choices=(1, 3), default=1)
    parser.add_argument("--target-wall-multiplier", type=int, choices=(1, 3), default=1)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--encoding", choices=("reference", "mlp-static"),
                        default="reference")
    parser.add_argument("--reuse-successors", action="store_true",
                        help="reuse equivalent leaves/inputs without changing action rows or model batches")
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if (min(args.worlds, args.selection_worlds, args.alternatives,
            args.batch_size, args.clusters, args.workers) < 1
            or args.report_worlds < 30):
        parser.error("positive worlds/alternatives/clusters/workers and >=30 report worlds required")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    if args.arm == "learned" and not args.checkpoint:
        parser.error("learned requires --checkpoint")
    if args.arm != "learned" and args.checkpoint:
        parser.error("--checkpoint is only valid for learned")
    if args.reuse_successors and args.arm != "learned":
        parser.error("--reuse-successors is only valid for learned")
    checkpoint = str(Path(args.checkpoint).resolve()) if args.checkpoint else None
    checkpoint_sha = None
    checkpoint_recipe = None
    if args.arm == "learned":
        evaluator = shared_evaluator(
            checkpoint, threads=1, max_batch=args.batch_size,
            encoding=args.encoding)
        checkpoint_sha = evaluator.checkpoint_sha256
        checkpoint_recipe = evaluator.identity()
    shortlist = CWVShortlistConfig(
        worlds=args.worlds, selection_worlds=args.selection_worlds,
        alternatives=args.alternatives, batch_size=args.batch_size,
        uniform=args.arm == "uniform")
    config = {
        "schema": "cwv-shortlist-config-v1", "arm": args.arm,
        "checkpoint": checkpoint, "checkpoint_sha256": checkpoint_sha,
        "checkpoint_recipe": checkpoint_recipe,
        "encoding": args.encoding,
        "shortlist": asdict(shortlist), "batch_size": args.batch_size,
        "report_worlds": args.report_worlds,
        "production_multiplier": args.production_multiplier,
        "target_wall_multiplier": args.target_wall_multiplier,
        "seed0": args.seed0, "clusters": args.clusters,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1]),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "environment": {k: v for k, v in sorted(os.environ.items())
                                    if k.startswith("SHENGJI_") or k in (
                                        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                        "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS")}},
    }
    # Leave old/default recipes unchanged; enabled receipts explicitly bind it.
    if args.reuse_successors:
        config["reuse_successors"] = True
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.clusters):
        path = args.out / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    try:
        _run_pending(config, pending, shards, output=args.out, workers=args.workers,
                     task_fn=run_cluster)
    except Exception as exc:
        if not (args.out / "failure.json").exists():
            _publish(args.out / "failure.json", {
                "type": type(exc).__name__, "message": str(exc),
                "failed_clusters": [],
                "completed_clusters": sorted(s["cluster"] for s in shards),
                "recovery": "rerun the identical command; completed mirrored pairs are retained",
            })
        raise
    finally:
        if shards:
            _publish(args.out / "summary.json",
                     summary_for(sorted(shards, key=lambda s: s["cluster"]), config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
