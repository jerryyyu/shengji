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
3. **BELIEF R4 is terminal, R5 closed.** No belief compute unless a separate
   oracle-belief probe shows a gain worth reopening.
4. **Next asks in order:** finish and integrate the main-based trajectory
   generator; interpret the running oracle probe extensions; port the minimal
   Value learning core onto current main; then use trajectory data at scale
   with Luna outcomes reserved for fine-tuning/evaluation. The D64
   interpretation review is complete at canonical ledger commit `784569ba`.


## Fleet — 2026-09-04

| host | state |
|---|---|
| shengji-perf (16c) | trajectory self-play Run A active as of 17:07Z (`traj-runA.service`, 16 workers); D64 sealed and exact-source-reopened |
| Mini (10c) | no active research compute as of 17:07Z; Codex/Claude development sessions remain active |
| shengji-cloud (16c) | oracle heuristic probe run2 active; run3 wide-ballot probe queued behind it as of 17:07Z |
| Air | not used for shengji |

## Review asks

The D64 interpretation review is complete at `784569ba`: pipeline proof PASS,
learning signal weak on 12 audit deals, and all authority false. The current
review asks are the repaired documentation-only milestone PR #210 and the
repaired main-based trajectory generator PR #207. Do not request or launch
D256 slot completion/training.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
