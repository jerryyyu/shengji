# Fleet job ledger

Last reconciled: 2026-08-13 02:03 EDT. This file owns current compute and
compact terminal stubs. Historical detail is archived in
`docs_archive/jobs-through-2026-08-11.md`; execution priority is in
`BACKLOG.md`.

## Live fleet

| host | live job | health / next use |
|---|---|---|
| **Mini** | `teacher-v3-stage-c-midlate-composition-screen-v1` | **HEALTHY / SATURATED; 0 TERMINAL.** Reviewed counter-only progress is `4,896/12,288` sequential arm-rounds (39.8%). Outcomes remain sealed until score-free supervisor-final review. tmux: `t4-midlate-screen-v1`. |
| **Air** | `pair-aware-whole-round-screen-v3` | **HEALTHY / SATURATED.** All eight shards are at `160/896`. Detached S6 queue `s6-preflight-queue-v2` is sleeping until the pair supervisor seals, publishes its score-free final and releases every worker. Do not inspect outcome-bearing shard JSON. |
| **Cloud** | `s4-point-banking-future-c2-360b-v1` | **HEALTHY / SATURATED.** Look one is at `3,325/8,192` clusters (`40.6%`; 203–212/512 per shard). No shard outcome or efficacy statistic has been opened. tmux: `s4-c2-360b-launch-queue-v2`. |
| **Performance Cloud** | bounded performance engineering | **AVAILABLE / PERFORMANCE-ONLY.** Corrected compatibility receipt PR #75 `90c5630` and prepared-world PR #77 `0381081` await external review. The latter measured 2.62% lower wall time across six fresh exact-head pairs with normalized semantics unchanged; the older 3.37% mixed-revision claim is retired. Trick-state caching is rejected after a safe repair ran 10.56% slower. Incremental Memory is also rejected for this champion: construction is only 0.073–0.078% of round time because its rollouts use HeuristicBot. Next use is a fresh exact-stack profile. S5 cannot use this host because its admission is spent. |
| **Fly production** | `mc-s0-report-lcb` | Release 18 / image `kitty-xray-b5a35ae` is healthy. This is the release-17 runtime plus PR #11 kitty X-ray only; no policy changed. Rollback runtime remains release 17 / `latency-cd6789e`. |

## Reviewed queue

| order | job | current gate |
|---:|---|---|
| 1 | Selective S6 shuai-pai preflight | **AIR AUTHORIZED / DURABLY QUEUED; MINI FALLBACK CLOSED.** Claude's 12:10 PASS permits one four-cluster score-free Air preflight from packet `19f3b2a3…79dd0`. Exact runtime/packet verification passed at 17:19; detached queue `s6-preflight-queue-v2` is fail-closed on pair supervisor final, worker absence and unused S6 targets. Draft PR #65 and its remote branch were closed without a packet or run. |
| 2 | Pair affected-state capacity preflight | **DESIGN EXTERNAL PASS / IMPLEMENTATION REVIEW PENDING.** PR #72 `373de84` PASSed at main `d6db827`. PR #79 `6461c66` implements a 16-lane concurrent score-free preflight with canonical review provenance and systemd worker ownership; 83 tests pass. No packet has been frozen and no preflight or scored run is authorized. |
| 3 | Attacker-gated pair-cap incremental control | **EXTERNAL ACTION-SEMANTICS PASS / CAPACITY DESIGN UNDERWAY.** Claude PASSed PR #69 `ca1913f` at 22:36. A three-arm incremental/matched-v1/literal-champion capacity design is being built; no packet or gameplay authority exists. |
| 4 | S5 defensive point-protection diagnostic | **OPERATIONAL HOLD / OLD ONE-SHOT SPENT.** PR #70 and PR #74 portability PASSed scientifically, but PR #74's request template self-authorized a 41.7-second partial attempt and consumed the admission without a result. PR #76 `e285f47` now permanently refuses the spent run and binds the canonical admission path; it awaits validation-only review. `retry_authorized:false`; never reuse the old queue/path. A separately reviewed fresh recovery namespace would still be required before any diagnostic. |

Pair-aware v3 owns Air and has no retry or extension authority. Every old S4 C2
namespace and the complete 300-billion interval are quarantined and grant no
retry. The 360-billion successor starts a fresh design/controller/packet chain.
Selective S6's old v1 packet is superseded and must never run. A design or
implementation review never substitutes for its named later authority.

## T4 closeout

1. Supervisor and eight shards finish naturally; no retry or resize.
2. External reviewer authenticates the score-free supervisor final.
3. One aggregation is admitted only after that PASS.
4. External reviewer independently reproduces the aggregate and posts the
   terminal verdict.

Safe monitoring: tmux/process state, CPU, supervisor console and durable
heartbeats. Forbidden before review: opening or parsing `shard-*.json` or any
outcome-bearing aggregate input.

## Recent terminal stubs

| date | job | verdict / headline | anchor |
|---|---|---|---|
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
