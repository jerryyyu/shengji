# Full-legal complete-world shortlist — DEV screen

Status: source implemented; **256-cluster screen not launched**. No strength,
promotion, deployment, or production-policy claim. Extends #227 using the
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
   handling and fresh report-LCB on this shortlist. The report remains R=300 in
   the requested screen. Selection N and W are chosen from timing, not outcomes.
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

Remaining: consolidated source review; exclusive Strength timing window;
publish the dose choices; run and retain all five arms; append result/ledger
and request the result review for merge under Jerry's authorization.
