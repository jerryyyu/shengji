# Small belief DEV: first fit and sampler comparison

Status: **bounded DEV study complete; do not promote this recipe**. The small
model improves kitty prediction but does not demonstrate stronger W32 play.
Keep production and future data-generation settings unchanged; preserve the
model, corpus and reusable sampler/evaluation code. Related issue: #326.
The existing declaration heuristic stays unchanged after the completed #331
benchmark. This work uses the merged opt-in banker-hand/kitty support repair
from #327; it does not change any registered bot or serving default.

## What runs

One 315,400-parameter feed-forward network: 776 inputs → 256 ReLU → 128 ReLU
→ 4 × 54 × 3 count logits. Receivers are the three other seat-relative hands
and kitty; each cell predicts zero, one or two copies. Inputs are own hand,
public state, final declaration, pooled public play history, and banker-private
kitty only when the actor is the banker. Original deck, seed, true other hands,
outcomes, action values and teacher labels never enter the feature vector.

Actor-visible count masks remove impossible classes. Banker declaration means
banker hand **plus kitty**, not banker hand alone. These necessary marginal
constraints do **not** construct a joint world. An explicit finite-legal-pool
adapter reaches W32 ranking, selection and report sampling; the fresh gameplay
comparison completed all 14 deals / 98 rounds.

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

| Epoch | Train loss | Dev CE | Dev Brier |
|---:|---:|---:|---:|
| 1 | 0.728439 | 0.691597 | 0.455102 |
| 4 | 0.647556 | 0.662308 | 0.433868 |
| 7 (selected) | 0.621777 | 0.658575 | 0.431694 |
| 10 | 0.602586 | 0.664944 | 0.436384 |
| 15 | 0.574194 | 0.681281 | 0.446626 |
| 20 | 0.550430 | 0.701390 | 0.458865 |

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

## Fresh ownership readout

The full fresh namespace contributes 14 deals / 54 reachable uncertain positions
at fixed action indices 0/16/32/48. Two of the 56 requested positions were
unavailable after an early round finish. Six positions are no-trump. Original
decks are disjoint from all 768 source deals, and no checkpoint was reselected.
States come only from the common ordinary-W32 baseline, not treatment outcomes.

| Uncertain receiver group | Small model | Corrected ordinary | Old R4 primary | Old R4 permuted control |
|---|---:|---:|---:|---:|
| All | 0.447290 | 0.470104 | 0.397387 | 0.442864 |
| Other three hands | 0.492678 | 0.494393 | 0.438731 | 0.472505 |
| Kitty | 0.212833 | 0.339447 | 0.170552 | 0.285471 |

With equal positions within each deal and equal deals, the small model's Brier
improvement over corrected ordinary is **+0.022814 [0.010447, 0.035776]**,
about 4.85% relative. The other-hands difference is **+0.001714
[-0.006600, 0.008776]**, not a demonstrated gain. Kitty improvement is
**+0.126614 [0.079453, 0.172656]**. These are exploratory 14-deal bootstrap
intervals, not promotion gates. The small model still trails old R4 primary.

Fresh zero/one/two-copy ECE is 0.019253 / 0.049077 / 0.011394, versus
0.032540 / 0.052751 / 0.025620 for raw 256-world reference probabilities.
The ECE baseline retains Monte Carlo noise; only Brier is debiased.

An illustrative error: at action 32 of fresh deal
`2f39d2f43d79c4368946338723bedcadacd88969db257dacea00b68045aefb49`,
actor 1 predicts one C8 in kitty with probability 0.707 versus ordinary 0.258;
the actual count is zero. The same position also contains correctly improved
kitty guesses, so examples cannot stand in for the aggregate score. Conversely,
at the initial rank-3 state of deal `b3a97bd5…`, the model gives one C5 in
relative receiver 2 probability 0.457 versus ordinary 0.223, correctly; that
is an initial-state improvement, not evidence of learning play chronology.

R4 caveats remain explicit: retained training metadata does not establish
deck-level exclusion, and all 54 fresh actor rows flag incomplete declaration
history (the final declaration and play history are available, but overwritten
declarations are not reconstructed by this bridge). This is the retained R4
adapter comparison, not a claim to reproduce R4's best original input pipeline.

Evidence: `~/shengji-archive/2026-09-10/simple-belief-fresh-ownership/`.
Five incremental passes reused completed deals; new scoring across all passes
totaled 15.03 seconds including repeated process startup, without gameplay
replay or another model training run.

## Final gameplay and cost

Each fresh deal has one common corrected-ordinary W32 baseline and two
focal-team mirrors for each treatment. Declarations, hybrid bury, value
checkpoint, ranking/selection/report budgets and rollout policy stay fixed.
The independent unit is a deal, not a mirror, decision or sampled world.

| Arm versus corrected ordinary W32 | Signed levels / round, 95% interval | Win-rate difference |
|---|---:|---:|
| Uniform reuse of 128-world pool | -0.2143 [-0.5714, +0.1071] | -10.71 pp |
| Small-model weighting | -0.0357 [-0.3214, +0.2857] | -3.57 pp |
| Old-R4-primary weighting | +0.0714 [-0.2500, +0.3929] | +3.57 pp |

All win-rate intervals also cross zero (small model: [-14.29, +7.14] pp).
Small-vs-uniform-pool signed-level difference is +0.1786
[-0.3571, +0.6795]; R4-vs-uniform is +0.2857 [-0.3214, +0.9286]. Thus neither
learned weighting nor finite-pool reuse has a demonstrated strength advantage.
These 14-deal intervals are wide: this is not proof of equivalence or evidence
that every possible learned sampler fails.

| Actual-consumer diagnostic | Ordinary | Uniform pool | Small model | R4 adapter |
|---|---:|---:|---:|---:|
| Mean complete-round wall | 66.17 s | 65.83 s | 64.26 s | 68.90 s |
| Mean focal decision wall | 0.931 s | 0.923 s | 0.937 s | 1.042 s |
| Mean pool construction + inference + fitting | — | 23.12 ms | 80.25 ms | 184.61 ms |
| Mean belief-inference wall | — | — | 0.535 ms | 105.42 ms |
| Mean distinct physical worlds in 128-slot pool | — | 122.40 | 123.07 | 123.11 |
| Mean distinct pool indices drawn | — | 120.56 | 94.39 | 95.76 |
| Mean fitted ESS / 128 | — | — | 0.5086 | 0.5048 |

These are descriptive costs on differing trajectories, not paired same-state
speedup claims. R4 adapter inference includes the retained bridge's two
eight-member cohorts, although only primary is used for gameplay. The small
model is cheap; legal-pool construction and fitting cost far more than its
forward pass. Parent CPU across all 98 rounds totals 6,410.11 seconds; this
excludes child CPU, for which 85.76 seconds of R4 inference **wall** is reported
separately and must not be mislabeled CPU.

Only 17/819 small-model fits and 13/826 R4 fits satisfy the solver's convergence
criterion within 500 iterations. Diversity protection is active (ESS at least
half the pool), but this is approximate marginal matching. Mean small-model
matching error drops from 0.07726 to 0.05174 after fitting; that is an error
against the model, **not against true ownership**. No invalid pool proposals
or strict-world rejections were recorded in this run; hard constraints remain
enforced and separately covered by can-fail consumer tests.

The four-worker extension completed in 1,544.5 seconds (25.74 minutes), after
the repaired first-two-deal chunk's 268.1 seconds. The six original controls
were reused, not replayed. This excludes the initial failed attempt's elapsed
time. The combined saved-evidence readout took about 0.5 seconds; there was no
duplicate full gameplay/inference verification pass.

**Recommendation:** stop scaling this specific small-model/pool recipe. Do not
change production or future data-generation policies on these results. More
epochs already worsen dev calibration, other-hand ownership has no fresh gain,
and neither the small model nor the more accurate R4 adapter shows a supported
gameplay improvement here. Preserve this as a useful inexpensive benchmark,
not a failed artifact to delete. If belief is revisited, first distinguish
other-hand prediction quality from loss introduced by finite-pool projection
and downstream search; a larger training run alone does not answer those
questions. The current run does not isolate which of those limitations causes
the neutral gameplay result.

## Gameplay recovery

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
continued to all 14 predeclared deals with four workers. Executed source is
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

Representative-error reports select the largest errors in the named direction:
a harmful position shows card predictions with increased error, not a larger
helpful kitty prediction that happened in the same position. Net-zero positions
are not called helpful or harmful. This report-only correction changes no score,
model or game. In the retained receiver schema, `opponents` means all three
non-actor hands (including the partner); use "other hands" in interpretations.

## Final evidence and preservation

- Source and results: draft PR #332; no production, serving, declaration or
  data-generation default files changed. The opt-in #327 repair is preserved.
- Combined report: `~/shengji-archive/2026-09-10/simple-belief-final-readout.json`
  (131,195 bytes), SHA256
  `385ea04733f1924cb07fe6a0411ab2e1fb1af59094703960281dadd6bfb2bea4`.
- Gameplay: `simple-belief-w32-gameplay-float32-repair/summary-14.json`,
  all 14 cluster shards, 92 newly completed arm shards and six controls retained
  under their original root. Both the original failure and repair provenance
  remain available; no result was discarded.
- Fresh ownership: `simple-belief-fresh-ownership/`, including all model/reference
  forecasts, reconstructed targets and fixed-position identities.
- Fit data, best/last checkpoints, all 20 curve points, internal check/reference
  and R4 readouts remain in the earlier listed Mini archive paths.
- Validation: 66 focused tests cover the feature boundary, label reconstruction,
  banker union, physical joint worlds, finite-MC correction, control reuse,
  actual W32 routing, calibration/report direction, and interrupted recovery.

The requested bounded implementation/evaluation is complete. A future study or
promotion requires a separately justified recipe; none is launched by this
closeout.
