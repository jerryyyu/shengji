# PERF.md — simulation speed: gaps, plan, progress

Living tracker for making the engine/search fast. Dated snapshots live
in `server/runs/perf_audit_*.md`; this file is the current state.
Update whenever an optimization ships or a measurement moves.

**Why it matters**: generation throughput bounds the whole project —
teacher data (gen-v3: ~28h fleet-wide), duels, tournaments, and MC's
live latency all sit on the same rollout loop. Rough math: 10x here =
overnight gens become 3h, and every gate duel runs in minutes.

## Deployment Pareto table (measured 2026-08-04)

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
| `mc-gate-v11pair` | 0.25 ms | 30 ms | 53.3% vs mc (n=300, screen only) | searches the ~12% it flags; FAILED its offline gate |
| `mc` (current default) | 77 ms | 150 ms | pool ~1119 | determinized search, N_DETERMINIZATIONS=10 |

**The Pareto frontier is two policies wide.** `smart` is the floor at
~0.05 ms. `rl-override-v11pair` is level with `mc` on 4,880 rounds at
**300x lower p50 and 290x lower p95** — that is the whole result. `mc-vleaf`
and `mc-gate` are dominated: both cost far more than the override and neither
is measurably stronger than `mc`.

Practical reading for a deploy decision:
- Switching prod from `mc` to `rl-override-v11pair` buys ~300x headroom per
  decision and removes the 150 ms p95 stalls, at no measured strength cost —
  where "no measured cost" rests on provisional unseeded evidence, not a
  seeded confirmation.
  It is a COST and RESPONSIVENESS decision, not an AI upgrade.
- `mc`'s p95 of 150 ms is per decision; a four-bot table compounds that, which
  is what makes the tail visible during play.
- The override's own max (3.3 ms) is a first-call artefact — the numpy weights
  load lazily.

---

## Current measured baselines (2026-08-02)

| metric | value | conditions |
|---|---|---|
| MC round, single core (pure) | ~5.7s | wide ballots, N=10, post-memo, loaded machine |
| MC round, single core (**SHENGJI_FAST=1**) | **~1.7s (3.42x)** | same conditions; opt-in, validation pending for gen/duels |
| full test suite | 18.6s pure / 7.0s fast | 55 tests, both modes green |
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
