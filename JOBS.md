# Fleet job ledger

Last reconciled: 2026-08-12 02:34 EDT. This file owns current compute and
compact terminal stubs. Historical detail is archived in
`docs_archive/jobs-through-2026-08-11.md`; execution priority is in
`BACKLOG.md`.

## Live fleet

| host | live strength job | health / next use |
|---|---|---|
| **Mini** | `teacher-v3-stage-c-midlate-composition-screen-v1` | **HEALTHY / SATURATED.** Eight supervised workers started 23:20 EDT under exact head `c89c871`; all remain CPU-bound. The 2,048-cluster T4 screen may take up to about 45.4 wall hours. No shard outcome may be opened before score-free supervisor-final review. tmux: `t4-midlate-screen-v1`. |
| **Air** | none | **FREE.** It completed the 192-state S6 exact source-shape exploration in about one minute; no worker remains live. Reserve it for the first externally authorized S4 or S6 preflight. |
| **Fly production** | `mc-s0-report-lcb` | Release 17 remains live. No deploy, restart, room wipe or policy change is authorized. |

## Reviewed queue

| order | job | current gate |
|---:|---|---|
| 1 | S4 future-only sequential preflight | PR #40 head `3403cdf`; controller review pending. A PASS permits one score-free Air preflight and packet design only. |
| 2 | S6 shuai-pai preflight | PR #41 head `ea07efa`; Air-bound packet v2 review pending. A PASS permits one score-free four-cluster Air preflight only. |
| 3 | Pair-aware capacity design | PR #42 head `d4d8ebd` source/result review, then PR #44 head `1801aa0` score-free dose review. Clean PASSes permit capacity-packet design only. |

Whichever of S4 or S6 receives its exact marker first takes Air. Preflight
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
