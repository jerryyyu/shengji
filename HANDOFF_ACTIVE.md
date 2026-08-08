# Active Claude/Codex handoff

Last update: 2026-08-08 08:18 EDT. This is the executable mailbox only.
Durable discussion and retractions remain in `HANDOFF_REVIEW.md`; policy
synthesis belongs in `AI_POLICIES.md`.

## Current truth

- **Teacher-v3 Stage B: COMPLETE / PASS; champion audit-v2: RUNNING.** At
  07:28 the reviewed outcome-blind checker found 8/8 regular gold finals,
  zero workers, exact clean producer `1a2a713`, no partial/gate collision and
  `outcomes_opened=false`. The single authorized Stage-B gate then exited zero
  with terminal PASS: mean cheap-minus-gold regret `-0.002686`, upper 95%
  `0.019548 < 0.10`, gate SHA
  `f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694`.
  The first audit preparation launched no labels: exact `182d1df` receipt
  creation exited 3 because its post-link verifier called an ordinary loader
  while its own hard-linked `.partial` refusal marker still existed. Preserve
  that checkout/final/partial/exit forever; never retry or adopt it.
  Repaired evaluator `1866132` / script SHA `c7b47a7a...d6cb` and controller
  `edc923f` passed the exact independent review at 08:07. The one authorized
  v2 preparation exited zero, bound all 20 parents, and published receipt SHA
  `ce51b826...71d0` plus preparation SHA `7f89a86c...6605`, with exact v2
  receipt identity and no partial. At 08:16 Air supervisor PID 95339 admitted
  that packet and launched eight 32/32 label workers, PIDs 95345--95352. All
  eight were live at about 82--85% CPU and initial fold progress was visible.
  No result has been read; the supervisor will invoke one terminal gate only
  after all eight regular finals exit zero and reopen exactly.
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
- **Suphx O0: COMPLETE / SELECT NONE.** The immutable review source contained
  the exact packet marker but no byte-authenticated reviewer identity; it was
  copied and hash-admitted at admission SHA `67f79f29…3e590b`. All six frozen
  Mini arms completed 64/64 updates with real midpoint teardown/resume, and
  all three DEV evaluations exited zero. Terminal gate SHA
  `592a009aaf6fbd6680b6d9bab5e9738832050d1654b71dc6f2e19612d0bd407c`
  independently replays with `verified=true`. Oracle-minus-initial was
  `+0.335938`, LCB `+0.273991`; oracle-minus-public was `+0.072917`, LCB
  `+0.002548`. Per-seed oracle-minus-public means were
  `+0.343750/-0.207031/+0.082031`, so the registered all-seeds robustness
  criterion failed. Every other exact-work, resume, legal-world,
  hidden-information, entropy, finite-model, surface and same-model-null gate
  passed. O1/strength/production authority are all false. Do not extend or
  retune this inspected recipe; preserve it as evidence that oracle learning
  was aggregate-positive but weak and seed-unstable.
- **DEV-512:** SELECT NONE / closed. CALIB and REPORT remain sealed.

Fresh executable reopening at 00:06 on August 8 independently reproduced
all three closed chains: strict C1 verification returned aggregate
`83f5a9df...f5ea` and
closeout `06dd487d...aae5`; Air at exact `d1d2019` verified V11 aggregate
`b7c90ba4...d21ad` with protected composition false; and Direct-Q recomputed
from its original clean `b365120` runtime returned
`passed_learning_screen=false`, `production_promotion=false`, and
`verified=true`. These checks generated no games and performed no training.

## Current Teacher-v3 audit-v2 run

The exact PASS marker is recorded in `HANDOFF_REVIEW.md` for evaluator
`1866132766c7`, evaluator-script SHA `c7b47a7a...d6cb` and controller
`edc923f3baf1`. Air execution is:

- evaluator root `~/Projects/shengji-teacher-audit-v2-air`, run ID
  `teacher-v3-report-lcb-audit-v2-149m`;
- receipt `ce51b826d4f04549b961f795868cc4c6c5f90124a8552ce76fe2d3ab0bd471d0`;
- preparation
  `7f89a86c2e0803d83473d8ccca978dd99dd010e467761d0d4429a3598c166605`;
- supervisor PID 95339; label PIDs 95345--95352; eight shards, each fixed at
  32 selection plus 32 disjoint report worlds per state;
- operator log `~/teacher-v3-audit-v2-supervisor.log`; authoritative progress
  `champion_audit_supervisor_v1.jsonl.partial` inside the audit namespace.

Monitor liveness and score-free fold counters only. Do not open partial outcome
values, retry, resume, alter a worker, or launch a second supervisor. A child
failure or malformed publication leaves the attempt terminally refused. On
eight exact zero exits, this supervisor alone reopens all labels and invokes
the frozen gate once; preserve PASS, FAIL or INCONCLUSIVE exactly as published.

## Historical 01:18 Teacher snapshot — superseded; do not execute

Air launched eight compiled+strict Teacher-v3 Stage-B gold workers at exact
`1a2a713`, namespace `teacher-v1-entry-149m-v3`. At 01:18 shard 1 remained the
only clean terminal publication, with its process gone, terminal success
sentinel present, one regular final and no partial; seven Python workers were
healthy. Corrected sequential outcome-blind fold progress by shard was
`1636/2048/1396/1464/1004/1304/1564/1524`, or 72.9% aggregate
(`11,940/16,384`). The reviewed readiness checker recognized
that exact one-final/seven-worker state and correctly returned not ready with
no opened outcome or created artifact. This proves
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

A separate score-blind capacity probe on Mini used one fresh
`timing_probe_v1` world per already-frozen audit state, candidate zero only,
and printed no utility or choice. It measured mean/max ballot sizes 6.09/14
and projects about 37.1 CPU-hours for the literal 32/32 audit. The frozen
eight-way partition projects approximately
`2.27/6.09/2.03/4.01/5.49/6.78/4.61/5.87` hours by shard on Mini, so the rough
critical path is 6.8 hours after a Stage-B PASS. This is a one-world sizing
estimate, not evidence or an Air ETA; it changes no state, fold, shard or gate.
A second native probe exercised all 14 candidates on two separately named
non-evidence outer worlds: 1,604 downstream decisions, 1,271 searched
decisions and 1,009,950 inner candidate rollouts completed in 201 seconds.
Both exact tensor and continuation-telemetry validators returned no problems;
the probe used neither future champion fold nor parent action choice.
Two information-boundary sweeps then changed only facts hidden from the acting
seat. Across all 64 frozen states and all 12 phase/role/lead-follow cells,
swapping cards between non-acting hands left the action, semantic decision
record, sampled-world count and counters identical; 56 witnesses performed a
real search. Swapping an unseen kitty card with another hidden hand passed the
same checks in all 47 non-banker states, including 41 searched witnesses. The
exact locked `mcbot.py`/`memory.py` bytes are also current main's bytes, so two
small non-vacuous regressions now preserve both boundaries. The focused file
passes 10/10 and the adjacent sampler/memory/invariant matrix passes 63/63 in
both ordinary and compiled-strict routing.

Local verification at exact current O0 material `7b15338` is 1,030 passed / 27
skipped in the broad ordinary suite, 25/25 focused, and 196/196 adjacent in
both ordinary and compiled-strict routes.
At 23:45 a separate no-artifact validator that does not call
`_chronological_world_problems()` or `Round.play` reconstructed the initial
hands, applied `validate_lead`/`validate_follow` directly, independently
recomputed trick winners, and recovered every remaining hand. All 128 selected
hidden-hand witnesses and all 126 selected hidden-burial witnesses passed with
zero failures. This corroborates the repair but does not replace the required
external implementation review.
The focused C1/S0 historical-boundary matrix is 31/31 in both ordinary and
compiled-strict modes. This does **not** turn the retired S0 parent into a
current verifier PASS: its immutable SELECT-NONE authority intentionally
reports the one exact descendant `registry_sha256` drift after C1 added a
policy. The test now proves the frozen introduction blob and this fail-closed
condition explicitly rather than misreporting a regression.

Mini has no long strength job. Suphx O0 is terminal SELECT NONE and all six
training/evaluation services are unloaded. Mini is available for the next
fresh, independently frozen strength screen; it must not extend Direct-Q, O0
or protected V11 from their inspected outcomes.

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

**Detached-creator status caveat found before any gold final existed:** the
eight manually launched Python workers have PPID 1 and their launch shell did
not persist a wait-status receipt. A literal historical exit code therefore
cannot be recovered after they disappear. Do not silently call that `exit 0`.
The proposed predeclared equivalent is, for every shard: its recorded original
Python PID (`73123` through `73130`, shard order) no longer runs that exact
command; the corresponding log is a regular file with no `REFUSING:` line and
whose final line exactly starts
`wrote <expected-output>: 16 records, digest `; the final is regular; its
`.partial` is absent; and the unchanged gate loader reopens and fully validates
the artifact.
In `teacher_v1_label.py` the flushed success sentinel runs only after final
linking, post-link parent/runtime revalidation, exact artifact reopening and
partial removal, and it is the last successful statement in `main()`. The
20:51 outcome-blind review explicitly accepted this as a predeclared artifact-
completion substitute—not a reconstructed exit code. The checker may therefore
admit exactly one producer-gate invocation once every mechanical condition is
green.

Pushed commit `3d8bee0` adds the stdlib-only
`scripts/teacher_stage_b_readiness.py` implementation of that exact
outcome-blind boundary. It checks the frozen producer/source/parent identities,
clean tree, worker absence, exact regular final/log population, absent
partials/gate, no refusal and the terminal success sentinel. It deliberately
never imports the evaluator or opens a gold JSON file, creates no artifact and
always reports gate/audit authority false. Its focused plus adjacent Teacher
matrix passes 134/134 in both ordinary and compiled-strict routing. A live
streamed check at 20:34 returned exit `4` / not ready solely with all eight
workers live and all eight finals absent; it reported
`outcomes_opened=false` and `artifact_created=false`. The review accepted the
implementation and completion equivalence at 20:51; a future ready result now
permits, but never itself runs, the one-shot gate.

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

The PASS-to-audit launch is no longer a manual copy or background-process
boundary. Pushed commits `ca62557` and `1c97928` add and harden the external,
stdlib-only
`teacher_champion_audit_prepare.py`, SHA-256
`5ffb6773057e021b4a66f6075dfd9d224513771a5c1bf3ab877eb921206baa57`,
and tightens `teacher_champion_audit_supervisor.py`, SHA-256
`44025386cf6d0b3d797a45ba65507f0d5f0a84d10c6ffca59eb85f8b88f682d5`.
The preparer accepts only the exact producer/audit identities and a caller-
bound terminal Stage-B PASS; validates the exact 20-parent population; copies
every parent exclusively with matching SHA; runs receipt creation synchronously;
persists its real exit status; and publishes a hash-bound preparation manifest.
It launches no labels. The supervisor now requires that exact manifest,
preparer identity, copied parents and receipt exit zero before admitting work.
It leaves frozen audit code `182d1df` untouched, owns all eight label children,
records every wait status, emits 60-second heartbeats, directly reopens each
regular 32/32 label and invokes the terminal gate exactly once only after all
eight exit zero. The preparer verifies the actual adjacent supervisor bytes
before its first irreversible copy, so a well-formed mistyped hash cannot burn
the receipt. A child failure, malformed basic identity, collision, signal or
identity drift terminates siblings, preserves partial evidence and never gates
or retries. Terminal output is accepted only for exact PASS/FAIL/INCONCLUSIVE
verdicts whose authorization fields agree with the real exit status. Deeper
semantic corruption is deliberately left to the
frozen evaluator, which publishes terminal INCONCLUSIVE rather than promotion;
a valid terminal non-PASS gate is preserved with exit `4`. The chained focused
suite is 20/20; the adjacent Teacher matrix is 154/154 in both ordinary and
compiled-strict routing. The fresh broad ordinary server suite is 1,005 passed,
27 skipped.

Air now has a clean detached controller worktree at exact
`~/Projects/shengji-teacher-control2-air` / `1c97928`. The older `07b2a9f`
controller is superseded before any receipt/label/gate and must not run. The
new live preflight binds both evidence checkouts, both controller hashes, the
audit-script hash and exact producer-venv Python 3.14.6, then refuses solely
because `stage_b_gate_v2.json` correctly does not exist. It created no audit
file. After the one-shot producer gate exits `0`, compute and externally record
its exact SHA, then run preparation once:

```sh
python3 ~/Projects/shengji-teacher-control2-air/server/scripts/teacher_champion_audit_prepare.py \
  --producer-root ~/Projects/shengji-teacher-air/server \
  --audit-root ~/Projects/shengji-teacher-audit-air/server \
  --python ~/Projects/shengji-teacher-air/server/.venv/bin/python \
  --expected-stage-b-gate-sha256 <exact-stage-b-gate-sha256> \
  --expected-preparer-sha256 \
  5ffb6773057e021b4a66f6075dfd9d224513771a5c1bf3ab877eb921206baa57 \
  --expected-supervisor-sha256 \
  44025386cf6d0b3d797a45ba65507f0d5f0a84d10c6ffca59eb85f8b88f682d5
```

Only if that exits zero, record the printed receipt and preparation SHAs and
run the label/gate supervisor once:

```sh
python3 ~/Projects/shengji-teacher-control2-air/server/scripts/teacher_champion_audit_supervisor.py \
  --audit-root ~/Projects/shengji-teacher-audit-air/server \
  --python ~/Projects/shengji-teacher-air/server/.venv/bin/python \
  --expected-receipt-sha256 <exact-receipt-sha256> \
  --expected-preparation-sha256 <exact-preparation-sha256> \
  --expected-preparer-sha256 \
  5ffb6773057e021b4a66f6075dfd9d224513771a5c1bf3ab877eb921206baa57 \
  --expected-supervisor-sha256 \
  44025386cf6d0b3d797a45ba65507f0d5f0a84d10c6ffca59eb85f8b88f682d5
```

These controllers grant no Stage-B or production authority. The 21:57
independent review passed exact `1c97928`, including the supervisor-byte
preflight and terminal-verdict contract. Its live Air invocation refused solely on
the correctly absent Stage-B gate and created no audit artifact. The semantic-
INCONCLUSIVE boundary above remains unchanged.

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

Release 17 now also has ordinary post-fix traffic rather than only the ship
gate. In room MYWR, one human seat completed five rounds against three bots
from 18:10--18:45 EDT. Of 249 bot play timings, 195 were search-like turns
(`compute_seconds >= 0.05`):
search p50/p95/max was 0.896/1.714/1.906s and full-turn p50/p95/max was
0.904/1.716/1.907s. All 249 records were offloaded and snapshot-isolated, with
no stale action. This supports the intended per-turn improvement but is one
room, not a concurrent multi-room tail test. Production was healthy and empty
at 23:21.

## Exact next actions

1. Wait for the exact `TEACHER_V3_AUDIT_V2_REVIEW_V1` PASS marker above. Do
   not launch another receipt from v1 or v2 before it exists and reopens.
2. On PASS only, run the `edc923f` preparer once against the fresh
   `shengji-teacher-audit-v2-air` root with gate SHA `f607b489...89694` and
   controller hashes `084c7e98...8434` / `59610ef0...bb06`. Require exit 0,
   final receipt, no partial, exact receipt/preparation SHAs and successful
   reopen before the same controller owns all eight frozen labels and one
   terminal gate. Preserve every nonzero or non-PASS result; never retry.
3. Monitor release-17 timing in ordinary human rooms. Roll back the runtime to
   release 16 only for a correctness, responsiveness or availability
   regression; policy rollback to `mc-strong` and CPU resize remain separate
   decisions.
4. Preserve Suphx O0 gate SHA `592a009a…bd407c` as terminal SELECT NONE.
   Do not extend it or enter O1. Use its weak aggregate oracle-public edge,
   seed-1 reversal and near-uniform policy diagnostics only to preregister a
   fresh learner question on new seeds/data.

## Review context and next Claude request

The 20:51 review accepted the Stage-B artifact-completion substitute and Suphx
runtime admission while preserving their narrow authority; the heading in
`HANDOFF_REVIEW.md` is Codex, not Claude. The later 21:57 independent review
passed exact controller `1c97928`. Continue watching Stage B without opening
outcomes or duplicating workers. Exact audit identity remains
`182d1df`/`57796fda...887ead`; superseded `f4f3dc0` must never create a receipt.
For Suphx O0, Codex chose the narrow option before any training: the primary
estimand is performance of the exact frozen three-seed ensemble across the 128
deal clusters, conditional on those learner/action streams. Per-seed positivity
is a robustness gate, not seed-level inference, and no recipe-level
generalization is claimed. The 22:57 review of `dd83182` correctly found 13
selected witness worlds whose current snapshot was plausible but whose earlier
public history was not: 10 hidden-hand swaps and three burial swaps violated a
past pair obligation or changed a recorded successful throw into a failed one.

The 23:52 review passed the chronology mechanics at exact repair
`7b153388096e1b8970794ef80fb750f38cae19ad`. It reconstructs all four
post-burial 25-card hands, forces real follow validation on, and replays every
resolved plus current public play through `Round.play`. It requires the replay
to preserve the actual recorded cards, trick leader/resolution, current turn,
remaining hands and attacker points. Named falsifications pin the historical
pair witness at deal `160100011`, successful-throw witness at `160100083`, and
hidden-burial pair witness at `160100029`; all now fail for the expected engine
reason. The regenerated 128-state population remains 32/32/32/32 by surface
and has burial witnesses in every surface. Tests are 25/25 focused, 196/196
adjacent in each route and 1,030 passed / 27 skipped broad ordinary. Packet
admission, exact-root enforcement and the optimized reopen boundary are
unchanged. A separate direct-legal-validator sweep then replayed all 128 hand
and 126 burial witnesses with zero failures without calling the repaired
chronological helper or `Round.play`; treat that only as corroboration. O0
material commit `9aabf0b` changes the reviewer's sole remaining blocker:
`SUPHX_MICRO_SPEC.md` now says the actual 25/25 focused count instead of 22/22,
and compiled+strict focused tests pass 25/25. The 00:49 review explicitly
passed exact material snapshot `9aabf0b`; the one allowed freeze and independent
semantic reopen then produced exact packet SHA
`6d4e6772e94df292fe0a7b72735ea3995e4f6098cca9e5c37ab12268bed1ed65`.
That packet review is now complete. Its exact external marker was admitted,
all six arms and three DEV evaluations completed, and terminal gate
`592a009a…bd407c` independently verified SELECT NONE. Do not repeat any O0
entry point.

After the current broad adversarial code/evidence audit, please provide a
separate **strategy synthesis**. Read `docs_archive/daily-log-2026-08-05.md`
through `daily-log-2026-08-08.md`, then current `BACKLOG.md`, `RL_PLAN.md` and
`AI_POLICIES.md`. Reconcile those documents with the terminal report-LCB,
DEV-512, V11-v2, Direct-Q and O0 evidence plus the still-running Teacher-v3
boundary. Do not open live Teacher outcomes, change code, launch compute or
turn this strategy review into a new execution gate.

One post-terminal O0 clue deserves explicit review. Reopening every candidate
checkpoint shows that all 24 entropy-controller paths reached alpha zero: lead
heads at iterations 10–12 and follow heads at 48–53. Terminal normalized DEV
entropy nevertheless stayed `0.999997–1.000000`. This was not a no-op:
oracle perfect encoders moved about 25–29% in relative L2, the other major
parameter groups moved roughly 18–39%, and terminal greedy-action change rates
were 53–60% for oracle and 52–62% for public. The current nonnegative entropy
bonus can stop encouraging excess entropy but cannot actively penalize it.
Please decide whether this is the intended minimum-entropy controller plus an
underpowered/high-variance dose, or an objective/gate implementation flaw.
Also assess whether three fixed pairs with arm-separated action RNG streams
can cleanly attribute oracle benefit, or whether a fresh crossed/common-random-
number design and training seeds as an inference dimension are required. These
are diagnostic questions only; they do not reopen O0.

Please append a concise entry to `HANDOFF_REVIEW.md` answering:

1. What are the five most decision-relevant findings from the last four days,
   and which common interpretation of each would be wrong?
2. Does the current three-lane strength plan still target the shortest credible
   path to beating `mc-s0-report-lcb`? Identify any lane that should be stopped,
   merged, reordered or added.
3. What do Direct-Q's positive gameplay/failed held-out gate and O0's positive
   aggregate oracle signal/failed seed robustness jointly imply about the next
   learner mechanism? Separate implementation-risk hypotheses from genuine
   algorithmic negatives.
4. How should Teacher-v3, the high-N/late-ply reservoirs, v11pair proposals and
   search/oracle labels feed one flywheel without merely imitating the current
   champion?
5. Give the next three preregistered experiments in order, with hypothesis,
   parent policy, data source, minimum control, screen metric, stop gate,
   approximate Mini/Air cost and the result that would justify scaling.
6. Name the highest-value analysis or code work that can proceed while Air is
   occupied, and explicitly list runs that would waste compute now.

Distinguish established evidence, inference and recommendation. Optimize for
verified bot strength rather than novelty or low latency, and make the plan
specific enough to copy into the ordered backlog without another design round.

## Standing rules

- Every accepted commit is pushed.
- Never delete or overwrite failed/evidence namespaces.
- Screens select; only fresh paired confirmations establish strength.
- Partial/live outcomes do not drive code, stopping or sample-size changes.
- House progression is uncapped; clipped `+/-3` is a named legacy RL target.
- Production changes are separate reviewed actions and require either an empty
  room or explicit authorization to interrupt live games. Jerry supplied
  scoped authorization to clear live games if a validated fix needs a deploy;
  check occupancy first and do not clear rooms preemptively.
