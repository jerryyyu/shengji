# Fleet job ledger

Last compacted: 2026-08-08 09:32 EDT. This file owns current compute and short
terminal stubs only. The exact 810-line pre-compaction ledger is archived at
`docs_archive/jobs-through-2026-08-08.md`, SHA-256 `26beff936f6c0744b220fc79e233163c8f09acde8a13adcba5450327ad132252`.
Detailed interpretation belongs in `AI_POLICIES.md`; execution order belongs
in `BACKLOG.md`.

## RUNNING — Teacher-v3 champion audit-v2 on Air

Stage B is terminal PASS. Its gate SHA is
`f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694`;
cheap-minus-gold mean regret was `-0.002686` and the one-sided upper 95% bound
was `0.019548 < 0.10`.

Preserve failed audit-v1 root `~/Projects/shengji-teacher-audit-air` at exact
`182d1df`. Receipt creation exited 3 before labels because its verifier
rejected its own still-owned hard-linked partial. Never retry or adopt it.

The single authorized v2 attempt launched at 08:16 EDT:

- evaluator root `~/Projects/shengji-teacher-audit-v2-air`, exact
  `1866132766c7f16542bc27e730622e2dfea639ae`;
- evaluator script SHA
  `c7b47a7a0305f6067129cc7b19517d9a983efff70085f83edc0d39475955d6cb`;
- controller `edc923f`, supervisor PID 95339;
- receipt `ce51b826d4f04549b961f795868cc4c6c5f90124a8552ce76fe2d3ab0bd471d0`;
- preparation
  `7f89a86c2e0803d83473d8ccca978dd99dd010e467761d0d4429a3598c166605`;
- label PIDs 95345--95352; eight fixed 32-selection/32-report shards;
- operator log `~/teacher-v3-audit-v2-supervisor.log`.

At 09:32 all eight workers plus the supervisor were live, zero finals had
published, and heartbeats were regular. Inspect only liveness
and score-free counters. Do not open partial outcomes, retry, resume, migrate,
duplicate or alter workers. This supervisor alone may invoke one terminal gate
after eight exact zero exits.

Terminal handling is outcome-independent and predeclared now. Do nothing until
the Air supervisor publishes both regular finals with no surviving partials
and the repaired adapter receives its independent PASS marker. Then:

1. hash the Air gate and supervisor final in place and copy those exact bytes
   without opening the gate payload to
   `server/runs/logs/teacher-v3-audit-v2-terminal/` on Mini;
2. verify the local hashes equal the Air hashes;
3. use a clean detached worktree at exact reviewed repair commit
   `2de0824738e3e5a45ba317876b0abb3930315249` to run
   `teacher_terminal_adapter.py create`, passing the two exact hashes and
   `--expected-git 2de0824738e3e5a45ba317876b0abb3930315249`;
4. publish only
   `server/runs/logs/teacher-v3-audit-v2-terminal/teacher_terminal_adapter_v1.json`,
   then reopen it with the adapter's `verify` mode and its exact SHA-256.

The adapter's output branch may be read only after those identity checks.
PASS can emit only a review-required hard-tail Stage-C design;
FAIL/INCONCLUSIVE can emit only an existing-evidence diagnostic. Neither
branch authorizes compute, labels, training, promotion, retry or same-recipe
extension. Never overwrite any terminal mirror or adapter output.

## Fleet availability

- **Air:** occupied by the eight-way Teacher audit; do not add load that changes
  its wall time or one-shot evidence boundary.
- **Mini:** no long strength job. Both hosts are 10-core Apple M4s; the earlier
  6.8-hour Teacher number was a Mini sizing projection, not evidence Mini is
  faster. Use Mini for reviewed short preflights/screens, preferably under one
  hour.
- **Local dev server:** one idle SmartBot server may appear on port 8899; it is
  not a strength job.

## Terminal job index

| date | job | verdict / headline | evidence anchor |
|---|---|---|---|
| 08-08 | Teacher Stage B | **PASS**; regret upper bound `0.019548 < 0.10` | gate `f607b489...89694` |
| 08-08 | Suphx O0 | **SELECT NONE**; aggregate oracle signal, seed-1 reversal | gate `592a009a...bd407c` |
| 08-07 | RLCB-C1 | **CONFIRM**; report-LCB `+0.338379 +/- 0.067706`, null flat | aggregate `83f5a9df...f5ef5ea`; closeout `06dd487d...b7aae5` |
| 08-07 | production latency | **LIVE**; release 17, off-loop isolated search | image `latency-cd6789e`; manifest `047bcfe4...5b300` |
| 08-07 | V11 direct-v2 | **SELECT NONE**; `-0.141113 +/- 0.069823` versus current | aggregate `b7c90ba4...05d21ad` |
| 08-07 | Direct-Q 144M | **SELECT NONE**; positive gameplay, failed held-out learning | aggregate `1fa6789e...ce791` |
| 08-07 | formal S0 | **SELECT NONE**; numerical S0c outcome unread/nonretryable | closeout `ef0a365...fde9a` |
| 08-05 | DEV-512 ballot | **SELECT NONE**; no design advanced, CALIB/REPORT sealed | state asset `af78748586034f6f...85d3e7b` |
| 08-04 | sampler Package H | **PASS** within bounded strict scope; not posterior calibration | commit `aea3774`; `certify_sampler_v3.json` |

No terminal row authorizes an extension unless its original gate says so.
Screens remain screens; failed and partial namespaces are preserved in place.

## Next admitted compute

The live order is in `BACKLOG.md`. Pushed `05ea1d1` versions S3a/S3b against
exact `mc-s0-report-lcb`; Claude independently passed exact material
`66be133c…e17c` at 09:54 and conveyed no strength or production authority.
Pushed `66d6836` adds S3a's outcome-free timing receipt on exact reserved
151M states. Its initial 09:56 PASS was superseded by HOLD after an arbitrary
nested-work-field probe passed. The repaired exact nested schema and counter
equalities were pushed at `2de0824` and independently passed review. The
subsequent v1 run exposed a separate publication-only false positive described
below; a fresh v2 repair now requires review.

The live-parent PASS admitted the first score-free S3b timing job on Mini.
That exact attempt is now terminal HOLD after the exact solver exceeded its
frozen cumulative node bound before treatment cluster 1 completed. S3a's
separate repaired sizing packet independently passed review at exact
`2de0824` / material `fb0fa7ba…6e16`, but its v1 publication refused after
both hidden states completed. A fresh-schema/fresh-seed v2 is next only after
review, and no two timing jobs may overlap.

1. S3b two-cluster throughput preflight under hard caps screen `200`
   fleet-hours / `30` max shard-hours and confirmation `800` / `120`;
2. S3a two-state timing preflight under hard caps `400` fleet-hours / `60`
   max shard-hours.

Neither preflight retains strength outcomes or authorizes its corresponding
screen. Neither lane may inherit stale formal-S0 `mc-strong` authority. While
review or timing is live, implementation continues off-host. Teacher terminal
branch routing's initial PASS was also superseded by HOLD; its repaired
gate-to-supervisor label-population binding is pushed at `2de0824` and awaits
re-review. O0-v2
CRN/logit-margin mechanics are pushed rather than competing for the measured
host.

The exact first launch is predeclared as
`s3b-report-lcb-v2-throughput-mini-v1`, output
`server/runs/logs/s3b-report-lcb-v2-throughput-mini-v1.json`, seeds
141,000,000--141,000,001. It runs only after a PASS marker for
`T2_LIVE_PARENT_V1_REVIEW` and uses the literal command:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
  server/.venv/bin/python server/scripts/s3b_endgame_strength.py preflight \
  --out server/runs/logs/s3b-report-lcb-v2-throughput-mini-v1.json \
  --screen-fleet-hour-cap 200 --screen-shard-wall-hour-cap 30 \
  --confirm-fleet-hour-cap 800 --confirm-shard-wall-hour-cap 120
```

At `ec2b886`, the score-free admission dry check reopened exact
`mc-s0-report-lcb` on `Jerrys-Mac-mini.local`, required the compiled/strict
runtime and returned zero protocol problems. It executed no round. The output
path was absent. A review PASS admits this preflight only, not a strength
screen.

The first S3b invocation at 09:56 refused at the initial clean-tree check
because Claude appended the S3a/Teacher review records concurrently. It exited
3 before `run_arm`, created no final or partial, consumed no registered round,
and produced no timing or strength result. Preserve this operational note; the
unchanged command may start once those review bytes are committed and pushed.

The unchanged command then ran once from clean exact head
`cd44ea8a6fefb8fba258d01bcca4bed98169a217` on Mini. It printed only
`throughput-only exact: starting 2 clusters; strength scores hidden`; before
the first `1/2` completion it exited 1 with
`ExactEndgameBudgetExceeded: exact endgame exceeded max_nodes=250000`. The
failure propagated deliberately from `_exact_endgame_value`: a budget refusal
invalidates the run instead of silently mixing exact and heuristic work. The
unlinked temporary score sink disappeared, and both final and `.partial`
receipt paths were verified absent. Therefore no timing projection or
strength outcome exists, the required zero-overflow gate is false, and the
2,048 screen is unauthorized. Do not rerun seed 141,000,000, raise the v2 cap,
add fallback semantics or reinterpret this as a numerical strength result.

The exact S3a launch is now predeclared as
`s3a-bury-v2-throughput-mini-v1`, output
`server/runs/logs/s3a-bury-v2-throughput-mini-v1.json`, hardcoded seeds
151,000,000--151,000,001. The literal command is:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
  server/.venv/bin/python server/scripts/s3a_bury_throughput.py run \
  --out server/runs/logs/s3a-bury-v2-throughput-mini-v1.json \
  --screen-fleet-hour-cap 400 --screen-shard-wall-hour-cap 60
```

It may persist only timing, exact work counters, frozen caps and their derived
placement decision. It may not retain actions, scores or raw records and may
not start the 512-state mechanism screen.

That exact v1 command ran once from clean head `b3ac6fd`. Both hidden states
151,000,000–151,000,001 completed, then receipt validation exited 3 with
`throughput receipt persists forbidden outcome fields:
runtime_identity.digests.cards`. This is an authenticated source-code digest
name produced by `require_real_context`, not a gameplay card field. Both final
and `.partial` paths remain absent. No score/action/raw record printed or
survived, but the two states are consumed and must never be replayed.

The bounded v2 repair changes only the receipt namespace/seeds and publication
validation: schema `s3a-bury-throughput-preflight-v2`, fresh seeds
151,000,002–151,000,003, and an outcome scan that exempts the equality-bound
`runtime_identity` and `live_champion_parent` trees while recursively scanning
every other receipt surface. Top-level and nested exact schemas plus fixed-
identity equality remain mandatory. A realistic `digests.cards` fixture now
passes; identity drift and actual `caps.cards` outcome injection refuse.
Focused tests pass 11/11 and the broad boundary matrix passes 86/86. No v2 run
is authorized before independent review.

The fresh v2 output is predeclared as
`server/runs/logs/s3a-bury-v2-throughput-mini-v2.json`; its `.partial` and
final are absent. After, and only after,
`S3A_THROUGHPUT_V2_REVIEW` PASS, run this literal command once:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
  server/.venv/bin/python server/scripts/s3a_bury_throughput.py run \
  --out server/runs/logs/s3a-bury-v2-throughput-mini-v2.json \
  --screen-fleet-hour-cap 400 --screen-shard-wall-hour-cap 60
```

The script hardcodes fresh seeds 151,000,002–151,000,003 and refuses a dirty
or unauthenticated runtime through `S3A.require_real_context()`. A receipt PASS
still authorizes placement only; the 512-state screen remains a separate gate.

## Archive pointers

- Exact pre-compaction ledger:
  `docs_archive/jobs-through-2026-08-08.md`.
- Daily chronology: `docs_archive/daily-log-2026-08-04.md` through the current
  daily log.
- Canonical AI numbers/interpretation: `AI_POLICIES.md`.
- Current milestone/queue: `BACKLOG.md`.
- Executable Claude/Codex mailbox: `HANDOFF_ACTIVE.md`.
