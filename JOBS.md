# Fleet job ledger

Last reconciled: 2026-08-10 08:42 EDT. This file owns live compute and compact
terminal stubs. Policy interpretation lives in `AI_POLICIES.md`; execution
order in `BACKLOG.md`; historical detail in dated `docs_archive/` logs.

## Live fleet

| host | job | status / next admitted use |
|---|---|---|
| Mini | Teacher Stage-C capture v6, session `13568` | **RUNNING / WAVE 1 OF 3.** Exact review PASS `8d6ce71`; source `2bdb094`; packet `40c602ea…20ffd`; one-shot receipt external SHA `8580b336…f8c66` (internal `cc24b5b7…0bd10`). Eight workers run at a time with progress every 250 deals. After 24 shards, the same bounded script freezes 2,048 states and replay-authenticates all 750,000 dispositions. |
| Air | none | **FREE / V6 TRAINING SOURCE STAGED.** Detached head `8ca347f` passes 145/145 under Python 3.14.6. Air starts the 48-cell play/bury × eight-seed × 25/50/100% matrix only after complete reviewed labels exist. |
| Fly | `mc-s0-report-lcb` | Release 17 live. Passive production latency monitoring only. |

## Next admitted execution

Capture-v6 passed exact independent review at `8d6ce71` and was admitted once.
The 07:53 v5 HOLD was Codex's audit; its remaining equal-valued
incumbent-bury tie was repaired before this run. V5 has no receipt/state and is
superseded; capture-v3's six partials remain terminal no-use. Current order:

1. **RUNNING:** Mini runs all 24 capture shards from scratch in three
   eight-worker waves.
2. Mini freezes exactly 2,048 states and authenticates the full 750,000-deal
   scan. External state-set review follows.
3. Mini runs a reviewed 32-state label-capacity pilot, then (only on PASS) the
   16 label shards at eight-way concurrency.
4. **Code propagation complete:** labels `7d3e6ad` (110 tests), training
   `8ca347f` (145), REPORT `e788fde` (158), composition `268ebeb`
   (220 Stage-C / 257 including S3c/live).
   Composition source rereview can proceed without blocking Mini.
5. Air starts only after complete reviewed labels, using the v6-bound 48-cell
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
| 08-10 | Teacher Stage-C capture v6 incumbent repair | **EXTERNAL PASS / CAPTURE RUNNING** | Claude PASS `8d6ce71`; source `2bdb094`; packet commit `055a196`; packet `40c602ea…20ffd`; one-shot receipt external `8580b336…f8c66`; Mini session `13568` |
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
