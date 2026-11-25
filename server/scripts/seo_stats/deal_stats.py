"""Deal-only statistics for a 4-player, 2-deck Sheng Ji deal (108 cards, 25 each, kitty 8).

Exact values come from hypergeometric counting; hand-shape values come from
simulated deals using the engine's own Round (shuffle + deal) and has_tractor.

The page /guides/sheng-ji-by-the-numbers quotes results/deal_stats.json,
written by: (from server/)
  PYTHONPATH=. python scripts/seo_stats/deal_stats.py 1000000 4 20261124 scripts/seo_stats/results/deal_stats.json
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from fractions import Fraction
from itertools import product
from math import comb
from multiprocessing import Pool

from shengji.engine.cards import Ordering, card_rank, card_suit, is_joker, total_points
from shengji.engine.combos import has_tractor, pair_count
from shengji.engine.round import Round, HAND_SIZE

TRUMP_RANK = "2"      # every game starts at level 2
TRUMP_SUIT = "H"      # any fixed suit; suits are symmetric under a uniform shuffle


def exact() -> dict:
    N, H, K = 108, 25, 8
    p_lj = Fraction(comb(N - 2, H - 2), comb(N, H))          # both little jokers
    p_all4 = Fraction(comb(N - 4, H - 4), comb(N, H))        # all four jokers
    p_either = 2 * p_lj - p_all4
    p_no_two = Fraction(comb(N - 8, H), comb(N, H))          # none of the eight level-2 cards
    # kitty: 8 fives (5 pts), 16 tens+kings (10 pts), 84 blanks
    dist: Counter = Counter()
    for f, t in product(range(0, 9), range(0, 9)):
        if f + t > K:
            continue
        ways = comb(8, f) * comb(16, t) * comb(84, K - f - t)
        dist[5 * f + 10 * t] += ways
    total = comb(N, K)
    kdist = {pts: w / total for pts, w in sorted(dist.items())}
    mean_pts = sum(p * q for p, q in kdist.items())
    return {
        "p_both_little_jokers": float(p_lj),
        "p_both_big_jokers": float(p_lj),
        "p_both_jokers_of_some_colour": float(p_either),
        "p_all_four_jokers": float(p_all4),
        "p_holds_a_trump_rank_card": float(1 - p_no_two),
        "kitty_mean_point_cards": K * 24 / N,
        "kitty_mean_points": mean_pts,
        "kitty_mean_points_closed_form": K * 200 / N,
        "kitty_p_zero_points": kdist[0],
        "kitty_p_ge_20": sum(q for p, q in kdist.items() if p >= 20),
        "kitty_p_ge_30": sum(q for p, q in kdist.items() if p >= 30),
        "kitty_p_ge_40": sum(q for p, q in kdist.items() if p >= 40),
        "kitty_points_distribution": kdist,
        "method": "exact hypergeometric counting over the 108-card deck",
    }


def groups(hand, o):
    g: dict[str, list[str]] = {}
    for c in hand:
        g.setdefault(o.eff_suit(c), []).append(c)
    return g


def worker(args):
    seed, n = args
    rng = random.Random(seed)
    o_suit = Ordering(TRUMP_SUIT, TRUMP_RANK)
    o_nt = Ordering(None, TRUMP_RANK)
    c = Counter()
    pairs_hist = Counter()
    kitty_pts = 0
    kitty_cards = 0
    for _ in range(n):
        rnd = Round(TRUMP_RANK, 0, rng)
        while rnd.phase == "deal":
            rnd.deal_next()
        kitty_pts += total_points(rnd.kitty)
        kitty_cards += sum(1 for x in rnd.kitty if total_points([x]) > 0)
        for hand in rnd.hands:
            assert len(hand) == HAND_SIZE
            c["hands"] += 1
            npairs = pair_count(hand)
            pairs_hist[npairs] += 1
            if npairs >= 1:
                c["ge1_pair"] += 1
            g = groups(hand, o_suit)
            trump_tr = has_tractor(g.get("T", []), o_suit, 2)
            side_tr = any(has_tractor(v, o_suit, 2) for k, v in g.items() if k != "T")
            if trump_tr:
                c["tractor_trump"] += 1
            if side_tr:
                c["tractor_side"] += 1
            if trump_tr or side_tr:
                c["tractor_any"] += 1
            if any(has_tractor(v, o_suit, 3) for v in g.values()):
                c["tractor3_any"] += 1
            gn = groups(hand, o_nt)
            if any(has_tractor(v, o_nt, 2) for v in gn.values()):
                c["tractor_any_nt"] += 1
            cnt = Counter(hand)
            if cnt["LJ"] == 2 or cnt["BJ"] == 2:
                c["joker_pair"] += 1
            # a declarable pair: two identical trump-rank cards or a joker pair
            if any(n2 >= 2 for code, n2 in cnt.items()
                   if is_joker(code) or card_rank(code) == TRUMP_RANK):
                c["declarable_pair"] += 1
            if any(card_rank(x) == TRUMP_RANK for x in hand):
                c["holds_trump_rank"] += 1
    return c, pairs_hist, kitty_pts, kitty_cards, n


def main():
    n_deals, procs, seed, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    per = n_deals // procs
    with Pool(procs) as pool:
        parts = pool.map(worker, [(seed + i, per) for i in range(procs)])
    c, ph = Counter(), Counter()
    kp = kc = deals = 0
    for a, b, x, y, n in parts:
        c.update(a); ph.update(b); kp += x; kc += y; deals += n
    h = c["hands"]

    def rate(k):
        p = c[k] / h
        return {"p": p, "count": c[k], "n_hands": h}
    sim = {
        "method": ("engine Round(trump_rank='2') shuffle+deal, hands of 25; tractors via "
                   "engine.combos.has_tractor per effective suit under Ordering(H, '2') "
                   "(and Ordering(None,'2') for no-trump); 4 hands per deal, so hands within a "
                   "deal are not independent"),
        "seeds": [seed + i for i in range(procs)],
        "n_deals": deals, "n_hands": h,
        "p_ge1_pair": rate("ge1_pair"),
        "mean_pairs_per_hand": sum(k * v for k, v in ph.items()) / h,
        "pairs_hist": dict(sorted(ph.items())),
        "p_tractor_in_trump": rate("tractor_trump"),
        "p_tractor_in_a_side_suit": rate("tractor_side"),
        "p_tractor_any_suit": rate("tractor_any"),
        "p_three_pair_tractor_any_suit": rate("tractor3_any"),
        "p_tractor_any_suit_if_no_trump": rate("tractor_any_nt"),
        "p_joker_pair": rate("joker_pair"),
        "p_declarable_pair_at_level2": rate("declarable_pair"),
        "p_holds_a_trump_rank_card": rate("holds_trump_rank"),
        "kitty_mean_points_sim": kp / deals,
        "kitty_mean_point_cards_sim": kc / deals,
    }
    with open(out, "w") as fh:
        json.dump({"exact": exact(), "simulated": sim}, fh, indent=1)
        fh.write("\n")
    print(json.dumps({k: v for k, v in sim.items() if k != "pairs_hist"}, indent=1))
    print(json.dumps({k: v for k, v in exact().items() if k != "kitty_points_distribution"}, indent=1))


if __name__ == "__main__":
    main()
