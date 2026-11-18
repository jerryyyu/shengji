#!/usr/bin/env python3
"""Parity and latency of the served unified slots (`shengji.train.unified_serving`) on full rounds.

    python scripts/unified_serving_check.py --fly-toml ../fly.toml --map VOLUME=LOCAL [...] \
        --unified PATH --unified-sha256 SHA --belief PATH --belief-sha256 SHA \
        [--rounds 10] [--first-seed 4500] --receipt OUT.jsonl
    python scripts/unified_serving_check.py stand-in --trunk BELIEF.npz --out DIR

The environment is ``fly.toml``'s with volume paths mapped to local files (`served_config`), plus
the four lines a unified release changes: the belief pair and the unified pair.  One bot of the
registry's unified name plays every seat of each round through the server's own turn path
(``_bot_declares``, ``_paced_bot_step``, ``_commit_bot_turn``).  Before each of its play turns, four
fresh bots with one seed decide a copy of that state:

* parity, clocks and the belief proposal's preparation budget lifted so the decision is a
  function of the code alone: the registry's unified bot against the duel adapter's (the served
  registry entry, then `unified_slots`' three installs, with the adapter's own two module-level
  stand-ins in place for that call).  Cards, base worlds, decision record (less the fields that
  measure the run and the registry bot's own ``unified`` entry) and slot counters must be equal,
  with no belief fallback on either side;
* latency, clocks as served: the registry's unified bot against the served bot (the served
  functions unwrapped for that call), seconds per ``decide_play``, in alternating order.

The receipt is JSON lines: a header, one row per decision, a terminal row with the mismatch count,
both latency distributions and their ratio, and the slot counters.  Exit 0 only with zero
mismatches, zero play fallbacks on the driver and every slot filled from the shared forward.

``stand-in`` writes a unified readout package for timing where the trained one is not at hand:
the given belief package's trunk, bit for bit, under random heads and a random readout of the
trained package's shape.  Its forwards cost what the trained package's cost and its belief is the
given package's; its prior, values and replies are noise, so it says nothing about play.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import hashlib
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER / "tests"))

SCHEMA = "unified-serving-check-v1"
MAX_PLAYS = 100
COUNTERS = ("unified_prior_calls", "unified_shared_hits", "unified_shared_misses", "unified_value_rows",
            "unified_value_other", "unified_reply_rows", "unified_reply_served", "unified_trunk_forwards",
            "unified_trunk_shared")
#: the heads and readout of the trained package (`unified_seq.HEAD_ARCH`, `unified_readout.READOUT_ARCH`)
STAND_IN_HEADS = {"q_hidden": 256, "policy_hidden": 192}
STAND_IN_READOUT = {"dp": 48, "dc": 96, "width": 288, "hidden": 576, "blocks": 3}


def stand_in(trunk_path, out_dir) -> dict:
    import numpy as np

    from shengji.ai import belief_numpy as bn
    from shengji.ai import unified_numpy as un
    from shengji.ai import unified_readout_numpy as rn

    belief = bn.load_belief_numpy(trunk_path)
    config = {"trunk": dict(belief.config), "heads": dict(STAND_IN_HEADS), "readout": dict(STAND_IN_READOUT)}
    rng = np.random.default_rng(0)

    def weights(shapes):
        out = {}
        for key, shape in shapes.items():
            if len(shape) == 1:
                out[key] = np.full(shape, 0.0 if key.endswith("bias") else 1.0, np.float32)
            else:
                out[key] = (rng.standard_normal(shape) / np.sqrt(shape[-1])).astype(np.float32)
        return out
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "unified-stand-in.npz"
    sha = rn.save_package(path, config, dict(belief.w), weights(un.head_shapes(config)),
                          weights(rn.readout_shapes(config)), {"temperature": belief.temperature,
                                                               "stand_in_trunk": belief.package_sha256})
    return {"unified": str(path), "unified_sha256": sha, "belief": str(trunk_path),
            "belief_sha256": belief.package_sha256}


def _quantile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def _latency(values):
    return {"n": len(values), "mean": round(statistics.fmean(values), 5) if values else None,
            "p50": _quantile(values, 0.5), "p95": _quantile(values, 0.95), "p99": _quantile(values, 0.99),
            "max": max(values) if values else None}


@contextlib.contextmanager
def _functions(ply, score):
    """``pv_tree_search.greedy_reply_ply`` and ``pv_encode_prefix.score_leaves`` set for one call."""
    from shengji.train import pv_encode_prefix, pv_tree_search
    saved = pv_tree_search.greedy_reply_ply, pv_encode_prefix.score_leaves
    pv_tree_search.greedy_reply_ply, pv_encode_prefix.score_leaves = ply, score
    try:
        yield
    finally:
        pv_tree_search.greedy_reply_ply, pv_encode_prefix.score_leaves = saved


def _decide(bot, rnd, lifted):
    import r50_flag_positions as P

    before = [getattr(bot, name, 0) for name in COUNTERS]
    if lifted:
        from shengji.ai import belief_numpy
        prep, belief_numpy.PREP_SECONDS = belief_numpy.PREP_SECONDS, 60.0
        try:
            out = P.decision(P.lift(bot), rnd)
        finally:
            belief_numpy.PREP_SECONDS = prep
        out["account"] = out["record"].pop("unified", None)
        seconds = None
    else:
        started = time.perf_counter()
        cards = sorted(bot.decide_play(rnd, rnd.turn))
        seconds = round(time.perf_counter() - started, 5)
        out = {"cards": cards, "schema": (bot.last_decision_record or {}).get("schema")}
    out["counters"] = [getattr(bot, name, 0) - b for name, b in zip(COUNTERS, before)]
    return out, seconds


def run(args) -> dict:
    from shengji.ai import registry
    from shengji.ai.unified_readout_numpy import load_unified_readout_numpy
    from shengji.api import server as srv
    from shengji.engine import combos, fast
    from shengji.engine.game import Game
    from shengji.eval import served_config
    from shengji.train import pv_encode_prefix, pv_search_policy as pv, pv_tree_search
    from shengji.train import unified_serving as serving
    from shengji.train import unified_slots as slots

    if os.environ.get("SHENGJI_FAST") == "1" and not fast.activate():
        raise SystemExit("SHENGJI_FAST=1 but the compiled engine is not built")
    mappings = dict(item.split("=", 1) for item in args.map)
    served_env = served_config.served_env(fly_toml=args.fly_toml, mappings=mappings)
    for key in (*served_config.WRITE_KEYS, "SHENGJI_FAST"):
        served_env.pop(key, None)
    words = {**served_env, "SHENGJI_PV_BELIEF_CKPT": args.belief, "SHENGJI_PV_BELIEF_SHA256": args.belief_sha256}
    unified_env = {**words, serving.CKPT_KEY: args.unified, serving.SHA256_KEY: args.unified_sha256}
    words["SHENGJI_BOT"] = served_config.registry_name(words)
    unified_env["SHENGJI_BOT"] = served_config.registry_name(unified_env)
    served_ply, served_score = pv_tree_search.greedy_reply_ply, pv_encode_prefix.score_leaves
    adapter_functions = slots.readout_reply_ply(served_ply), slots.readout_score_leaves(served_score)

    stack = contextlib.ExitStack()
    with stack:
        with served_config.process_env(served_env):
            registry._register_pv_search_from_env()
            make_served = registry.REGISTRY[served_env["SHENGJI_BOT"]]
        stack.enter_context(served_config.process_env(unified_env))
        registry._register_pv_search_from_env()
        make_unified = registry.REGISTRY[unified_env["SHENGJI_BOT"]]
        make_words = registry.REGISTRY[words["SHENGJI_BOT"]]
        model = load_unified_readout_numpy(args.unified, args.unified_sha256)
        driver = make_unified(seed=args.first_seed)
        unified_functions = pv_tree_search.greedy_reply_ply, pv_encode_prefix.score_leaves
        assert serving.active() and unified_functions[0] is not served_ply

        def make_adapter(seed):
            bot = make_words(seed=seed)
            slots.install_shared_forward(bot, model)
            slots.install_value_readout(bot, model, keep_prefix=True)
            slots.install_reply_readout(bot, model, keep_prefix=True)
            return bot

        logs = Path(str(args.receipt) + ".logs")
        fh = open(args.receipt, "x")
        logs.mkdir()

        def write(obj):
            fh.write(json.dumps(obj, sort_keys=True, default=list) + "\n")
            fh.flush()

        write({"kind": "header", "schema": SCHEMA, "argv": sys.argv, "unified_name": unified_env["SHENGJI_BOT"],
               "served_name": served_env["SHENGJI_BOT"], "adapter_base_name": words["SHENGJI_BOT"],
               "compiled_engine": bool(fast.HAVE_FAST and combos.decompose is fast.decompose),
               "files": {k: {"path": v, "sha256": hashlib.sha256(Path(v).read_bytes()).hexdigest()}
                         for k, v in unified_env.items() if k.endswith("_CKPT")}})
        rows, mismatches, driver_records, parity_fallbacks = [], [], [], []

        def compare(rnd, deal_seed, index):
            seed = deal_seed * 1000 + index
            with _functions(*adapter_functions):
                want, _ = _decide(make_adapter(seed), copy.deepcopy(rnd), True)
            with _functions(*unified_functions):
                got, _ = _decide(make_unified(seed=seed), copy.deepcopy(rnd), True)
            timed = {}
            order = ("unified", "served") if index % 2 == 0 else ("served", "unified")
            for side in order:
                functions = unified_functions if side == "unified" else (served_ply, served_score)
                make = make_unified if side == "unified" else make_served
                with _functions(*functions):
                    timed[side] = _decide(make(seed=seed), copy.deepcopy(rnd), False)
            account = got.pop("account")
            want.pop("account")
            if got["record"].get("belief_fallback") or want["record"].get("belief_fallback"):
                parity_fallbacks.append(index)
            row = {"kind": "decision", "deal_seed": deal_seed, "index": index, "trick": len(rnd.history) + 1,
                   "position": len(rnd.trick.plays) if rnd.trick is not None else 0,
                   "equal": got == want, "cards": got["cards"], "counters": got["counters"], "account": account,
                   "exact": [k for k in got["record"] if k.endswith("_status")],
                   "unified_seconds": timed["unified"][1], "served_seconds": timed["served"][1],
                   "unified_schema": timed["unified"][0]["schema"], "served_schema": timed["served"][0]["schema"],
                   "same_cards_as_served": timed["unified"][0]["cards"] == timed["served"][0]["cards"]}
            if not row["equal"]:
                keys = sorted(k for k in set(got["record"]) | set(want["record"])
                              if got["record"].get(k) != want["record"].get(k))
                row["differs"] = {"cards": got["cards"] != want["cards"], "worlds": got["worlds"] != want["worlds"],
                                  "counters": got["counters"] != want["counters"], "record_keys": keys[:20]}
                mismatches.append(row)
            rows.append(row)
            write(row)

        async def one_round(deal_seed):
            room = srv.Room(code=f"U{deal_seed}", log_dir=logs)
            room.game = Game(random.Random(deal_seed))
            rnd = room.game.start_round()
            room.index_round()
            room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
            room.bot = driver
            while rnd.phase == "deal":
                async with room.lock:
                    seat, idx, card = rnd.deal_next()
                    room.ids[seat][idx] = card
                await srv._bot_declares(room, [seat])
            await srv._bot_declares(room, list(range(4)), final=True)
            async with room.lock:
                rnd.finalize_declare()
            for index in range(MAX_PLAYS + 1):
                if rnd.phase not in ("bury", "play"):
                    break
                if rnd.phase == "play":
                    with _functions(served_ply, served_score):
                        compare(rnd, deal_seed, index)
                seat = rnd.banker if rnd.phase == "bury" else rnd.turn
                phase = rnd.phase
                with _functions(*unified_functions):
                    prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
                if prepared is None:
                    raise RuntimeError(f"deal {deal_seed}: the server produced no {phase} turn")
                copy_ = prepared.decision.snapshot.bot_copy
                record = copy_.last_bury_record if phase == "bury" else copy_.last_decision_record
                driver_records.append((phase, (record or {}).get("schema"), copy_.policy_name))
                async with room.lock:
                    if not srv._commit_bot_turn(room, prepared):
                        raise RuntimeError(f"deal {deal_seed}: a {phase} turn did not commit")
            write({"kind": "round", "deal_seed": deal_seed, "phase": rnd.phase, "decisions": len(rows)})
            return room.bot

        async def scenario():
            nonlocal driver
            for i in range(args.rounds):
                driver = await one_round(args.first_seed + i)
        with _functions(served_ply, served_score):
            asyncio.run(scenario())

        totals = [sum(r["counters"][i] for r in rows) for i in range(len(COUNTERS))]
        counters = dict(zip(COUNTERS, totals))
        unified_s = [r["unified_seconds"] for r in rows]
        served_s = [r["served_seconds"] for r in rows]
        plays = [r for r in driver_records if r[0] == "play"]
        failures = []
        if mismatches:
            failures.append(f"{len(mismatches)} of {len(rows)} decisions differ from the adapter's")
        if parity_fallbacks:
            failures.append(f"{len(parity_fallbacks)} parity decisions fell back to the fallback worlds")
        if any(schema != pv.RECORD_SCHEMA for _, schema, _ in plays):
            failures.append("a driver play decision fell back")
        if any(name != unified_env["SHENGJI_BOT"] for _, _, name in driver_records):
            failures.append("a driver decision was not the unified name's")
        if counters["unified_shared_hits"] != len(rows) or counters["unified_shared_misses"]:
            failures.append("a root prior ran outside the shared forward")
        if counters["unified_value_other"] or counters["unified_reply_served"] or counters["unified_trunk_forwards"]:
            failures.append("a value position, a reply or a trunk forward left the shared readout")
        if not counters["unified_value_rows"] or not counters["unified_reply_rows"]:
            failures.append("the readout scored no value row or no reply row")
        terminal = {"kind": "terminal", "passed": not failures, "failures": failures, "rounds": args.rounds,
                    "decisions": len(rows), "mismatches": len(mismatches),
                    "parity_belief_fallbacks": len(parity_fallbacks),
                    "driver": {"plays": len(plays), "buries": len(driver_records) - len(plays),
                               "play_fallbacks": sum(s != pv.RECORD_SCHEMA for _, s, _ in plays)},
                    "counters": counters,
                    "latency": {"unified_decision_s": _latency(unified_s), "served_decision_s": _latency(served_s),
                                "ratio_mean_unified_over_served": (round(statistics.fmean(unified_s)
                                                                         / statistics.fmean(served_s), 4)
                                                                   if rows else None),
                                "timed_fallbacks": {"unified": sum(r["unified_schema"] != pv.RECORD_SCHEMA for r in rows),
                                                    "served": sum(r["served_schema"] != pv.RECORD_SCHEMA for r in rows)}},
                    "same_cards_as_served": sum(r["same_cards_as_served"] for r in rows)}
        write(terminal)
        fh.close()
    return terminal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")
    make = sub.add_parser("stand-in")
    make.add_argument("--trunk", required=True)
    make.add_argument("--out", required=True)
    parser.add_argument("--fly-toml")
    parser.add_argument("--map", action="append", default=[], help="volume_path=local_path")
    parser.add_argument("--unified")
    parser.add_argument("--unified-sha256")
    parser.add_argument("--belief")
    parser.add_argument("--belief-sha256")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--first-seed", type=int, default=4500)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if args.command == "stand-in":
        print(json.dumps(stand_in(args.trunk, args.out), indent=1, sort_keys=True))
        return 0
    missing = [name for name in ("fly_toml", "unified", "unified_sha256", "belief", "belief_sha256", "receipt")
               if not getattr(args, name)]
    if missing:
        parser.error(f"missing: {', '.join('--' + m.replace('_', '-') for m in missing)}")
    terminal = run(args)
    print(json.dumps({k: terminal[k] for k in ("passed", "failures", "decisions", "mismatches", "driver",
                                               "counters", "latency", "same_cards_as_served")},
                     indent=1, sort_keys=True))
    return 0 if terminal["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
