#!/usr/bin/env python3
"""DEV measurement of the uniform world proposal and the bury-rule kitty
(`ai.uniform_worlds`; pv-search rules ``world_uniform`` / ``kitty_bury_rule``).

Re-runs the serving audit's world-model witnesses with the rules on, on the
same heuristic self-play roots, the served recipe and the real package:

``values``     (audit W2b) per role and trick bucket, the served leaf's mean
               value over the true world, release 45's worlds (P), the
               whl+whd worlds (H), the uniform worlds (WU) and the uniform
               worlds with the bury-rule kitty (KB); the trump-length spread of
               the other hands; the attackers' kitty trumps; and the seconds
               of each ``_worlds`` call and the proposal's fallback worlds.
``decisions``  (audit W3) the plain argmax over the served admitted ballot on
               two independent draws of each world model: flips between two
               draws of one model are the noise, flips across models the
               effect; excess = cross - noise, with a bootstrap interval.
``bury``       (audit W6) the served wide chooser's candidates scored on 32
               worlds per draw, production's helper worlds vs the proposal's.
``kitty``      (audit W8) attacker roots: the value gap to the true world with
               random (WU) and bury-rule (KB) kitties, and the flips.

Every number is a world-model measurement, not playing strength.  Usage (cwd
server/, compiled engine, the ``rl`` group)::

    SHENGJI_FAST=1 python scripts/s30_uniform_worlds_eval.py values --n 600 --out OUT.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import time
from collections import Counter

import numpy as np

PKG = os.environ.get("S30_PKG", os.path.expanduser("~/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz"))
PKG_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
SERVED_ENV = {
    "SHENGJI_PV_ADMISSION_DIVERSITY": "1", "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1",
    "SHENGJI_PV_TIEBREAK_POINTS": "1", "SHENGJI_PV_LEAD_ANCHOR": "1",
    "SHENGJI_PV_DOOMED_THROW_RESELECT": "1", "SHENGJI_PV_VALUE_DECLARE": "1",
    "SHENGJI_PV_CKPT": PKG, "SHENGJI_PV_SHA256": PKG_SHA, "SHENGJI_PV_WORLDS": "64",
    "SHENGJI_PV_CANDIDATES": "8", "SHENGJI_PV_CAP": "4000", "SHENGJI_PV_BATCH_SIZE": "128",
    "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3", "SHENGJI_PV_BURY_ARM": "hybrid",
    "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2", "SHENGJI_PV_BURY_WIDE_VALUE": "1",
    "SHENGJI_PV_BURY_WIDE_K": "64",
}
MODELS = {
    "P": {},
    "H": dict(world_history_legal=True, world_history_draw=True),
    "WU": dict(world_history_legal=True, world_history_draw=True, world_uniform=True),
    "KB": dict(world_history_legal=True, world_history_draw=True, world_uniform=True,
               kitty_bury_rule=True),
}


def served_bot(seed, **rules):
    from shengji.train import pv_search_policy as pv
    recipe = pv.pv_env_recipe(dict(SERVED_ENV))
    recipe.update(rules)
    (name, factory), = pv.pv_registry_entries(**recipe).items()
    bot = factory(seed=seed)
    bot.serving_budget_seconds = None
    return name, bot


def _declared(seed):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = h.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = h.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    return rnd


def dealt_round(seed):
    from shengji.ai.heuristic import HeuristicBot
    rnd = _declared(seed)
    rnd.bury(rnd.banker, HeuristicBot().decide_bury(rnd, rnd.banker))
    return rnd


def bury_state(seed):
    rnd = _declared(seed)
    assert rnd.phase == "bury"
    return rnd


def bootstrap(xs, reps=4000, seed=1):
    a = np.asarray(xs, dtype=float)
    rng = np.random.default_rng(seed)
    means = a[rng.integers(0, len(a), size=(reps, len(a)))].mean(axis=1)
    return [float(a.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def trump_stats(rnd, seat, worlds):
    from shengji.engine.cards import TRUMP
    o = rnd.ordering
    lengths = [sum(o.eff_suit(c) == TRUMP for c in hands[s]) for hands, _ in worlds
               for s in range(4) if s != seat]
    kitty = [sum(o.eff_suit(c) == TRUMP for c in buried) for _, buried in worlds]
    return float(np.std(lengths)), float(np.mean(kitty))


def timed_worlds(bot, rnd, seat):
    t = time.perf_counter()
    worlds, _ = bot._worlds(rnd, seat)
    return worlds, time.perf_counter() - t, dict(bot._last_sampling)


def leaf_means(ev, rnd, seat, actions, worlds):
    from shengji.ai.cwv_policy import afterstate
    leaves = [afterstate(rnd, seat, hands, buried, a, finish_trick=True)
              for hands, buried in worlds for a in actions]
    return np.asarray(ev.score(leaves, seat)).reshape(len(worlds), len(actions)).mean(axis=0)


BUCKETS = (("banker 0-4", True, 0, 4), ("attacker 0-4", False, 0, 4),
           ("banker 5-9", True, 5, 9), ("attacker 5-9", False, 5, 9),
           ("banker 10+", True, 10, 99), ("attacker 10+", False, 10, 99))


def cmd_values(args):
    from shengji.ai.heuristic import HeuristicBot
    bots = {k: served_bot(51, **rules)[1] for k, rules in MODELS.items()}
    ev = bots["P"].evaluator
    h = HeuristicBot()
    rng = random.Random(8)
    rows, deal = [], 1010000
    while len(rows) < args.n:
        rnd = dealt_round(deal)
        deal += 1
        stops = set(rng.sample(range(60), 3))
        ply = 0
        while rnd.phase == "play" and ply < 60 and len(rows) < args.n:
            seat = rnd.turn
            action = h.decide_play(rnd, seat)
            if ply in stops:
                row = dict(trick=len(rnd.history), banker=not rnd.is_attacker(seat),
                           v_true=float(leaf_means(ev, rnd, seat, [action],
                                                   [([list(x) for x in rnd.hands],
                                                     list(rnd.buried))])[0]))
                for key, bot in bots.items():
                    worlds, secs, stats = timed_worlds(bot, rnd, seat)
                    row[f"v_{key}"] = float(leaf_means(ev, rnd, seat, [action], worlds)[0])
                    row[f"sd_{key}"], row[f"kit_{key}"] = trump_stats(rnd, seat, worlds)
                    row[f"secs_{key}"] = secs
                    row[f"fallback_{key}"] = stats.get("uniform_fallback_worlds")
                    row[f"tries_{key}"] = stats.get("uniform_tries")
                from shengji.engine.cards import TRUMP
                row["kit_true"] = sum(rnd.ordering.eff_suit(c) == TRUMP for c in rnd.buried)
                rows.append(row)
            rnd.play(seat, action)
            ply += 1
        print("roots", len(rows), flush=True)
    out = {"n": len(rows), "buckets": {}, "seconds": {}, "fallback": {}}
    for label, banker, lo, hi in BUCKETS:
        sel = [r for r in rows if r["banker"] == banker and lo <= r["trick"] <= hi]
        if not sel:
            continue
        g = lambda k: np.array([r[k] for r in sel])
        entry = {"n": len(sel), "v_true": float(g("v_true").mean())}
        for key in MODELS:
            d = g(f"v_{key}") - g("v_true")
            entry[f"{key}-true"] = [float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d)))]
            entry[f"sd_{key}"] = float(g(f"sd_{key}").mean())
            if not banker:
                entry[f"kitty_trumps_{key}"] = float(g(f"kit_{key}").mean())
        if not banker:
            entry["kitty_trumps_true"] = float(g("kit_true").mean())
        out["buckets"][label] = entry
    for key in MODELS:
        s = np.array([r[f"secs_{key}"] for r in rows])
        out["seconds"][key] = {q: float(np.percentile(s, q)) for q in (50, 90, 99)}
        out["seconds"][key]["max"] = float(s.max())
        fb = [r[f"fallback_{key}"] for r in rows if r[f"fallback_{key}"] is not None]
        if fb:
            out["fallback"][key] = {"worlds_share": float(np.sum(fb) / (64 * len(fb))),
                                    "decisions_with_fallback": float(np.mean(np.array(fb) > 0)),
                                    "tries_p50": float(np.percentile([r[f"tries_{key}"] for r in rows], 50)),
                                    "tries_p99": float(np.percentile([r[f"tries_{key}"] for r in rows], 99))}
    return out, rows


def cmd_decisions(args):
    from shengji.ai.heuristic import HeuristicBot
    _, served = served_bot(21)
    bots = {k: served_bot(21 + i, **rules)[1] for i, (k, rules) in enumerate(MODELS.items())}
    ev = served.evaluator
    h = HeuristicBot()
    srng = random.Random(3)
    rows, deal = [], 950000
    while len(rows) < args.n:
        rnd = dealt_round(deal)
        deal += 1
        stop = srng.randrange(0, 60)
        ply = 0
        while rnd.phase == "play":
            seat = rnd.turn
            if ply == stop:
                b = copy.deepcopy(served)
                b.decide_play(copy.deepcopy(rnd), seat)
                admitted = b.last_decision_record["admitted"]
                if len(admitted) >= 2:
                    picks = {}
                    for key, bot in bots.items():
                        picks[key] = [int(np.argmax(leaf_means(ev, rnd, seat, admitted,
                                                               bot._worlds(rnd, seat)[0])))
                                      for _ in range(2)]
                    rows.append(dict(trick=len(rnd.history), banker=not rnd.is_attacker(seat),
                                     lead=not rnd.trick.plays, k=len(admitted), picks=picks))
                    print("roots", len(rows), flush=True)
                break
            rnd.play(seat, h.decide_play(rnd, seat))
            ply += 1
    return flip_table(rows, [("P", "WU"), ("P", "KB"), ("H", "WU"), ("WU", "KB")]), rows


def flip_table(rows, pairs):
    def per_row(r, a, b):
        p = r["picks"]
        noise = ((p[a][0] != p[a][1]) + (p[b][0] != p[b][1])) / 2
        cross = np.mean([p[a][i] != p[b][j] for i in (0, 1) for j in (0, 1)])
        return cross - noise, noise, cross
    subsets = {"all": lambda r: True, "leads": lambda r: r["lead"],
               "banker 0-4": lambda r: r["banker"] and r["trick"] <= 4,
               "attacker 0-4": lambda r: not r["banker"] and r["trick"] <= 4,
               "banker": lambda r: r["banker"], "attacker": lambda r: not r["banker"]}
    out = {}
    for a, b in pairs:
        for label, f in subsets.items():
            sel = [r for r in rows if f(r)]
            if not sel:
                continue
            vals = np.array([per_row(r, a, b) for r in sel])
            out[f"{a} vs {b} | {label}"] = {
                "n": len(sel), "noise": float(vals[:, 1].mean()), "cross": float(vals[:, 2].mean()),
                "excess": bootstrap(vals[:, 0])}
    return out


def cmd_bury(args):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.ai.registry import make_bot
    from shengji.ai.uniform_worlds import sample_worlds_uniform
    from shengji.train.bury_wide_value import wide_bury_candidates
    from shengji.train.cwv_bury import score_bury_candidates
    from shengji.train.cwv_bury_policy import _seed, _worlds
    _, bot = served_bot(41)
    rows = []
    for i in range(args.n):
        rnd = bury_state(870000 + i)
        seat = rnd.banker
        incumbent = HeuristicBot().decide_bury(rnd, seat)
        cands, _ = wide_bury_candidates(rnd, seat, bot._bury_candidates(rnd, incumbent), 64)
        p_helper = make_bot("mc-s0-report-lcb", seed=_seed("model", 41))
        u_helper = make_bot("mc-s0-report-lcb", seed=_seed("model", 41))
        picks, secs = {"P": [], "WU": []}, {"P": [], "WU": []}
        for _ in range(2):
            for key in ("P", "WU"):
                t = time.perf_counter()
                if key == "P":
                    worlds = _worlds(p_helper, rnd, seat, 32, "model")[0]
                else:
                    worlds = sample_worlds_uniform(u_helper, rnd, seat, 32)[0]
                secs[key].append(time.perf_counter() - t)
                v = score_bury_candidates(rnd, cands, worlds, bot.evaluator,
                                          first_trick_policy=p_helper.rollout_policy)
                picks[key].append(int(np.argmax(v.mean(axis=0))))
        rows.append(dict(picks=picks, secs=secs, chosen_incumbent={k: [p == 0 for p in v]
                                                                    for k, v in picks.items()}))
        print(i, picks, flush=True)
    out = flip_table([dict(r, trick=0, banker=True, lead=False) for r in rows], [("P", "WU")])
    out = {k: v for k, v in out.items() if k.endswith("| all")}
    out["sampler_seconds"] = {k: float(np.mean([s for r in rows for s in r["secs"][k]]))
                              for k in ("P", "WU")}
    return out, rows


def cmd_kitty(args):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.cards import TRUMP
    _, served = served_bot(61)
    bots = {k: served_bot(61 + i, **MODELS[k])[1] for i, k in enumerate(("WU", "KB"))}
    ev = served.evaluator
    h = HeuristicBot()
    srng = random.Random(72)
    rows, deal = [], 1100000
    while len(rows) < args.n:
        rnd = dealt_round(deal)
        deal += 1
        stop = srng.randrange(0, 24)
        ply = 0
        while rnd.phase == "play":
            seat = rnd.turn
            if ply >= stop and rnd.is_attacker(seat):
                b = copy.deepcopy(served)
                b.decide_play(copy.deepcopy(rnd), seat)
                admitted = b.last_decision_record["admitted"]
                if len(admitted) >= 2:
                    true = [([list(x) for x in rnd.hands], list(rnd.buried))]
                    mt = leaf_means(ev, rnd, seat, admitted, true)
                    row = dict(trick=len(rnd.history), picks={}, gap={}, kitty={})
                    for key, bot in bots.items():
                        row["picks"][key], gaps, kits = [], [], []
                        for _ in range(2):
                            worlds = bot._worlds(rnd, seat)[0]
                            m = leaf_means(ev, rnd, seat, admitted, worlds)
                            row["picks"][key].append(int(np.argmax(m)))
                            gaps.append(float((m - mt).mean()))
                            kits.append(trump_stats(rnd, seat, worlds)[1])
                        row["gap"][key], row["kitty"][key] = float(np.mean(gaps)), float(np.mean(kits))
                    row["kitty"]["true"] = sum(rnd.ordering.eff_suit(c) == TRUMP for c in rnd.buried)
                    rows.append(row)
                break
            rnd.play(seat, h.decide_play(rnd, seat))
            ply += 1
        print("roots", len(rows), flush=True)
    out = flip_table([dict(r, banker=False, lead=False) for r in rows], [("WU", "KB")])
    out = {k: v for k, v in out.items() if k.endswith("| all")}
    for key in ("WU", "KB"):
        d = np.array([r["gap"][key] for r in rows])
        out[f"V({key})-V(true)"] = [float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d)))]
        out[f"kitty_trumps_{key}"] = float(np.mean([r["kitty"][key] for r in rows]))
    out["kitty_trumps_true"] = float(np.mean([r["kitty"]["true"] for r in rows]))
    return out, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("values", "decisions", "bury", "kitty"))
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    summary, rows = {"values": cmd_values, "decisions": cmd_decisions, "bury": cmd_bury,
                     "kitty": cmd_kitty}[a.what](a)
    summary["wall_seconds"] = time.time() - t0
    with open(a.out, "w") as fh:
        json.dump({"summary": summary, "rows": rows}, fh)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    sys.exit(main())
