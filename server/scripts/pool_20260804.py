"""Seeded Elo pool, 2026-08-04 — the first one containing an arm that beats mc.

Every pairing is mirrored and BOTH sides are seeded from the deal seed, so the
whole pool reproduces. That mattered historically: the previous pool's headline
(vleaf +32 Elo over mc) came from 120-round pairings and did not survive a
1,200-round direct duel, which is why this file also prints the raw pair
records — a Bradley-Terry fit is only as good as the pairings under it, and
gaps under ~40 Elo have twice proved unreliable here.

Entrants:
  * heuristic / smart / mc          — the ladder
  * mc-vleaf-v7w-ep02               — measured EQUAL to mc (50.4%, n=1200)
  * rl-override-v11pair             — the learned override, level with mc
  * mc-race4-v11pair                — net as ROOT PRIOR; beat mc 54.8% over
                                      2,900 rounds with a random-prune control
                                      at 49.8%
  * mc-randrace4                    — that control, in the pool so the Elo fit
                                      has to place it too

    uv run python scripts/pool_20260804.py [rounds_per_pairing] [--chunk=k/n]
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from shengji.ai.registry import make_bot        # noqa: E402
from shengji.ai.tournament import fit_elo, play_pairing  # noqa: E402

ENTRANTS = [
    "heuristic", "smart", "mc",
    "mc-vleaf-v7w-ep02",
    "rl-override-v11pair",
    "mc-race4-v11pair",
    "mc-randrace4",
]


def factory(name):
    # Forward kwargs so _seeded() actually seeds: a lambda that accepts and
    # drops seed= is the defect that made three earlier duel sets unseeded.
    return lambda **kw: make_bot(name, **kw)


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60
    pairs = [(i, j) for i in range(len(ENTRANTS))
             for j in range(i + 1, len(ENTRANTS))]
    chunk = next((a for a in sys.argv if a.startswith("--chunk")), None)
    if chunk:
        k, n = map(int, chunk.split("=")[1].split("/"))
        pairs = pairs[k::n]

    print(f"SEEDED POOL 2026-08-04: {len(ENTRANTS)} entrants, {len(pairs)} "
          f"pairings, {2*n_seeds} rounds each", flush=True)
    wins: dict[tuple[int, int], int] = {}
    t0 = time.perf_counter()
    for k, (i, j) in enumerate(pairs):
        a, b = play_pairing(factory(ENTRANTS[i]), factory(ENTRANTS[j]),
                            n_seeds, 0)
        wins[(i, j)] = a
        wins[(j, i)] = b
        print(f"PAIR {ENTRANTS[i]} {ENTRANTS[j]} {a} {b}   "
              f"[{k+1}/{len(pairs)}, {(time.perf_counter()-t0)/60:.0f}m]",
              flush=True)

    if chunk:
        print("chunked run: rerun without --chunk to fit Elo over all pairs")
        return
    elo = fit_elo(ENTRANTS, wins, anchor="heuristic")
    print("\nELO (heuristic = 1000, Bradley-Terry MLE):")
    for name in sorted(ENTRANTS, key=lambda n: -elo[n]):
        print(f"  {name:24} {elo[name]:7.0f}")
    print("\nRead gaps under ~40 Elo as unresolved: this pool's predecessor put "
          "vleaf +32 over mc, and a 1,200-round direct duel then measured 50.4%.")


if __name__ == "__main__":
    main()
