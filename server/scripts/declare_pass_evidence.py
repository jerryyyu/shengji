#!/usr/bin/env python3
"""How often does a seat that could over-declare stay silent?  (#707 S15(4))

Read-only over production room logs (``logs/*.jsonl`` and ``logs/archive``):
for every round with one ``round_start`` (the deck) and one ``trump`` event,
the deal is replayed card by card (round-robin from seat 0) and each
``declare`` event is placed at a deal position: ``max(the card that
completed the declared cards, (t - t_round_start) / --rate)`` capped at 100
(100 = the grace window after the deal).  An EPISODE opens when a seat other
than the current declarer first holds a combination stronger than the current
declaration (a trump-rank single over nothing; a trump-rank pair, or a joker
pair, over something weaker); a single episode that becomes a pair restarts as
a pair episode.  It closes as ``declared`` (the seat declares), ``preempted``
(another declaration makes its combination too weak), ``immediate`` (it declares on the
very card that made it eligible: zero wait, no exposure), ``grace`` (it
declares only after the deal), ``upgraded`` or ``passed`` (it never declares).

Printed per (human|bot, single|pair): the outcome counts, the zero-wait
share, and the geometric hazard per own card dealt AFTER the first chance
(deal-time declarations with at least one silent own card / those own cards).
`shengji.train.declare_pass_worlds.HAZARD` is an exploratory fixed constant
chosen at or below these human estimates, not a calibrated rate.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

DEAL = 100


def strength(cards, rank):
    if len(cards) == 1 and cards[0] not in ("LJ", "BJ") and cards[0][1:] == rank:
        return 1
    if len(cards) == 2 and cards[0] == cards[1]:
        code = cards[0]
        if code == "BJ":
            return 4
        if code == "LJ":
            return 3
        if code[1:] == rank:
            return 2
    return None


def best(hand, rank):
    counts, top = collections.Counter(hand), 0
    for code, n in counts.items():
        if code == "BJ" and n >= 2:
            top = max(top, 4)
        elif code == "LJ" and n >= 2:
            top = max(top, 3)
        elif code not in ("LJ", "BJ") and code[1:] == rank:
            top = max(top, 2 if n >= 2 else 1)
    return top


def completed_at(deck, seat, cards):
    need, have = collections.Counter(cards), collections.Counter()
    for i in range(seat, DEAL, 4):
        have[deck[i]] += 1
        if all(have[c] >= n for c, n in need.items()):
            return i
    raise ValueError("declared cards were never dealt to the declarer")


def rounds(log_dir):
    files = glob.glob(f"{log_dir}/*.jsonl") + glob.glob(f"{log_dir}/archive/**/*.jsonl",
                                                          recursive=True)
    events, seen = collections.defaultdict(list), set()
    for path in files:
        for line in open(path):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "e" not in d:
                continue
            key = (d["room"], d["round"], d["t"], d["e"], d.get("seat"))
            if key not in seen:
                seen.add(key)
                events[(d["room"], d["round"])].append(d)
    for evs in events.values():
        evs.sort(key=lambda d: d["t"])
        start = [d for d in evs if d["e"] == "round_start"]
        trump = [d for d in evs if d["e"] == "trump"]
        if len(start) != 1 or len(trump) != 1 or trump[0]["t"] < start[0]["t"]:
            continue
        declares = [d for d in evs if d["e"] == "declare"
                    and start[0]["t"] <= d["t"] <= trump[0]["t"]]
        yield start[0], trump[0], declares


def replay(deck, rank, human, placed, tally):
    """Replay one round's deal and its ``placed`` declarations
    (``(deal position, t, seat, strength)``, sorted) into ``tally``.

    At each deal position the new card is dealt FIRST, then every episode its
    holder now qualifies for opens (or a single episode upgrades to a pair),
    and only then are that position's declarations classified -- so a seat
    that declares on the very card that made it eligible is seen.  Such a
    ZERO-WAIT declaration (no own card held silently) is ``immediate``: it is
    counted, but it is not a hazard event and adds no exposure (the
    per-own-card hazard is the rate after the first chance; the zero-wait
    probability is reported separately).  After declarations, eligibility is
    re-checked (a previous declarer can become eligible against the new one)."""
    outcome, exposure, events = tally
    current, declarer, nxt = 0, None, 0
    hands = [[] for _ in range(4)]
    open_ = {}

    def close(s, how):
        kind, own = open_.pop(s)
        key = ("human" if s in human else "bot", kind)
        outcome[key][how] += 1
        exposure[key] += own
        events[key] += how == "declared"

    def open_eligible():
        for s in range(4):
            if s == declarer:
                continue
            b = best(hands[s], rank)
            if s in open_ and open_[s][0] == "single" and b >= 2:
                close(s, "upgraded")
            if s not in open_ and b > current:
                open_[s] = ("single" if b == 1 else "pair", 0)
    for k in range(DEAL + 1):
        if k < DEAL:
            s0 = k % 4
            hands[s0].append(deck[k])
            if s0 in open_:
                kind, own = open_[s0]
                open_[s0] = (kind, own + 1)
        open_eligible()
        while nxt < len(placed) and placed[nxt][0] <= k:
            _, _, s, st = placed[nxt]
            nxt += 1
            if s in open_:
                if k >= DEAL:
                    close(s, "grace")
                elif open_[s][1] == 0:
                    close(s, "immediate")
                else:
                    close(s, "declared")
            elif s == declarer:
                # the current declarer strengthening its own declaration: no
                # episode is opened for it (it is not silent), counted apart
                outcome[("human" if s in human else "bot", "self-overcall")]["declaration"] += 1
            else:
                raise AssertionError("a declaration by a seat with no stronger combination")
            current, declarer = st, s
            for o in list(open_):
                if best(hands[o], rank) <= current:
                    close(o, "preempted")
        open_eligible()
    for s in list(open_):
        close(s, "passed")


def measure(log_dir, rate):
    tally = (collections.defaultdict(collections.Counter), collections.Counter(),
             collections.Counter())
    n_rounds = 0
    for start, trump, declares in rounds(log_dir):
        n_rounds += 1
        deck, rank = start["deck"], trump["rank"]
        human = {p["seat"] for p in start["players"] if not p["is_bot"]}
        placed = sorted((max(completed_at(deck, d["seat"], d["cards"]),
                             min(DEAL, int((d["t"] - start["t"]) / rate))),
                         d["t"], d["seat"], strength(d["cards"], rank)) for d in declares)
        replay(deck, rank, human, placed, tally)
    return (n_rounds, *tally)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--logs", default=str(Path(__file__).resolve().parents[2] / "logs"))
    parser.add_argument("--rate", type=float, default=0.2185,
                        help="seconds per dealt card (server DEAL_DELAY 0.22 s)")
    args = parser.parse_args()
    n_rounds, outcome, exposure, events = measure(args.logs, args.rate)
    print(f"rounds {n_rounds}  rate {args.rate}")
    for key in sorted(outcome):
        if key[1] == "self-overcall":
            print(f"{key[0]:5s} self-overcalls {outcome[key]['declaration']}")
            continue
        o = outcome[key]
        hazard = events[key] / exposure[key] if exposure[key] else float("nan")
        opened = sum(o.values())
        print(f"{key[0]:5s} {key[1]:6s} {dict(o)}  "
              f"zero-wait {o['immediate']}/{opened} = {o['immediate'] / opened:.3f}  "
              f"hazard after the first chance {events[key]}/{exposure[key]} = "
              f"{hazard:.4f} per own card")


if __name__ == "__main__":
    main()
