# PERF.md — engine/search speed: rules, baselines, shipped results

Durable record only. Live performance work (fresh profiles, ranked candidates,
in-progress optimizations) is tracked in GitHub issue #208, not here. The
historical plan/gaps/candidate sections that used to live in this file are
preserved byte-for-byte in `docs_archive/perf-through-2026-09-04.md`.

Update this file only when an optimization ships (add a row) or a measured
baseline moves (replace the row and date it).

## Measured baselines (latest first)

| date | metric | value | conditions |
|---|---|---|---|
| 2026-09-04 | production search throughput, fast engine | 3,500–4,100 rollouts/s per worker; ~775 rollouts per decision | shengji-cloud 16 workers, oracle probe run1 `runtime.json`/`summary.json` (archived `shengji-archive/2026-09-04/oracle-run1`) |
| 2026-09-04 | compiled vs pure Python, one 2-round cluster, identical output hash | 17.56 s vs 80.31 s (4.57x) | shengji-cloud, `SHENGJI_FAST=1`, Codex profile on issue #208 |
| 2026-09-04 | where search time goes (cProfile shares, compiled) | report fold 80% of `decide_play`; `_rollout` 61%; sampling (`_sample_hands`/`_assign`) 38%; heuristic continuation 21% | one compiled 2-round cluster; shares overlap, do not add; issue #208 |
| 2026-09-04 | share of rollouts in the 300-world report fold (live Run A sidecars) | 77% of all rollouts, 91% of sampled worlds | 4,516 completed clusters, issue #208 |

## Measured baselines (2026-08, retained)

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

## Fast-path evidence and boundaries

The August 3 gate was clean: 2,870 generation decisions and 16,550 teacher
floats were bit-identical, duel records matched per game, the 900-round tier
sweep was clean, and 20k+ edge comparisons plus 69k interleavings passed.
`server/tests/test_fast_parity.py` and golden histories retain the executable gate.
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
