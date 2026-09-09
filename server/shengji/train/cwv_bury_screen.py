"""Three-arm paired DEV bury screen with identical W32 play afterward.

Each independent natural deal is replayed with heuristic, MC and hybrid bury.
Only the banker bury changes. Every seat uses W32 and the same play RNG seed
across arms. This is a paired counterfactual round comparison, not a multi-round
match, mirrored opposing-team duel, or production promotion test.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from ..ai.cwv_policy import shared_evaluator
from ..oracle.screen import work_counters
from ..rl.value_afterstate import signed_level_category, category_signed_level
from .cwv_bury_diagnostic import capture_state, reopen_state, derived_seed
from .cwv_bury_panel import atomic_json
from .cwv_bury_readout import interval
from .cwv_bury_policy import make_cwv_bury_bot
from .search_screen import _run_pending, bind_output_config, execution_source_identity

ARMS = ("heuristic", "mc", "hybrid")
START_INDEX = 64  # diagnostic roots 0..63 are excluded


def banker_utility(points):
    """Existing paired-screen convention: a win counts at least one level."""
    if points >= 80:
        return -max(1, (points - 80) // 40)
    return 3 if points == 0 else 2 if points < 40 else 1


def run_cluster(config, cluster):
    output = Path(config["output"])
    state_index = START_INDEX + cluster
    row = capture_state(state_index)
    evaluator = shared_evaluator(config["checkpoint"], threads=1, max_batch=128, encoding="mlp-static")
    if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
        raise ValueError("checkpoint mismatch in gameplay worker")
    records = []
    for arm in ARMS:
        path = output / f"arm-{cluster:04d}-{arm}.json"
        if path.exists():
            record = json.loads(path.read_text())
            if record["config_sha256"] != config["config_sha256"] or record["state"] != row or record["arm"] != arm:
                raise ValueError("completed arm binding mismatch")
            records.append(record)
            continue
        rnd = reopen_state(row)
        bots = [make_cwv_bury_bot(evaluator, seed=derived_seed(
                    f"cwv-bury-gameplay-v1:{state_index}", seat), arm=arm)
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
    result = {"schema": "cwv-bury-gameplay-summary-v1", "completed_deals": len(shards),
              "requested_deals": config["deals"], "complete": len(shards) == config["deals"],
              "claim": "exploratory rank2 single-round paired comparison; not promotion or equivalence",
              "primary_metric": "banker signed level utility; wins/losses count at least 1, same convention as paired screen",
              "no_outcome_based_extension": True, "comparisons": {}, "cost": {}}
    for a, b in (("mc", "heuristic"), ("hybrid", "heuristic"), ("hybrid", "mc")):
        pairs = [(next(r for r in s["records"] if r["arm"] == a),
                  next(r for r in s["records"] if r["arm"] == b)) for s in shards]
        result["comparisons"][f"{a}_minus_{b}"] = {
            "utility": interval([x["banker_utility"] - y["banker_utility"] for x, y in pairs]),
            "banker_win_rate_difference": interval([x["banker_won"] - y["banker_won"] for x, y in pairs]),
            "attacker_points": interval([x["attacker_points"] - y["attacker_points"] for x, y in pairs]),
            "different_bury_deals": sum(x["buried"] != y["buried"] for x, y in pairs)}
    for arm in ARMS:
        rows = [r for s in shards for r in s["records"] if r["arm"] == arm]
        result["cost"][arm] = {"total_wall_seconds": sum(r["wall_seconds"] for r in rows),
                               "total_cpu_seconds": sum(r["cpu_seconds"] for r in rows),
                               "total_bury_seconds": sum(r["bury"]["elapsed_seconds"] for r in rows)}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--deals", type=int, default=256)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int, help="timing slice only; same fixed population on resume")
    args = parser.parse_args(argv)
    if min(args.deals, args.workers) < 1 or (args.limit is not None and args.limit < 1):
        parser.error("positive deals/workers/limit required")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 required")
    evaluator = shared_evaluator(args.checkpoint, threads=1, max_batch=128, encoding="mlp-static")
    config = {"schema": "cwv-bury-gameplay-config-v1", "deals": args.deals,
              "output": str(args.out.resolve()), "start_index": START_INDEX,
              "checkpoint": str(Path(args.checkpoint).resolve()),
              "checkpoint_sha256": evaluator.checkpoint_sha256,
              "w32": {"worlds": 32, "selection_worlds": 30, "alternatives": 4,
                      "report_worlds": 300, "reuse_successors": True},
              "bury": {"model_worlds": 32, "selection_worlds": 32, "alternatives": 4,
                       "leaf": "one heuristic trick", "mc_rule": "existing objective and margin"},
              "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1]),
              "environment": {k: v for k, v in os.environ.items() if k.startswith("SHENGJI_")}}
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
