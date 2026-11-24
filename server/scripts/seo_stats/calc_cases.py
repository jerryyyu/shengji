"""The score calculator's fixture, every case scored by the engine itself.

The /guides/score-calculator page (web/src/guides/scoreCalc.ts and the page's
own script) must agree with the engine on each case written here. A case is
stated in the calculator's terms: the attackers' trick points, who won the
last trick, the kitty's points, the shape of the last lead and the rules
variant, the banker's seat and both teams' levels. To score it, this script
builds real cards for the kitty and the lead and runs

* ``shengji.engine.rules_profile.kitty_multiplier`` on the lead (the default
  profile is ``Round._resolve_trick``'s ``2 x cards led``; ``SHENGJIORG``
  is ``2 x the largest decompose() component``), and
* ``shengji.engine.game.Game.finish_round`` on a round whose end state is set,

and records what they return. Seats run 0-3 in play order (North, East,
South, West); teams are 0+2 and 1+3.

Usage (from server/): python scripts/seo_stats/calc_cases.py [OUT.json]
The default output is web/src/guides/__fixtures__/score_cases.json.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from shengji.engine.cards import RANKS, Ordering, total_points
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.rules_profile import DEFAULT, SHENGJIORG, kitty_multiplier

FIXTURE = Path(__file__).resolve().parents[3] / "web" / "src" / "guides" / "__fixtures__" / "score_cases.json"

TRUMP_SUIT = "H"   # the multiplier and the levels do not depend on the trump suit
LEAD_SUIT = "D"    # leads are built in a side suit
VARIANTS = {"site": DEFAULT, "largest-part": SHENGJIORG}

# shape -> (pairs as offsets into the side suit's ranks, singles likewise).
# Offset 0 is the highest side rank, 1 the next one down, and so on, skipping
# the level rank, so consecutive offsets are consecutive in play.
LEAD_SHAPES: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "single": ((), (0,)),
    "pair": ((0,), ()),
    "two-singles": ((), (0, 1)),
    "pair-single": ((0,), (2,)),
    "two-pairs": ((0, 2), ()),
    "tractor-2": ((0, 1), ()),
    "tractor-2-single": ((0, 1), (3,)),
    "tractor-3": ((0, 1, 2), ()),
    "tractor-4": ((0, 1, 2, 3), ()),
}


def lead_cards(shape: str, level: str) -> list[str]:
    side = [r for r in reversed(RANKS) if r != level]
    pairs, singles = LEAD_SHAPES[shape]
    out = []
    for i in pairs:
        out += [LEAD_SUIT + side[i]] * 2
    for i in singles:
        out.append(LEAD_SUIT + side[i])
    return out


def kitty_cards(points: int) -> list[str]:
    """Eight cards holding ``points`` (a multiple of 5, at most 80)."""
    assert points % 5 == 0 and 0 <= points <= 80, points
    tens, five = divmod(points, 10)
    cards = ["SK", "S10", "CK", "C10", "DK", "D10", "HK", "H10"][:tens] + ["S5"] * (five // 5)
    return cards + ["S3"] * (8 - len(cards))


def score(case: dict) -> dict:
    inp = case["input"]
    levels = inp["levels"]
    banker = inp["banker"]
    game = Game(random.Random(0), games_to_win=1)
    game.level_idx = [RANKS.index(levels[0]), RANKS.index(levels[1])]
    game.banker = banker
    rnd = game.start_round()
    ordering = Ordering(TRUMP_SUIT, rnd.trump_rank)
    lead = lead_cards(inp["lead"], rnd.trump_rank)
    buried = kitty_cards(inp["kittyPoints"])
    assert total_points(buried) == inp["kittyPoints"]
    largest = max(c.size for c in decompose(list(lead), ordering).components)
    mult = kitty_multiplier(lead, ordering, VARIANTS[inp["variant"]]) if inp["attackersWonLast"] else 0
    bonus = total_points(buried) * mult
    rnd.ordering = ordering
    rnd.buried = list(buried)
    rnd.kitty_bonus = bonus
    rnd.attacker_points = inp["trickPoints"] + bonus
    rnd.phase = "round_end"
    res = game.finish_round()
    return {
        "name": case["name"],
        "input": inp,
        "engine": {"leadCards": lead, "leadCardCount": len(lead), "leadLargestPart": largest, "buried": buried},
        "output": {
            "multiplier": mult,
            "bonus": bonus,
            "total": rnd.attacker_points,
            "winner": "defenders" if res.winner_team == banker % 2 else "attackers",
            "winnerTeam": res.winner_team,
            "levelsGained": res.level_change,
            "nextBanker": res.next_banker,
            "newLevels": list(res.new_levels),
            "gameWon": res.point_scored,
        },
    }


def case(name, banker, levels, tricks, last, kitty=0, lead="single", variant="site") -> dict:
    return {"name": name, "input": {
        "trickPoints": tricks, "attackersWonLast": last == "attackers", "kittyPoints": kitty,
        "lead": lead, "variant": variant, "banker": banker, "levels": list(levels)}}


# The kitty points of cases 1-6 and 11-12 are their buried points; the
# defenders win the last trick, so they score nothing.
CASES = [
    case("Shut-out", 0, ("2", "2"), 0, "defenders"),
    case("Held under 40", 0, ("5", "3"), 35, "defenders"),
    case("Exactly 40", 1, ("4", "7"), 40, "defenders"),
    case("Just short at 75", 2, ("9", "6"), 75, "defenders"),
    case("Exactly 80: the deal passes, no level", 0, ("J", "8"), 80, "defenders"),
    case("120: the deal passes, up 1", 3, ("6", "10"), 120, "defenders"),
    case("The kitty flips it (single lead, x2)", 0, ("3", "3"), 70, "attackers", 10, "single"),
    case("The kitty on a pair lead (x4)", 1, ("8", "5"), 100, "attackers", 25, "pair"),
    case("Pair and single throw, this site's rule (x6)", 0, ("7", "7"), 40, "attackers", 20, "pair-single"),
    case("Same throw, largest-part rule (x4)", 0, ("7", "7"), 40, "attackers", 20, "pair-single", "largest-part"),
    case("Defending A wins the game", 2, ("A", "Q"), 60, "defenders"),
    case("Attackers on K go up 2, capped at A", 0, ("10", "K"), 165, "defenders"),
    # edge cases
    case("Kitty points with the defenders winning the last trick score nothing", 0, ("2", "2"), 70, "defenders", 40, "pair"),
    case("Over 200, only through the kitty", 0, ("5", "5"), 150, "attackers", 25, "pair"),
    case("The largest kitty on the largest lead", 1, ("4", "6"), 120, "attackers", 80, "tractor-4"),
    case("Shut out in tricks, saved by the kitty", 2, ("2", "2"), 0, "attackers", 40, "pair"),
    case("Defenders on K go up 3, capped at A, not a win", 0, ("K", "9"), 0, "defenders"),
    case("Attackers at A take the deal: no win yet", 0, ("8", "A"), 130, "defenders"),
    case("Defending A with a shut-out still wins only the game", 1, ("3", "A"), 0, "defenders"),
    case("Losing a defence at A passes the deal", 3, ("5", "A"), 80, "defenders"),
    case("115 is still no level", 3, ("2", "2"), 115, "defenders"),
    case("155 is still up 1", 2, ("2", "2"), 155, "defenders"),
    case("160 is up 2", 2, ("2", "2"), 160, "defenders"),
    case("Five points is up 2 for the defenders", 1, ("2", "2"), 5, "defenders"),
    case("Banker West: the deal passes to North", 3, ("2", "2"), 90, "defenders"),
    case("Banker West: the deal stays with East", 3, ("2", "2"), 60, "defenders"),
]
for _shape in LEAD_SHAPES:
    for _variant in VARIANTS:
        CASES.append(case(f"Lead {_shape}, {_variant} rule", 0, ("10", "4"), 40, "attackers", 15, _shape, _variant))
# every trick total from 0 to 200 at one table, to pin the threshold arithmetic
for _p in range(0, 205, 5):
    CASES.append(case(f"Sweep {_p}", 0, ("2", "2"), _p, "defenders"))
# past 200 only the kitty gets there: 120 in tricks plus a buried 80 at x2 to x16
for _shape in LEAD_SHAPES:
    CASES.append(case(f"Sweep 120 + 80 on a {_shape} lead", 0, ("2", "2"), 120, "attackers", 80, _shape))


def build() -> list[dict]:
    return [score(c) for c in CASES]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{out}: {len(CASES)} cases")


if __name__ == "__main__":
    main()
