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
when every turn committed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
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


def run_smoke(env: dict[str, str], *, turns: int = 12, deal_seed: int = 91) -> dict:
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
               "turns": [], "passed": False}

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
            receipt["turns"].append({"phase": phase, "seat": seat,
                                     "seconds": round(time.perf_counter() - started, 3)})
    asyncio.run(scenario())
    phases = {t["phase"] for t in receipt["turns"]}
    receipt["passed"] = "bury" in phases and "play" in phases
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fly-toml", required=True)
    parser.add_argument("--map", action="append", default=[], help="volume_path=local_path")
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    mappings = dict(item.split("=", 1) for item in args.map)
    env = env_from_fly_toml(args.fly_toml, mappings)
    try:
        receipt = run_smoke(env, turns=args.turns)
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
