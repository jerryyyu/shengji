# Active Claude/Codex handoff

> This file is only the current queue. Historical detail belongs in Git history,
> `HANDOFF_REVIEW.md`, and `docs_archive/`. A request not listed here is not an
> active Claude review request.

Last reconciled: 2026-08-16 09:49 EDT.

## Immediate objective

Carry BELIEF-V1 V2 to one runnable immutable freeze with the two remaining
sound review boundaries:

1. one exact-freeze review after the qualified-host measurements populate the
   otherwise unknowable host/runtime/deadline hashes; and
2. one terminal review after the one-shot sealed result exists.

There are no per-stage capture, REF-C, input-index, device, cohort, calibration,
or progress reviews between those boundaries.

## Current review queue — empty while the freeze is built

No Claude review is currently requested. PR #119 exact head
`c011773e15ef362e149f8360eece6f9fc8901eaa` passed at canonical ledger
`17ecdf3`; do not re-review PR #117, #118, or #119.

Codex is running the final exact-source, score-free capacity/deadline
measurements on the qualified 16-CPU host. The next and only review request is
the canonical immutable-freeze JSON after those host-specific hashes and caps
exist. There is no receipt-by-receipt or stage-by-stage review in between.

## Current operational truth

- PR #117 exact head `1a0c9c8` passed and merged as main `08c0502`. Its review
  item is closed; do not re-review it.
- V1 capture and REF-C completed, but both training cohorts exceeded the frozen
  eight-hour cap and were stopped before calibration/test. Its admission is
  spent; no V1 model, null, terminal, or strength result exists. Never resume
  or reuse those partial models.
- PR #118 source at exact `bc44869` is fully reviewed and merged as main
  `6b3611a8`. PR #119 exact child `c011773` has source PASS `17ecdf3`; its only
  delta repairs the real deadline-observer callback shape and adds the
  full-round witness that fails on the parent with the production error.
- `shengji-cloud` is clean/root-owned and detached at exact reviewed
  `c011773`. Its fresh 416-round score-free preflight is running on all 16
  CPUs. The earlier `bc44869` preflight remains planning evidence only because
  the freeze requires the final execution Git identity.
- No V2 evidence namespace has been initialized and no production V2 capture,
  REF-C, training, calibration, or test job is running.
- A powered host is not execution authority. After source PASS, use a qualified
  host with at least 16 logical CPUs only for the bounded score-free measurements
  needed to construct the freeze.
- Python/Torch remain staged outside the cloud checkout with the rebuilt
  compiled x86 engine. `shengji-perf` is powered off or unreachable.
- PR #116 remains Codex's independent performance-review item, not a Claude
  queue item and not a blocker for this consolidated review.
- The Claude queue is empty until the immutable freeze is published.
  Superseded PR #117/118/119 prompts and old strength-lane queues are
  historical.

## Current freeze-construction steps

1. Finish the exact-`c011773` 416-round capacity preflight and the
   reference/training deadline probe using candidate `cpu`.
2. Bind the already-regenerated exact-`c011773` scan/registry and derive the
   resource caps mechanically from the reopened receipts.
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
