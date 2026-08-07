# Active Claude/Codex handoff

Last update: 2026-08-07 13:42 EDT. This is the executable mailbox, not a
chronology. Historical packets and retractions remain in `HANDOFF_REVIEW.md`;
job artifacts are indexed in `JOBS.md`.

## Current truth

- Production Fly version 16 runs compiled `mc-s0-report-lcb`; `mc-strong` is
  rollback. This was Jerry's strength-first product decision from replicated
  S0a/b development evidence, not a formal S0 promotion.
- Formal S0 is terminal `S0_COMPLETE_SELECT_NONE`. S0c outcomes remain unread
  and burned; no retry, repair, pooling, extension or dependent authorization.
- Main/origin are pinned at clean experiment commit `ced1033` for the running
  RLCB-C1 supervisor. Do not alter its bound sources. Claude's uncommitted
  `HANDOFF_REVIEW.md` note is preserved separately and postdates launch.
- T1 implementation work is isolated and pushed on `codex/t1-latency`, current
  head `8e7afe3`. Do not duplicate or edit its replay asset from another tree.

## Running

### RLCB-C1 — Mini

- Root: `server/runs/logs/rlcb-c1-150m-v1`
- Supervisor commit: `ced1033e47bcb27b82136f72c757de40387a94f0`
- Receipt SHA-256:
  `02c286ed6e431ec807c4fe4040244e11c790c4a5b0ac5dd8f2ba186d275d39d0`
- Fresh seeds: `150000000..150002047`, 8x256 clusters.
- Arms: `mc-s0-report-lcb`, `mc-strong`,
  `mc-strong-null-rlcb-c1`; exact report/search doses are bound.
- All eight workers and score-blind heartbeats are live. At 13:42, every
  report-LCB worker had logged 200/512 mirrored rounds. No shard is terminal
  and no partial score has been opened.
- Single superiority gate: LCB95(report-LCB minus current) > 0. Null-current
  containing zero is calibration, not a second superiority claim.
- Completion is not required for T1; immutable freeze and launch are.

## T1 lane return packet

### V11-v2 — COMPLETE / FAIL

- Artifact-only repair commit `fe1ef1b`; zero games replayed or rewritten.
- Aggregate:
  `v11-current-revalidation-v2-repaired-d1d2019.aggregate.json`
- SHA-256:
  `b7c90ba4c1a9bb421a4cfcc788dbf1eb44365868f65ee0eb58257b38205d21ad`
- 2,048 clusters; exact accepted dose; sane null.
- V11-current `-0.141113 +/- 0.069823`; V11-null
  `-0.109863 +/- 0.070111`; null-current `-0.031250 +/- 0.067878`.
- `protected_composition_authorized=false`. Do not launch this checkpoint's
  protected anchor. Retain V11 only as an exact-ballot proposal/ranker and
  Teacher-v3 disagreement source; pairwise deltas are not a scalar leaf.

### Teacher-v3 entry — COMPLETE / 64 STATES FROZEN

- Source commit `be25b4d`; packet `teacher-v1-entry-149m-v3`.
- Canonical lead/follow, one-action and fallback behavior fixed. Named v2
  refusal witness plus a 1,452-decision attacker/defender lead/follow scan had
  zero off-ballot actions.
- 1,024 fresh captures, eight exact-parent diagnostics, then exactly 64 states:
  48 representative, eight boundary and eight uncertainty.
- State-set SHA-256:
  `e016373e8ecb9b6c7b6f3c14f8f4b14d9845f76478137f7a2c07249628cb4648`
- Terminal `STAGE_A_STATES_FROZEN`; `labels_launched=false` and
  `stage_a_launched=false`.
- Next gate is two separately receipted Stage-A mechanics executions over the
  same eight 8-state partitions, each with 256 selection + 256 report worlds.
  Only their deterministic PASS may freeze 128 disjoint Stage-B states. Do not
  run cheap/gold directly on the 64.

### Direct-Q — COMPLETE / SELECT NONE

- Root: `server/runs/logs/direct-q-144m-v1`
- Aggregate SHA-256:
  `1fa6789eded784e03778f5ede841e45039579625477dbaa249d63c5ccc8ce791`
- Full admitted 512-iteration screen completed. Gameplay treatment-control was
  `+0.162760 +/- 0.058755`, LCB `+0.104005`, all three seeds positive.
- Q magnitude/action-spread health passed, but seed 1 regressed on held-out MSE
  and pooled attacker/defender improvement LCBs were negative.
- `passed_learning_screen=false`, `production_promotion=false`, authorizes
  nothing, no extension. Next: target/probe diagnosis and the bounded
  Suphx-style supervised microbaseline before any Direct-Q v2.

### Production latency — CODE + AIR PASS / FLY OPEN

- Pushed branch commits `a543dbd`, `7eef872`, `9acafb1`, `7c4b037`, `8e7afe3`.
- Sanitized asset contains 100 stratified decisions from CAXI's 109 searches,
  no room/player/token/time identities, and exact cards/candidates/work/record.
- Post-RNG provenance is honest: 81 match the next live pre-state; 19 are
  explicitly source-replay-derived because intervening bot actions consumed
  the shared room RNG. Cross-architecture float comparison permits only eight
  ULPs; every non-float field remains exact.
- Scheduler offloads CPU work, defers cancellation until mutation completes,
  preserves a 50ms seat-claim grace and overlaps search with the remaining
  0.7s minimum turn pacing. Focused matrix: 44/44 plus repeated CPU fairness.
- Frozen Air result SHA-256:
  `2623def50a91d96a9dc97bd63139ef28532c2ee389c1a0cc9b4631842c6dcd57`.
  Exact 100/100; compiled p50 0.172s, p95 0.357s, max 0.422s; all gates PASS.
- Live Fly shared-cpu evidence still fails: p50 1.143s, p95 16.413s, max
  20.499s before the old additive delay. Remaining work is same-image Fly CPU
  evidence, reviewed merge/deploy and post-deploy `bot_timing`. Any billable
  resize/temp machine requires Jerry's approval and empty rooms.

## Requested review from Claude

1. Review pushed range `ced1033..8e7afe3`, especially:
   - cancellation cannot release `room.lock` while the thread mutates;
   - 50ms claim grace preserves join/takeover semantics;
   - asset sanitization, 81/19 post-RNG provenance and eight-ULP boundary;
   - no policy parameter or decision-semantic change; and
   - whether any production deploy blocker is missing.
2. Reopen Teacher-v3 state SHA `e01637…b4648` independently. Confirm the next
   legal transition is Stage-A primary/rerun mechanics, not Stage-B gold.
3. Review the written continuation decision: current Stage-B code hard-codes
   `mc-strong@N=30`, but the live champion is report-LCB. Before a Stage-B
   receipt exists, either retain old gold as explicitly attribution-only or
   version label/gate code to a stronger named continuation. Never substitute.
4. Do not inspect RLCB-C1 partial scores or modify its checkout. Post only
   source/protocol bugs that can be evaluated without outcomes.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; fresh paired confirmations establish strength.
- Partial/live outcomes never drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes are separate reviewed actions; formal experiment locks do
  not silently deploy or roll back a bot.
