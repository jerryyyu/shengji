# Fleet job ledger

Last reconciled: 2026-08-12 04:10 EDT. This file owns current compute and
compact terminal stubs. Historical detail is archived in
`docs_archive/jobs-through-2026-08-11.md`; execution priority is in
`BACKLOG.md`.

## Live fleet

| host | live strength job | health / next use |
|---|---|---|
| **Mini** | `teacher-v3-stage-c-midlate-composition-screen-v1` | **HEALTHY / SATURATED.** Eight supervised workers started 23:20 EDT under exact head `c89c871`; at 03:47 each had completed 100/512 treatment rounds and all remained CPU-bound. The 2,048-cluster T4 screen may take up to about 45.4 wall hours. No shard outcome may be opened before score-free supervisor-final review. tmux: `t4-midlate-screen-v1`. |
| **Air** | none | **FREE.** S6 boss/near DEV completed. Pair-capacity v2 was stopped at 1/4 after its PASS was superseded; admission/progress are preserved and no result exists. Next is the first newly authenticated S4, broad-S6 or corrected-pair-v3 score-free preflight. |
| **Fly production** | `mc-s0-report-lcb` | Release 17 remains live. No deploy, restart, room wipe or policy change is authorized. |

## Reviewed queue

| order | job | current gate |
|---:|---|---|
| 1 | S4 future-only sequential preflight | PR #40 head `3403cdf`; controller review pending. A PASS permits one score-free Air preflight and packet design only. |
| 2 | S6 shuai-pai preflight | PR #41 head `ea07efa`; Air-bound packet v2 review pending. A PASS permits one score-free four-cluster Air preflight only. |
| 3 | Pair-aware capacity preflight | **V2 WITHDRAWN / V3 REVIEW OPEN.** The v2 process was halted after one score-free cluster when its synthetic 84-card witness was found invalid; no result published. PR #46 source `1ef8a4d`, packet `67294a93…e4a9b4` proves terminal 100-card/25-per-seat histories in fresh v3 paths. Await `PAIR_AWARE_ROLLOUT_CAPACITY_PACKET_V3_REVIEW`; a PASS permits one score-free preflight only. |

Whichever of S4, S6 or pair-aware receives its exact marker first takes Air. Preflight
artifacts must stay score-free; a later independent packet review is required
before scored execution.

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
