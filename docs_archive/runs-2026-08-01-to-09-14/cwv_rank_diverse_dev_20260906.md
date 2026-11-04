# W32 on a fresh, balanced trump-rank population

Source PASS: [PR #258 at ce68f6ed](https://github.com/jerryyyu/shengji/pull/258#issuecomment-5557752621).
This is a bounded DEV strength screen, not production activation or a model refit.

## Question and recipe

Does the retained K4 shortlist advantage survive beyond the previously tested
rank-2 population? Use 260 fresh deal clusters / 520 mirrored rounds, with rank
`(2,3,4,5,6,7,8,9,10,J,Q,K,A)[cluster % 13]`, seed `91260904 + cluster`.
Both mirrors get the same rank: exactly 20 independent deal clusters per rank.
The primary result is the **mixed-rank average**, not thirteen powered rank claims.
Suit and no-trump are observed from actual declarations and reported separately;
cycling ranks does not guarantee no-trump coverage.

Keep K4 (four model alternatives plus incumbent), ABC checkpoint
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`,
32 ranking worlds, N30 selection, R300 report, static MLP encoding, batch128,
successor reuse and the unchanged production opponent. No deeper continuation,
widening, checkpoint selection or new learned component is bundled here.
The earlier matched K8-minus-K4 screen favored K4; it does not determine
which fresh deals are included or permit stopping after a favorable result.

## Execution and recovery

The committed allocation is `screen-cwv-k4-ranks13-20260906`,
`[91260904,91261164)`. Its 260 seeds were checked against every current committed
window, including training A/B/C/D/E and prior screens. At launch, invoke the
existing `shengji.seeds.check_and_register` with that exact name/span and
`resume=True`, without overlap permission; the shortlist CLI itself has no
registry hook. Preserve this receipt with the run. This is not a guarantee
against undocumented historical private data.

Use an isolated immutable source tree on idle Strength, 16 processes and one
numerical thread per process. Fresh seeds have no valid prior cost ordering;
do not substitute timings from the old rank-2 deals. Submit all clusters to
the existing work queue and record the realized tail and core utilization.
Planning ETA is **20–45 minutes**, extrapolated from the completed 16–25 minute
rank-2 jobs, not a new measured capacity result. A two-hour operational stop
retains completed pairs. Resume the same command/source/config; never discard
completed games, redraw failed deals or turn partial coverage into a full result.

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B scripts/cwv_shortlist_screen.py --arm learned --checkpoint ABC_CHECKPOINT \
  --worlds 32 --selection-worlds 30 --report-worlds 300 --alternatives 4 \
  --batch-size 128 --encoding mlp-static --reuse-successors \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --clusters 260 --workers 16 --seed0 91260904 --out NEW_DIVERSE_ROOT
```

Report signed levels per round and win rate with deal-clustered uncertainty,
actual rank/suit/NT coverage, failures, decision/ranking wall, rollout counts,
whole-process wall and CPU. Keep the old rank-2 result separate: changing both
rank and deals prevents attributing any difference solely to rank. Higher-cost
strength is permitted; measured cost is disclosed, not an equal-cost launch gate.
No duplicate full-game reconstruction is required. Retain raw shards and logs.

## Completed result — 2026-09-06, 04:08 ET

All 260 pairs / 520 rounds completed at executing source `bc89b557`, exit 0.
The mixed-rank estimate is **positive but inconclusive**: +0.06154 signed
levels per round, deal-clustered 95% bootstrap CI `[-0.00577,+0.13462]`.
Win rate was 52.5%, CI `[49.42%,55.77%]`. These are the original summary's
1,000-replicate intervals; no outcome-dependent population extension was run.
The difference from the previous rank-2 result cannot be attributed to rank:
the seeds also changed. Twenty deals per rank do not support separate claims.

| Evidence | Observed |
|---|---|
| Actual rank coverage | 40 rounds for each of all 13 ranks; both mirrors checked |
| Actual suit coverage | C92 / D124 / H126 / S128 / NT50 rounds |
| Whole-process wall / CPU | 22m52.81s / 19,068.83s; 13.89 mean cores, 16 workers, zero swaps |
| Arm / production decision wall | 15,708.57s / 3,310.50s = 4.745× |
| Arm ranking wall | 12,575.60s, about 80% of arm decision wall |
| Arm / production full rollouts | 11,269,140 / 11,911,470 |
| Cheap ranking evaluations | 246,722,176 |

Saved traces locate the next engineering target without another gameplay run:
the most expensive 1% of ranking decisions account for 59.16% of ranking wall;
the largest ranking pass took 382.55s. Existing successor reuse avoided
233,785,943 leaf completions (12,936,233 remained), but did not eliminate the
full matrix of neural scoring rows. This is profiling evidence, not a promised
additional speedup or permission to prune candidates under an exactness claim.

Raw shards, summary, log and launch script are retained on Mini at
`~/shengji-archive/2026-09-06/cwv-ranks13/` (85MB), and on Strength at
`/root/cwv-ranks13-20260906.YtvILo`. Summary SHA:
`069995e821ffed02a69e8281758ff8ac0d4f28aa360b9000b91ad1712686848d`.
The [full readout](https://github.com/jerryyyu/shengji/pull/258#issuecomment-5557969812)
records the inherited generic summary-label caveat: use the actual config,
shortlist recipe and work counters, not `arm_description`/`work.production`.
Artifacts are unchanged. Strength was explicitly released to Claude's queued
Run F after completion and local preservation; no Codex follow-up was armed.
