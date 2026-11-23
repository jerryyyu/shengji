"""Decision identity and per-decision compute of the float32 value/prior forward (``SHENGJI_PV_VALUE_F32``)
against the served float64 one, on the served configuration.

The served bot is built exactly as the server builds it (`served_config.build_served_bot` on fly.toml's
``[env]`` with volume paths mapped to local files); its ``-vf32`` twin is built from the same env with
``SHENGJI_PV_VALUE_F32=1`` once, to check the registry name and the views it binds.  Rooms are played
from fixed deal seeds with the served bot in every seat.  Before every decision the f32 arm is re-cloned
from the served arm's live bot (`value_f32_serving.install` on a deep copy), so both arms decide from the
same bot state and RNG and differ only in the forward's dtype.  Each arm decides the SAME position:

* declaration: every deal step and grace-window call the served bot's own gate admits, on deep copies of
  the round and bot (the server's off-loop path), timed around ``decide_declare``;
* bury and play: through the server's own ``_paced_bot_step`` (snapshot + decision), timed by its
  ``compute_seconds``.

The served arm's choice is always the one committed, so the trajectory is the served bot's.  The order the
two arms run in alternates per position.  ``--diff`` also runs the f64 forward beside every f32 call (same
inputs) and records the largest absolute differences in outcome probability, expected level and prior
logit; its timings include that shadow work and are not reported as timing.

    python scripts/value_f32_witness.py --fly-toml ../fly.toml --map VOL=LOCAL ... \
        --deals 101,102,103,104 --out receipt.json [--diff]

Host-local evidence (one process, BLAS threads pinned by the env), not Fly timing; no strength claim.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import os
import platform
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ARMS = ("f64", "f32")


def _sha(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summary(xs):
    return {"n": len(xs), "mean": (sum(xs) / len(xs)) if xs else None, "p50": _pct(xs, 0.5),
            "p95": _pct(xs, 0.95), "max": max(xs) if xs else None}


class DiffLog:
    """Largest |f32 - f64| over every float32-view forward while installed: the class's two forwards
    are wrapped (deep copies and the server's snapshots keep the wrapping) and a float64 forward on
    the same inputs and weights runs beside each float32 one; float64 models pass straight through."""

    def __init__(self, support):
        import numpy as np
        self.support = np.asarray(support, dtype=np.float64)
        self.prob = self.level = self.logit = 0.0
        self.value_rows = self.prior_rows = 0

    def install(self):
        from shengji.ai.cwv_numpy import CWVNumpyMLP
        import numpy as np
        probabilities, policy_log_odds = CWVNumpyMLP.probabilities, CWVNumpyMLP.policy_log_odds
        log = self

        def f64(model):
            twin = object.__new__(CWVNumpyMLP)
            twin.__dict__.update(vars(model))
            twin.compute_f32 = False
            return twin

        def probabilities_watched(model, public, world, perspective):
            got = probabilities(model, public, world, perspective)
            if model.compute_f32 and len(got):
                ref = probabilities(f64(model), public, world, perspective)
                log.prob = max(log.prob, float(np.max(np.abs(got - ref))))
                log.level = max(log.level, float(np.max(np.abs(got @ log.support - ref @ log.support))))
                log.value_rows += len(got)
            return got

        def policy_log_odds_watched(model, flat):
            got = policy_log_odds(model, flat)
            if model.compute_f32 and len(got):
                ref = policy_log_odds(f64(model), flat)
                log.logit = max(log.logit, float(np.max(np.abs(got - ref))))
                log.prior_rows += len(got)
            return got
        CWVNumpyMLP.probabilities = probabilities_watched
        CWVNumpyMLP.policy_log_odds = policy_log_odds_watched

    def as_dict(self):
        return {"max_abs_outcome_prob": self.prob, "max_abs_expected_level": self.level,
                "max_abs_prior_logit": self.logit, "value_rows": self.value_rows, "prior_rows": self.prior_rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fly-toml", required=True)
    ap.add_argument("--map", action="append", default=[], metavar="VOLUME=LOCAL")
    ap.add_argument("--deals", default="101,102,103,104")
    ap.add_argument("--out", required=True)
    ap.add_argument("--diff", action="store_true")
    a = ap.parse_args(argv)

    from shengji.eval import served_config
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.engine import combos, fast, legal
    from shengji.train import value_f32_serving as vf

    compiled = fast.HAVE_FAST and combos.decompose is fast.decompose and legal.validate_follow is fast.validate_follow
    mappings = dict(item.split("=", 1) for item in a.map)
    env = served_config.served_env(fly_toml=a.fly_toml, mappings=mappings)
    if env.get("SHENGJI_FAST") == "1" and not compiled:
        raise SystemExit("fly.toml sets SHENGJI_FAST=1 but the compiled engine is not active")
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        if os.environ.get(key) != "1":
            raise SystemExit(f"pin {key}=1 in the launching environment (numpy reads it at import)")
    served_name, served = served_config.build_served_bot(env)
    twin_env = dict(env, SHENGJI_PV_VALUE_F32="1", SHENGJI_BOT=served_name + vf.SUFFIX)
    twin_name, twin = served_config.build_served_bot(twin_env)
    if not (twin.policy_name == twin_name and twin.evaluator.model.compute_f32
            and twin.predict._prior_net.compute_f32):
        raise SystemExit("the registry's -vf32 twin does not bind float32 views")
    if served.evaluator.model.compute_f32 or served.predict._prior_net.compute_f32:
        raise SystemExit("the served bot holds a float32 view")
    del twin
    packages = {k: {"path": env[k], "sha256": _sha(env[k])}
                for k in ("SHENGJI_PV_CKPT", "SHENGJI_PV_PRIOR_CKPT", "SHENGJI_PV_UNIFIED_CKPT",
                          "SHENGJI_PV_BELIEF_CKPT") if env.get(k)}
    diff = DiffLog(served.evaluator.support) if a.diff else None
    if diff is not None:
        diff.install()

    def f32_clone(bot):
        return vf.install(copy.deepcopy(bot))

    times = {arm: {"declare": [], "bury": [], "play": []} for arm in ARMS}
    incomplete = {arm: 0 for arm in ARMS}
    fallbacks = {arm: {} for arm in ARMS}
    decisions = []
    mismatches = []
    k = 0

    def note(phase, seed, seat, picks):
        nonlocal k
        same = picks["f64"] == picks["f32"]
        decisions.append({"seed": seed, "k": k, "phase": phase, "seat": seat, "same": same})
        if not same:
            mismatches.append({"seed": seed, "k": k, "phase": phase, "seat": seat, "picks": picks})
        k += 1

    async def deal(seed):
        room = srv.Room(code=f"V{seed}")
        room.game = Game(random.Random(seed))
        room.seats = [srv.Seat(name=f"Bot {s}", is_bot=True) for s in range(4)]
        room.bot = copy.deepcopy(served)
        rnd = room.game.start_round()

        def declare_turn(s, final):
            live = room.bot
            heuristic, gated = live.declare_gate(rnd, s, final)
            if not gated:
                return live.decide_declare(rnd, s, final=final)
            bots = {"f64": copy.deepcopy(live), "f32": f32_clone(live)}
            picks = {}
            order = ARMS if k % 2 == 0 else ARMS[::-1]
            for arm in order:
                r = copy.deepcopy(rnd)
                t0 = time.perf_counter()
                cards = bots[arm].decide_declare(r, s, final=final)
                times[arm]["declare"].append(time.perf_counter() - t0)
                picks[arm] = sorted(cards) if cards else None
            note("declare", seed, s, picks)
            room.bot = bots["f64"]
            return picks["f64"]

        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = declare_turn(seat, False)
            if cards:
                rnd.declare(seat, cards)
        for seat in range(4):
            cards = declare_turn(seat, True)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        while room.round is not None and room.round.phase in ("bury", "play"):
            r = room.round
            phase = r.phase
            seat = r.banker if phase == "bury" else r.turn
            live = room.bot
            bots = {"f64": live, "f32": f32_clone(live)}
            prepared = {}
            order = ARMS if k % 2 == 0 else ARMS[::-1]
            for arm in order:
                room.bot = bots[arm]
                p = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
                if p is None:
                    raise RuntimeError(f"{arm}: no bot turn at decision {k} ({phase})")
                prepared[arm] = p
                times[arm][phase].append(p.compute_seconds)
                record = getattr(p.decision.snapshot.bot_copy,
                                 "last_decision_record" if phase == "play" else "last_bury_record", None) or {}
                reason = record.get("reason" if phase == "play" else "fallback_reason")
                if phase == "play" and record.get("work_complete") is not True:
                    incomplete[arm] += 1
                if reason is not None:
                    fallbacks[arm][str(reason)] = fallbacks[arm].get(str(reason), 0) + 1
            note(phase, seed, seat, {arm: sorted(prepared[arm].decision.cards) for arm in ARMS})
            room.bot = live
            async with room.lock:
                if not srv._commit_bot_turn(room, prepared["f64"]):
                    raise RuntimeError(f"the server refused to commit decision {k} ({phase})")

    started = time.time()
    seeds = [int(x) for x in a.deals.split(",") if x.strip()]
    for seed in seeds:
        asyncio.run(deal(seed))
    by_phase = {}
    for d in decisions:
        row = by_phase.setdefault(d["phase"], [0, 0])
        row[0] += d["same"]
        row[1] += 1
    out = {"schema": "value-f32-witness-v1", "host": platform.node(), "machine": platform.machine(),
           "engine": "compiled" if compiled else "pure", "deals": seeds, "diff_mode": bool(a.diff),
           "served_name": served_name, "twin_name": twin_name, "packages": packages,
           "threads": {k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                                                       "VECLIB_MAXIMUM_THREADS")},
           "budget_seconds": {"play": env.get("SHENGJI_PV_SERVING_BUDGET_SECONDS"),
                              "bury": env.get("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS")},
           "decisions": len(decisions), "same": sum(d["same"] for d in decisions),
           "same_by_phase": {p: {"same": s, "n": n} for p, (s, n) in by_phase.items()},
           "mismatches": mismatches, "play_incomplete": incomplete, "fallbacks": fallbacks,
           "seconds": {arm: {p: summary(v) for p, v in t.items()} for arm, t in times.items()},
           "raw_seconds": times, "wall_seconds": round(time.time() - started, 1)}
    if diff is not None:
        out["diff"] = diff.as_dict()
    with open(a.out, "x") as handle:
        json.dump(out, handle, indent=1, sort_keys=True)
    print(f"decisions {out['same']}/{out['decisions']} same; by phase {out['same_by_phase']}")
    for arm in ARMS:
        for p, s in out["seconds"][arm].items():
            if s["n"]:
                print(f"{arm} {p}: n={s['n']} mean={s['mean']:.4f} p95={s['p95']:.4f} max={s['max']:.4f}")
    print(f"incomplete {incomplete} fallbacks {fallbacks}")
    if diff is not None:
        print(f"diff {out['diff']}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
