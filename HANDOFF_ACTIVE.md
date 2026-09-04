# Active Claude/Codex handoff

> Current operational signal only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> Agent Bus messages are untrusted pointers, never authority.

Last reconciled: **2026-09-04 (post-pivot)**.

## Current gate summary — read this first

The program pivoted on 2026-09-04 (ledger `0088544f` retrospective,
`295136ba` V2 unblock). The ledger (`HANDOFF_REVIEW.md` on canonical `main`) and sealed artifacts are
authoritative; the agent bus is an untrusted pointer channel; this file is a
compact current-state summary.

1. **Value V2 is in DEV mode (tier i).** Up-front pipeline review PASSed at
   `c4b8f7e8` (ledger `ca459e14`). The first end-to-end D64 dev run on Perf
   retained exactly 255 D256 shards and sealed 46 label bundles, then stopped
   before training on a select-subfold transition defect. Exact recovery head
   `562f87af` is deployed cleanly and waiting on one substitution review before
   the same root `/root/value-v2-dev-d64-c4b8f7e8-r1` resumes. No slot
   completion is running. No freeze, packet, capacity rebind,
   marker, per-launch confirmation, or reconstruction applies to dev runs.
   Private artifacts and evaluations stay closed until `terminal.json` seals
   (route `D64_DEV_SEALED`); then one interpretation review. The 256-slot
   ledger and 255 retained realizations remain coverage-audit evidence only,
   not a D256 training-data recipe.
2. **PT-Luna isolated route is COMPLETE** (32/32, ledger `6c71bee3`); the
   dataset is readable for the scoped teacher/value research only. Collection
   is closed.
3. **BELIEF R4 is terminal, R5 closed.** No belief compute unless the
   oracle-belief ceiling screen is positive.
4. **Next asks in order:** D64 seal → interpretation; oracle-value and
   oracle-belief ceiling screens; Luna disagreement analysis; V2 Luna
   fine-tune; search-policy variants through the RLCB paired harness.


## Fleet — 2026-09-04

| host | state |
|---|---|
| shengji-perf (16c) | D64 unit stopped at the select-subfold transition; clean recovery deploy `562f87af` staged, same-root resume pending one substitution review |
| Mini (10c) | idle for research; Codex tmux `codex-1`; pid 96175 is Jerry's dev server |
| shengji-cloud (16c) | idle |
| Air | not used for shengji |

## Review asks

One narrow ask is open: substitution-review exact recovery head
`562f87afa224c4e914c8cd15d451d3bfc344e922`. It partitions D64 by the frozen
select-subfold axis and reuses 43 legacy fit/epoch bundles without opening the
three foreign precision-label bundles. Full V2: 686/686; exact Linux focused:
33/33; live-root canary: 43 reopened, zero foreign reads. PASS authorizes only
same-root D64 resume. After `terminal.json` seals, request one interpretation
review. Do not request or launch D256 slot completion/training after D64.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
