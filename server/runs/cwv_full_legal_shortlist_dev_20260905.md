# Full-legal complete-world shortlist — DEV screen

Status at 2026-09-05 19:54 UTC: source PASS and merged in [#236](https://github.com/jerryyyu/shengji/pull/236);
**five-arm 256-cluster screen running on Strength**, started at 19:47:38 UTC
(15:47:38 EDT) after the two-ply job completed successfully at 19:47:15 UTC.
No strength, promotion, deployment, or production-policy claim. Extends #227 using the
merged #229/#230 evaluator/checkpoint, not the old public-observation head.
The #222 driver conflict is resolved in the merged stack; no duplicate repair.

## Policy and controls

1. Enumerate the **entire legal submitted-action set**, with harvest's
   `cap=None`. This includes multi-component throws; the engine decides which
   component actually plays in each sampled world. No truncated-prefix fallback.
2. Score every action on W shared production-sampled complete worlds. Apply the
   action, let the same #229 heuristic finish this trick, then evaluate the
   complete-world net in the root team's perspective (terminal outcomes exact).
   Batches retain O(legal actions + batch size) data, not a full world/state matrix.
3. Keep the **four highest-valued alternatives plus production's incumbent**.
   This explicitly means min(5, legal count), with the incumbent always first.
   Uniform control selects the same number of alternatives without replacement
   and without model rankings. A forced singleton needs no ranking.
4. Run production's unmodified adaptive selection, full rollouts, point-shy
   handling and fresh report-LCB on this shortlist. Learned and uniform arms
   retain R=300; production's 3x comparator uses R=900. Selection N and W are
   chosen from timing, not outcomes.
   Production's tractor-lock bypass is disabled in these two arms so that it
   cannot bypass the requested full-legal enumeration.

Cheap sampling uses a named child RNG and restores the parent RNG. Production
selection/allocation/report retain their existing streams and algorithms.
Sampler counters retain the truthful overall total and explicitly separate
cheap samples from full-rollout samples. Cheap predictions are **not** rollouts.

The checkpoint selected before screen outcomes is
`tmp/train-out/cwv/runAB-mlp-points/best.pt`, SHA-256
`650d4144b0641741fce2d3168f70577ea31e2ae768c6161345354f6ae9ff1787`.
The evaluator uses its terminal-distribution head's expected signed levels;
the auxiliary points head trained this checkpoint but is not directly scored.

## Timing and screen plan

Use outcome-blind production states from seed **89260904**, not screen seeds.
The cost probe captures **all** decision surfaces, including forced and
tractor-locked decisions. For a subset it samples one seeded position per
chronological block; `--stride 1` measures the full census. A fixed every-fourth
or every-eighth decision can alias trick positions and is not used.

Measure the smallest W/N setting and larger W/N settings on the same states,
with counterbalanced timing order. Keep the baseline at N30/R300 and measure
production's own N90/R900. Preserve N30 for the learned arm where it fits;
use remaining time for more cheap worlds. Measure the uniform control's dose
too: matching shortlist size alone does not match its lower inference cost.
Publish selected W/N and measured times before opening the screen population.
If the minimum faithful configuration cannot fit a requested wall budget,
report that infeasibility rather than truncate legal actions or label an
over-budget run as equal-work.

Screen **256 fresh rank-2 clusters, seed0=90260904**, two team mirrors per
cluster, for learned 1x/3x targets, corresponding uniform controls, and the
production 3x arm. The current 1x production policy is always the opponent.
Report signed levels per round and deal-cluster-bootstrap CIs, alongside actual
decision CPU/wall ratios and enumeration/model/full-rollout work. Candidate
trajectories can change realized cost: disclose drift, never censor outcomes
or retune on them. This is an exploratory screen, not a confirmatory claim.

Reuse #227's process-pool pair runner, progress/ETA updates and atomic shards.
Use all 16 cloud workers in an exclusive screen window; numerical libraries
use one thread each. Resume the identical recipe over missing mirrored pairs.
Completed pairs survive failures. No resealing training data, no new capacity
framework, and no duplicated multi-hour reconstruction.

Commands (W/N replaced with the published cost-derived settings):

```sh
SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -B scripts/cwv_shortlist_cost.py --checkpoint CHECKPOINT \
  --deals 2 --stride 1 --world-grid 1,4 --selection-grid 1,30 \
  --out COST_ROOT

SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  python -B scripts/cwv_shortlist_screen.py --arm learned \
  --checkpoint CHECKPOINT --worlds W --selection-worlds N \
  --target-wall-multiplier 1 --clusters 256 --workers 16 \
  --seed0 90260904 --out LEARNED_1X_ROOT
```

Repeat for target 3x; `--arm uniform` omits the checkpoint and uses its measured
selection dose. `--arm production --production-multiplier 3` selects N90/R900.
Do not reuse smoke or cost seeds as screen seeds.

## Initial engineering evidence (not screen results)

- 45 focused native tests passed across shortlist, evaluator, legal enumerator
  and production S0 search; the 13 shortlist tests also passed after explicit
  cheap/full sampler accounting was added. One existing unknown-pytest-mark
  warning, no failures.
- One real two-mirror smoke, seed88261904, completed in 47 seconds on Mini with
  zero summary problems. This deliberately used candidate N1/**R30** versus
  baseline N30/R300: **not an equal-work or strength comparison**. It evaluated
  64,610 cheap action/world rows across 74 candidate decisions; the largest
  observed legal set exceeded 13,000 actions. All legal actions were included.
  Raw receipt: `/private/tmp/cwv-shortlist-smoke-20260905/` on Mini.
- Small Mini-only outcome-blind timing probe: one production deal, 11 seeded
  block-sampled states (seed89260904), W1/N30=0.919x, W4/N30=0.963x,
  production N90/R900=2.939x measured decision wall. These are noisy diagnostics
  on a shared Mini, **not** the cloud budget calibration. Raw receipt:
  `/private/tmp/cwv-shortlist-cost-mini-stratified-20260905/`.
- An earlier seven-state systematic-stride probe overrepresented leads and is
  retained at `/private/tmp/cwv-shortlist-cost-mini-20260905/`, but is not used
  for choosing the screen dose. The cost sampler now avoids four-seat aliasing.

## Published recipes and execution handoff

The [pre-screen dose publication](https://github.com/jerryyyu/shengji/pull/236#issuecomment-5553657910)
records these choices before any screen outcome. Executing source is the
reviewed head `2f98cf404f58fdfd9bad823d04b21c581b49ef94`, merged as
`05d3c3c7d61ed64729af2503625373b5416398d5`. The AB checkpoint above stays fixed.

| Arm / output directory | Cheap worlds W | Selection N | Report R | Wall target |
|---|---:|---:|---:|---:|
| learned-1x | 1 | 30 | 300 | 1x |
| uniform-1x | — | 45 | 300 | 1x |
| learned-3x | 32 | 30 | 300 | 3x |
| uniform-3x | — | 420 | 300 | 3x |
| production-3x | — | 90 | 900 | 3x |

All five use the same 256 rank-2 clusters and two mirrors, seed0=90260904,
16 workers, numerical threads=1, batch size 128, and production N30/R300 as
opponent. These are approximate wall targets, not established equal-work arms.

The isolated Strength cost job retained 107/156 states before its operational
20-minute limit. Only its complete first 84-state production round at
seed89260904 supplies the full-round census: learned W1/N30 measured 0.951x;
production N90/R900 measured 2.861x. The incomplete second round is retained,
not pooled into that census or rerun. A shared-Mini full-round follow-up on
the same 84 states measured learned W1/N30 at 1.004x and W32/N30 at 3.209x.
Strength's W1/W4 timings **forecast**, but do not measure, W32/N30 near 2.98x.
Mini uniform N80/N650 measured 1.188x/4.219x; interpolation gives approximately
N45/N421, selected as N45/N420. Those selected uniform doses were not measured
on Strength. The earlier 11-state Mini sample omitted leads and is diagnostic
only. Actual screen costs will be reported even if the targets are missed;
no post-outcome retuning or censoring.

The model-free `cwv-shortlist-screen-20260905.service` queue owns the launch:
two-ply completes successfully, then these five arms run sequentially, before
the separately owned netroll screen. Do not start a duplicate launcher.
Pinned source and operations are at `/root/cwv-shortlist-dev.tE2GiD` on
Strength; outputs go under its `screen/` directory. Each arm retains atomic
completed cluster pairs and can resume only missing pairs with identical
inputs. The live unit's driver and 16 spawned workers were independently
verified; all workers were using approximately one core each. The first arm
completed all 256 pairs in 505.9 seconds with zero summary problems; the queue
started uniform-1x at 19:56:08 UTC. Its measured decision CPU/wall was
1.2813x/1.2814x baseline: the nominal 1x target was exceeded and will be
reported as such, not presented as equal work. This is faster than the initial
4–6-hour total planning estimate; later arms have larger doses, so do not
extrapolate total duration from the first arm alone. Progress and stage
timestamps remain in the saved logs and `screen/pipeline-status.json`.

Pre-screen evidence and the exact operations plan are retained on Mini at
`/Users/jerryyu/shengji-archive/2026-09-05/cwv-shortlist-pre-screen.tar.gz`,
SHA-256 `ba854716905f69097868a48e70021ccab2c49ac165b63c6c42d651c8b341c10d`.
This archive contains timing evidence, not screen results.

Remaining: run and retain all five arms; aggregate existing pair records once
without replaying games; publish per-arm utility/CIs and actual CPU/wall, plus
deal-paired learned-minus-uniform (1x and 3x) and learned-3x-minus-production-3x
contrasts. These contrasts compare paired outcomes against a common opponent,
not direct duels between arms. Append the result and one ledger line, then
request Claude's result review for merge. The complete five-arm comparison is
not available yet.
