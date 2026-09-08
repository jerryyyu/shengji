# Model + search: findings and next experiment

Status: development evidence, September 7, 2026. No deployment.
[Detailed results and artifact pointers](cwv-horizon-diagnostic-evidence-2026-09-07.md)
are preserved separately; this page is the current decision summary.

## What we know

| Finding | Action |
|---|---|
| Default ACDEF-v2 `3cd27716` is the leading W32 candidate: +.126 whole signed levels/round vs production on the reused 520-deal DEV window. | Keep it as the baseline, finished-trick W32/K4/N30/R300 with MC-LCB. This is not a win rate or fresh confirmation. |
| Lower LR improves CE (.6218→.6106), but loses to that default by .0587 levels/round; paired interval [-.1058, -.0115]. | Do not promote a checkpoint on CE alone. This does not prove the newer model is better at choosing actions but search wastes it. |
| On 52 cutoff-focused roots, these models change 27 retained sets but only three final moves. One loss excludes a useful action family; another case favors lower LR. | Diagnose nomination separately from MC selection. There is no single demonstrated bottleneck or universal gate repair. |
| Our small original FIT panel also fails to rank six checkpoints in gameplay order. | Keep it for debugging; do not simply replace CE with its regret score. Use more independent positions reached by W32. |
| Changing horizon, effective-action diversity or selector utility did not establish a gain. | Do not rerun a broad grid of these mechanisms or weaken MC-LCB globally. |

The v2/data combination improved the observed gameplay mean over older ACD-v1
by .078 levels/round (exploratory interval [.026, .132]). There is real progress,
but neither ingredient independently separates, and better distribution fit
does not guarantee better action judgments.

## Next: test where model and MC complement each other

Jerry explicitly added this workstream: determine whether another consumer can
use the models better, including one focused revisit of an existing search
method or one narrow hybrid. No new model training is required for that test.

1. **Measure the division of work first.** On common saved positions/worlds,
   compare model-nominated moves, MC-selected moves and an independent rollout
   reference. Separate useful moves excluded by the shortlist from bad choices
   inside it. Measure action-gap error, not just absolute state-value error.
   Use existing outputs; draw additional diagnostic roots from already-planned
   W32 FIT trajectories, across many independent deals, not more positions from
   the same few games. Freeze any confidence/gap rule before testing new deals.
2. **Test one different use of the model.** Candidate: many cheap model
   evaluations, with a smaller matched sample of complete rollouts correcting
   their error. The model would inform value estimates beyond merely proposing
   four moves; MC would supply corrections. First check whether residuals in
   *action advantages* are less noisy and whether total cost actually falls.
   This is a hypothesis, not a validated estimator or launch-ready recipe.
3. **Compare consumers, not just models.** Use the same frozen default/lower-LR
   checkpoint pair in W32 and one alternate consumer. Coordinate with Claude
   before revisiting a prior PUCT/leaf configuration, and reuse completed W32
   baselines where compatible. Begin with a small mechanistic comparison; only
   a promising result advances to paired gameplay against W32 and production.
   Report quality and measured cost separately; extra compute is allowed.

The correction idea is related to learned control variates. [AIVAT](https://ojs.aaai.org/index.php/AAAI/article/view/11481)
uses heuristic values to reduce variance in **agent evaluation**; it is not
evidence that this proposed search policy will work. Any adaptation must check
sampling/utility consistency, avoid fitting corrections on their own test
returns, preserve information boundaries, and validate the resulting MC gate.

## Engineering and dependencies

- #294/#296: decision-preserving optimizations already integrated. #298: a
  separate 2.44% fixed-state gain, awaiting review; no live source swap.
- #299: correct W32 teacher registration/recipe/production-ballot capture
  merged at `d23c084d`; generating better training data is enabled, not proven.
- H256 replacement fit stopped after epoch17 and selected immutable epoch14;
  its reporting process remains live. Reuse fixed checkpoints and cached
  references; do not repeat training or holdout reports for diagnostics.
- Preserve live jobs, all trajectories and held-out deals. No production
  deployment. Detailed results remain evidence, not additional review gates.
