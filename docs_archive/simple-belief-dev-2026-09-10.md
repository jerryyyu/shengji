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
constraints do **not** construct a joint world. Legal sampler integration and
gameplay comparison remain unfinished.

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

## Retained evidence and rerun commands

All roots below are under `/Users/jerryyu/shengji-archive/2026-09-10/`:

- `simple-belief-fit768/`: recipe, per-deal NPZ arrays, completion.
- `simple-belief-mlp-seed0/`: best/last models, optimizer/RNG state, curves.
- `simple-belief-check-reference/`: recipe, per-deal predictions, truths,
  reference marginals, sampler attempts/diversity, summary.

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

1. Read calibration and representative errors by phase/rank/receiver from
   saved predictions; compare the old R4 model on matching actor states.
2. Wire the new probabilities to an explicitly approximate mixture of legal
   worlds, retaining hard constraints and measuring diversity/latency. Do not
   silently treat independent count predictions as a joint posterior.
3. Run a bounded fresh paired W32 gameplay comparison against ordinary corrected
   sampling and old R4. Ownership improvement alone is insufficient.
4. Publish the supported next recipe or stop recommendation before scaling.
