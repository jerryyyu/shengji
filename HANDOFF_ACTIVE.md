# Active Claude/Codex handoff

> Current queue only. Historical review records and raw authority markers live
> in append-only `HANDOFF_REVIEW.md`. A request not listed here is not active.

Last reconciled: 2026-08-21 09:06 EDT by Codex against `origin/main`
`4e8aa9becb420ec78ad402acb54f2e80d12360b2`.

## Immediate objective

Produce one interpretable BELIEF offline result without another all-or-nothing
training loss. R3 is spent and produced no model verdict: it completed capture,
references and 5-6 epochs per cohort, then the old deadline contract refused
before sealing. Calibration, the test split and the terminal were never opened.

R4 repairs that failure mode and adopts measured, parity-checked speedups. It is
source/design work only until one consolidated exact-head source review and one
short exact-freeze review both pass. Those are the only two planned external
review decisions before launch.

## Claude queue — one consolidated R4 source review

Review the exact current PR head of branch `codex/belief-r4-restart-cache`
against `origin/main`. This is the only active Claude request. Do not split it
into separate design, cache, recovery, orchestration or host-protocol reviews.
Do not launch compute, open calibration/test inputs, merge or deploy.

Audit the complete R4 source/design delta and answer exactly:

1. `PASS` or `HOLD`, with only load-bearing findings and exact file/line;
2. whether graceful deadline truncation and durable epoch recovery preserve a
   valid best-common-epoch result without allowing a truncated cohort to claim
   patience convergence, retry, or reuse a spent namespace;
3. whether sparse non-test tensor caching, the label-only control overlay,
   REF-C/input speedups and every materialized/streaming parity witness preserve
   exact semantics and actor/privileged separation;
4. whether connected-component H0 splitting prevents the same human identity
   from crossing files/splits without publishing raw identities;
5. whether the source-bound ten-stage/81-task supervisor is complete,
   fail-fast, non-Cartesian for human references, and incapable of opening the
   test stage before all predecessors pass; and
6. if `PASS`, whether it authorizes only fresh score-free H0 inventory/split,
   generated/outcome-blind host capacity/device/deadline measurements, seed
   registry construction and one immutable R4 freeze. It does **not** authorize
   initialization, training, calibration/test opening, terminal evaluation,
   strength claims, sampler work, merge or deployment.

One later short exact-freeze review is planned. Add another source review round
only if this review finds a load-bearing defect or the reviewed source bytes
materially change.

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
- H0 split isolation is by connected human-player component across source files,
  while raw player identities remain unpublished.
- Every long stage emits machine-readable percent progress.
- The old external nine-stage R3 supervisor is superseded by a source-bound
  ten-stage/81-task R4 plan. It includes the cache before qualification,
  permits exactly nine non-Cartesian human references, runs references before
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

1. Publish the R4 source as one clean exact draft-PR head; the final
   diff/whitespace check and 111-test recovery/cache/freeze/controller/supervisor
   surface pass locally.
2. Obtain the one consolidated Claude PASS requested above on source, recovery,
   cache parity,
   information boundaries, H0 isolation and the host-probe protocol. This PASS
   authorizes only the fresh score-free host receipts and freeze construction.
3. Run generated/outcome-blind host preflights for exact cache size, free disk,
   memory, thread/process width and revised per-epoch pace. No scientific or
   sealed test bytes may be opened.
4. Build one host-specific immutable freeze and obtain one short Claude PASS on
   its exact bytes, identities, caps, authority map and fresh namespace.
5. Only after both PASS decisions, initialize and launch the bounded DAG.
   Cache/capture/reference/training progress must be reported as percentages.
6. A completed or deadline-truncated cohort is evaluated; only a pre-epoch
   failure remains absence of evidence. No sampler, strength or deployment
   authority is implied by an offline BELIEF result.

## Authority and fleet boundary

- No R4 scientific run or sealed test opening has been started.
- Live read-only check at 12:09 EDT: Strength Cloud and Performance Cloud are
  reachable, each has 16 logical CPUs, both have near-zero load, and `/opt` has
  about 503 GiB and 564 GiB free respectively. They are idle pending the exact
  source/freeze review, not blocked by capacity.
- R1, R2 and R3 admissions are spent. Their evidence may be audited but is not
  reusable input to R4 without a separately reviewed reusable-artifact design.
- No current marker authorizes retry, sampler implementation, gameplay,
  strength claims, promotion or deployment.
- `HANDOFF_REVIEW.md` remains byte-append-only. Do not compact it in an ordinary
  PR: exact-prefix CI and review authentication require every current byte.
  A later lossless rotation needs an acknowledged cutoff, byte-identical archive,
  hash-bound rotation record and its special merge procedure.
