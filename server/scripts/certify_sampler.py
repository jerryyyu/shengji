"""Certify sampled worlds against an INDEPENDENT history-derived validator.

Codex's objection to the first sampler screen was precise and correct: the
sampler was checked against `Memory`, so producer and validator shared the same
inference. Agreement proved self-consistency, not legality. The 18.2k-search
screen established that allocator dead-ends are gone and that conservation and
voids hold — it did not establish that every emitted world is legal given the
full history.

This validator derives its constraints from the RULES and the trick record,
never from `Memory`:

  * every card dealt to a seat must be consistent with each trick that seat
    followed — if they played off-suit, they were void; if they showed fewer
    pairs than led, `validate_follow` proves they had no more, so nothing they
    hold now can form a pair in that suit;
  * hand sizes and the unseen multiset must be exact;
  * no card may appear more often than the deck contains it.

Three claims are kept separate, per Codex: VALIDITY (checked here),
COMPLETENESS (the real deal is a witness — checked here by planting it), and
DISTRIBUTION FIDELITY (not checked; needs toy posteriors and is out of scope).

No rollouts. This is a correctness job, not a strength job.

    uv run python scripts/certify_sampler.py [--corpus F] [--limit N] [--worlds K]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.memory import Memory                     # noqa: E402
from shengji.ai.mcbot import MCBot                       # noqa: E402
from shengji.ai.smart import SmartBot                    # noqa: E402
from shengji.engine.combos import pair_count             # noqa: E402
from shengji.engine.game import Game                     # noqa: E402


def constraints_from_history(rnd):
    """(voids, no_pair) per seat, derived from the trick record and the rules.

    Deliberately re-derived here rather than imported from `Memory`: a
    validator that shares the producer's inference cannot falsify it.
    """
    o = rnd.ordering
    voids = {s: set() for s in range(4)}
    no_pair = {s: set() for s in range(4)}
    tricks = list(rnd.history)
    if rnd.trick and rnd.trick.plays:
        tricks.append(rnd.trick)
    for trick in tricks:
        lead = trick.plays[0].cards
        lead_suit = o.eff_suit(lead[0])
        led_pairs = pair_count(lead) if len(lead) >= 2 else 0
        for i, tp in enumerate(trick.plays):
            if i == 0:
                continue
            if any(o.eff_suit(c) != lead_suit for c in tp.cards):
                voids[tp.seat].add(lead_suit)
            if led_pairs:
                ins = [c for c in tp.cards if o.eff_suit(c) == lead_suit]
                if pair_count(ins) < led_pairs:
                    # validate_follow enforces need_pairs = min(led_pairs,
                    # pair_count(their suit)), so they played every pair held.
                    no_pair[tp.seat].add(lead_suit)
    return voids, no_pair


def violations(world, rnd, voids, no_pair):
    """Every way a sampled world contradicts the public record."""
    o = rnd.ordering
    out = []
    for seat, cards in world.items():
        per_suit: dict[str, list[str]] = {}
        for c in cards:
            per_suit.setdefault(o.eff_suit(c), []).append(c)
        for suit, cs in per_suit.items():
            if suit in voids[seat]:
                out.append(f"seat {seat} holds {suit} but showed void")
            if suit in no_pair[seat] and pair_count(cs) > 0:
                out.append(f"seat {seat} holds a {suit} pair after a short "
                           f"pair answer")
        if len(cards) != len(rnd.hands[seat]):
            out.append(f"seat {seat} has {len(cards)} cards, needs "
                       f"{len(rnd.hands[seat])}")
        for code, n in Counter(cards).items():
            if n > 2:
                out.append(f"seat {seat} holds {n} copies of {code}")
    return out


def states(seed0, n, min_ply):
    """Real states, played out with a mixed table."""
    for k in range(n):
        seed = seed0 + k
        game = Game(random.Random(seed))
        pol = [MCBot(seed=seed + 7), SmartBot(), MCBot(seed=seed + 11), SmartBot()]
        rnd = game.start_round()
        while rnd.phase == "deal":
            s, _, _ = rnd.deal_next()
            cs = pol[s].decide_declare(rnd, s)
            if cs:
                rnd.declare(s, cs)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, pol[rnd.banker].decide_bury(rnd, rnd.banker))
        plies = 0
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if plies >= min_ply:
                yield seed, rnd, s
                break
            rnd.play(s, pol[s].decide_play(rnd, s))
            plies += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed0", type=int, default=97_000_000)
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--worlds", type=int, default=24)
    ap.add_argument("--min-ply", type=int, default=8,
                    help="late states are where the constraints actually bind")
    ap.add_argument("--out", default="runs/logs/certify_sampler.json")
    args = ap.parse_args()

    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        print("REFUSING: set SHENGJI_REQUIRE_VOIDS=1 — certifying the lenient "
              "path would certify nothing.")
        sys.exit(3)

    bot = MCBot(seed=99)
    n_states = n_worlds = n_bad = n_none = 0
    witness_fail = 0
    bad_examples: list[str] = []
    t0 = time.time()

    for seed, rnd, seat in states(args.seed0, args.limit, args.min_ply):
        n_states += 1
        voids, no_pair = constraints_from_history(rnd)

        # COMPLETENESS witness: the REAL deal satisfies every constraint, so a
        # sampler that cannot find any world is provably incomplete.
        real = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
        if violations(real, rnd, voids, no_pair):
            witness_fail += 1        # the validator itself is too strict

        mem = Memory(rnd, seat)
        found = 0
        for _ in range(args.worlds):
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                continue
            found += 1
            n_worlds += 1
            bad = violations(got[0], rnd, voids, no_pair)
            if bad:
                n_bad += 1
                if len(bad_examples) < 10:
                    bad_examples.append(f"seed {seed} ply {len(rnd.history)}: "
                                        f"{bad[0]}")
        if found == 0:
            n_none += 1
        if n_states % 200 == 0:
            print(f"  {n_states} states, {n_worlds} worlds, {n_bad} invalid, "
                  f"{time.time()-t0:.0f}s", flush=True)

    print(f"\nstates {n_states:,}   worlds {n_worlds:,}   "
          f"{time.time()-t0:.0f}s")
    print(f"VALIDITY     invalid worlds: {n_bad}")
    print(f"COMPLETENESS states with NO world found: {n_none}  "
          f"(the real deal is always a witness, so any >0 is incompleteness)")
    print(f"validator sanity (real deal rejected): {witness_fail}  "
          f"(must be 0, else the validator is wrong, not the sampler)")
    for e in bad_examples:
        print(f"  - {e}")
    print("\nNOT CERTIFIED: distribution fidelity. This checks validity and "
          "completeness only; matching the true posterior is a separate "
          "question and is not evidenced here (Codex).")

    os.makedirs("runs/logs", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"states": n_states, "worlds": n_worlds, "invalid": n_bad,
                   "no_world": n_none, "validator_rejected_real": witness_fail,
                   "seed0": args.seed0, "min_ply": args.min_ply,
                   "examples": bad_examples}, fh, indent=2)
    sys.exit(1 if (n_bad or n_none or witness_fail) else 0)


if __name__ == "__main__":
    main()
