"""Before-deal declaration comparison; W32/hybrid bury stays fixed afterward.

Census mode never plays or scores a round. Gameplay changes declarations for
one team, averages its two seat mirrors within each independent deal, and
reports utility from that team's perspective even if declaration changes the
banker. No claim about human grace-window/pass timing or multi-round strength.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import time

from ..engine.cards import RANKS
from ..engine.round import Round, actual_play_after
from .declare_policy import capture_declare_view, choose_declaration

ARMS = ("baseline", "pair-eager")
NAMESPACE = "declare-pair-eager-dev-20260910-v1"


def derived_seed(label, index):
    return int.from_bytes(hashlib.sha256(
        f"{NAMESPACE}:{label}:{index}".encode()).digest()[:8], "big")


def deal_spec(index):
    """52 rank/banker cells plus a real rank-2 first-round cell per block."""
    cell = index % 53
    return {"index": index, "seed": derived_seed("deal", index),
            "rank": RANKS[cell // 4] if cell < 52 else "2",
            "initial_banker": cell % 4 if cell < 52 else None}


def prepare_round(spec, arm, team):
    if arm not in ARMS or team not in (0, 1):
        raise ValueError("unknown declaration arm/team")
    rnd = Round(spec["rank"], spec["initial_banker"], random.Random(spec["seed"]))
    events = []

    def declare(seat, final=False):
        view = capture_declare_view(rnd, seat, final)
        chosen = choose_declaration(view, arm if seat % 2 == team else "baseline")
        baseline = choose_declaration(view, "baseline")
        # Audit opportunities at their actual actor-visible prefix, not after
        # the future cards arrive. Declines with legal options are retained.
        if view.options:
            payload = asdict(view)
            payload["own_hand"] = list(view.own_hand)
            payload["options"] = [list(option) for option in view.options]
            events.append({"view": payload, "chosen": chosen,
                           "baseline": baseline, "changed": chosen != baseline})
        if chosen:
            rnd.declare(seat, chosen)

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        declare(seat)
    for seat in range(4):
        declare(seat, final=True)
    # All-bot final pass: no human response or wall-clock grace is simulated.
    for seat in range(4):
        rnd.pass_declare(seat)
    rnd.finalize_declare()
    return rnd, events


def finish_round(rnd, bots, focal_team):
    banker = rnd.banker
    if banker is None:
        raise ValueError("declarations must finish before play")
    rnd.bury(banker, bots[banker].decide_bury(rnd, banker))
    transcript = []
    while rnd.phase == "play":
        seat = rnd.turn
        attempted = bots[seat].decide_play(rnd, seat)
        previous = rnd.last_trick
        rnd.play(seat, attempted)
        transcript.append({"seat": seat, "cards": actual_play_after(rnd, seat, previous)})
    points = rnd.attacker_points
    banker_value = (-max(1, (points - 80) // 40) if points >= 80 else
                    3 if points == 0 else 2 if points < 40 else 1)
    value = banker_value if banker % 2 == focal_team else -banker_value
    return {"focal_signed_levels": value, "focal_won": int(value > 0),
            "attacker_points": points, "kitty_bonus": rnd.kitty_bonus,
            "kitty_ge80": int(rnd.kitty_bonus >= 80),
            "focal_is_banker_team": banker % 2 == focal_team,
            "buried": list(rnd.buried), "transcript": transcript}


def make_bots(config, spec):
    from ..ai.cwv_policy import shared_evaluator
    from .cwv_bury_policy import make_cwv_bury_bot
    evaluator = shared_evaluator(config["checkpoint"], threads=1,
                                 max_batch=128, encoding="mlp-static")
    if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
        raise ValueError("gameplay checkpoint changed")
    return [make_cwv_bury_bot(evaluator, arm="hybrid", seed=derived_seed(
        f"play:{spec['index']}", seat)) for seat in range(4)]


def read_record(path, config, spec, arm, team):
    row = json.loads(path.read_text())
    if (row.get("config_sha256") != config["config_sha256"] or
            row.get("spec") != spec or row.get("arm") != arm or
            row.get("focal_team") != team or
            ("outcome" in row) != (config["mode"] == "play")):
        raise ValueError("completed declaration arm mismatch")
    return row


def run_cluster(config, cluster):
    from .search_screen import _publish
    spec = deal_spec(config["start_index"] + cluster)
    records = []
    for team in (0, 1):
        for arm in ARMS:
            path = Path(config["output"]) / f"arm-{cluster:05d}-{team}-{arm}.json"
            if path.exists():
                records.append(read_record(path, config, spec, arm, team))
                continue
            start, cpu = time.perf_counter(), time.process_time()
            rnd, events = prepare_round(spec, arm, team)
            row = {"spec": spec, "arm": arm, "focal_team": team,
                   "config_sha256": config["config_sha256"],
                   "declaration": rnd.declaration, "banker": rnd.banker,
                   "trump_suit": rnd.trump_suit or "NT", "events": events}
            if config["mode"] == "play":
                bots = make_bots(config, spec)
                row["outcome"] = finish_round(rnd, bots, team)
                from ..oracle.screen import work_counters
                row["work"] = work_counters(bots)
            row.update(wall_seconds=time.perf_counter() - start,
                       cpu_seconds=time.process_time() - cpu)
            _publish(path, row)
            records.append(row)
    return {"cluster": cluster, "config_sha256": config["config_sha256"],
            "records": records}


def summarize(shards, config):
    from .cwv_bury_readout import interval
    result = {"mode": config["mode"], "completed_independent_deals": len(shards),
              "requested_deals": config["deals"],
              "complete": len(shards) == config["deals"],
              "claim": "DEV bot-only declaration comparison, not promotion",
              "changed_deal_mirrors": 0, "changed_trump_deal_mirrors": 0,
              "changed_final_declaration_deal_mirrors": 0,
              "changed_banker_deal_mirrors": 0, "comparisons": {}}
    deltas = {k: [] for k in ("focal_signed_levels", "focal_won", "kitty_bonus", "kitty_ge80")}
    rows = [r for shard in shards for r in shard["records"]]
    for shard in shards:
        per_deal = {k: [] for k in deltas}
        for team in (0, 1):
            base, changed = [next(r for r in shard["records"]
                                 if r["focal_team"] == team and r["arm"] == arm)
                             for arm in ARMS]
            result["changed_deal_mirrors"] += int(any(e["changed"] for e in changed["events"]))
            result["changed_trump_deal_mirrors"] += int(base["trump_suit"] != changed["trump_suit"])
            result["changed_banker_deal_mirrors"] += int(base["banker"] != changed["banker"])
            result["changed_final_declaration_deal_mirrors"] += int(base["declaration"] != changed["declaration"])
            if config["mode"] == "play":
                for metric in deltas:
                    per_deal[metric].append(changed["outcome"][metric] - base["outcome"][metric])
        if config["mode"] == "play":
            for metric in deltas:
                deltas[metric].append(sum(per_deal[metric]) / 2)
    if config["mode"] == "play" and shards:
        result["comparisons"] = {key: interval(values) for key, values in deltas.items()}
    result["cost"] = {arm: {"cpu_seconds": sum(r["cpu_seconds"] for r in rows if r["arm"] == arm),
                           "wall_seconds_sum": sum(r["wall_seconds"] for r in rows if r["arm"] == arm)}
                      for arm in ARMS}
    return result


def main(argv=None):
    from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("census", "play"), default="census")
    parser.add_argument("--checkpoint")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--deals", type=int, default=53)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if (args.deals <= 0 or args.deals % 53 or args.start_index < 0 or
            args.start_index % 53 or args.workers < 1 or
            (args.limit is not None and args.limit < 1)):
        parser.error("positive deals and nonnegative start-index must be multiples of 53; positive workers/limit")
    if args.mode == "play" and (not args.checkpoint or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        parser.error("play requires --checkpoint and SHENGJI_REQUIRE_VOIDS=1")
    config = {"schema": "declare-screen-v1", "mode": args.mode, "namespace": NAMESPACE,
              "deals": args.deals, "start_index": args.start_index,
              "output": str(args.out.resolve()), "arms": list(ARMS),
              "source": execution_source_identity(Path(__file__).resolve().parents[1]),
              "environment": {k: v for k, v in os.environ.items() if k.startswith("SHENGJI_")}}
    if args.mode == "play":
        from ..ai.cwv_policy import shared_evaluator
        config["checkpoint"] = str(Path(args.checkpoint).resolve())
        config["checkpoint_sha256"] = shared_evaluator(
            args.checkpoint, threads=1, max_batch=128, encoding="mlp-static").checkpoint_sha256
        config["continuation"] = "W32 K4 N30 R300 reuse; hybrid bury32/32/32 K4; no serving deadline"
    config["config_sha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.deals):
        path = args.out / f"cluster-{cluster:05d}.json"
        if path.exists():
            shard = json.loads(path.read_text())
            if shard.get("config_sha256") != config["config_sha256"] or shard.get("cluster") != cluster:
                raise ValueError("completed declaration cluster mismatch")
            shards.append(shard)
        else:
            pending.append(cluster)
    _run_pending(config, pending[:args.limit] if args.limit else pending, shards,
                 output=args.out, workers=args.workers, task_fn=run_cluster)
    result = summarize(shards, config)
    _publish(args.out / "summary.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
