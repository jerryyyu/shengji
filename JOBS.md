# Fleet job ledger

Last reconciled: 2026-08-15 01:24 EDT. This file owns current compute and
compact terminal stubs. Historical detail is archived in
`docs_archive/jobs-through-2026-08-11.md`; execution priority is in
`BACKLOG.md`.

## Live fleet

| host | live job | health / next use |
|---|---|---|
| **Mini** | idle / BELIEF-V1 pre-execution | **NO LIVE RESEARCH JOB.** T4 is terminally reviewed `SELECT_NONE`. PR #113 exact `529664f4` is green and awaits source-only review; no BELIEF corpus, training, test opening or design freeze has occurred. A rejected-head V1 design is preserved but must never initialize; the post-merge V2 namespace is absent. |
| **Air** | none | **IDLE AFTER TERMINAL TIMEOUT.** The broad Pair screen reached its fixed 64.08h cutoff with `0/8` terminal shards and published no shard bundle, manifest, aggregate or final. Canonical review `483ed02` preserves the fail-closed terminal. No retry, resize, resume or partial-result use. |
| **Cloud** | powered off | **S4 CLOSED / HOST OFF.** S4 finished both looks and terminally selected none. Independent review `15e8dbb` reproduced final SHA `0aef1ca8…be90`; no retry or candidate action follows. |
| **Performance Cloud** | powered off | **PAIR CHECKPOINT ATTEMPT SPENT.** The sole reviewed V1 execution fail-closed on microshard 3 with `treatment work drift` and no terminal evidence; canonical ledger `2b1fba5`. The later host shutdown makes the invocation unreachable. Any power-on permits score-free recovery inspection only—never resume, retry, outcome access or aggregation. |
| **Fly production** | `mc-s0-report-lcb` | Release 18 / image `kitty-xray-b5a35ae` is healthy. This is the release-17 runtime plus PR #11 kitty X-ray only; no policy changed. Rollback runtime remains release 17 / `latency-cd6789e`. |

## Reviewed queue

| order | job | current gate |
|---:|---|---|
| 1 | BELIEF-V1 B2 offline milestone | **SOURCE REVIEW PENDING.** PR #113 exact `529664f4` is green/mergeable. PASS permits merge and one Mini-specific V2 design freeze only; a second exact marker then covers the consolidated capture/reference/training/test sequence. |
| 2 | Pair checkpoint recovery | **HOLD / BOTH EVIDENCE PATHS SPENT.** Air timed out with no terminal shards; Performance V1 refused and the host is off. Diagnose/recover only through a fresh reviewed design and namespace; no old result may be opened or resumed. |
| 3 | Post-null roadmap | **BELIEF-V1 IS THE CHOSEN REPRESENTATION MILESTONE.** T4, S4 and combined S6 selected none. B0 contracts and B2 implementation exist; no B2 data has run. No scored campaign follows until calibration, sampler fidelity, same-work causality and natural-dose/MDE gates are satisfied. |

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
| 08-14 | Air Pair whole-round screen | **TERMINAL TIMEOUT / NO EVIDENCE:** fixed 64.08h cutoff, `0/8` terminal shards, no manifest/final/aggregate; no retry or partial interpretation. | source `cd206707`; ledger `483ed02` |
| 08-14 | Pair checkpoint successor | **ONE-SHOT ATTEMPT SPENT / NO TERMINAL:** source `71356b2` and packet `f2878fff…a5c9c` passed review, but microshard 3 fail-closed on `treatment work drift`; the later host shutdown leaves no resumable execution. | invocation `ac5425e0…b221`; ledger `2b1fba5`; PR #106 |
| 08-14 | S6 scored-DEV recovery | **TERMINAL `SELECT_NONE_FOR_FRESH_SCREEN_DESIGN`:** all 64 records reconstructed; bury source passed every criterion, lead source failed three. No fresh screen or retry. | result `de1c4f33…d0bc`; review `e31e9a2` |
| 08-14 | S4 360B confirmation | **TERMINAL `SELECT_NONE`:** both looks and all integrity checks completed; final efficacy was not met. | final `0aef1ca8…be90`; review `15e8dbb` |
| 08-13 | S6 opened-DEV V2 start | **PRE-ADMISSION REFUSAL / V2 RETIRED:** the sole reviewed systemd start reached the live shadow gate and refused an ignored controller `.pyc` before packet-review snapshot, admission, gameplay, record-directory or final publication. V2 cannot retry. Optimized V3 PR #104 binds the incident and moves the same shadow check before packet review. | packet `dd7709e9…4adca`; invocation `fcdcb04e…583d`; shadow `3bcf3c6f…18c1`; PR #104 `a93c2f5` |
| 08-13 | Pair checkpoint successor capacity packet | **FROZEN / AWAITING PACKET REVIEW:** exact PR #96 source PASS marker `035bb24` froze one root-owned packet `b2d78d67…f69f92f` / internal `f9123d41…817f1b`. Verification passes; review snapshot, admission, result and installed unit remain absent. | PR #96 `8a3ef59`; runtime profile `ff2dc8f1…7945` |
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
| 08-12 | Pair-aware powered screen packet | **TERMINAL TIMEOUT / NO EVIDENCE:** the admitted 7,168-cluster execution reached its fixed 64.08h cutoff with `0/8` terminal shards and published no manifest, final or aggregate. No retry, resume or partial-result interpretation. | packet `4ece02b9…ae47` / source `cd20670` / ledger `483ed02` |
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
