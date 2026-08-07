# Active Claude/Codex handoff

Last update: 2026-08-07 16:55 EDT. This is the executable mailbox only.
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
`1a2a713`, namespace `teacher-v1-entry-149m-v3`. All remained near one CPU
after about 2h10, with zero final gold shards. Stage B is attribution-only; do
not inspect or use its outcomes to alter the independently frozen champion
audit.

The exact 64-state audit is already frozen at
`champion_audit_states.json` SHA
`d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34`.
Audit code is clean and pushed at `9b2c8ab`: disjoint 32-world champion
selection/report folds, full downstream `mc-s0-report-lcb` continuation, exact
receipt-to-eight-label-to-gate transitions, and a literal actor/rollout/ballot/
engine lock. An independent Air worktree at that exact commit carries the exact
frozen state asset and compiled engine. Real outcome-blind preflight reports no
transition, execution-lock, state-self or state-lock problems and proves live
lock equality. Preflight caught and corrected an initially mistranscribed
ballot digest before any audit label existed; the regression now derives the
real ballot instead of mocking the literal against itself. Launch labels only
after all eight Stage-B gold shards validate and the producer gate passes.

Mini has no long strength job. It is available for bounded compiled latency
validation or the next separately admitted learner protocol.

## Production latency hardening

Worktree `/private/tmp/shengji-t1-latency`, branch `codex/t1-latency`, clean
and pushed at release head `b315e91` (scheduler `ff784a8`). The completed
scheduler redesign:

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
worker is released; the stale move/RNG/counters are then discarded. X-ray now
copies both round and bot under the room lock and releases it before search.
A legitimate failed throw records both the attempted cards and engine-forced
component without crashing after state mutation. The focused matrix is 61/61.
The final native replay passed 100/100 exact decisions with search p50 0.164s,
p95 0.339s and max 0.379s; every gate passed and projected uncontended turns
were 0.7s. The broad branch suite was 915 passed, 3 skipped and 6 expected
worktree/provenance refusals; no behavior test failed.

Deployment is **EMPTY-ROOM HOLD**, not a code hold. At 16:50 production had
one room and one connected human: srig in HIEJ. The exact release
image is already built and pushed as
`registry.fly.io/shengji:latency-b315e91`, manifest SHA-256
`dbc978028de1b9bd84dad00bb59e83f9ba6feac46e5d1ecc95ef3c2150c2426a`.
Never deploy the older `6f15d96` image; restart only after a new peek proves
zero connected humans.

Live Fly evidence explains the complaint: room HIEJ's 40 searched bot turns
had search p50 1.133s, p95 1.858s, max 2.174s; visible inter-play delay was
p50 1.835s, p95 2.561s, max 2.876s. Three sequential bots therefore feel like
about 5.5 seconds. Overlap removes the additive 0.7 seconds but cannot erase
real search compute; Fly CPU class remains a separate product lever.

## Exact next actions

1. Deploy image `latency-b315e91` only when a fresh production peek has zero
   human connections; never deploy the old `6f15d96` image.
2. Verify live policy, native engine, semantic timing logs, seat claim,
   reconnect and X-ray; keep version 16 as the immediate rollback.
3. Monitor all eight Teacher-v3 Stage-B workers without opening outcome
   aggregates. When terminal, validate receipts and publish exactly one
   `stage_b_gate_v2.json` from the unchanged `1a2a713` producer worktree.
4. Only if that gate passes, copy the exact bound parents into the independent
   `9b2c8ab` audit worktree, publish one receipt, run eight frozen audit shards,
   and publish one gate. No outcome-conditioned state, policy, fold, threshold
   or execution-lock change.
5. Reconcile terminal Teacher/latency evidence into `JOBS.md`, `BACKLOG.md`,
   `AI_POLICIES.md`, and the 2026-08-07 daily log.

## Review request for Claude

Please audit pushed latency commit `ff784a8` specifically for snapshot/commit
atomicity, cancellation, failed-throw bookkeeping, bot-task ownership and the
real WebSocket claim witness, including X-ray's round+bot snapshot. Do not
review or deploy the earlier `6f15d96` image. Separately, audit pushed Teacher
commit `9b2c8ab`, especially the real-ballot regression and bounded transition;
watch the Stage-B receipt transition without opening gold outcomes or
duplicating workers.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; only fresh paired confirmations establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes are separate reviewed actions and require an empty room
  when they restart the server.
