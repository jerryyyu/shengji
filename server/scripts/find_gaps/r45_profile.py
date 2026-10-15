"""Behaviour profile of release 45 from exploit_duel histories (DEV, descriptive).

Reads ``--history`` records (any arm; mirror 0 of the identity arm is plain
release 45 x4) and rebuilds each round with the engine to profile declaration,
bury, kitty, throws and void/ruff behaviour by seat team.

  .venv/bin/python scripts/find_gaps/r45_profile.py OUT/identity.jsonl [--team ex|r45|all]
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shengji.engine.cards import TRUMP, points  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.legal import uniform_suit  # noqa: E402
from shengji.ai.heuristic import HeuristicBot  # noqa: E402


def replay(rec):
    game = Game(random.Random(rec["seed"]))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    d = rec["declaration"]
    if d:
        rnd.declaration = dict(d)
    rnd.finalize_declare()
    assert rnd.banker == rec["banker"], "banker mismatch"
    rnd.bury(rnd.banker, rec["buried"])
    return rnd


def profile(recs, team_filter):
    hb = HeuristicBot()
    c = Counter()
    bury_pts, kitty_bonus, ap = [], [], []
    void_spots = Counter()
    for r in recs:
        rnd = replay(r)
        o = rnd.ordering
        banker = rnd.banker
        is_ex = lambda s: s % 2 == r["ex_team"]
        want = (lambda s: True) if team_filter == "all" else (
            is_ex if team_filter == "ex" else (lambda s: not is_ex(s)))
        c["rounds"] += 1
        if want(banker):
            c["banker_rounds"] += 1
            bury_pts.append(sum(points(x) for x in r["buried"]))
            decl = r["declaration"]
            if decl and decl["seat"] == banker:
                left = Counter(decl["cards"]) - Counter(r["buried"])
                if sum(left.values()) < len(decl["cards"]):
                    c["banker_buried_declared"] += 1
            # voids created by the bury (plain suits held before, none after)
            before = Counter(o.eff_suit(x) for x in rnd.hands[banker] + list(r["buried"]))
            after = Counter(o.eff_suit(x) for x in rnd.hands[banker])
            c["bury_voids"] += sum(1 for s in "SHDC" if before[s] and not after[s])
            c["bury_trumps"] += sum(1 for x in r["buried"] if o.eff_suit(x) == TRUMP)
            kitty_bonus.append(r["kitty_bonus"])
            if r["kitty_bonus"]:
                c["kitty_lost"] += 1
        ap.append(r["attacker_points"])
        for i, seat, ex_side in r["failed_throws"]:
            if want(seat):
                c["failed_throws"] += 1
        # replay plays for void/ruff decisions
        for seat, cards in r["history"]:
            trick = rnd.trick
            if trick.plays and want(seat):
                lead = trick.plays[0].cards
                ls = uniform_suit(lead, o)
                hand = rnd.hands[seat]
                if ls != TRUMP and not any(o.eff_suit(x) == ls for x in hand):
                    w, inc_suit, inc_top = hb._current_winner(rnd)
                    if w % 2 != seat % 2:
                        pts = sum(points(x) for tp in trick.plays for x in tp.cards)
                        last = len(trick.plays) == 3
                        win = hb._cheapest_winning(hand, lead, inc_suit, inc_top, o)
                        if win is not None and o.eff_suit(win[0]) == TRUMP:
                            ruffed = o.eff_suit(cards[0]) == TRUMP
                            band = "pts>=10" if pts >= 10 else ("pts1-9" if pts else "pts0")
                            key = f"{'last' if last else 'notlast'}:{band}"
                            void_spots[key + ":n"] += 1
                            void_spots[key + ":ruff"] += ruffed
            rnd.play(seat, cards)
    out = dict(c)
    out["bury_points_mean"] = st.mean(bury_pts) if bury_pts else None
    out["bury_points_dist"] = dict(Counter(bury_pts).most_common(8))
    out["kitty_bonus_mean_per_banker_round"] = st.mean(kitty_bonus) if kitty_bonus else None
    out["attacker_points_mean"] = st.mean(ap)
    out["void_ruff"] = {k[:-2]: f"{void_spots[k[:-2] + ':ruff']}/{void_spots[k]}"
                        for k in sorted(void_spots) if k.endswith(":n")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--team", default="all", choices=["all", "ex", "r45"])
    ap.add_argument("--mirror", type=int, default=None)
    a = ap.parse_args()
    recs = []
    for p in a.paths:
        for line in open(p):
            r = json.loads(line)
            if "history" in r and (a.mirror is None or r["mirror"] == a.mirror):
                recs.append(r)
    print(json.dumps(profile(recs, a.team), indent=1))


if __name__ == "__main__":
    main()
