# W32 v2: reuse validated public unseen counts

This is a decision-preserving inference optimization, not a new model or
search policy. On 52 retained FIT states, two counterbalanced repetitions
gave **104/104 exact matched decisions**, with 2.44% less observed wall and
2.06% less CPU. This is a modest incremental gain after #294 and #297,
measured on a contended Mini—not a production or whole-game speed claim.

## Change

The v2 static MLP encoder already constructs the v1 public observation.
It then rebuilt a complete `Memory` object to get one quantity for the
additional 29 columns: unseen trump count. That repeated history/deduction
work even though the validated v1 observation already contains the exact
unseen-card counts, as half-copy values.

The fast route now recovers those counts from the v1 plane. The reference
and fast routes share the same v2 feature arithmetic and tensor assembly;
there is no second implementation of the 29 features. The shortcut is used
only after successful fused-state validation. Unsupported or malformed states
retain the reference route and its refusal behavior. In particular, the
historical `own_kitty=False` convention is unchanged: even the banker's own
buried cards remain in this public unseen plane.

No model dimensions, weights, information boundary, rank order, batches,
worlds, selection/report budgets, LCB rule, cache capacity, or RNG policy
change. v1 and sequential-model dispatch remain unchanged. All nine source
files in the archived CWV checkpoint-identity closure are untouched; existing
checkpoint and cache identities remain usable.

## Actual-consumer result

The existing `cwv_prepared_lead_probe.py --optimization v2-unseen` switches
only the v2 count-reuse helper back to reference widening for the baseline.
Both arms keep the other merged optimizations. It compares every raw semantic
field: score-stream digest, batch sizes, shortlist, final action, selection
means, report, rollout work, all reuse counters, input mutation, and RNG state.

| 104 decisions per arm | Baseline | Public-count reuse |
|---|---:|---:|
| Summed decision wall | 17.7555 s | 17.3220 s |
| Summed process CPU | 17.4443 s | 17.0849 s |
| Decision/score/work/RNG differences | — | 0 |

Wall reduction was 2.35% and 2.53% in the two repetitions; CPU reduction
was 1.59% and 2.54%. Process cumulative peak RSS was 360.39 MiB; because
the arms share a process, this is **not** an arm-specific memory comparison.
Two repeats of 52 states are not 104 independent states. The Mini was also
running Claude's unrelated H256 MPS training. No held-out states were opened,
no games were replayed, and no live source or job was modified.

Recipe: W32/K4/N30/R300, batch128, seed89260904, one nice19 process with
BLAS/Torch threads1. Checkpoint SHA:
`3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.
Base main: `4bf63d9125cb3d5f9498c6a17951194b513adfc1`. The benchmark binds
the actual proposed source bytes, not merely this unchanged base HEAD.

Retained artifact: `~/shengji-archive/2026-09-07/cwv-v2-unseen.pgTPWO/`.
`consumer/config.json` binds source/native/checkpoint/input hashes;
`consumer/r*.json` holds all per-decision receipts. `analyze.py` rechecks
exact parity and source bytes and derives `readout.json` without model calls
or new rollouts. Configuration SHA:
`c16bd027330bce05ab5d06146c48d2ce674f18afb3a9a5d0fc510b5c381bd1c3`.

## Validation and scope

The focused encoder/evaluator/identity suite passes **130 tests in each mode**:
`SHENGJI_FAST` unset (16.75 s), and compiled play with `SHENGJI_FAST=1`,
`SHENGJI_REQUIRE_VOIDS=1` (8.07 s). Both have the same inherited unknown
`integration` mark warning. The test list is:

```text
tests/test_cwv_v2_unseen.py tests/test_cwv_v2_static_widen.py
tests/test_cwv_stable_encoder.py tests/test_encode_versions.py
tests/test_cwv_fused_static.py tests/test_cwv_policy.py
tests/test_cwv_static_encoding.py tests/test_cwv_static_public.py
tests/test_cwv_encoder_v2_binding.py tests/test_encoder_identity.py
```

New witnesses disconnect the optimization at the real
evaluator call site and trigger a `Memory` tripwire; explicitly distinguish
banker private-kitty semantics; preserve canonical fallback errors; and test
probe restoration on an exception. Existing multi-rank, no-trump, four-seat,
early/mid/late parity cases continue to compare complete model inputs.

One inherited test still forbade *any* v1 fusion beneath a v2 request, contrary
to merged #294. Its failure was reproduced on the old source. The repaired
witness now requires v1-only fusion plus full canonical v2 tensor equality;
the neighboring direct-v2-fusion refusal test remains. This is test-contract
alignment, not evidence of a new v2 runtime defect.

Adoption should be a normal reviewed source change for future workers.
Do not hot-swap a running worker, rerun completed model evaluations merely
to time this change, or treat this small saving as a new strength result.
