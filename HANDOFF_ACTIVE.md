# Active Claude/Codex handoff

> This file is only the current queue. Historical detail belongs in Git history,
> `HANDOFF_REVIEW.md`, and `docs_archive/`. A request not listed here is not an
> active Claude review request.

Last reconciled: 2026-08-16 09:05 EDT.

## Immediate objective

Carry BELIEF-V1 V2 to one runnable immutable freeze with the fewest sound
review boundaries:

1. one consolidated exact-head source/design review of PR #118;
2. one exact-freeze review after the qualified host measurements populate the
   otherwise unknowable host/runtime/deadline hashes; and
3. one terminal review after the one-shot sealed result exists.

There are no per-stage capture, REF-C, input-index, device, cohort, calibration,
or progress reviews between those boundaries.

## Current review queue — none while freeze inputs are built

PR #118 exact head `bc448695ce50e85871c32760c06bdceba085915d`
has consolidated source PASS `78325580` plus exact corrected delta PASS
`1f4d351b`; zero blockers remain. Do not re-review either source packet.

The next and only Claude request is one exact-freeze review after all
host/runtime/deadline/cap bytes exist. No intermediate preflight, deadline,
registry, V1 receipt, or freeze-construction review is requested.

## Current operational truth

- PR #117 exact head `1a0c9c8` passed and merged as main `08c0502`. Its review
  item is closed; do not re-review it.
- V1 capture and REF-C completed, but both training cohorts exceeded the frozen
  eight-hour cap and were stopped before calibration/test. Its admission is
  spent; no V1 model, null, terminal, or strength result exists. Never resume
  or reuse those partial models.
- PR #118 source at exact `bc44869` is fully reviewed. The 416-round score-free
  preflight started at 09:04 EDT on idle `shengji-cloud` using 16 overlapping
  workers. No V2 evidence namespace has been initialized and no V2 capture,
  REF-C, training, calibration, or test job is running.
- A powered host is not execution authority. After source PASS, use a qualified
  host with at least 16 logical CPUs only for the bounded score-free measurements
  needed to construct the freeze.
- `shengji-cloud` is detached at exact reviewed `bc44869`, clean/root-owned,
  with the frozen Python/Torch environment and rebuilt compiled x86 engine.
  `shengji-perf` is powered off or unreachable.
- PR #116 remains Codex's independent performance-review item, not a Claude
  queue item and not a blocker for this consolidated review.
- No Claude review request is open until the immutable freeze exists.
  Superseded PR #117/118 prompts and old strength-lane queues are historical.

## Current freeze-construction steps

1. Finish and verify the fresh 416-round preflight at reviewed `bc44869`, then
   run the same-host reference/training deadline probe using candidate `cpu`.
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
