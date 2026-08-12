# PERF.md — simulation speed: gaps, plan, progress

Living tracker for making the engine/search fast. Dated snapshots live
in `server/runs/perf_audit_*.md`; this file is the current state.
Update whenever an optimization ships or a measurement moves.

**Why it matters**: generation throughput bounds the whole project —
teacher data (gen-v3: ~28h fleet-wide), duels, tournaments, and MC's
live latency all sit on the same rollout loop. Rough math: 10x here =
overnight gens become 3h, and every gate duel runs in minutes.

## Current production performance — release 17

Production runs compiled `mc-s0-report-lcb`, not the older policies in the
historical table below. A matched Mini benchmark measured 0.390s per decision
for report-LCB versus 0.127s for `mc-strong`; that extra work buys the confirmed
`+0.338 +/- 0.068` signed-level gain. On Fly before the scheduler change,
searched turns could block room interaction and then pay a separate fixed 0.7s
pacing delay.

Release 17 preserves the exact N=30/R=300 decision semantics while searching an
isolated snapshot off the event loop and overlapping the pacing window. It
revalidates room/round/phase/turn/controller before commit, discarding stale
actions and cloned RNG/counters. The live ship gate kept 25 concurrent
WebSocket probes at p50 12ms/max 19ms during a real 1.53s X-ray. The first
ordinary post-fix human room produced 195 search-like turns with
search p50/p95/max `0.896/1.714/1.906s` and full-turn
`0.904/1.716/1.907s`; all 249 bot turns were offloaded and isolated.

This fixes event-loop blocking and removes an additive wait. It does not make
search free, precompute a response before the latest play, or prove concurrent
multi-room capacity. Release 16 is the runtime rollback; `mc-strong` is the
separate policy rollback. See `DEPLOY.md`.

## Historical deployment Pareto table (measured 2026-08-04)

What could actually be shipped, strength against cost. Latency is per decision
on the mini, torch-free numpy path where a net is involved; strength is the
direct mirrored evidence, not pool Elo (pool gaps under ~40 have twice proved
unreliable). **The v11-vs-mc rows are PROVISIONAL, not confirmed**: all 4,880
of those rounds ran against UNSEEDED MC factories (the seed-swallowing lambda),
so they are exploratory evidence of a tie, not a reproducible seeded result
(Codex, 2026-08-04).

| policy | p50 | p95 | strength | notes |
|---|---|---|---|---|
| `heuristic` | 0.02 ms | 0.04 ms | pool 1000 (baseline) | |
| `smart` | 0.05 ms | 0.13 ms | pool ~1093 | hand-written, no search |
| **`rl-override-v11pair`** | **0.25 ms** | **0.52 ms** | **57.7% vs smart** (n=480); **51.1% vs mc** (n=4880, CI includes 50) | SmartBot + learned override, NO search |
| `mc-vleaf-v7w-ep02` | 32 ms | 67 ms | 50.4% vs mc (n=1200) | truncated rollouts + net value leaf |
| `mc-gate-v11pair` | 0.25 ms | 30 ms | 53.3% vs MC (n=300, SCREEN only) | 55% timing was extrapolated; T2 did not earn confirmation; later T3 runner was INVALID/terminated with no result |
| `mc` (source fallback, not production) | 77 ms | 150 ms | pool ~1119 | determinized search, N_DETERMINIZATIONS=10 |

This table is retained as a historical cost comparison, not current deployment
advice. `rl-override-v11pair` was plausibly near the old MC reference at
roughly 300x lower p50, but those opponents were unseeded. Its later corrected
direct-v2 comparison selected none, and no learned policy is production-
authorized. The v7 value-leaf and gated arms likewise have no verified edge
over the live champion.

Practical reading: cheap policies remain useful difficulty/capacity choices,
but switching away from report-LCB gives up confirmed strength. Any such policy
change requires a fresh product decision, not a latency-only inference from
this 08-04 table.

---

## Measured baselines

| metric | value | conditions |
|---|---|---|
| production decision | report-LCB 0.390s / `mc-strong` 0.127s | matched Mini benchmark; policy work only |
| MC round, one core | pure 5.74s / compiled 1.68s | wide N=10 ballot; **3.42x**, byte-identical seeded histories |
| generation fleet | 0.335 -> 1.212 rounds/s | same workload before/after compiled activation; **3.62x** |
| v11 numpy inference | p50 0.25ms / p95 0.52ms | torch-free path; first call slower |
| release-17 live search | p50/p95/max 0.896/1.714/1.906s | first ordinary post-fix room, 195 search-like turns |

Reproduce the engine baseline from `server/runs/perf_audit_20260802.md` and
compare only under like-for-like load.

## Shipped

| date | change | measured | notes |
|---|---|---|---|
| 07-31 | Ordering lookup tables | +11% single-core | killed then-#1 hotspot |
| 08-02 | decompose memo (cache on Ordering, per-round lifetime) | **1.26x** | pure function; differential-tested byte-identical |
| 08-02 | trusted-rollout fast path (skip follow re-validation in MC clones only) | ~1% solo (memo cheapened validation) | validate_lead always runs (throw penalties) |
| 08-03 | compiled phases 0-2: caller-order caches, rules kernels and policy leaves | **3.42x** round (5.74 -> 1.68s) | 10k+ randomized parity cases, six byte-identical seeded histories; opt-in `SHENGJI_FAST=1` |
| 08-07 | release-17 speculative scheduler + off-loop X-ray | live searched-turn p95 `1.714s`; WebSockets responsive during search | Decision semantics unchanged; overlaps pacing, validates before commit, discards stale snapshot state. This is responsiveness isolation, not rollout-throughput speedup. |

## Gaps (ranked by ROI)

| # | gap | fix | est. win | status |
|---|---|---|---|---|
| 1 | Memory rebuilt per decision (full history rescan, O(tricks²)/round) | incremental Memory carried through rollouts | 1.1-1.2x | open |
| 2 | Python policy hot loop after compiled phases 0-2 | port `_lead`, `_current_winner` and `_cheapest_winning` one phase at a time | toward ~5x round-level | open; pure/compiled history and bot-timing gates required |
| 3 | string cards and list hands still cross every compiled call | convert once per rollout; compile `Round.play`/trick resolution | remaining path toward 10-20x | open; keep strings at public boundaries |
| 4 | Round/Trick clone churn per rollout (3.8k clones/round) | reusable scratch state | ~1.1x | open |
| 5 | multi-room capacity is not measured | concurrent-room latency/load gate | product reliability | open |
| 6 | feature flags mix exact `"1"` checks with string truthiness | version and centralize boolean parsing | evidence correctness | open; until then unset flags for false—`=0` is unsafe |
| 7 | rollouts always play to round end | early-terminate decided brackets | speculative and potentially biased | parked behind a strength/correctness gate |
| 8 | single-machine ceiling | rented 32-core burst (~$5/generation) | ~4x fleet, zero code | available when critical path is compute-bound |
| 9 | Rust/PyO3 full engine core | 30-100x; wasm client bonus | large | parked; requires a 10k-seed two-engine parity harness |

## Plan (sequencing)

1. Port `_lead`, `_current_winner` and `_cheapest_winning` in bounded phases;
   require byte-identical histories plus wall-clock bot timing each time.
2. Move int-card conversion to the rollout boundary, then compile
   `Round.play`/trick resolution under the same differential gate.
3. Add a concurrent-room production capacity test; event-loop isolation alone
   is not a capacity proof.
4. Measure incremental Memory and clone reuse after the next profile rather
   than assuming the old percentages still hold.
5. Burst to more cores when the strength critical path is compute-bound.

## Fast-path evidence and boundaries

The August 3 gate was clean: 2,870 generation decisions and 16,550 teacher
floats were bit-identical, duel records matched per game, the 900-round tier
sweep was clean, and 20k+ edge comparisons plus 69k interleavings passed.
`tests/test_fast_parity.py` and golden histories retain the executable gate.
Activation lives inside spawned generation workers and `META.json` records the
engine mode.

Compiled drop-ins currently require list inputs; strings remain the public
card representation; cache populations can differ even when behavior cannot.
Earlier value-leaf profiling also showed candidate enumeration/encoding—not
the small network—as the dominant cost, so adding a GPU is not the current
bottleneck. Any shortcut that changes rollout length or action semantics is a
new strength experiment, not a performance-only patch.

## Rules

- Every optimization ships with a differential test (identical seeded
  histories, optimized vs reference path) — correctness of generated
  data outranks speed, always.
- Measure on like-for-like machine load; profile numbers (cProfile)
  overstate hotspots ~2x — trust wall-clock A/Bs for claims.
- Running workers load code at spawn: optimizations reach jobs at
  their NEXT launch, never mid-run.
- Parse environment flags through one versioned helper. Until that migration,
  unset a flag to mean false; several paths currently treat the string `"0"`
  as true.
