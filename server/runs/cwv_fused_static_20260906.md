# Fused static W32 inputs — correctness checked, timing pending

Research-only decision-preserving engineering for [#248](https://github.com/jerryyyu/shengji/issues/248).
Base: `0ba7f709020b455d62f74954dc54154b0cd52d6d` (merged #286).
No production default, checkpoint, training encoder, search budget or live
worker changes. **No speedup or gameplay-strength claim yet.**

## Why this target

The two original zero-reuse follow positions are recovered, not hypothetical:
ABC rank-2 cluster 255, seed 90261159, mirror 0, trick 2, seats 0 and 2.
Their exhaustive ordered action sets contain 64,897 and 44,760 actions,
respectively: 3,509,024 W32 ranking rows together. Replaying the stored public
prefix plus deterministic setup reproduced both ordered legal-set hashes.
No new search, model calls or policy decisions were needed for recovery.

On a tiny actual-consumer prefix (128 actions × first 2 original sampled
worlds per position), both successor and tensor hit counts were zero. Static
tensor construction took 48.44/48.65 ms inside 77.29/59.30 ms ranking profiles.
Public encoding, physical checks and tensor validation are nested inside
those totals, not additive. This contended-host cProfile diagnostic identifies
work; it is not a wall-speedup measurement or a population-share estimate.

## Change and boundaries

`_fused_static_tensors` constructs public/world/perspective planes while
validating the same cards and events in one traversal. It counts the full
physical deck and still requires exactly two copies of every card. It retains
tensor shape, finite-value, count and perspective validation.

The fast path is restricted to ordinary exact play-phase engine objects and
standard list-backed fields. Unsupported or malformed input falls back to
the unchanged static/reference path, preserving exception type, text and
ordering. There is no trust flag, cross-call cache or skipped physical check.
The MLP's discarded history remains one zero row. Sequence models still use
the reference encoder. Checkpoint/training-encoder identity is unchanged;
the separately recorded inference-adapter source hash changes normally.

This addresses both short-history wide follows and later states. Caching only
long public histories would not address the recovered trick-2 bottleneck.

## Verified evidence

- 30 targeted tests pass in pure Python and with the compiled engine.
- Differential tensor checks cover all four root seats, early/middle/late
  history, ordinary trumps and NT, banker-private card copies and nonzero
  void flags. No input mutation.
- Malformed physical population, cards, declaration and events preserve
  refusals. A duplicate played-card witness cannot be satisfied by validating
  hidden-world tensors alone.
- A real evaluator tripwire proves the fused path is used; disconnecting it
  fails at the consumer. A small real shortlist preserves ordered score bytes,
  batches, shortlist, report, work and RNG.
- The extended A/B probe switches only the requested optimization, restores
  its process-local patch after errors, publishes actual consumer parity and
  reopens completed rows without replay. Prepared-lead remains the default;
  fused-static keeps prepared-lead enabled in both arms.
- Actual saved ABC checkpoint/native-engine comparison: two 128-action ×
  2-world wide-follow prefixes and one complete small-state W32/N30/R300
  decision are bit-identical. This is **not full wide-follow W32 coverage**.

An independent source reviewer found no blocking defect. External review and
an isolated actual-consumer wall A/B are still required before merge.

The private diagnostic initially compared a sorted snapshot serialization
against an older fixture's unsorted hand lists. The check was corrected to
compare before/after serialization plus the original ordered hand/burial
lists. The encoder/source was unchanged by that diagnostic repair.

### Retained artifacts

- Recovery, private states, original world seeds and profiles:
  `~/shengji-archive/2026-09-06/w32-wide-follow-recovery.2esjdh/`.
- Saved-model parity script/result and final test logs:
  `~/shengji-archive/2026-09-06/w32-fused-static-check.SzEEsD/`.
- Actual checkpoint SHA:
  `3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
- Checked adapter SHA:
  `989c8e4dbaa09bc7f27fdc4b6d7eb50a18c248038ece41d8040985ffc73695c3`.
- Saved-model result SHA:
  `2d40b8d3ca65de395556b14bb5de01cf850548ba950d0ccd9e4f66fc21444ec3`.
- Compiled artifact SHA:
  `6e812718892ec31885f188ca664e69c84213219d88dd295afd8db862068807e7`.

## Next measurement — do not compete with live scored jobs

Use the existing probe, not a new gameplay run:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
python -B -m scripts.cwv_prepared_lead_probe \
  --optimization fused-static --states-json <saved-states.json> \
  --checkpoint <ABC-checkpoint.pt> --out <fresh-output> \
  --repetitions 1 --decision-seconds 600
```

Start with one paired pass over both recovered wide follows and the prior
seven-state panel in an isolated window. The full decision includes
enumeration, all 32 worlds, scoring and MC-LCB verification. Preserve every
ordered score, batch, shortlist, report, work count and RNG state; refuse on
any mismatch. Per-decision failures retain completed rows and cannot silently
restart. Repeat counterbalanced pairs only if the measured cost fits the
available window. Report individual states and fixed-panel aggregate
separately, including regressions; do not call either whole-game speedup.

Mini currently has Claude's scored ACD screen/training plus Luna collection;
both clouds are generating data. No isolated timing run was launched beside
them. No frozen/live worker adopts this source mid-run.
