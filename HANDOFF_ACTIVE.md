# Active Claude/Codex handoff

> Current queue only. Historical review records and raw authority markers live
> in append-only `HANDOFF_REVIEW.md`. A request not listed here is not active.

Last reconciled: 2026-08-21 09:45 EDT by Codex against `origin/main`
`a22f6edc1e47c08c62f2e38d197a8b14a161e012`.

## Immediate objective

Produce one interpretable BELIEF offline result without another all-or-nothing
training loss. R3 is spent and produced no model verdict: it completed capture,
references and 5-6 epochs per cohort, then the old deadline contract refused
before sealing. Calibration, the test split and the terminal were never opened.

R4 repairs that failure mode and adopts measured, parity-checked speedups. It is
source/design work only until one consolidated exact-head source review and one
short exact-freeze review both pass. Those are the only two planned external
review decisions before launch.

## Claude queue — one narrow H0 repair review after exact head is published

The consolidated R4 source review PASS at exact `38617eb` is canonical in
ledger `a22f6ed`; recovery/cache/deadline/source scope remains accepted. The
fresh authorized H0 inventory then exposed one real-population blocker before
freeze: connected-component hashing produced 27/1/2 groups and
2,812/18/**0** decisions, while the reviewed supervisor hardcoded 24/3/3. The
zero-row test fold and mismatched task population make those diagnostic split
bytes unusable.

Review only the exact repair delta from merge head `084850b` once it is
published to PR #122. Return `PASS` or `HOLD` with all load-bearing findings in
one response. Verify:

1. H0 split V3 never separates a cross-file player component or publishes raw
   identities;
2. it uses only component digest and eligible actor-decision counts—not hidden
   labels, outcomes, rank, loss, or model evidence—to apply its fixed 80/10/10
   decision-balance rule, requires every fold nonempty, and routes zero-row
   components to train;
3. the private-population preview is honestly bound: 30 groups, 11 components,
   2,830 decisions; repaired 21/4/5 groups, 7/1/3 components and
   2,323/456/51 decisions for train/calibration/test;
4. the supervisor derives the closed reference/task population from the split
   (current preview: 29 references, 85 total tasks), retains fixed stage order
   and concurrency, and still refuses missing/cache/Cartesian/source drift;
5. the freeze reports `cross-file-human-player-component`, not the obsolete
   per-file split unit; and
6. if `PASS`, the authority remains exactly the prior source PASS: fresh
   score-free H0/preflight/registry receipts and one immutable freeze only. No
   initialization, capture, reference, training, calibration/test opening,
   terminal evaluation, merge, strength claim or deployment.

This second source decision exists only because the first authorized private
population made a reviewed check fail. Do not re-review unchanged
recovery/cache/model code. One later short exact-freeze review remains planned.

## R4 source state — implemented and locally validated

- Graceful deadline truncation: expiry before epoch 1 still refuses; expiry
  after at least one complete epoch seals the mandatory best common epoch as
  `truncated_by_deadline:true` and may proceed through the ordinary offline
  calibration/test gates. It cannot also claim patience convergence.
- Durable epoch recovery: every completed epoch binds model, optimizer,
  receipts, calibration losses and common-epoch selection. Restart must use the
  highest contiguous epoch and original wall clock. An interrupted next-epoch
  publication can finish only when regenerated state/curve bytes equal every
  preserved full byte or exact prefix.
- Durable non-test tensor cache: sparse actor tensors and separately bound
  privileged labels are cached for train/calibration only; the label-control
  cohort shares actor bytes through a label-only overlay. All consumers reopen
  and hash every cache byte. Partial cache construction resumes only from exact
  source-derived content.
- Training/device/scoring are wired to the cache. The original streaming path
  remains the parity oracle, not the production R4 input path.
- REF-C validates actor-constant mechanics once per world batch, and compact
  input derivation no longer reconstructs identical examples twice.
- H0 split isolation is by connected human-player component across source
  files. The repaired split balances eligible decision counts without reading
  labels/outcomes; raw identities remain unpublished.
- Every long stage emits machine-readable percent progress.
- The old external nine-stage R3 supervisor is superseded by a source-bound
  ten-stage split-derived R4 plan. The real preview has 85 tasks and 13
  non-Cartesian human references. It includes the cache before qualification,
  runs references before
  the four-by-four-worker CPU training stage, and refuses any dropped, added or
  reordered task before publishing the ops start token. The sanitized plan
  summary binds the SHA-256 of the complete internal task/argument population,
  while private source paths remain unpublished.

Measured generated-input performance (not scientific evidence):

- REF-C: `28.160s -> 14.664s`, **1.92x**, with identical 68-decision,
  17,408-world streams and exact actor/world/counter hashes.
- compact input derivation: `21.38s -> 9.45s`, **2.26x**, with identical
  1,332-decision payload SHA-256.
- sparse cached epoch on Performance Cloud: `169.78s -> 32.36s`, **5.25x**,
  with exact receipts and model hashes; `447,743,533 -> 72,275,646` bytes
  (**6.19x** smaller). Full cache projection is about 31 GiB; the proposed
  reviewed cap is 64 GiB and must be re-measured on the execution host.

Current validation:

- H0 repair surface: `43 passed`; a real root-only preview reconstructs the
  21/4/5 group, 7/1/3 component, 2,323/456/51 decision split and an 85-task
  supervisor without publishing identities or outcome fields;

- final recovery/cache/freeze/controller/supervisor suite: `111 passed`; the
  supervisor mutation witnesses refuse a missing cache stage, the old
  Cartesian reference matrix and source/split population drift. The added
  controller-altitude witness proves the cache factories, rather than either
  materialized or streaming fallback, produce the sealed/reopened cohort;
- all BELIEF tests before the final supervisor/wiring delta, pure: `407 passed,
  2 skipped`;
- all BELIEF tests, compiled: `409 passed`;
- worker bootstrap before final publication: PASS through a temporary alternate
  Git index containing the then-new source paths; it will be rerun from the
  clean exact committed head before push;
- full server suite: `2164 passed, 10 skipped, 39 failed`. One failure is the
  expected worker bootstrap refusal while new modules remained untracked; that
  exact path passes through a temporary alternate index. The other 38 are
  unavailable historical/private artifacts or tests outside every path changed
  by the six-commit R4 base plus the local R4 diff. No changed BELIEF behavior
  failed the complete pure or compiled BELIEF suites.

## Remaining path to one run

1. Publish and obtain the single narrow H0 repair PASS requested above.
2. Regenerate clean exact-head H0, seed registry and generated/outcome-blind
   host preflights for exact cache size, free disk,
   memory, thread/process width and revised per-epoch pace. No scientific or
   sealed test bytes may be opened.
3. Build one host-specific immutable freeze and obtain one short Claude PASS on
   its exact bytes, identities, caps, authority map and fresh namespace.
4. Only after the repair and freeze PASS decisions, initialize and launch the
   bounded DAG.
   Cache/capture/reference/training progress must be reported as percentages.
5. A completed or deadline-truncated cohort is evaluated; only a pre-epoch
   failure remains absence of evidence. No sampler, strength or deployment
   authority is implied by an offline BELIEF result.

## Authority and fleet boundary

- No R4 scientific run or sealed test opening has been started.
- Live check at 09:30 EDT: Strength Cloud and Performance Cloud are reachable,
  each has 16 logical CPUs and near-zero load, with about 502 GiB and 564 GiB
  free. The reviewed Strength checkout is separate from the dirty H0 repair
  preview; no R4 scientific stage has started.
- R1, R2 and R3 admissions are spent. Their evidence may be audited but is not
  reusable input to R4 without a separately reviewed reusable-artifact design.
- No current marker authorizes retry, sampler implementation, gameplay,
  strength claims, promotion or deployment.
- `HANDOFF_REVIEW.md` remains byte-append-only. Do not compact it in an ordinary
  PR: exact-prefix CI and review authentication require every current byte.
  A later lossless rotation needs an acknowledged cutoff, byte-identical archive,
  hash-bound rotation record and its special merge procedure.
