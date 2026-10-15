"""DEV duel: release 45 with a widened value-declare gate against release 45.

DEV diagnostic only (tier i; no strength claim, screens decide).  Adapted from
the find-gaps exploit duel (branch ``claude/find-gaps``,
``server/scripts/find_gaps/exploit_duel.py``): every seat starts from release
45 as served (fly.toml's SHENGJI_BOT and env) with a per-(deal, seat) seed
that does not depend on the arm or the mirror, so release 45 x4 plays the same
round in both mirrors and an arm's mirrored margin IS its paired difference
against release 45 x4 on the same deal.

Each deal is played as: one release-45 x4 baseline game, then for every arm
both mirrors (mirror 0: arm on seats 0+2; mirror 1: on seats 1+3; the other
team stays release 45).  An arm is release 45's env plus SHENGJI_PV_* overrides:

  vdea  SHENGJI_PV_VALUE_DECLARE_EVERY_ROUND=1
  vdef  SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST=1  (control: identical to release
        45 in a round with a fixed banker)

Round kinds:
  later  a later round of a game in progress, built exactly as
         ``Game.start_round`` deals it once a banker exists: banker seat =
         ``seed % 4`` (each seat, hence each side's two bots, banks equally
         often; both mirrors keep the same banker SEAT, so the arm is the
         banker team in exactly one mirror), both teams' levels set to
         ``RANKS[(seed // 4) % 13]`` (every level 2..A equally often, crossed
         with the banker seat), so the trump rank is that level.  Only the
         banker team's level enters the round (the trump rank); the level
         change is scored by ``Game.finish_round`` as served.
  first  the first round of a game (banker = first declarer), trump rank 2:
         the latency comparison for vdef.

Usage (cwd server/):
  SHENGJI_FAST=1 nice -n 10 python scripts/vdea_duel.py --kind later \
      --seed0 81600000 --deals 20 --workers 2 --out OUT.jsonl
  python scripts/vdea_duel.py --summarize OUT.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve()
SERVER = Path(os.environ.get("VDEA_SERVER", HERE.parents[1]))
REPO = SERVER.parent
DEFAULT_PKG = "/Users/jerryyu/Projects/shengji-wt/pkg/smv3out-491ee4bf.npz"


def served_env(pkg: str) -> str:
    """Set release 45's SHENGJI_* env from fly.toml (rollback-only CWV keys
    skipped); return SHENGJI_BOT."""
    env = tomllib.load(open(REPO / "fly.toml", "rb"))["env"]
    for k, v in env.items():
        if (k.startswith("SHENGJI_") and not k.startswith("SHENGJI_CWV_")) \
                or k.endswith("_THREADS"):
            os.environ[k] = str(v)
    os.environ["SHENGJI_PV_CKPT"] = pkg
    os.environ.setdefault("SHENGJI_FAST", "1")
    return env["SHENGJI_BOT"]


R45 = served_env(os.environ.get("VDEA_PKG", DEFAULT_PKG))
sys.path.insert(0, str(SERVER))

from shengji.ai.env import observe_committed_play  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import RANKS  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.round import actual_play_after  # noqa: E402

SEAT_SEED_STRIDE = 16
ARMS = {
    "vdea": (("SHENGJI_PV_VALUE_DECLARE_EVERY_ROUND", "1"),),
    "vdef": (("SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST", "1"),),
}


def seat_seed(deal_seed: int, seat: int) -> int:
    return deal_seed * SEAT_SEED_STRIDE + seat + 7


_VARIANTS: dict = {}


def variant_factory(overrides: tuple):
    """(name, factory) for release 45's recipe plus SHENGJI_PV_* overrides."""
    if not overrides:
        return R45, (lambda seed: make_bot(R45, seed=seed))
    if overrides not in _VARIANTS:
        from shengji.train.pv_search_policy import pv_env_recipe, pv_registry_entries
        env = dict(os.environ)
        env.update(dict(overrides))
        recipe = pv_env_recipe(env)
        entries = pv_registry_entries(recipe.pop("checkpoint"), **recipe)
        tail = R45.split("-bury-")[1].split("-")[:-1]
        names = [n for n in entries if n.split("-bury-")[-1].split("-")[:-1] == tail]
        if len(names) != 1:
            raise SystemExit(f"variant {overrides}: ambiguous names {names}")
        factory = entries[names[0]]

        def make(seed, _f=factory, _n=names[0]):
            bot = _f(seed=seed)
            bot.policy_name = _n
            return bot
        _VARIANTS[overrides] = (names[0], make)
    return _VARIANTS[overrides]


def new_game(kind: str, deal_seed: int) -> Game:
    game = Game(random.Random(deal_seed))
    if kind == "later":
        level = (deal_seed // 4) % len(RANKS)
        game.level_idx = [level, level]
        game.banker = deal_seed % 4
    return game


def _record_summary(rec):
    if not rec:
        return None
    return {k: rec.get(k) for k in ("gate", "final", "heuristic", "value_choice", "played",
                                    "changed", "evaluated", "fallback_reason", "seconds",
                                    "worlds_completed")}


def play(kind: str, deal_seed: int, arm: str | None, mirror: int) -> dict:
    """One round; ``arm`` None is release 45 x4 (the baseline)."""
    arm_team = mirror if arm is not None else None
    r_name, r_make = variant_factory(())
    a_name, a_make = variant_factory(ARMS[arm]) if arm is not None else (r_name, r_make)
    bots = [(a_make if arm is not None and seat % 2 == arm_team else r_make)(seat_seed(deal_seed, seat))
            for seat in range(4)]
    game = new_game(kind, deal_seed)
    rnd = game.start_round()
    declares, chances = [], []
    t_declare = 0.0

    def ask(seat, final):
        nonlocal t_declare
        t0 = time.perf_counter()
        cards = bots[seat].decide_declare(rnd, seat, final=final)
        t_declare += time.perf_counter() - t0
        rec = _record_summary(getattr(bots[seat], "last_declare_record", None))
        if rec is not None:
            rec["seat"] = seat
            rec["pos"] = rnd._deal_pos
            chances.append(rec)
        if cards:
            rnd.declare(seat, cards)
            declares.append([seat, list(cards), rnd._deal_pos, final])

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        ask(seat, False)
    for seat in range(4):
        ask(seat, True)
    rnd.finalize_declare()
    banker = rnd.banker
    rnd.bury(banker, bots[banker].decide_bury(rnd, banker))
    history = []
    t0 = time.perf_counter()
    while rnd.phase == "play":
        seat = rnd.turn
        cards = bots[seat].decide_play(rnd, seat)
        prev_last = rnd.last_trick
        rnd.play(seat, cards)
        history.append([seat, actual_play_after(rnd, seat, prev_last)])
        observe_committed_play(rnd, bots)
    play_secs = time.perf_counter() - t0
    result = game.finish_round()
    team = arm_team if arm is not None else 0
    won = result.winner_team == team
    decl = rnd.declaration
    return {
        "kind": kind, "seed": deal_seed, "arm": arm or "r45", "mirror": mirror,
        "arm_team": arm_team, "trump_rank": rnd.trump_rank, "banker": banker,
        "arm_role": (None if arm is None else ("banker" if banker % 2 == arm_team else "defender")),
        "trump": "NT" if rnd.trump_is_nt else rnd.trump_suit,
        "declarer": decl["seat"] if decl else None,
        "declaration": list(decl["cards"]) if decl else None,
        "declares": declares, "chances": chances,
        "buried": sorted(rnd.buried),
        "history_sha": hashlib.sha256(json.dumps(history).encode()).hexdigest()[:16],
        "attacker_points": result.attacker_points, "winner_team": result.winner_team,
        "level_change": result.level_change,
        "arm_levels": result.level_change if won else -result.level_change,
        "declare_secs": round(t_declare, 4), "play_secs": round(play_secs, 2),
        "arm_name": a_name,
    }


def _work(args):
    kind, deal_seed, arms = args
    out = [play(kind, deal_seed, None, 0)]
    for arm in arms:
        out += [play(kind, deal_seed, arm, m) for m in (0, 1)]
    return out


def run(kind, seed0, deals, workers, out, arms, stride=1, offset=0):
    done = set()
    if os.path.exists(out):
        for line in open(out):
            r = json.loads(line)
            done.add((r["seed"], r["arm"], r["mirror"]))
    seeds = [seed0 + i for i in range(offset, deals, stride)]
    need = [("r45", 0)] + [(a, m) for a in arms for m in (0, 1)]
    todo = [(kind, s, arms) for s in seeds if any((s, a, m) not in done for a, m in need)]
    print(f"{kind} {arms}: {len(todo)} deals to play ({len(seeds) - len(todo)} done)", flush=True)
    t0 = time.time()
    with open(out, "a") as fh:
        if workers <= 1:
            it = map(_work, todo)
        else:
            import multiprocessing as mp
            pool = mp.get_context("spawn").Pool(workers, maxtasksperchild=25)
            it = pool.imap_unordered(_work, todo)
        for i, recs in enumerate(it, 1):
            for r in recs:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            if i % 5 == 0:
                print(f"{i}/{len(todo)} deals {time.time() - t0:.0f}s", flush=True)


def bootstrap_ci(xs, reps=10000, seed=1):
    import numpy as np
    a = np.asarray(xs, dtype=float)
    rng = np.random.default_rng(seed)
    means = a[rng.integers(0, len(a), size=(reps, len(a)))].mean(axis=1)
    return float(a.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _pct(xs, q):
    import numpy as np
    return float(np.percentile(xs, q)) if xs else None


def summarize(paths):
    by = {}
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            by.setdefault((r["kind"], r["seed"]), {})[(r["arm"], r["mirror"])] = r
    out = {}
    kinds = sorted({k for k, _ in by})
    arms = sorted({a for d in by.values() for a, _ in d if a != "r45"})
    for kind in kinds:
        deals = {s: d for (k, s), d in by.items() if k == kind}
        for arm in arms:
            full = {s: d for s, d in deals.items()
                    if ("r45", 0) in d and (arm, 0) in d and (arm, 1) in d}
            if not full:
                continue
            lv = [(d[(arm, 0)]["arm_levels"] + d[(arm, 1)]["arm_levels"]) / 2 for d in full.values()]
            m, lo, hi = bootstrap_ci(lv)
            # by role: the arm's signed levels minus release 45's in the same seat
            # team (baseline game, team = mirror)
            role_diff = {"banker": [], "defender": []}
            mech = {"games": 0, "trump_changed": 0, "declarer_changed": 0,
                    "declarer_team_changed": 0, "any_declare_change": 0,
                    "history_changed": 0, "outcome_changed": 0}
            mech_role = {"banker": dict(mech), "defender": dict(mech)}
            for d in full.values():
                base = d[("r45", 0)]
                for mm in (0, 1):
                    r = d[(arm, mm)]
                    b_lv = base["level_change"] if base["winner_team"] == mm else -base["level_change"]
                    role_diff[r["arm_role"]].append(r["arm_levels"] - b_lv)
                    for tgt in (mech, mech_role[r["arm_role"]]):
                        tgt["games"] += 1
                        tgt["trump_changed"] += r["trump"] != base["trump"]
                        tgt["declarer_changed"] += r["declarer"] != base["declarer"]
                        tgt["declarer_team_changed"] += ((r["declarer"] is None) != (base["declarer"] is None)
                                                         or (r["declarer"] is not None and base["declarer"] is not None
                                                             and r["declarer"] % 2 != base["declarer"] % 2))
                        tgt["any_declare_change"] += r["declares"] != base["declares"]
                        tgt["history_changed"] += r["history_sha"] != base["history_sha"]
                        tgt["outcome_changed"] += r["arm_levels"] != b_lv
            gates, secs, changed = {}, [], 0
            admitted_per_round = []
            for d in full.values():
                for mm in (0, 1):
                    r = d[(arm, mm)]
                    n = 0
                    for c in r["chances"]:
                        if c["seat"] % 2 != mm:
                            continue
                        n += 1
                        gates[c["gate"]] = gates.get(c["gate"], 0) + 1
                        changed += bool(c["changed"])
                        if c["seconds"] is not None:
                            secs.append(c["seconds"])
                    admitted_per_round.append(n)
            role_ci = {k: (bootstrap_ci(v) if v else None) for k, v in role_diff.items()}
            res = dict(deals=len(full), levels=m, ci=[lo, hi], by_role=role_ci,
                       mechanism=mech, mechanism_by_role=mech_role,
                       arm_team_chances=dict(gates=gates, changed=changed,
                                             per_round_mean=sum(admitted_per_round) / len(admitted_per_round)))
            out[f"{kind}:{arm}"] = res
            print(f"[{kind}] {arm} vs r45 n={len(full)} levels/round {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
            for k, v in role_ci.items():
                if v:
                    print(f"    arm as {k:8s} diff vs r45 same seats {v[0]:+.4f} [{v[1]:+.4f}, {v[2]:+.4f}] (n={len(role_diff[k])} games)")
            print(f"    mechanism {mech}")
            for k, v in mech_role.items():
                print(f"      {k}: {v}")
            print(f"    arm-team value-declare chances: gates {gates} changed {changed} "
                  f"per arm-team round {res['arm_team_chances']['per_round_mean']:.2f}")
        # latency: release 45 baseline (all seats) and each arm (arm-team seats)
        lat = {}
        base_rows = [d[("r45", 0)] for d in deals.values() if ("r45", 0) in d]
        groups = {"r45": [(r, None) for r in base_rows]}
        for arm in arms:
            groups[arm] = [(d[(arm, mm)], mm) for d in deals.values() for mm in (0, 1) if (arm, mm) in d]
        for name, rows in groups.items():
            secs, per_round, per_round_secs = [], [], []
            for r, mm in rows:
                cs = [c for c in r["chances"] if mm is None or c["seat"] % 2 == mm]
                # per round of FOUR bots of this kind: a release-45 game counts all
                # four seats; an arm game counts its two seats, doubled below
                per_round.append(len(cs) * (1 if mm is None else 2))
                per_round_secs.append(sum(c["seconds"] or 0 for c in cs) * (1 if mm is None else 2))
                secs += [c["seconds"] for c in cs if c["seconds"] is not None]
            if not rows:
                continue
            lat[name] = dict(rounds=len(rows), chances=len(secs),
                             p50=_pct(secs, 50), p90=_pct(secs, 90), max=max(secs) if secs else None,
                             admitted_per_round=sum(per_round) / len(per_round),
                             declare_secs_per_round=sum(per_round_secs) / len(per_round_secs),
                             declare_secs_per_round_p90=_pct(per_round_secs, 90))
            L = lat[name]
            print(f"  [{kind}] latency {name}: admitted/round(4 seats) {L['admitted_per_round']:.2f} "
                  f"per-chance p50 {L['p50'] or 0:.3f}s p90 {L['p90'] or 0:.3f}s max {L['max'] or 0:.3f}s "
                  f"declare s/round {L['declare_secs_per_round']:.2f} (p90 {L['declare_secs_per_round_p90'] or 0:.2f})")
        out[f"{kind}:latency"] = lat
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kind", choices=("later", "first"), default="later")
    ap.add_argument("--arms", default="vdea,vdef")
    ap.add_argument("--seed0", type=int, default=81_600_000)
    ap.add_argument("--deals", type=int, default=20)
    ap.add_argument("--stride", type=int, default=1, help="play deals offset, offset+stride, ...")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out")
    ap.add_argument("--summarize", nargs="*")
    ap.add_argument("--json", help="write the summary here")
    a = ap.parse_args(argv)
    if a.summarize:
        res = summarize(a.summarize)
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=1))
        return
    arms = tuple(x for x in a.arms.split(",") if x)
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm {arm}")
    run(a.kind, a.seed0, a.deals, a.workers, a.out, arms, a.stride, a.offset)


if __name__ == "__main__":
    main()
