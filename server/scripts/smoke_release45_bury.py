"""Release-45 server-path smoke: the wide value-only bury (K=64) through the server.

The deploy gate for release 45 (#974 on release 44). It builds the served bot
from a fly.toml ``[env]`` exactly as the server does (`cwv_serving_smoke.
build_production_bot`: registry registration from the env, ``make_bot(SHENGJI_BOT)``),
then for each of N first-round deals with four bot seats:

- streams the deal card by card and runs every declaration through the server's
  `_bot_declares` (the gated value declare goes off the loop through the shared
  model-search admission, as served), then the final declare call and
  ``finalize_declare``;
- runs the banker's bury through `_paced_bot_step` -> `_commit_bot_turn` (the
  snapshot path, never an in-process ``decide_bury``) and records its wall
  seconds, the bot's own elapsed seconds, ``wide_value.candidates``, the
  chooser, the fallback reason, and that the turn committed exactly once (a
  second commit of the same prepared turn is refused and the room log holds
  one ``bury`` event);
- plays a few play turns through the same path.

    SHENGJI_FAST=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \\
    python scripts/smoke_release45_bury.py --fly-toml ../fly.toml \\
        --map /data/models/smv3out-491ee4bf.npz=/local/smv3out-491ee4bf.npz \\
        --map /data/models/js-m1-0d17fd03.npz=/local/js-m1-0d17fd03.npz \\
        [--rounds 40] [--plays 4] [--receipt smoke.json]

Exit status 0 only when every bury committed exactly once through the wide
value-only chooser with no fallback, within the fly.toml bury budget, and
every play turn committed.  Timings are this host's, not Fly's.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

SCHEMA = "release45-bury-smoke-v1"


def _quantile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _events(log_path: Path, kind: str) -> list[dict]:
    if not log_path.exists():
        return []
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    return [row for row in rows if row["e"] == kind]


async def _one_round(srv, bot, deal_seed: int, plays: int, log_dir: Path) -> dict:
    from shengji.engine.game import Game

    code = f"S{deal_seed}"
    room = srv.Room(code=code, log_dir=log_dir)
    room.game = Game(random.Random(deal_seed))
    rnd = room.game.start_round()
    assert rnd.first_round
    room.index_round()
    room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
    room.bot = bot
    declare_calls = []
    while rnd.phase == "deal":
        async with room.lock:
            seat, idx, card = rnd.deal_next()
            room.ids[seat][idx] = card
        started = time.perf_counter()
        await srv._bot_declares(room, [seat])
        declare_calls.append(time.perf_counter() - started)
    started = time.perf_counter()
    await srv._bot_declares(room, list(range(4)), final=True)
    declare_calls.append(time.perf_counter() - started)
    async with room.lock:
        rnd.finalize_declare()
    log = log_dir / f"{code}.jsonl"
    decisions = _events(log, "declare_decision")
    gated_seconds = [e["elapsed_seconds"] for e in _events(log, "model_search")
                     if e.get("phase") == "declare" and e.get("event") == "completed"]
    assert rnd.phase == "bury", rnd.phase
    banker = rnd.banker
    started = time.perf_counter()
    prepared = await srv._paced_bot_step(room, banker, minimum_turn_seconds=0)
    if prepared is None:
        raise RuntimeError(f"deal {deal_seed}: server produced no bury turn")
    async with room.lock:
        committed = srv._commit_bot_turn(room, prepared)
        recommitted = srv._commit_bot_turn(room, prepared)
    wall = time.perf_counter() - started
    record = prepared.decision.snapshot.bot_copy.last_bury_record or {}
    wide = record.get("wide_value") or {}
    bury_events = _events(log, "bury")
    row = {
        "deal_seed": deal_seed, "banker": banker,
        "trump": rnd.trump_suit or "NT", "declared": rnd.declaration is not None,
        "bury_wall_seconds": round(wall, 4),
        "bury_compute_seconds": round(prepared.compute_seconds, 4),
        "bury_elapsed_seconds": (round(record["elapsed_seconds"], 4)
                                 if "elapsed_seconds" in record else None),
        "schema": record.get("schema"),
        "arm": record.get("arm"),
        "chooser": "wide-value" if wide else ("fallback" if record.get("schema") == "cwv-bury-fallback-v1"
                                              else "arm"),
        "candidates": wide.get("candidates"),
        "chosen_is_incumbent": wide.get("chosen_is_incumbent"),
        "fallback_reason": record.get("fallback_reason", record.get("reason")),
        "committed": bool(committed), "recommit_refused": not recommitted,
        "bury_events": len(bury_events), "phase_after_bury": rnd.phase,
        "kitty_size": len(rnd.kitty),
        "declare_calls": len(declare_calls),
        "declare_max_call_seconds": round(max(declare_calls), 4),
        "value_declare_decisions": len(decisions),
        "value_declare_search_seconds": [round(s, 4) for s in gated_seconds],
        "plays": [],
    }
    for _ in range(plays):
        if rnd.phase != "play":
            break
        seat = rnd.turn
        started = time.perf_counter()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        if prepared is None:
            raise RuntimeError(f"deal {deal_seed}: server produced no play turn")
        async with room.lock:
            ok = srv._commit_bot_turn(room, prepared)
        row["plays"].append({"seat": seat, "seconds": round(time.perf_counter() - started, 4),
                             "committed": bool(ok)})
    return row


def run(env: dict[str, str], *, rounds: int, plays: int, first_seed: int) -> dict:
    from scripts.cwv_serving_smoke import build_production_bot, file_sha256
    from shengji.api import server as srv
    from shengji.engine import combos, fast

    name, bot = build_production_bot(env)
    budget = float(env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"])
    receipt = {"schema": SCHEMA, "policy": name, "bot_class": type(bot).__name__,
               "bury_budget_seconds": budget,
               "bury_wide_value": env.get("SHENGJI_PV_BURY_WIDE_VALUE"),
               "bury_wide_k": env.get("SHENGJI_PV_BURY_WIDE_K"),
               "compiled_engine": bool(fast.HAVE_FAST and combos.decompose is fast.decompose),
               "files": {k: {"path": v, "sha256": file_sha256(v)} for k, v in env.items()
                         if k.endswith("_CKPT")},
               "rounds": []}

    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(rounds):
                receipt["rounds"].append(await _one_round(srv, bot, first_seed + i, plays, Path(tmp)))
    asyncio.run(scenario())

    rows = receipt["rounds"]
    walls = [r["bury_wall_seconds"] for r in rows]
    plays_s = [p["seconds"] for r in rows for p in r["plays"]]
    failures = []
    for r in rows:
        if not (r["committed"] and r["recommit_refused"] and r["bury_events"] == 1
                and r["phase_after_bury"] == "play" and r["kitty_size"] == 8):
            failures.append(f"deal {r['deal_seed']}: bury not committed exactly once")
        if r["chooser"] != "wide-value" or r["fallback_reason"] is not None:
            failures.append(f"deal {r['deal_seed']}: chooser {r['chooser']} fallback {r['fallback_reason']}")
        if r["bury_wall_seconds"] >= budget:
            failures.append(f"deal {r['deal_seed']}: bury {r['bury_wall_seconds']} s >= budget {budget} s")
        if not all(p["committed"] for p in r["plays"]):
            failures.append(f"deal {r['deal_seed']}: a play turn did not commit")
    vd_search = [s for r in rows for s in r["value_declare_search_seconds"]]
    receipt["summary"] = {
        "buries": len(rows),
        "bury_wall_p50": _quantile(walls, 0.5), "bury_wall_p90": _quantile(walls, 0.9),
        "bury_wall_max": max(walls), "bury_wall_mean": round(statistics.fmean(walls), 4),
        "margin_to_budget_at_max": round(budget - max(walls), 4),
        "fallbacks": sum(r["chooser"] != "wide-value" or r["fallback_reason"] is not None for r in rows),
        "candidates": sorted({r["candidates"] for r in rows if r["candidates"] is not None}),
        "chosen_incumbent": sum(bool(r["chosen_is_incumbent"]) for r in rows),
        "committed_exactly_once": sum(r["committed"] and r["recommit_refused"] and r["bury_events"] == 1
                                      for r in rows),
        "play_turns": len(plays_s),
        "play_p50": _quantile(plays_s, 0.5) if plays_s else None,
        "play_max": max(plays_s) if plays_s else None,
        "value_declare_decisions": sum(r["value_declare_decisions"] for r in rows),
        "value_declare_search_max": max(vd_search) if vd_search else None,
        "declare_max_call_seconds": max(r["declare_max_call_seconds"] for r in rows),
    }
    receipt["failures"] = failures
    receipt["passed"] = not failures and len(rows) == rounds
    return receipt


def main(argv=None) -> int:
    from scripts.cwv_serving_smoke import env_from_fly_toml

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fly-toml", required=True)
    parser.add_argument("--map", action="append", default=[], help="volume_path=local_path")
    parser.add_argument("--rounds", type=int, default=40)
    parser.add_argument("--plays", type=int, default=4)
    parser.add_argument("--first-seed", type=int, default=4500)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    env = env_from_fly_toml(args.fly_toml, dict(item.split("=", 1) for item in args.map))
    receipt = run(env, rounds=args.rounds, plays=args.plays, first_seed=args.first_seed)
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    print("deal  banker trump declared  bury_s  elapsed_s  cand  chooser     fallback  committed_once  vd_decisions")
    for r in receipt["rounds"]:
        print(f"{r['deal_seed']:5d}  {r['banker']:6d} {r['trump']:5s} {str(r['declared']):8s}  "
              f"{r['bury_wall_seconds']:6.3f}  {r['bury_elapsed_seconds']:9.3f}  {r['candidates']!s:4s}  "
              f"{r['chooser']:10s}  {r['fallback_reason']!s:8s}  "
              f"{str(r['committed'] and r['recommit_refused'] and r['bury_events'] == 1):14s}  "
              f"{r['value_declare_decisions']}")
    print(json.dumps({k: receipt[k] for k in ("policy", "bury_budget_seconds", "bury_wide_value",
                                              "bury_wide_k", "compiled_engine", "summary")}, indent=1))
    for failure in receipt["failures"]:
        print("FAIL:", failure)
    print("PASS" if receipt["passed"] else "FAIL")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
