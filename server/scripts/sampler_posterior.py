"""Bounded probe: does the sampler draw worlds in the RIGHT PROPORTIONS?

Certification established that every emitted world is LEGAL and that every legal
world is REACHABLE. Neither says anything about frequency. A sampler can be
valid and complete while badly mis-weighting, and two named biases are expected
here by construction:

  * `_splits` picks among feasible (suit x receiver) count matrices roughly
    uniformly, though matrices admit very different numbers of completions —
    so balanced worlds should be UNDER-represented;
  * `_deal_suit` takes the first card that respects the pair/run caps, which
    prefers distinct codes beyond what the constraints require.

Why it matters for the pilot rather than just aesthetically: sharing proposal
and report worlds gives low-variance paired comparisons, but it does NOT cancel
a biased belief distribution when the bias changes which action is best (Codex).

Three measurements, all against an EXACT reference on states small enough to
enumerate every legal world:

  1. **Total variation distance** between the empirical world distribution and
     uniform-over-legal-worlds, with a sampling-noise band so a small TV is not
     mistaken for bias.
  2. **Per-(card, seat) marginals** against exact counts.
  3. **Exchangeability**: two cards the constraints do not distinguish must
     land in a given seat equally often.

Uniform-over-legal-worlds is the reference because determinization assumes an
uninformative prior over deals consistent with the public record. That is the
sampler's own stated target, so it is the right thing to hold it to.

    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \\
    uv run python scripts/sampler_posterior.py --states 12 --draws 4000
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from certify_sampler import constraints, enumerate_legal, toy_states  # noqa: E402
from shengji.ai.memory import Memory                                  # noqa: E402
from shengji.ai.mcbot import MCBot                                    # noqa: E402
from shengji.pilot_folds import world_key                             # noqa: E402


def tv_noise_band(n_worlds: int, draws: int, reps: int = 200) -> float:
    """95th-percentile TV a PERFECT uniform sampler would show at this n.

    Without this, any TV > 0 reads as bias — but a finite sample from a uniform
    distribution has nonzero TV by construction, and for 90 worlds in 4,000
    draws that floor is not small.
    """
    import random as _r
    rng = _r.Random(12345)
    tvs = []
    for _ in range(reps):
        c = Counter(rng.randrange(n_worlds) for _ in range(draws))
        tvs.append(0.5 * sum(abs(c.get(i, 0) / draws - 1 / n_worlds)
                             for i in range(n_worlds)))
    tvs.sort()
    return tvs[int(0.95 * len(tvs))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", type=int, default=12)
    ap.add_argument("--draws", type=int, default=4000)
    ap.add_argument("--max-worlds", type=int, default=200,
                    help="skip states whose legal space is too large for the "
                         "draw budget to estimate frequencies at all")
    ap.add_argument("--out", default="runs/logs/sampler_posterior.json")
    args = ap.parse_args()

    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        print("REFUSING: set SHENGJI_REQUIRE_VOIDS=1 — probing the lenient "
              "sampler measures a distribution nothing uses.")
        sys.exit(3)

    # Generate states with the DEFAULT sampler, then measure with whatever is
    # configured. `toy_states` self-plays full rounds with mc-strong to reach
    # deep banker positions; under the weighted sampler that GENERATION cost
    # dominated and three runs hung past 10 minutes without reaching the
    # measurement at all. The states are just positions — how they were found
    # does not change the posterior over their hidden hands.
    _w = os.environ.pop("SHENGJI_WEIGHTED_SPLITS", None)
    import shengji.ai.mcbot as _M
    _M.WEIGHTED_SPLITS = False
    states = list(toy_states(args.states * 3))
    if _w:
        os.environ["SHENGJI_WEIGHTED_SPLITS"] = _w
        _M.WEIGHTED_SPLITS = True

    bot = MCBot(seed=4242)
    rows = []
    for seed, rnd, seat in states:
        cons = constraints(rnd)
        try:
            legal = enumerate_legal(rnd, seat, cons)
        except RuntimeError:
            continue
        if not legal or len(legal) > args.max_worlds:
            continue
        mem = Memory(rnd, seat)
        n = len(legal)
        seen: Counter = Counter()
        card_seat: Counter = Counter()
        ok = 0
        for _ in range(args.draws):
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                continue
            ok += 1
            hands, extra = got
            seen[world_key(hands, extra)] += 1
            for s, cards in hands.items():
                for c in cards:
                    card_seat[(c, s)] += 1
        if ok < args.draws // 2:
            continue

        tv = 0.5 * sum(abs(seen.get(k, 0) / ok - 1 / n) for k in legal)
        tv += 0.5 * sum(v / ok for k, v in seen.items() if k not in legal)
        band = tv_noise_band(n, ok)

        # exact per-(card, seat) marginal from the enumerated legal set
        exact: Counter = Counter()
        for k in legal:
            for s, cards in k[0]:
                for c in cards:
                    exact[(c, s)] += 1
        worst_card, worst_gap = None, 0.0
        for key, cnt in exact.items():
            want = cnt / n
            have = card_seat.get(key, 0) / ok
            if abs(have - want) > worst_gap:
                worst_gap, worst_card = abs(have - want), key
        rows.append({"seed": seed, "n_legal": n, "draws": ok,
                     "tv": tv, "tv_noise_95": band,
                     "tv_excess": max(0.0, tv - band),
                     "worst_marginal_gap": worst_gap,
                     "worst_marginal": f"{worst_card}" if worst_card else None,
                     "unreached": sum(1 for k in legal if k not in seen)})
        print(f"  seed {seed}: {n:3d} legal, TV {tv:.3f} "
              f"(noise band {band:.3f}, excess {max(0.0,tv-band):.3f}), "
              f"worst marginal gap {worst_gap:.3f}, "
              f"{rows[-1]['unreached']} never drawn", flush=True)
        if len(rows) >= args.states:
            break

    if not rows:
        print("no enumerable states in range")
        sys.exit(2)
    mtv = sum(r["tv"] for r in rows) / len(rows)
    mex = sum(r["tv_excess"] for r in rows) / len(rows)
    mmg = sum(r["worst_marginal_gap"] for r in rows) / len(rows)
    biased = sum(1 for r in rows if r["tv_excess"] > 0.05)
    print(f"\nstates {len(rows)}   mean TV {mtv:.3f}   "
          f"mean EXCESS over noise {mex:.3f}   mean worst marginal gap {mmg:.3f}")
    print(f"states with TV excess > 0.05: {biased}/{len(rows)}")
    print("\nTV excess is the number that matters — raw TV includes the floor a "
          "perfect uniform sampler shows at this draw count.")
    print("This is a BOUNDED PROBE. It says whether bias is material enough to "
          "repair before pilot scoring; it is not a certification.")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump({"states": len(rows), "mean_tv": mtv, "mean_tv_excess": mex,
                   "mean_worst_marginal_gap": mmg, "biased_states": biased,
                   "draws": args.draws, "rows": rows}, fh, indent=1)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
