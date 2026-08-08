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

## Current measured baselines (2026-08-02)

| metric | value | conditions |
|---|---|---|
| MC round, single core (pure) | ~5.7s | wide ballots, N=10, post-memo, loaded machine |
| MC round, single core (**SHENGJI_FAST=1**) | **~1.7s (3.42x)** | same conditions; opt-in, seeded histories parity-validated |
| full test suite (08-04 audit) | 44.8s pure / 23.7s fast | 112 passed, 2 skipped in both modes |
| MC round, single core, SHENGJI_FAST=1 | **~1.7s (3.42x)** | same load, seed-7 best-of-3 interleaved (08-03); opt-in only, histories byte-identical (seeds 3/7/11/23/42/99 checked) |
| generation rate | 0.03-0.04 r/s/worker | N=30, wide ballots (gen-v3 config) |
| fleet aggregate | ~0.55 r/s (15 workers) | mini 8 + Air 7 |
| v11 numpy inference | p50 0.25ms / p95 0.52ms | production torch-free path; first call is slower |
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
| 08-07 | release-17 speculative scheduler + off-loop X-ray | live searched-turn p95 `1.714s`; WebSockets responsive during search | Decision semantics unchanged; overlaps pacing, validates before commit, discards stale snapshot state. This is responsiveness isolation, not rollout-throughput speedup. |

## Gaps (ranked by ROI)

| # | gap | fix | est. win | status |
|---|---|---|---|---|
| 1 | Memory rebuilt per decision (full history rescan, O(tricks²)/round) | incremental Memory carried through rollouts | 1.1-1.2x | open |
| 2 | str card codes ("H10") → dict-hash on every eff_suit/level/beats; list-of-str hands | u8 int cards + array hands inside engine primitives | enabler for #3 | de-quarantined 08-03 (caller-order keys, suite green both modes). str stays at ALL public boundaries; u8 conversion happens per compiled call. Full int-native hands (convert once per rollout, only back at Round.play) still open — the remaining chunk of the 10-20x. |
| 3 | interpreted Python hot loop (PARTIALLY DONE: phases 0-2 shipped 08-03) (per round: 181k heuristic decisions, 845k decompose, 282k beats, 278k validate_follow) | Cython over combos/legal/heuristic AFTER #2 | **10-20x combined** | in progress — **3.42x measured** (rules + policy leaves compiled, opt-in SHENGJI_FAST=1). Post-3.42x profile (fast active, cProfile): heuristic._lead 1.0s, _follow orchestration ~0.8s own, Round.play/_resolve_trick 1.3s, _cheapest_winning 0.5s, _current_winner 0.5s of 4.1s profiled. Next ports: _lead/_current_winner/_cheapest_winning (est. → ~5x), then int-native hands + compiled Round.play for the rest. |
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

## RESOLVED 2026-08-03: fast path VALIDATED and LIVE for generation

Deep validation returned CLEAN: generation records are **bit-identical**
(2,870 decisions, 16,550 teacher floats, max |delta| = 0.0; obs vectors,
candidate order, chosen index all identical), duel records are
**per-game identical** (not merely aggregate-equal), 900-round × 3-tier
sweep clean, 20k+ edge comparisons incl. 1,717 throw-penalty firings,
69k interleave checks. Measured generation speedup at fleet conditions:
**0.335 -> 1.212 rounds/s aggregate (3.62x)**.

Trap found and fixed: `SHENGJI_FAST=1` only affected pytest — activation
now lives INSIDE `distill_generate.worker()` (mp spawn re-imports in
children) and asserts loudly; `META.json` records the engine mode so
fast-path data stays scopable. Both machines relaunched on it 10:2x.

Caveats recorded: compiled drop-ins require `list` inputs (TypeError on
tuple/generator — all current callers comply); the HeuristicBot
method-patch guard is activate-time only; `_trcache` population differs
between modes (behaviour does not); the new lowest-beatable throw rule
is unreachable in self-play (0 firings in 900 rounds) so its only
coverage is the constructed sweep + committed test.

## Fast path: RESOLVED (2026-08-03)

The deep validation this section once described as "in flight" completed:
per-candidate VALUE parity, a 300-round sweep, duel-record equivalence, and
interleaving safety all passed, and `SHENGJI_FAST=1` has since generated
gen-v3 and gen-v4 and run every duel on both machines. Bit-identical parity is
asserted by `tests/test_fast_parity.py` and the golden histories.


## Current perf state (2026-08-03 evening)

- Cython fast path VALIDATED and live for generation, duels and tests
  (3.4x round-level; gen-v4 ran at 1.4-2.0 rounds/s aggregate per
  machine vs 0.33 before).
- Profiling of the vleaf hybrid at generation settings: the value net is
  only **8%** of the cost. Per-leaf `enumerate_actions` (32%) and
  `encode_obs` (19%) dominate. **GPU would not help** (485k params;
  kernel-launch overhead exceeds the math; 8 workers would serialise on
  one device — numpy already beat torch 14ms vs 17ms).
- Highest-value remaining perf item: a **direct V(state) head** that
  scores a position without enumerating candidates — removes both
  dominant costs, ~2x on generation AND on vleaf play latency.

## Rules

- Every optimization ships with a differential test (identical seeded
  histories, optimized vs reference path) — correctness of generated
  data outranks speed, always.
- Measure on like-for-like machine load; profile numbers (cProfile)
  overstate hotspots ~2x — trust wall-clock A/Bs for claims.
- Running workers load code at spawn: optimizations reach jobs at
  their NEXT launch, never mid-run.
