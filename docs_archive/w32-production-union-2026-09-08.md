# W32 production-ballot union: focused DEV test

Status: fixed 52-deal gameplay comparison complete; no supported strength win.
Keep unchanged W32. Do not promote the production-ballot union or extend this
screen to chase a positive result.
No production change or deployment. Checkpoint:
`3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`.

## Why this test

64 W32-reached FIT positions, one per independent deal, were selected by
input-only hash order from the first 100 published Run I cluster shards.
Run I itself remains live/unsealed. Its population is rank 2 with 10%
exploration, not a representative sample of every human-game setting.
Train eligibility uses the COMPLETE 16,000-deal I/J population, split seed 7:
12,800 train / 1,600 validation / 1,600 test. Never split a partial corpus.

Independent 1,024-world heuristic-continuation reference, fixed menu of W32
retained moves, top-eight model alternatives and production candidates:

| Cross-fitted opportunity | Mean | Exploratory 95% deal-bootstrap interval |
| --- | ---: | --- |
| Candidate coverage | .01292 | [.00438, .02284] |
| Selection within retained moves | .00479 | [-.00136, .01241] |

Units are the model's half-integer signed-level utility, not whole-game
strength or win probability. Selection and evaluation use different halves
of reference worlds. Intervals are conditional on the sampled worlds and
not multiplicity-adjusted. The finite heuristic reference is not optimal play.

Largest excluded reference-best examples include H10 (model rank 34), C3
pair (rank 1,440), D6 pair (rank 19), and C10 (rank 11). All were already in
production's candidate list. Simply taking more top-model moves would still
miss several. Unioning the production candidates with the retained five gives
about 9.95 candidates on average (5–17) on this panel. Its cross-fitted menu
opportunity is .01317 [.00464, .02313], not an actual policy improvement yet.

## One treatment, fixed comparison

Keep W32/K4/N30/R300, selected checkpoint, mlp-static encoding and successor
reuse. Keep the incumbent first and the four model nominations in order;
append missing production candidates in canonical order. Do not change MC
rollouts, selection, report confidence rule, or tie-breaking.

1. Run treatment on the same 64 saved positions. Reuse the independent
   reference columns already computed; do not rerun the referee or baseline.
2. Run **52 fixed paired deals / 104 mirrored rounds**, seeds
   `91261190..91261241`, rank 2, treatment versus unchanged selected-model W32.
   This reuses an opened DEV seed window, not fresh confirmation. No other
   mechanism, checkpoint sweep, population extension or stop-on-positive rule.
3. Report paired whole signed-level outcomes and deal-bootstrap uncertainty,
   decision CPU/wall, candidate counts and rollouts separately. Additional
   compute is allowed, but no equal-cost claim. Preserve completed pairs on
   failure and resume only missing work with the same recipe.

The intended model lesson is concrete action-comparison training examples:
where useful production moves are ranked below redundant or weak nominations.
This test does not itself establish a new training objective or architecture.

## Artifacts

`~/shengji-archive/2026-09-08/w32-fit-inputs.JYzSHj/` contains the shard-level
snapshot, full assignment, fixed panel, per-root reference matrices and
`analysis.json`. Assignment digests independently match PR #321.
Probe: 5.91 seconds wall, 380 MB maximum RSS. Remaining 63 roots: 26.94 seconds
wall / 192.39 CPU seconds on eight Mini workers; no swaps reported. The probe
result was reused. These are diagnostics timings, not policy gameplay costs.

The actual union treatment changed 7/64 saved-state choices. Mean gain against
the reused independent reference was +.001297, with exploratory 95% deal-bootstrap
interval [-.003540, +.007111]: inconclusive, not the larger menu-opportunity
number above. Invocation wall was 7.98 seconds; no reference recomputation.
See `union-probe/summary.json` under the same artifact root.

The fixed gameplay run started 2026-09-09 00:43 UTC in Mini tmux session
`w32-production-union-20260908`, eight single-threaded workers. Artifacts and
exact rerunnable command are in
`~/shengji-archive/2026-09-08/w32-production-union-screen.6CsyIa/`.
The live source worktree is isolated and must not be modified while it runs.
Each completed mirrored pair is retained; an error drains running workers and
stops admitting more pairs. No outcome-triggered population extension.

Validation: 24 diagnostic/importer/runner tests and 28 union/screen/shortlist
tests passed in pure and native modes; independent review passed the diagnostic
and treatment wiring. Production registry/defaults and report gate are untouched.

## Fixed gameplay result

All 52 independent deals / 104 mirrored rounds completed in 487.4 seconds
(8.12 minutes) of worker-pool wall. No refused/failed/zero-world/short searches
or void fallbacks were reported. The final summary and all 52 pair shards are
retained under the run directory above; `readout.js` checks completeness and
the mirrored deal identities and summarizes saved records without rerunning games.

| Measurement | Union vs unchanged W32 |
| --- | --- |
| Signed levels per round | **−0.05769**, 95% deal-bootstrap CI **[−0.20192, +0.07692]** |
| Union round win rate | **48.08%**, 95% deal-bootstrap CI **[42.31%, 53.85%]** |
| Positive / tied / negative paired deals | 6 / 35 / 11 |
| Full continuation rollouts | 2,378,160 / 2,131,440 (**+11.58%**) |
| Decision CPU seconds | 1,690.69 / 1,706.74 (ratio **0.991**) |
| Decision wall seconds | 1,706.00 / 1,722.26 (ratio **0.991**) |
| Cheap action-world evaluations | 39,196,928 / 43,405,376 |

These are the pre-existing 1,000-replicate deal-bootstrap intervals, not
independent-round intervals. Direct summation of the 104 saved signed utilities
matches the reported mean. This is opened DEV, not a confirmation or a claim
that the policies are equivalent. The interval still permits modest benefit
and harm, but supplies no basis for promoting the extra mechanism.

The treatment appended 8,465 candidates across 1,637 of its 3,494 recorded
decisions. Its baseline opponent had zero union additions. This verifies that
the treatment actually reached the gameplay consumer, not only a unit helper.
Timing is **not** a decision-preserving speedup: the policies reached different
positions, and the union encountered fewer exhaustive legal action-world rows.
Extra MC rollout work was partly offset by that changed state distribution.

## What this teaches us

- Coverage misses are real on the saved FIT panel, including production moves
  ranked below many near-duplicate model nominations. Cross-fitted coverage
  evidence was stronger than evidence for selection errors within the existing
  shortlist.
- A larger useful menu is an opportunity, not a strength guarantee. Once those
  moves entered the real MC/report consumer, neither the saved-state policy
  probe nor the paired games established improvement.
- The finite heuristic-continuation referee is not optimal play. We have not
  isolated continuation bias or proved it caused this null result; do not weaken
  the confidence gate or replace the rollout policy based on this screen.
- The supported next recipe remains the selected 3cd27716 model with unchanged
  W32/K4/N30/R300 and successor reuse. Preserve the diagnostic positions for
  action-gap/rank-quality evaluation of future models. A new training objective,
  rollout policy, or shortlist mechanism needs its own focused hypothesis, not
  another arm appended after seeing these outcomes.
