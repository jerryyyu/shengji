"""Independent certification of the world sampler, against the BACKLOG P0 gate.

The first version of this script met about three of the gate's clauses while
reading like it met all of them. What it actually did was replay its own fresh
seeds, check voids and pair caps, and call "a legal world was available within
24 retries" completeness. The gate says, in as many words, *do not call
availability across 24 retries completeness*.

This version implements the gate:

  * **Reservoir states, not self-generated ones.** Replays rows from the
    original 20,845-state corpus and the 12,000-state late supplement, so the
    state distribution is the one we actually reason about rather than one this
    script invented.
  * **Full conservation.** The observer's hand, every sampled hand, the
    returned kitty and all played cards must together reconstitute the deck
    exactly, with no code exceeding its two physical copies.
  * **Declaration pins.** Cards the declarer showed and has not played must be
    in the declarer's sampled hand — the constraint whose interaction with the
    pair cap produced the only defect found so far.
  * **Suit voids and pair obligations**, re-derived from the trick record and
    `validate_follow`, never from `Memory`.
  * **Tractor obligations.** A seat that answered a pure tractor lead with a
    shorter pair run cannot still hold a run that long in that suit.
  * **Every failed draw counted**, not only states where all draws failed.
  * **Immutable provenance**: git SHA, tree state, and digests of this script,
    the sampler module, the corpus and the split.

Completeness is proved two ways, neither of which is "a world turned up":

  1. **Toy enumeration.** On states small enough to enumerate every legal
     assignment by brute force, the sampler must be able to produce each one.
  2. **Planted witness.** The real deal is legal by construction; the sampler
     must be able to REACH it, checked by seeding the draw and searching, not
     by observing that some world appeared.

Distribution fidelity is a separate later claim and is not evidenced here.

    uv run python scripts/certify_sampler.py --reservoir original|late|both
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.mcbot import MCBot                       # noqa: E402
from shengji.ai.memory import Memory                     # noqa: E402
from shengji.ai.smart import SmartBot                    # noqa: E402
from shengji.engine.cards import make_deck               # noqa: E402
from shengji.engine.combos import decompose, pair_count  # noqa: E402
from shengji.engine.game import Game                     # noqa: E402

RESERVOIRS = {"original": "rl_data/highn_corpus_all.jsonl",
              "late": "rl_data/highn_late_air.jsonl"}


def digest(path):
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ------------------------------------------------------- rule-derived facts

def constraints(rnd):
    """(voids, no_pair, max_run, pinned) derived from the record and the rules.

    Re-derived here rather than imported from `Memory`: a validator sharing the
    producer's inference cannot falsify it.
    """
    o = rnd.ordering
    voids = {s: set() for s in range(4)}
    no_pair = {s: set() for s in range(4)}
    max_run = {s: {} for s in range(4)}
    tricks = list(rnd.history)
    if rnd.trick and rnd.trick.plays:
        tricks.append(rnd.trick)
    for trick in tricks:
        lead = trick.plays[0].cards
        lead_suit = o.eff_suit(lead[0])
        ldec = decompose(list(lead), o)
        led_pairs = pair_count(lead) if len(lead) >= 2 else 0
        pure_tractor = (len(ldec.components) == 1
                        and ldec.components[0].pair_len >= 2)
        for i, tp in enumerate(trick.plays):
            if i == 0:
                continue
            ins = [c for c in tp.cards if o.eff_suit(c) == lead_suit]
            if any(o.eff_suit(c) != lead_suit for c in tp.cards):
                voids[tp.seat].add(lead_suit)
            if led_pairs and pair_count(ins) < led_pairs:
                # validate_follow forces need_pairs = min(led, held), so every
                # pair they had was played.
                no_pair[tp.seat].add(lead_suit)
            if pure_tractor and ins:
                k = ldec.components[0].pair_len
                shown = decompose(ins, o).max_pair_run()
                if shown < k:
                    # Could not match a k-run, so no k-run remains either.
                    prev = max_run[tp.seat].get(lead_suit)
                    max_run[tp.seat][lead_suit] = (
                        k - 1 if prev is None else min(prev, k - 1))
    # Declared-and-unplayed cards belong to the declarer.
    pinned: dict[str, tuple[int, int]] = {}
    decl = rnd.declaration
    if decl and decl.get("seat") is not None:
        played_by = Counter()
        for trick in tricks:
            for tp in trick.plays:
                if tp.seat == decl["seat"]:
                    played_by.update(tp.cards)
        for code, n in Counter(decl["cards"]).items():
            left = n - played_by[code]
            if left > 0:
                pinned[code] = (decl["seat"], left)
    return voids, no_pair, max_run, pinned


def check_world(world, extra, rnd, seat, cons):
    """Every way a sampled world contradicts the public record. Exhaustive."""
    voids, no_pair, max_run, pinned = cons
    o = rnd.ordering
    out = []

    # ---- conservation: observer + sampled hands + kitty + played == deck ----
    total = Counter(rnd.hands[seat])
    for cards in world.values():
        total.update(cards)
    total.update(extra)
    tricks = list(rnd.history)
    if rnd.trick and rnd.trick.plays:
        tricks.append(rnd.trick)
    for trick in tricks:
        for tp in trick.plays:
            total.update(tp.cards)
    # NOT rnd.buried on top: `extra` already carries it. For the banker the
    # sampler returns the real burial; for anyone else it returns a sampled
    # kitty standing in for it. Adding it again double-counted eight cards,
    # and truncating the diff to four entries hid that it was exactly eight.
    deck = Counter(make_deck())
    if total != deck:
        missing = {c: deck[c] - total.get(c, 0)
                   for c in deck if deck[c] != total.get(c, 0)}
        out.append(f"conservation broken on {len(missing)} codes, "
                   f"net {sum(missing.values()):+d}: "
                   f"{dict(list(missing.items())[:4])}")
    for code, n in total.items():
        if n > 2:
            out.append(f"{code} appears {n} times (deck holds 2)")

    for s, cards in world.items():
        if len(cards) != len(rnd.hands[s]):
            out.append(f"seat {s} has {len(cards)} cards, needs "
                       f"{len(rnd.hands[s])}")
        per_suit: dict[str, list[str]] = {}
        for c in cards:
            per_suit.setdefault(o.eff_suit(c), []).append(c)
        for suit, cs in per_suit.items():
            if suit in voids[s]:
                out.append(f"seat {s} holds {suit} but showed void")
            if suit in no_pair[s] and pair_count(cs) > 0:
                out.append(f"seat {s} holds a {suit} pair after a short "
                           f"pair answer")
            cap = max_run[s].get(suit)
            if cap is not None and decompose(cs, o).max_pair_run() > cap:
                out.append(f"seat {s} holds a {suit} run longer than {cap} "
                           f"after failing a tractor obligation")
    # ---- declaration pins ----
    for code, (dseat, n) in pinned.items():
        if dseat == seat:
            continue
        have = Counter(world.get(dseat, []))[code]
        if have < n:
            out.append(f"declarer {dseat} shown {n}x{code} but sampled {have}")
    return out


# ------------------------------------------------------------ completeness

def enumerate_legal(rnd, seat, cons, cap=60000):
    """Every legal assignment of the unseen pool, by multiset combination.

    The first version permuted the pool, which is 479 million orderings for
    twelve cards and simply never returned — so `enumerate_legal` silently
    reported "too large" on every state and toy completeness read 0/0 while
    looking implemented. Choosing each hand as a COMBINATION of the remaining
    indices is the same set of worlds at a tractable size: C(12,4)*C(8,4) is
    34,650, not 12!.

    Returns None when the space exceeds `cap`, so completeness is claimed only
    where it was genuinely exhausted.
    """
    mem = Memory(rnd, seat)
    pool = sorted(mem.unseen.elements())
    others = [s for s in range(4) if s != seat]
    sizes = [len(rnd.hands[s]) for s in others]
    kitty_slots = 0 if seat == rnd.banker else len(rnd.buried)
    if sum(sizes) + kitty_slots != len(pool) or len(pool) > 14:
        return None

    legal: set = set()
    seen_shapes: set = set()

    def rec(idx_left, i, world):
        if len(legal) > cap or len(seen_shapes) > 20 * cap:
            raise StopIteration
        if i == len(others):
            # Match what the SAMPLER returns as `extra`: the banker's own
            # burial (which is not in its unseen pool), or the sampled kitty
            # for anyone else. Building it from leftover pool gave the banker
            # an empty kitty, so conservation rejected every world and the
            # enumerator reported "too large" for a space of ninety.
            extra = (sorted(rnd.buried) if seat == rnd.banker
                     else sorted(pool[j] for j in idx_left))
            # Seat-KEYED. Sorting the hands loses which seat holds which,
            # and seats are not interchangeable — they carry different voids
            # and caps. That collapsed 90 assignments to 9 shapes and let an
            # illegal assignment mask the legal one behind the same key.
            key = (tuple(sorted((k, tuple(sorted(v)))
                                for k, v in world.items())),
                   tuple(extra))
            if key in seen_shapes:
                return
            seen_shapes.add(key)
            if not check_world(world, extra, rnd, seat, cons):
                legal.add(key)
            return
        for combo in itertools.combinations(sorted(idx_left), sizes[i]):
            world[others[i]] = [pool[j] for j in combo]
            rec(idx_left - set(combo), i + 1, world)
        world.pop(others[i], None)

    try:
        rec(set(range(len(pool))), 0, {})
    except StopIteration:
        return None                 # genuinely too large to exhaust
    if not legal:
        # Distinct from "too large": zero legal worlds means the validator
        # rejects even the real deal, which is a bug in the validator.
        raise RuntimeError(
            f"enumerated {len(seen_shapes)} assignments and found NONE legal; "
            f"the real deal is legal by construction, so the validator is wrong")
    return legal


def toy_states(n_want, seed0=880000, max_pool=7):
    """Deep BANKER states, where the unseen pool is small enough to enumerate.

    The banker knows its own burial, so its unseen pool is just the three other
    hands — roughly twelve cards once each holds four. Non-banker seats always
    carry the eight-card kitty on top, which puts them out of reach. Corpus rows
    stop far too early to contain any of these, so they are constructed here;
    that is what "exhaustively enumerable toy states" means, and it is a
    completeness test, not a distribution claim.
    """
    made = 0
    seed = seed0
    while made < n_want and seed < seed0 + 4000:
        seed += 1
        game = Game(random.Random(seed))
        rnd = game.start_round()
        pol = [MCBot(seed=seed + 7), SmartBot(), MCBot(seed=seed + 11), SmartBot()]
        try:
            while rnd.phase == "deal":
                s, _, _ = rnd.deal_next()
                cs = pol[s].decide_declare(rnd, s)
                if cs:
                    rnd.declare(s, cs)
            rnd.finalize_declare()
            rnd.bury(rnd.banker, pol[rnd.banker].decide_bury(rnd, rnd.banker))
            while rnd.phase == "play":
                s = rnd.turn
                if s is None:
                    break
                if s == rnd.banker:
                    pool = sum(len(rnd.hands[x]) for x in range(4) if x != s)
                    if pool <= max_pool:
                        made += 1
                        yield seed, rnd, s
                        break
                rnd.play(s, pol[s].decide_play(rnd, s))
        except Exception:
            continue


def reachable(bot, rnd, seat, mem, targets, draws):
    """Which enumerated worlds the sampler actually PRODUCES.

    This is the completeness test the gate asks for. "A world was available
    within 24 retries" says nothing about whether the sampler can reach any
    particular legal world, which is what completeness means.
    """
    hit = set()
    for _ in range(draws):
        got = bot._sample_hands(rnd, seat, mem)
        if got is None:
            continue
        hands, extra = got
        key = (tuple(sorted((k, tuple(sorted(v)))
                            for k, v in hands.items())),
               tuple(sorted(extra)))
        if key in targets:
            hit.add(key)
    return hit


# ------------------------------------------------------------- state source

def reservoir_states(paths, limit, min_ply):
    """Replay rows from the CORPUS, so the distribution is the real one."""
    n = 0
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            for line in fh:
                if n >= limit:
                    return
                row = json.loads(line)
                if row["ply"] < min_ply:
                    continue
                seed = row["seed"]
                game = Game(random.Random(seed))
                rnd = game.start_round()
                pol = [MCBot(seed=seed + 7), SmartBot(),
                       MCBot(seed=seed + 11), SmartBot()]
                try:
                    while rnd.phase == "deal":
                        s, _, _ = rnd.deal_next()
                        cs = pol[s].decide_declare(rnd, s)
                        if cs:
                            rnd.declare(s, cs)
                    for s in range(4):
                        cs = pol[s].decide_declare(rnd, s, final=True)
                        if cs:
                            rnd.declare(s, cs)
                    rnd.finalize_declare()
                    if list(rnd.deck) != list(row["setup"]["deck"]):
                        continue
                    rnd.bury(rnd.banker, list(row["setup"]["buried"]))
                    for p in row["plays"]:
                        rnd.play(p["seat"], list(p["cards"]))
                except Exception:
                    continue
                if rnd.turn != row["seat"] or rnd.phase != "play":
                    continue
                n += 1
                yield path, seed, rnd, row["seat"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reservoir", default="both",
                    choices=["original", "late", "both"])
    ap.add_argument("--limit", type=int, default=800)
    ap.add_argument("--worlds", type=int, default=24)
    ap.add_argument("--min-ply", type=int, default=0)
    ap.add_argument("--toy-draws", type=int, default=4000)
    ap.add_argument("--toy-states", type=int, default=40,
                    help="constructed deep-banker states, exhaustively enumerated")
    ap.add_argument("--out", default="runs/logs/certify_sampler.json")
    args = ap.parse_args()

    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        print("REFUSING: set SHENGJI_REQUIRE_VOIDS=1 — certifying the lenient "
              "path would certify nothing.")
        sys.exit(3)

    paths = ([RESERVOIRS[args.reservoir]] if args.reservoir != "both"
             else list(RESERVOIRS.values()))
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    prov = {
        "git": sha, "tree_dirty": bool(dirty),
        "script_sha256_16": digest(os.path.abspath(__file__)),
        "sampler_sha256_16": digest("shengji/ai/mcbot.py"),
        "memory_sha256_16": digest("shengji/ai/memory.py"),
        "reservoirs": {p: digest(p) for p in paths},
        "split_sha256_16": digest("rl_data/corpus_split.v1.json"),
        "require_voids": True, "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    print(json.dumps(prov, indent=2), flush=True)

    bot = MCBot(seed=99)
    n_states = requested = accepted = rejected = n_bad = 0
    toy_states_n = toy_complete = toy_worlds_missed = 0
    witness_states = witness_hit = witness_missing = 0
    bad_examples: list[str] = []
    t0 = time.time()

    for path, seed, rnd, seat in reservoir_states(paths, args.limit,
                                                  args.min_ply):
        n_states += 1
        cons = constraints(rnd)
        mem = Memory(rnd, seat)

        # ---- validity, counting EVERY draw ----
        for _ in range(args.worlds):
            requested += 1
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                rejected += 1
                continue
            accepted += 1
            bad = check_world(got[0], got[1], rnd, seat, cons)
            if bad:
                n_bad += 1
                if len(bad_examples) < 12:
                    bad_examples.append(
                        f"{os.path.basename(path)} seed {seed} "
                        f"ply {len(rnd.history)}: {bad[0]}")

        if n_states % 100 == 0:
            print(f"  {n_states} states, {accepted} worlds, {n_bad} invalid, "
                  f"{time.time()-t0:.0f}s", flush=True)

    # ---- COMPLETENESS: constructed toy states, exhaustively enumerated ----
    print("\n  toy completeness phase...", flush=True)
    for seed, rnd, seat in toy_states(args.toy_states):
        cons_t = constraints(rnd)
        try:
            legal = enumerate_legal(rnd, seat, cons_t)
        except RuntimeError as exc:
            bad_examples.append(f"toy seed {seed}: {exc}")
            continue
        if not legal:
            continue
        toy_states_n += 1
        mem_t = Memory(rnd, seat)
        hit = reachable(bot, rnd, seat, mem_t, legal, 60 * len(legal) + 600)
        if hit == legal:
            toy_complete += 1
        else:
            toy_worlds_missed += len(legal - hit)
            if len(bad_examples) < 12:
                bad_examples.append(
                    f"toy seed {seed}: reached {len(hit)}/{len(legal)} "
                    f"enumerated legal worlds")
        # the real deal is one of the enumerated worlds; it must be reachable
        real = {x: sorted(rnd.hands[x]) for x in range(4) if x != seat}
        rkey = (tuple(sorted((k, tuple(sorted(v))) for k, v in real.items())),
                tuple(sorted(rnd.buried) if seat == rnd.banker else ()))
        if rkey in legal:
            witness_states += 1
            if rkey in hit:
                witness_hit += 1
        else:
            witness_missing += 1

    print(f"\nstates {n_states:,}   requested {requested:,}   "
          f"accepted {accepted:,}   rejected {rejected:,}   "
          f"{time.time()-t0:.0f}s")
    print(f"VALIDITY      invalid worlds: {n_bad}")
    print(f"COMPLETENESS  toy states fully reachable: {toy_complete}/{toy_states_n}"
          f"   enumerated worlds never produced: {toy_worlds_missed}")
    print(f"WITNESS       real deal reached in {witness_hit}/{witness_states} "
          f"enumerated toy states")
    if witness_missing:
        print(f"  !! {witness_missing} states where the REAL deal was not in "
              f"the enumerated legal set — the enumerator is wrong")
    for e in bad_examples:
        print(f"  - {e}")
    print("\nNOT CERTIFIED: distribution fidelity. Legality and reachability "
          "say nothing about whether worlds are produced in the right "
          "PROPORTIONS; that needs exact toy posteriors (Codex).")

    os.makedirs("runs/logs", exist_ok=True)
    result = {**prov, "states": n_states, "requested": requested,
              "accepted": accepted, "rejected": rejected, "invalid": n_bad,
              "toy_states": toy_states_n, "toy_complete": toy_complete,
              "toy_worlds_missed": toy_worlds_missed,
              "witness_states": witness_states, "witness_hit": witness_hit,
              "witness_missing": witness_missing,
              "examples": bad_examples,
              "certified": bool(n_states and not n_bad and toy_states_n
                                and toy_complete == toy_states_n
                                and not witness_missing
                                and witness_hit == witness_states)}
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"\nwrote {args.out}")
    sys.exit(0 if result["certified"] else 1)


if __name__ == "__main__":
    main()
