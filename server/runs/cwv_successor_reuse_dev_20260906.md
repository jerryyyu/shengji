# Shortlist successor reuse — engineering A/B

Status: opt-in implementation and differential checks complete; isolated wall
profile pending. No speedup, new strength, merge or deployment claim. Track
shortlist work in #248; this extends the #249/#252 encoding optimizations.

## What is reused

The exhaustive enumerator lists submitted actions, including throws that the
engine can reduce to a forced component. For one fixed root and sampled world,
different submissions can therefore have the same actual played cards and the
same remaining hands. The current deterministic heuristic finisher and model
encoder do not use the discarded attempt/message as an extra feature.

Every submitted action still passes through `afterstate(..., finish_trick=False)`.
`WorldSuccessorCache` keys the ordered engine-accepted tuple from
`actual_play_after`, scopes it to that root/world, and retains at most 128
finished leaves. A separate 128-entry `TensorInputCache` uses exact leaf identity,
encoder identity and seat. References are retained to prevent object-ID reuse.

The tensor cache spans one decision because forward batches can cross world
boundaries. **No model row is removed or reordered, and no batch is flushed at a
new boundary.** Softmax, float64 support multiplication, summation, shortlist
tie-breaking, world draws and final MC selection/report are unchanged. Terminal
rows still use exact terminal utility. There is no neural prediction cache.

The cache assumes immutable finished leaves and the existing deterministic
finisher. Do not hand cached mutable Rounds to recursive search or reuse these
caches after modifying a root, leaf, continuation policy or encoder. Each cache
is local and discarded after the ranking decision; no cross-game/world cache,
new global storage layer or full action-by-world materialization is introduced.

## Evidence so far

The real retained A+B+C checkpoint is
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
On seven pre-existing snapshots, one sampled world each, four modes
(reference/static encoding × reuse off/on) produced identical ordered score
hashes, batch populations, complete shortlist receipts excluding wall/reuse
telemetry, and unchanged parent RNG. A forced singleton was included.

| Submitted actions | Finished leaves / tensor builds with reuse | Reused rows |
|---:|---:|---:|
| 6,958 | 25 | 6,933 |
| 104 | 19 | 85 |
| 3 | 3 | 0 |
| 34 | 11 | 23 |
| 1 | 0 (forced; ranking skipped) | 0 |
| 8 | 4 | 4 |
| 4 | 4 | 0 |

For the wide case all modes retained 54 batches of 128 plus one batch of 46,
with score SHA `325688b90a4b057b051636a3ca9df54b41ce78d1ba3e9ac44de41cba95c30b88`.
This is a seven-position structural/differential result, **not** a population
duplicate rate, 278x speedup, or proof that only 25 actions matter across worlds.
The isolated timing probe must measure the retained model/engine work too.

Local receipt and bounded driver:
`/private/tmp/shengji-cwv-encoding.qRHUNe/successor-parity.actual.jsonl` and
`successor_parity.py` in the same directory. These did not publish hidden cards,
read game outcomes or launch new games; the host was contended, so no wall claim
is derived from them.

Focused tests cover actual full MC decisions with MLP/reference, MLP/static and
Transformer/reference; three worlds with batch17 (straddling world boundaries)
and internal max_batch13; exact final play/RNG/score/batch parity; real finisher
and encoder call counts reconciled to the result record; root immutability,
world/seat/encoder isolation, eviction, fourth-seat/terminal resolution; and
CLI → worker → resume-recipe binding. The cost probe's corruption witnesses
require a score or decision mutation to fail the parity comparison.

Validation: 53 focused tests passed in the default mode (12 new/extended and
41 surrounding regressions); the 12 new/extended cases also passed with
`SHENGJI_FAST=1`. An in-memory mutation dropping the evaluator's cache argument
made the real-decision witness fail on 588 encodes versus 588: helper-only tests
could not mask that broken wiring. Source files were not modified by the probe.

## Profile, then scaling

The existing `scripts/cwv_shortlist_cost.py` now accepts
`--successor-grid off,on`, independently of `--encoding-grid reference,mlp-static`.
It reuses `--states-json`, counterbalances recipe order, and atomically retains
each completed state/arm for interruption recovery. Report ordered score/batch/
decision/RNG parity; end-to-end and ranking wall; CPU/wall effective cores; cache
hits/completions and peak entries; process-lifetime peak RSS (not per-arm memory
savings). No duplicate whole-run integrity pass is required.

Run the W32 A/B in an isolated window, one native thread per worker, before
using measurements to size parallel runs. Structural tests may run bounded and
single-threaded on a busy host; timing claims may not. Do not stop live teacher,
training, PUCT or capture jobs to create a window.

Jerry authorized using the optimization in the not-yet-started shortlist scaling
arms after parity, profiling and Claude approval. Bind the same engineering
mode for optimized-W32 cost measurement and W64, preserve checkpoint/search
settings, and keep engineering savings separate from the W64 policy comparison.
The screen flag is `--reuse-successors`, learned-only and off by default; enabled
receipts bind the flag while legacy/default recipes reopen unchanged. No existing
run is changed in place. Production x10 and final MC x2 remain separate questions
in #251; this cache does not increase their rollout budgets by itself.
