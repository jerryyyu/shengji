# Fleet job ledger

Last compacted: 2026-08-08 08:43 EDT. This file owns current compute and short
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

At 08:43 all eight workers were live after 26 minutes at roughly 86--92% CPU,
zero finals had published, and heartbeats were regular. Inspect only liveness
and score-free counters. Do not open partial outcomes, retry, resume, migrate,
duplicate or alter workers. This supervisor alone may invoke one terminal gate
after eight exact zero exits.

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

The live order is in `BACKLOG.md`. In brief: version S3a/S3b against exact
`mc-s0-report-lcb`; after review run S3b's two-cluster score-free throughput
preflight on Mini, then the bounded S3a mechanism screen if its wall time is
acceptable. Neither may inherit stale formal-S0 `mc-strong` authority.

## Archive pointers

- Exact pre-compaction ledger:
  `docs_archive/jobs-through-2026-08-08.md`.
- Daily chronology: `docs_archive/daily-log-2026-08-04.md` through the current
  daily log.
- Canonical AI numbers/interpretation: `AI_POLICIES.md`.
- Current milestone/queue: `BACKLOG.md`.
- Executable Claude/Codex mailbox: `HANDOFF_ACTIVE.md`.
