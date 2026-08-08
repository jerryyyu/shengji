# Fleet job ledger

Last reconciled: 2026-08-08 15:13 EDT. This file owns current compute and short
terminal stubs only. The exact 810-line pre-compaction ledger is archived at
`docs_archive/jobs-through-2026-08-08.md`, SHA-256 `26beff936f6c0744b220fc79e233163c8f09acde8a13adcba5450327ad132252`.
Detailed interpretation belongs in `AI_POLICIES.md`; execution order belongs
in `BACKLOG.md`.

## OPEN REVIEW — exact S3a 512-state Mini screen

Mini is idle. The one-shot controller is pushed at exact
`14548d3da31c3cfe899cbd7e572614ae05242c0a`, material
`4f74aa44…1b9c`; 55/55 full boundary tests and a no-write exact Mini admission
pass. Namespace
`server/runs/logs/s3a-bury-v2-screen-136m-v1` is absent. Launch is blocked
only on a PASS `S3A_SCREEN_LAUNCH_V1_REVIEW` marker.

After PASS, make the canonical root clean and detached at exact `14548d3`,
reconfirm namespace absence, then run exactly once:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
  server/.venv/bin/python server/scripts/s3a_bury_screen_supervisor.py launch \
  --expected-git 14548d3da31c3cfe899cbd7e572614ae05242c0a \
  --expected-runner-sha256 6feb06ea6571c6eea82fe0fd247528ec3bc87d201b1a4c5254d4356159ec4e83 \
  --expected-controller-sha256 d73a0b1ceab55cd067572c47eae324eb662ca2f402ecbf0d08ad743d42d4d69c \
  --heartbeat-seconds 30
```

The controller launches eight fixed shards concurrently, prints and persists
heartbeats, then aggregates and independently recomputes. Any failure consumes
the namespace and forbids retry. A terminal PASS is only a state-level
mechanism signal permitting design of a fresh live-champion duel; this command
cannot promote or deploy anything.

## TERMINAL OPERATIONAL REFUSAL — Teacher-v3 champion audit-v2 on Air

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
- controller `edc923f`, former supervisor PID 95339;
- receipt `ce51b826d4f04549b961f795868cc4c6c5f90124a8552ce76fe2d3ab0bd471d0`;
- preparation
  `7f89a86c2e0803d83473d8ccca978dd99dd010e467761d0d4429a3598c166605`;
- former label PIDs 95345--95352; eight fixed 32-selection/32-report shards;
- operator log `~/teacher-v3-audit-v2-supervisor.log`.

At 13:36 all nine processes were dead. Shard 6 returned `3`; the supervisor
then terminated the other seven workers, whose exit records are `-15`. Its
terminal log ended at state `149000349:4:0`, after 32/32 selection worlds and
13/32 report worlds, with `invalid champion continuation:
TeacherProtocolError: champion report fold is incomplete` at candidate 9,
world 13, downstream decision 6.

There are zero label finals. `champion_audit_gate_v1.json` and regular
`champion_audit_supervisor_v1.jsonl` are absent; only the supervisor `.partial`
remains. No partial outcome was opened. The reviewed terminal adapter cannot
run without those regular finals, so this is no Teacher strength/fidelity
result and no PASS/FAIL/INCONCLUSIVE gate. Preserve the entire Air root. Never
resume, retry, migrate, duplicate, delete or adopt audit-v2. T1 remains open
pending a reviewed diagnosis and an explicit fresh-run/closeout decision.

Diagnostic-only branch `b7534ee` independently passed review at 14:36.
It changes no acceptance rule and authorizes no compute; its purpose is to
make a future synthetic preflight distinguish short work, rejected retries,
contract drift and telemetry drift without reading outcomes. Exact compiled
Teacher boundary tests pass 147/147. Material SHA-256 is
`8ede4d351346fc636d5e7dff43f694bfc44c81660eb980358a7ae9b4e8b643e7`.
The PASS authorizes synthetic reproduction and v3 contract design only; a
fresh Teacher receipt or label attempt remains unauthorized.

## Fleet availability

- **Mini:** currently has no strength job and is the default placement for all
  newly authorized long or short compute. This is an owner preference even
  when Air has similar nominal cores.
- **Air:** Teacher audit processes are dead; preserve its failed v2 root. Use
  Air as overflow only, or when a recorded benchmark/constraint justifies it.
- **Local dev server:** one idle SmartBot server may appear on port 8899; it is
  not a strength job.

## Terminal job index

| date | job | verdict / headline | evidence anchor |
|---|---|---|---|
| 08-08 | S3a v2 sizing | **CAPACITY PASS**; 0.142 fleet-hours / 0.0178 max-shard hours under frozen 400/60 caps | receipt `cf770277...5c431` |
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
below; exact v2 repair `c784e6d` / material `34993502…092d` passed review at
14:33 and admits only the predeclared two-state Mini sizing run.

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
review or timing is live, implementation continues off-host. The Teacher
terminal adapter repair passed at `2de0824` but is inapplicable to failed v2;
diagnostic-only branch `b7534ee` passed review but authorizes only synthetic
reproduction and v3 contract design, not evidence compute.
O0-v2 mechanics remain unchanged; exact public-key integration branch
`dd730a8` / material `639c259b…a0494b` also awaits review and has no training
authority, so it does not compete for the measured host.

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
The final `claim_boundary` repair is pushed at `c784e6d`; focused tests pass
12/12 and the broad boundary matrix passes 87/87. Claude independently passed
exact material `34993502…092d` at 14:33. This authorizes only the two-state
outcome-free Mini sizing command below; no registered 136M state or 512-state
strength screen is authorized.

The fresh v2 output was predeclared as
`server/runs/logs/s3a-bury-v2-throughput-mini-v2.json`. After exact review
PASS, this literal command ran once from clean `79ab7d2`:

```bash
env -u SHENGJI_WEIGHTED_SPLITS -u SHENGJI_UNIFORM_DEAL \
  -u SHENGJI_PHYSICAL_FILLS -u SHENGJI_ALLOW_BALLOT_MISMATCH \
  SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 \
  server/.venv/bin/python server/scripts/s3a_bury_throughput.py run \
  --out server/runs/logs/s3a-bury-v2-throughput-mini-v2.json \
  --screen-fleet-hour-cap 400 --screen-shard-wall-hour-cap 60
```

It completed both states in `0.998834s` and published a regular unlinked final;
the `.partial` is absent. SHA-256 is
`cf7702770e2dd416b0ecfcdcc2ba6a5c32ab262aef0319d87346d05bcdf5c431`,
and the exact CLI verifier reopened it. Selection accepted 220/220 requested
worlds and report accepted 240/240, with zero failed/rejected/impossible
worlds; each of structured, legacy-four and trigger-matched random widening
consumed 792 candidate-worlds. No score, action or raw record persisted and no
registered 136M screen state was consumed.

With the frozen 2× safety factor, the receipt projects `0.142056` fleet-hours
and `0.017757` max-shard wall-hours, passing the predeclared `400/60` capacity
caps. This is placement evidence only. The next admitted action is to design
and independently review a 512-state screen packet; the strength run itself is
not authorized by this receipt.

## Archive pointers

- Exact pre-compaction ledger:
  `docs_archive/jobs-through-2026-08-08.md`.
- Daily chronology: `docs_archive/daily-log-2026-08-04.md` through the current
  daily log.
- Canonical AI numbers/interpretation: `AI_POLICIES.md`.
- Current milestone/queue: `BACKLOG.md`.
- Executable Claude/Codex mailbox: `HANDOFF_ACTIVE.md`.
