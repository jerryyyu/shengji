# One extra trick of double-shortlist continuation

Tracks [shortlist strength/scaling #248](https://github.com/jerryyyu/shengji/issues/248).
DEV only. This changes the simulated continuation policy, not production and
not the learned model. Higher cost is permitted; it is not an efficiency claim.

## The experiment

Keep the reference ABC checkpoint
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`,
W32 root ranking, four alternatives plus the heuristic incumbent, N30
selection worlds per candidate, R300 independent report worlds, static MLP
encoding and successor reuse. Do not select a new checkpoint for this screen.

For each root candidate, finish the current trick in each sampled world. In
the first **4/30 of each independent selection/report set**, play one
additional trick using an inner shortlist. At each mover's turn, rank the
**exhaustive** legal set from that mover's team perspective, retain the
heuristic incumbent plus four alternatives, and run each finalist to round
end with the fixed heuristic. Choose the best terminal-point continuation for
the mover, preserving the incumbent on ties. After the extra trick, finish
the remainder with the heuristic. Those terminal points—not neural leaf
values—enter the existing root paired means, standard errors and MC-LCB rule.

The root ranking worlds are not reused as selection/report draws. Those
streams stay independent. Scale the guided count to the actual accepted-world
population: `ceil(n * min(inner_worlds, selection_worlds) / selection_worlds)`.
Thus full selection uses 4/30 and each full report fold uses 40/300, estimating
the same mixture of guided and heuristic continuations. For an underfilled
batch, rounding can add less than one guided world; report both actual counts
and the target fraction. The heuristic control guides zero worlds. This is not
an all-world deeper search; a later all-world arm is separate.

This is the explicit `selection-fraction-ceil-v2` recipe, replacing the
unexecuted four-worlds-per-stream proposal reviewed at `1278350e`. The old
proposal mixed 13% guidance in selection with 1.3% in report, confounding a
depth failure with a changed continuation estimand. Old same-count recipes
must not resume as this recipe. The report stage now costs more; measure it.
Root-equivalent successors can share finished leaves, but evolving branches
must clone them before mutation. Inner scoring packs rows from different
live world/candidate parents into bounded batches of 128, with an explicit
mover for every row. Only each parent's five finalist leaves are retained.

Inner decisions are **per-sampled-world perfect-information simulations**.
They do not see the true hidden allocation, but are also not an executable
information-set-consistent policy for the opponents. This is a heuristic
simulation improvement, not a claim to solve strategy fusion.

## Comparisons and recovery

First use 26 fresh, outcome-independent deal clusters (52 mirrored rounds),
two deals for each of the 13 ranks, with the same rank schedule for every arm.
Allocate an actual disjoint seed window through the existing seed registry
before launch; preserve its receipt. No anonymous replacement of slow or
failed deals. All arms use the same checkpoint and root recipe:

1. Learned inner ranking versus flat optimized W32.
2. Uniform inner shortlist versus flat optimized W32: identical depth,
   finalist count and terminal verification, but no learned inner ranking.
3. Flat optimized W32 versus production on the same deal seeds, anchoring
   interpretation of this new population.

Predeclare learned-minus-uniform on matched deal clusters as the primary
mechanism contrast; show both against flat W32, and the separate production
anchor. Choosing the best of five single heuristic completions may exploit
continuation-specific errors; terminal points are not optimal-play values.
Two deals per rank cannot support per-rank conclusions. Keep this pilot
exploratory even if a small-sample interval happens to exclude zero.

The fraction witnesses exercise the actual continuation dispatcher at 30/300
accepted worlds with cheap stub continuations (4/40 guided). Separate tests
drive the real decision and report adapters, including a natural-state
N30/R30 LCB check and a synthetic N1/R3 unequal-population check. These are
mechanics tests, not measurements of real-checkpoint throughput or strength.

The `heuristic` inner mode is the code-level flat-parity control, not an extra
gameplay arm. Keep each arm's atomic mirrored-pair shards and its immutable
config; resumed work reopens completed pairs rather than replaying them.
Partial outcomes remain visible and are labelled partial. Compute differences
never erase outcomes. No one-shot test opening or duplicate full replay.

Use an idle, explicitly released host with one numerical thread per worker;
do not compete with Claude's Run F, Run E or Mini training. Start with a
two-hour operational stop per arm and retain completed pairs. Observe the
first completed pairs for a real remaining-time estimate rather than inventing
a full-run ETA from the old flat screen. The first small real-checkpoint
decision probe should include an early wide state and a follow, and record
enumeration, scoring, inner rollouts and wall cost. It is a diagnostic, not
another capacity-review prerequisite. If the long tail makes the panel
impractical, preserve the evidence and change the next named recipe explicitly.

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 \
python -B scripts/cwv_shortlist_screen.py --arm learned --checkpoint ABC_CHECKPOINT \
  --worlds 32 --selection-worlds 30 --report-worlds 300 --alternatives 4 \
  --encoding mlp-static --reuse-successors --batch-size 128 \
  --inner-mode learned --inner-worlds 4 --inner-batch-size 128 \
  --baseline flat-shortlist --trump-ranks 2,3,4,5,6,7,8,9,10,J,Q,K,A \
  --clusters 26 --workers 16 --seed0 REGISTERED_START --out NEW_ARM_ROOT
```

Use `--inner-mode uniform` for comparison 2. Omit `--inner-mode` and
`--baseline flat-shortlist` for comparison 3. No production registration or
default changes. Report paired signed levels and win rate with deal-clustered
uncertainty, actual rank/suit/NT coverage, all failures, wall/CPU, outer and
inner rollout counts, and inner scoring rows/batches. Twenty-six deals are a
cheap diagnostic, not a powered final claim or permission to keep extending
the population until an interval becomes positive.
