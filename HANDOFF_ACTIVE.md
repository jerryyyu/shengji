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

1. **Value V2 D64 sealed (tier i).** Up-front pipeline review PASSed at
   `c4b8f7e8` (ledger `ca459e14`). Same-root recovery at exact source
   `11c438396b46ef35fbeb9084e0674c0f5950e3e0` sealed route
   `D64_DEV_SEALED`; the exact-source reopener succeeds and systemd reports a
   successful exit. Terminal file SHA-256 is `c9ba457471cdd9a06c4e59116ec67825d5235bb81d3a3ca2fcfe1b2a87286e72`.
   On 12 natural audit deals, RPS improvement was `+0.006400834` with interval
   `[+0.002789151,+0.010361512]` and 4/4 positive members, while scalar
   absolute-error improvement was `-0.178319`, paired action-sensitivity
   improvement was `-0.045395`, and selected-action utility was an
   inconclusive `+0.0625` (`[-0.21875,+0.375]`). This is distribution-shape
   learning without a calibrated value/action result. The 256-slot ledger and
   255 retained realizations remain coverage-audit evidence only, not a D256
   training-data recipe; the one missing slot will not be completed.
2. **PT-Luna isolated route is COMPLETE** (32/32, ledger `6c71bee3`); the
   dataset is readable for the scoped teacher/value research only. Collection
   is closed.
3. **BELIEF R4 is terminal, R5 closed.** No belief compute unless the
   oracle-belief ceiling screen is positive.
4. **Next asks in order:** D64 interpretation; oracle-value and
   oracle-belief ceiling screens; Luna disagreement analysis; V2 Luna
   fine-tune; search-policy variants through the RLCB paired harness.


## Fleet — 2026-09-04

| host | state |
|---|---|
| shengji-perf (16c) | D64 sealed and exact-source-reopened; service exited successfully; currently idle |
| Mini (10c) | idle for research; Codex tmux `codex-1`; pid 96175 is Jerry's dev server |
| shengji-cloud (16c) | idle |
| Air | not used for shengji |

## Review asks

One compact D64 interpretation review may now read the sealed terminal. Exact
recovery head `11c43839` passed 688/688 full Value V2 tests and 47/47 Linux
recovery tests; the exact-source terminal reopener also passes. The review is
interpretive only: all terminal authority is false. Do not request or launch
D256 slot completion/training.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
