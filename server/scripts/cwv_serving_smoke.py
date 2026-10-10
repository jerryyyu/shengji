"""Server-path smoke for a deploy configuration (#435; the release 25 incident).

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

With ``SHENGJI_PV_VALUE_DECLARE=1`` in the env (the value-guided declaration),
the deal is NOT replayed with a helper heuristic: ``--declare-rounds`` deals
(default 1) are streamed through the server's own ``run_deal``, so every gated
declare decision takes the off-loop, budgeted path (`_offloop_declare`) with
the production bot.  Each such decision is a ``declare_turns`` entry (seconds,
status, fallback reason, acted, stale); the smoke passes only if at least one
gated declaration completed off the loop and none hit an error.  The bury and
play turns then continue the last streamed deal.  Without the flag the smoke is
unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
import tomllib
from pathlib import Path

SCHEMA = "cwv-serving-smoke-v1"


def file_sha256(path) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def env_from_fly_toml(path, mappings: dict[str, str]) -> dict[str, str]:
    config = tomllib.loads(Path(path).read_text())
    env = {k: str(v) for k, v in config["env"].items()}
    for key, value in list(env.items()):
        if value in mappings:
            env[key] = mappings[value]
    return env


def build_production_bot(env: dict[str, str]):
    """Register exactly what the server registers from this env and build SHENGJI_BOT.

    The registration is done EXPLICITLY from the parsed env rather than by
    exporting it into ``os.environ``: the server registers at import from the
    process environment, and exporting here would leak the deploy env into
    every later import in the same process (and its subprocesses).
    """
    from shengji.ai import registry
    from shengji.train.cwv_bury_policy import bury_env_recipe
    from shengji.train.cwv_shortlist import shortlist_env_recipe
    parsed = bury_env_recipe(env)
    if parsed is not None:
        checkpoint, worlds, recipe, arm, config, budget = parsed
        registry.register_cwv_bury_policies(checkpoint, worlds, arm=arm, bury_config=config,
                                            serving_budget_seconds=budget, **recipe)
    play = shortlist_env_recipe(env)
    if play is not None:
        registry.register_cwv_shortlist_policies(play[0], play[1], **play[2])
    if env.get("SHENGJI_PV_CKPT"):
        # the policy/value search mode (#585): one package as value net and prior
        from shengji.train.pv_search_policy import pv_env_recipe
        recipe = pv_env_recipe(env)
        registry.register_pv_search_policies(recipe.pop("checkpoint"), **recipe)
    name = env["SHENGJI_BOT"]
    if name not in registry.REGISTRY:
        raise SystemExit(f"SHENGJI_BOT {name!r} is not registered by this env: the server would not boot with it")
    return name, registry.make_bot(name, seed=13)


def stream_deals_through_server(room, bot, *, rounds: int, deal_seed: int) -> list[dict]:
    """Deal ``rounds`` fresh rounds through the server's ``run_deal`` with ``bot``
    at all four seats; return one entry per off-loop declare decision.  The room
    is left in the last round's bury phase."""
    from shengji.api import server as srv
    from shengji.engine.game import Game

    declare_turns: list[dict] = []
    original_log = room.log_event

    def log_event(kind, **data):
        if kind == "bot_declare_timing":
            record = data.get("decision") or {}
            declare_turns.append({
                "round": None,  # set after the deal below
                "seat": data["seat"], "final": data["final"],
                "seconds": round(data["compute_seconds"], 4),
                "status": data["status"], "fallback_reason": data["fallback_reason"],
                "acted": data["acted"], "stale": data["stale_discarded"],
                "changed": record.get("changed"),
                "bot_fallback_reason": record.get("fallback_reason")})
        return original_log(kind, **data)

    room.log_event = log_event
    saved = srv.DEAL_DELAY, srv.kick_bots
    srv.DEAL_DELAY, srv.kick_bots = 0.0, (lambda r: None)
    try:
        for index in range(int(rounds)):
            room.game = Game(random.Random(deal_seed + index))
            room.game.start_round()
            room.index_round()
            first = len(declare_turns)
            asyncio.run(srv.run_deal(room))
            for entry in declare_turns[first:]:
                entry["round"] = index
            if room.round.phase != "bury":
                raise RuntimeError(f"run_deal ended in phase {room.round.phase}")
    finally:
        srv.DEAL_DELAY, srv.kick_bots = saved
        room.log_event = original_log
    return declare_turns


def run_smoke(env: dict[str, str], *, turns: int = 12, deal_seed: int = 91,
              declare_rounds: int = 1) -> dict:
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv
    from shengji.engine.game import Game

    name, bot = build_production_bot(env)
    room = srv.Room(code="SMOKE")
    room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
    room.bot = bot
    value_declare = getattr(bot, "value_declare", False) is True
    declare_turns = None
    if value_declare:
        declare_turns = stream_deals_through_server(room, bot, rounds=declare_rounds,
                                                    deal_seed=deal_seed)
        rnd = room.round
    else:
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
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
    receipt = {"schema": SCHEMA, "policy": name, "bot_class": type(bot).__name__,
               "files": {k: {"path": v, "sha256": file_sha256(v)} for k, v in env.items()
                         if k.endswith("_CKPT")},
               "turns": [], "passed": False}
    if declare_turns is not None:
        receipt["declare_turns"] = declare_turns
        receipt["declare_budget_seconds"] = srv.DECLARE_BUDGET_SECONDS

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
    if declare_turns is not None:
        receipt["passed"] = receipt["passed"] and bool(declare_turns) and any(
            t["status"] == "complete" for t in declare_turns) and not any(
            t["fallback_reason"] == "server-error" for t in declare_turns)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fly-toml", required=True)
    parser.add_argument("--map", action="append", default=[], help="volume_path=local_path")
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--declare-rounds", type=int, default=1,
                        help="deals streamed through run_deal when SHENGJI_PV_VALUE_DECLARE=1")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    mappings = dict(item.split("=", 1) for item in args.map)
    env = env_from_fly_toml(args.fly_toml, mappings)
    try:
        receipt = run_smoke(env, turns=args.turns, declare_rounds=args.declare_rounds)
    except Exception as exc:  # noqa: BLE001 - the smoke's job is to surface exactly this
        print(f"FAIL: {type(exc).__name__}: {exc}")
        if args.receipt:
            args.receipt.write_text(json.dumps({"schema": SCHEMA, "passed": False,
                                                "error": f"{type(exc).__name__}: {exc}"}, indent=1))
        return 1
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    walls = ", ".join(f"{t['phase']}:{t['seconds']}s" for t in receipt["turns"])
    if "declare_turns" in receipt:
        declares = receipt["declare_turns"]
        seconds = sorted(t["seconds"] for t in declares)
        statuses = {}
        for t in declares:
            key = t["status"] if t["fallback_reason"] is None else t["fallback_reason"]
            statuses[key] = statuses.get(key, 0) + 1
        print(f"declare: {len(declares)} off-loop decisions {statuses}"
              + (f", seconds mean {sum(seconds) / len(seconds):.4f} max {seconds[-1]:.4f}"
                 if seconds else "")
              + f", budget {receipt['declare_budget_seconds']}s")
    print(f"{'PASS' if receipt['passed'] else 'FAIL'}: {receipt['policy']} ({receipt['bot_class']}) "
          f"{len(receipt['turns'])} server turns [{walls}]")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
