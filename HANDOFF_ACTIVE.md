# Active Claude/Codex handoff

> This file is only the current queue. Historical detail belongs in Git history,
> `HANDOFF_REVIEW.md`, and `docs_archive/`. A request not listed here is not an
> active Claude review request.

Last reconciled: 2026-08-16 08:47 EDT.

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

### P0 — PR #118 zero-decision human-group delta

The consolidated source review at parent `86aa3b70` is closed with PASS and
zero blockers (ledger `78325580`). Do not repeat it. Review only:

- PR: `https://github.com/jerryyyu/shengji/pull/118`
- exact child: `7cc193077cccf20abfdb54612f51448bcd6be223`
- exact reviewed parent: `86aa3b70cbe9672a2ee82c19e9d0583bae530756`
- delta: 5 files, +131/-7
- prompt/comment: `https://github.com/jerryyyu/shengji/pull/118#issuecomment-5307508755`

The frozen H0 inventory contains 20/48 legitimate zero-decision human groups.
Verify in one delta pass that they remain source/inventory/split-bound empty
capture and REF-C manifests, contribute zero scoring rows, and report one
honest `0/1` to `1/1` group-stage progress unit. Nonempty groups must retain
exact decision/artifact/scoring bindings. No gameplay, model/training,
test-opening, registry-policy, or authority semantics changed.

Exact child evidence: focused 52 passed; pure 380 passed + 2 skipped; strict
compiled 382 passed; seed scan SHA `53e9c293…fc89`; registry SHA
`175711fb…a41`, 5,415/5,415 classified, 13,312 seeds, zero collisions, all
authority false. Return one DELTA PASS or one DELTA HOLD with every blocker.

A PASS preserves only the parent's authority for qualified score-free host
measurements and immutable-freeze construction. It does not authorize pipeline
execution; the populated freeze still needs its own PASS.

## Current operational truth

- PR #117 exact head `1a0c9c8` passed and merged as main `08c0502`. Its review
  item is closed; do not re-review it.
- V1 capture and REF-C completed, but both training cohorts exceeded the frozen
  eight-hour cap and were stopped before calibration/test. Its admission is
  spent; no V1 model, null, terminal, or strength result exists. Never resume
  or reuse those partial models.
- PR #118 is source/design only. Parent `86aa3b7` passed; exact child `7cc1930`
  is the sole delta review above. No V2 evidence namespace has been initialized
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
- No other Claude review request is open. Superseded PR #117 and PR #118 parent
  prompts and old strength-lane queues are closed historical records.

## Next steps after final PR #118 child PASS

1. On one available >=16-logical-CPU host, reproduce the exact preflight,
   runtime/native/boot, candidate-device, memory, and deadline receipts at
   final reviewed child head `7cc1930`.
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
