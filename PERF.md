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
| MC round, single core, SHENGJI_FAST=1 | **~1.7s (3.42x)** | same load, seed-7 best-of-3 interleaved (08-03); opt-in only, histories byte-identical (seeds 3/7/11/23/42/99 checked) |
| generation rate | 0.03-0.04 r/s/worker | N=30, wide ballots (gen-v3 config) |
| fleet aggregate | ~0.55 r/s (15 workers) | mini 8 + Air 7 |
| net inference | ~2ms/decision | v1 ballot, MPS/CPU |
| benchmark cmd | one seeded MC round, see `server/runs/perf_audit_20260802.md` | compare like-for-like load only |

## Shipped

| date | change | measured | notes |
|---|---|---|---|
| 07-31 | Ordering lookup tables | +11% single-core | killed then-#1 hotspot |
| 08-02 | decompose memo (cache on Ordering, per-round lifetime) | **1.26x** | pure function; differential-tested byte-identical |
| 08-03 | Cython port phases 0-2 (caller-order semantics, rules kernels, leaf ports) | **3.42x** round (5.74->1.68s); beats 11.3x micro | 54/54 both modes, goldens byte-identical 6 seeds; opt-in SHENGJI_FAST=1 |
| 08-02 | trusted-rollout fast path (skip follow re-validation in MC clones only) | ~1% solo (memo cheapened validation) | validate_lead always runs (throw penalties) |
| 08-03 | Cython quarantine fix: caller-order memo keys (tuple(cards)) shared with pure `_dcache`/`_trcache` | **1.10x** round (pure 5.83s / fast 5.29s, seed-7 best-of-3 interleaved) | de-quarantined; 3 red contract tests now green; hashes identical |
| 08-03 | Cython rules port: beats / decompose_matching / validate_follow / pair_count / uniform_suit / check_in_hand | **2.36x** round (pure 6.02s / fast 2.55s) | micro: beats 11.3x, decompose_matching 6.9x, validate_follow 4.0x; 10k+ randomized parity cases per function; hashes identical |
| 08-03 | Cython policy leaves: points/total_points tables + HeuristicBot._lowest/_forced_follow (class-patched at activate) | **3.42x** round (pure 5.74s / fast 1.68s) | partial of the int-native goal (see gap #2/#3); 10k+ randomized parity; goldens byte-identical both modes |

## Gaps (ranked by ROI)

| # | gap | fix | est. win | status |
|---|---|---|---|---|
| 1 | Memory rebuilt per decision (full history rescan, O(tricks²)/round) | incremental Memory carried through rollouts | 1.1-1.2x | open |
| 2 | str card codes ("H10") → dict-hash on every eff_suit/level/beats; list-of-str hands | u8 int cards + array hands inside engine primitives | enabler for #3 | de-quarantined 08-03 (caller-order keys, suite green both modes). str stays at ALL public boundaries; u8 conversion happens per compiled call. Full int-native hands (convert once per rollout, only back at Round.play) still open — the remaining chunk of the 10-20x. |
| 3 | interpreted Python hot loop (per round: 181k heuristic decisions, 845k decompose, 282k beats, 278k validate_follow) | Cython over combos/legal/heuristic AFTER #2 | **10-20x combined** | in progress — **3.42x measured** (rules + policy leaves compiled, opt-in SHENGJI_FAST=1). Post-3.42x profile (fast active, cProfile): heuristic._lead 1.0s, _follow orchestration ~0.8s own, Round.play/_resolve_trick 1.3s, _cheapest_winning 0.5s, _current_winner 0.5s of 4.1s profiled. Next ports: _lead/_current_winner/_cheapest_winning (est. → ~5x), then int-native hands + compiled Round.play for the rest. |
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
