# Fleet job ledger through 2026-08-11

Last reconciled: 2026-08-11 23:20 EDT after the reviewed T4 mid/late
whole-round screen launched on Mini. This file
owns live compute and compact terminal job stubs. Exact historical detail is archived at
`docs_archive/jobs-through-2026-08-08.md`; policy interpretation belongs in
`AI_POLICIES.md`, execution order in `BACKLOG.md`, and current review requests
in `HANDOFF_ACTIVE.md`.

## Live fleet

| host | live strength job | status / next admitted use |
|---|---|---|
| Mini | `teacher-v3-stage-c-midlate-composition-screen-v1` | **RUNNING:** eight supervised shards, 2,048 mirrored clusters, treatment/matched-null/live champion. Started 23:20 under exact `c89c871`; tmux `t4-midlate-screen-v1`. Projected up to ~45.4 wall hours. Outcomes remain sealed until supervisor-final review and aggregate admission. |
| Air | none | **FREE:** live SSH probe found no Python strength worker. Use for separately reviewed S6/S4 work that cannot interfere with T4. |
| Fly production | `mc-s0-report-lcb` | Release 17 remains live; passive latency monitoring only. |

The design HOLD and external execution review are closed. Replacement V3
packet `00c8ea70…16b6e` selected all 219 untouched
`champion_uncertainty` states, pins Python 3.14.6 and projected 84.7%/87.8%
one-look power from DESIGN/CALIB. Its one-shot admission is consumed; the
observed action LCB was negative, so no composition packet or whole-game
screen is authorized.

## Active T4 whole-round execution

The mid/late state result `f18c2e42...948f6` passed terminal review. The
whole-round controller/packet and score-free capacity result also passed
independent review. Screen receipt `200f5085…91ea` and supervisor slot
`7cc4b575…3d77` were consumed before eight shard launches. The supervisor
owns signals, emits 30-second durable heartbeats, and will publish a
score-free terminal seal before any aggregate may open outcomes. S6 and a
future-only S4 design remain independent work while this computes.

| order | gate | plain-English progress and what remains |
|---:|---|---|
| 1 | Broad-play capability review | **Closed PASS:** exact raw capability marker is authenticated; REPORT remains unopened. |
| 2 | Power-qualified REPORT design | **Closed/frozen V3:** pushed head `5ebd344`, packet `00c8ea70…16b6e`; all 219 target rows, Python 3.14.6, selection `98fe909d…71fb`, schedule `e6789c7f…1fb78`, 274,504 finite ceiling. Old broad admission is HOLD-bound and durably retired; complete live report-LCB is mandatory fallback. |
| 3 | Play-REPORT controller review | **Closed PASS:** Claude reproduced complete-target selection, 84.7%/87.8% projected power, public N=30 scope, candidate sources, literal live-policy preservation, retirement tombstone and all commands; raw marker authenticated exactly once. |
| 4 | One play REPORT on Mini | **Closed exact execution:** all 219 rows, eight shards, zero refusals and 274,504/274,504 attempted/completed candidate worlds; result `e2e774da…b4c5`, final `821c286b…f7c3`. |
| 5 | Terminal REPORT review | **Closed PASS / SELECT_NONE:** Claude independently reproduced every identity, all 274,504 exact candidate worlds, zero refusals, action mean `+0.012129` / LCB `-0.005056`, and the diagnostic NLL result. The sole raw marker is byte-exact. |
| 6 | Composition | **Closed for this generation:** source `bed8f56` and its real DESIGN smoke are valid readiness work, but the required positive action LCB did not occur. Do not freeze it as evidence. |
| 7 | Whole-game screen | **Not authorized:** no screen, confirmation or deployment follows from this generation. A materially new hypothesis must start a fresh lane. |

S4 point-banking, H0 human/V11 proposal admission, the first protected-play
REPORT and the expanded-bury REPORT are terminal `SELECT_NONE`; none may be
retried, extended or reused. The 2,048-state capture, 7,040-state expanded
labels and eight-seed training cohort are completed prerequisites, not live
jobs.

## Terminal job index

| date | job | verdict / headline | evidence anchor |
|---|---|---|---|
| 08-11 | Powered uncertainty Teacher REPORT | **SELECT NONE, independently reviewed**; action mean `+0.01213`, one-sided LCB `-0.00506`; outcome-NLL strongly positive but nongating | result `e2e774da...1fdb4c5`; final `821c286b...5f7c3` |
| 08-11 | Expanded-bury Teacher REPORT | **SELECT NONE**; mean `+0.03381`, one-sided LCB `-0.01525`; narrow structured-point/void signal only | result `2e21a9bf...72ac4d`; final `126d73cd...e58387` |
| 08-11 | S4 point-banking replication | **SELECT NONE**; mean `+0.04883`, LCB `-0.00688`; positive direction did not replicate conclusively | aggregate `d6b73f45...8f4d4`; final `20ece4ed...f144a` |
| 08-10 | Protected-play Teacher REPORT | **SELECT NONE**; mean `-0.00823`, LCB `-0.01894`; proposal-disagreement overrides lost out of sample | result `8fa323de...5aea6`; final `3b42561d...1758f8` |
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
