# v2 inference: stable cross-batch encoder reuse

Decision-preserving follow-up to #294. No policy, checkpoint, training encoder,
world sampling, selection/report budget or live job changes.

## Defect and repair

`CompleteWorldEvaluator.encoder` returned a fresh v2 lambda on each access.
`TensorInputCache` binds exact encoder/seat/leaf identities, so successive
`score` calls missed the same immutable leaf. A bounded eight-entry dispatch
cache now binds the builder and version to a stable callable. It retains no
model, game or tensor. v1 keeps its original callable. Changing encoder mode
or replacing the builder gets the appropriate separate identity.

Reuse stays within an exact leaf and perspective. Distinct sampled worlds
are not combined; the successor cache remains world-scoped. Every original
model row, its weight and batch position still goes through the network.
This is input reuse, not model-output caching.

## Evidence

Actual W32 on the same 52 saved FIT roots, two counterbalanced repetitions:

| Measurement | Fresh dispatch | Stable dispatch |
|---|---:|---:|
| Tensor constructions | 30,466 | 19,068 |
| Tensor-cache hits | 195,070 | 206,468 |
| Finished-leaf constructions | 19,068 | 19,068 |
| Summed decision wall seconds | 23.8771 | 21.3826 |
| Summed process CPU seconds | 22.8157 | 20.4879 |

All **104 pairs** preserve ordered scores, batch sizes, shortlist choices,
submitted actions, report values, work/allocation counters, RNG and input
state. The comparison exempts only `tensor_hits`, `tensor_completions` and
`peak_tensor_entries` in the two copies of the reuse report; raw reports are
preserved. Tests prove score/report/work/RNG/leaf-counter drift still fails.

Observed reductions: 37.41% fewer tensor constructions, 10.45% wall and
10.20% CPU. **This is a contended Mini diagnostic, not a whole-game or
isolated-host speed claim.** One nice-19 CPU worker ran beside existing jobs;
focused tests also overlapped the initial portion. Process high-water RSS
was 349,765,632 bytes (333.56 MiB), cumulative across arms, not an independent
per-arm memory comparison. No new trajectories, outcomes or holdouts opened.

Checkpoint: completed ACDEF-v2 `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.
Recipe: W32, K4 plus incumbent, N30, R300, batch128, static encoding and
successor reuse. Base source: #294 `b8424cd1`; every row/config binds the
actual changed source and script. Native extension reused from that exact
base after confirming unchanged engine sources (binary SHA `0fd003d0a7fd2c0ff473e195f031f4b74646e21ffe4aa8bebae89f9998cb7080`).

76 focused tests pass in each mode: native 8.35s, pure 18.28s. Restoring fresh
dispatch by process-local mutation makes the actual shortlist batch-loop
witness fail at `tensor_completions == 1` (observed 4), while score equality
still holds. Test coverage also checks early/middle/late positions, seat and
world isolation, mode/builder changes, v1 dispatch, bounded retention and
diagnostic restoration on exception. Initial test-only fixture errors used
an uncapturable empty history and a seed already terminal at ply70; repaired
to the existing live-state fixture family without changing production code.

Reproduce with `server/scripts/cwv_prepared_lead_probe.py`:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
python -P -B -m scripts.cwv_prepared_lead_probe \
  --optimization stable-v2-encoder --states-json FIT_SNAPSHOTS.json \
  --checkpoint COMPLETED_V2.pt --repetitions 2 --out NEW_OUTPUT
```

Run from `server` with its Python path and native extension installed.
Private per-state artifacts and source-bound config:
`~/shengji-archive/2026-09-07/cwv-stable-encoder.1WNpF3/ab/`.
Review should unblock future-consumer adoption after #294, not modify the
in-progress, pinned gameplay family. No deployment authority is implied.
