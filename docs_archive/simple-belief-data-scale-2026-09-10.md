# Small belief: data-scaling follow-up

Jerry requested a larger-data test after the first 768-deal study. The earlier
stop recommendation was premature as a conclusion about data scaling: the
original cache was a 1% subset of 76,800 eligible value-fit deals, and only
603 of those deals trained the belief network. No original results are erased.

## Controlled comparison

- Reuse the existing full A/C/D/E/F2 trajectory stores, restricted to the
  baseline checkpoint's fit-deal allowlist. Exclude its validation/test deals.
- Preserve all original 603 training deals in nested 8,000- and 32,000-deal
  training sets. Additional deals are selected by outcome-blind hash order,
  restricted to the original deterministic belief-training split.
- Keep the original 68 dev and 97 check deals and all their cached positions
  unchanged. Explicitly exclude the 14 earlier gameplay deals from training.
- Same 315,400-parameter MLP, 16 phase-spread positions per deal, seed 0,
  AdamW 0.001, batch 256, 20 epochs. Select each checkpoint by the same dev CE.
  Larger datasets mean more optimizer updates: this tests the larger-data
  recipe, not a matched-update causal experiment. One seed is exploratory.
- Reuse exact saved ordinary/R4 forecasts and truths. Only recompute the new
  model forecast at matching states; do not rerun MC or R4 inference.
- Report other hands (including partner) separately from kitty. The 14-deal
  ownership check reuses earlier DEV evaluation states, not a new unopened
  holdout or a new gameplay result.

## Execution

Source: `server/shengji/train/simple_belief_scale.py` and
`simple_belief_scale_assess.py`, on branch `codex/simple-belief-data-scale`.
Artifacts: `~/shengji-archive/2026-09-10/simple-belief-data-scale/`.

Preparation used four independent single-thread workers, streamed shards and
retained per-deal caches. It finished in 209.68 seconds, without copying full
trajectories. Both tiers hard-link identical original dev/check cache files.
Training runs sequentially with two Torch threads to avoid memory contention.
All epochs, model checkpoints, predictions, controls and failed report-repair
context remain available. No production/declaration/sampler defaults change.

The first saved-reference reader omitted two summary population fields needed
by the calibration reader. All predictions and receiver scores were retained;
only the summary was repaired, then calibration completed without new inference.

## Completed results

All models use the same original check states. Lower Brier is better.

| Training deals | Check: all receivers | Check: other hands | Check: kitty | Fresh DEV: other hands |
|---|---:|---:|---:|---:|
| Ordinary corrected sampler | 0.493213 | 0.505248 | 0.346462 | 0.494393 |
| 603 (original) | 0.486675 | 0.513939 | 0.208319 | 0.492678 |
| 8,000 | 0.469882 | 0.496493 | 0.187145 | 0.466718 |
| 32,000 | 0.460401 | 0.486533 | 0.178131 | 0.453565 |
| Retained R4 primary | 0.444173 | 0.468794 | 0.158324 | 0.438731 |

On the same 97 internal-check deals, other-hand Brier changed from 0.513939
(603 train) to 0.496493 (8,000 train), versus ordinary 0.505248. The 8,000-deal
model-minus-ordinary error is -0.008755, paired deal-bootstrap 95% interval
[-0.012322, -0.004874]. Thus the earlier other-hand regression is not persistent
under this larger-data recipe.

On the same 14 earlier gameplay deals, 8,000-deal other-hand Brier is 0.466718
versus ordinary 0.494393 (difference -0.027675 [-0.034451, -0.020472]); all-receiver
Brier is 0.423292. The old small model was 0.492678 and 0.447290 respectively.
These are ownership improvements, not evidence of stronger gameplay. Retained
R4 remains more accurate and retains the original declaration-history and
training-overlap limitations.

8,000-deal training took 42.06 seconds of train/dev compute; epoch 7 selected,
dev CE 0.625087 versus 0.658575 for the original model. The 32,000-deal arm
completed all 20 epochs in 156.68 seconds; epoch 19 selected by dev CE 0.608660.
Its 512,000 training positions come from 32,000 distinct training deals.
Training times exclude NPZ loading/checkpoint writes; all curves are retained.

The 32,000-deal other-hand error versus ordinary is -0.018716 on 97 check deals,
95% interval [-0.022994, -0.014472], about 3.70% relative improvement. On the
14 earlier gameplay deals it is -0.040827 [-0.049116, -0.032300], about 8.26%
relative improvement. All-receiver Brier there is 0.411280 and kitty 0.182475.
The direction improves at both larger sizes and on both diagnostic populations.
The check and earlier gameplay results are exploratory, already-open DEV data.

**Recommendation:** replace the earlier stop-on-small-data recommendation with
a focused gameplay evaluation of the 32,000-deal checkpoint using the unchanged
legal-pool adapter and proper ordinary/uniform-pool controls. Do not claim a
gameplay win from these ownership results, select another checkpoint on check
scores, or change production/data-generation defaults. R4 remains more accurate;
more training updates and corpus coverage both change here, so this experiment
does not uniquely identify why scaling helped. Additional seeds or larger
held-out populations can test reproducibility, but a new broad sweep is not
necessary before checking whether the measured gain reaches W32 decisions.

Final artifacts: `readout-{603,8000,32000}/` and
`fresh-readout-{8000,32000}/` contain receiver comparisons, calibration, error
examples and saved predictions; `model-{8000,32000}/` retains best/last states
and curves. Data preparation, both training jobs and all readouts exited
successfully. 70 focused tests pass, including nested deal exclusions,
real label reconstruction, cache reuse and model-only rescoring isolation.
