# Fleet job ledger

Last reconciled: 2026-08-11 00:42 EDT. This file owns live compute and compact
terminal stubs. Result interpretation lives in `AI_POLICIES.md`; execution
order in `BACKLOG.md`; full chronology in dated `docs_archive/` logs.

## Live fleet

| host | live job | safe progress | next admitted use |
|---|---|---|---|
| **Mini** | **Idle; expanded labels terminal** | Exact source `32d94a4`, receipt `48a64759…8efe`. 16/16 shards completed: 5,504 rows, zero refusals, 13,136,320 candidate worlds; aggregate `3deb3a81…f6ca`. | Independent `TEACHER_STAGE_C_EXPANDED_LABEL_RESULT_V1_REVIEW`, then freeze/review one 96-cell training packet. No training before its separate PASS. |
| **Air** | `s4-point-banking-replication-air-180b-v1` | Exact `fb6ec1a`, receipt `fc6d54e7…1077`, 8/8 workers. Last score-free progress 1,398/2,048 primary clusters; 256 exact-null sentinels are also frozen. | Preserve to terminal publication, verify, then independent result review. Never inspect interim utility or retry. |
| **Fly** | `mc-s0-report-lcb` | Release 17 live. Xray kitty-bury support merged in PR #11; no policy change. | Passive latency/correctness monitoring only. |

## Next compute sequence

1. Expanded labels finish and pass full replay plus independent terminal review.
2. Freeze one 7,040-state matched-training packet: two loss recipes, play/bury,
   eight seeds, three learning-curve fractions, at most eight cells live.
3. Only a separate packet PASS may admit training. DESIGN/CALIB selects one
   whole cohort or `SELECT_NONE`; no seed cherry-pick.
4. Only a selected cohort may open the third untouched 512-state REPORT once.
5. Only a REPORT passer may be composed and screened against live report-LCB.

S4 remains an isolated Air lane. S6 source/tests and repository cleanup use no
strength compute while Mini and Air are occupied.

## Recent terminal index

| date | job | terminal verdict | anchor / meaning |
|---|---|---|---|
| 08-10 | Protected Stage-C fresh REPORT | **SELECT NONE / EXTERNALLY PASSED** | Source `cd3d7bd`; result `8fa323de…aea6`; 480/480, zero refusals, 810,944 exact worlds. Triggered 171 rows; mean improvement `-0.00822754`, LCB `-0.01894357`. No composition or REPORT reuse. |
| 08-10 | Stage-C training generation v1 | **SELECT NONE** | Source `18a6fa1`; all 48 cells / 288 checkpoints completed and replayed. Play ranker approached candidate zero but failed the 6/8 seed gate; bury was negative. Fresh REPORT remained unopened until the separately protected test above. |
| 08-10 | Expanded label packet | **PACKET PASS / EXECUTION NOW LIVE** | Source `32d94a4`; 7,040 DESIGN/CALIB states, 5,504 new labels, 512 third REPORT sealed; controller `82447501…2084`. |
| 08-10 | Stage-C iid-v2 labels | **TERMINAL + EXTERNAL PASS** | 2,048/2,048 labels, replacement sampling, exact folds and fidelity review. These 1,536 DESIGN/CALIB rows are retained by the expansion; original REPORT is spent/quarantined. |
| 08-10 | Stage-C label v1 | **TERMINAL NO-USE / NO AGGREGATE** | 2 complete / 6 refused shards because realized-world deduplication exhausted late support and changed posterior mass. Never retry or mine partial rows. |
| 08-10 | Stage-C capture v7 | **CAPTURE + STATE-SET PASS** | 24/24 shards; all 750,000 dispositions and all 2,048 selected states replayed. State set `c7a769c4…e8e1c`, verifier `143fb2db…4adb`. |
| 08-10 | S4 whole-game screen v2 | **SCREEN PASS** | Treatment−champion `+0.086914 +/- 0.056166`, LCB `+0.030748`; matched null identical. Independent replication is the live Air job above. |
| 08-09 | S3a structured-bury full game | **SELECT NONE / CLOSED** | 2,048 clusters; structured−champion `+0.0464`, LCB `-0.0041`. No retry/tuning. |
| 08-09 | H0 human/V11 diagnostic | **TERMINAL INCOMPLETE / NO AGGREGATE** | 555/557 rows; two score-free refusals. No human-derived rule, no partial mining. |
| 08-09 | S5 replay boundary | **SOURCE/FIXTURE PASS / NO CENSUS** | Exact `2351b36`; one future score-free replay census remains eligible. |
| 08-08–09 | V11 direct-v2, Direct-Q, O0/O0-v2, S3b-v2 | **SELECT NONE / HOLD** | Preserve diagnostic lessons; none is deployable or authorizes continuation. See `AI_POLICIES.md`. |
| 08-07 | RLCB-C1 | **CONFIRM** | Aggregate `83f5a9df…f5ef5ea`; `+0.338 +/- 0.068` signed levels versus `mc-strong`, matched null flat. Supports production report-LCB. |

No terminal row grants more authority than its original gate. In particular,
S4's first PASS does not authorize deployment, and an expanded-label PASS will
authorize only a score-free training-packet freeze for separate review.

## Archive pointers

- `docs_archive/jobs-through-2026-08-08.md`
- `docs_archive/daily-log-2026-08-08.md`
- `docs_archive/daily-log-2026-08-09.md`
- `docs_archive/daily-log-2026-08-10.md`
- Git history preserves the pre-compaction terminal table.
