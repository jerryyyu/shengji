"""Fresh DEV gameplay screen for encoder-v3 W32 against encoder-v2 W32.

The two play consumers differ only by their checkpoint.  Both sides use the
same fixed encoder-v2 hybrid-bury evaluator through an independent bury bot;
this is a gameplay screen, not a confirmation or equal-work claim.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import time

from .. import seeds
from ..ai.cwv_policy import shared_evaluator
from ..engine.cards import RANKS
from ..oracle import screen as duel
from .cwv_bury_policy import CWVBuryBot, CWVBuryConfig
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from .cwv_shortlist_screen import CwvTimedPolicy, work_counters as shortlist_work_counters
from .leaf_screen import _game_factory_for
from .search_screen import (_publish, _run_pending, bind_output_config,
                            execution_source_identity)


SCHEMA = "cwv-model-screen-config-v1"
SHARD_SCHEMA = "cwv-model-screen-shard-v1"
SUMMARY_SCHEMA = "cwv-model-screen-summary-v1"
ARM = "encoder-v3"
PLAY_RECIPE = {
    "worlds": 32,
    "selection_worlds": 30,
    "alternatives": 4,
    "batch_size": 128,
    "report_worlds": 300,
    "encoding": "mlp-static",
    "reuse_successors": True,
}
BuryConfig = CWVBuryConfig(max_candidates=32, model_worlds=32,
                           selection_worlds=32, alternatives=4)
BuryConfig = asdict(BuryConfig)


class CwvModelBot:
    """Composition adapter with separate consumer and bury policy owners."""

    def __init__(self, playbot, burybot):
        self.playbot = playbot
        self.burybot = burybot

    def __getattr__(self, name):
        # Every attribute not explicitly owned by bury is a play/declaration
        # attribute.  In particular, sampler/RNG/search telemetry is never
        # accidentally read from the bury helper.
        return getattr(self.playbot, name)

    def decide_play(self, rnd, seat):
        return self.playbot.decide_play(rnd, seat)

    def decide_declare(self, *args, **kwargs):
        return self.playbot.decide_declare(*args, **kwargs)

    def decide_bury(self, rnd, seat):
        return self.burybot.decide_bury(rnd, seat)

    @property
    def last_bury_record(self):
        return self.burybot.last_bury_record


class ModelTimedPolicy(CwvTimedPolicy):
    """Existing play timing/tracing plus separately retained bury evidence."""

    def __init__(self, bot):
        super().__init__(bot)
        self.bury_records = []
        self.bury_decision_cpu_seconds = 0.0
        self.bury_decision_wall_seconds = 0.0

    def decide_bury(self, rnd, seat):
        cpu0, wall0 = time.process_time(), time.perf_counter()
        try:
            return self.bot.decide_bury(rnd, seat)
        finally:
            self.bury_decision_cpu_seconds += time.process_time() - cpu0
            self.bury_decision_wall_seconds += time.perf_counter() - wall0
            record = copy.deepcopy(getattr(self.bot, "last_bury_record", None))
            if record is not None:
                self.bury_records.append({"seat": int(seat), "record": record})


def _checkpoint_sha(evaluator):
    return getattr(evaluator, "checkpoint_sha256", None)


def _verify_evaluator(evaluator, expected_sha, version, label):
    if _checkpoint_sha(evaluator) != expected_sha:
        raise ValueError(f"{label} checkpoint changed between configuration and worker")
    actual = getattr(evaluator, "enc_version", None)
    if type(actual) is not int or actual != version:
        raise ValueError(f"{label} requires encoder v{version}, got v{actual}")


def _evaluator_backend(evaluator):
    backend = getattr(evaluator, "backend", None)
    if backend is not None:
        return backend
    identity = getattr(evaluator, "identity", None)
    return identity().get("backend") if callable(identity) else None


def _verify_backends(values):
    backends = {label: _evaluator_backend(evaluator)
                for label, evaluator in values.items()}
    if any(type(value) is not str or not value for value in backends.values()):
        raise ValueError("all screen evaluators must expose a backend identity")
    if len(set(backends.values())) != 1:
        raise ValueError("candidate, baseline, and bury evaluators must use one backend")
    return backends


def _load_evaluators(config):
    """Load candidate, baseline and fixed-bury evaluators once per process."""
    values = {}
    for label, key, version in (("candidate", "candidate_checkpoint", 3),
                                ("baseline", "baseline_checkpoint", 2),
                                ("bury", "bury_checkpoint", 2)):
        values[label] = shared_evaluator(
            config[key], threads=1, max_batch=128, encoding="mlp-static")
        _verify_evaluator(values[label], config[key + "_sha256"], version, label)
    _verify_backends(values)
    if (_checkpoint_sha(values["bury"]) != _checkpoint_sha(values["baseline"])
            or config["bury_checkpoint_sha256"] != config["baseline_checkpoint_sha256"]):
        raise ValueError("bury checkpoint must have the baseline checkpoint SHA")
    return values


def make_side(config, side, seed, evaluators=None):
    """Build one side: play owns its model; bury owns fixed production model."""
    if side not in ("arm", "baseline"):
        raise ValueError(f"unknown screen side {side!r}")
    evaluators = _load_evaluators(config) if evaluators is None else evaluators
    play_label = "candidate" if side == "arm" else "baseline"
    play = CWVShortlistBot(
        evaluators[play_label], seed=seed,
        config=CWVShortlistConfig(worlds=32, selection_worlds=30,
                                  alternatives=4, batch_size=128,
                                  uniform=False),
        reuse_successors=True)
    play.REPORT_FOLD_WORLDS = 300
    bury = CWVBuryBot(
        evaluators["bury"], seed=seed,
        config=CWVShortlistConfig(worlds=32, selection_worlds=30,
                                  alternatives=4, batch_size=128,
                                  uniform=False),
        arm="hybrid", reuse_successors=True,
        bury_config=CWVBuryConfig(**config["bury_recipe"]),
        # Fly uses a 2s cooperative fallback; this DEV comparison deliberately
        # avoids hardware-sensitive fallback and records the full bury cost.
        serving_budget_seconds=config.get("bury_serving_budget_seconds"))
    return CwvModelBot(play, bury)


def work_counters(bots):
    out = shortlist_work_counters(bots)
    out["bury_decision_cpu_seconds"] = float(sum(
        getattr(bot, "bury_decision_cpu_seconds", 0.0) for bot in bots))
    out["bury_decision_wall_seconds"] = float(sum(
        getattr(bot, "bury_decision_wall_seconds", 0.0) for bot in bots))
    out["bury_seconds"] = out["bury_decision_wall_seconds"]
    return out


def _recipe(config):
    return {
        "play": config["play_recipe"],
        "bury": {"arm": "hybrid", "config": config["bury_recipe"]},
        "candidate_checkpoint_sha256": config["candidate_checkpoint_sha256"],
        "baseline_checkpoint_sha256": config["baseline_checkpoint_sha256"],
        "bury_checkpoint_sha256": config["bury_checkpoint_sha256"],
        "checkpoint_recipe": config.get("checkpoint_recipe", {}),
        "bury_serving_budget_seconds": config.get("bury_serving_budget_seconds"),
        "trump_ranks": config["trump_ranks"],
    }


def run_cluster(config, cluster):
    evaluators = _load_evaluators(config)
    created = []

    def factory(_config, side, seed):
        wrapped = ModelTimedPolicy(make_side(config, side, seed, evaluators))
        created.append((side, wrapped))
        return wrapped

    rank = config["trump_ranks"][cluster % len(config["trump_ranks"])]
    base = duel.build_config(arm="none", select_worlds=30, report_worlds=300)
    seed = config["seed0"] + cluster
    rows = [duel.play_screen_round(
        base, cluster, seed, mirror, bot_factory=factory,
        counter_fn=work_counters, game_factory=_game_factory_for(rank))
        for mirror in (0, 1)]
    if len(created) != 8:
        raise ValueError("screen driver did not construct four policies per mirror")
    for record, _timing in rows:
        if record["trump_rank"] != rank:
            raise ValueError(f"cluster {cluster} dealt rank {record['trump_rank']!r}, expected {rank!r}")
        record["arm"] = ARM
    for _record, timing in rows:
        # Keep bury cost visible beside the inherited search timing receipt;
        # the full counters remain in the round record for aggregation.
        work = _record.get("work", {})
        for side in ("arm", "baseline"):
            counters = work.get(side, {})
            timing[f"{side}_bury_cpu_seconds"] = float(
                counters.get("bury_decision_cpu_seconds", 0.0))
            timing[f"{side}_bury_wall_seconds"] = float(
                counters.get("bury_decision_wall_seconds", 0.0))
    return {
        "schema": SHARD_SCHEMA, "cluster": cluster, "seed": seed,
        "rank": rank, "recipe": _recipe(config),
        "config_sha256": config.get("config_sha256"),
        "records": [record for record, _ in rows],
        "timings": [timing for _, timing in rows],
        "decision_traces": [{
            "mirror": i // 4, "side": side,
            "decisions": policy.decisions,
            "bury_records": policy.bury_records,
            "bury_cpu_seconds": policy.bury_decision_cpu_seconds,
            "bury_wall_seconds": policy.bury_decision_wall_seconds,
        } for i, (side, policy) in enumerate(created)],
    }


def reopen_shard(path, config, cluster):
    shard = json.loads(path.read_text())
    rows = shard.get("records", [])
    seed = config["seed0"] + cluster
    rank = config["trump_ranks"][cluster % len(config["trump_ranks"])]
    timings = shard.get("timings", [])
    if (shard.get("schema") != SHARD_SCHEMA or shard.get("cluster") != cluster
            or shard.get("seed") != seed or shard.get("rank") != rank
            or shard.get("recipe") != _recipe(config)
            or shard.get("config_sha256") != config.get("config_sha256")
            or len(rows) != 2 or [r.get("mirror") for r in rows] != [0, 1]
            or len(timings) != 2
            or [t.get("mirror") for t in timings] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank or r.get("arm") != ARM
                   for r in rows)
            or any(t.get("cluster") != cluster or t.get("seed") != seed
                   or t.get("mirror") not in (0, 1) for t in timings)):
        raise ValueError("completed shard does not match its mirrored pair, rank, or recipe")
    return shard


def _complete(shards, config):
    if len(shards) != config["clusters"]:
        return False
    clusters = {shard.get("cluster") for shard in shards}
    if clusters != set(range(config["clusters"])):
        return False
    expected_recipe = _recipe(config)
    for shard in shards:
        cluster = shard.get("cluster")
        seed = config["seed0"] + cluster if type(cluster) is int else None
        rank = (config["trump_ranks"][cluster % len(config["trump_ranks"])]
                if type(cluster) is int and cluster >= 0 else None)
        rows = shard.get("records", [])
        if (shard.get("schema") != SHARD_SCHEMA
                or seed is None or shard.get("seed") != seed
                or shard.get("rank") != rank
                or shard.get("recipe") != expected_recipe
                or shard.get("config_sha256") != config.get("config_sha256")
                or len(rows) != 2
                or [r.get("mirror") for r in rows] != [0, 1]
                or any(r.get("cluster") != cluster or r.get("seed") != seed
                       or r.get("trump_rank") != rank or r.get("arm") != ARM
                       for r in rows)):
            return False
    return True


def summary_for(shards, config):
    complete = _complete(shards, config)
    result = {
        "schema": SUMMARY_SCHEMA,
        "arm": ARM,
        "claim": "fresh DEV encoder-v3 versus encoder-v2 gameplay; not confirmation or deployment",
        "label": "fresh DEV gameplay screen; not confirmation",
        "arm_description": "encoder-v3 W32 play versus encoder-v2 W32 play; fixed hybrid bury on both sides",
        "equal_work_strength_claim": False,
        "completed_pairs": len(shards),
        "requested_pairs": config["clusters"],
        "completed_clusters": len(shards),
        "requested_clusters": config["clusters"],
        "complete": complete,
        "config": config,
        "checkpoint_sha256": {
            "candidate": config["candidate_checkpoint_sha256"],
            "baseline": config["baseline_checkpoint_sha256"],
            "bury": config["bury_checkpoint_sha256"],
        },
    }
    # Never read partial outcomes as a result or use them to alter stopping.
    if not complete:
        result.update({"outcomes_read": False, "comparisons": {},
                       "work_totals": {},
                       "incomplete_reason": "all planned mirrored pairs are required"})
        return result
    records = [record for shard in sorted(shards, key=lambda s: s["cluster"])
               for record in shard["records"]]
    base = duel.build_config(arm="none", select_worlds=30, report_worlds=300)
    out = duel.summarize(records, base, seed0=config["seed0"], replicates=1000)
    result.update(out)
    result.update({
        "schema": SUMMARY_SCHEMA,
        "arm": ARM,
        "claim": "fresh DEV encoder-v3 versus encoder-v2 gameplay; not confirmation or deployment",
        "label": "fresh DEV gameplay screen; not confirmation",
        "arm_description": "encoder-v3 W32 play versus encoder-v2 W32 play; fixed hybrid bury on both sides",
        "equal_work_strength_claim": False,
        "completed_pairs": len(shards), "requested_pairs": config["clusters"],
        "completed_clusters": len(shards), "requested_clusters": config["clusters"],
        "complete": True, "config": config,
        "outcomes_read": True,
    })
    totals = result.get("work_totals", {})
    result["bury_cost"] = {
        side: {
            "cpu_seconds": totals.get(side, {}).get("bury_decision_cpu_seconds", 0.0),
            "wall_seconds": totals.get(side, {}).get("bury_decision_wall_seconds", 0.0),
        }
        for side in ("arm", "baseline")
    }
    return result


def _config_sha(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--baseline-checkpoint", type=Path, required=True)
    parser.add_argument("--bury-checkpoint", type=Path, required=True)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--clusters", type=int, default=260)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed-registry", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.clusters < 1 or args.workers < 1:
        parser.error("clusters and workers must be positive")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    registry = args.seed_registry.resolve()
    if not registry.is_file():
        parser.error(f"--seed-registry must name an existing registry file: {registry}")

    paths = {
        "candidate_checkpoint": str(args.checkpoint.resolve()),
        "baseline_checkpoint": str(args.baseline_checkpoint.resolve()),
        "bury_checkpoint": str(args.bury_checkpoint.resolve()),
    }
    # Loading once here binds the exact checkpoint hashes and identities before
    # registration; workers repeat the same verification in their process.
    loaded = {}
    for label, key in (("candidate", "candidate_checkpoint"),
                       ("baseline", "baseline_checkpoint"),
                       ("bury", "bury_checkpoint")):
        loaded[label] = shared_evaluator(paths[key], threads=1, max_batch=128,
                                         encoding="mlp-static")
    hashes = {f"{label}_checkpoint_sha256": _checkpoint_sha(evaluator)
              for label, evaluator in loaded.items()}
    if any(not value for value in hashes.values()):
        parser.error("all checkpoint evaluators must expose checkpoint SHA256")
    if hashes["bury_checkpoint_sha256"] != hashes["baseline_checkpoint_sha256"]:
        parser.error("--bury-checkpoint must have the same SHA256 as --baseline-checkpoint")
    for label, version in (("candidate", 3), ("baseline", 2), ("bury", 2)):
        actual = getattr(loaded[label], "enc_version", None)
        if type(actual) is not int or actual != version:
            parser.error(f"{label} checkpoint must use encoder v{version}, got v{actual}")
    try:
        backends = _verify_backends(loaded)
    except ValueError as exc:
        parser.error(str(exc))

    def evaluator_identity(evaluator):
        identity = getattr(evaluator, "identity", None)
        value = identity() if callable(identity) else {
            "checkpoint_sha256": _checkpoint_sha(evaluator),
        }
        value = dict(value)
        value["enc_version"] = evaluator.enc_version
        value["backend"] = _evaluator_backend(evaluator)
        return value

    config = {
        "schema": SCHEMA, "arm": ARM, **paths, **hashes,
        "bury_recipe": BuryConfig, "bury_serving_budget_seconds": None,
        "play_recipe": PLAY_RECIPE,
        "checkpoint_recipe": {label: evaluator_identity(loaded[label])
                              for label in ("candidate", "baseline", "bury")},
        "backend": backends["candidate"],
        "seed0": args.seed0, "clusters": args.clusters,
        "trump_ranks": list(RANKS),
        "population": "all-13-ranks-cycle",
        "seed_registry": str(registry),
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1]),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "environment": {k: v for k, v in sorted(os.environ.items())
                                    if k.startswith("SHENGJI_") or k in (
                                        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                        "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS")}},
    }
    config["config_sha256"] = _config_sha(config)
    bind_output_config(args.out, config)

    receipt = seeds.check_and_register(
        name=f"cwv-model-screen:{args.out.resolve()}:{config['config_sha256'][:16]}",
        purpose="screen", seed0=args.seed0, clusters=args.clusters,
        refuse=None, resume=True, path=registry,
        note=f"fresh encoder-v3-vs-v2 W32 screen; output={args.out.resolve()}",
        what=f"cwv_model_screen run {args.out.resolve()}")
    _publish(args.out / "seed_registry_receipt.json", receipt)

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
        _publish(args.out / "summary.json", summary_for(shards, config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
