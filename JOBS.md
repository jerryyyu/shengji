# Fleet job ledger

Last reconciled: 2026-08-08 18:19 EDT. This file owns live compute and compact
terminal job stubs. Exact historical detail is archived at
`docs_archive/jobs-through-2026-08-08.md`; policy interpretation belongs in
`AI_POLICIES.md`, execution order in `BACKLOG.md`, and current review requests
in `HANDOFF_ACTIVE.md`.

## Live fleet

| host | live strength job | status / next admitted use |
|---|---|---|
| Mini | `teacher-v3-report-lcb-audit-v3-mini-149m` | **RUNNING / HEALTHY / LONG:** supervisor admitted at 16:33 EDT and owns 8/8 CPU-bound label shards. At 18:19, score-free progress was 1,055/4,096 outer worlds (25.8%); no shard was terminal. Wait for one terminal gate; no duplicate/retry/migration. |
| Air | none | Physically idle but not admissible for the current S3a parent. A no-write probe with exact copied RLCB-C1 evidence/native bytes still refused the historical Mini `execution_host`/Python lock. Do not launch S3a on Air without a separately reviewed portable-parent design. |
| Fly production | `mc-s0-report-lcb` | Release 17 remains live; passive latency monitoring only. |

The T1 Teacher audit is **running on Mini**. Receipt
`e293858c…a10d` and preparation `83892930…c39` are exact, and the supervisor
post-preparation preflight returned zero problems. Air remains idle by design.
The runtime forecast uses only score-free progress events emitted after each
outer world plus frozen candidate counts/ply; it reads no utility, regret,
choice or gate outcome. It is operational sizing, not evidence. The job is
healthy but the nested report-LCB continuation geometry was not throughput-
preflighted before launch.

## Next admitted execution

### T1 Teacher

1. **Complete:** exact Mini launch review passed for evaluator `f78e904`,
   controller `0399591`, and material `645b8f54…b894d`.
2. **Complete:** the one-shot preparer emitted exact receipt
   `e293858c…a10d` and preparation `83892930…c39`; both reopened cleanly.
3. **Running:** one Mini supervisor owns eight shards at outer folds 32/32
   while each searched continuation retains the reviewed inner 30+300
   accepted-world dose.
4. **Complete:** Claude independently passed terminal adapter `5b26c4b`.
5. Preserve and independently verify the first terminal PASS, FAIL, or
   INCONCLUSIVE gate, then create/verify one adapter artifact. Never retry,
   extend, promote, or move hosts from this packet.

### T2 S3a

The state-level screen has already passed. Claude's narrow HOLD on the old
exacts is repaired by core `b5dee2e` and Mini-only score-free controller
`0085409`; 61/61 combined tests pass and bounded rereview is requested. The
next possible compute is the separately reviewed
score-free sizing preflight on Mini after Teacher releases it—not a rerun,
enlarged state screen, Air launch, or strength duel.

### T2 learner

O0-v2 public-key integration is merged and reviewed. Packet design may proceed
in parallel, but no collector, training job, O1 extension, or strength run is
authorized yet.

## Terminal job index

| date | job | verdict / headline | evidence anchor |
|---|---|---|---|
| 08-08 | S3a 512-state screen | **AUTHORIZE DUEL DESIGN**; all three state-level LCBs positive; no production authority | aggregate `74aa5a39...396cd`; final `d3f2b1ab...69a6b` |
| 08-08 | S3a v2 sizing | **CAPACITY PASS**; 0.142 fleet-hours / 0.0178 max-shard hours under frozen 400/60 caps | receipt `cf770277...5c431` |
| 08-08 | Teacher Stage B | **PASS**; regret upper bound `0.019548 < 0.10` | gate `f607b489...89694` |
| 08-08 | Teacher audit-v2 | **OPERATIONAL REFUSAL / NO ML VERDICT**; incomplete continuation, no labels/gate | receipt `ce51b826...71d0`; failed root preserved |
| 08-08 | S3b v2 preflight | **TERMINAL HOLD / NO SCREEN**; exact node cap hit in cluster 1 | head `cd44ea8`; no final/partial receipt |
| 08-08 | Suphx O0 | **SELECT NONE**; aggregate oracle signal, seed-1 reversal | gate `592a009a...bd407c` |
| 08-07 | RLCB-C1 | **CONFIRM**; report-LCB `+0.338379 +/- 0.067706`, null flat | aggregate `83f5a9df...f5ef5ea`; closeout `06dd487d...b7aae5` |
| 08-07 | production latency | **LIVE**; release 17, off-loop isolated search | image `latency-cd6789e`; manifest `047bcfe4...5b300` |
| 08-07 | V11 direct-v2 | **SELECT NONE**; `-0.141113 +/- 0.069823` versus current | aggregate `b7c90ba4...05d21ad` |
| 08-07 | Direct-Q 144M | **SELECT NONE**; positive gameplay, failed held-out learning | aggregate `1fa6789e...ce791` |
| 08-07 | formal S0 | **SELECT NONE**; numerical S0c outcome unread/nonretryable | closeout `ef0a365...fde9a` |
| 08-05 | DEV-512 ballot | **SELECT NONE**; no design advanced, CALIB/REPORT sealed | state asset `af787485...85d3e7b` |
| 08-04 | sampler Package H | **PASS** within bounded strict scope; not posterior calibration | commit `aea3774`; `certify_sampler_v3.json` |

No row grants more authority than its original gate. In particular, S3a's
positive state screen permits duel **design**, not a duel launch, strength
claim, policy promotion, or production change.

## Current terminal details

### S3a 512-state screen — verified PASS

- reviewed source git `14548d3da31c3cfe899cbd7e572614ae05242c0a`;
- run ID `s3a-bury-v2-screen-136m-v1`, eight successful shards, exact seeds
  136,000,000–136,000,511;
- aggregate `74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd`;
- supervisor final
  `d3f2b1ab48085ccf37534b5dd7f20ea6cf0d7644c6c49304b644ecf895169a6b`;
- separate CLI verifier exited zero with `verified=true`;
- structured-minus-incumbent `+0.997314 +/- 0.400606`, LCB `+0.596708`;
- structured-minus-legacy-four `+0.877848 +/- 0.379885`, LCB `+0.497963`;
- structured-minus-random-widening `+3.252848 +/- 0.561197`, LCB
  `+2.691652`;
- no problems, partials or symlinks; retry/resume false; production promotion
  false.

### Teacher audit-v2 — immutable refusal

Stage B passed, but audit-v2 shard 6 stopped after a complete selection fold
and incomplete report continuation. The supervisor terminated siblings. No
label final, terminal audit gate, or regular supervisor final exists, so the
reviewed adapter cannot consume it. Preserve
`~/Projects/shengji-teacher-audit-v2-air` and the earlier failed v1 root; never
resume, migrate, delete, or reinterpret them. Exact retry semantics at
`1589fb4` passed independent review but did not authorize a new run.

### S3b v2 — immutable preflight HOLD

The exact treatment exceeded `max_nodes=250000` before cluster 1 completed.
No score, raw record, receipt, or partial survived. V2 may not retry or change
its cap/fallback. Any future v3 requires a fresh resource contract and review.

## Archive pointers

- Full pre-compaction ledger:
  `docs_archive/jobs-through-2026-08-08.md`, SHA-256
  `26beff936f6c0744b220fc79e233163c8f09acde8a13adcba5450327ad132252`.
- Day chronology: `docs_archive/daily-log-2026-08-08.md`.
- Review markers and adversarial findings: `HANDOFF_REVIEW.md`.
