# Active Claude/Codex handoff

Last update: 2026-08-07 17:31 EDT. This is the executable mailbox only.
Durable discussion and retractions remain in `HANDOFF_REVIEW.md`; policy
synthesis belongs in `AI_POLICIES.md`.

## Current truth

- **Production latency: COMPLETE / LIVE.** With Jerry's explicit authorization
  to interrupt HIEJ, Fly release 17 now runs exact image
  `latency-cd6789e`, digest `047bcfe4...5b300`. Health passes with compiled
  `mc-s0-report-lcb`; release 16 / `mc-strong` remains the immediate rollback.
- **Report-LCB confirmation: COMPLETE / CONFIRM.** Fresh RLCB-C1 used 2,048
  new paired clusters and a collision-free current-policy null:
  report-LCB-current `+0.338379 +/- 0.067706`, null-current
  `-0.019043 +/- 0.068270`. Every predeclared criterion passed. Aggregate SHA:
  `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
  The admitted supervisor completed all eight shards but terminally refused
  before aggregation because unrelated `HANDOFF_REVIEW.md` was dirty. Pushed
  artifact-only closeout `57f4e1b` binds that exact transcript, all original
  shards, the frozen runtime/source identity and the unchanged aggregate
  without replay. Closeout SHA `06dd487d...b7aae5` independently verifies.
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
`1a2a713`, namespace `teacher-v1-entry-149m-v3`. At 17:23 all remained near
one CPU after about 2h40, with zero final gold shards; outcome-blind progress
was 5.5--32.6% by shard and 17.5% aggregate work. Stage B is
attribution-only; do not inspect or use its outcomes to alter the independently
frozen champion audit.

The exact 64-state audit is already frozen at
`champion_audit_states.json` SHA
`d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34`.
Audit code is clean and pushed at `f4f3dc0`: disjoint 32-world champion
selection/report folds, full downstream `mc-s0-report-lcb` continuation, exact
receipt-to-eight-label-to-gate transitions, and a literal actor/rollout/ballot/
engine lock. An independent Air worktree at that exact commit carries the exact
frozen state asset and compiled engine. Real outcome-blind preflight reports no
transition, execution-lock, state-self or state-lock problems and proves live
lock equality. Receipt creation additionally requires exact externally
predeclared git `f4f3dc0d...5c5349` and audit-script SHA
`32a31bf7...c7bd9`; a fake future allowed-path HEAD is rejected. Preflight
caught and corrected an initially mistranscribed
ballot digest before any audit label existed; the regression now derives the
real ballot instead of mocking the literal against itself. Launch labels only
after all eight Stage-B gold shards validate and the producer gate passes.

Mini has no long strength job. It is available for bounded compiled latency
validation or the next separately admitted learner protocol.

### Frozen Teacher transition names

These names were fixed while Stage-B had zero final gold shards; do not rename
or version them from observed outcomes:

- producer gate: `stage_b_gate_v2.json` in the unchanged `1a2a713` namespace;
- Stage-B state parent: `stage_b_states.json`, SHA
  `90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6`;
- audit run id: `teacher-v3-report-lcb-audit-v1-149m`;
- audit receipt: `champion_audit_receipt_v1.json`;
- eight outputs: `champion_audit_v1_shard00.json` through
  `champion_audit_v1_shard07.json`;
- terminal output: `champion_audit_gate_v1.json`.

The audit dose is exactly eight shards and disjoint 32/32 outer
selection/report worlds; its downstream continuation remains literal deployed
report-LCB N=30/R=300. A non-PASS Stage-B gate ends this packet without an
audit receipt or labels.

## Production latency hardening

Worktree `/private/tmp/shengji-t1-latency`, branch `codex/t1-latency`, clean
and pushed at release head `578b2c6` (runtime release `b315e91`, scheduler
`ff784a8`). The reviewed commits are also integrated onto authoritative `main`
through `cd6789e`; later main commit `76afab2` changes only the C1 verifier.
The completed
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

Claude's final two harness holds are also closed at `578b2c6`: all manually
entered WebSocket sessions were replaced by `with`/`ExitStack` ownership that
cleans up on assertion failure, and the cutoff regression now drives the real
`evaluate -> play_game -> FullGameCutoff` boundary. The WebSocket+game suite is
49/49; the expanded scheduler/X-ray/replay/invariant matrix is 92 passed, two
optional skips and one expected absent historical corpus asset, with no
behavioral failure. The new remote image tag
`registry.fly.io/shengji:latency-578b2c6` has the same runtime manifest
`dbc97802...c2426a` as `b315e91`, proving the test-only hardening did not alter
runtime bytes. A fresh build from integrated main `cd6789e` is pushed as
`latency-cd6789e`, manifest `047bcfe4...5b300`; its runtime source tree is
byte-identical to release branch `578b2c6` and it is the preferred deploy tag.

Deployment is complete as Fly release 17. The exact running image is
`registry.fly.io/shengji:latency-cd6789e`, manifest SHA-256
`047bcfe4d4573961734a5536ad549605fd0df5e1477d7480cdf322282955b300`;
Fly status and the health check independently report it. Never deploy the
older `6f15d96` image.

The live ship gate exercised an actual on-turn search. A claimant received the
bot seat in 20ms and resumed that same seat/token in 17ms; semantic logs show
the displaced worker as `acted=false`, `stale_discarded=true`, and every timing
record as offloaded and snapshot-isolated. A real eight-candidate X-ray search
took 1.53s while 25 concurrent WebSocket peeks stayed at p50 12ms/max 19ms.
After 42 bot timings, search p50/p95/max were 1.136/1.857/3.104s and full-turn
p50/p95/max were 1.138/1.858/3.106s. Release 16 is retained for rollback.

Live Fly evidence explains the complaint: room HIEJ's 40 searched bot turns
had search p50 1.133s, p95 1.858s, max 2.174s; visible inter-play delay was
p50 1.835s, p95 2.561s, max 2.876s. Three sequential bots therefore feel like
about 5.5 seconds. Overlap removes the additive 0.7 seconds but cannot erase
real search compute; Fly CPU class remains a separate product lever.

## Exact next actions

1. Monitor all eight Teacher-v3 Stage-B workers without opening outcome
   aggregates. When terminal, validate receipts and publish exactly one
   `stage_b_gate_v2.json` from the unchanged `1a2a713` producer worktree.
2. Only if that gate passes, copy the exact bound parents into the independent
   `f4f3dc0` audit worktree, publish one receipt with the exact git/script
   predeclaration above, run eight frozen audit shards, and publish one gate.
   No outcome-conditioned state, policy, fold, threshold or execution-lock
   change.
3. Monitor release-17 timing in ordinary human rooms. Roll back to release 16
   only for a correctness, responsiveness or availability regression; CPU
   resize remains a separate product decision.

## Review request for Claude

Please audit main integration through `cd6789e` (release-equivalent
`578b2c6`), especially failure-safe socket ownership and the real
evaluator-cutoff witness. Do not review or deploy the
earlier `6f15d96` image. Separately, audit pushed Teacher
commit `f4f3dc0`, especially its exact receipt-entry predeclaration, and C1
artifact-only closeout `57f4e1b`/SHA `06dd487d...b7aae5`; watch the Stage-B
receipt transition without opening gold outcomes or duplicating workers.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; only fresh paired confirmations establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes are separate reviewed actions and require either an empty
  room or explicit authorization to interrupt live games. Jerry supplied that
  authorization for release 17 only.
