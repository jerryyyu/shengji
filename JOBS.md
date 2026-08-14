# Fleet job ledger

Last reconciled: 2026-08-13 20:47 EDT. This file owns current compute and
compact terminal stubs. Historical detail is archived in
`docs_archive/jobs-through-2026-08-11.md`; execution priority is in
`BACKLOG.md`.

## Live fleet

| host | live job | health / next use |
|---|---|---|
| **Mini** | T4 terminal closeout complete | **TERMINAL REVIEWED `SELECT_NONE`.** External aggregate `f30a77c7…e652`, admission `ec96102e…7a08`; the merged PR #80 helper recursively reproduced all statistics and canonical review `a165274` verified the result. No confirmation, retry or deployment is authorized. Mini has no live T4 worker. |
| **Air** | `pair-aware-whole-round-screen-v3` | **HEALTHY / SATURATED; 0 TERMINAL; SUBSTANTIVE TIMEOUT RISK.** Reviewed score-free counters are `[432,448,448,432,448,448,432,432]/896`, totaling `3,520/7,168` clusters (49.11%), with sealed outcomes. Detached S6 queue `s6-preflight-queue-v2` remains asleep until the Pair supervisor seals and releases every worker. Current run has no retry or extension authority. |
| **Cloud** | `s4-point-banking-future-c2-360b-v1`, tranche two | **HEALTHY / SATURATED; 0 TERMINAL.** Look one completed with integrity intact but below the early-efficacy boundary, so the reviewed controller automatically continued. All 16 tranche-two workers are healthy; reviewed score-free progress is `5,318/8,192` (64.92%). No outcome or efficacy statistic has been opened. There is no hard runtime timeout. |
| **Performance Cloud** | PR #98 merge review and PR #94 V2 packet review | **IDLE / NO STRENGTH AUTHORITY.** The six-pair V5 batch completed once under invocation `7bae1e19…43e0`; frozen validator and Claude's terminal review at `e5818ee` give 29.3203% lower wall and 27.8619% paired lower bound with exact normalized semantics. V5 is consumed forever and V6 is superseded. Draft PR #98 `008d75e` is the production-only measured delta pending review. PR #94 source head `08ee055` PASSed; fresh packet `dd7709e9…4adca` is frozen and verified, but its packet review, admission, records, final and installed unit remain absent. |
| **Fly production** | `mc-s0-report-lcb` | Release 18 / image `kitty-xray-b5a35ae` is healthy. This is the release-17 runtime plus PR #11 kitty X-ray only; no policy changed. Rollback runtime remains release 17 / `latency-cd6789e`. |

## Reviewed queue

| order | job | current gate |
|---:|---|---|
| 1 | S6 opened-DEV V2 diagnostic | **PACKET REVIEW PENDING / PERF IDLE.** PR #94 exact `08ee055` PASSed source review. Fresh packet `dd7709e9…4adca` is frozen and verified, but the distinct reviewer attestation, packet-review snapshot, admission, records, final and installed unit are absent. No run is authorized. |
| 2 | Selective S6 shuai-pai preflight | **AIR AUTHORIZED / DURABLY QUEUED; MINI FALLBACK CLOSED.** Claude's 12:10 PASS permits one four-cluster score-free Air preflight from packet `19f3b2a3…79dd0`. Exact runtime/packet verification passed at 17:19; detached queue `s6-preflight-queue-v2` is fail-closed on pair supervisor final, worker absence and unused S6 targets. Draft PR #65 and its remote branch were closed without a packet or run. |
| 3 | Pair affected-state controller design | **SCORED DESIGN MERGED / CONTROLLER DESIGN ONLY OPEN.** Merged PR #86 exact head `289fdf0` pins its negative ancestry/authority fixtures and grants no packet implementation/freeze/run, evidence access, scoring, REPORT, aggregation, retry, strength, training, promotion or deployment authority. |
| 4 | Attacker-gated pair-cap incremental control | **EXTERNAL ACTION-SEMANTICS PASS / CAPACITY DESIGN UNDERWAY.** Claude PASSed PR #69 `ca1913f` at 22:36. A three-arm incremental/matched-v1/literal-champion capacity design is being built; no packet or gameplay authority exists. |

Pair-aware v3 owns Air and has no retry or extension authority. Every old S4 C2
namespace and the complete 300-billion interval are quarantined and grant no
retry. The 360-billion successor starts a fresh design/controller/packet chain.
Selective S6's old v1 packet is superseded and must never run. A design or
implementation review never substitutes for its named later authority.

## T4 closeout

Read-only closeout helper PR #80 exact head `e61975c` PASSed external review
and is merged on main. Its 22/22 tests pass both plain and under
`SHENGJI_FAST=1`, including aggregate-binding, supervisor-final TOCTOU and
sealed-shard drift refusals. It has no launch, aggregation, scoring or live-run
authority. It recursively reproduced the sole completed aggregate, and
independent terminal review closed it at `SELECT_NONE`.

1. Supervisor and eight shards finish naturally; no retry or resize — **done**.
2. External reviewer authenticates the score-free supervisor final — **done**.
3. One aggregation is admitted only after that PASS — **done**.
4. External reviewer independently reproduces the aggregate and posts the
   terminal verdict — **done at canonical `a165274`: `SELECT_NONE`**.

During execution and review, monitoring was limited to process state and
reviewed score-free heartbeats. The terminal artifacts now remain sealed under
their reviewed verifier; no ad hoc reopening or post-hoc analysis is authorized.

## Recent terminal stubs

| date | job | verdict / headline | anchor |
|---|---|---|---|
| 08-13 | Mini helper-test contention | **MONITORING/PROCESS-DISCIPLINE INCIDENT:** a helper unintentionally launched two pytest processes beside the live T4 workers. The exact PIDs were caught and stopped after roughly two CPU-core-minutes total. Tests used no-bytecode mode; no evidence was written or outcome opened, and T4 remained healthy. Broad tests are no longer permitted on a scored host. | operational observation; no strength/evidence authority changed |
| 08-13 | S5 x86 incident closeout | **VALIDATION PASS / DEAD CHAIN CLOSED:** PR #76 authenticated the spent admission and permanently refused execution. PRs #76/#74 were then closed rather than merged; PR #70 retains only reusable diagnostic source. No retry or result exists. | review main `e91f3b4`; PR #76 `e285f47`; PR #70 `f8083cf` |
| 08-12 | S4 reviewer child-witness incident | **OLD PACKET/SEED BLOCK RETIRED:** a reviewer called real `launch()` behind an ineffective wrapper monkeypatch, starting 16 disposable gameplay workers for about five minutes. No completed result or observed outcome existed and the formal namespace remained unadmitted, but its immutable history was no longer true. Full 300-billion interval retired; disjoint 360-billion design is PR #66. | INC-15; retired packet `65c3cf8a…916e8`; PR #66 `8c262f7` |
| 08-12 | S4 recovery-v1 packet freeze | **OUTCOME-FREE PRE-PACKET REFUSAL:** the formal invocation omitted required native-runtime flags. Runtime refused, but the old controller had already copied one review file. No packet, admission, worker, gameplay or outcome exists. Recovery-v2 makes this boundary transactional and uses a fresh namespace. | review snapshot `9f95587c…05e9`; recovery PR #63 `2649b51` |
| 08-12 | S4 future C2 first launch | **PRE-GAMEPLAY FAILURE / CHAIN RETIRED:** the reviewed packet was admitted, but all 16 children rejected a stale C1 receipt path before gameplay. No shard or outcome existed. That recovery chain and the complete 300-billion interval were later retired after INC-15; the separately reviewed 360-billion successor now runs on Cloud. | failed packet `83cadbfa…cb205`; retired recovery PR #63; successor `e7551e4` |
| 08-12 | Attacker-gated pair-cap replay | **ACTION SEMANTICS PASS / DESIGN ONLY:** external review reproduced all 192 roots: 189 agree with both parents, two retain favorable broad-v2 changes and one blocks its harmful defender-only reversion. Score-free actions only; whole-game design is authorized, execution is not. | artifact `c45a573…ff88` / review `732be40a…af332` / PR #62 `8b83cec` |
| 08-12 | S4 future Cloud capacity preflight | **HOLD OLD EXECUTION PROFILE:** every score-free integrity/dose criterion passed, but the frozen eight-shard schedule projects 869.30 fleet-hours / 108.66 hours per shard over 4/4 measured clusters, above 768/96 caps. Preserve the 8,192/16,384 evidence target and use a reviewed 16-shard successor; never retry this preflight. | result `70a15405…413e` / PR #56 `9f9d80b`; C2 design PR #59 `f0c2a6d` |
| 08-12 | Pair-ballot retention source census | **REAL BUT EARLY-SKEWED SOURCE GAP:** 15,187/18,618,281 lead states (`0.0816%`) omitted at least one legal pair; 14,826 were early (`97.6%`), 352 mid and 9 late. Advance to a trigger-matched equal-work state screen, not a uniformly diluted whole-game duel. Score-free prevalence only. | result `557df627…61f3` / PR #55 `24b421d` |
| 08-12 | S6 literal-champion source census | **DOSE TRANSFERS / SCORE-FREE:** 13/512 rounds (`2.54%`) and 13/9,382 leads (`0.139%`) exposed the full-hand gate; all triggers were mid/late, split 10 attacker / 3 defender. This is slightly above the 2.02% heuristic trajectory estimate, so the 7,168-cluster screen keeps its conservative lower-rate sizing. | aggregate `65eacf05…bf14` / PR #50 `90f05eb` |
| 08-12 | S6 actor-visible full-hand selector | **ADVANCE TO FRESH WHOLE-GAME PACKET DESIGN (reused DEV):** 512 decisions on 128 public states; 427 overrides, 101 beneficial / 20 harmful / 306 neutral; state-cluster mean `+0.307`, LCB `+0.175`, both roles positive. This is selector feasibility, not independent strength. | result `54733434…984c` / PR #50 `f3918d2` |
| 08-12 | S6 full-hand natural prevalence | **VIABLE SELECTIVE DOSE / SCORE-FREE:** 1,011/50,000 deals (2.02%) triggered; 1,085/1,067,189 leads, all mid/late; 126 occurred at four cards. | result `8934c2e3…ea45` / PR #50 |
| 08-12 | S6 full-hand boss/near exact replication | **ADVANCE TO DEV SELECTOR:** 128 fresh balanced states, mean `+0.234` levels, one-sided LCB `+0.100`, 24W/8L/96T; both role means positive. Perfect-information action-set value, not whole-game strength. | result `946b029c…cebe` / PR #50 `469b064` |
| 08-12 | Pair-aware powered screen packet | **REVIEWED / RUNNING:** 7,168 clusters, 8×896, ~84% planning power at `+0.05`; one admitted execution began on Air around 07:27. Outcomes remain sealed until score-free supervisor review. | packet `4ece02b9…ae47` / source `cd20670` |
| 08-12 | S6 level-objective audit | **STOP THIS FILTER:** on the exact 300 report worlds, level-bracket scoring kept 5/12 selected throws, still retained the only two-level loss and retained zero wins. A full matched pilot is not justified from this evidence. | artifact `f6478bac…6329` / PR #47 |
| 08-12 | Pair-aware powered screen implementation | **RUNNABLE SOURCE, FREEZE BLOCKED:** PR #49 implements 7,168 clusters under the reviewed caps with ~84% power at `+0.05`; capacity PASS and then packet review remain mandatory. | PR #49 `cd20670` |
| 08-12 | Pair-aware v1 selected-root audit | **ENCOURAGING, NOT STRENGTH:** across all nine finite-search v1 changes at 4,096 fresh common worlds, primary level utility favored v1 on 5–6 roots, opposed it on 1–2 and left two unresolved under two continuation models. One points-positive root was level-negative, so points alone are insufficient. | artifact `131a64e…7eaa3` / PR #48 |
| 08-12 | Pair-aware v3 capacity | **EXTERNAL PASS / PACKET FROZEN:** v1 changed 6/8 mirrored natural roots; no utility was published. The successor now waits on packet review. | result `08f7282c…f7c1` / review `051129e` |
| 08-12 | S6 report-world failure audit | **SAFETY SIGNAL, NO WIN:** 276 full-throw failures across the 12 override folds; zero-failure gating catches the only loss but retains ten neutral all-boss overrides and no positive utility. | artifact `fd1435b9…c966` / PR #47 |
| 08-12 | S6 boss/near override census | **FAILED-THROW RISK ISOLATED (EXPLORATION):** 11 successful throws were utility-neutral; the sole failed throw was the sole −2 result. Ten publicly proven all-boss bundles were all neutral, so that safer gate removes the observed loss but has no positive strength signal. | artifact `f910a94c…4d80` / PR #47 |
| 08-12 | S6 boss/near DEV pilot | **NO RETAINED SIGNAL (EXPLORATION):** 31/32 clusters tied; one treatment cluster lost two levels; 12 overrides yielded 11 ties and one loss, zero wins. Mean `-0.0625`, 95% interval `[-0.185,+0.060]`. | artifact `ad3eae32…b8b8e` / PR #47 |
| 08-12 | Pair-capacity v2 preflight | **ABORTED AT 1/4, NO RESULT:** a superseding audit found the short-round fixture did not prove 100 played cards. Consumed admission and one progress line are hash-preserved; fresh v3 packet is under review. | admission `19b60b02…0444176` / PR #46 |
| 08-12 | Pair-cap v2 incremental-dose census | **NONZERO DOSE, SCORE-FREE:** 57/192 states triggered; v1/v2 changed 9/10 roots; v2 differed on three (two new, one reverted). Utility remains unknown. | result `f2e1d28b…b0d78` / PR #48 |
| 08-12 | S6 boss/near search-spend census | **87.37% FEWER SECOND SEARCHES, SCORE-FREE:** complete source ballot preserved; boss/near gate triggered 1,283 versus 10,162 broad triggers across 10,895 leads, with all phases/roles represented | result `167eabbc…e88c3` / PR #47 |
| 08-12 | Pair-cap live high-N diagnostic | **8/8 POSITIVE, EXPLORATION ONLY:** every pair-cap-only live state favored the proposed low pair at 3,000 common worlds; mean state gap `+5.0023` points. Rows share rooms/rounds and are not independent. | result `b323827f…8b1f3` / internal `f698c83d…db38` |
| 08-12 | S6 exact source-shape exploration | **NARROW THE HYPOTHESIS:** boss/near was the only nonnegative late action-set stratum (`+0.0156`, 4W/4L/56T); generic whole-plain and whole-trump had zero wins over the best live ballot. Exploration only. | result `fc670903…806c` / PR #45 |
| 08-12 | S6 source prevalence census | **BROAD / SCORE-FREE:** new candidates on 10,201/10,924 natural leads (93.4%), 18,882 additions; capacity and actual move changes still unknown | disjoint DEV seeds starting `431000000`; no scored artifact |
| 08-12 | Pair-aware natural lead-root dose | **SPARSE BUT NONZERO (score-free):** treatment activated in 17/24 balanced lead roots and changed one move; follow roots and complete-round prevalence remain unmeasured | result `e530da6a…bbbb8` / PR #44 |
| 08-12 | Pair-aware exact endgame diagnostic | **ADVANCE TO WHOLE-GAME DESIGN (exploration only):** `+9.21875` acting-team points, one-sided LCB `+6.67570`, both roles positive | result `031a365d…919` / PR #42 |
| 08-11 | Mid/late protected state screen | **PASS:** treatment−live `+0.02020`, LCB `+0.01275`; treatment−same-work-null `+0.01570`, LCB `+0.00880` | result `f18c2e42…948f6` |
| 08-11 | Powered uncertainty Teacher REPORT | **SELECT NONE:** action mean `+0.01213`, LCB `-0.00506`; outcome prediction improved but was nongating | result `e2e774da…b4c5` |
| 08-11 | Expanded-bury Teacher REPORT | **SELECT NONE:** mean `+0.03381`, LCB `-0.01525`; narrow structured-point/void signal survived | result `2e21a9bf…ac4d` |
| 08-11 | S4 point-banking independent replication | **SELECT NONE under its one-shot rule:** mean `+0.04883`, LCB `-0.00688`; implementation sentinels stayed exact | aggregate `d6b73f45…f4d4` |
| 08-10 | Protected-play Teacher REPORT | **SELECT NONE:** `-0.00823`, LCB `-0.01894` | result `8fa323de…aea6` |
| 08-08 | S3a 512-state mechanism screen | **PASS / DUEL DESIGN ONLY:** all three state-level lower bounds positive | aggregate `74aa5a39…396cd` |
| 08-07 | RLCB-C1 | **CONFIRM:** report-LCB `+0.338379 +/- 0.067706`, null flat | aggregate `83f5a9df…f5ef5ea` |

No terminal row grants more authority than its original gate. In particular,
the pair diagnostic is not whole-game strength, the mid/late state result is
not a deploy claim, and the old S4 populations cannot be pooled post hoc.
