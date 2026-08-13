# PERF.md — simulation speed: gaps, plan, progress

Living tracker for making the engine/search fast. Dated snapshots live
in `server/runs/perf_audit_*.md`; this file is the current state.
Update whenever an optimization ships or a measurement moves.

**Why it matters**: generation throughput bounds the whole project —
teacher data (gen-v3: ~28h fleet-wide), duels, tournaments, and MC's
live latency all sit on the same rollout loop. Rough math: 10x here =
overnight gens become 3h, and every gate duel runs in minutes.

## Current production performance — release 18

Production runs compiled `mc-s0-report-lcb`, not the older policies in the
historical table below. A matched Mini benchmark measured 0.390s per decision
for report-LCB versus 0.127s for `mc-strong`; that extra work buys the confirmed
`+0.338 +/- 0.068` signed-level gain. On Fly before the scheduler change,
searched turns could block room interaction and then pay a separate fixed 0.7s
pacing delay.

Release 17 introduced the performance change: it preserves the exact N=30/R=300 decision semantics while searching an
isolated snapshot off the event loop and overlapping the pacing window. It
revalidates room/round/phase/turn/controller before commit, discarding stale
actions and cloned RNG/counters. The live ship gate kept 25 concurrent
WebSocket probes at p50 12ms/max 19ms during a real 1.53s X-ray. The first
ordinary post-fix human room produced 195 search-like turns with
search p50/p95/max `0.896/1.714/1.906s` and full-turn
`0.904/1.716/1.907s`; all 249 bot turns were offloaded and isolated.

Release 18 keeps that runtime and adds kitty X-ray only; it does not change the
policy or search cost. This fixes event-loop blocking and removes an additive wait. It does not make
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

## Current candidates — independently audited, external review

The Cython `_current_winner` path is dropped. Corrected microbenchmarks against
the production baseline found it about 4% slower on both ARM and x86; the
earlier roughly 6x leaf microbenchmark did not represent production work. The
combined `b7476e4` timing was confounded and is not a merge-candidate result.

The lead candidate implementation is `414fe29`, with historical-evidence test
repair at exact PR #71 head `093ec33`: a pair-count tractor
prefilter plus redundant import cleanup, with no Cython leaf. The optimization
uses a necessary condition—a `k`-pair tractor cannot exist when fewer than `k`
physical pairs exist—so it avoids impossible enumerations without pruning a
legal tractor.

Isolated x86 measurement with compiled routing produced:

- 10,000 natural lead decisions across five repeats: `0.459523s -> 0.198866s`
  mean, **2.31x faster**, exact action digests;
- 20 paired seeded full rounds: `1.616785s -> 1.426878s` mean, **11.75% less
  wall time**, every paired reduction positive (`8.61%–15.66%`), exact play
  histories and terminal results.

An independent four-seed ARM check reproduced complete deck/declaration/bury,
ordered play, trick and terminal identities; median speedup was **1.198x**.
These are synthetic performance measurements, not strength evidence.

The first audit found a pre-existing H0 integrity hole: a newly constructed
controller could name the frozen historical heuristic while blessing today's
runtime heuristic. The repair validates all three frozen executable sources
(heuristic, action universe and structured bury) during controller creation and
every runtime reopen; the test shim now returns the exact frozen byte count
instead of a hybrid record. Fifty focused and 134 broader strict compiled tests
pass. A second independent audit reproduced the complete guard mutations and
found 16.22% lower median ARM whole-round time across alternating 2,000-round
trials with identical transcript SHA. Exact head `093ec33` is draft PR #71;
CI passes. Merge still waits for Claude's independent semantics/benchmark
review and user approval.

Corrected compatibility receipt PR #75 head `90c5630` keeps the historical
RLCB/H0 identities immutable while binding the current heuristic, ballot,
three-policy contracts and the exact 64-character native `.text` identity.
It is compatibility evidence only: it authorizes no deployment or strength
evaluation.

Prepared-world PR #77 head `0381081` validates each accepted determinized
world once, then gives every candidate fresh non-aliased hand lists. Six fresh
exact-head x86 pairs measured `116.391565s -> 113.338140s`: **2.6234% lower
wall time**, **2.6941% higher throughput** and a **1.5066%** one-sided lower
bound, with normalized decisions, RNG, sampler/work counters and transcripts
identical. That missed the preregistered **3% retention gate**, so PR #77 is
not retained as-is. The earlier 3.37% nine-pair number mixed two code revisions
and is retired. The larger trick-state-cache prototype is also rejected: its
safe fingerprint/order/pickle repair was **10.56% slower** over six fresh
normalized full rounds, every pair slower.

PR #81 head `c6c7126` contains two candidates that cleared their own retain
thresholds but is stacked on rejected PR #77. Native cheapest-winner selection
measured **7.7306% lower wall time** with a paired one-sided lower bound of
**6.2489%**. Counting rollout-lead pairs once per hand measured **4.0124%
incremental reduction** with a **3.2857%** lower bound. Every normalized
gameplay, search, RNG and sampler artifact matched byte-for-byte. Preserve the
two candidates, not the current stack: split and rebase them onto the accepted
PR #71/#75 path, then remeasure that exact composition. The percentages come
from different baselines and must not be added. PR #81 authorizes no merge,
deployment, policy change or substitution into a sealed strength run.

The first native-lead prototype head `0bd073c` could segfault on a malformed
negative seat even though ordinary gameplay parity passed. Repaired source
`8e698e` restores the Python boundary and passes 31 ARM plus 30 x86
boundary/parity cases; an independent adversarial audit also passed. One
ordinary exploratory three-pair exact-final A/B measured
`40.7905s -> 36.6293s`: **10.2014% lower aggregate wall time**, **11.3603%
higher throughput** and a **9.22594%** one-sided lower bound, with normalized
gameplay, search work, RNG and sampler records matching exactly. The result is
published in stacked draft PR #83 head `69ff44e`, whose CI is green.

This is deliberately not confirmatory evidence. The raw remote artifacts are
still owner-writable and have no immutable manifest; the committed receipt
hash-pins the observed design, result, harness and runner files, but does not
make their remote storage immutable. Treat the number as a performance-only
exploratory estimate with no strength, merge, review, deployment or sealed-run
substitution authority.

Those retained implementation ideas are now composed in PR #89 without the
below-threshold PR #77 prepared-world seam. Exact measurement base is PR #71
`093ec33`; optimized arm `a91eb271` combines native cheapest-winner, guarded
native lead, trusted-rollout trick-state maintenance and disabled-exact-endgame
hoists. Source/tooling head `fa0f9cf` PASSed external review. The isolated
percentages above remain useful provenance but must not be added or marketed as
the combined result.

The first host design was retired before execution because its evidence root
sat directly beneath mode-1777 `/var/tmp` and failed the harness's own
parent-ownership admission check. Corrected frozen design `8721aec4…ec9d`
moves the still-absent evidence root beneath root-owned
`/var/lib/shengji-perf-ab-pr89-v2r1`; all six seeds remain unused. It awaits a
replacement exact-design PASS, after which exactly one six-pair N=30/R=300
batch may run with no retry or tuning. Retention requires byte-exact normalized
semantics, at least 3% aggregate wall reduction and a positive paired one-sided
95% lower bound.

## Gaps (ranked by ROI)

The ordering below came from the pre-activation profile. Before choosing the
next port, take a fresh isolated profile: the 3.62x compiled win changed where
time is spent. Port shared engine/heuristic leaves used by active policies, not
one-off experiment controllers.

| # | gap | fix | est. win | status |
|---|---|---|---|---|
| 1 | Memory rebuilt per decision (historical profile) | incremental Memory carried through rollouts | `<0.1%` for current champion | rejected for report-LCB: 179 constructions were only 0.073–0.078% of x86/ARM round time; reconsider only if a Memory-aware rollout becomes active |
| 2 | Python policy hot loop after compiled phases 0-2 | measure exact PR #89 base `093ec33` versus composed arm `a91eb271` once under corrected immutable design `8721aec4…ec9d` | prior isolated candidates ranged from 4.0% to 10.2%, but only the combined fresh batch can establish retained ROI | source reviewed; corrected host design awaits exact PASS, no batch yet |
| 3 | string cards and list hands still cross every compiled call | convert once per rollout; compile `Round.play`/trick resolution | remaining path toward 10-20x | open; keep strings at public boundaries |
| 4 | Round/Trick clone churn per rollout (3.8k clones/round) | reusable scratch state | ~1.1x | open |
| 5 | multi-room capacity is not measured | concurrent-room latency/load gate | product reliability | open |
| 6 | feature flags mix exact `"1"` checks with string truthiness | version and centralize boolean parsing | evidence correctness | open; until then unset flags for false—`=0` is unsafe |
| 7 | rollouts always play to round end | early-terminate decided brackets | speculative and potentially biased | parked behind a strength/correctness gate |
| 8 | strength-compute ceiling | rented 16-vCPU x86 strength Cloud worker | roughly doubles the local 16-slot fleet, zero policy change | active; currently owns S4 |
| 9 | isolated performance capacity | separate 16-vCPU / 30-GiB x86 worker via local `shengji-perf` alias | profiles and parity without disturbing sealed runs | idle and admission-ready for corrected PR #89 design after exact PASS; PR #93/#94 strict x86 tests completed without gameplay. Pair V3's score-free capacity result grants no scored execution or strength authority |
| 10 | Rust/PyO3 full engine core | 30-100x; wasm client bonus | large | parked; requires a 10k-seed two-engine parity harness |

## Plan (sequencing)

1. Keep PR #77 retired after missing its 3% gate. Run exactly one reviewed PR
   #89 six-pair batch for base `093ec33` versus optimized arm `a91eb271` under
   corrected design `8721aec4…ec9d`; no retry, tuning or cross-baseline pooling.
2. Retain the composed stack only if every normalized semantic/work/RNG record
   is exact, aggregate wall reduction is at least 3% and the paired one-sided
   lower bound is positive. Otherwise drop it as a unit and profile before
   choosing a smaller successor.
3. After exact-stack measurement and review, profile the accepted stack
   again. Do not infer the
   next hotspot from the old profile or from leaf microbenchmarks that bypass
   today's compiled globals.
4. Consider moving int-card conversion to the rollout boundary and compiling
   `Round.play`/trick resolution only if that fresh profile still names them.
   The first trick-resolution candidate was retired before timing because its
   frozen normal harness rejected 11/72 forced no-search plays before reaching
   the head arm. Do not retry that evidence slot; future harnesses must accept
   normal forced plays while separately pinning that the optimized seam fired.
5. Add a concurrent-room production capacity test; event-loop isolation alone
   is not a capacity proof.
6. Reconsider incremental Memory only if a Memory-aware rollout policy becomes
   active; it is not a current-champion hotspot.
7. Keep `shengji-cloud` strength evidence and `shengji-perf` optimization work
   physically and logically separate. Pair V3's score-free capacity result
   passed external review at canonical `16af447`, opening scored-packet design
   only. It is not permission to freeze, run or score strength work, open
   REPORT, train, promote or deploy.

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
- Never benchmark or run a full test suite beside a sealed scored job merely
  because a core appears spare. Code, CI and tiny deterministic checks may run
  elsewhere; host measurements wait for an explicit isolated window.
- Running workers load code at spawn: optimizations reach jobs at
  their NEXT launch, never mid-run.
- Parse environment flags through one versioned helper. Until that migration,
  unset a flag to mean false; several paths currently treat the string `"0"`
  as true.
