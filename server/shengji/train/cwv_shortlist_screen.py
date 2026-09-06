"""Resumable mirrored screen for the exhaustive complete-world shortlist."""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import platform

from ..ai.cwv_policy import shared_evaluator
from ..ai.registry import make_bot
from ..oracle import screen as duel
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from .cwv_double_shortlist import CWVDoubleShortlistBot
from .leaf_screen import _game_factory_for, parse_trump_ranks
from .search_screen import (
    TimedPolicy, _publish, _run_pending, bind_output_config,
    execution_source_identity,
)

BASELINE_SELECT_WORLDS = 30
BASELINE_REPORT_WORLDS = 300
RANK = "2"
ARMS = ("learned", "uniform", "production", "identity")


def rank_for(config: dict, cluster: int) -> str:
    """Return the configured rank for a cluster, preserving legacy rank 2."""
    ranks = config.get("trump_ranks") or (RANK,)
    return ranks[cluster % len(ranks)]


def _cost_order(directory: Path, clusters, seed0: int, trump_ranks=None) -> dict:
    """Read prior completed shard timings for execution-only scheduling."""
    costs = {}
    directory = directory.resolve()
    for cluster in clusters:
        path = directory / f"cluster-{cluster:05}.json"
        if not path.is_file():
            raise ValueError(f"cost-order artifact missing cluster {cluster}: {path}")
        try:
            shard = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid cost-order artifact for cluster {cluster}") from exc
        expected_seed = seed0 + cluster
        rank = rank_for({"trump_ranks": trump_ranks}, cluster)
        if (shard.get("schema") != "cwv-shortlist-shard-v1"
                or type(shard.get("cluster")) is not int
                or shard.get("cluster") != cluster
                or type(shard.get("seed")) is not int
                or shard.get("seed") != expected_seed
                or shard.get("rank") != rank):
            raise ValueError(f"cost-order artifact drift for cluster {cluster}")
        timings = shard.get("timings")
        if type(timings) is not list or len(timings) != 2:
            raise ValueError(f"cost-order artifact requires two mirrors for cluster {cluster}")
        walls = []
        mirrors = []
        for timing in timings:
            if type(timing) is not dict:
                raise ValueError(f"invalid cost-order timing for cluster {cluster}")
            mirror = timing.get("mirror")
            wall = timing.get("wall_secs")
            if (type(mirror) is not int or mirror not in (0, 1)
                    or mirror in mirrors
                    or type(timing.get("cluster")) is not int
                    or timing.get("cluster") != cluster
                    or type(timing.get("seed")) is not int
                    or timing.get("seed") != expected_seed
                    or type(wall) not in (int, float) or isinstance(wall, bool)
                    or not math.isfinite(wall) or wall < 0):
                raise ValueError(f"invalid cost-order timing for cluster {cluster}")
            mirrors.append(mirror)
            walls.append(wall)
        costs[cluster] = sum(walls)
        if not math.isfinite(costs[cluster]):
            raise ValueError(f"nonfinite cost-order total for cluster {cluster}")
    ordered = sorted(clusters, key=lambda cluster: (-costs[cluster], cluster))
    return {
        "source": str(directory),
        "criterion": "sum prior shard timings wall_secs",
        "clusters": ordered,
        "cluster_wall_secs": {str(cluster): costs[cluster] for cluster in ordered},
    }


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
            inner = getattr(self.bot, "last_double_shortlist", None)
            if inner is not None and len(self.decisions) > before:
                self.decisions[-1]["cwv_double_shortlist"] = copy.deepcopy(inner)
            record = getattr(self.bot, "last_decision_record", None)
            if record is not None and len(self.decisions) > before:
                allocation = record.get("alloc")
                if allocation is not None:
                    self.decisions[-1]["selection_allocation"] = copy.deepcopy(allocation)


def _shortlist_config(config: dict) -> CWVShortlistConfig:
    return CWVShortlistConfig(**config["shortlist"])


def _encoding(config: dict) -> str:
    """Reopen legacy configs as reference-encoded screens."""
    return config.get("encoding", "reference")


def _selection_allocation(config: dict) -> str:
    allocation = config.get("selection_allocation", "uniform")
    if allocation not in ("uniform", "adaptive"):
        raise ValueError("selection allocation must be uniform or adaptive")
    if allocation == "adaptive":
        if config.get("arm") != "learned":
            raise ValueError("adaptive selection allocation requires learned arm")
        if config.get("double_shortlist") is not None:
            raise ValueError("adaptive selection allocation is incompatible with double-shortlist")
    return allocation


def make_side(config: dict, side: str, seed: int):
    arm = config["arm"]
    allocation = _selection_allocation(config)
    flat_baseline = side == "baseline" and config.get("baseline") == "flat-shortlist"
    if (side == "baseline" and not flat_baseline) or arm in ("identity", "production"):
        bot = make_bot("mc-s0-report-lcb", seed=seed)
        if side == "arm" and arm == "production":
            multiplier = int(config["production_multiplier"])
            bot.N_DETERMINIZATIONS = BASELINE_SELECT_WORLDS * multiplier
            bot.REPORT_FOLD_WORLDS = BASELINE_REPORT_WORLDS * multiplier
        else:
            bot.N_DETERMINIZATIONS = BASELINE_SELECT_WORLDS
            bot.REPORT_FOLD_WORLDS = BASELINE_REPORT_WORLDS
        bot.ADAPTIVE_ALLOCATION = False
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
    inner = config.get("double_shortlist") if side == "arm" else None
    kwargs = dict(seed=seed, config=_shortlist_config(config),
                  reuse_successors=config.get("reuse_successors", False))
    if inner is not None:
        if inner.get("guidance") != "selection-fraction-ceil-v2":
            raise ValueError("double-shortlist guidance recipe is not selection-fraction-ceil-v2")
        bot = CWVDoubleShortlistBot(evaluator, **kwargs,
                                   inner_mode=inner["mode"],
                                   inner_worlds=inner["worlds"],
                                   inner_alternatives=4,
                                   inner_batch_size=inner["batch_size"],
                                   inner_reuse_successors=inner.get(
                                       "reuse_successors", False))
    else:
        bot = CWVShortlistBot(evaluator, **kwargs)
    bot.REPORT_FOLD_WORLDS = int(config["report_worlds"])
    # Double-shortlist owns this flag: its existing selection-stage guidance
    # uses that hook. Only configure the new root allocator for flat bots.
    if inner is None:
        bot.ADAPTIVE_ALLOCATION = (
            allocation == "adaptive" and arm == "learned"
            and side == "arm" and not flat_baseline)
    return bot


def work_counters(bots):
    out = duel.work_counters(bots)
    for bot in bots:
        for key, value in getattr(bot, "shortlist_counts", {}).items():
            name = "cwv_" + key
            out[name] = out.get(name, 0) + int(value)
        for key, value in getattr(bot, "double_shortlist_counts", {}).items():
            name = "double_" + key
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
    if any(hasattr(bot, "double_shortlist_counts") for bot in bots):
        out["inner_continuation_rollouts"] = int(out.get("double_inner_full_rollouts", 0))
        out["outer_continuation_rollouts"] = (
            out["total_rollouts"] - out["inner_continuation_rollouts"])
    return out


def _recipe(config):
    ranks = config.get("trump_ranks")
    recipe = {
        "schema": config["schema"], "arm": config["arm"],
        "checkpoint_sha256": config["checkpoint_sha256"],
        "shortlist": config["shortlist"],
        "report_worlds": config["report_worlds"],
        "production_multiplier": config["production_multiplier"],
        "target_wall_multiplier": config["target_wall_multiplier"],
        "rank": RANK if not ranks else ranks[0] if len(ranks) == 1 else None,
    }
    # New receipts bind the requested mode.  A pre-mode config has no such
    # field and must continue to reopen its legacy shards as reference.
    if "encoding" in config:
        recipe["encoding"] = _encoding(config)
    if "reuse_successors" in config:
        recipe["reuse_successors"] = config["reuse_successors"]
    if "trump_ranks" in config:
        recipe["trump_ranks"] = config["trump_ranks"]
    for key in ("double_shortlist", "baseline"):
        if key in config:
            recipe[key] = config[key]
    if "selection_allocation" in config:
        recipe["selection_allocation"] = _selection_allocation(config)
    return recipe


def run_cluster(config, cluster):
    created = []

    def factory(_config, side, seed):
        wrapped = CwvTimedPolicy(make_side(config, side, seed))
        created.append((side, wrapped))
        return wrapped

    rank = rank_for(config, cluster)
    base = duel.build_config(arm="none", select_worlds=BASELINE_SELECT_WORLDS,
                             report_worlds=BASELINE_REPORT_WORLDS)
    seed = config["seed0"] + cluster
    games = []

    def game_factory(rng):
        game = _game_factory_for(rank)(rng)
        games.append(game)
        return game

    rows = [duel.play_screen_round(
        base, cluster, seed, mirror, bot_factory=factory,
        counter_fn=work_counters, game_factory=game_factory)
            for mirror in (0, 1)]
    if len(rows) != len(games):
        raise ValueError("ranked screen game factory did not produce one game per mirror")
    for (record, _), game in zip(rows, games, strict=True):
        if record["trump_rank"] != rank:
            raise ValueError(f"cluster {cluster} dealt trump rank {record['trump_rank']!r}, expected {rank!r}")
        record["arm"] = config["arm"]
        if "trump_ranks" in config:
            round_state = getattr(game, "round", None)
            actual_suit = getattr(round_state, "trump_suit", None)
            if actual_suit is None:
                if not getattr(round_state, "trump_is_nt", False):
                    raise ValueError(f"cluster {cluster} has no declared trump suit/NT witness")
                actual_suit = "NT"
            if actual_suit not in ("S", "H", "D", "C", "NT"):
                raise ValueError(f"cluster {cluster} has invalid actual trump suit {actual_suit!r}")
            record["trump_suit"] = actual_suit
    return {
        "schema": "cwv-shortlist-shard-v1", "cluster": cluster,
        "seed": seed, "rank": rank, "recipe": _recipe(config),
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
    rank = rank_for(config, cluster)
    if (shard.get("schema") != "cwv-shortlist-shard-v1"
            or shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != rank or shard.get("recipe") != _recipe(config)
            or len(rows) != 2 or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank
                   or r.get("arm") != config["arm"]
                   or ("trump_ranks" in config
                       and r.get("trump_suit") not in ("S", "H", "D", "C", "NT"))
                   for r in rows)):
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
        "arm": config["arm"],
        "rank": (RANK if "trump_ranks" not in config
                 else config["trump_ranks"][0] if len(config["trump_ranks"]) == 1 else None),
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
    if "double_shortlist" in config or "baseline" in config:
        result["claim"] = "exploratory paired DEV strength estimate; not confirmation or deployment"
        result["arm_description"] = (
            "exhaustive learned root shortlist; bounded per-world perfect-information "
            "inner shortlist continuation, then terminal heuristic values and root MC-LCB"
            if "double_shortlist" in config else "flat exhaustive learned root shortlist")
        result["baseline_description"] = config.get("baseline", "production")
        result["work_caveat"] += (
            " Inner finalist continuations count separately and are included exactly once "
            "in total rollouts. Inner choices see sampled complete worlds, not true hidden hands.")
    if "selection_allocation" in config:
        allocation = _selection_allocation(config)
        result["selection_allocation"] = allocation
        result["allocation_label"] = f"{allocation}-root-selection"
    if "trump_ranks" in config:
        records = [record for shard in shards for record in shard["records"]]
        by_rank = {rank: 0 for rank in config["trump_ranks"]}
        by_suit = {suit: 0 for suit in ("S", "H", "D", "C", "NT")}
        for record in records:
            rank = record.get("trump_rank")
            suit = record.get("trump_suit")
            if rank not in by_rank:
                raise ValueError(f"record trump rank {rank!r} is outside configured cycle")
            if suit not in by_suit:
                raise ValueError(f"record lacks a valid actual trump suit/NT: {suit!r}")
            by_rank[rank] += 1
            by_suit[suit] += 1
        result["trump_ranks"] = list(config["trump_ranks"])
        result["coverage"] = {"by_rank": by_rank, "by_trump_suit": by_suit}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--worlds", type=int, default=1)
    parser.add_argument("--selection-worlds", type=int, default=30)
    parser.add_argument("--selection-allocation", choices=("uniform", "adaptive"),
                        help="opt in to bounded adaptive allocation for the learned root")
    parser.add_argument("--alternatives", type=int, default=4)
    parser.add_argument("--report-worlds", type=int, default=300)
    parser.add_argument("--production-multiplier", type=int, choices=(1, 3), default=1)
    parser.add_argument("--target-wall-multiplier", type=int, choices=(1, 3), default=1)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--encoding", choices=("reference", "mlp-static"),
                        default="reference")
    parser.add_argument("--reuse-successors", action="store_true",
                        help="reuse equivalent leaves/inputs without changing action rows or model batches")
    parser.add_argument("--inner-mode", choices=("learned", "uniform", "heuristic"),
                        help="DEV: one extra trick of per-world shortlist continuation; learned root only")
    parser.add_argument("--inner-worlds", type=int, default=4,
                        help="guided fraction numerator over --selection-worlds; scaled to each accepted world set")
    parser.add_argument("--inner-batch-size", type=int, default=128)
    parser.add_argument("--inner-reuse-successors", action="store_true",
                        help="reuse exact inner successor leaves and evaluator inputs")
    parser.add_argument("--baseline", choices=("production", "flat-shortlist"),
                        default="production")
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trump-ranks",
                        help="comma-separated distinct trump ranks for the cluster cycle")
    parser.add_argument("--cost-order-from", type=Path,
                        help="order pending clusters by prior shard wall time")
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
    if args.inner_mode is not None:
        if args.arm != "learned" or args.alternatives != 4:
            parser.error("--inner-mode requires a learned root with four alternatives plus incumbent")
        if min(args.inner_worlds, args.inner_batch_size) < 1:
            parser.error("inner worlds and batch size must be positive")
    if args.selection_allocation == "adaptive":
        if args.arm != "learned":
            parser.error("--selection-allocation adaptive requires --arm learned")
        if args.inner_mode is not None:
            parser.error("--selection-allocation adaptive is incompatible with --inner-mode")
    if args.inner_reuse_successors and args.inner_mode is None:
        parser.error("--inner-reuse-successors requires --inner-mode")
    if args.baseline == "flat-shortlist" and args.arm != "learned":
        parser.error("--baseline flat-shortlist requires the learned checkpoint/root recipe")
    trump_ranks = None
    if args.trump_ranks is not None:
        try:
            trump_ranks = parse_trump_ranks(args.trump_ranks)
        except Exception as exc:
            parser.error(str(exc))
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
    if trump_ranks is not None:
        config["trump_ranks"] = list(trump_ranks)
    if args.inner_mode is not None:
        config["double_shortlist"] = {
            "guidance": "selection-fraction-ceil-v2",
            "mode": args.inner_mode, "worlds": args.inner_worlds,
            "batch_size": args.inner_batch_size,
            "extra_tricks": 1, "alternatives": 4,
            "information": "per-sampled-world perfect information; simulation only",
        }
        if args.inner_reuse_successors:
            config["double_shortlist"]["reuse_successors"] = True
    if args.baseline != "production":
        config["baseline"] = args.baseline
    if args.selection_allocation is not None:
        config["selection_allocation"] = args.selection_allocation
    cost_order = (_cost_order(args.cost_order_from, range(args.clusters), args.seed0,
                              trump_ranks=trump_ranks)
                  if args.cost_order_from is not None else None)
    if cost_order is not None:
        config["execution_order"] = cost_order
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.clusters):
        path = args.out / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    if cost_order is not None:
        costs = cost_order["cluster_wall_secs"]
        pending.sort(key=lambda cluster: (-costs[str(cluster)], cluster))
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
