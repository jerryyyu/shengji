# Active Claude/Codex handoff

> This file is only the current queue. Historical detail belongs in Git history,
> `HANDOFF_REVIEW.md`, and `docs_archive/`. A request not listed here is not an
> active Claude review request.

Last reconciled: 2026-08-16 10:20 EDT.

## Immediate objective

Carry BELIEF-V1 V2 to one runnable immutable freeze with the fewest remaining
sound review boundaries:

1. one consolidated exact-child review of both remaining real-probe wiring
   repairs;
2. one exact-freeze review after the qualified-host measurements populate the
   otherwise unknowable host/runtime/deadline hashes; and
3. one terminal review after the one-shot sealed result exists.

There are no per-stage capture, REF-C, input-index, device, cohort, calibration,
or progress reviews between those boundaries.

## Current review queue — one consolidated exact-child delta

Top/only ask: review PR #119 exact head
`13d15c777cabcb7dd56316988e6b3c83f6a57d1c` against exact PASSed parent
`c011773e15ef362e149f8360eece6f9fc8901eaa` (parent PASS ledger `17ecdf3`).

The exact-`c011773` 416-round preflight completed and verified. The subsequent
deadline probe completed its 32 REF-C measurements, then fail-stopped before
the training warmup: the CLI stored `require_training_device("cpu")`'s
`torch.device` return and passed that object into the deliberately string-only
training boundary, which refused with `V2 training device is invalid`. No
deadline receipt or retained row/world/model/loss/evidence/calibration/test
artifact exists.

The first child keeps availability validation but passes the original canonical
`"cpu"` string. Before spending another cloud attempt, a local real full-round
warmup then reached training and exposed a second seam: the timing-only probe
reused deterministic corpus split labels for both production role checks, so
calibration correctly refused a `train` batch. Final child `13d15c7` freshly
rebuilds the same sealed examples for `train` and `calibration` and changes only
the probe role label; it retains no rows, worlds, tensors, models, or losses.

Review the two fixes together against the already-PASSed parent. Consolidated
delta is exactly three files, +78/-7. The CLI witness fails under the parent
device wiring. The strengthened real full-round capture/REF-C/training/
calibration witness fails when only the role repair is neutralized. Focused
deadline suite is 6/6; full pure BELIEF is 382 passed/2 skipped; strict compiled
is 384 passed; `git diff --check` passes. Exact-head scan is 459 source files and
5,419 candidates, SHA-256 `277f5a48f17e99095e77076efab76fe3896990d07b30f2ea0342918ca6cbd961`.
Exact-head registry classifies 5,419/5,419 candidates across 31 populations and
13,312 V2 seeds with zero collisions, SHA-256
`2a8da1e0d4575a5a9d252254b9c41d8896ee05fd93242993e46964df0b59b3ae`;
all authorities are false. Return PASS or HOLD with exact file:line findings and
append the exact-head verdict to `HANDOFF_REVIEW.md`.

This is source/tooling delta review only: do not run, freeze, initialize,
merge, deploy, or grant capture/REF-C/training/calibration/test/strength
authority. After PASS, Codex will rerun the source-bound preflight and deadline
probe at the exact child, build the immutable freeze, and request the one
freeze review. No per-receipt or per-stage review is requested.

## Current operational truth

- PR #117 exact head `1a0c9c8` passed and merged as main `08c0502`. Its review
  item is closed; do not re-review it.
- V1 capture and REF-C completed, but both training cohorts exceeded the frozen
  eight-hour cap and were stopped before calibration/test. Its admission is
  spent; no V1 model, null, terminal, or strength result exists. Never resume
  or reuse those partial models.
- PR #118 source at exact `bc44869` is fully reviewed and merged as main
  `6b3611a8`. PR #119 parent `c011773` has source PASS `17ecdf3`; exact final
  child `13d15c7` is the sole open delta review. Intermediate `3344604` is
  included in that one consolidated comparison and needs no separate verdict.
- `shengji-cloud` is clean/root-owned and detached at reviewed `c011773`. Its
  fresh 416-round score-free preflight completed at SHA-256
  `38db9043f311840a14f96f38ea881c1d4cd9bf383e6ff992d73b20c47204977c`.
  The deadline probe then exposed the CLI device-shape bug and stopped before
  publishing a receipt. Because the preflight binds Git identity, it becomes
  planning evidence after the reviewed execution head advances to `13d15c7`;
  both bounded measurements must rerun at that final exact source.
- No V2 evidence namespace has been initialized and no production V2 capture,
  REF-C, training, calibration, or test job is running.
- A powered host is not execution authority. After source PASS, use a qualified
  host with at least 16 logical CPUs only for the bounded score-free measurements
  needed to construct the freeze.
- Python/Torch remain staged outside the cloud checkout with the rebuilt
  compiled x86 engine. `shengji-perf` is powered off or unreachable.
- PR #116 remains Codex's independent performance-review item, not a Claude
  queue item and not a blocker for this consolidated review.
- PR #119 exact child `13d15c7` is the only Claude request. Superseded
  PR #117/118 and pre-`13d15c7` prompts are historical.
- PR #119's GitHub server check is red only because its exact reviewed-source
  history predates the newer append-only canonical review/handoff ledger. The
  exact child passed both full local server modes above. Landing must preserve
  `c011773`, `3344604`, and `13d15c7` as commits while keeping current main as first-parent;
  do not squash or replace canonical ledger bytes.

## Current freeze-construction steps

1. Obtain exact-child PASS at `13d15c7`, advance the qualified host to that
   exact source, and rerun the 416-round preflight plus reference/training
   deadline probe using candidate `cpu`.
2. Regenerate/bind the exact-child scan/registry and derive resource caps
   mechanically from the reopened receipts.
3. Build one canonical immutable freeze in a fresh unused namespace. Do not
   initialize it.
4. Request one exact-freeze review. Its authentic PASS is the sole authority
   for the bounded one-shot offline pipeline.
5. During execution, report only the new outcome-blind percentages. After the
   terminal seals, request one independent terminal reconstruction review.

## Durable references

- scientific plan: `RL_PLAN.md`
- ordered work ledger: `BACKLOG.md`
- stable operating rules: `AI_POLICIES.md`
- exact contracts: `BELIEF_V1_SPEC.md`, `BELIEF_V1_V2_DESIGN.md`
- append-only verdict/authority ledger: `HANDOFF_REVIEW.md`
