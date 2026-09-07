# Fused static W32 inputs — measured wide-follow speedup

Research-only decision-preserving engineering for [#248](https://github.com/jerryyyu/shengji/issues/248).
Base: `0ba7f709020b455d62f74954dc54154b0cd52d6d` (merged #286).
No production default, checkpoint, training encoder, search budget or live
worker changes. **1.3324× measured decision speedup on two saved huge follows;
the seven-state small/lead panel is neutral. No whole-game or strength claim.**

## Completed isolated Strength A/B

Executed source `e1f93c274f1bcca686df8f1b285e97d34758d05d`, actual ABC
checkpoint, compiled Linux engine, Python 3.14.4, one inference thread. Claude
paused F2 at a retained-shard boundary; the unit and research processes were
independently verified inactive before launch. One counterbalanced paired pass
covered every planned state. No retries, new games, provider calls or outcome
selection. The only arm change was fused static input construction; prepared
lead validation and the existing caches were enabled in both arms.

All **9/9 pairs (18 decisions, including one forced pair)** preserve ordered
score hashes, batches, shortlist, report, work, input states and RNG. Both huge
follows have zero successor/tensor hits and together process **3,509,024 ranking
rows per arm**. This is the full W32/N30/R300 consumer, not a tensor microbenchmark.

| Panel / state | Legal actions | Baseline seconds | Fused seconds | Baseline / fused |
|---|---:|---:|---:|---:|
| Prior panel 0, wide lead | 6,958 | 6.95645 | 6.92460 | 1.0046× |
| Prior panel 1 | 104 | 0.47278 | 0.50709 | 0.9323× |
| Prior panel 2 | 3 | 0.33649 | 0.32636 | 1.0310× |
| Prior panel 3 | 34 | 0.26047 | 0.26646 | 0.9775× |
| Prior panel 4, forced | 1 | 0.00039 | 0.00031 | 1.2425× |
| Prior panel 5 | 8 | 0.11213 | 0.10349 | 1.0835× |
| Prior panel 6 | 4 | 0.10255 | 0.09368 | 1.0946× |
| Recovered follow 0 | 64,897 | 325.84335 | 246.79641 | 1.3203× |
| Recovered follow 1 | 44,760 | 196.90544 | 145.54143 | 1.3529× |
| **Prior seven-state sum** | — | **8.24125** | **8.22199** | **1.0023×** |
| **Two huge-follow sum** | — | **522.74879** | **392.33783** | **1.3324×** |

The large-follow sum uses about **25.0% less wall**. Small states are mixed:
the 104-action case is 34 ms / 7.3% slower in this single paired pass. These are
fixed diagnostic states, not frequency-weighted gameplay; one pair per state
does not establish timing precision. Do not call this regression-free, multiply
it by #286's different-host result, or extrapolate it to a whole-game speedup.
The forced case does not exercise neural encoding. CPU and wall closely agree
on both large states; this is isolated single-decision latency, not all-core
throughput. Better whole-game scheduling remains a separate measurement.

The supervisor finished successfully in **939.07 seconds (15m39s)**, sampled
peak process-group RSS **604,577,792 bytes (~576.6 MiB)**. Both stages exited 0;
neither the per-decision nor outer wall/memory limit fired. Unit
`cwv-fused-static-ab-20260906.service` and its children exited; Strength was
released immediately to Claude. No live F2 or Mini source adopted this change.

Remote root: `shengji-cloud:/root/cwv-fused-static-20260906.CsN7aR/`.
Complete local retained evidence:
`~/shengji-archive/2026-09-06/fused-static-strength-final.FKTnEm/`.
It contains both panels, 18 raw rows, configs/summaries, launch/stage/exit
receipts, log, launcher, exact source archive, native artifact, checkpoint and
private input snapshots. `readout.py` checks the retained rows and transfer
bindings without any model/engine replay. No additional reconstruction run.

- Prior-panel summary SHA: `ab6caf1673109d143df05fb706ae4c82697c98cf81ae2789d72003db57bad658`.
- Huge-follow summary SHA: `56abd3d2f92d9d77902953d8ab11e1f90730ca6140d0ef4b99f08a8e658fed06`.
- Terminal receipt SHA: `af03fe8bf2577387cc2828c867f756ba8d96ef837cf338701aae8fecde5e587d`.
- Readout SHA: `11d1e6be7ddcf352818c5d2742598db1fd9b4c02087eb961c61fa13f85159b30`.
- Exact tracked-source archive SHA: `d7cc3608bc21993c421ae0ab185259b02e355d347649ea60435d9c0630c56183`.
- Executed Linux native SHA: `6a2bd3522b4c2448467c024dbf66d6642f535865af1119d1a8f011bbc2e509fd`.

The archive identifies exact tracked runtime rather than pretending the remote
extraction is a Git checkout. `_fast.pyx` was unchanged against the retained
Linux build source; the probe records/asserts actual native activation. Both
arms use fixed common probe world seeds; these are not asserted to be the
original archived gameplay's sampler streams. This result-only document update
does not change the executed source.

**Next: one consolidated external source+measurement review for merge.** Keep
the research path opt-in and production/checkpoint/training identities intact;
no new capacity, gameplay or timing run is a prerequisite to that review.

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
  Its deadline also bypasses broad encoder fallback catches; a consumer-level
  witness proves expiry is recorded and reopening cannot silently retry it.
- Actual saved ABC checkpoint/native-engine comparison: two 128-action ×
  2-world wide-follow prefixes and one complete small-state W32/N30/R300
  decision are bit-identical. This is **not full wide-follow W32 coverage**.

An independent source reviewer found no blocking defect. The isolated full
consumer A/B above is complete; external source+measurement review remains
required before merge.

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

## Measurement procedure used — do not compete with live scored jobs

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

For this measurement Strength was explicitly released by its owner; it was
not run beside F2. Mini's training/Luna collection and Perf's generation were
untouched. No frozen/live worker adopts this source mid-run.
