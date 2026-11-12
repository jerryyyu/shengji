#!/usr/bin/env python3
"""Fixtures that hold the TypeScript offline bots to SmartBot and HeuristicBot.

The bots under ``web/src/offline/bot/`` are ports of ``shengji.ai.smart`` and
``shengji.ai.heuristic``; their vitest suite replays these fixtures and
asserts every recorded decision.  Two files are written to ``--out``:

``bot_rounds.jsonl.gz``
    A header line, then one line per round.  Games are driven like
    ``shengji.ai.env.play_round``: after every dealt card the receiving seat's
    bot is asked whether to declare, then each seat once more in the grace
    window (``final=True``), then the banker buries and the bots play every
    trick.  A round records its deck, every declaration the bots made (all
    other declare decisions were passes), the bury and every attempted play.
    The first ``--rounds`` rounds seat SmartBot four times; the next
    ``--mixed`` rounds seat a per-game mix of SmartBot and HeuristicBot.

``bot_primitives.json.gz``
    The randomized inputs of ``tests/test_fast_parity.py`` for
    ``HeuristicBot._lowest``, ``_forced_follow`` and ``_cheapest_winning``
    (same seeds and draws, truncated to ``PRIMITIVE_LIMITS``) with the pure
    outputs, plus that file's named ``_cheapest_winning`` witnesses.

Everything is a deterministic function of the arguments.

Usage::

    python scripts/gen_offline_bot_fixtures.py --rounds 300 --mixed 100 \\
        --out ../web/src/offline/fixtures
    python scripts/gen_offline_bot_fixtures.py --rounds 10000 --mixed 2000 \\
        --out /tmp/x
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from collections import Counter
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (SERVER_DIR, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gen_offline_engine_fixtures import (  # noqa: E402
    CONFIGS, _dumps, _gzip_bytes, _random_lead, _suit_groups)
from shengji.engine import combos, legal  # noqa: E402
from shengji.engine.cards import TRUMP, Ordering, make_deck  # noqa: E402
from shengji.engine.game import Game  # noqa: E402

FORMAT = 1
MAX_ROUNDS_PER_GAME = 40
# (start_level, games_to_win), cycled per game: every trump rank is reached.
GAME_CONFIGS = [("2", 1), ("10", None), ("Q", 2), ("A", 1), ("6", None),
                ("K", None)]
# Seatings for the mixed games, cycled per game.
MIXED_SEATS = [
    ("smart", "heuristic", "smart", "heuristic"),
    ("heuristic", "smart", "heuristic", "smart"),
    ("smart", "smart", "heuristic", "heuristic"),
    ("heuristic", "heuristic", "smart", "smart"),
    ("smart", "heuristic", "heuristic", "smart"),
    ("heuristic", "heuristic", "heuristic", "smart"),
]
PRIMITIVE_LIMITS = {"policy_iterations": 3000, "cheapest_iterations": 30_000}


def _bot(kind):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.ai.smart import SmartBot
    return SmartBot() if kind == "smart" else HeuristicBot()


def play_recorded_round(game, bots, kinds, stats):
    rec = {"levels": list(game.levels), "banker": game.banker,
           "gamesWon": list(game.games_won)}
    rnd = game.start_round()
    rec["trumpRank"] = rnd.trump_rank
    rec["deck"] = list(rnd.deck)
    declares = []

    def ask(seat, final):
        cards = bots[seat].decide_declare(rnd, seat, final=final)
        stats[f"{kinds[seat]}_declare_decisions"] += 1
        if cards:
            declares.append([rnd._deal_pos, seat, int(final), list(cards)])
            stats[f"{kinds[seat]}_declares"] += 1
            rnd.declare(seat, cards)

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        ask(seat, False)
    for seat in range(4):
        ask(seat, True)
    rec["declares"] = declares
    rnd.finalize_declare()
    rec["trump"] = [rnd.trump_suit, rnd.banker]
    bury = list(bots[rnd.banker].decide_bury(rnd, rnd.banker))
    stats[f"{kinds[rnd.banker]}_bury"] += 1
    rnd.bury(rnd.banker, bury)
    rec["bury"] = bury
    plays = []
    while rnd.phase == "play":
        seat = rnd.turn
        kind = "lead" if not rnd.trick.plays else "follow"
        cards = list(bots[seat].decide_play(rnd, seat))
        stats[f"{kinds[seat]}_{kind}"] += 1
        plays.append(cards)
        rnd.play(seat, cards)
    rec["plays"] = plays
    rec["attackerPoints"] = rnd.attacker_points
    game.finish_round()
    stats["rounds"] += 1
    return rec


def iter_rounds(n_smart, n_mixed, seed, stats):
    g = 0
    for n_rounds, mixed in ((n_smart, False), (n_mixed, True)):
        produced = 0
        while produced < n_rounds:
            start, to_win = GAME_CONFIGS[g % len(GAME_CONFIGS)]
            kinds = (MIXED_SEATS[g % len(MIXED_SEATS)] if mixed
                     else ("smart",) * 4)
            game = Game(random.Random(seed * 1_000_003 + g), start_level=start,
                        games_to_win=to_win)
            bots = [_bot(k) for k in kinds]
            r = 0
            while (not game.game_over and r < MAX_ROUNDS_PER_GAME
                   and produced < n_rounds):
                rec = play_recorded_round(game, bots, kinds, stats)
                head = {"game": g, "round": r}
                if r == 0:
                    head["config"] = {"seats": list(kinds), "startLevel": start,
                                      "gamesToWin": to_win}
                    stats["games"] += 1
                yield {**head, **rec}
                produced += 1
                r += 1
            g += 1


def rounds_text(n_smart, n_mixed, seed, stats=None):
    stats = Counter() if stats is None else stats
    lines = [_dumps(r) for r in iter_rounds(n_smart, n_mixed, seed, stats)]
    header = {"format": FORMAT, "rounds": n_smart, "mixed": n_mixed,
              "seed": seed, "stats": dict(sorted(stats.items()))}
    return "\n".join([_dumps(header)] + lines) + "\n"


# --------------------------------------------------------------- primitives

def _outcome(fn, *args):
    try:
        return fn(*args)
    except legal.IllegalPlay as e:
        return {"exc": "IllegalPlay", "msg": str(e)}
    except AssertionError:
        return {"exc": "AssertionError"}


NAMED_CHEAPEST = [
    ("single", ("H", "7"), ["S10", "SJ", "SA"], ["S9"], "S", 6),
    ("pair", ("H", "7"), ["SJ", "SJ", "S10", "S10"], ["S9", "S9"], "S", 6),
    ("tractor", ("H", "7"), ["S9", "S9", "S10", "S10", "SJ", "SJ"],
     ["S8", "S8", "S9", "S9"], "S", 6),
    ("void-ruff", ("H", "7"), ["H2", "H3", "C4"], ["D9"], "D", 6),
    ("partial-suit", ("H", "7"), ["S10", "H2", "H3"], ["S9", "S9"], "S", 6),
    ("already-ruffed", ("H", "7"), ["S10", "SJ", "SA"], ["S9"], "T", 2),
    ("throw-ruff", ("H", "7"), ["H2", "H2", "H3", "C4"], ["S3", "S3", "SA"],
     "S", 1),
    ("equal-level-pair", ("H", "7"), ["D7", "D7", "S7", "S7", "D4"],
     ["C9", "C9"], "C", 6),
    ("no-trump-level-tie", (None, "7"), ["C7", "S7", "H3"], ["D9"], "D", 6),
]


def primitives():
    """test_fast_parity's policy-leaf draws, replayed with the same seeds."""
    from shengji.ai.heuristic import HeuristicBot

    class _NoVoidDump(HeuristicBot):
        VOID_DUMP = False

    out = {"lowest": [], "forced": [], "cheapest": []}
    # test_points_and_policy_leaves_random_parity
    rng = random.Random(424242)
    deck = make_deck()
    bots = [HeuristicBot(), _NoVoidDump()]
    for i in range(PRIMITIVE_LIMITS["policy_iterations"]):
        cfg = CONFIGS[i % len(CONFIGS)]
        op = Ordering(*cfg)
        bot = bots[i % 2]
        hand = rng.sample(deck, rng.randint(1, 25))
        avoid = (None if rng.random() < 0.4
                 else set(rng.sample(hand, rng.randint(0, len(hand) // 2))))
        avoid_list = None if avoid is None else sorted(avoid)
        got = [bot._lowest(hand, op, avoid_points=ap, seek_points=sp,
                           avoid=avoid)
               for ap, sp in ((False, False), (True, False), (False, True))]
        out["lowest"].append([list(cfg), bot.VOID_DUMP, hand, avoid_list, got])
        lead_hand = rng.sample(deck, rng.randint(1, 14))
        lead_group = rng.choice(list(_suit_groups(lead_hand, op).values()))
        lead = _random_lead(rng, lead_group)
        if len(hand) < len(lead):
            continue
        got = [_outcome(bot._forced_follow, hand, lead, op, prefer, avoid)
               for prefer in (False, True)]
        out["forced"].append([list(cfg), bot.VOID_DUMP, hand, lead, avoid_list,
                              got])

    bot = HeuristicBot()
    for label, cfg, hand, lead, inc_suit, inc_top in NAMED_CHEAPEST:
        ref = _outcome(bot._cheapest_winning, list(hand), list(lead), inc_suit,
                       inc_top, Ordering(*cfg))
        out["cheapest"].append([list(cfg), hand, lead, inc_suit, inc_top, ref,
                                label])
    # test_cheapest_winning_random_and_shape_weighted_parity
    rng = random.Random(20260813)
    for i in range(PRIMITIVE_LIMITS["cheapest_iterations"]):
        cfg = CONFIGS[i % len(CONFIGS)]
        op = Ordering(*cfg)
        source = rng.sample(deck, rng.randint(4, 28))
        groups = list(_suit_groups(source, op).values())
        group = rng.choice(groups)
        mode = i % 5
        if mode == 0:
            lead = [rng.choice(group)]
        elif mode == 1:
            pair_codes = [c for c, n in Counter(group).items() if n >= 2]
            lead = ([rng.choice(pair_codes)] * 2 if pair_codes
                    else [rng.choice(group)])
        elif mode == 2:
            runs = []
            complete_group = rng.choice(list(_suit_groups(deck, op).values()))
            for k in (2, 3, 4):
                runs.extend(combos.find_tractor_runs(complete_group, op, k))
            lead = list(rng.choice(runs))
        else:
            lead = _random_lead(rng, group)
        hand = rng.sample(deck, rng.randint(1, 33))
        lead_suit = legal.uniform_suit(lead, op)
        assert lead_suit is not None
        inc_suit = rng.choice([lead_suit, TRUMP,
                               rng.choice(["S", "H", "C", "D"])])
        inc_top = rng.randint(-1, 15)
        ref = _outcome(bot._cheapest_winning, list(hand), list(lead), inc_suit,
                       inc_top, op)
        out["cheapest"].append([list(cfg), hand, lead, inc_suit, inc_top, ref])
    return out


def primitives_text():
    return _dumps({"format": FORMAT, **primitives()}) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rounds", type=int, default=300,
                    help="rounds with SmartBot at every seat")
    ap.add_argument("--mixed", type=int, default=100,
                    help="rounds with mixed SmartBot/HeuristicBot seats")
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    if os.environ.get("SHENGJI_RULES_PROFILE"):
        ap.error("SHENGJI_RULES_PROFILE must be unset: fixtures are our rules")
    args.out.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    text = rounds_text(args.rounds, args.mixed, args.seed, stats)
    (args.out / "bot_rounds.jsonl.gz").write_bytes(_gzip_bytes(text))
    (args.out / "bot_primitives.json.gz").write_bytes(
        _gzip_bytes(primitives_text()))
    print(_dumps({"out": str(args.out), **dict(sorted(stats.items()))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
