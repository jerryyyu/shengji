"""Cheap resumable DEV duel of learned root search vs production MC-LCB.

No deployment, freeze, one-shot gate, or fresh training. Completed mirrored
deal shards survive errors. Outcome summaries are descriptive; CPU work and
coverage are separate measured facts, never inferred from equal N settings.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from functools import lru_cache
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import random
import tempfile
import time

from ..ai.registry import make_bot
from ..engine.cards import RANKS
from ..engine.game import Game
from ..engine.round import Round
from ..oracle import screen as duel
from .search_inference import SearchHeads
from .search_policy import LearnedSearchBot, SearchConfig


class TimedPolicy:
    def __init__(self, bot):
        self.bot = bot
        self.decision_cpu_seconds = self.decision_wall_seconds = 0.0
        self.decisions = []

    def __getattr__(self, name):
        return getattr(self.bot, name)

    def decide_play(self, rnd, seat):
        cpu, wall = time.process_time(), time.perf_counter()
        try:
            return self.bot.decide_play(rnd, seat)
        finally:
            self.decision_cpu_seconds += time.process_time() - cpu
            self.decision_wall_seconds += time.perf_counter() - wall
            rec = self.bot.last_decision_record
            if rec:
                challenger = rec.get("report_candidate_index")
                learned = rec.get("learned_search", {})
                self.decisions.append({
                    "seat": seat, "trick": len(rnd.history),
                    "incumbent": rec["candidates"][0], "played": rec["played"],
                    "challenger": (rec["candidates"][challenger]
                                   if challenger is not None else None),
                    "reason": rec["reason"], "report": rec.get("report_fold"),
                    "selection_N": rec["n_determinizations"],
                    "report_worlds": rec["report_worlds_requested"],
                    "legal_size": learned.get("legal_size"),
                    "production_size": learned.get("production_size"),
                    "counts": learned.get("counts"),
                })


@lru_cache(maxsize=1)
def loaded_heads(path, allow_legacy, batch_size):
    import torch
    torch.set_num_threads(1)
    return SearchHeads.from_checkpoint(path, allow_legacy=allow_legacy, batch_size=batch_size)


def work_counters(bots):
    out = duel.work_counters(bots)
    for bot in bots:
        for key, val in getattr(bot, "learned_counts", {}).items():
            out[f"learned_{key}"] = out.get(f"learned_{key}", 0) + val
    for name in ("decision_cpu_seconds", "decision_wall_seconds", "enumeration_secs",
                 "learned_inference_secs"):
        out[name] = sum(getattr(bot, name, 0.0) for bot in bots)
    # Legacy counter rollouts includes replaced leaf evaluations. Do not label
    # those as full continuations in the new report.
    out["continuation_rollouts"] = out["rollouts"] - out.get("learned_value_evaluations", 0)
    out["total_rollouts"] = out["continuation_rollouts"]
    return out


def run_cluster(config, cluster):
    """Both mirrors are one atomic, independently replayable work unit."""
    created = []
    def factory(_config, side, seed):
        if side == "baseline" or config["arm"] == "none":
            bot = make_bot("mc-s0-report-lcb", seed=seed)
        else:
            heads = loaded_heads(config["checkpoint"], config["allow_legacy"], config["batch_size"])
            expected = config.get("checkpoint_sha256")
            if expected and heads.metadata["checkpoint_sha256"] != expected:
                raise ValueError("checkpoint changed between parent and worker")
            bot = LearnedSearchBot(heads, seed=seed, config=SearchConfig(
                arm=config["arm"], leaf_tricks=config["leaf_tricks"]))
        # Small overrides are ONLY for source-wiring tests, not labelled as
        # production-work evidence by summarize().
        bot.N_DETERMINIZATIONS = config["select_worlds"]
        if side == "arm" and config["arm"] != "none":
            bot.N_DETERMINIZATIONS = config.get("candidate_select_worlds") or config["select_worlds"]
        bot.REPORT_FOLD_WORLDS = config["report_worlds"]
        wrapped = TimedPolicy(bot)
        created.append((side, wrapped))
        return wrapped

    rank = RANKS[cluster % len(RANKS)]

    def game_factory(rng):
        game = Game(rng)
        game.level_idx = [RANKS.index(rank), RANKS.index(rank)]
        # Game.start_round uses rank 2 when banker is not yet known. Keep the
        # first-round declaration rule but explicitly construct this rank.
        def start():
            game.round = Round(rank, None, game.rng)
            game.round_no += 1
            return game.round
        game.start_round = start
        return game

    base = duel.build_config(arm="none", select_worlds=config["select_worlds"],
                             report_worlds=config["report_worlds"])
    seed = config["seed0"] + cluster
    rows = [duel.play_screen_round(base, cluster, seed, mirror,
                bot_factory=factory, counter_fn=work_counters, game_factory=game_factory)
            for mirror in (0, 1)]
    for record, _ in rows:
        record["arm"] = config["arm"]
    return {"cluster": cluster, "seed": seed, "rank": rank,
            "records": [r for r, _ in rows], "timings": [t for _, t in rows],
            "decision_traces": [{"mirror": i // 4, "side": side,
                                 "decisions": bot.decisions}
                                for i, (side, bot) in enumerate(created)]}


def summary_for(shards, config):
    records = [r for shard in shards for r in shard["records"]]
    base = duel.build_config(arm="none", select_worlds=config["select_worlds"],
                             report_worlds=config["report_worlds"])
    out = duel.summarize(records, base, seed0=config["seed0"], replicates=1000)
    totals = out["work_totals"]
    def ratio(name):
        denominator = totals["baseline"].get(name, 0)
        return totals["arm"].get(name, 0) / denominator if denominator else None
    cpu_ratio = ratio("decision_cpu_seconds")
    out.update({
        "schema": "learned-search-dev-summary-v1", "arm": config["arm"],
        "claim": "small DEV paired screen; not confirmation, promotion or deployment",
        "arm_description": "learned root allocation and optional one-trick value; production fresh-world report",
        "config": config, "completed_clusters": len(shards),
        "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "arm_over_baseline_decision_cpu": cpu_ratio,
        "arm_over_baseline_decision_wall": ratio("decision_wall_seconds"),
        "candidate_evaluation_ratio": ratio("rollouts"),
        "no_more_measured_decision_cpu": cpu_ratio is not None and cpu_ratio <= 1.0,
        "equal_work_strength_claim": False,
        "work_caveat": ("N is matched against the production ballot per searched state, not full cost. "
                        "An explicit candidate N override can reduce learned selection cost. "
                        "Different trajectories/extra unlocked decisions change aggregate work. "
                        "CPU includes enumeration, model calls and report. A ratio above 1 cannot "
                        "support an equal-work improvement claim; this small run is a cost diagnostic."),
    })
    return out


def _publish(path, value):
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    # A crash may leave a temporary file, never an occupied scientific slot.
    # Unique temporary names allow a restart to reuse all completed pairs.
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def reopen_shard(path, config, cluster):
    shard = json.loads(path.read_text())
    rows = shard.get("records", [])
    seed = config["seed0"] + cluster
    rank = RANKS[cluster % len(RANKS)]
    if (shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != rank or len(rows) != 2
            or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank or r.get("arm") != config["arm"] for r in rows)):
        raise ValueError("completed shard does not contain its exact mirrored pair")
    return shard


def execution_source_identity(package):
    """One first-consumption stamp, not repeated per state or worker.

    Include Python dependencies (engine, game driver, heuristic and sampler),
    not just the adapter. Otherwise an old pair could mix with changed rules
    or continuation semantics when a run resumes. Bind any loaded native
    candidate as well; ignored bytecode caches are not source artifacts.
    """
    paths = sorted([*package.rglob("*.py"), *package.rglob("*.so")])
    return {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def bind_output_config(output, config):
    output.mkdir(parents=True, exist_ok=True)
    path = output / "config.json"
    if path.exists():
        if json.loads(path.read_text()) != config:
            raise ValueError("existing output belongs to a different configuration")
    else:
        _publish(path, config)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--allow-legacy", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm", choices=("none", "uniform", "prior", "value", "both"), default="both")
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--leaf-tricks", type=int, choices=(0, 1), default=1)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--select-worlds", type=int, default=30)
    parser.add_argument("--candidate-select-worlds", type=int,
                        help="candidate-only selection N for outcome-blind CPU budget calibration")
    parser.add_argument("--report-worlds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.clusters < 1 or args.workers < 1 or args.select_worlds < 1 or args.report_worlds < 30:
        parser.error("positive clusters/workers/selection and >=30 report worlds required")
    if args.candidate_select_worlds is not None and args.candidate_select_worlds < 1:
        parser.error("candidate-select-worlds must be positive")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    heads = loaded_heads(str(Path(args.checkpoint).resolve()), args.allow_legacy, args.batch_size)
    config = {k: v for k, v in vars(args).items() if k not in {"out", "workers"}}
    config["checkpoint"] = str(Path(args.checkpoint).resolve())
    config["checkpoint_sha256"] = heads.metadata["checkpoint_sha256"]
    # Source changes must not silently mix different policies into one sample.
    package = Path(__file__).resolve().parents[1]
    config["source_sha256"] = execution_source_identity(package)
    config["runtime"] = {"python": platform.python_version(), "platform": platform.platform(),
                         "environment": {k: v for k, v in sorted(os.environ.items())
                                         if k.startswith("SHENGJI_") or k in
                                         {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"}}}
    config["model_metadata"] = heads.metadata
    bind_output_config(args.out, config)
    shards = []
    pending = []
    for cluster in range(args.clusters):
        path = args.out / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    started = time.perf_counter()
    ctx = multiprocessing.get_context("spawn")
    try:
        with ProcessPoolExecutor(max_workers=min(args.workers, max(1, len(pending))), mp_context=ctx) as pool:
            tasks = {pool.submit(run_cluster, config, c): c for c in pending}
            remaining = set(tasks)
            while remaining:
                finished, remaining = wait(remaining, timeout=30, return_when=FIRST_COMPLETED)
                for future in finished:
                    shard = future.result()
                    _publish(args.out / f"cluster-{shard['cluster']:05}.json", shard)
                    shards.append(shard)
                elapsed = time.perf_counter() - started
                done_new = len(shards) - (args.clusters - len(pending))
                eta = (f"{elapsed / done_new * (args.clusters - len(shards)):.1f}s"
                       if done_new else "pending first pair")
                print(f"{len(shards)}/{args.clusters} pairs ({100*len(shards)/args.clusters:.1f}%) "
                      f"elapsed={elapsed:.1f}s eta={eta} workers={args.workers}", flush=True)
    except Exception as exc:
        _publish(args.out / "failure.json", {
            "type": type(exc).__name__, "message": str(exc),
            "completed_clusters": sorted(s["cluster"] for s in shards),
            "recovery": "rerun the identical command; completed mirrored pairs are retained",
        })
        raise
    finally:
        if shards:
            _publish(args.out / "summary.json", summary_for(sorted(shards, key=lambda s: s["cluster"]), config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
