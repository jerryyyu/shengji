"""Server-path smoke for a deploy configuration.

The decision-identity gate proves the served packages compute what the Torch
checkpoints compute. It does NOT prove the server can take a turn with the bot:
release 25 passed 2,222/2,222 and then stalled every bot turn, because the
server deep-copies the bot into a turn snapshot before any search and the
NumPy prior could not be pickled. This smoke builds the bot EXACTLY as the
server does, from a fly.toml's ``[env]`` (registry registration from the env,
``make_bot(SHENGJI_BOT)``), then plays a bury and play turns through the
server's own ``_paced_bot_step`` / ``_commit_bot_turn`` for every bot seat.

    python scripts/cwv_serving_smoke.py --fly-toml ../fly.toml \
        --map /data/models/m1-12ce4415.npz=/local/m1.npz \
        --map /data/models/prior-v2-b9ff76c9.npz=/local/prior.npz [--turns 12] [--receipt smoke.json]

``--map`` rewrites volume paths to local files (the SHA of each local file is
recorded; compare it with the volume before deploying). Exit status 0 only
when bury and play both committed. With ``--require-budget-records``, every
turn must also have a complete PV decision record and both decision time and
server wall time within its configured budget. Wall time includes queueing,
snapshot and commit overhead. This is host-local evidence, not Fly timing
unless executed there; it establishes no gameplay-strength result.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shengji.eval import served_config  # noqa: E402

SCHEMA = "cwv-serving-smoke-v1"


def file_sha256(path) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def env_from_fly_toml(path, mappings: dict[str, str]) -> dict[str, str]:
    """fly.toml's ``[env]`` with volume paths mapped (`served_config.served_env`)."""
    return served_config.served_env(fly_toml=path, mappings=mappings)


#: the scoped build-time export (`served_config.process_env`)
process_env = served_config.process_env


def build_production_bot(env: dict[str, str]):
    """Register exactly what the server registers from this env and build SHENGJI_BOT, with
    the env in the process environment (`served_config.build_served_bot`)."""
    try:
        return served_config.build_served_bot(env)
    except served_config.ServedConfigError as exc:
        raise SystemExit(str(exc)) from exc


def bot_latency_switches(bot) -> dict[str, bool] | None:
    """The pv-search latency switches the built bot carries; ``None`` off that mode."""
    try:
        from shengji.train.pv_search_policy import LATENCY_SWITCH_ENV, PVSearchBot
    except ImportError:
        return None
    if not isinstance(bot, PVSearchBot):
        return None
    return {attr: bool(getattr(bot, attr, False)) for attr in LATENCY_SWITCH_ENV}


def budget_turn(phase, bot, wall_seconds, env):
    """Bounded telemetry from the bot that actually ran in the server snapshot."""
    from shengji.train.pv_search_policy import RECORD_SCHEMA

    play = phase == "play"
    record = getattr(bot, "last_decision_record" if play else "last_bury_record", None)
    record = record if isinstance(record, dict) else {}
    key = "SHENGJI_PV_SERVING_BUDGET_SECONDS" if play else "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"
    attr = "serving_budget_seconds" if play else "bury_serving_budget_seconds"
    elapsed = record.get("seconds" if play else "elapsed_seconds", record.get("elapsed_seconds"))
    reason = record.get("reason") if play else record.get("fallback_reason")
    expected_schema = RECORD_SCHEMA if play else "cwv-bury-policy-v1"
    failures = []
    try:
        budget = float(env[key])
    except (KeyError, TypeError, ValueError):
        budget = None
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    if not finite(budget) or budget <= 0:
        failures.append("invalid_budget")
    elif getattr(bot, attr, None) != budget:
        failures.append("bot_budget_mismatch")
    if record.get("schema") != expected_schema:
        failures.append("decision_schema")
    if reason is not None or (play and record.get("work_complete") is not True):
        failures.append("fallback_or_incomplete")
    for label, value in (("server_wall", wall_seconds), ("decision", elapsed)):
        if not finite(value):
            failures.append(label + "_time_invalid")
        elif finite(budget) and value > budget:
            failures.append(label + "_budget_exceeded")
    return {"budget_seconds": budget, "decision_seconds": elapsed,
            "server_wall_seconds": wall_seconds, "record_schema": record.get("schema"),
            "fallback_reason": reason, "work_complete": record.get("work_complete"),
            "failures": failures}


def run_smoke(env: dict[str, str], *, turns: int = 12, deal_seed: int = 91,
              require_budget_records: bool = False) -> dict:
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv
    from shengji.engine.game import Game

    name, bot = build_production_bot(env)
    room = srv.Room(code="SMOKE")
    room.game = Game(random.Random(deal_seed))
    rnd = room.game.start_round()
    helper = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        card = helper.decide_declare(rnd, seat)
        if card:
            rnd.declare(seat, card)
    for seat in range(4):
        card = helper.decide_declare(rnd, seat, final=True)
        if card:
            rnd.declare(seat, card)
    rnd.finalize_declare()
    room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
    room.bot = bot
    room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
    room._kitty_given = True
    receipt = {"schema": SCHEMA, "policy": name, "bot_class": type(bot).__name__,
               "latency_switches": bot_latency_switches(bot),
               "files": {k: {"path": v, "sha256": file_sha256(v)} for k, v in env.items()
                         if k.endswith("_CKPT")},
               "turns": [], "passed": False, "require_budget_records": require_budget_records,
               "budget_failures": []}

    async def scenario():
        assert rnd.phase == "bury", rnd.phase
        for _ in range(int(turns)):
            if rnd.phase == "round_end":
                break
            seat = rnd.banker if rnd.phase == "bury" else rnd.turn
            phase = rnd.phase
            started = time.perf_counter()
            prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
            if prepared is None:
                raise RuntimeError(f"server produced no bot turn in phase {phase}")
            committed = srv._commit_bot_turn(room, prepared)
            if not committed:
                raise RuntimeError(f"server refused to commit the bot turn in phase {phase}")
            wall = time.perf_counter() - started
            turn = {"phase": phase, "seat": seat, "seconds": round(wall, 3)}
            if require_budget_records:
                turn["budget"] = budget_turn(phase, prepared.decision.snapshot.bot_copy, wall, env)
                receipt["budget_failures"].extend(
                    {"turn": len(receipt["turns"]), "phase": phase, "type": kind}
                    for kind in turn["budget"]["failures"])
            receipt["turns"].append(turn)
    asyncio.run(scenario())
    phases = {t["phase"] for t in receipt["turns"]}
    receipt["passed"] = ("bury" in phases and "play" in phases
                         and not receipt["budget_failures"])
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fly-toml", required=True)
    parser.add_argument("--map", action="append", default=[], help="volume_path=local_path")
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--require-budget-records", action="store_true",
                        help="require complete PV decision records and both server-wall and "
                             "decision times within configured play/bury budgets")
    args = parser.parse_args(argv)
    mappings = dict(item.split("=", 1) for item in args.map)
    env = env_from_fly_toml(args.fly_toml, mappings)
    try:
        receipt = run_smoke(env, turns=args.turns,
                            require_budget_records=args.require_budget_records)
    except Exception as exc:  # noqa: BLE001 - the smoke's job is to surface exactly this
        print(f"FAIL: {type(exc).__name__}: {exc}")
        if args.receipt:
            args.receipt.write_text(json.dumps({"schema": SCHEMA, "passed": False,
                                                "error": f"{type(exc).__name__}: {exc}"}, indent=1))
        return 1
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    walls = ", ".join(f"{t['phase']}:{t['seconds']}s" for t in receipt["turns"])
    print(f"{'PASS' if receipt['passed'] else 'FAIL'}: {receipt['policy']} ({receipt['bot_class']}) "
          f"{len(receipt['turns'])} server turns [{walls}]")
    if receipt.get("latency_switches") is not None:
        on = sorted(k for k, v in receipt["latency_switches"].items() if v)
        print(f"latency switches on: {', '.join(on) or 'none'}")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
