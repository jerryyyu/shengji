"""Outcome-blind conditional pair-eager screen with fixed W32/hybrid play.

Enumerate a fixed deal population before any gameplay. Play both arms only for
deal/team pairs whose final declaration differs. This measures the effect
conditional on exposure; it must not be reported as an all-deal strength gain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from . import declare_screen as screen
from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity


def final_declaration(rnd):
    return {"declaration": rnd.declaration, "banker": rnd.banker,
            "trump_suit": rnd.trump_suit or "NT"}


def selection_plan(start, deals):
    """No bot construction, bury, play or outcome reads during selection."""
    selected = []
    for index in range(start, start+deals):
        spec = screen.deal_spec(index)
        pairs = []
        for team in (0, 1):
            states = {arm: final_declaration(screen.prepare_round(spec, arm, team)[0])
                      for arm in screen.ARMS}
            if states["baseline"] != states["pair-eager"]:
                pairs.append({"team": team, "states": states})
        if pairs:
            selected.append({"spec": spec, "pairs": pairs})
    return {"start_index": start, "population_deals": deals, "population_deal_teams": 2*deals,
            "criterion": "final declaration/banker/trump differs before bury or play",
            "selected": selected, "selected_deals": len(selected),
            "selected_deal_teams": sum(len(r["pairs"]) for r in selected)}


def run_cluster(config, cluster):
    selected = config["selection"]["selected"][cluster]
    spec = selected["spec"]
    records = []
    for pair in selected["pairs"]:
        team = pair["team"]
        for arm in screen.ARMS:
            path = Path(config["output"])/f"arm-{cluster:05d}-{team}-{arm}.json"
            if path.exists():
                row = screen.read_record(path, config, spec, arm, team)
                if row["final_declaration"] != pair["states"][arm]:
                    raise ValueError("completed conditional declaration differs")
            else:
                started, cpu = time.perf_counter(), time.process_time()
                rnd, events = screen.prepare_round(spec, arm, team)
                if final_declaration(rnd) != pair["states"][arm]:
                    raise ValueError("conditional selection changed before gameplay")
                bots = screen.make_bots(config, spec)
                outcome = screen.finish_round(rnd, bots, team)
                from ..oracle.screen import work_counters
                row = {"spec": spec, "arm": arm, "focal_team": team,
                       "config_sha256": config["config_sha256"], "events": events,
                       "final_declaration": pair["states"][arm], "outcome": outcome,
                       "work": work_counters(bots), "wall_seconds": time.perf_counter()-started,
                       "cpu_seconds": time.process_time()-cpu}
                _publish(path, row)
            records.append(row)
    return {"cluster": cluster, "config_sha256": config["config_sha256"], "records": records}


def summarize(shards, config):
    from .cwv_bury_readout import interval
    metrics = ("focal_signed_levels", "focal_won", "kitty_bonus", "kitty_ge80")
    values = {m: [] for m in metrics}
    pairs = 0
    rows = []
    for shard in shards:
        records = shard["records"]
        rows.extend(records)
        teams = sorted({r["focal_team"] for r in records})
        pairs += len(teams)
        differences = {m: [] for m in metrics}
        for team in teams:
            base, treatment = [next(r for r in records if r["focal_team"] == team and r["arm"] == arm)
                               for arm in screen.ARMS]
            for m in metrics:
                differences[m].append(treatment["outcome"][m]-base["outcome"][m])
        for m in metrics:
            values[m].append(sum(differences[m])/len(teams))
    return {"scope": "conditional DEV effect among deals with changed final declarations; not all-deal strength",
            "complete": len(shards) == config["selection"]["selected_deals"],
            "completed_independent_deals": len(shards), "completed_deal_team_pairs": pairs,
            "selection": {k:v for k,v in config["selection"].items() if k != "selected"},
            "comparisons": {m: interval(v) for m,v in values.items()} if shards else {},
            "cost": {arm: {"cpu_seconds": sum(r["cpu_seconds"] for r in rows if r["arm"] == arm),
                             "wall_seconds_sum": sum(r["wall_seconds"] for r in rows if r["arm"] == arm)}
                     for arm in screen.ARMS}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=53)
    parser.add_argument("--population-deals", type=int, default=1060)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if (args.start_index < 0 or args.start_index % 53 or args.population_deals <= 0
            or args.population_deals % 53 or not 1 <= args.workers <= 4
            or (args.limit is not None and args.limit < 1)):
        parser.error("whole 53-cell populations, one to four workers and positive limit required")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 required")
    args.out.mkdir(parents=True, exist_ok=True)
    plan_path = args.out/"selection.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_bytes())
        if plan["start_index"] != args.start_index or plan["population_deals"] != args.population_deals:
            raise ValueError("completed population selection differs")
        # A crash can publish selection before config binds it. Reproduce the
        # entire cheap census in that startup window, not just included pairs:
        # checking selected pairs alone cannot detect omitted eligible deals.
        if not (args.out/"config.json").exists():
            if plan != selection_plan(args.start_index, args.population_deals):
                raise ValueError("unbound cached selection differs from full census")
    else:
        plan = selection_plan(args.start_index, args.population_deals)
        _publish(plan_path, plan)
    config = {"schema": "declare-conditional-v1", "mode": "play", "selection": plan,
              "output": str(args.out.resolve()), "checkpoint": str(args.checkpoint.resolve()),
              "checkpoint_sha256": hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
              "continuation": "W32 K4 N30 R300 reuse; hybrid bury32/32/32 K4; no serving deadline",
              "source": execution_source_identity(Path(__file__).resolve().parents[1]),
              "environment": {k:v for k,v in os.environ.items() if k.startswith("SHENGJI_")}}
    config["config_sha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(plan["selected_deals"]):
        path = args.out/f"cluster-{cluster:05d}.json"
        if path.exists():
            row = json.loads(path.read_bytes())
            if row["cluster"] != cluster or row["config_sha256"] != config["config_sha256"]:
                raise ValueError("completed conditional cluster differs")
            shards.append(row)
        else:
            pending.append(cluster)
    _run_pending(config, pending[:args.limit] if args.limit else pending, shards,
                 output=args.out, workers=args.workers, task_fn=run_cluster)
    result = summarize(shards, config)
    _publish(args.out/"summary.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
