"""Fresh paired W32 gameplay screen for the simple-belief DEV arms.

This module deliberately does not register a policy or import the declaration
screen.  Declarations and the common deal are prepared with the ordinary
heuristic policy; only play-time hidden-world sampling differs between arms.
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

from ..ai.heuristic import HeuristicBot
from ..ai.cwv_policy import shared_evaluator
from ..engine.cards import RANKS
from ..engine.round import Round, actual_play_after
from .cwv_bury_policy import CWVBuryBot
from .cwv_shortlist import CWVShortlistConfig
from .harvest_labels import record_deal_key
from .r4_runtime_client import R4RuntimeClient, actor_for_round
from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity
from .simple_belief_r4 import ownership_array
from .simple_belief_sampler import SmallBeliefPredictor, belief_bot_class


NAMESPACE = "simple-belief-gameplay-dev-20260910-v1"
ARMS = ("uniform-pool", "new-small", "r4-synthetic-primary")
ALL_ARMS = ("ordinary", *ARMS)
PLANNED_DEALS = 14
POOL_SIZE = 128
FIT_ITERATIONS = 500
SELECT_WORLDS = 30
REPORT_WORLDS = 300


def seed_for(label: str, index: int) -> int:
    """Stable unsigned seed derived without Python's process hash salt."""
    return int.from_bytes(
        hashlib.sha256(f"{NAMESPACE}:{label}:{index}".encode()).digest()[:8],
        "big",
    )


def policy_seed(cluster: int, seat: int) -> int:
    """The paired play stream; treatment labels never alter this seed."""
    if type(cluster) is not int or type(seat) is not int or not 0 <= seat < 4:
        raise ValueError("invalid gameplay policy coordinate")
    return seed_for(f"play:{cluster}", seat)


def spec_for(cluster: int) -> dict:
    if type(cluster) is not int or not 0 <= cluster < PLANNED_DEALS:
        raise ValueError("this screen has exactly14 planned deals")
    return {
        "index": cluster,
        "seed": seed_for("deal", cluster),
        "rank": RANKS[cluster] if cluster < 13 else "2",
        "initial_banker": cluster % 4 if cluster < 13 else None,
    }


def schedule() -> list[tuple[str, int | None]]:
    """One common baseline plus two focal-team mirrors for each treatment."""
    return [("ordinary", None), *((arm, team) for arm in ARMS for team in (0, 1))]


def _normal_declaration(rnd: Round) -> None:
    policies = [HeuristicBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
        rnd.pass_declare(seat)
    rnd.finalize_declare()


def prepare_round(spec: dict) -> tuple[Round, dict]:
    """Create a deterministic dealt/declaration-complete round.

    The returned metadata is intentionally small and contains no opponent
    hands.  A fresh ``Round`` is made for every arm, so mirrors share the deal
    and declaration while retaining independent policy RNG streams.
    """
    expected = spec_for(spec["index"])
    if spec != expected:
        raise ValueError("round specification differs from its planned deal")
    rnd = Round(spec["rank"], spec["initial_banker"], random.Random(spec["seed"]))
    _normal_declaration(rnd)
    return rnd, {"rank": rnd.trump_rank, "banker": rnd.banker,
                 "trump_suit": rnd.trump_suit, "declaration": rnd.declaration}


class _R4Predictor:
    """Adapter retaining only synthetic-primary ownership and child timing."""

    def __init__(self, client, archive_server):
        self.client = client
        self.archive_server = archive_server
        self.inference_wall_seconds = 0.0

    def __call__(self, rnd, seat):
        actor = actor_for_round(rnd, seat, self.archive_server)
        response = self.client.predict(actor)
        payload = response["arms"]["synthetic-primary"]["ownership"]
        self.inference_wall_seconds += float(response.get("inference_wall_s", 0.0))
        return ownership_array(actor, payload)


def _predictor_for(mode, config, client, small_predictor):
    if mode == "ordinary":
        return None
    if mode == "uniform-pool":
        return None
    if mode == "new-small":
        return small_predictor
    if mode == "r4-synthetic-primary":
        return _R4Predictor(client, config["archive_server"])
    raise ValueError(f"unknown gameplay mode {mode!r}")


def _make_bot(mode, evaluator, seed, config, client, small_predictor):
    cls = belief_bot_class(CWVBuryBot)
    play_config = CWVShortlistConfig(
        worlds=32, selection_worlds=SELECT_WORLDS, alternatives=4,
        batch_size=128, uniform=False,
    )
    belief_mode = {"ordinary": "ordinary", "uniform-pool": "uniform-pool",
                   "new-small": "learned-pool",
                   "r4-synthetic-primary": "learned-pool"}[mode]
    bot = cls(
        evaluator,
        seed=seed,
        config=play_config,
        arm="hybrid",
        reuse_successors=True,
        belief_mode=belief_mode,
        belief_predictor=_predictor_for(mode, config, client, small_predictor),
        belief_pool_size=POOL_SIZE,
        belief_fit_iterations=FIT_ITERATIONS,
    )
    bot.REPORT_FOLD_WORLDS = REPORT_WORLDS
    return bot


def _json_copy(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def play_round(rnd, bots, cluster, arm, team):
    banker = rnd.banker
    if banker is None or rnd.phase != "bury":
        raise ValueError("gameplay round must be declaration-complete")
    bury = bots[banker].decide_bury(rnd, banker)
    rnd.bury(banker, bury)
    transcript = []
    started = time.perf_counter()
    child_inference_wall = 0.0
    while rnd.phase == "play":
        seat = rnd.turn
        bot = bots[seat]
        before = rnd.last_trick
        decision_start = time.perf_counter()
        predictor = getattr(bot, "belief_predictor", None)
        child_before = (getattr(predictor, "inference_wall_seconds", 0.0)
                        if isinstance(predictor, _R4Predictor) else 0.0)
        attempted = bot.decide_play(rnd, seat)
        decision_wall = time.perf_counter() - decision_start
        child_after = (getattr(predictor, "inference_wall_seconds", 0.0)
                       if isinstance(predictor, _R4Predictor) else 0.0)
        child_delta = max(0.0, child_after - child_before)
        rnd.play(seat, attempted)
        actual = actual_play_after(rnd, seat, before)
        last_belief = _json_copy(getattr(bot, "last_belief", None))
        child_inference_wall += child_delta
        transcript.append({
            "seat": seat,
            "attempted": list(attempted),
            "cards": list(actual),
            "decision_wall_s": decision_wall,
            "last_belief": last_belief,
        })
        if len(transcript) % 16 == 0:
            print(json.dumps({"cluster": cluster, "arm": arm, "team": team,
                              "plays": len(transcript),
                              "cards_remaining": sum(map(len, rnd.hands)),
                              "round_wall_s": round(time.perf_counter() - started, 1)}),
                  flush=True)
    points = rnd.attacker_points
    level = (-max(1, (points - 80) // 40) if points >= 80 else
             3 if points == 0 else 2 if points < 40 else 1)
    team0_signed = level if banker % 2 == 0 else -level
    return {
        "team0_signed_levels": team0_signed,
        "banker": banker,
        "attacker_points": points,
        "kitty_bonus": rnd.kitty_bonus,
        "buried": list(rnd.buried),
        "transcript": transcript,
        "round_wall_s": time.perf_counter() - started,
        "child_inference_wall_s": child_inference_wall,
    }


def _work_counters(bots, parent_cpu, parent_wall, child_inference_wall):
    from ..oracle.screen import work_counters
    out = work_counters(bots)
    out.update({
        "parent_cpu_seconds": float(parent_cpu),
        "parent_wall_seconds": float(parent_wall),
        "child_inference_wall_seconds": float(child_inference_wall),
        "parent_cpu_s": float(parent_cpu),
        "parent_wall_s": float(parent_wall),
        "child_inference_wall_s": float(child_inference_wall),
        "cpu_scope": "parent only; child inference wall only, not child full CPU",
    })
    return out


def _validate_outcome(outcome):
    if not isinstance(outcome, dict) or type(outcome.get("team0_signed_levels")) is not int:
        raise ValueError("saved gameplay outcome shape differs")
    if outcome.get("banker") not in range(4) or outcome["team0_signed_levels"] == 0:
        raise ValueError("saved gameplay outcome score differs")
    if (type(outcome.get("attacker_points")) is not int or
            type(outcome.get("kitty_bonus")) is not int or
            min(outcome["attacker_points"], outcome["kitty_bonus"]) < 0 or
            not isinstance(outcome.get("buried"), list) or len(outcome["buried"]) != 8 or
            not isinstance(outcome.get("transcript"), list)):
        raise ValueError("saved gameplay outcome fields differ")
    return outcome


def validate_arm(row, config, spec, arm, team):
    if (row.get("schema") != "simple-belief-gameplay-arm-v1" or
            row.get("config_sha256") != config["config_sha256"] or
            row.get("spec") != spec or row.get("arm") != arm or
            row.get("focal_team") != team):
        raise ValueError("saved gameplay arm identity differs")
    _validate_outcome(row.get("outcome"))
    return row


def read_arm(path, config, spec, arm, team):
    return validate_arm(json.loads(path.read_bytes()), config, spec, arm, team)


def read_cluster(path, config, cluster):
    shard = json.loads(path.read_bytes())
    if (shard.get("schema") != "simple-belief-gameplay-cluster-v1" or
            shard.get("config_sha256") != config["config_sha256"] or
            shard.get("cluster") != cluster or shard.get("spec") != spec_for(cluster)):
        raise ValueError("saved gameplay cluster identity differs")
    records = shard.get("records")
    if not isinstance(records, list) or len(records) != len(schedule()):
        raise ValueError("saved gameplay cluster arm population differs")
    for row, (arm, team) in zip(records, schedule(), strict=True):
        validate_arm(row, config, spec_for(cluster), arm, team)
    return shard


def _fresh_check(cache_recipe, planned):
    path = Path(cache_recipe)
    if path.is_dir():
        path = path / "recipe.json"
    raw = path.read_bytes()
    recipe = json.loads(raw)
    descriptors = recipe.get("deals")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("cache recipe has no deals")
    cache_keys = {d.get("deal_key") for d in descriptors if isinstance(d, dict)}
    if len(cache_keys) != len(descriptors) or None in cache_keys:
        raise ValueError("cache recipe deal keys are invalid")
    overlap = []
    for spec in planned:
        rnd = Round(spec["rank"], spec["initial_banker"], random.Random(spec["seed"]))
        if record_deal_key({"deck": rnd.deck}) in cache_keys:
            overlap.append(spec["index"])
    if overlap:
        raise ValueError(f"fresh gameplay deals overlap cache recipe: {overlap}")
    return hashlib.sha256(raw).hexdigest(), sorted(cache_keys)


def run_cluster(config, cluster):
    spec = spec_for(cluster)
    output = Path(config["output"])
    paths = {(arm, team): output / f"arm-{cluster:03d}-{arm}-{team}.json"
             for arm, team in schedule()}
    rows = []
    pending = []
    for arm, team in schedule():
        path = paths[(arm, team)]
        if path.exists():
            rows.append(read_arm(path, config, spec, arm, team))
        else:
            pending.append((arm, team))
    if not pending:
        return {"schema": "simple-belief-gameplay-cluster-v1", "cluster": cluster,
                "config_sha256": config["config_sha256"], "spec": spec,
                "records": [read_arm(paths[a], config, spec, *a) for a in schedule()]}

    evaluator = shared_evaluator(config["checkpoint"], threads=1, max_batch=128,
                                 encoding="mlp-static")
    if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
        raise ValueError("gameplay value checkpoint changed")
    small_predictor = None
    if any(arm == "new-small" for arm, _ in pending):
        if (hashlib.sha256(Path(config["small_checkpoint"]).read_bytes()).hexdigest()
                != config["small_checkpoint_sha256"]):
            raise ValueError("small belief checkpoint changed")
        small_predictor = SmallBeliefPredictor(config["small_checkpoint"],
                                               config["cache_recipe_sha256"])
    need_client = any(arm == "r4-synthetic-primary" for arm, _ in pending)
    client_context = (R4RuntimeClient(config["archive_server"], config["training_root"])
                      if need_client else None)
    try:
        for arm, team in pending:
            started, cpu = time.perf_counter(), time.process_time()
            rnd, _ = prepare_round(spec)
            client = client_context
            predictor = small_predictor
            bots = []
            for seat in range(4):
                mode = arm if arm != "ordinary" and seat % 2 == team else "ordinary"
                bots.append(_make_bot(mode, evaluator,
                                      policy_seed(cluster, seat),
                                      config, client, predictor))
            outcome = play_round(rnd, bots, cluster, arm, team)
            row = {
                "schema": "simple-belief-gameplay-arm-v1",
                "config_sha256": config["config_sha256"], "spec": spec,
                "arm": arm, "focal_team": team, "trump_rank": rnd.trump_rank,
                "trump_suit": rnd.trump_suit, "declaration": rnd.declaration,
                "outcome": outcome, "bury_config": asdict(bots[0].bury_config),
                "model_identity": getattr(evaluator, "identity", lambda: None)(),
                "work": _work_counters(
                    bots, time.process_time() - cpu, time.perf_counter() - started,
                    outcome["child_inference_wall_s"]),
                "wall_s": time.perf_counter() - started,
            }
            if client is not None:
                row["r4_identity"] = client.identity
            _publish(paths[(arm, team)], row)
            rows.append(row)
            print(json.dumps({"cluster": cluster, "completed_arms": len(rows),
                              "total_arms": len(schedule()), "last_arm_wall_s": row["wall_s"]}),
                  flush=True)
    finally:
        if client_context is not None:
            client_context.close()
    ordered = { (r["arm"], r["focal_team"]): r for r in rows }
    return {"schema": "simple-belief-gameplay-cluster-v1", "cluster": cluster,
            "config_sha256": config["config_sha256"], "spec": spec,
            "records": [ordered[a] for a in schedule()]}


def summarize(shards):
    from .cwv_bury_readout import interval
    deltas = {arm: {"signed_levels": [], "wins": []} for arm in ARMS}
    for shard in shards:
        records = shard.get("records", [])
        if len(records) != len(schedule()):
            raise ValueError("incomplete arm population before aggregate")
        by_key = {(r["arm"], r["focal_team"]): r for r in records}
        if set(by_key) != set(schedule()):
            raise ValueError("incomplete or duplicate arm population before aggregate")
        baseline = by_key[("ordinary", None)]["outcome"]
        for arm in ARMS:
            values, wins = [], []
            for team in (0, 1):
                changed = by_key[(arm, team)]["outcome"]["team0_signed_levels"]
                sign = 1 if team == 0 else -1
                base = sign * baseline["team0_signed_levels"]
                changed = sign * changed
                values.append(changed - base)
                wins.append(int(changed > 0) - int(base > 0))
            deltas[arm]["signed_levels"].append(sum(values) / 2)
            deltas[arm]["wins"].append(sum(wins) / 2)
    return {
        "schema": "simple-belief-gameplay-summary-v1",
        "independent_deals": len(shards), "planned_deals": PLANNED_DEALS,
        "complete": len(shards) == PLANNED_DEALS,
        "rounds": len(schedule()) * len(shards),
        "comparisons": {arm: {metric: interval(values) for metric, values in metrics.items()}
                         for arm, metrics in deltas.items()} if shards else {},
        "scope": "fresh DEV paired W32 gameplay; not confirmation or production authority",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--small-checkpoint", type=Path, required=True)
    parser.add_argument("--cache-recipe", type=Path, required=True)
    parser.add_argument("--archive-server", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2)
    parser.add_argument("--limit", type=int, choices=range(1, PLANNED_DEALS + 1), default=PLANNED_DEALS)
    args = parser.parse_args(argv)
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 required")
    checkpoint = args.checkpoint.resolve()
    small_checkpoint = args.small_checkpoint.resolve()
    cache_recipe = args.cache_recipe.resolve()
    cache_path = cache_recipe / "recipe.json" if cache_recipe.is_dir() else cache_recipe
    recipe_sha, _ = _fresh_check(cache_recipe, [spec_for(i) for i in range(PLANNED_DEALS)])
    config = {
        "schema": NAMESPACE, "output": str(args.out.resolve()),
        "checkpoint": str(checkpoint), "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "small_checkpoint": str(small_checkpoint),
        "small_checkpoint_sha256": hashlib.sha256(small_checkpoint.read_bytes()).hexdigest(),
        "cache_recipe": str(cache_path), "cache_recipe_sha256": recipe_sha,
        "archive_server": str(args.archive_server.resolve()),
        "training_root": str(args.training_root.resolve()),
        "training_manifests": {name: hashlib.sha256(
            (args.training_root / name / "manifest.json").read_bytes()).hexdigest()
            for name in ("synthetic-primary", "hard-geometry-label-permutation")},
        "training_manifest_paths": {name: str(
            (args.training_root / name / "manifest.json").resolve())
            for name in ("synthetic-primary", "hard-geometry-label-permutation")},
        "source": execution_source_identity(Path(__file__).parents[1]),
        "archive_source": execution_source_identity(args.archive_server / "shengji"),
        "planned_deals": [spec_for(i) for i in range(PLANNED_DEALS)],
        "arms": schedule(), "play": {"worlds": 32, "selection_worlds": SELECT_WORLDS,
                                      "alternatives": 4, "report_worlds": REPORT_WORLDS,
                                      "reuse_successors": True, "pool_worlds": POOL_SIZE,
                                      "fit_iterations": FIT_ITERATIONS},
    }
    config = json.loads(json.dumps(config, sort_keys=True))
    config["config_sha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.limit):
        path = args.out / f"cluster-{cluster:05d}.json"
        if path.exists():
            shards.append(read_cluster(path, config, cluster))
        else:
            pending.append(cluster)
    _run_pending(config, pending, shards, output=args.out, workers=args.workers,
                 task_fn=run_cluster)
    shards.sort(key=lambda row: row["cluster"])
    result = summarize(shards)
    _publish(args.out / f"summary-{len(shards)}.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
