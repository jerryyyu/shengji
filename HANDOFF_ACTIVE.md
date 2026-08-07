# Active Claude/Codex handoff

Last update: 2026-08-07 18:12 EDT. This is the executable mailbox only.
Durable discussion and retractions remain in `HANDOFF_REVIEW.md`; policy
synthesis belongs in `AI_POLICIES.md`.

## Current truth

- **Production latency: COMPLETE / LIVE.** With Jerry's explicit authorization
  to interrupt HIEJ, Fly release 17 now runs exact image
  `latency-cd6789e`, digest `047bcfe4...5b300`. Health passes with compiled
  `mc-s0-report-lcb`. Release 16 is the scheduler/runtime rollback;
  `mc-strong` is the separate policy rollback.
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

Fresh executable reopening at 17:35 independently reproduced all three closed
chains: strict C1 verification returned aggregate `83f5a9df...f5ea` and
closeout `06dd487d...aae5`; Air at exact `d1d2019` verified V11 aggregate
`b7c90ba4...d21ad` with protected composition false; and Direct-Q recomputed
from its original clean `b365120` runtime returned
`passed_learning_screen=false`, `production_promotion=false`, and
`verified=true`. These checks generated no games and performed no training.

## Running compute

Air owns eight live compiled+strict Teacher-v3 Stage-B gold workers at exact
`1a2a713`, namespace `teacher-v1-entry-149m-v3`. At 18:08 all eight real
Python workers remained healthy at 86--89% CPU after about 3h24m, with zero
final gold shards; outcome-blind fold progress by shard was
`372/704/152/432/268/508/356/500`, or 20.1% aggregate
(`3,292/16,384`). This proves
liveness but is not a compute-weighted ETA because ballot sizes and
continuation costs vary. Stage B is attribution-only; do not inspect or use
its outcomes to alter the independently frozen champion audit.

The exact 64-state audit is already frozen at
`champion_audit_states.json` SHA
`d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34`.
Audit code is clean and pushed at `182d1df`: disjoint 32-world champion
selection/report folds, full downstream `mc-s0-report-lcb` continuation, exact
receipt-to-eight-label-to-gate transitions, and a literal actor/rollout/ballot/
engine lock. An independent Air worktree at that exact commit carries the exact
frozen state asset and compiled engine. Real outcome-blind preflight reports no
transition, execution-lock, state-self or state-lock problems and proves live
lock equality. Receipt creation additionally requires exact externally
predeclared git `182d1df21697cedd722edfd3215ea1e2a7dd8753` and audit-script
SHA `57796fda247a4152a58bb98508d24ae1063f7e2c843ccf436b8b111f7c887ead`;
a fake future allowed-path HEAD is rejected.

The earlier `f4f3dc0` identity is superseded before receipt creation. Its
"live" ballot test had reused a process-local cache populated before the exact
native binary was installed, freezing `c008dd47b0b7`; a fresh receipt process
correctly produced `568848979a2d` and refused. Commit `182d1df` restores that
fresh identity, clears the audit-boundary cache, and regression-tests a
deliberately poisoned cache before deriving it.
Air passes 19/19 focused tests and a brand-new interpreter reports empty
transition/predeclaration/execution/state problem lists. No audit label exists.
Launch labels only after all eight Stage-B gold shards validate and the
producer gate passes.

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

### One-shot Stage-B transition checklist

Do not run the terminal gate merely because eight filenames appear. Readiness
requires all eight `stage_b_gold_v2_shard00..07.json` files to be regular
files, zero matching `.partial` files, zero live `teacher_v1_label.py gold`
workers, an unchanged clean producer at exact
`1a2a71333ea283784b19855e67e1ae231379ec79`, exact
`stage_b_states.json` SHA `90956da8...dc6`, and no existing
`stage_b_gate_v2.json` or partial. The final hard link appears before each
worker's last provenance recheck, which is why process exit and partial
absence are both required.

Once those conditions hold, run exactly one producer gate from
`~/Projects/shengji-teacher-air/server` with compiled+strict flags and all
eight inputs in shard order:

```sh
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
  .venv/bin/python scripts/teacher_v1_gate.py stage-b \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard00.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard01.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard02.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard03.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard04.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard05.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard06.json \
  --cheap runs/logs/teacher-v1-entry-149m-v3/stage_b_cheap_v2_shard07.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard00.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard01.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard02.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard03.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard04.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard05.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard06.json \
  --gold runs/logs/teacher-v1-entry-149m-v3/stage_b_gold_v2_shard07.json \
  --state-set runs/logs/teacher-v1-entry-149m-v3/stage_b_states.json \
  --expected-state-set-sha256 \
  90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6 \
  --out runs/logs/teacher-v1-entry-149m-v3/stage_b_gate_v2.json
```

Exit 0 means terminal PASS; exit 4 means a valid terminal FAIL or
INCONCLUSIVE. Preserve the published gate in either case and never retry it.
Only PASS permits the audit transition. Before receipt creation, reopen the
gate and every parent, calculate their exact file SHA-256 values, copy the
state set, both producer receipts, eight cheap shards, eight gold shards and
gate into the otherwise-empty ignored namespace of the clean `182d1df` audit
worktree without overwriting anything, and prove source/destination bytes
match. The receipt must use the already-frozen run id/names plus exact git
`182d1df21697cedd722edfd3215ea1e2a7dd8753`, script SHA
`57796fda247a4152a58bb98508d24ae1063f7e2c843ccf436b8b111f7c887ead`,
state SHAs above, and the newly sealed parent/gate SHAs. Only then launch
exactly eight 32/32 audit shards. **Do not infer success from the receipt's
final filename:** publication hard-links that name before the last provenance
recheck. Require the receipt creator to exit `0`, require a regular final and
no `champion_audit_receipt_v1.json.partial`, recompute its SHA-256, and reopen
it under that exact SHA before starting labels. Apply the same rule to every
audit label: worker exit `0`, regular final, no matching `.partial`, exact
SHA/reopen. Their terminal gate is likewise published once, only after all
eight workers have exited and all eight artifacts validate; preserve a
non-PASS gate and never retry it.

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
p50/p95/max were 1.138/1.858/3.106s. Release 16 is retained for runtime
rollback; `mc-strong` remains the policy rollback.

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
   `182d1df` audit worktree, publish one receipt with the exact git/script
   predeclaration above, run eight frozen audit shards, and publish one gate.
   No outcome-conditioned state, policy, fold, threshold or execution-lock
   change.
3. Monitor release-17 timing in ordinary human rooms. Roll back the runtime to
   release 16 only for a correctness, responsiveness or availability
   regression; policy rollback to `mc-strong` and CPU resize remain separate
   decisions.

## Review request for Claude

Please audit current main, including `91c42a9`, the release-17 live evidence,
the distinction between runtime rollback (Fly 16) and policy rollback
(`mc-strong`), the one-shot Stage-B readiness/transition checklist, and the
restoration of the already-frozen 149M-v3/audit contract into main's previously
stale `TEACHER_V1_SPEC.md`.
The latency code under test remains integration `cd6789e`, release-equivalent
`578b2c6`; do not review or deploy the earlier `6f15d96` image. Separately,
audit pushed Teacher repair `182d1df`, especially the stale-ballot-cache
regression and new exact receipt predeclaration; the superseded `f4f3dc0`
identity must never create a receipt. Also audit C1 artifact-only closeout
`57f4e1b`/SHA `06dd487d...b7aae5`; watch the Stage-B transition without opening
gold outcomes or duplicating workers. Separately review the new no-run
`SUPHX_MICRO_SPEC.md` plus `server/shengji/rl/suphx_micro.py` and its tests: in
particular, challenge whether its legal/private feature boundary, O0
prerequisite, three O1 arms and public-endpoint invariance form the smallest
honest test of oracle guiding. The feature gate is 12/12 and adjacent tests are
48/48; it authorizes no training.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; only fresh paired confirmations establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes are separate reviewed actions and require either an empty
  room or explicit authorization to interrupt live games. Jerry supplied that
  authorization for release 17 only.
