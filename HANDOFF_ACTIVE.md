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
   `c4b8f7e8` (ledger `ca459e14`). The first end-to-end D64 dev run is live on
   Perf: unit `value-v2-dev-d64-c4b8f7e8-r1.service`, root
   `/root/value-v2-dev-d64-c4b8f7e8-r1`. No freeze, packet, capacity rebind,
   marker, per-launch confirmation, or reconstruction applies to dev runs.
   Private artifacts and evaluations stay closed until `terminal.json` seals
   (route `D64_DEV_SEALED`); then one interpretation review, then D256.
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
| shengji-perf (16c) | `value-v2-dev-d64-c4b8f7e8-r1.service` — D64 dev run, width-8 population, resumable |
| Mini (10c) | idle for research; Codex tmux `codex-1`; pid 96175 is Jerry's dev server |
| shengji-cloud (16c) | idle |
| Air | not used for shengji |

## Review asks

None open. The next ask is the D64 interpretation review once
`/root/value-v2-dev-d64-c4b8f7e8-r1/terminal.json` seals. Ceiling screens and
the Luna disagreement analysis are tier i/ii and need no pre-review.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
