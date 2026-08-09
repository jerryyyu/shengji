# Fleet job ledger

Last reconciled: 2026-08-09 06:40 EDT. This file owns live compute and compact
terminal job stubs. Exact historical detail is archived at
`docs_archive/jobs-through-2026-08-08.md`; policy interpretation belongs in
`AI_POLICIES.md`, execution order in `BACKLOG.md`, and current review requests
in `HANDOFF_ACTIVE.md`.

## Live fleet

| host | live strength job | status / next admitted use |
|---|---|---|
| Mini | none | **FREE / S3a PREFLIGHT PASS:** the reviewed four-cluster score-free run ended `AUTHORIZE_SCREEN_PACKET_REVIEW`; final `56943242…e9f`. No screen is admitted until a separate one-shot packet passes external review. |
| Air | none | **FREE / O0-v2 CLOSED:** all 32 training endpoints, 16 evaluations, terminal gate and independent replay completed. Gate `0dbd9aa8…f24e` is `SELECT_NONE` and independently `verified=true`. No O1/strength/production authority and no reviewed Air successor. |
| Fly production | `mc-s0-report-lcb` | Release 17 remains live; passive latency monitoring only. |

The T1 Teacher audit is **terminal PASS**. Receipt
`e293858c…a10d` and preparation `83892930…c39` are exact, and the supervisor
post-preparation preflight returned zero problems. All 64 states and 8 shards
completed, and independent aggregation reproduced the gate byte-for-byte. Air
completed and independently verified the admitted O0-v2 terminal result.

## Next admitted execution

### T1 Teacher

1. **Complete:** exact Mini launch review passed for evaluator `f78e904`,
   controller `0399591`, and material `645b8f54…b894d`.
2. **Complete:** the one-shot preparer emitted exact receipt
   `e293858c…a10d` and preparation `83892930…c39`; both reopened cleanly.
3. **Complete:** all eight shards exited zero; terminal gate `8a1532b7…91f8`
   is PASS and supervisor final is `02f4f8b…6f237`.
4. **Complete:** a fresh exact evaluator aggregation returned zero and matched
   the canonical gate byte-for-byte.
5. **Review open:** the previously passed adapter `5b26c4b` correctly refused
   the real absolute label paths because its fixture predicted relative paths.
   Exact `60d46e1` changes only that literal contract, passes 30/30 and reopens
   the real gate/supervisor with zero problems. Await external PASS, then
   create/verify one design-only adapter. Never retry, extend or train here.

### T2 S3a

The state-level screen has already passed. Claude passed repaired core
`b5dee2e` and Mini-only controller `0085409`; integration `fcad972` preserved
the reviewed bytes and passed 76/76. The first literal packet is superseded
because Teacher exclusivity was prose-only. Exact `e6f2493` hashes and enforces
the terminal-final/no-partial/no-live-worker gate; its focused tests pass
16/16, including wiring non-vacuity, and a real live-Teacher probe refused
before creating a namespace. Claude independently passed superseding contract
`5e0f6ade…b44653`, all 16 tests and the equivalent `192/24`, `768/96` caps.
The exact preflight ran once after the Teacher guard cleared. It completed in
255.3 seconds with exact work, zero bad counters, receipt `97280974…68ca`,
preflight `09692f82…edf0` and final `56943242…e9f`. The 2× projection is
`72.62` fleet-hours / `9.08` max-shard hours for the screen and `290.50` /
`36.31` for confirmation. Its only authority is design and external review of
the screen packet; no strength run has started.

### T2 learner

O0-v2 public-key integration and mandatory semantic replay are reviewed.
Claude's V3 PASS confirmed test-only exact `2e13c35`, including the direct
endpoint replay removal witness and 163/163 local/strict-Air tests. The one
score-redacted Air preflight passed at `f8e1dc16…12eaf`; its 2x projection is
59.4 minutes. Packet `20d2aaee…5cab0` is frozen and independently reverified.
Claude's separate packet review passed after in-situ reopen and adversarial
mutation probes. Exact committed review `116dfb8c…e3d` was admitted once at
`f436f4b0…01e7a`; all 32 training and 16 evaluation endpoints exited zero.
The terminal gate selected none at `0dbd9aa8…f24e`; a separate full semantic
replay exited with the expected code 4 and `verified=true`. Neither factorial
cell advanced. O1, strength and production remain unauthorized.

## Terminal job index

| date | job | verdict / headline | evidence anchor |
|---|---|---|---|
| 08-09 | S3a full-game preflight | **CAPACITY PASS / SCREEN PACKET REVIEW**; 4/4 clusters, exact 952/952 structured rollouts, screen projection `72.62` fleet-hours / `9.08` max-shard hours | preflight `09692f82...edf0`; final `56943242...e9f` |
| 08-09 | Teacher-v3 fresh audit | **PASS / STAGE-C DESIGN**; cheap upper `0.0354`, N=30 upper `0.0439` below `0.10`; no training authority | gate `8a1532b7...91f8`; supervisor `02f4f8b...6f237` |
| 08-09 | Suphx O0-v2 | **SELECT NONE**; control `+0.015` (LCB `-0.067`), plus-margin `-0.047` (LCB `-0.109`); independently replayed | gate `0dbd9aa8...f24e`; admission `f436f4b0...01e7a` |
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
