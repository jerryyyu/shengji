# Corrected-rollout selection: first DEV screen

Issue #389; stacked on the diagnostic in PR #394. No registry or production
change. This packet queues experiments, not deployment or a strength claim.

## Mechanism

Keep exhaustive W32 admission (incumbent + four model alternatives). Draw 64
new legal worlds, independently of admission. Before scoring, uniformly choose
30 distinct indices shared by every candidate. Score model leaves on all 64;
run the existing full heuristic continuation on the selected 30. Select using
`mean_64(V) + mean_30(R - V)`. Both terms are acting-team signed levels.

The final independent 300-world challenger/incumbent MC report remains in
points with the existing LCB gate. This is not model-guided rollout play or
deeper tree search. Selection's point-shy epsilon is zero (exact ties only),
not production's 2-point band misinterpreted as 2 levels. The levels-only
control uses the same 64/30 worlds and `mean_30(R)` without model correction.
Both controls keep the exact same admission model and report rule.

Do not invent an SE for corrected selection. Its record says `paired_se: null`;
the actual report fold retains its real paired SE. Record N*K model evaluations
separately from m*K continuation rollouts. Underfill retains the incumbent.

## Perf queue

After the four #390 throw-component windows release Perf, and after this
exact source receives one source review, run two sequential 64-deal mirrored
screens (128 rounds each), 16 workers / one numerical thread per worker:

1. Corrected versus current W32 (`--baseline flat-shortlist`).
2. Corrected versus same-objective MC (`--baseline levels-shortlist`).

Both use seed0 **198260913**, ranks `2,3,4,5,6,7,8,9,10,J,Q,K,A`, checkpoint
`fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9`, and identical
full-completion hybrid burial. This is not Fly's timed 2-second burial fallback.
Deal windows shared between comparisons are paired evidence, not 128 unique
deals. They are disjoint from #390 seeds 193260913 through 197260913.

Common command options for `python -m shengji.train.cwv_shortlist_screen`:

```text
--arm learned --checkpoint /root/w32-fd6bb411.npz
--worlds 32 --selection-worlds 30 --report-worlds 300
--alternatives 4 --batch-size 128 --encoding mlp-static --reuse-successors
--corrected-rollout corrected --correction-worlds 64 --residual-worlds 30
--hybrid-bury --clusters 64 --workers 16 --seed0 198260913
--trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A
```

Use separate outputs `cwv-corrected-vs-w32-198260913` and
`cwv-corrected-vs-levels-198260913`. Preserve every completed pair, stop on error,
no automatic retry, 2-hour timeout per screen. Reuse the existing screen's
config-bound resume only for unchanged code/recipe and explicit continuation.
No multi-hour duplicate reconstruction. Approximate initial ETA 30–60 minutes
per screen, unmeasured for this new arm; update from actual progress and tails.

Report signed-level utility per round with deal-cluster uncertainty, win rate,
role splits, model rows, actual rollout counts, wall/CPU and incomplete pairs.
Publish both results regardless of sign. The first three selected throw-state
diagnostics were mixed and do not establish a benefit; the gameplay screens
are exploratory DEV tests, not confirmation. Do not merge into production or
scale based on this small sample alone.

## Pre-publication checks

96 focused tests pass, including S0/default behavior, golden engine histories,
real corrected decisions, screen/config accounting, and x-ray unit labels.
Independent source review found and closed a control-factory bug; the runtime
witness now proves baseline selection makes zero model calls.

A real fd6bb411 W32 decision at the 64/30/300 recipe completed for both modes:
150 selection + 600 report rollouts each, 320 extra model rows in corrected,
zero in levels control, no underfill. Local walls were 2.64s and 2.39s for this
single state; these are a smoke check, not a speed or strength benchmark.
