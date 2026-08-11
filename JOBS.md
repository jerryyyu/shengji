# Fleet job ledger

Last reconciled: 2026-08-11 04:54 EDT. This file owns live compute and compact
terminal stubs. Result interpretation lives in `AI_POLICIES.md`; execution
order in `BACKLOG.md`; full chronology in dated `docs_archive/` logs.

## Live fleet

| host | live job | safe progress | next admitted use |
|---|---|---|---|
| **Mini** | **Idle; concrete fresh-REPORT v2 controller review open** | Recovery source/selection passed externally. Packet `e856c02e…175e2` binds 32 untouched bury rows in eight shards; two pinned rebuilds returned `VERIFIED_NO_REPORT_OPEN`. | Raw `TEACHER_STAGE_C_EXPANDED_FRESH_REPORT_CONTROLLER_V2_REVIEW`; PASS permits its only admission and one execution. |
| **Air** | **Idle; S4 closed** | Independent terminal review passed `SELECT_NONE` at 2,048 clusters: `+0.048828 +/- 0.055712`, LCB `-0.006884`; all 256 null sentinels exact. | Available for separately admitted work; S4 has no retry, extension or deploy authority. |
| **Fly** | `mc-s0-report-lcb` | Release 17 live. Xray kitty-bury support merged in PR #11; no policy change. | Passive latency/correctness monitoring only. |

## Next compute sequence

1. Externally pass the already-frozen concrete v2 controller packet.
2. Only that packet PASS may consume the one untouched REPORT look on Mini.
3. Rebuild and externally review the terminal result without tuning or reuse.
4. Only a REPORT passer may be composed and screened against live report-LCB.

S4 remains an isolated Air lane. S6 source/tests and repository cleanup use no
strength compute while Mini and Air are occupied.

## Recent terminal index

| date | job | terminal verdict | anchor / meaning |
|---|---|---|---|
| 08-11 | Expanded Stage-C labels | **TERMINAL + EXTERNAL PASS** | Source `32d94a4`; 5,504/5,504 new rows, zero refusals, aggregate `3deb3a81…f6ca`. Its one score-free packet freeze was consumed; no training authority followed directly. |
| 08-11 | Expanded Stage-C training | **TERMINAL EXTERNAL PASS / CALIB CAPABILITY** | Source `c18b80e`; all 96 cells / 576 checkpoints replayed; aggregate `5ad77eb0…b6bd` selected epoch-32 all-pairs bury ranking, 8/8 positive seeds, median `+0.016418` versus candidate zero. Its one packet-freeze authority is consumed; no strength claim. |
| 08-11 | Expanded Stage-C REPORT v1 | **TERMINAL OPERATIONAL NO-USE / ZERO EVIDENCE** | Packet `5ce892db…25f0`, receipt `3c4b1f…74bf`; all eight shard commands returned 2 in argparse because `--expected-git` was omitted. Zero labels/predictions/utility/results; third population consumed. |
| 08-11 | Expanded Stage-C REPORT recovery + packet | **RECOVERY EXTERNAL PASS / PACKET REVIEW OPEN / ZERO REPORT ACCESS** | PR #32 `564db02`; fourth selection `3c318da2…41e4`, 480/32 rows and zero prior state/deal overlap. Packet `e856c02e…175e2` binds 32 bury states in eight shards; two pinned rebuilds verified no REPORT open. |
| 08-11 | S4 independent replication | **SELECT NONE / EXTERNAL INTEGRITY PASS** | Exact `fb6ec1a`; 2,048 clusters at `+0.048828 +/- 0.055712`, LCB `-0.006884`; 256 exact-null sentinels. Closed without retry, extension, confirmation or deploy. |
| 08-10 | Protected Stage-C fresh REPORT | **SELECT NONE / EXTERNALLY PASSED** | Source `cd3d7bd`; result `8fa323de…aea6`; 480/480, zero refusals, 810,944 exact worlds. Triggered 171 rows; mean improvement `-0.00822754`, LCB `-0.01894357`. No composition or REPORT reuse. |
| 08-10 | Stage-C training generation v1 | **SELECT NONE** | Source `18a6fa1`; all 48 cells / 288 checkpoints completed and replayed. Play ranker approached candidate zero but failed the 6/8 seed gate; bury was negative. Fresh REPORT remained unopened until the separately protected test above. |
| 08-10 | Expanded label packet | **PACKET PASS / EXECUTION CONSUMED** | Source `32d94a4`; 7,040 DESIGN/CALIB states, 5,504 new labels, 512 third REPORT sealed; controller `82447501…2084`. Execution completed in the 08-11 row above. |
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
S4's first PASS does not authorize deployment. The expanded training result is
CALIB-only. Its failed v1 REPORT is not a model verdict; the fresh recovery
source must pass, then its concrete packet must pass before one REPORT look.

## Archive pointers

- `docs_archive/jobs-through-2026-08-08.md`
- `docs_archive/daily-log-2026-08-08.md`
- `docs_archive/daily-log-2026-08-09.md`
- `docs_archive/daily-log-2026-08-10.md`
- Git history preserves the pre-compaction terminal table.
