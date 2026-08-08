# Active Claude/Codex handoff

Last update: 2026-08-08 16:22 EDT. This is the executable mailbox, not a
history. Terminal results live in `AI_POLICIES.md`, queue order in
`BACKLOG.md`, exact run state in `JOBS.md`, and review history in
`HANDOFF_REVIEW.md`.

## Current truth

| area | status | next action |
|---|---|---|
| Production | **LIVE / CONFIRMED** | Fly release 17 runs compiled `mc-s0-report-lcb`; RLCB-C1 confirmed `+0.338379 +/- 0.067706` versus `mc-strong`. Runtime rollback is release 16; policy rollback is `mc-strong`. |
| T1 Teacher | **MINI LAUNCH REVIEW OPEN / NO RECEIPT OR LABEL** | The untouched 64-state complement is reviewed and frozen. Exact evaluator/controller, four immutable Mini roots, Python 3.14.6, native engine, and all 22 input assets pass no-write preflight. Review the packet below; PASS authorizes its one-shot receipt plus eight Mini shards. |
| T2 S3a structured bury | **512-STATE MECHANISM PASS** | Structured widening passed all three frozen state-level LCBs. Design a fresh full-game duel against exact production plus a champion-matched null; no duel is yet authorized. |
| T2 S3b sampled exact | **TERMINAL HOLD** | The frozen 250,000-node preflight cap fired. Never retry or relax v2. |
| T2 learner O0-v2 | **INTEGRATION MERGED** | Exact integration passed review; a fresh population/runner/gate packet is next. No training is authorized. |

## OPEN NOW — fresh Teacher audit launch review on Mini

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

1. Obtain the exact launch marker above.
2. Run the preparer once, record/reopen its receipt and preparation SHAs, then
   run the supervisor once on Mini.
3. Preserve the terminal PASS/FAIL/INCONCLUSIVE gate and independently verify
   all child/aggregate bindings.
4. Route the terminal verdict through the already-reviewed adapter: PASS opens
   Stage-C/hard-tail **design**; FAIL/INCONCLUSIVE records redesign/stop. That
   closes T1. No branch automatically launches training.

## S3a terminal packet

The reviewed Mini screen completed 8/8 shards. Aggregate
`74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd`;
supervisor final
`d3f2b1ab48085ccf37534b5dd7f20ea6cf0d7644c6c49304b644ecf895169a6b`.
Structured-minus-production mean/LCB was `+0.997314/+0.596708`, versus
legacy-four `+0.877848/+0.497963`, and versus matched random widening
`+3.252848/+2.691652`. This is a mechanism result, not a full-game strength or
production result.

## Standing rules

- Failed and consumed evidence namespaces are immutable; no same-recipe retry.
- Review markers authorize only the scope they name.
- Experimental posterior-changing sampler/ballot flags remain off.
- Continue useful implementation while review/compute runs; utilization never
  justifies moving an evidence gate.
- All commits made for this work are pushed to GitHub.
