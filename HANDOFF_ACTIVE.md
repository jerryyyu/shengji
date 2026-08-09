# Active Claude/Codex handoff

Last update: 2026-08-09 01:49 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, queue order in
`BACKLOG.md`, exact run state in `JOBS.md`, and review history in
`HANDOFF_REVIEW.md`.

## Current truth

| area | status | next action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 confirmed `+0.338379 +/- 0.067706` versus `mc-strong`. Runtime rollback is release 16; policy rollback is `mc-strong`. |
| T1 Teacher | **RUNNING ON MINI / 3 OF 8 SHARDS PUBLISHED / ADAPTER PASS** | Claude passed the launch packet and terminal adapter `5b26c4b`. Shards 2, 5 and 7 exited zero; five workers remain live under the same supervisor. Keep every label sealed until the one terminal gate, independently recompute it, then create one adapter artifact. |
| T2 S3a structured bury | **MECHANISM PASS / GUARDED PREFLIGHT REVIEW PASS** | Claude passed exact `e6f2493` / contract `5e0f6ade…b44653`, including the executable Teacher-release guard and its wiring witness. The exact four-cluster score-free preflight may run only after Teacher publishes its final, removes the partial, and all workers exit. It cannot launch the screen or make a strength claim. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The frozen 250,000-node preflight cap fired. Never retry or relax v2. |
| T2 learner O0-v2 | **AIR PREFLIGHT PASS / PACKET REVIEW OPEN / NO TRAINING** | Claude passed exact `2e13c35`. The one disposable score-redacted Air preflight passed and independently reverified; frozen packet `20d2aaee…5cab0` now awaits exact `SUPHX_O0_V2_AIR_PACKET_REVIEW_V1`. Do not admit or train before that separate PASS. |

## OPEN NOW — O0-v2 frozen Air packet review

Claude's delta-only V3 review passed exact `2e13c35`; its marker is preserved
in `HANDOFF_REVIEW.md`. The authorized Air preflight then passed all criteria
in 1.75 seconds and independently reverified at SHA-256
`f8e1dc1673d1d6f3e20d3f849e84c7f45da570ba6b49db07f030d4d34e312eaf`.
Its conservative 2x projection is 3,561.71 seconds (59.4 minutes), below the
frozen eight-hour ceiling. It contains no scores and authorizes no training.

The canonical Air packet was frozen and independently reverified at exact
path `server/runs/logs/suphx-o0-v2-air-8seed-v1/launch_packet.json`, SHA-256
`20d2aaee9773ab40011d9e3844132a6bbf458a4a6fdf258af578813563f5cab0`.
It binds eight fresh initial seeds, both factorial cells and arms, exact
source/runtime/preflight identity, and still says `training_authorized=false`.
Claude should now perform the bounded packet review requested at the bottom of
`HANDOFF_REVIEW.md`. PASS can authorize admission and O0-v2 training only;
O1, strength, promotion and production remain false.

## LIVE NOW — fresh Teacher audit on Mini

Claude independently passed evaluator `f78e904`, controller `0399591`, and
ordered material `645b8f54…b894d`; the exact marker is preserved in
`HANDOFF_REVIEW.md`. The one authorized preparation completed at zero exit:

- receipt SHA-256 `e293858c728437d6016a3f02a62a355c38a37a6028ad0d83e49423e1caf4a10d`;
- preparation SHA-256 `83892930fa8e7e8148960511ef0a87c3becbe77a87eaebf3c912458863644c39`;
- independent post-preparation supervisor preflight: zero problems.

The one-shot supervisor admitted run
`teacher-v3-report-lcb-audit-v3-mini-149m` on literal host
`Jerrys-Mac-mini.local` and launched all eight shards at 16:33 EDT. Output is
owned under `runs/logs/teacher-v1-entry-149m-v5`. Outer audit folds are 32/32;
each searched continuation retains 30 accepted selection plus 300 accepted
disjoint report worlds with bounded unscored retries. Do not start another
instance, migrate to Air, inspect partial scores for decisions, retry, extend,
train, promote, or launch Stage C. Wait for the supervisor's single terminal
gate and independently reopen every binding.

Outcome-blind runtime audit at 01:49 found 3,333/4,096 outer worlds (81.4%) and
50/64 states. Shards 2, 5 and 7 published regular label/log/exit triplets after
exit zero; all three label JSONs remain unopened and unhashed. Five workers remain
CPU-bound under the original supervisor. An
earlier bounded audit found ~13% of a candidate-count × remaining-ply work
proxy complete after ~56 minutes. Because
the frozen partition is highly imbalanced (1–14 candidates and ply 0–72), a
simple slowest-shard projection is roughly 10–16 hours. This is not a stall:
all eight workers remain CPU-bound and every log advances. It does mean a
same-evening terminal gate is unlikely. Never use this operational forecast to
read or stop on outcomes; do not repartition, duplicate, migrate or mutate the
reviewed one-shot chain.

## O0-v2 review boundary

The superseded V2/V3 code-review narrative is intentionally omitted here.
Current packet identity, preflight evidence, authority and the sole open
review are recorded once at the top of this file. T1 terminal closeout already
has its separate adapter PASS.

Use pushed read-only monitor `c96a932` while the run is partial:

```bash
server/.venv/bin/python server/scripts/teacher_audit_progress.py \
  --run-root /Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server/runs/logs/teacher-v1-entry-149m-v5
```

It accepts only the exact progress/publication-receipt key sets and monotone
32/32 fold ordering; an outcome or unknown field, duplicate state, malformed
number, log collision, or incomplete final refuses. Its 8/8 falsification
tests pass. It never reads a label JSON or grants stopping/retry authority.

## CLOSED REVIEW — terminal adapter v2 PASS

Claude independently passed branch `codex/teacher-terminal-adapter-v2` at exact
`5b26c4b4bdb678b2c780c8a4b6ed5b87e181964e` (29/29 focused tests). It updates
the previously reviewed fail-closed adapter to the exact v2 gate/supervisor,
fresh Mini run identity, retry admission, old/new state provenance, Stage-B
assets, literal receipt `e293858c…a10d`, literal preparation
`83892930…c39`, preparer/supervisor/native bytes, host/runtime and ordered
shard population. After Claude's bounded HOLD, it pins the literal
canonical Mini paths for the gate, supervisor final and adapter output and
rejects copied evidence directories or any symlinked parent component. Exact
receipt nonce, all eight cheap parents, all eight N=30 parents, all eight label
paths and adapter Python 3.14.6 are also literal rather than merely shape-valid.
Exact file SHA-256s are `d46f0751…c5589` for the adapter and
`195fc327…7c82` for its tests. Commits `490757a`, `76195fd`, `f5fb18f` and
`0f4ef15` are superseded.

The independent review reproduced all literals, 29/29 tests and adversarial
copy/symlink/population probes. Both outcome branches remain design-only: PASS
may emit hard-tail Stage-C **design**, while FAIL/INCONCLUSIVE may diagnose
frozen evidence only. Neither may launch labels, compute, training, retry,
extension, promotion, or production. Closed marker:

`TEACHER_TERMINAL_ADAPTER_V2_REVIEW {"git":"5b26c4b4bdb678b2c780c8a4b6ed5b87e181964e","run_id":"teacher-v3-report-lcb-audit-v3-mini-149m","canonical_namespace":true,"reject_parent_symlinks":true,"literal_parent_populations":true,"literal_receipt_nonce":true,"exact_adapter_python":"3.14.6","receipt_sha256":"e293858c728437d6016a3f02a62a355c38a37a6028ad0d83e49423e1caf4a10d","preparation_sha256":"83892930fa8e7e8148960511ef0a87c3becbe77a87eaebf3c912458863644c39","output_name":"teacher_terminal_adapter_v2.json","fail_closed":true,"no_compute_authority":true,"verdict":"PASS"}`

At 21:38 Codex reopened the exact clean `5b26c4b` worktree, reproduced adapter
and test SHAs `d46f0751…c5589` / `195fc327…7c82`, and reran 29/29 focused
tests. The current-main live-parent verifier also reopened exact
`mc-s0-report-lcb`/RLCB-C1 and exited zero. The terminal closeout therefore has
no outstanding code or human-review dependency.

## Closed launch packet — retained until the terminal gate

Review these two pushed branches together:

- evaluator `codex/teacher-audit-v3-evaluator` at exact
  `f78e9047b50e7e254c76f8a1ff9490bc9aa75700`;
- external controller `codex/teacher-audit-v3-controller-prep` at exact
  `03995917346e674096cc879f7a15f3678f04d1d6`.

Ordered shasum-style material SHA-256:
`645b8f543ba88d24ba5fae29b82a5c7fd0fdc44f800b26330904ec98b55b894d`.

| reviewed material | SHA-256 |
|---|---|
| `server/scripts/teacher_v1_champion_audit.py` | `0a79aa6c3dc2f2bfef81e035bead8ac22974c0c27561908a60a38cd1edbf413a` |
| `server/tests/test_teacher_v1_champion_audit.py` | `976079baecb4e0730c02c7abe21a65940c2e4201e379db22421ae8f4f594a38c` |
| `server/scripts/teacher_champion_audit_prepare.py` | `c6f24b58eabe0ffaccb1ce38f6724100133075f4ebda0851e5615adba2bc4346` |
| `server/scripts/teacher_champion_audit_supervisor.py` | `07284fc0c99e678df0a1d02f8aabc06d7fa8d38837aa46099110ff908ae2f47f` |
| `server/tests/test_teacher_champion_audit_prepare.py` | `3de6d76723670b2aadc8080e5257b8269d81f0b19a53a7bf7f5a700c902203c5` |
| `server/tests/test_teacher_champion_audit_supervisor.py` | `3820be920b39232972f959f0dd2867b69227b5c79e9fada105da092b68195380` |

### Exact claim

- Fresh labels use the reviewed retry-aware continuation unchanged: 30
  accepted selection worlds plus 300 accepted disjoint report worlds; failed
  determinizations are unscored retries only within 1,200/12,000 attempt caps.
- The historical consumed asset remains byte-immutable at
  `d04d1c0fa507bab680da4d53eeb72325a97c8ca058aac0d01c16dfdcf44f7a34`.
  Its exact pre-retry metadata is validated as historical provenance; it is
  never rewritten or mistaken for the current label contract.
- The reviewed fresh complement remains byte-immutable at
  `82da0fd8a2f362dd2a8340847ccb7caaba1c2d58840cd0809d2353751999d94c`.
  A real no-write reopen on Mini recomputed 64 consumed + 64 fresh, zero
  overlap, exact 128-state union, and 64 joined parent-label records.
- Receipt/shard/gate schemas are v2 and bind both state assets separately,
  Stage-B state/gate and all 16 cheap/N=30 shards, exact evaluator Git/script,
  exact compiled engine, runtime flags, host, Python, folds, and run ID.
- The preparer copies 20 Stage-B parents plus two state assets exclusively
  into a new namespace, then creates one receipt. The supervisor owns all eight
  children, records heartbeat/exit/log/output hashes, kills siblings on first
  failure, and runs one terminal gate only after all eight finals reopen.
- Host is literally `Jerrys-Mac-mini.local`; Python is literally 3.14.6; the
  native engine SHA is
  `ef7c161829c607aad790e949e0a0bae7e04d8a3be7aea51b80d5108a1f566b4d`.
- Run ID is `teacher-v3-report-lcb-audit-v3-mini-149m`; output namespace is
  fresh `runs/logs/teacher-v1-entry-149m-v5`; retry/resume/overwrite and
  production promotion are false.

Measured locally: evaluator/Teacher battery 123/123; controller battery 29/29.
The exact staged Mini roots return zero preparer-preflight problems, 20/20
Stage-B parents, clean evaluator runtime/transition/continuation locks, and no
receipt, label, gate, log, exit, or partial artifact.

One no-write probe caught and repaired a genuine launch blocker before this
packet: the immutable consumed asset correctly carries the old continuation
metadata while the fresh asset carries retry admission. Exact `f78e904`
versions those two provenance contracts instead of demanding that historical
evidence be rewritten. Please specifically falsify that boundary.

### Literal authorized chain if review passes

Preparation (creates inputs/receipt only; launches no label):

```bash
/opt/homebrew/bin/python3.14 /Users/jerryyu/Projects/shengji-teacher-control-v3-mini/server/scripts/teacher_champion_audit_prepare.py \
  --producer-root /Users/jerryyu/Projects/shengji-teacher-producer-mini/server \
  --consumed-root /Users/jerryyu/Projects/shengji-teacher-consumed-mini/server \
  --fresh-asset-root /Users/jerryyu/Projects/shengji-teacher-fresh-asset-mini/server \
  --audit-root /Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server \
  --python /opt/homebrew/bin/python3.14 \
  --expected-stage-b-gate-sha256 f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694 \
  --expected-preparer-sha256 c6f24b58eabe0ffaccb1ce38f6724100133075f4ebda0851e5615adba2bc4346 \
  --expected-supervisor-sha256 07284fc0c99e678df0a1d02f8aabc06d7fa8d38837aa46099110ff908ae2f47f
```

Only after zero exit and exact receipt/preparation SHAs are printed, launch:

```bash
/opt/homebrew/bin/python3.14 /Users/jerryyu/Projects/shengji-teacher-control-v3-mini/server/scripts/teacher_champion_audit_supervisor.py \
  --audit-root /Users/jerryyu/Projects/shengji-teacher-audit-v3-mini/server \
  --python /opt/homebrew/bin/python3.14 \
  --expected-receipt-sha256 <PREPARER_RECEIPT_SHA256> \
  --expected-preparation-sha256 <PREPARER_PREPARATION_SHA256> \
  --expected-preparer-sha256 c6f24b58eabe0ffaccb1ce38f6724100133075f4ebda0851e5615adba2bc4346 \
  --expected-supervisor-sha256 07284fc0c99e678df0a1d02f8aabc06d7fa8d38837aa46099110ff908ae2f47f \
  --heartbeat-seconds 60
```

Please mutate historical/current continuation contracts, swap or omit either
state binding, alter host/Python/native bytes, change a parent/gate SHA, inject
experimental flags, collide an output/partial, fake receipt identity, produce
a zero-exit missing final, or mutate a shard/gate schema. PASS authorizes only
the exact command chain above and one terminal audit verdict; it authorizes no
Stage C, training, deployment, retry, extension, or production change.

Append exactly one marker to `HANDOFF_REVIEW.md`:

`TEACHER_FRESH_MINI_LAUNCH_V1_REVIEW {"evaluator_git":"f78e9047b50e7e254c76f8a1ff9490bc9aa75700","controller_git":"03995917346e674096cc879f7a15f3678f04d1d6","material_sha256":"645b8f543ba88d24ba5fae29b82a5c7fd0fdc44f800b26330904ec98b55b894d","mini_preflight":true,"receipt_authorized":true,"label_launch_authorized":true,"verdict":"PASS|HOLD"}`

If any probe fails, append a prose HOLD and do not emit a PASS marker.

## T1 finish path

1. **Complete:** exact launch review passed; the one-shot receipt and
   preparation were created and independently reopened.
2. **Running:** eight Mini label shards are owned by one supervisor. Do not
   launch a duplicate, retry, extension, or host migration.
3. After the supervisor publishes the finalized JSONL, reopen its ordered
   eight `label_sha256s`, gate SHA, gate return code, and verdict. Require
   return code 0 exactly for PASS and 4 exactly for FAIL/INCONCLUSIVE.
4. In a new `mktemp -d` namespace, rerun exact evaluator `f78e904` `gate`
   under `/opt/homebrew/bin/python3.14` with receipt `e293858c…a10d`, the
   literal eight label paths, and those eight terminal hashes. Accept its 0/4
   return-code contract, then require the recomputed gate bytes and SHA to
   match the supervisor gate exactly. This is aggregation only: no worlds.
5. Compute the finalized supervisor-JSONL SHA. Run reviewed adapter `5b26c4b`
   `create` once with the exact gate/progress paths and hashes into the sole
   canonical `teacher_terminal_adapter_v2.json`, then run `verify` with that
   adapter's exact SHA.
6. Record both terminal artifacts. PASS opens Stage-C/hard-tail **design**;
   FAIL/INCONCLUSIVE records frozen-evidence diagnosis/redesign. That closes
   T1. Neither branch automatically launches labels, training, or production.

## S3a terminal packet

The reviewed Mini screen completed 8/8 shards. Aggregate
`74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd`;
supervisor final
`d3f2b1ab48085ccf37534b5dd7f20ea6cf0d7644c6c49304b644ecf895169a6b`.
Structured-minus-production mean/LCB was `+0.997314/+0.596708`, versus
legacy-four `+0.877848/+0.497963`, and versus matched random widening
`+3.252848/+2.691652`. This is a mechanism result, not a full-game strength or
production result.

## CLOSED — S3a full-game duel core and controller PASS

Claude's 18:14 review put exacts `3e5fcc0` / `7b52d19` on HOLD for one
seed-hygiene defect and the resulting controller re-pin. The controller's own
falsifications otherwise passed, and Claude answered the sizing question:
four mirrored complete-round preflight clusters plus the 2× safety factor are
sufficient, provided the final literal packet freezes both fleet-hour and
per-shard wall caps. At 19:21 Claude passed repaired exacts `b5dee2e` /
`0085409`; the exact terminal markers are in `HANDOFF_REVIEW.md`.

The repair is pushed on branch `codex/s3a-full-game-duel-v2`. Core-only exact
`b5dee2e002b0d955534bfb9d2a2f7246e3a55f93` has runner SHA-256
`d04fd162a959986c0b0170df5f6f0a3f543c8a50fa90c7f776a2ecc5cd3bfb38`,
test SHA-256
`acf73c26e9fb71cd239438d1c4c0b1d03ba578afd906a327ba2942a7c8490a39`,
and ordered material SHA-256
`5d8d7e3f96514d84525f62c194f43445281c4fb825c5035c3a9ff03083f44267`.
The core/parent/structured-bury battery passes 48/48.

The repair names all four already consumed outcome-free sizing deal seeds
`151000000..151000003`, moves the first screen cluster to fresh seed
`153000003`, changes the screen run ID accordingly, and includes the consumed
population in the global collision proof. A mutation that puts the screen
back on a consumed sizing seed now refuses. No estimand, treatment, control,
gate, dose, screen size, confirmation size, or outcome authority changed.

This freezes a 2,048-cluster screen and independent 8,192-cluster
confirmation over mirrored complete-round signed level utility. Treatment is
exact live `mc-s0-report-lcb` with only structured bury enabled; controls are
the exact champion and its registered RNG-shifted matched null; the exact
champion is the common opponent. Preflight, screen and confirmation seed/role
streams use sparse populations proven globally disjoint. The score-free
preflight publishes timing/counters only with a 2× capacity projection. The
gate requires treatment LCBs above both controls, the two-sided null/champion
interval to contain zero, witnessed trigger/override, exact structured work
and zero feature dose in all controls. A screen PASS opens confirmation-packet
review only; even a confirmation PASS cannot deploy.

Claude reproduced the original `151000000` collision, verified the new
four-seed exclusion/fresh identity, and mutation-proved the guard. Core PASS
grants no preflight or strength launch. The closed marker is:

`S3A_FULL_GAME_DUEL_CORE_V1_REVIEW {"git":"b5dee2e002b0d955534bfb9d2a2f7246e3a55f93","material_sha256":"5d8d7e3f96514d84525f62c194f43445281c4fb825c5035c3a9ff03083f44267","consumed_sizing_seeds_excluded":true,"fresh_screen_seed0":153000003,"paired_complete_round":true,"global_stream_separation":true,"score_free_preflight":true,"strength_launch_authorized":false,"production_promotion":false,"verdict":"PASS|HOLD"}`

### Controller review — PASS

On the same branch, descendant exact
`00854092104cd5dd0c765404bf198871fb523e31` re-pins the controller to core
`b5dee2e`. Controller SHA-256 is
`92c057145ed2049922a403d50f4bacc02afc8b9910b1d7720ea1e1b2f45ffeeb`,
test SHA-256
`0fcb7508c3e80516f528fc681c713ee04a3e3b9b7be4f14e896db78c1fdc4114`,
and ordered material SHA-256 is
`dbd9a79754347f36956d3390ff1d4fd18abbd6f765c1e9404edc6d2f2981382c`.
Controller-focused tests pass 13/13; the combined battery passes 61/61.

Exacts `34154f9` and `7b52d19` are superseded. A no-write Air probe first refused missing
RLCB-C1 bytes; after staging the exact 15 MB evidence namespace and confirmed
native binary, the full reopener still correctly refused because historical
aggregate verification is pinned to Mini's original `execution_host` and
Python. Treating copied bytes as portable would weaken the live-parent gate.
Exact `0085409` therefore registers Mini only and mutation-tests that Air is
inadmissible. A future Air lane requires a separately designed portable-parent
attestation; this preflight does not invent one.

The controller binds exact Git/source bytes, canonical Mini venv Python
3.14.3, one registered host, live-parent/runtime bytes, capacity budgets, sparse population, exact
command and a fresh namespace. It owns one score-free child, receipt,
heartbeats, exit/log/output hashes and a fully recomputed terminal final.
Outcome fields, run mixing, projection/capacity lies, telemetry/counter drift,
control activation, progress splicing, overwrite/retry and authority mutation
refuse. Its strongest possible terminal status is
`AUTHORIZE_SCREEN_PACKET_REVIEW`; it cannot launch a screen.

Claude verified the new ancestry, canonical Mini 3.14.3 parent reopen,
Homebrew 3.14.6 refusal and prior controller falsifications. This closed review
froze no numeric budget or launch command; the new literal packet below does.
The closed marker is:

`S3A_DUEL_PREFLIGHT_CONTROLLER_V1_REVIEW {"git":"00854092104cd5dd0c765404bf198871fb523e31","core_git":"b5dee2e002b0d955534bfb9d2a2f7246e3a55f93","material_sha256":"dbd9a79754347f36956d3390ff1d4fd18abbd6f765c1e9404edc6d2f2981382c","mini_only":true,"exact_python":"3.14.3","homebrew_3_14_6_refuses":true,"air_refuses":true,"one_shot":true,"score_free":true,"screen_packet_review_only":true,"preflight_launch_authorized":false,"strength_launch_authorized":false,"production_promotion":false,"verdict":"PASS|HOLD"}`

### Frozen literal capacity inputs

These inputs authorize nothing until the literal packet below passes. Closed RLCB-C1
provides 4,096 terminal Mini rounds under the exact 3.14.3/native/report-LCB
runtime. Its report-LCB team averaged 8.994817 search-seconds per round. One
S3a cluster contains six rounds with two report-LCB teams, giving a
107.937802-second outcome-blind cost proxy before the structured-bury
increment. Under the protocol's 2× factor, that projects to:

- screen: 122.81 fleet-hours / 15.35 max-shard hours;
- confirmation: 491.24 fleet-hours / 61.40 max-shard hours;
- four-cluster score-free preflight: about 7.20 minutes.

Candidate final caps are screen `192/24` and confirmation `768/96`
fleet/max-shard hours. All four values encode the same 168.75-second maximum
cluster mean, roughly 56% above the historical proxy. The actual score-free
preflight—not this proxy—must terminate at `TERMINAL_CAPACITY_HOLD` if any
projection exceeds a cap. The passed core/controller reviews were necessary
but insufficient; exact merge Git, source hashes, these four numbers,
heartbeat 30, canonical Mini command and the fresh namespace are frozen in the
separate literal launch review below.

Integration `fcad972a088724c7f24cbfb9759f8355857928ae` descends from reviewed
controller `0085409` and then-current main `804782a`; its full
S3a/parent/progress battery passed 76/76 under canonical Mini Python 3.14.3.
The duel runner remains byte-identical at `d04fd162…3bfb38`.

The first literal packet is **superseded**: its marker said
`teacher_exclusive=true`, but exact `fcad972` neither hashed that prerequisite
nor refused a concurrent Teacher. Exact current-main merge
`e6f2493943d5ec2b826d852ec62a782bef10e412` adds only that missing launch
boundary plus three tests, including a non-vacuous `_identity_context` wiring
witness. New controller/test SHA-256s are `5ca78416…09434` /
`a40ed76b…51d22`; ordered material is `02255a7a…f741c`; focused tests pass
16/16.

## CLOSED REVIEW — Teacher-guarded S3a Mini preflight PASS

This packet authorizes only four mirrored complete-round timing/counter
clusters after the live Teacher supervisor has terminated and released Mini.
It reads no duel outcome and can end only at screen-packet review authority or
a terminal protocol/capacity HOLD. It cannot launch the 2,048 screen.

Claude independently reproduced exact `e6f2493`, all source/material hashes,
16/16 focused tests and the four equivalent 168.75-second cap calculations.
The authentic canonical launch-side probe computed frozen contract SHA-256
`5e0f6ade690f308b812cdb8ff73e87df7f3619514f6a89c27c9b1cbb15b44653`.
Claude corroborated the contract function and every literal input; an exact
second digest computation correctly refused because Teacher is still live.
The controller recomputes and binds the digest at launch, so drift still fails
closed before work.
The review mutation-proved every Teacher release predicate and the
`_identity_context` wiring. A real invocation while Teacher was live refused
at exit 3, named the supervisor plus seven workers, and left the `18b`
namespace absent. The exact PASS marker is preserved in `HANDOFF_REVIEW.md`.

Before launch, the canonical root `/Users/jerryyu/Projects/shengji` must be
clean and detached at `e6f2493`; it must remain there until the controller
terminates. The controller itself now requires the canonical Teacher
supervisor final to be regular/unlinked, its `.partial` to be absent, and no
matching Teacher supervisor/worker process. Freeze screen caps at `192`
fleet-hours / `24` max-shard-hours, confirmation caps at `768` / `96`, and
heartbeat at 30 seconds. The exact command is:

```bash
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
server/.venv/bin/python server/scripts/s3a_bury_duel_preflight.py launch \
  --expected-git e6f2493943d5ec2b826d852ec62a782bef10e412 \
  --expected-runner-sha256 d04fd162a959986c0b0170df5f6f0a3f543c8a50fa90c7f776a2ecc5cd3bfb38 \
  --expected-controller-sha256 5ca78416db7194a2fe5dca07936240785f32643d7348d692096a92cb1c609434 \
  --expected-host Jerrys-Mac-mini.local \
  --screen-fleet-hours 192 \
  --screen-max-shard-hours 24 \
  --confirm-fleet-hours 768 \
  --confirm-max-shard-hours 96 \
  --heartbeat-seconds 30
```

This command remains dormant until the executable Teacher guard clears. Its
strongest possible terminal status is `AUTHORIZE_SCREEN_PACKET_REVIEW`; it
authorizes no screen, confirmation, strength conclusion, retry, promotion or
production change.

## Standing rules

- Failed and consumed evidence namespaces are immutable; no same-recipe retry.
- Review markers authorize only the scope they name.
- Experimental posterior-changing sampler/ballot flags remain off.
- Continue useful implementation while review/compute runs; utilization never
  justifies moving an evidence gate.
- All commits made for this work are pushed to GitHub.
