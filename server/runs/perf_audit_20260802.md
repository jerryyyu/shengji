# Simulation performance audit — 2026-08-02 (late night)

## How MC simulation works (per decision)
Ballot (≤14 lead / ≤12 follow candidates) → sample N=30 hidden-hand
worlds → for each (world × candidate): shallow-copy Round, install
sampled hands, play candidate, HeuristicBot plays ALL seats to round
end (~80-100 decisions), score attacker points → average per candidate
→ margin rule vs heuristic incumbent. Worlds are shared across
candidates (good); Ordering lookup tables already killed the old #1
hotspot (good).

## Profile (one MC round, cProfile, pre-optimization)
~25s profiled: _rollout 24.9s cum; inside: 181k heuristic decide_play
(16.7s), 845k decompose (4.6s), 282k beats (6.0s), 278k
validate_follow (5.9s). All str card-codes + dict ops.

## Implemented tonight (differential-tested: byte-identical play
histories on fixed seeds, fast vs forced-validation paths)
1. **decompose memo** — cache on the Ordering instance (per-round
   lifetime, auto-invalidating; pure function). Measured **1.26x** per
   round standalone.
2. **Trusted-rollout fast path** — skip validate_follow re-validation
   ONLY inside MC rollout clones (`Round._trusted_rollout`);
   validate_lead always runs (throw penalties change outcomes).
   Measured small solo (~1%) once memo landed (memo already cheapened
   validation); kept: free and correct.
Net effect ~1.3x; running gen workers use OLD code (loaded at start) —
benefits apply to every future launch.

## Remaining gaps (est. win, in order)
| gap | fix | est |
|---|---|---|
| Memory rebuilt per decision (O(tricks²)/round) | incremental memory through rollouts | 1.1-1.2x |
| str card codes everywhere | u8 ints + array hands in engine primitives | enabler |
| interpreted hot loop | Cython over combos/legal/heuristic AFTER int-encoding | **10-20x combined** |
| Round/Trick clone churn per rollout | reusable scratch state | 1.1x |
| rollouts always run to round end | early-terminate on decided brackets (BIASES values — gate carefully) | speculative |
| Rust/PyO3 full core | only if AWAC needs 100x; wasm client bonus; two-implementation drift risk ⇒ 10k-seed parity harness mandatory | 30-100x |

Sequencing: int-encode + Cython is the "10-30x generation" backlog
item (BACKLOG.md); do after the v8 cycle, with differential tests as
tonight (identical seeded histories before any generated data is
trusted).
