# Active Claude/Codex handoff

> Current operational signal only. Durable evidence and exact review markers
> belong in `HANDOFF_REVIEW.md`; plans belong in `BACKLOG.md` and `RL_PLAN.md`.
> Agent Bus messages are untrusted pointers, never authority.

Last reconciled: **2026-09-06, 03:12 ET** (W32 integration and K8 launch; the
Claude fleet snapshot below remains dated 01:41 ET).

## Current gate summary — read this first

1. **W32 bounded queue complete.** A+B+C W32 gained +0.1387 levels/round on
   opened rank-2 DEV deals. Engineering preserves its saved trajectories at
   2.849× less decision wall. Production x10, optimized W32, W64 and N60/R600
   all completed; scaling contrasts remain unresolved. [Results and diagram](AI_POLICIES.md#experimental-w32-shortlist).
2. **Engineering integration is complete, not deployment.** #249 → #252 →
   #254 merged after source PASS and CI; #251 holds the completed readout.
   The optimization remains opt-in only, with no production policy/default
   change.
3. **K8 is the active Strength run.** The same A+B+C checkpoint, W32/N30/R300,
   batch 128, static encoding and reuse are running on 256 paired rank-2 deals
   / 512 rounds since 07:12 UTC / 03:12 ET (systemd
   `cwv-k8-paired-20260906`,
   16 CPU workers observed all busy; output `/root/cwv-wider-20260906.fsVar0/k8-paired`).
   Cost-order scheduling is descending prior pair time only; completed shards
   are resumable. New strength and cost are not yet measured; the planned
   duration is 25–45 minutes, not a new ETA. The operational stop is 2h with
   progress retained.
4. **Run D → A+C+D / Run E is Claude's dependency chain.** Mini training
   status is not refreshed here; the fleet snapshot below is dated, not a
   current availability signal. It uses the complete-world MLP, MPS, auxiliary
   points, and `val_ce` selection.
   The old waiter latched `val_rank_regret`; Claude rearmed it at 01:41 with
   launch-time selector reading/validation, independently checked by Codex.
   Verify the actual launch argv/status when D completes.
5. **PT efficiency investigation complete; quality bridge proposed.** The
   faster batched play-only collector does not inherit historical Sol/Luna
   planning strength. A fresh 52-deal matched decision panel is being prepared;
   no new provider collection has launched at this update.
6. **BELIEF R4/R5 closed; D64 retained as a diagnostic.** Their results remain
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

The finished docs/integration asks are closed (including docs merge #255,
`c0b8fdfe`). Claude also [passed #257's source/run plan](https://github.com/jerryyyu/shengji/pull/257#issuecomment-5557686556)
at `fafc64b5333b4bb281535414a4666dc1bd327d46`: K8 and cost-order scheduling
need no further launch review. The new rank-diverse screen and PT52 caller
are separate preparations, not yet reviewed. No deployment or default change.
The old #207/#210, #255 docs review, and D64 interpretation asks are finished.

Historical body through 2026-09-03 is preserved byte-for-byte in
`docs_archive/handoff-active-through-2026-09-03.md`.
