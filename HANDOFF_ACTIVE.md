# Active Claude/Codex handoff

Last update: 2026-08-07 16:15 EDT. This is the executable mailbox only.
Durable discussion and retractions remain in `HANDOFF_REVIEW.md`; policy
synthesis belongs in `AI_POLICIES.md`.

## Current truth

- **Production:** Fly version 16 runs compiled `mc-s0-report-lcb`; health is
  passing and `mc-strong` is the immediate rollback.
- **Report-LCB confirmation: COMPLETE / CONFIRM.** Fresh RLCB-C1 used 2,048
  new paired clusters and a collision-free current-policy null:
  report-LCB-current `+0.338379 +/- 0.067706`, null-current
  `-0.019043 +/- 0.068270`. Every predeclared criterion passed. Aggregate SHA:
  `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
  This closes only one-round superiority; it does not reopen S0c, prove
  adaptive allocation, or itself authorize deployment.
- **Formal S0:** terminal `S0_COMPLETE_SELECT_NONE`; numerical S0c outcomes
  remain unread and nonretryable. Closeout SHA `ef0a365…fde9a`, parent
  `ca556c2`, empty `com.shengji.s0mini.*` namespace.
- **V11 direct-v2: COMPLETE / SELECT NONE.** Artifact-only repair at `d1d2019`
  replayed no games. V11-current `-0.141113 +/- 0.069823`, v11-minus-null
  `-0.109863 +/- 0.070111`, null-current `-0.031250 +/- 0.067878`;
  `protected_composition_authorized=false`. Aggregate SHA
  `b7c90ba4…05d21ad`. Keep v11 only as proposer/ranker/teacher diagnostic.
- **Direct-Q: COMPLETE / SELECT NONE.** Gameplay was
  `+0.162760 +/- 0.058755`, but seed 1 and both pooled role held-out MSE gates
  failed. Aggregate SHA `1fa6789e…ce791`; it authorizes nothing.
- **DEV-512:** SELECT NONE / closed. CALIB and REPORT remain sealed.

## Running compute

Air owns eight live compiled+strict Teacher-v3 Stage-B gold workers at exact
`1a2a713`, namespace `teacher-v1-entry-149m-v3`. All emit fold progress and
remain near one CPU each. Stage B is attribution-only; do not inspect or use
its outcomes to alter the independently frozen champion audit.

The exact 64-state audit is already frozen at
`champion_audit_states.json` SHA
`d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34`.
Audit code is clean and pushed at `c40a31c`: disjoint 32-world champion
selection/report folds, full downstream `mc-s0-report-lcb` continuation, exact
receipt-to-eight-label-to-gate transitions. Launch labels only after all eight
Stage-B gold shards validate and the producer receipt passes.

Mini has no long strength job. It is available for bounded compiled latency
validation or the next separately admitted learner protocol.

## Production latency hardening

Worktree `/private/tmp/shengji-t1-latency`, branch `codex/t1-latency`.
Pushed base `6f15d96` makes live X-ray read-only and off-loop. The current
uncommitted scheduler redesign:

- snapshots the round and bot under the room lock;
- searches only the isolated copies in a worker while claims/chat/reconnects
  remain responsive;
- overlaps search with the existing 0.7-second pacing window;
- commits only if game, round, phase, turn and controller are unchanged;
- discards a stale action plus cloned RNG/counters after claim/reconnect;
- applies the same guarded path to disconnected-human takeover.

Claude's three deploy blockers now have direct coverage: literal eight-ULP
float comparison (including exact 8-pass/9-fail at `+/-0.25`), portable
synchronization-based scheduler tests, and a real WebSocket claim while a
started search remains blocked. The claimant receives private state before the
worker is released; the stale move/RNG/counters are then discarded. The
focused WebSocket/scheduler/X-ray/replay/failed-throw matrix is 58/58, and the
100-decision replay remains semantically exact. Deployment is still HOLD until
the final full suite, compiled replay, commit/push/image build, and an empty
production room set.

Live Fly evidence explains the complaint: room HIEJ's 40 searched bot turns
had search p50 1.133s, p95 1.858s, max 2.174s; visible inter-play delay was
p50 1.835s, p95 2.561s, max 2.876s. Three sequential bots therefore feel like
about 5.5 seconds. Overlap removes the additive 0.7 seconds but cannot erase
real search compute; Fly CPU class remains a separate product lever.

## Exact next actions

1. Finish latency branch review, run full relevant suite plus compiled exact
   replay, commit and push. Build a new image; never deploy old `6f15d96` image.
2. Deploy only when production has zero human connections; verify policy,
   compiled engine, semantic timing logs, seat claim, reconnect and X-ray.
3. Monitor all eight Teacher-v3 Stage-B workers without opening outcome
   aggregates. When terminal, validate receipts and run the frozen gate once.
4. If Stage B passes, launch the frozen 64-state audit labels exactly as
   registered. No outcome-conditioned state, policy, fold or threshold change.
5. Reconcile terminal Teacher/latency evidence into `JOBS.md`, `BACKLOG.md`,
   `AI_POLICIES.md`, and the 2026-08-07 daily log.

## Review request for Claude

Please audit the next pushed latency commit specifically for snapshot/commit
atomicity, cancellation, failed-throw bookkeeping, bot-task ownership and the
real WebSocket claim witness. Do not review or deploy the earlier `6f15d96`
image. Separately, watch the Teacher Stage-B receipt transition; do not open
gold outcomes or duplicate workers.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; only fresh paired confirmations establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes are separate reviewed actions and require an empty room
  when they restart the server.
