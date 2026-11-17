"""AV1: replay archived paired-duel rows (exploit_duel_s61 format, rows carry ``dtrace``) and price every play
decision on the TRUE world with the served value head.

For each row (one mirror of one deal) the round is rebuilt from the row's seed and plan entry (round_kind, trump_rank,
planned_banker), every traced declare / final declare / bury / play is re-applied in order, and the replay is checked
against the row (declaration, banker, attacker points, level change, ex_levels).  Before each play the served R52 bot's own
value pass is run on the one true world for the traced action: ``bot._value_means(rnd, seat, [action], [(hands, buried)])``,
a score in signed levels for the acting seat's team, then sign-normalized to the exploiter team.

Output (one JSON line per row): seed, mirror, ex_team, ex_levels, and ``u`` = [[seat, u_t], ...] per play decision.
Pre-treatment deal features (AMENDMENT_AV1_1 item 4) are written for mirror 0 rows as ``feat``.

Usage: replay_values.py IN.jsonl OUT.jsonl [--limit N] [--models DIR] [--fly-toml PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
# AV1_SERVER: the engine tree to replay with (default: this worktree's server); the archived duels were produced by
# claude-bx4duel-src 99338c7e, whose compiled engine is used read-only.
SERVER = Path(os.environ.get("AV1_SERVER", HERE.parents[2]))
sys.path.insert(0, str(SERVER))

from shengji.engine.cards import is_joker, points  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.train.leaf_screen import _game_factory_for  # noqa: E402


def make_round(row):
    kind, rank, fixed = row["round_kind"], row["trump_rank"], row["planned_banker"]
    if kind == "first":
        game = Game(random.Random(row["seed"]))
    else:
        game = _game_factory_for(rank, fixed)(random.Random(row["seed"]))
    rnd = game.start_round()
    assert rnd.trump_rank == rank and bool(rnd.first_round) == (kind == "first")
    assert fixed is None or rnd.banker == fixed
    return game, rnd


def deal_features(rnd, kind, fixed):
    """The dealt hands are complete only after the deal phase; called by the caller once all cards are dealt and
    before any bury (``rnd.hands`` are 25-card hands, ``rnd.kitty`` the 8 dealt kitty cards)."""
    rank = rnd.trump_rank
    J, R, P = [0, 0], [0, 0], [0, 0]
    for s in range(4):
        for c in rnd.hands[s]:
            if is_joker(c):
                J[s % 2] += 1
            elif c[1:] == rank:
                R[s % 2] += 1
            P[s % 2] += points(c)
    kit = list(getattr(rnd, "kitty", None) or [])
    kp = sum(points(c) for c in kit)
    bank = (J[fixed % 2] + R[fixed % 2]) if (kind != "first" and fixed is not None) else 0
    return [abs(J[0] - J[1]), abs(R[0] - R[1]), abs(P[0] - P[1]),
            (J[0] + R[0]) * (J[1] + R[1]), bank, kp, 1 if kind == "first" else 0]


def build_bot(models: Path, fly_toml: Path):
    from shengji.eval.served_config import build_served_bot, served_env
    mappings = {f"/data/models/{p.name}": str(p) for p in models.iterdir()}
    env = served_env(fly_toml=fly_toml, mappings=mappings)
    name, bot = build_served_bot(env, seed=13)
    return name, bot


def replay_row(row, bot, want_features):
    game, rnd = make_round(row)
    trace = row["dtrace"]
    i = 0
    feat = None
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        ph, ts, _, _, hand, cards = trace[i]
        assert ph == "D" and ts == seat and hand == len(rnd.hands[seat]), (i, trace[i], seat)
        if cards:
            rnd.declare(seat, cards)
        i += 1
    for seat in range(4):
        ph, ts, _, _, hand, cards = trace[i]
        assert ph == "F" and ts == seat, (i, trace[i])
        if cards:
            rnd.declare(seat, cards)
        i += 1
    if want_features:
        feat = deal_features(rnd, row["round_kind"], row["planned_banker"])
    rnd.finalize_declare()
    assert rnd.banker == row["banker"], (rnd.banker, row["banker"])
    ph, ts, _, _, hand, cards = trace[i]
    assert ph == "B" and ts == rnd.banker and hand == len(rnd.hands[ts])
    rnd.bury(ts, cards)
    i += 1
    ex_team = row["ex_team"]
    u = []
    while rnd.phase == "play":
        seat = rnd.turn
        ph, ts, _, _, hand, cards = trace[i]
        assert ph == "P" and ts == seat and hand == len(rnd.hands[seat]), (i, trace[i], seat)
        hands = [list(h) for h in rnd.hands]
        buried = list(rnd.buried)
        means, _ = bot._value_means(rnd, seat, [list(cards)], [(hands, buried)])
        v = float(means[0])
        u.append([seat, round(v if seat % 2 == ex_team else -v, 6)])
        rnd.play(seat, list(cards))
        i += 1
    assert i == len(trace), (i, len(trace))
    result = game.finish_round()
    won = result.winner_team == ex_team
    signed = result.level_change if won else -result.level_change
    assert signed == row["ex_levels"], (signed, row["ex_levels"])
    assert result.attacker_points == row["attacker_points"]
    return {"seed": row["seed"], "mirror": row["mirror"], "ex_team": ex_team, "ex_levels": row["ex_levels"],
            "u": u, **({"feat": feat} if feat is not None else {})}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--models", default="/Users/jerryyu/.claude/jobs/d0498cda/tmp/rd1av1/av1/models")
    ap.add_argument("--fly-toml", default=str(SERVER.parent / "fly.toml"))
    a = ap.parse_args(argv)
    name, bot = build_bot(Path(a.models), Path(a.fly_toml))
    print("bot", name, file=sys.stderr)
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            r = json.loads(line)
            done.add((r["seed"], r["mirror"]))
    t0 = time.time()
    n = 0
    with open(a.inp) as fin, open(a.out, "a") as fout:
        for line in fin:
            row = json.loads(line)
            if (row["seed"], row["mirror"]) in done:
                continue
            rec = replay_row(row, bot, want_features=True)
            fout.write(json.dumps(rec) + "\n")
            fout.flush()
            n += 1
            if a.limit and n >= a.limit:
                break
            if n % 50 == 0:
                print(f"{n} rows {time.time() - t0:.0f}s", file=sys.stderr)
    print(f"done {n} rows {time.time() - t0:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
