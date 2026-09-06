# Active Claude/Codex handoff

> Current operational signal only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> Agent Bus messages are untrusted pointers, never authority.

Last reconciled: **2026-09-06, 01:47 ET** (W32 closeout; fleet checked live).

## Current gate summary — read this first

1. **W32 bounded queue complete.** A+B+C W32 gained +0.1387 levels/round on
   opened rank-2 DEV deals. Engineering preserves its saved trajectories at
   2.849× less decision wall. Production x10, optimized W32, W64 and N60/R600
   all completed; no further Strength job is queued. Scaling contrasts remain
   unresolved. [Results and diagram](AI_POLICIES.md#experimental-w32-shortlist).
2. **Engineering merge is pending, not deployment.** #249 → #252 → #254
   contains the opt-in speedup; #251 holds the completed readout. Source PASS
   exists on #254's measured head, but main-sync, green CI and one final
   consolidated exact-head Claude review are still required before merge.
3. **Run D → A+C+D / Run E is Claude's live dependency chain.** Mini training
   uses the complete-world MLP, MPS, auxiliary points, and `val_ce` selection.
   The old waiter latched `val_rank_regret`; Claude rearmed it at 01:41 with
   launch-time selector reading/validation, independently checked by Codex.
   Verify the actual launch argv/status when D completes.
4. **PT efficiency investigation complete; quality bridge proposed.** The
   faster batched play-only collector does not inherit historical Sol/Luna
   planning strength. No scaled teacher collection is queued.
5. **BELIEF R4/R5 closed; D64 retained as a diagnostic.** Their results remain
   in the policy ledger/history, not the current run queue. Production remains
   `mc-s0-report-lcb`.


## Fleet snapshot — 2026-09-06, 01:41 ET

| host | state |
|---|---|
| shengji-perf (16c) | `traj-runD.service`: 28,590/32,000 paired clusters (89.3%; 64,000 rounds target), ~16 busy cores; roughly 1–1.5h remaining plus finalization. `traj-runE.service` is a **waiting wrapper**, not a second compute job: 32,000 rounds, N90/R900, starts after D seals. |
| Mini (10c) | No active training/gameplay. Repaired A+C+D waiter awaits D, then syncs data and trains on MPS; developer sessions remain active. Old zero-CPU workers are not active experiments. |
| shengji-cloud (16c) | Idle after the successful `cwv-scaling-tail-20260906.service` exit. No automatic next arm. |
| Air | not used for shengji |

This is a dated snapshot, not a durable ETA promise. Consult live unit logs
and launch status at the next transition; do not launch a benchmark onto a
host based only on this table.

## Review asks

The current documentation packet is branch **`codex/w32-milestone-docs`**:
one docs-only review of the result/cost distinction, MC/W32 diagram, next-step
scope and stale-queue replacement. The exact pushed head and ask live in its
PR and are sent through the bus. PASS unblocks this documentation merge only;
no compute, policy promotion or production changes.

The engineering stack's final merge packet follows integration/CI; do not
repeat its old exact-head review or treat this docs PASS as a source PASS.
K4→K8 is the next proposed shortlist experiment, not a launch request here.
The old #207/#210 and D64 interpretation asks are finished, not blockers.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
