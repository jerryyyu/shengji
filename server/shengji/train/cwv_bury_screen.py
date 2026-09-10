"""Three-arm paired DEV bury screen with identical W32 play afterward.

Each independent natural deal is replayed with heuristic, MC and hybrid bury.
Only the banker bury changes. Every seat uses W32 and the same play RNG seed
across arms. This is a paired counterfactual round comparison, not a multi-round
match, mirrored opposing-team duel, or production promotion test.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time
from collections import Counter

import numpy as np

from ..ai.cwv_policy import shared_evaluator
from ..engine.cards import RANKS, points as card_points
from ..oracle.screen import work_counters
from ..rl.value_afterstate import signed_level_category, category_signed_level
from .cwv_bury_diagnostic import (
    ALLRANK_NAMESPACE, ALLRANK_POPULATION, capture_allrank_state,
    capture_state, reopen_state, derived_seed,
)
from .cwv_bury_panel import atomic_json
from .cwv_bury_readout import interval
from .cwv_bury_policy import CWVBuryConfig, make_cwv_bury_bot
from .search_screen import _run_pending, bind_output_config, execution_source_identity

ARMS = ("heuristic", "mc", "hybrid")
START_INDEX = 64  # diagnostic roots 0..63 are excluded
ALLRANK_DEALS = 1040
POPULATIONS = ("legacy-rank2", ALLRANK_POPULATION)


def scaling_recipes():
    """Fixed six-arm DEV screen; model ranking and play settings stay fixed."""
    def recipe(arm, candidates=32, worlds=32):
        return {"arm": arm, "bury_config": asdict(CWVBuryConfig(
            max_candidates=candidates, selection_worlds=worlds))}
    return {
        "mc": recipe("mc"),
        "hybrid": recipe("hybrid"),
        "hybrid_pool64": recipe("hybrid", candidates=64),
        "hybrid_mc128": recipe("hybrid", worlds=128),
        "hybrid_pool64_mc128": recipe("hybrid", candidates=64, worlds=128),
        "mc_pool64_mc128": recipe("mc", candidates=64, worlds=128),
    }


def screen_arms(config):
    return tuple(config["arm_recipes"]) if "arm_recipes" in config else ARMS


def _population(config):
    return config.get("population", "legacy-rank2")


def _state_for_config(config, index):
    if _population(config) == ALLRANK_POPULATION:
        return capture_allrank_state(index)
    return capture_state(index)


def stratified_interval(values, shards, *, reps=4000, seed=782321):
    """Bootstrap paired deltas within equally weighted rank/banker strata."""
    if len(values) != len(shards) or not values:
        raise ValueError("stratified interval needs aligned nonempty values/shards")
    ordered = sorted(zip(shards, values), key=lambda pair: pair[0]["cluster"])
    groups = {}
    for shard, value in ordered:
        records = shard.get("records") or []
        if not records:
            raise ValueError("stratified interval shard has no records")
        state = records[0]["state"]
        key = (state.get("setup", {}).get("trump_rank"),
               state.get("initial_banker"))
        if None in key:
            raise ValueError("all-rank state missing stratum identity")
        groups.setdefault(key, []).append(float(value))
    if not groups or any(not values_ or len(values_) != len(next(iter(groups.values())))
                         for values_ in groups.values()):
        raise ValueError("all-rank population strata are unbalanced")
    # Draw the same number from every stratum on each replicate; this keeps
    # every rank/banker cell equally weighted even if shard order changes.
    rng = np.random.default_rng(seed)
    n = len(next(iter(groups.values())))
    boot = np.zeros(reps, dtype=float)
    arrays = [np.asarray(groups[key], dtype=float) for key in sorted(groups)]
    for array in arrays:
        draws = rng.integers(0, n, size=(reps, n))
        boot += array[draws].mean(axis=1)
    boot /= len(arrays)
    x = np.asarray(values, dtype=float)
    return {"mean": float(x.mean()),
            "ci95": np.quantile(boot, [.025, .975]).tolist(),
            "n_independent_states": len(x),
            "resampling": (f"{reps} paired bootstrap replicates within "
                           "rank×initial_banker strata")}


def banker_utility(points):
    """Existing paired-screen convention: a win counts at least one level."""
    if points >= 80:
        return -max(1, (points - 80) // 40)
    return 3 if points == 0 else 2 if points < 40 else 1


def run_cluster(config, cluster):
    output = Path(config["output"])
    state_index = config.get("start_index", START_INDEX) + cluster
    row = _state_for_config(config, state_index)
    evaluator = shared_evaluator(config["checkpoint"], threads=1, max_batch=128, encoding="mlp-static")
    if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
        raise ValueError("checkpoint mismatch in gameplay worker")
    records = []
    for arm in screen_arms(config):
        path = output / f"arm-{cluster:04d}-{arm}.json"
        if path.exists():
            record = json.loads(path.read_text())
            if record["config_sha256"] != config["config_sha256"] or record["state"] != row or record["arm"] != arm:
                raise ValueError("completed arm binding mismatch")
            records.append(record)
            continue
        rnd = reopen_state(row)
        kwargs = {"arm": arm}
        if "arm_recipes" in config:
            recipe = config["arm_recipes"][arm]
            kwargs = {"arm": recipe["arm"],
                      "bury_config": CWVBuryConfig(**recipe["bury_config"])}
        play_namespace = (ALLRANK_NAMESPACE if _population(config) == ALLRANK_POPULATION
                          else "cwv-bury-gameplay-v1")
        play_label = (f"{play_namespace}:play:{state_index}"
                      if _population(config) == ALLRANK_POPULATION
                      else f"{play_namespace}:{state_index}")
        bots = [make_cwv_bury_bot(evaluator, seed=derived_seed(
                    play_label, seat), **kwargs)
                for seat in range(4)]
        started, cpu_start = time.perf_counter(), time.process_time()
        banker = rnd.banker
        chosen = bots[banker].decide_bury(rnd, banker)
        bury_record = bots[banker].last_bury_record
        rnd.bury(banker, chosen)
        transcript = []
        while rnd.phase == "play":
            seat = rnd.turn
            attempted = bots[seat].decide_play(rnd, seat)
            rnd.play(seat, attempted)
            transcript.append({"seat": seat, "attempted": list(attempted)})
        points = rnd.attacker_points
        record = {"arm": arm, "state": row, "bury": bury_record,
                  "banker_won": int(points < 80), "attacker_points": points,
                  "banker_utility": banker_utility(points),
                  "model_unit_utility": category_signed_level(signed_level_category(points, False)),
                  "kitty_bonus": rnd.kitty_bonus, "buried": list(rnd.buried),
                  "transcript": transcript, "work": work_counters(bots),
                  "wall_seconds": time.perf_counter() - started,
                  "cpu_seconds": time.process_time() - cpu_start,
                  "config_sha256": config["config_sha256"]}
        atomic_json(path, record)
        records.append(record)
    return {"schema": "cwv-bury-gameplay-shard-v1", "cluster": cluster,
            "config_sha256": config["config_sha256"], "records": records}


def summarize(shards, config):
    population = _population(config)
    if population == ALLRANK_POPULATION:
        shards = sorted(shards, key=lambda shard: shard["cluster"])
    result = {"schema": "cwv-bury-gameplay-summary-v1", "completed_deals": len(shards),
              "requested_deals": config["deals"], "complete": len(shards) == config["deals"],
              "claim": "exploratory rank2 single-round paired comparison; not promotion or equivalence",
              "primary_metric": "banker signed level utility; wins/losses count at least 1, same convention as paired screen",
              "no_outcome_based_extension": True, "comparisons": {}, "cost": {}}
    comparisons = (("mc", "heuristic"), ("hybrid", "heuristic"), ("hybrid", "mc"))
    if "arm_recipes" in config:
        comparisons = (
            ("hybrid", "mc"),
            ("hybrid_pool64", "hybrid"),
            ("hybrid_mc128", "hybrid"),
            ("hybrid_pool64_mc128", "hybrid"),
            ("hybrid_pool64_mc128", "mc_pool64_mc128"),
            ("mc_pool64_mc128", "mc"),
            ("hybrid_pool64_mc128", "hybrid_pool64"),
            ("hybrid_pool64_mc128", "hybrid_mc128"),
        )
        result["comparisons_are_exploratory"] = True
        result["intervals"] = "nominal 95%; multiple comparisons, no promotion claim"
        result["arm_recipes"] = config["arm_recipes"]
    if population == ALLRANK_POPULATION:
        result["claim"] = ("exploratory all-rank known-banker single-round paired "
                            "comparison panel; not a human deal distribution, "
                            "promotion or equivalence")
        rank_counts = Counter()
        suit_counts = Counter()
        for shard in shards:
            state = shard["records"][0]["state"]
            rank_counts[state["setup"]["trump_rank"]] += 1
            suit_counts["NT" if state["setup"].get("trump_is_nt")
                        else state["setup"].get("trump_suit")] += 1
        result["rank_counts"] = dict(sorted(rank_counts.items()))
        result["trump_suit_counts"] = dict(sorted(suit_counts.items(),
                                                    key=lambda item: str(item[0])))
        result["nt_count"] = suit_counts.get("NT", 0)
        result["population_counts"] = {"ranks": result["rank_counts"],
                                        "trump_suits": result["trump_suit_counts"],
                                        "no_trump": result["nt_count"]}
    for a, b in comparisons:
        pairs = [(next(r for r in s["records"] if r["arm"] == a),
                  next(r for r in s["records"] if r["arm"] == b)) for s in shards]
        metric_interval = (lambda values: stratified_interval(values, shards)
                           if population == ALLRANK_POPULATION else interval(values))
        buried_points = lambda record: sum(card_points(card) for card in record["buried"])
        result["comparisons"][f"{a}_minus_{b}"] = {
            "utility": metric_interval([x["banker_utility"] - y["banker_utility"] for x, y in pairs]),
            "banker_win_rate_difference": metric_interval([x["banker_won"] - y["banker_won"] for x, y in pairs]),
            "attacker_points": metric_interval([x["attacker_points"] - y["attacker_points"] for x, y in pairs]),
            "kitty_bonus": metric_interval([x["kitty_bonus"] - y["kitty_bonus"] for x, y in pairs]),
            "different_bury_deals": sum(
                (sorted(x["buried"]) != sorted(y["buried"]))
                if population == ALLRANK_POPULATION else (x["buried"] != y["buried"])
                for x, y in pairs)}
        if population == ALLRANK_POPULATION:
            same_bury = [sorted(x["buried"]) == sorted(y["buried"])
                         for x, y in pairs]
            transcript_mismatch = [same and x["transcript"] != y["transcript"]
                                   for same, (x, y) in zip(same_bury, pairs)]
            outcome_mismatch = [
                same and (x["attacker_points"], x["kitty_bonus"]) !=
                (y["attacker_points"], y["kitty_bonus"])
                for same, (x, y) in zip(same_bury, pairs)]
            buried_delta = [buried_points(x) - buried_points(y) for x, y in pairs]
            kitty_ge80_delta = [int(x["kitty_bonus"] >= 80) -
                                int(y["kitty_bonus"] >= 80) for x, y in pairs]
            contrast = result["comparisons"][f"{a}_minus_{b}"]
            contrast.update({
                "same_bury_count": sum(same_bury),
                "different_bury_deals": len(pairs) - sum(same_bury),
                "same_bury_transcript_mismatch_count": sum(transcript_mismatch),
                "same_bury_outcome_mismatch_count": sum(outcome_mismatch),
                "buried_points_delta": metric_interval(buried_delta),
                "kitty_ge80_difference": metric_interval(kitty_ge80_delta),
            })
    for arm in screen_arms(config):
        rows = [r for s in shards for r in s["records"] if r["arm"] == arm]
        result["cost"][arm] = {"total_wall_seconds": sum(r["wall_seconds"] for r in rows),
                               "total_cpu_seconds": sum(r["cpu_seconds"] for r in rows),
                               "total_bury_seconds": sum(r["bury"]["elapsed_seconds"] for r in rows),
                               "mean_bury_seconds": sum(r["bury"]["elapsed_seconds"] for r in rows) / len(rows),
                               "full_bury_rollouts": sum(r["bury"].get("mc_rollouts", 0) for r in rows),
                               "model_positions": sum(r["bury"].get("model_positions", 0) for r in rows),
                               "mean_candidate_count": sum(len(r["bury"].get("candidates", [])) for r in rows) / len(rows)}
        if population == ALLRANK_POPULATION:
            bury_seconds = np.asarray([r["bury"]["elapsed_seconds"] for r in rows], dtype=float)
            candidate_counts = np.asarray([len(r["bury"].get("candidates", []))
                                           for r in rows], dtype=float)
            kitty = np.asarray([r["kitty_bonus"] for r in rows], dtype=float)
            result["cost"][arm].update({
                "bury_latency_p95_seconds": float(np.quantile(bury_seconds, .95)),
                "bury_latency_p99_seconds": float(np.quantile(bury_seconds, .99)),
                "max_candidate_count": int(candidate_counts.max()),
                "kitty_nonzero_count": int(np.count_nonzero(kitty)),
                "kitty_ge80_count": int(np.count_nonzero(kitty >= 80)),
                "kitty_bonus_max": int(kitty.max()),
            })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--population", choices=POPULATIONS, default="legacy-rank2")
    parser.add_argument("--deals", type=int)
    parser.add_argument("--start-index", type=int, default=None,
                        help="first natural deal index; use a fresh range for an extension")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--scaling", action="store_true",
                        help="fixed six-arm candidate-pool/MC-world DEV scaling screen")
    parser.add_argument("--limit", type=int, help="timing slice only; same fixed population on resume")
    args = parser.parse_args(argv)
    if args.deals is None:
        args.deals = ALLRANK_DEALS if args.population == ALLRANK_POPULATION else 256
    if args.start_index is None:
        args.start_index = 0 if args.population == ALLRANK_POPULATION else START_INDEX
    if min(args.deals, args.workers) < 1 or (args.limit is not None and args.limit < 1):
        parser.error("positive deals/workers/limit required")
    if args.population == ALLRANK_POPULATION:
        if args.deals % 52 or args.start_index < 0 or args.start_index % 52:
            parser.error("all-rank population requires deals/start-index multiples of 52")
        if args.scaling:
            parser.error("--scaling is unavailable for all-rank population")
    elif args.start_index < START_INDEX:
        parser.error("start-index must exclude diagnostic indices 0..63")
    if args.scaling and args.start_index < 1088:
        parser.error("scaling must exclude the completed bury population: start-index >=1088")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 required")
    evaluator = shared_evaluator(args.checkpoint, threads=1, max_batch=128, encoding="mlp-static")
    config = {"schema": "cwv-bury-gameplay-config-v1", "deals": args.deals,
              "output": str(args.out.resolve()), "start_index": args.start_index,
              "checkpoint": str(Path(args.checkpoint).resolve()),
              "checkpoint_sha256": evaluator.checkpoint_sha256,
              "w32": {"worlds": 32, "selection_worlds": 30, "alternatives": 4,
                      "report_worlds": 300, "reuse_successors": True},
              "bury": {"model_worlds": 32, "selection_worlds": 32, "alternatives": 4,
                       "leaf": "one heuristic trick", "mc_rule": "existing objective and margin"},
              "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1]),
              "environment": {k: v for k, v in os.environ.items() if k.startswith("SHENGJI_")}}
    if args.population == ALLRANK_POPULATION:
        config["population"] = ALLRANK_POPULATION
        config["namespace"] = ALLRANK_NAMESPACE
        config["schedule"] = {"ranks": list(RANKS),
                               "bankers": 4, "deals_per_rank_banker": args.deals // 52}
    if args.scaling:
        config["arm_recipes"] = scaling_recipes()
        config["claim"] = "fixed-count exploratory scaling; no outcome-driven extension or deployment"
    config["config_sha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.deals):
        path = args.out / f"cluster-{cluster:05d}.json"
        if path.exists():
            shard = json.loads(path.read_text())
            if shard["config_sha256"] != config["config_sha256"] or shard["cluster"] != cluster:
                raise ValueError("completed deal binding mismatch")
            shards.append(shard)
        else:
            pending.append(cluster)
    if args.limit:
        pending = pending[:args.limit]
    _run_pending(config, pending, shards, output=args.out, workers=args.workers, task_fn=run_cluster)
    if len(shards) == args.deals:
        result = summarize(shards, config)
        atomic_json(args.out / "summary.json", result)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
