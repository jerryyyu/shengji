# Wider W32 shortlist — bounded DEV comparison

Status: implementation/wiring tests prepared; isolated cost probe and paired
run pending. This is a policy experiment, not another engineering-equivalence
claim. Tracks [#248](https://github.com/jerryyyu/shengji/issues/248).

## Question and fixed comparison

Does W32 discard useful choices by keeping only four learned alternatives?
Compare **eight alternatives plus the incumbent (nine moves)** with the retained
**four plus incumbent (five moves)**. Both enumerate and rank all legal actions.
The eight-alternative arm increases final selection work; it is not free width.

Hold fixed the retained ABC checkpoint
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`, W32,
selection N30, report R300, batch128, static MLP encoding, successor reuse,
continuation, incumbent and production opponent. Reuse the same opened-DEV
seed0=90260904, 256 clusters / 512 mirrored rank-2 rounds. This is deliberately
paired with existing K4 evidence, not a fresh confirmation population. The
separate fresh 13-rank screen must not be conflated with this width contrast.

The screen already supported `--alternatives 8`; this change adds a direct
nine-candidate witness, persisted CLI-to-worker checks, and that option to the
cost probe's learned and size-matched uniform arms. Defaults stay at four.

## Efficient execution and recovery

The previous K4 run used an average 10.45/16 cores because its last expensive
pair ran alone for about eight minutes. The optional `--cost-order-from` reads
the prior complete paired timings once and submits expensive clusters first.
It never uses outcomes, changes the requested population or reorders the final
aggregation. Cluster/seed/rank/two-mirror identity and finite costs are checked;
the order is recorded as execution metadata, not a different policy recipe.
Without the option, old cluster order and recipes remain unchanged.

Use 16 processes and one numerical thread each on free Strength. Keep completed
cluster files and resume the identical command after an interruption. No
duplicate full-game reconstruction. A hard runtime stop must preserve completed
pairs; an incomplete population is reported explicitly, never silently pooled
as the planned full screen.

Before the full loop, use the existing seven saved snapshots for a small
W32/N30 cost check with `--alternatives 8 --encoding-grid mlp-static
--successor-grid on`. This sizes incremental final-selection cost; these saved
positions alone do not establish population latency, wide-tail performance or
quality. The full population records real wall/CPU, rollouts, ranking rows,
batch occupancy and stragglers. Current planning estimate is 25–45 minutes on
16 cores, not a measured new-run ETA. Use a two-hour operational stop, retain
partial shards on expiry, and report the measured estimate after the probe.

Full loop (paths are host-specific, bound in the resulting config):

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B scripts/cwv_shortlist_screen.py --arm learned --checkpoint ABC_CHECKPOINT \
  --worlds 32 --selection-worlds 30 --report-worlds 300 --alternatives 8 \
  --batch-size 128 --encoding mlp-static --reuse-successors \
  --clusters 256 --workers 16 --seed0 90260904 \
  --cost-order-from COMPLETED_K4_ROOT --out NEW_K8_ROOT
```

## Interpretation

Report K8 minus K4 paired signed-level utility and game-clustered uncertainty,
plus each against the common production opponent. Report actual decision cost
and compare with retained production-x3/x10 controls with their cost mismatch
explicit. Multipliers are not exact work matching; more worlds/alternatives
are not independently observed games. Preserve negative and inconclusive
results. No production entry/default change, deployment, model refit, new
checkpoint or concurrent depth/pruning change is part of this contrast.
