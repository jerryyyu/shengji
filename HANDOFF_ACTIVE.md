# Active Claude/Codex handoff

> This file is only the current queue. Historical detail belongs in Git history,
> `HANDOFF_REVIEW.md`, and `docs_archive/`. A request not listed here is not an
> active Claude review request.

Last reconciled: 2026-08-16 09:30 EDT.

## Immediate objective

Carry BELIEF-V1 V2 to one runnable immutable freeze with the fewest sound
review boundaries:

1. one narrow exact-child delta review of PR #119, required because the first
   real deadline probe exposed an unwitnessed callback-shape bug after PR #118;
2. one exact-freeze review after the qualified host measurements populate the
   otherwise unknowable host/runtime/deadline hashes; and
3. one terminal review after the one-shot sealed result exists.

There are no per-stage capture, REF-C, input-index, device, cohort, calibration,
or progress reviews between those boundaries.

## Current review queue — one exact-child delta

Top/only ask: review PR #119 exact head
`c011773e15ef362e149f8360eece6f9fc8901eaa` against exact parent
`bc448695ce50e85871c32760c06bdceba085915d`.

The qualified-host deadline probe stopped before producing any receipt because
`_capture_with_policies` passes `CorpusPairV1` to its observer while the probe
treated that argument as newline-terminated actor bytes. The child reopens
`pair.actor_bytes` and adds a real-full-round `_measure_coordinate` witness at
the wiring boundary. Audit exactly the two-file +33/-4 delta and prove the new
witness fails on the parent. Local validation is 381 passed/2 skipped pure and
383 passed strict-compiled; `git diff --check` passes. Return PASS or HOLD with
file:line findings and append the exact-head verdict to `HANDOFF_REVIEW.md`.
This is tooling/source review only: do not run, freeze, initialize, merge,
deploy, or grant capture/REF-C/training/calibration/test/strength authority.

PR #118 exact head `bc448695ce50e85871c32760c06bdceba085915d`
has consolidated source PASS `78325580` plus exact corrected delta PASS
`1f4d351b`; zero blockers remain. Do not re-review either source packet.

After PR #119 PASS, Codex will merge/deploy the exact child to the measurement
host, rerun the deadline probe, and construct the immutable freeze. The next
request after that is one exact-freeze review; no per-receipt or per-stage
review is requested.

## Current operational truth

- PR #117 exact head `1a0c9c8` passed and merged as main `08c0502`. Its review
  item is closed; do not re-review it.
- V1 capture and REF-C completed, but both training cohorts exceeded the frozen
  eight-hour cap and were stopped before calibration/test. Its admission is
  spent; no V1 model, null, terminal, or strength result exists. Never resume
  or reuse those partial models.
- PR #118 source at exact `bc44869` is fully reviewed and merged as main
  `6b3611a8`. The final-runtime 416-round score-free preflight completed and
  verifies at SHA-256 `a70929c3202b88544090b6ffbc4d291769becc88214bb17b20c13b33142f64cc`.
  The deadline probe exposed PR #119's narrow observer bug and stopped before
  producing a receipt. No V2 evidence namespace has been initialized and no V2
  capture, REF-C, training, calibration, or test job is running.
- A powered host is not execution authority. After source PASS, use a qualified
  host with at least 16 logical CPUs only for the bounded score-free measurements
  needed to construct the freeze.
- `shengji-cloud` is detached at exact reviewed `bc44869`, clean/root-owned,
  with Python/Torch staged outside the checkout and the rebuilt compiled x86
  engine. Advance it only after PR #119 exact-head PASS.
  `shengji-perf` is powered off or unreachable.
- PR #116 remains Codex's independent performance-review item, not a Claude
  queue item and not a blocker for this consolidated review.
- PR #119 is the only open Claude request. Superseded PR #117/118 prompts and
  old strength-lane queues are historical.

## Current freeze-construction steps

1. Obtain exact-child PASS on PR #119 and advance the same host to that exact
   source; rerun the reference/training deadline probe using candidate `cpu`.
2. Regenerate/rebind the exact scan/registry if any source byte changed; source
   drift instead requires a new consolidated source review.
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
