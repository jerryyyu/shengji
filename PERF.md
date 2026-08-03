# PERF.md — simulation speed: gaps, plan, progress

Living tracker for making the engine/search fast. Dated snapshots live
in `server/runs/perf_audit_*.md`; this file is the current state.
Update whenever an optimization ships or a measurement moves.

**Why it matters**: generation throughput bounds the whole project —
teacher data (gen-v3: ~28h fleet-wide), duels, tournaments, and MC's
live latency all sit on the same rollout loop. Rough math: 10x here =
overnight gens become 3h, and every gate duel runs in minutes.

## Current measured baselines (2026-08-02)

| metric | value | conditions |
|---|---|---|
| MC round, single core | ~5.9s | wide ballots, N=10, post-memo, loaded machine |
| generation rate | 0.03-0.04 r/s/worker | N=30, wide ballots (gen-v3 config) |
| fleet aggregate | ~0.55 r/s (15 workers) | mini 8 + Air 7 |
| net inference | ~2ms/decision | v1 ballot, MPS/CPU |
| benchmark cmd | one seeded MC round, see `server/runs/perf_audit_20260802.md` | compare like-for-like load only |

## Shipped

| date | change | measured | notes |
|---|---|---|---|
| 07-31 | Ordering lookup tables | +11% single-core | killed then-#1 hotspot |
| 08-02 | decompose memo (cache on Ordering, per-round lifetime) | **1.26x** | pure function; differential-tested byte-identical |
| 08-02 | trusted-rollout fast path (skip follow re-validation in MC clones only) | ~1% solo (memo cheapened validation) | validate_lead always runs (throw penalties) |

## Gaps (ranked by ROI)

| # | gap | fix | est. win | status |
|---|---|---|---|---|
| 1 | Memory rebuilt per decision (full history rescan, O(tricks²)/round) | incremental Memory carried through rollouts | 1.1-1.2x | open |
| 2 | str card codes ("H10") → dict-hash on every eff_suit/level/beats; list-of-str hands | u8 int cards + array hands inside engine primitives | enabler for #3 | prototype (08-02): Cython leaf port of decompose/find_tractor_runs/suit_cards with str at all boundaries — primitives 2-6x, round only **1.11x** (goldens byte-identical). Lesson: leaf porting is boundary-conversion-bound; full win needs int-native hands through the rollout loop. See `server/shengji/engine/_fast.pyx` + `fast.py` |
| 3 | interpreted Python hot loop (per round: 181k heuristic decisions, 845k decompose, 282k beats, 278k validate_follow) | Cython over combos/legal/heuristic AFTER #2 | **10-20x combined** | open — toolchain + parity gate proven by the #2 prototype ("the 10-30x generation" backlog item) |
| 4 | Round/Trick clone churn per rollout (3.8k clones/round) | reusable scratch state | ~1.1x | open |
| 5 | rollouts always play to round end | early-terminate decided brackets | speculative — BIASES values, gate carefully | parked |
| 6 | single-machine ceiling | rented 32-core burst (~$5/gen) | 4x fleet, zero code | available anytime |
| 7 | Rust/PyO3 full engine core | 30-100x; wasm client bonus | parked until AWAC-scale; two-implementation drift risk ⇒ 10k-seed parity harness mandatory | parked |

## Plan (sequencing)

1. After the v8 cycle: #1 incremental Memory (day, pure Python, easy
   differential test).
2. Then #2+#3 together — int-encoding + Cython pass (the big one,
   ~days). Non-negotiable gate: byte-identical seeded play histories
   vs the Python engine before ANY generated data is trusted
   (Elo-798 lesson applied to rules).
3. #6 rented burst whenever a gen run blocks the roadmap by >1 day.
4. #7 Rust only if AWAC-scale self-play demands it.

## Rules

- Every optimization ships with a differential test (identical seeded
  histories, optimized vs reference path) — correctness of generated
  data outranks speed, always.
- Measure on like-for-like machine load; profile numbers (cProfile)
  overstate hotspots ~2x — trust wall-clock A/Bs for claims.
- Running workers load code at spawn: optimizations reach jobs at
  their NEXT launch, never mid-run.
