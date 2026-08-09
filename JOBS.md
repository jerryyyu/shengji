# Fleet job ledger

Last reconciled: 2026-08-09 17:25 EDT. This file owns live compute and compact
terminal stubs. Policy interpretation lives in `AI_POLICIES.md`; execution
order in `BACKLOG.md`; historical detail in dated `docs_archive/` logs.

## Live fleet

| host | job | status / next admitted use |
|---|---|---|
| Mini | `s4-point-banking-duel-screen-100b-v2` | **RUNNING / OUTCOME SEALED.** Exact `cad3992`, packet `17036e63…1385`, admission `1d99bb55…bdbf`, receipt `20a420d2…5cc`; eight shards × 256. Latest count-only heartbeat: `4,4,4,5,4,4,5,5 / 256` (35/2,048), all workers live. Never inspect partial outcomes, retry, extend or move the pinned checkout. |
| Air | none | **FREE.** Use it for the exact H0 controller review/tests or another already reviewed job. No unreviewed strength launch exists. |
| Fly | `mc-s0-report-lcb` | Release 17 live. Passive production latency monitoring only. |

## S4 legal next action

Monitor only `supervisor.jsonl.partial` count/status fields until all workers
terminate. Then invoke the exact `cad3992` controller verifier once:

- `AUTHORIZE_CONFIRM_PACKET_REVIEW`: freeze one fresh 8,192-cluster
  confirmation packet and request external review. This does not authorize its
  launch.
- `SELECT_NONE`: preserve the terminal aggregate/final and close the exact S4
  recipe. Do not retry, tune from outcomes or pool it with the 64-state
  mechanism screen.
- operational refusal: preserve the namespace and diagnose without reading or
  manufacturing strength evidence.

The reviewed preflight completed 4/4 score-free clusters in 321.32 seconds and
projected the screen at `91.40` fleet-hours / `11.42` max-shard hours. That is
capacity evidence, not a strength result.

## Terminal job index

The canonical numbers and meanings are in the results table in
`AI_POLICIES.md`; this table is only an artifact locator.

| date | job | terminal verdict | anchor |
|---|---|---|---|
| 08-09 | S3a structured-bury full-game screen | **SELECT NONE / CLOSED** | exact `c599b42`; all 2,048 clusters verified; aggregate `20609613…271f`, final `32156d79…c9ff`; no confirmation, retry, tuning or promotion |
| 08-09 | Human H0-v3 controller | **SCORE-FREE FROZEN / REVIEW OPEN** | producer `931f504`; asset `ff277b4`; packet `13d9a97f…61fc`; 557 rows replayed, geometry `876ed56b…ff2b`, 0 worlds/outcomes; review precedes one diagnostic execution |
| 08-09 | S3c natural-prefix census + curriculum | **SCORE-FREE FROZEN / DESIGN REVIEW NEXT** | producer `0b96fae`; asset commit `4fb90a1`; 768 roots; census `23632609…b52a`; packet `df102428…9eca`; local/Air replay pass; no solver/screen/training/strength authority |
| 08-09 | S4 complete-round v2 preflight + packet | **PACKET PASS / MINI SCREEN RUNNING** | exact `cad3992`; preflight `fcc8b891…ee060`, 91.40 fleet-hours / 11.42 max-shard hours; packet `17036e63…1385`; Claude marker `51a864c`; admission `1d99bb55…bdbf`, receipt `20a420d2…5cc`; no confirmation/strength |
| 08-09 | S4 point-banking exact-state screen | **MECHANISM PASS / FULL-GAME PACKET REVIEW** | screen `abd9f36f…cdc00`; receipt `90124eb6…f526b`; overall point delta `+5.156`, LCB `+3.029`; both roles positive; no strength or launch authority |
| 08-09 | Human H0 design v3 | **DESIGN PASS / CONTROLLER FROZEN** | source `b02b6de`, packet commit `d6214ce`, packet `4d3f0a35…8cc3c`; Claude marker `239f13c`; preserved plays, frozen buries, 17/33 caps, explicit continuation, finite work; no outcomes |
| 08-09 | Human H0 design v2 | **IDENTITY DELTA PASS / SUPERSEDED PRE-CONTROLLER** | exact `12dac55`; packet `2cccf580…8f2b`; Claude marker `9fdb67a`; real V11 + portable parent passed, later bounded-design audit superseded it; no outcomes |
| 08-09 | Human H0 design v1 | **SPLIT REVIEW PASS / SUPERSEDED PRE-EXECUTION** | exact `9770313`; packet `9ff160a9…247d3`; split semantics passed, but pinned V11 SHA names no artifact; no outcomes computed |
| 08-09 | Teacher Stage-C design freeze v2 | **HELD PRE-REVIEW / H0 PARENT SUPERSEDED** | exact `b0ef0f9`; 1,024/512/512 DESIGN/CALIB/REPORT; packet `45802e47…a350`; repair only after bounded H0 v3 PASS; no capture/labels/compute |
| 08-09 | S4 v2 generation replay | **SCORE-FREE COMPLETE / CONSUMED BY REVIEWED SCREEN** | exact verifier `b0ef0f9`; all 69,047 ascending deals rescanned and all 64 states rebuilt exactly; witness `3079fb16…f0a9` |
| 08-09 | S4 fresh state capture v2 | **SCORE-FREE COMPLETE / CONSUMED BY REVIEWED SCREEN** | exact `1b35fb7`; 64 unique deals (32/role); states `4538be85…6b5f`; Air native `d14eefdd…ebe2e0` |
| 08-09 | S4 fresh state capture v1 | **HOLD / CLOSED WITHOUT OUTCOMES** | exact `402c012`; state asset internally valid, but claimed material digest was irreproducible and test counts were unpinned; replaced by fresh v2 rather than reused |
| 08-09 | Teacher-v3 fresh audit | **PASS / STAGE-C DESIGN** | gate `8a1532b7…91f8`; supervisor `02f4f8b…6f237`; adapter `56ccefbd…c2442` |
| 08-09 | Suphx O0-v2 | **SELECT NONE** | gate `0dbd9aa8…f24e`; independent semantic replay `verified=true` |
| 08-09 | S3a full-game preflight | **CAPACITY PASS** | preflight `09692f82…edf0`; final `56943242…e9f` |
| 08-08 | S3a 512-state screen | **MECHANISM PASS** | aggregate `74aa5a39…396cd`; final `d3f2b1ab…69a6b` |
| 08-08 | S3b-v2 preflight | **TERMINAL HOLD / NO SCREEN** | exact head `cd44ea8`; no receipt/final by design |
| 08-08 | Teacher Stage B | **PASS** | gate `f607b489…89694` |
| 08-08 | Teacher audit-v2 | **OPERATIONAL REFUSAL / NO ML VERDICT** | receipt `ce51b826…71d0`; failed root preserved |
| 08-08 | Suphx O0 | **SELECT NONE** | gate `592a009a…bd407c` |
| 08-07 | RLCB-C1 | **CONFIRM** | aggregate `83f5a9df…f5ef5ea`; closeout `06dd487d…b7aae5` |
| 08-07 | production latency | **LIVE** | image `latency-cd6789e`; manifest `047bcfe4…5b300` |
| 08-07 | V11 direct-v2 | **SELECT NONE** | aggregate `b7c90ba4…05d21ad` |
| 08-07 | Direct-Q 144M | **SELECT NONE** | aggregate `1fa6789e…ce791` |
| 08-07 | formal S0 | **SELECT NONE / OUTCOMES UNREAD** | closeout `ef0a365…fde9a` |
| 08-05 | DEV-512 ballot | **SELECT NONE** | asset `af787485…85d3e7b` |
| 08-04 | sampler Package H | **BOUNDED PASS** | commit `aea3774`; `certify_sampler_v3.json` |

No terminal row grants more authority than its original gate. In particular,
Teacher authorizes Stage-C packet review rather than labels/training; the S3a
state screen authorizes a full-game design rather than strength; and O0-v2
does not authorize O1.

## Preserved failures

- S4 full-game v1 `b64bc95` / `80e4f1bf…6947` is superseded before external
  review. Adversarial probes found outcome-sign/bound, accepted-work and direct-
  authority gaps. It never launched and published no outcomes; repaired v2 is
  a fresh seed namespace rather than a retry.
- Teacher audit-v1/v2 roots remain immutable evidence of publication and
  underfilled-continuation refusals. The fresh v3 audit supersedes them
  operationally but does not rewrite them.
- S3b-v2 exceeded its frozen 250k-node cap before completing its first
  treatment cluster. No score, partial or receipt survived; v2 cannot retry.
- Formal S0c completed compute but failed the evidence chain before corrected
  score parsing. Its numerical result remains permanently unread.

## Archive pointers

- `docs_archive/jobs-through-2026-08-08.md`
- `docs_archive/daily-log-2026-08-08.md`
- `docs_archive/daily-log-2026-08-09.md`
- `docs_archive/handoff-review-2026-08-08-through-2026-08-09-t1-t2.md`
