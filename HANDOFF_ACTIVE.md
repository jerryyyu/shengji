# Active Claude/Codex handoff

> This file is only the current queue. Historical detail belongs in Git history,
> `HANDOFF_REVIEW.md`, and `docs_archive/`. A request not listed here is not an
> active Claude review request.

Last reconciled: 2026-08-16 08:27 EDT.

## Immediate objective

Carry BELIEF-V1 V2 to one runnable immutable freeze with the fewest sound
review boundaries:

1. one consolidated exact-head source/design review of PR #118;
2. one exact-freeze review after the qualified host measurements populate the
   otherwise unknowable host/runtime/deadline hashes; and
3. one terminal review after the one-shot sealed result exists.

There are no per-stage capture, REF-C, input-index, device, cohort, calibration,
or progress reviews between those boundaries.

## Current review queue — exactly one Claude request

### P0 — PR #118 consolidated V2 execution-source review

- PR: `https://github.com/jerryyyu/shengji/pull/118`
- exact head: `86aa3b70cbe9672a2ee82c19e9d0583bae530756`
- exact merge base: `08c050209952edb1e5a2328b0545e4f643ffa4ff`;
  base branch is canonical `main`
- diff: 27 files, +2,951/-335; no `HANDOFF_REVIEW.md`, production, gameplay
  policy, or frozen evidence changes
- review mode: one consolidated PASS or one HOLD containing every blocker
  found in this pass; do not split performance, streaming, memory, telemetry,
  or design into separate review requests

Review these four surfaces together:

1. **CPU cohort execution.** Four persistent member workers share immutable
   batches while Torch intra-op work remains one thread. Fixed member order,
   all 8+8 members, optimizer independence, receipts, calibration losses, and
   portable checkpoint hashes must match the serial reference. MPS is not
   retained: the exact Mini diagnostic was CPU 2.978871292 s versus MPS
   17.306243501 s. Four workers were the measured resource-efficiency knee
   (48.8% lower epoch wall, +79.1% CPU); eight were faster but cost +129.4% CPU.
2. **Bounded streaming inputs.** The old materialized bridge projected about
   106.6 GiB before Python overhead on a roughly 30 GiB host. The new compact
   index must bind every source/schedule/row without opening test targets;
   device qualification and each epoch may retain only the current bounded
   batch. Reopeners must detect missing, extra, reordered, or mutated sources.
3. **Qualification and memory closure.** The 32-batch plan must include maximum
   decision count plus minimum/maximum active-label-density extremes, keep all
   qualification batches resident, and conservatively require measured
   per-process peak x exact concurrent cohort count to fit the host cap.
   Training and terminal receipts must independently reconstruct that bound.
4. **Outcome-blind progress.** Every long worker command must reach its real
   controller loop and emit canonical stderr-only completed/total units,
   basis-point percent, elapsed time, and ETA. It must not alter stdout or any
   evidence bytes, expose loss/score/selection/test/terminal outcome, regress
   or change totals, or grant retry/execution/strength/deploy authority.

Exact-head evidence:

- focused progress/controller/cohort/device: 51 passed;
- full BELIEF pure: 379 passed, 2 skipped;
- full BELIEF compiled/strict: 381 passed;
- `git diff --check`, clean tree, and isolated worker bootstrap: PASS;
- seed scan: 1,943,634 bytes, SHA-256
  `f2ffc1fa4482ed356c4c12c6728303833115054c15fda8b04dc544b0281740f4`;
- registry: 1,725,973 bytes, SHA-256
  `d2f75dd2f0d089fb4312e0e125276467e1257cb69022d93c5040ec57b85e76b6`;
  5,415/5,415 candidates classified, 140 explicit, 74 finite-population,
  31 populations, 13,312 V2 seeds, zero collisions; all capture, training,
  test, gameplay, strength, and deployment authority flags are false.

Return exactly:

1. `PASS` or `HOLD` at exact head `86aa3b7`;
2. every finding in one severity-ordered list with file:line and a concrete
   repair or proof request;
3. whether PASS permits only qualified score-free host capacity/device/deadline
   measurements and immutable-freeze construction; and
4. any host-populated freeze fields that must be checked in the next exact-
   freeze review.

A source PASS does **not** authorize initialization, capture, REF-C, training,
calibration, test opening, gameplay, strength claims, promotion, or deployment.
The populated freeze is a separate exact object and must PASS before execution.

## Current operational truth

- PR #117 exact head `1a0c9c8` passed and merged as main `08c0502`. Its review
  item is closed; do not re-review it.
- V1 capture and REF-C completed, but both training cohorts exceeded the frozen
  eight-hour cap and were stopped before calibration/test. Its admission is
  spent; no V1 model, null, terminal, or strength result exists. Never resume
  or reuse those partial models.
- PR #118 is source/design only. No V2 evidence namespace has been initialized
  and no V2 capture, REF-C, training, calibration, or test job is running.
- A powered host is not execution authority. After source PASS, use a qualified
  host with at least 16 logical CPUs only for the bounded score-free measurements
  needed to construct the freeze.
- Read-only 08:27 readiness probe: `shengji-cloud` is reachable with 16 logical
  CPUs, 32,078,280 KiB total / 31,248,492 KiB available memory, load 0.03, and
  zero matching belief/Shengji/pytest workers. `shengji-perf` is powered off or
  unreachable. Do not stage or run V2 on the available host before source PASS.
- PR #116 remains Codex's independent performance-review item, not a Claude
  queue item and not a blocker for this consolidated review.
- No other Claude review request is open. Superseded PR #117 prompts and old
  strength-lane queues are closed historical records.

## Next steps after PR #118 PASS

1. On one available >=16-logical-CPU host, reproduce the exact preflight,
   runtime/native/boot, candidate-device, memory, and deadline receipts at
   reviewed head `86aa3b7`.
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
