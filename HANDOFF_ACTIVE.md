# Active Claude/Codex handoff

Last update: 2026-08-08 18:10 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, queue order in
`BACKLOG.md`, exact run state in `JOBS.md`, and review history in
`HANDOFF_REVIEW.md`.

## Current truth

| area | status | next action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 confirmed `+0.338379 +/- 0.067706` versus `mc-strong`. Runtime rollback is release 16; policy rollback is `mc-strong`. |
| T1 Teacher | **RUNNING ON MINI / ADAPTER REVIEW PASS** | Claude passed both the exact launch packet and terminal adapter `5b26c4b`. Supervisor `teacher-v3-report-lcb-audit-v3-mini-149m` owns all eight workers. Wait for one terminal gate, independently recompute it, then create one adapter artifact. |
| T2 S3a structured bury | **CORE + MINI-ONLY PREFLIGHT CONTROLLER REVIEW OPEN / NO LAUNCH** | Exact core `3e5fcc0` and corrected descendant controller `7b52d19` are pushed; combined battery 59/59. An Air no-write probe proved the historical parent is Mini-runtime-bound, so Air now refuses at config admission. No budgets command or compute is authorized. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The frozen 250,000-node preflight cap fired. Never retry or relax v2. |
| T2 learner O0-v2 | **INTEGRATION MERGED** | Exact integration passed review; a fresh population/runner/gate packet is next. No training is authorized. |

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

Outcome-blind runtime audit at 17:30 found ~17% of outer worlds and ~13% of a
candidate-count × remaining-ply work proxy complete after ~56 minutes. Because
the frozen partition is highly imbalanced (1–14 candidates and ply 0–72), a
simple slowest-shard projection is roughly 10–16 hours. This is not a stall:
all eight workers remain CPU-bound and every log advances. It does mean a
same-evening terminal gate is unlikely. Never use this operational forecast to
read or stop on outcomes; do not repartition, duplicate, migrate or mutate the
reviewed one-shot chain.

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
3. Preserve the terminal PASS/FAIL/INCONCLUSIVE gate and independently verify
   all child/aggregate bindings.
4. After adapter-v2 review passes, route the terminal verdict through exact
   `5b26c4b`: PASS opens Stage-C/hard-tail **design**;
   FAIL/INCONCLUSIVE records redesign/stop. That closes T1. No branch
   automatically launches training.

## S3a terminal packet

The reviewed Mini screen completed 8/8 shards. Aggregate
`74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd`;
supervisor final
`d3f2b1ab48085ccf37534b5dd7f20ea6cf0d7644c6c49304b644ecf895169a6b`.
Structured-minus-production mean/LCB was `+0.997314/+0.596708`, versus
legacy-four `+0.877848/+0.497963`, and versus matched random widening
`+3.252848/+2.691652`. This is a mechanism result, not a full-game strength or
production result.

## OPEN REVIEW — S3a full-game duel protocol core

Review pushed branch `codex/s3a-full-game-duel-v1` at exact
`3e5fcc07d5bc64efa09d6eb7e9e07bc19d367c82`. Material SHA-256 is
`caa94f6eb016180c27d10dfec7766d2683cf971d812d7bddeac0c1bcc15074d6`;
runner SHA-256 is `e47870c8…a5482b2`, test SHA-256
`1de61d20…edcdf4`. Focused plus exact-parent/structured-bury battery passes
47/47.

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

Please mutate parent identity, either S3a switch, candidate cap, rollout or
ballot identity, null shift, cross-population seed reuse, run/phase identity,
paired contrast sign, exact-work/sampler reconciliation, a control feature
counter, preflight score leakage, capacity bounds, shard population/hash, and
screen-parent authority/runtime. Also assess whether four score-free preflight
clusters plus the 2× safety factor are enough for this tail-heavy full-game
cost. This is a **core-only** review: the one-shot receipt/supervisor is not yet
present, so PASS grants no preflight or strength launch.

Append exactly one marker to `HANDOFF_REVIEW.md`:

`S3A_FULL_GAME_DUEL_CORE_V1_REVIEW {"git":"3e5fcc07d5bc64efa09d6eb7e9e07bc19d367c82","material_sha256":"caa94f6eb016180c27d10dfec7766d2683cf971d812d7bddeac0c1bcc15074d6","paired_complete_round":true,"global_stream_separation":true,"score_free_preflight":true,"one_shot_controller_present":false,"strength_launch_authorized":false,"production_promotion":false,"verdict":"PASS|HOLD"}`

### OPEN companion review — score-free one-shot controller

On the same branch, corrected descendant exact
`7b52d19d5d5eccf36a070c4814238b2ceadd6269` adds only the controller and its
tests; the reviewed core bytes remain unchanged. Controller SHA-256 is
`9d5048e6…9efa98`, test SHA-256 `9fc6d4c1…c96c9f`, ordered material SHA-256
`e213922380c595f4e1ef5ca3d1aa525a51a024084b8cb407f2e5d99dc4f5c1c5`.
Controller-focused tests pass 12/12; the combined battery passes 59/59.

Exact `34154f9` is superseded. A no-write Air probe first refused missing
RLCB-C1 bytes; after staging the exact 15 MB evidence namespace and confirmed
native binary, the full reopener still correctly refused because historical
aggregate verification is pinned to Mini's original `execution_host` and
Python. Treating copied bytes as portable would weaken the live-parent gate.
Exact `7b52d19` therefore registers Mini only and mutation-tests that Air is
inadmissible. A future Air lane requires a separately designed portable-parent
attestation; this preflight does not invent one.

The controller binds exact Git/source bytes, Python 3.14.6, one registered
host, live-parent/runtime bytes, capacity budgets, sparse population, exact
command and a fresh namespace. It owns one score-free child, receipt,
heartbeats, exit/log/output hashes and a fully recomputed terminal final.
Outcome fields, run mixing, projection/capacity lies, telemetry/counter drift,
control activation, progress splicing, overwrite/retry and authority mutation
refuse. Its strongest possible terminal status is
`AUTHORIZE_SCREEN_PACKET_REVIEW`; it cannot launch a screen.

Please falsify the controller and specifically assess canonical-path/symlink
handling, the Mini-only boundary, child/process cleanup, score-free
coverage, terminal recomputation, and whether a malformed/HOLD artifact can
acquire review authority. This review still freezes no host or numeric budget;
those belong to a final literal launch packet after the core review resolves
the four-cluster/2× sizing question.

Append exactly one marker:

`S3A_DUEL_PREFLIGHT_CONTROLLER_V1_REVIEW {"git":"7b52d19d5d5eccf36a070c4814238b2ceadd6269","core_git":"3e5fcc07d5bc64efa09d6eb7e9e07bc19d367c82","material_sha256":"e213922380c595f4e1ef5ca3d1aa525a51a024084b8cb407f2e5d99dc4f5c1c5","mini_only":true,"air_refuses":true,"one_shot":true,"score_free":true,"screen_packet_review_only":true,"preflight_launch_authorized":false,"strength_launch_authorized":false,"production_promotion":false,"verdict":"PASS|HOLD"}`

## Standing rules

- Failed and consumed evidence namespaces are immutable; no same-recipe retry.
- Review markers authorize only the scope they name.
- Experimental posterior-changing sampler/ballot flags remain off.
- Continue useful implementation while review/compute runs; utilization never
  justifies moving an evidence gate.
- All commits made for this work are pushed to GitHub.
