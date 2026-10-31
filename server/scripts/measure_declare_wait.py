#!/usr/bin/env python3
"""Measure the value declaration's wait option (``vdw``, `train.declare_wait`)
against release 45 on seeded deals with the real package.

Both bots are built from fly.toml's env (release 45) through the registry,
the second with ``SHENGJI_PV_VALUE_DECLARE_WAIT=1``; each deal is driven with
the bot at every seat by the canonical declare loop (`ai.env.prepare_round`:
one chance per dealt card for its receiver, then one grace-window pass,
``final=True``, over the four seats).  Reports, per evaluated declare chance,
the wall seconds (ordinary pass alone off; ordinary + wait pass on); how often
the wait pass ran and chose to wait; and per deal whether the standing
declaration at the window's close (seat, cards) differs from release 45's and
how many cards had been dealt when it was made.  Read-only: no record, no
log, nothing written but stdout.

    nice -n 10 python scripts/measure_declare_wait.py --package PATH --seeds 0-39
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.engine.round import Round  # noqa: E402
from shengji.train import pv_search_policy as pv  # noqa: E402

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


def fresh(seed):
    """A seeded deal (the tests' `test_pv_value_declare.fresh`): every rank,
    a known banker or (every fifth) a first round."""
    return Round(RANKS[seed % len(RANKS)], None if seed % 5 == 0 else seed % 4,
                 random.Random(seed))


def build(env, package):
    env = {**env, "SHENGJI_PV_CKPT": package}
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    (name, factory), = entries.items()
    return name, factory


def drive(seed, bot):
    rnd = fresh(seed)
    chances, standing_at = [], None

    def call(seat, final):
        nonlocal standing_at
        started = time.perf_counter()
        choice = bot.decide_declare(rnd, seat, final=final)
        seconds = time.perf_counter() - started
        record = getattr(bot, "last_declare_record", None)
        if record is not None:
            chances.append({"seconds": seconds, "final": final,
                            "cards_dealt": record["cards_dealt"],
                            "pair_held": any(len(o) == 2 for o in rnd.declare_options(seat)),
                            "wait": record.get("wait")})
        if choice:
            rnd.declare(seat, choice)
            standing_at = sum(len(h) for h in rnd.hands) if not final else 100

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        call(seat, False)
    for seat in range(4):
        call(seat, True)
    declaration = rnd.declaration
    final = None if declaration is None else [declaration["seat"], sorted(declaration["cards"])]
    return {"final": final, "standing_at": standing_at if declaration else None,
            "chances": chances}


def summary(values):
    if not values:
        return None
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
    return {"n": len(values), "mean": round(statistics.fmean(values), 4),
            "p90": round(p90, 4), "max": round(ordered[-1], 4)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--package", required=True)
    parser.add_argument("--seeds", default="0-39")
    args = parser.parse_args(argv)
    lo, hi = (int(x) for x in args.seeds.split("-"))
    from shengji.eval.served_config import fly_env
    env = fly_env()
    off_name, off_factory = build(env, args.package)
    on_name, on_factory = build({**env, "SHENGJI_PV_VALUE_DECLARE_WAIT": "1"}, args.package)
    rows = []
    for seed in range(lo, hi + 1):
        off = drive(seed, off_factory(seed=seed))
        on = drive(seed, on_factory(seed=seed))
        rows.append({"seed": seed, "off": off, "on": on})
        print(json.dumps({"seed": seed, "off_final": off["final"], "on_final": on["final"],
                          "off_at": off["standing_at"], "on_at": on["standing_at"]}),
              file=sys.stderr, flush=True)

    off_chances = [c for r in rows for c in r["off"]["chances"]]
    on_chances = [c for r in rows for c in r["on"]["chances"]]
    waits = [c["wait"] for c in on_chances if c["wait"] is not None]
    evaluated = [w for w in waits if w["evaluated"]]
    differ = [r for r in rows if r["off"]["final"] != r["on"]["final"]]
    shifts = [r["on"]["standing_at"] - r["off"]["standing_at"] for r in rows
              if r["off"]["standing_at"] is not None and r["on"]["standing_at"] is not None]
    out = {
        "off_name": off_name, "on_name": on_name, "seeds": [lo, hi],
        "engine": "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "pure",
        "off_seconds_per_evaluated_chance": summary([c["seconds"] for c in off_chances]),
        "on_seconds_per_evaluated_chance": summary([c["seconds"] for c in on_chances]),
        "on_seconds_where_wait_ran": summary([c["seconds"] for c in on_chances
                                              if c["wait"] is not None]),
        "wait_pass_seconds": summary([w["seconds"] for w in waits]),
        "evaluated_chances_off": len(off_chances), "evaluated_chances_on": len(on_chances),
        "wait_pass_runs": len(waits), "wait_pass_evaluated": len(evaluated),
        "wait_pass_fallbacks": sorted({(w["fallback_reason"], w["fallback_error"])
                                       for w in waits if not w["evaluated"]}),
        "waited": sum(w["waited"] for w in evaluated),
        "waited_with_pair": sum(1 for c in on_chances if c["wait"] is not None
                                and c["wait"]["waited"] and c["pair_held"]),
        "wait_runs_with_pair": sum(1 for c in on_chances if c["wait"] is not None
                                   and c["pair_held"]),
        "mean_wait_minus_now": (None if not evaluated else round(statistics.fmean(
            w["wait_mean"] - w["now_mean"] for w in evaluated), 4)),
        "deals": len(rows),
        "final_declaration_differs": len(differ),
        "no_declaration_off": sum(r["off"]["final"] is None for r in rows),
        "no_declaration_on": sum(r["on"]["final"] is None for r in rows),
        "standing_declaration_cards_dealt_off": summary(
            [r["off"]["standing_at"] for r in rows if r["off"]["standing_at"] is not None]),
        "standing_declaration_cards_dealt_on": summary(
            [r["on"]["standing_at"] for r in rows if r["on"]["standing_at"] is not None]),
        "timing_shift_on_minus_off": summary(shifts),
        "timing_shift_nonzero": sum(1 for s in shifts if s != 0),
    }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
