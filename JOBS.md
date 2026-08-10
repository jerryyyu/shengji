# Fleet job ledger

Last reconciled: 2026-08-10 12:48 EDT. This file owns live compute and compact
terminal stubs. Policy interpretation lives in `AI_POLICIES.md`; execution
order in `BACKLOG.md`; historical detail in dated `docs_archive/` logs.

## Live fleet

| host | job | status / next admitted use |
|---|---|---|
| Mini | none | **FREE / WAITING ON LABEL-PACKET REVIEW.** Capacity result passed. Label packet `e4958358…09c2` is frozen/reproduced with zero admission/label; PASS opens one 16-shard run projected at ~13 minutes. |
| Air | none | **FREE / PRE-STAGED, TRAINING CAUSALLY BLOCKED.** Persistent worktree `shengji-stagec-integrated-v8-air` is exact `42e17269…160c`, compiled strict mode with reviewed binary `9c9e77fb…be4c1`; 252 tests pass. No checkpoint until complete reviewed labels and a reviewed training packet. |
| Fly | `mc-s0-report-lcb` | Release 17 live. Passive production latency monitoring only. |

## Next admitted execution

Capture-v7 passed exact review and consumed its one admission. All 24 fresh
shards completed, freeze published exact `1024/512/512` splits and `1920/128`
play/bury surfaces, and terminal verification returned
`VERIFIED_STAGE_C_CAPTURE`: state set `c7a769c4…e8e1c`, verifier
`143fb2db…4adb`, 24/24 byte-identical disposition replays totaling 750,000
deals, plus all 2,048 selected states regenerated. Current order:

1. External review of the immutable v7 state set is **complete / PASS**.
2. Capacity packet/result externally passed; result `111092b7…cee0` is closed.
3. Frozen label-controller packet `e4958358…09c2` now needs external review.
4. Only after packet PASS, Mini admits once and runs 16 label shards at
   eight-way concurrency, then aggregates only on 2,048/2,048 complete rows.
5. Air starts only after complete reviewed labels, using the v7-bound 48-cell
   training controller. DESIGN/CALIB choose a capability; untouched REPORT
   remains closed until that selection is final.

No S4 confirmation, S6 screen or other filler job is authorized merely to use
an idle host. S4's screen is already terminal PASS; its confirmation projection
is about `365.592` fleet-hours / `45.699` max-shard hours and the active T4 goal
stops before launching it.

## Terminal job index

The canonical numbers and meanings are in the results table in
`AI_POLICIES.md`; this table is only an artifact locator.

| date | job | terminal verdict | anchor |
|---|---|---|---|
| 08-10 | Teacher Stage-C label capacity | **TERMINAL CAPACITY + EXTERNAL RESULT PASS** | packet `e8967d6f…d2a58`; result `111092b7…cee0`; 32/32, zero refusals, no retained outcome; `1.545` projected fleet-hours / `0.219` eight-worker wall-hours; unequal-rate fixture `202a1d2` mutation-sensitive |
| 08-10 | Teacher Stage-C label controller | **FROZEN/VERIFIED / PACKET REVIEW OPEN / ZERO LABELS** | source `3f6f048`; packet external/internal `e4958358…09c2` / `4b6c3c83…5be5`; 2,048 states, 16 shards, 4,984,960 candidate-worlds; no receipt/admission/shard/partial |
| 08-09 | S3a structured-bury full-game screen | **SELECT NONE / CLOSED** | exact `c599b42`; all 2,048 clusters verified; aggregate `20609613…271f`, final `32156d79…c9ff`; no confirmation, retry, tuning or promotion |
| 08-09 | Teacher Stage-C controller rebind | **EXTERNAL PASS / ZERO STATES** | source `7018f36`; packet commit `45429f3`; packet `b60c4298…7b18`; Claude PASS at `cb9471b`; all seven curriculum commitments unchanged; capture-controller implementation only |
| 08-09 | Teacher Stage-C design v3 | **DESIGN PASS / SUPERSEDED ONLY BY IDENTITY REBIND** | source `20bdb95`; asset `1a29418`; packet `f213314a…3b4`; Claude PASS at `d92f595`; zero states/labels; curriculum preserved exactly by passed rebind `b60c4298…7b18` |
| 08-09 | S5 replay-census code | **BOUNDARY FIXTURE PASS / NO CENSUS** | draft PR #4 head `2351b36`; real `HK` versus lower-ranked equal-point `H10` witness; named `<`→`<=` mutation fails; 12 focused + 52 broader available tests pass; one score-free census freeze eligible |
| 08-09 | H0 controller admit→runtime repair | **V3 EXTERNAL PASS / ZERO OUTCOMES** | PR #6; source `4ebcd09`; packet `cf074871…35392`; Claude PASS at `205b6af`; 557 rows; no diagnostic receipt yet |
| 08-09 | Human H0-v3 controller v2 | **COMPONENT PASS / OPERATIONAL HOLD** | source `6977dbb`; packet `3f68dc6e…7fcf`; admission's unignored lock makes runtime reject its own dirty tree; zero worlds/outcomes |
| 08-09 | S3c one-card controller repair | **V2 EXTERNAL PASS / ZERO SOLVER WORK** | PR #6; source `4ebcd09`; packet `cafbee43…f23e`; Claude PASS at `205b6af`; 64 roots; no mechanics receipt yet |
| 08-09 | S3c one-card controller v1 | **COMPONENT PASS / OPERATIONAL HOLD** | source `e9db4a2`; packet `f58d23b7…3874`; same unignored-lock admit→runtime failure; zero worlds/exact sessions |
| 08-09 | Human H0-v3 controller v1 | **HOLD / SUPERSEDED BEFORE OUTCOMES** | producer `931f504`; asset `ff277b4`; packet `13d9a97f…61fc`; runtime did not self-enforce compiled/strict-void mode and receipt deletion could reissue; preserved and replaced by frozen v2 |
| 08-09 | S3c natural-prefix census + curriculum | **DESIGN PASS / ONE-CARD CONTROLLER IMPLEMENTATION ONLY** | producer `0b96fae`; asset `4fb90a1`; 768 roots; census `23632609…b52a`; packet `df102428…9eca`; Claude marker commit `084ba7e`; no solver/screen/training/strength authority |
| 08-10 | Teacher Stage-C capture v3 | **TERMINAL HOLD / SIX PARTIAL SHARDS NO-USE** | exact source `0b697b6`; first wave found deterministic exact-late phase drift at seeds `170002101` and `170007422`; no later waves, pooling or retry |
| 08-10 | Teacher Stage-C capture v4 repair | **EXTERNAL PASS / SUPERSEDED PRE-ADMISSION** | source `5a51a1e`; packet `0d1a94d4…54eaa`; Claude PASS `8263492`; exact phase fix remains valid, but a later candidate canonicality defect means no v4 receipt/state may be issued |
| 08-10 | Teacher Stage-C capture v5 canonical-source repair | **HOLD / SUPERSEDED BEFORE ADMISSION** | source `a71c67e`; packet `e299ac6c…cf749`; play/follow/random-source repairs were sound, but equal-valued SmartBot incumbent buries still inherited hand order; zero v5 states/worlds |
| 08-10 | Teacher Stage-C capture v6 incumbent repair | **TERMINAL HOLD / 24 SHARDS NO-USE** | Claude PASS `8d6ce71`; source `2bdb094`; receipt external `8580b336…f8c66`; ordered shards `89af231f…8d6`; six exact-late follow cells `0/N`; no state set/verification, retry or extension |
| 08-10 | Teacher Stage-C capture v7 + state set | **TERMINAL CAPTURE + EXTERNAL STATE-SET PASS** | Claude source PASS `83e3fce`; source `03c87d6`; packet `b53af06c…8a43`; receipt `8fdfdef5…f0ef5`; 24/24 fresh shards; reviewed 2,048-state set `c7a769c4…e8e1c`; verifier `143fb2db…4adb`, all 750,000 dispositions and every state replayed |
| 08-09 | S4 complete-round v2 screen | **TERMINAL PASS / CONFIRMATION NOT LAUNCHED** | exact `cad3992`; treatment−champion `+0.086914 +/- 0.056166`, LCB `+0.030748`; treatment and matched null identical, null−champion zero; confirmation projection `365.592` fleet-hours / `45.699` max-shard hours |
| 08-09 | S4 point-banking exact-state screen | **MECHANISM PASS / FULL-GAME PACKET REVIEW** | screen `abd9f36f…cdc00`; receipt `90124eb6…f526b`; overall point delta `+5.156`, LCB `+3.029`; both roles positive; no strength or launch authority |
| 08-09 | Human H0 design v3 | **DESIGN PASS / CONTROLLER FROZEN** | source `b02b6de`, packet commit `d6214ce`, packet `4d3f0a35…8cc3c`; Claude marker `239f13c`; preserved plays, frozen buries, 17/33 caps, explicit continuation, finite work; no outcomes |
| 08-09 | Human H0 design v2 | **IDENTITY DELTA PASS / SUPERSEDED PRE-CONTROLLER** | exact `12dac55`; packet `2cccf580…8f2b`; Claude marker `9fdb67a`; real V11 + portable parent passed, later bounded-design audit superseded it; no outcomes |
| 08-09 | Human H0 design v1 | **SPLIT REVIEW PASS / SUPERSEDED PRE-EXECUTION** | exact `9770313`; packet `9ff160a9…247d3`; split semantics passed, but pinned V11 SHA names no artifact; no outcomes computed |
| 08-09 | Teacher Stage-C design freeze v2 | **HELD PRE-REVIEW / H0 PARENT SUPERSEDED** | exact `b0ef0f9`; 1,024/512/512 DESIGN/CALIB/REPORT; packet `45802e47…a350`; rebind only after H0 controller-v2 PASS; no capture/labels/compute |
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
Teacher's passed Stage-C rebind authorizes capture-controller implementation
only and does not authorize state capture, labels or training; the S3a state
screen authorized only the now-terminal full-game test; and O0-v2 does not
authorize O1.

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
