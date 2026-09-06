# Full-legal complete-world shortlist — DEV screen

Historical source-plan record below; the original screen has since run.
See the **Sep 6 scaling assessment** at the end for the retained ABC W32 result
and current queue. No promotion, deployment, or production-policy claim.
Extends #227 using the
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
4. Run production's unmodified uniform selection, full rollouts, point-shy
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

Historical next steps at the original source freeze: consolidated source review; exclusive Strength timing window;
publish the dose choices; run and retain all five arms; append result/ledger
and request the result review for merge under Jerry's authorization.

## Sep 6 scaling assessment — #248 / #251

The retained **A+B+C W32** run (not the original A+B checkpoint above) completed
256 deal clusters / 512 mirrored rounds. Checkpoint SHA:
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
Source: `2f98cf404f58fdfd9bad823d04b21c581b49ef94`; seed0 `90260904`, rank 2,
four alternatives plus incumbent, batch128, N30/R300. Its signed-level utility
was +0.13867 per round, paired-deal bootstrap 95% CI [+0.06445, +0.21680], at
**10.6126x production decision wall**. This is opened exploratory DEV evidence,
not equal-work superiority or independent confirmation.

Retained evidence on Mini:
`~/shengji-archive/2026-09-05/cwv-shortlist-abc-rerun/learned-3x/`.
The directory's historical `3x` name is not its measured cost or world count.

### Where a larger final-MC budget would go

Reading all 256 existing cluster traces, with counts reconciled against the
stored summary (no games, model inference or new labels):

| Quantity | Observed |
|---|---:|
| Arm decisions / forced singletons / searched decisions | 18,272 / 3,092 / 15,180 |
| Full selection rollouts | 1,930,770 |
| Full paired-report rollouts | 9,108,000 (82.51% of full rollouts) |
| Ranking wall / total arm decision wall | 30,924.20s / 33,952.56s (91.08%) |
| Challenger retained by report-LCB | 5,092 |
| Positive report mean rejected by its LCB | 2,596 |
| Report gap=0 and SE=0 | 1,738 |

The last row is included in the 5,092 overrides: production accepts a report
statistic **equal to** its zero threshold. It is not 1,738 proven-positive
improvements. Of 1,179 off-ballot plays, 270 had this flat sampled report tie.
Conversely, a positive mean rejected by the LCB is not proof of a missed good
action. More independent rollout samples may resolve uncertainty, but cannot
fix systematic continuation-policy bias or a bad candidate set by themselves.

On these fixed positions, doubling **all nonranking time** would increase arm
decision time by 8.92%, or both sides' combined decision time by 8.15%. This is
a linear-cost forecast, **not a measured speed, upper bound or strength
prediction**: nonranking time includes fixed overhead, and new decisions alter
later states, RNG streams and the legal-action cost tail. It nevertheless makes
N60/R600 a substantially cheaper scaling question than doubling the 91%-of-wall
ranking stage. No bootstrap of the existing worlds is treated as fresh draws.

### Separate comparisons, after Claude releases Strength

1. **Production x10:** N300/R3000 against literal N30/R300 production on the
   retained 256 deal coordinates. Compare paired cluster utilities with retained
   ABC W32; report actual wall mismatch instead of assuming x10 means equal work.
2. **Full W64:** same checkpoint, exhaustive legal set, four alternatives,
   batch128 and N30/R300. No two-stage pruning bundled into the scaling contrast.
3. **Final MC x2:** W32/N60/R600, separately, against retained W32/N30/R300.
   The ranking recipe stays fixed; only selection and report dose double.
   This tests the combined final-MC budget, not which of N or R deserves credit.
   Do not expand this into an N-by-R grid before reading this bounded contrast.

Each new arm uses the existing 16-worker resumable paired harness, with one
native thread per worker and all completed pairs retained. No model training,
new population, duplicate integrity pass or changed live process is required.
The shared 256 coordinates improve pairing but do not make multiple comparisons
independent or turn this exploratory follow-up into confirmation.

Initial forecasts: production x10 roughly 45–60 minutes, W64 90–110 minutes,
and final-MC x2 roughly 55–70 minutes; update from completed-pair pace. These are
projections from the retained ~49-minute W32 run, not new measurements. Launch
only after the PUCT unit is actually terminal and Claude's host queue is clear.
Jerry subsequently authorized incorporating the encoding/successor-reuse
optimizations in these not-yet-started runs **after decision parity, profiling
and Claude's source approval**. Bind the same engineering mode for W32 and W64,
with a matched optimized-W32 cost measurement; retain the old W32 strength
evidence but do not call its old 10.6126x wall the optimized cost. Record the
executing source and enabled mode explicitly. This conditional adoption does
not change the checkpoint, world counts, RNG, submitted action set, model batch
shapes, or final MC policy. No live PUCT job is altered. If parity or review
fails, keep the original path and investigate before adopting the optimization.
