# Fleet job ledger

Last reconciled: 2026-08-12 06:39 EDT. This file owns current compute and
compact terminal stubs. Historical detail is archived in
`docs_archive/jobs-through-2026-08-11.md`; execution priority is in
`BACKLOG.md`.

## Live fleet

| host | live strength job | health / next use |
|---|---|---|
| **Mini** | `teacher-v3-stage-c-midlate-composition-screen-v1` | **HEALTHY / SATURATED.** Eight supervised workers started 23:20 EDT under exact head `c89c871`; at 05:40 all remained CPU-bound after 6h20m. The 2,048-cluster T4 screen may take up to about 45.4 wall hours. No shard outcome may be opened before score-free supervisor-final review. tmux: `t4-midlate-screen-v1`. |
| **Air** | `s6-full-hand-champion-census-v1` | **HEALTHY / SATURATED.** Eight workers started at 06:35 under exact head `d65dd08`, 64 deals each. They retain source/dose counts only—no winner, points, utility, action or hand. This checks whether the 2.02% heuristic prevalence transfers to literal four-seat `mc-s0-report-lcb` trajectories before sizing is frozen. |
| **Fly production** | `mc-s0-report-lcb` | Release 17 remains live. No deploy, restart, room wipe or policy change is authorized. |

## Reviewed queue

| order | job | current gate |
|---:|---|---|
| 1 | S4 future-only sequential preflight | PR #40 head `3403cdf`; controller review pending. A PASS permits one score-free Air preflight and packet design only. |
| 2 | S6 shuai-pai preflight | PR #41 head `ea07efa`; Air-bound packet v2 review pending. A PASS permits one score-free four-cluster Air preflight only. |
| 3 | Pair-aware powered screen | **PACKET REVIEW PENDING.** Capacity passed; PR #49 packet `4ece02b9…ae47` freezes 7,168 clusters but remains unadmitted. A raw packet marker is required for execution. |

Pair-v3 received and consumed the capacity-result marker to freeze one packet;
its scored namespace remains untouched. All three Air lanes now wait on exact
markers. A packet or implementation review never substitutes for later
execution authority.

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
| 08-12 | S6 actor-visible full-hand selector | **ADVANCE TO FRESH WHOLE-GAME PACKET DESIGN (reused DEV):** 512 decisions on 128 public states; 427 overrides, 101 beneficial / 20 harmful / 306 neutral; state-cluster mean `+0.307`, LCB `+0.175`, both roles positive. This is selector feasibility, not independent strength. | result `54733434…984c` / PR #50 `f3918d2` |
| 08-12 | S6 full-hand natural prevalence | **VIABLE SELECTIVE DOSE / SCORE-FREE:** 1,011/50,000 deals (2.02%) triggered; 1,085/1,067,189 leads, all mid/late; 126 occurred at four cards. | result `8934c2e3…ea45` / PR #50 |
| 08-12 | S6 full-hand boss/near exact replication | **ADVANCE TO DEV SELECTOR:** 128 fresh balanced states, mean `+0.234` levels, one-sided LCB `+0.100`, 24W/8L/96T; both role means positive. Perfect-information action-set value, not whole-game strength. | result `946b029c…cebe` / PR #50 `469b064` |
| 08-12 | Pair-aware powered screen packet | **FROZEN / NOT RUNNING:** 7,168 clusters, 8×896, ~84% planning power at `+0.05`; external packet/source review must resolve the capacity-prose ambiguity before execution. | packet `4ece02b9…ae47` / PR #49 `9edadcf` |
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
