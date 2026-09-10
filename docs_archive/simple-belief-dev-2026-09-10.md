# Small belief DEV: first fit and sampler comparison

Status: experimental source and an encouraging ownership result, **not a
gameplay-strength result or production recommendation**. Related issue: #326.
The existing declaration heuristic stays unchanged after the completed #331
benchmark. This work uses the merged opt-in banker-hand/kitty support repair
from #327; it does not change any registered bot or serving default.

## What runs

One 315,400-parameter feed-forward network: 776 inputs → 256 ReLU → 128 ReLU
→ 4 × 54 × 3 count logits. Receivers are the three seat-relative opponents
and kitty; each cell predicts zero, one or two copies. Inputs are own hand,
public state, final declaration, pooled public play history, and banker-private
kitty only when the actor is the banker. Original deck, seed, true other hands,
outcomes, action values and teacher labels never enter the feature vector.

Actor-visible count masks remove impossible classes. Banker declaration means
banker hand **plus kitty**, not banker hand alone. These necessary marginal
constraints do **not** construct a joint world. An explicit finite-legal-pool
adapter now reaches W32 ranking, selection and report sampling; the fresh
gameplay comparison remains unfinished.

Reconstruction reuses `harvest_labels.replay_checked` and the engine. The source
is existing curated baseline-fit trajectories from A/C/D/E/F2: 768 original
deals, reduced outcome-blindly to 16 distinct phase-spread positions per deal.
Global deck grouping collapses mirrored/cross-source duplicates. Multi-deal
clusters are refused rather than pretending to have a match split. No new
capture campaign, ensemble training, or original R4 test reopening.

Split by original-deal hash: **603 train / 68 dev / 97 check**, 12,288 positions.
These check deals are unseen by this belief fit but were fit-eligible for the
existing value model. They are **not fresh combined W32 gameplay holdout**.
This is a small initial slice, not a claim that all newer data has been used.

## First results

AdamW, learning rate 0.001, batch 256, seed 0, 20 epochs. Epoch 7 selected by
dev uncertain-cell cross-entropy. CPU on the 10-core, 16-GB Mini:

| Stage | Work | Measured time |
|---|---|---:|
| Ownership cache | 768 deals, four workers | 12.46 s |
| Train + dev evaluation | 20 epochs, two Torch threads | 2.87 s |
| Corrected reference readout | 97 deals, four workers | 10.60 s |

Training time excludes cache load and checkpoint writes. Cached arrays occupy
6.3 MB; best/last checkpoints and curves occupy 7.9 MB. Completed deal shards
and epochs are independently reusable. Training cannot open check arrays.
An injected stop between best and last publication resumes to identical model
tensors; non-resume refuses an occupied output directory.

| Readout | Model | Comparison |
|---|---:|---:|
| Best dev CE | 0.658575 | count prior 0.820378 |
| Best dev Brier | 0.431694 | count prior 0.534591 |
| All internal-check CE | 0.657349 | count prior 0.825616 |
| All internal-check Brier | 0.429166 | count prior 0.534695 |
| Phase-spread check Brier | 0.486675 | corrected ordinary sampler 0.493213 |

The last row is a different population/weighting: three selected positions per
deal, one of which was fully determined for every deal and is explicitly
excluded, leaving 194 uncertain positions. Each position averages uncertain
cells, then each deal averages its positions. The ordinary baseline draws 256
worlds with corrected banker/kitty support. Its raw empirical Brier was
0.495134; subtracting sum(p-hat × (1−p-hat))/(N−1) per count cell removes the
finite-draw inflation before comparison.

Equal-deal mean Brier improvement is **+0.006538**, bootstrap 95% interval
**[+0.001699, +0.011241]** (2,000 deal-cluster resamples). This is approximately
1.33% relative improvement over the corrected reference on this slice. It is
not a calibrated joint-posterior or policy-strength claim.

The training curve already reveals a limit: train loss falls from 0.72844 to
0.55043, but dev CE worsens from its epoch-7 minimum to 0.70139 at epoch 20.
More epochs alone are not the next step. Do not select another checkpoint
using these check outcomes.

## Old R4 and calibration readout

The retained actor-only R4 bridge scored the same 194 uncertain positions in
15.72 seconds, including 13.99 seconds for both cohorts' inference:

| Forecaster | Brier (lower is better) |
|---|---:|
| Corrected ordinary sampler | 0.493213 |
| Small feed-forward model | 0.486675 |
| Old R4 synthetic-primary | 0.444173 |
| Old R4 label-permutation control | 0.472431 |

The small model beats ordinary sampling here, **not old R4**. These are matching
actor states, not an opening of R4's original test. The retained R4 index does
not expose original-deck identities, so disjointness from R4 training is not
independently established; do not label its numbers verified unseen-deal
generalization. The new model's 97 check deals are disjoint from its own fit.

Per-count-class calibration is mixed. Ten-bin ECE for zero/one/two copies is
0.01772 / 0.05925 / 0.01150 for the small model, versus 0.03848 / 0.05649 /
0.02831 for raw empirical reference probabilities. These ECE comparisons are
not corrected for the reference's finite sampling noise. The small model is
slightly worse on one-copy ECE. Raw Brier differences favor it mainly at later
positions; initial positions and no-trump positions are nearly neutral. This
does not isolate history causally: kitty/burial patterns may explain part of
the later-position gain. Saved error examples and receiver breakdowns are
needed before attributing the improvement to behavioral inference.

The receiver split materially changes the conclusion:

| Uncertain receiver group | Small model | Corrected ordinary | Old R4 primary |
|---|---:|---:|---:|
| Other players' hands (97 deals) | 0.513939 | 0.505248 | 0.468794 |
| Hidden kitty (72 contributing deals) | 0.208319 | 0.346462 | 0.158324 |

For other hands, small-minus-ordinary error is **+0.008691** (deal bootstrap
95% **[+0.005002, +0.012357]**): worse, not improved. For kitty it is −0.138143
([−0.161045, −0.115437]). Banker-known kitty cells are excluded. Each position
first averages its group's uncertain cells, each deal averages contributing
positions, then deals receive equal weight. The aggregate win therefore does
not support a claim of better opponent-hand inference. Keep gameplay bounded;
do not scale this recipe based on its aggregate Brier alone.

## Approximate sampler and first consumer timing

`simple_belief_sampler` has three explicitly named modes:

- **ordinary:** corrected proposal draws, with strict public-fact validation;
- **uniform-pool:** sample a fixed legal pool per decision, then draw uniformly
  with replacement from it;
- **learned-pool:** the identical pool construction, with bounded least-squares
  matching to model count marginals, then weighted draws with replacement.

The learned mode caps each weight at 4/N and maintains effective sample size
at least N/2. It reports fit residuals and non-convergence, rather than calling
the weights an exact posterior. Ranking, selection and report draws use their
existing RNG streams but share a finite pool: conditional draw independence
does not remove shared pool-approximation error. The uniform-pool control is
therefore essential, not an optional weak baseline. No action values, rollout
returns or true ownership enter weight fitting.

The real W32 consumer tests cover all three folds, hard facts, hidden twins,
fresh mutable draw containers, count accounting and refusal of invalid pools.
One actual full-work W32 decision on Mini took 2.117 seconds: 128 distinct
proposal worlds, 0.090 seconds total pool preparation, 362 delivered draws
(32 ranking + 30 selection + 300 report), and 750 selection/report rollouts.
Small-model inference was 0.011 seconds on this first call. The fit hit its
500-iteration limit and is explicitly non-converged; its valid ESS-guarded
weights improved the marginal matching objective. This is a single-position
cost observation, not a whole-round runtime or strength estimate.

## Retained evidence and rerun commands

All roots below are under `/Users/jerryyu/shengji-archive/2026-09-10/`:

- `simple-belief-fit768/`: recipe, per-deal NPZ arrays, completion.
- `simple-belief-mlp-seed0/`: best/last models, optimizer/RNG state, curves.
- `simple-belief-check-reference/`: recipe, per-deal predictions, truths,
  reference marginals, sampler attempts/diversity, summary.
- `simple-belief-check-r4/`: same-state R4 primary/control predictions and timing.
- `simple-belief-calibration-reference.json`: per-class reliability, phase
  summaries, and representative saved prediction errors.
- `simple-belief-receiver-readout-equal-position.json`: receiver split with
  the primary readout's equal-position, equal-deal weighting. The earlier
  `simple-belief-receiver-readout.json` pools cells within each deal and is
  retained as a differently weighted diagnostic, not the primary comparison.

Best checkpoint SHA256:
`4843d1d9ab8e7272fad7709ae6a4892f8114c1bed2c3af26ccc836c71562eb96`.
Reference summary SHA256:
`30273d3b35b5cd692f7a63d21b7af692b7197d7d101cd600fbcd693e85a17271`.

Entry points (use distinct outputs for changed recipes):

```sh
PYTHONPATH=server python -m shengji.train.simple_belief_data --help
PYTHONPATH=server python -m shengji.train.simple_belief_train --help
PYTHONPATH=server python -m shengji.train.simple_belief_assess --help
```

Focused tests cover hidden twins/poisoned hidden objects, actual banker burial,
whole-round true-label admissibility, dedup/split/eligibility, cache reuse,
masked loss and learning, exact finite-MC correction, train/check isolation,
and interrupted checkpoint recovery. No production deployment is authorized.

## What remains

The first two-deal gameplay chunk stopped at the small-model probability
validator, after completing six ordinary/uniform-pool control rounds. The
observed float32 softmax normalization errors (1.04e-7 and 1.17e-7) exceeded
the former 1e-7 tolerance; the model outputs were otherwise valid. The repair
uses four float32 epsilons for float32 predictions and normalizes before fitting.
A consumer test accepts the observed roundoff and still rejects a 0.001 mass
error. Models, predictions used in the earlier readouts, and policy settings
are unchanged.

The successor uses `--reuse-controls-from` to retain those six controls with
their original config/source/arm hashes. Only ordinary and uniform-pool arms
can be inherited; changed policy settings or dependencies refuse reuse. The
known sampler repair is checked to change only its learned-only branch.
Incomplete learned arms run on the repaired source in a separate output root.
Fresh ownership assessment replays the saved common baseline at fixed action
indices 0/16/32/48; it does not replay the expensive W32 policy. Predictions
precede privileged label construction, and completed per-deal outputs survive
interruption. These are small DEV comparisons, not a new R4 one-shot gate.

The repaired two-deal chunk completed in 268.1 seconds for eight remaining
learned rounds, retaining six original controls. The unchanged recipe then
continued to all 14 predeclared deals with four workers. Running source is
local `7e6801b1` / published identical-tree `4b28745a`; later report-only
additions do not change that executing tree.

`simple_belief_readout` combines the finished 14 gameplay clusters, saved fresh
ownership predictions and training curves without rerunning inference or games.
It reports both ordinary-baseline comparisons and learned-vs-uniform-pool
comparisons; mirrors are averaged before deal-level intervals. Cost, physical
pool diversity, index-level ESS and fit convergence are separate diagnostics.
Do not interpret fit-to-model error as ownership accuracy, or sum pool wall and
inference wall (the former already includes the latter). A missing final cluster
refuses the final report but never removes the completed shards.

1. Finish receiver/error interpretation and preserve the R4 overlap caveat.
2. Run a bounded fresh paired W32 gameplay comparison: one common ordinary
   baseline plus two focal-team mirrors each for uniform-pool, small-model
   weighting and R4 weighting. Keep declarations, hybrid bury, value checkpoint
   and rollout policy fixed. Preserve completed arms on interruption.
3. Report fresh ownership evidence, paired gameplay, cost and diversity together;
   publish the supported next recipe or stop recommendation before scaling.
