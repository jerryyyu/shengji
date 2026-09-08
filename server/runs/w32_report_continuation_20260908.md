# Report-only learned continuations

DEV experiment, not deployment. Keep selected checkpoint `3cd27716` and
W32/K4/N30/R300. Root enumeration/ranking, sampler, selection rollouts and
challenger selection are unchanged. Only the two report finalists use a
different continuation through the current trick; thereafter the existing
heuristic finishes the round and the exact final attacker points are scored.

This is not double shortlist: no second exhaustive legal/world search, no
extra full trick, no inner MC selection, and no guidance of the root selection
stage. Inner model choices use the existing production ballot/tractor lock
and maximize the simulated mover's partnership value, not the root's team.
Hidden inputs belong to sampled simulation worlds, never actual opponents'
hands. The report fold retains its fresh seeded world population and paired
sampling arithmetic. Its SE is not evidence against continuation/model bias.

## Why this test, and what has already failed

The selected model is useful for root ranking, but that does not establish a
better continuation policy. Earlier A+B net-rollout work was inconclusive at
high cost. PR302 already tested this selected checkpoint's one-trick auxiliary
points leaf; it did not show a gain. Do not repeat that test as if merely using
the selected checkpoint were new.

A seven-root opened-fixture probe reused W32's 32 ranking worlds and compared
heuristic, current-trick learned and current-trick stratified-prior guidance.
One candidate gap changed +0.625 -> +10.78125 points with the model, but the
no-learning control also changed it to +7.03125. Another candidate's gap
changed sign under both controls. These are sensitivity observations, not
accuracy or strength. Learned continuation cost summed to1.119s vs0.086s for
the heuristic component; the whole parallel probe took4.49s. The report-only
scope and batching use existing implementation, not a prediction of cheap play.
Evidence: `~/shengji-archive/2026-09-08/v3-fit768-82ttx4dj/continuation-probe/`.

## Fixed comparisons

1. Learned current-trick report guidance vs unchanged flat W32.
2. Stratified-prior current-trick report guidance vs unchanged flat W32.

Both use the same selected checkpoint for ROOT ranking. The second arm uses
only that checkpoint's training-fitted stratified prior to choose simulated
plays. A K0/heuristic identity arm belongs in mechanics tests and a bounded
actual-consumer check, not a duplicate full scientific run.

Start with13 already-opened DEV deals (seed0 91261190, rank cycle
2,3,4,5,6,7,8,9,10,J,Q,K,A), two mirrors per deal per comparison. No claim
of adequate power for modest gains. This is not a fresh holdout and no outcome
chooses which deals finish. Report all completed pairs and any failures.

Report signed-level utility and deal-bootstrap intervals, actual world/rollout
counts, report net plays/rows/batches, total CPU/wall and tail cost. Compare
the two contrasts paired by deal, but do not call their difference a direct
learned-versus-prior match. A wider or direct comparison requires a useful
signal, not just more completed work. Neither points-gap shifts nor agreement
with heuristic rollouts establish prediction accuracy: that requires a named
independent continuation/outcome reference.

## Execution and reuse

Use the current resumable screen: atomic pair shards, config-bound reopen and
30-second progress. One real initial pair may be retained in the13-deal output
using `--max-new-clusters 1`, then resume with the same source/recipe. Do not
change source within its output folder. No second full-game reconstruction.
Run independent learned/prior pairs in parallel on idle Perf, at most six
workers per arm, single-threaded Torch/BLAS. Preserve Strength RunI and Fly.
Derive the launch ETA from the retained pair, not from the tiny root probe.
A one-hour operational window preserves completed shards on interruption;
it is not a scientific success/failure criterion or an excuse to erase data.

Command per guidance mode, with separate OUTPUT:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 PYTHONPATH=. \
python -m shengji.train.cwv_shortlist_screen \
  --arm learned --checkpoint CHECKPOINT --worlds 32 --alternatives 4 \
  --selection-worlds 30 --report-worlds 300 --batch-size 128 \
  --encoding mlp-static --reuse-successors --baseline flat-shortlist \
  --report-continuation learned \
  --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --seed0 91261190 --clusters 13 --workers 6 --out OUTPUT
```

No production registry/default changes or automatic deployment are part of
this source PR.
