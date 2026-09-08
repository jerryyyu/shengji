# Model + search: findings and next experiment

Status: development evidence, updated September 8, 2026. No deployment.
[Detailed results and artifact pointers](cwv-horizon-diagnostic-evidence-2026-09-07.md)
are preserved separately; this page is the current decision summary.

## What we know

| Finding | Action |
|---|---|
| Default ACDEF-v2 `3cd27716` is the leading W32 candidate: +.126 whole signed levels/round vs production on the reused 520-deal DEV window. | Keep it as the baseline, finished-trick W32/K4/N30/R300 with MC-LCB. This is not a win rate or fresh confirmation. |
| Lower LR improves CE (.6218→.6106), but loses to that default by .0587 levels/round; paired interval [-.1058, -.0115]. | Do not promote a checkpoint on CE alone. This does not prove the newer model is better at choosing actions but search wastes it. |
| Smaller H256, LR1e-4 (`752427c3`, CE .61189), finishes at +.0721 vs production. Versus default: -.0538 [-.1048, -.0029]; versus same-LR H512: +.0048 [-.0433, .0529]. | Default remains the baseline. No resolved size effect at the same LR; the default comparison also changes LR and selected epoch. These are reused-DEV, unadjusted exploratory intervals, not independent confirmation. |
| On 52 cutoff-focused roots, these models change 27 retained sets but only three final moves. One loss excludes a useful action family; another case favors lower LR. | Diagnose nomination separately from MC selection. There is no single demonstrated bottleneck or universal gate repair. |
| Our small original FIT panel also fails to rank six checkpoints in gameplay order. | Keep it for debugging; do not simply replace CE with its regret score. Use more independent positions reached by W32. |
| Matched residual probe: the models remove 37.5–38.7% of across-world state-value variance, but only 1.2–1.4% of action-gap variance. Fixed correction does not clearly improve choices. | Overall position knowledge is not the same as knowing which move is better. Do not implement this correction as a new search policy yet. |
| Current-model T1 points-leaf substitution loses against the fixed heuristic-rollout reference. Training-view alignment changes decisions but does not resolve that loss. | Not a gameplay test or a closure of learned leaves: training uses realized MC-trajectory outcomes, not this heuristic continuation. |
| Changing horizon, effective-action diversity or selector utility did not establish a gain. | Do not rerun a broad grid of these mechanisms or weaken MC-LCB globally. |

The v2/data combination improved the observed gameplay mean over older ACD-v1
by .078 levels/round (exploratory interval [.026, .132]). There is real progress,
but neither ingredient independently separates, and better distribution fit
does not guarantee better action judgments.

**Keep CE for outcome-distribution training; do not select the search model on
CE alone.** Action-gap error and shortlist regret/coverage are candidate offline
metrics, not validated replacements. Test whether they predict gameplay order
on independent W32 development deals before adding an action-comparison loss.

The [completed H256 comparison](https://github.com/jerryyyu/shengji/pull/292#issuecomment-5580129433)
reuses all 520 matched deals; reproducible readout and artifact hashes are at
`~/shengji-archive/2026-09-08/cwv-h256-comparison.aSIiDM/`.

## Next: test where model and MC complement each other

Jerry explicitly added this workstream: determine whether another consumer can
use the models better, including one focused revisit of an existing search
method or one narrow hybrid. No new model training is required for that test.

**Ready, awaiting the existing Strength job's completion:** [PR302](https://github.com/jerryyyu/shengji/pull/302)
implements the fixed default/lower-LR pair with a T1 last-actor points leaf,
52 matched already-opened DEV deals per model, reusing flat-W32 baselines.
Source `8d7ed763` passed review; no additional model arm or review campaign.
This small comparison can detect large effects, not settle every subtle gap.

1. **Measure the division of work first.** On common saved positions/worlds,
   compare model-nominated moves, MC-selected moves and an independent rollout
   reference. Separate useful moves excluded by the shortlist from bad choices
   inside it. Measure action-gap error, not just absolute state-value error.
   Use existing outputs; draw additional diagnostic roots from already-planned
   W32 FIT trajectories, across many independent deals, not more positions from
   the same few games. Freeze any confidence/gap rule before testing new deals.
2. **Test one different use of the model.** The first cheap probe is complete:
   36 FIT roots / 22 deals, reusing 1024-world rollout columns, fixed-coefficient
   correction with independent cheap/correction/reference samples. Action-gap
   noise barely falls, and choice-regret intervals include zero at both doses.
   Do not scale this correction or fit a new coefficient to rescue this panel.
   The existing T1 points-leaf probe is also complete: 52 FIT roots / 26 deals,
   unchanged five-move ballots and N30/R300 samples. Leaf-minus-full-MC reference
   value is -.0469/-.0291 for default/lower-LR. Encoding the last actor, as in
   training, gives -.0459/-.0249; neither is a demonstrated rescue. All use the
   same finite heuristic continuation reference, not actual played outcomes.
3. **Compare consumers, not just models.** Use the same frozen default/lower-LR
   checkpoint pair in W32 and one alternate consumer. Coordinate with Claude
   before revisiting a prior PUCT/leaf configuration, and reuse completed W32
   baselines where compatible. The next decision is a bounded actual-gameplay
   comparison, not another grid against the same heuristic proxy. ACDEF labels
   come from MC trajectories with differing ballots/work budgets; the diagnostic
   reference finishes via heuristic play. Keep that policy difference explicit
   rather than labeling all disagreement prediction error. Report quality and
   measured cost separately; extra compute is allowed.

The correction idea is related to learned control variates. [AIVAT](https://ojs.aaai.org/index.php/AAAI/article/view/11481)
uses heuristic values to reduce variance in **agent evaluation**; it is not
evidence that this proposed search policy will work. Any adaptation must check
sampling/utility consistency, avoid fitting corrections on their own test
returns, preserve information boundaries, and validate the resulting MC gate.

The completed residual probe does not implement or change an MC-LCB gate.
It uses signed-level utility, not production's attacker-point score. It is
mechanistic evidence on restricted FIT nominations, not a gameplay result.

## Engineering and dependencies

- #294/#296: decision-preserving optimizations already integrated. #298's
  separate fixed-state optimization merged at `5b385e82`; no live source swap.
- #299: correct W32 teacher registration/recipe/production-ballot capture
  merged at `d23c084d`; generating better training data is enabled, not proven.
- H256 fit and its 520-deal gameplay screen completed; H1024 is still training
  under Claude's ownership. Do not select an unfinished sweep's mutable best
  checkpoint or repeat completed training/holdout reports.
- Preserve live jobs, all trajectories and held-out deals. No production
  deployment. Detailed results remain evidence, not additional review gates.
