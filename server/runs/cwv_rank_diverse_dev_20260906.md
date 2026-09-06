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
