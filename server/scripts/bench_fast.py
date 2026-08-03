"""Benchmark the Cython fast path (PERF.md #2+#3 prototype).

    cd server
    uv run python scripts/bench_fast.py          # round A/B + microbench
    uv run python scripts/bench_fast.py --micro  # microbench only

Round bench: one seeded MC round (seed 7, MCBot default config), pure vs
fast, interleaved twice each (best-of to shed load noise), with a play-
history hash printed as differential evidence — pure and fast MUST match.
Microbench: 10k cache-miss decompose / find_tractor_runs calls.
"""

import argparse
import hashlib
import json
import random
import sys
from time import perf_counter

sys.path.insert(0, ".")
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.engine import combos, fast, legal  # noqa: E402
from shengji.engine.cards import TRUMP, Ordering, make_deck  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


def one_round() -> tuple[float, str]:
    t0 = perf_counter()
    game = Game(random.Random(7))
    play_round(game, [MCBot(seed=i) for i in range(4)])
    dt = perf_counter() - t0
    hist = [[p.seat, sorted(p.cards)] for t in game.round.history for p in t.plays]
    return dt, hashlib.sha256(json.dumps(hist).encode()).hexdigest()[:16]


def bench_round(reps: int = 3) -> None:
    results: dict[str, list[float]] = {"pure": [], "fast": []}
    hashes: dict[str, set] = {"pure": set(), "fast": set()}
    for _ in range(reps):
        for mode in ("pure", "fast"):
            if mode == "fast":
                assert fast.activate(), "extension not built"
            dt, h = one_round()
            if mode == "fast":
                fast.deactivate()
            results[mode].append(dt)
            hashes[mode].add(h)
    p, f = min(results["pure"]), min(results["fast"])
    print(f"MC round seed 7 (best of {reps}):  pure {p:.2f}s   fast {f:.2f}s"
          f"   speedup {p / f:.2f}x")
    print(f"  all times: pure {['%.2f' % t for t in results['pure']]}"
          f"  fast {['%.2f' % t for t in results['fast']]}")
    ok = hashes["pure"] == hashes["fast"] and len(hashes["pure"]) == 1
    print(f"  history hash pure={hashes['pure']} fast={hashes['fast']}"
          f"  -> {'IDENTICAL' if ok else 'MISMATCH (BUG!)'}")


def bench_micro(n: int = 10_000) -> None:
    rng = random.Random(3)
    deck = make_deck()
    o = Ordering("H", "7")
    groups = []
    while len(groups) < n:
        hand = rng.sample(deck, rng.randint(4, 20))
        by = {}
        for c in hand:
            by.setdefault(o.eff_suit(c), []).append(c)
        groups.extend(cards for cards in by.values() if len(cards) >= 2)
    groups = groups[:n]

    hands = [rng.sample(deck, 25) for _ in range(2000)]  # for suit_cards
    op, of = Ordering("H", "7"), Ordering("H", "7")  # fresh memos, hit path
    for cs in groups:
        combos.decompose(cs, op), combos.find_tractor_runs(cs, op, 2)
        fast.decompose(cs, of), fast.find_tractor_runs(cs, of, 2)

    fast._ctx(o)  # build tables outside the timed region
    for name, py_fn, cy_fn in (
        ("decompose miss", lambda cs: combos._decompose_uncached(cs, o),
         lambda cs: fast.decompose_uncached(cs, o)),
        ("decompose memo-hit", lambda cs: combos.decompose(cs, op),
         lambda cs: fast.decompose(cs, of)),
        ("find_tractor_runs(k=2) miss",
         lambda cs: combos._find_tractor_runs_uncached(cs, o, 2),
         lambda cs: fast.find_tractor_runs_uncached(cs, o, 2)),
        ("find_tractor_runs(k=2) memo-hit",
         lambda cs: combos.find_tractor_runs(cs, op, 2),
         lambda cs: fast.find_tractor_runs(cs, of, 2)),
    ):
        t0 = perf_counter()
        for cs in groups:
            py_fn(cs)
        tp = perf_counter() - t0
        t0 = perf_counter()
        for cs in groups:
            cy_fn(cs)
        tf = perf_counter() - t0
        print(f"{name}: {n} calls  pure {tp*1e6/n:.1f}us/call  "
              f"fast {tf*1e6/n:.1f}us/call  speedup {tp/tf:.2f}x")

    t0 = perf_counter()
    for h in hands:
        for e in ("S", "H", "D", "C", TRUMP):
            legal.suit_cards(h, e, o)
    tp = perf_counter() - t0
    t0 = perf_counter()
    for h in hands:
        for e in ("S", "H", "D", "C", TRUMP):
            fast.suit_cards(h, e, o)
    tf = perf_counter() - t0
    m = len(hands) * 5
    print(f"suit_cards (25-card hand): {m} calls  pure {tp*1e6/m:.1f}us/call"
          f"  fast {tf*1e6/m:.1f}us/call  speedup {tp/tf:.2f}x")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--micro", action="store_true", help="microbench only")
    args = ap.parse_args()
    if not fast.HAVE_FAST:
        sys.exit("extension not built: uv run python setup.py build_ext --inplace")
    bench_micro()
    if not args.micro:
        bench_round()
