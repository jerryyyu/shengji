# CWV model-to-shortlist diagnostic — September 7, 2026

Status: development evidence; no policy/default change or deployment.
Diagnostic source: `f2306753476f1e7e768ce9032b328925c6f699c4` (PR #292).

## Finding and test

The ordinary CWV training and candidate-evaluation bridge encodes the state
immediately after a candidate action. W32's actual consumer first lets the
heuristic finish the current trick. Its nonterminal inputs therefore have
all 16 v2 trick-local added columns at boundary constants; the other 13
points/hand-shape columns can still vary. This is a real distribution
difference, not proof of a defective encoder or cause of a gameplay loss.

The paired diagnostic uses saved Luna **fit-only** positions: 52 roots,
one per rank/current-trick-position stratum selected by an input-only hash,
24 distinct deals. The 26 Luna validation deals remain untouched. All models
share exhaustive legal actions, W32 ranking worlds, incumbent-plus-four
shortlists, and production N30/report R300 final selection. An independent
64-world stream provides native heuristic-continuation reference values on
the union of all nominated actions and the production ballot.

Reference utilities are transformed per world before averaging, in the
model's half-integer signed-level units. They are not win rates, full-game
strength, perfect play, or the value of a move in the one recorded true world.
Aggregation weights source deals equally after averaging their selected roots.

## Initial horizon result (64 reference worlds)

| Model | Immediate minus finished final reference value | Exploratory paired 95% interval |
|---|---:|---:|
| ACD v1 | -.01834 | [-.04134, -.00174] |
| ACD v2 | +.00543 | [-.00651, +.02539] |

Both models' per-world absolute value error worsens at the immediate horizon.
Keep finished-trick W32 as the baseline: a blanket immediate-state switch is
not supported. The intervals bootstrap 24 deals, condition on the sampled
reference worlds, and are not confirmatory or multiplicity-adjusted.

## Expanded saved-checkpoint comparison

All four models and both horizons were subsequently evaluated on the same
roots with a shared expanded nomination union. Lower error/regret is better.

| Finished-trick checkpoint | Per-world value MAE | Union coverage regret | MC selection regret inside shortlist | Final reference improvement over incumbent |
|---|---:|---:|---:|---:|
| ACD v1 | .78244 | .00749 | .01400 | +.04975 |
| ACD v2 | .78869 | .02148 | .01497 | +.03478 |
| ACD v2 LR1e-4 (best tuning CE) | .79946 | .00684 | .02116 | +.04324 |
| ACDEF v1 (larger dataset) | .75872 | .00651 | .01497 | +.04975 |

The incumbent is the first production-ballot action, **not the full production
policy's selected move**. Coverage regret is relative to the nominated union,
not an exhaustive oracle. Do not compare union-regret values from separately
constructed unions without recomputing a common reference population.

ACDEF-v1 improves prediction error and changes 10/52 retained sets, but chooses
exactly the same final move on all 52 roots as ACD-v1 finished. LR1e-4 improves
coverage relative to baseline v2 here, but incurs more MC selection regret.
Thus better CE, better nomination and better final decisions are distinct.

On the initial two-model union, v2 finished has better mean-advantage MAE than
v1 (.08565 vs .09230), yet worse direct-model-argmax regret (.07048 vs .05035).
Predicting zero advantage has MAE .09473; many alternatives are tied/similar.
This control illustrates why small average prediction improvements need not
fix the important ranking errors. It does not establish that value is useless.

## Concrete miss and diversity ablation

At saved root `01422afe`, v2 finished excludes SK+SQ and chooses HK; v2 immediate
keeps SK+SQ and MC chooses it. v1 behaves in the opposite direction. A post-hoc
1,024-world evaluation over all 11 legal moves still ranks SK+SQ first
(+.55664 utility vs HK +.25781). However, in the **recorded true world every
move loses** under that heuristic continuation. This is a nomination example,
not a claim that the alternative would win that recorded game.

An additional lead-only census found that v1 finished's 55 retained submitted
actions represent only 45 distinct accepted-card vectors across W32; 5 of 13
lead roots contain duplicates. Different throws can consume shortlist slots
while producing the same sampled outcomes. A completed bounded research ablation
tested effective-action diversity at the cutoff. Equality across 32 worlds
is not equivalence in all worlds; such a change is a policy experiment, not a
decision-preserving speedup. Preserve the incumbent and do not deduplicate
merely because scalar model values happen to match.

The diversity implementation preserves the incumbent, K, N30/R300, and the
baseline ordering of any retained set. It prefers distinct **complete ordered
W32 accepted-card vectors**, then backfills duplicates if needed. It neither
deduplicates equal scalar predictions nor assumes one-world equality is enough.
It is opt-in diagnostic code, not a new registered/default policy.

Across the same 52 roots, four saved models changed 4–6 retained sets each.
Effective classes across all roots increased from 163–166 to 175, at a total
signature-construction cost of .94 seconds. The full comparison took 79.89
seconds. Three models changed one submitted move from C6+C6+CQ to CQ; these
had identical reference returns. **Every model's final reference-value delta
was zero.** No strength or speedup claim follows from extra class coverage.

## Fresh 1,024-world corroboration

The original 64-world reference can misidentify the best retained move.
We therefore fixed every already-selected action and re-evaluated **all 52
roots**, both horizons and diversity arms, against one new shared 1,024-world
stream per root. No new model inference, games, validation opening, action
reselection, or fit-population selection was involved. This took 50.01 seconds.

| Fixed recipe | Final reference gain over incumbent | Immediate minus finished | Exploratory paired 95% interval for horizon difference |
|---|---:|---:|---:|
| ACD v1, finished | +.04435 | -.01864 | [-.03823, -.00244] |
| ACD v2, finished | +.03367 | -.00338 | [-.02006, +.01341] |
| ACD v2 LR1e-4, finished | +.03930 | -.00831 | [-.02285, +.00142] |
| ACDEF v1, finished | +.04435 | -.01301 | [-.03006, +.00106] |

These remain **FIT diagnostics**, not an independent gameplay comparison.
Intervals bootstrap source deals, condition on finite reference draws, and
are not multiplicity-adjusted. The small positive v2 immediate-horizon point
estimate from the original reference changes sign. None supports switching
the baseline horizon. Diversity again has exactly zero final-value effect.

The initial coverage improvements for v1 and ACDEF-v1 disappear on the new
reference; v2 retains a small coverage improvement without a final-choice
gain. Consequently, calling the final selector the primary bottleneck solely
from the original coverage/selection-regret decomposition would overclaim.

## Why MC did not choose some newly admitted options

For all three roots where the original diversity result improved retained
reference value, we replayed the exact N30 selection and R300 report streams.
The independent full-rollout reference **reproduced the actual per-candidate
selection means and the optimized report consumer's gap/SE** to 1e-12.
This checks the consumer wiring, not just a helper's self-consistency.

- Rank 4, root `00a09e5b`: D10 and D10+D9 appeared +.09375 better than DJ in
  the 64-world readout. A fresh post-hoc 1,024-world case stream put them at
  -.02344 and -.00781. All tested diverse ballots' fresh best was DJ.
  The report gate was not demonstrably suppressing a real improvement.
- Rank 10, root `04ba4ee9`: D10+D8 went from +.17188 to -.06934 vs CQ;
  the approximate paired 95% interval was [-.12530, -.01337]. SQ's apparent
  +.21875 shrank to +.02246, interval [-.03097, +.07589].
- Rank Q, root `027c6f02`: BJ+S6 retained a +.07422 level-utility gap over CA,
  interval [.01029, .13815]. N30 instead sent BJ+S4 to the report fold.
  Both alternatives have similar fresh **point** gains (+.659 vs +.693),
  despite different level gains (+.074 vs +.004). Production selects by raw
  points with its point-shy tie-break, while the model ranks expected level
  utility. Objective choice and sampling precision are separable hypotheses;
  this one outcome-selected example does not establish a policy improvement.

Those case intervals describe sampled-world uncertainty for post-hoc FIT
cases, not population strength. The separate full-panel corroboration above
uses a different fresh stream and all roots. Neither diagnostic opens the
26 preserved Luna validation deals.

## Best-supported recipe and next decision

Keep optimized finished-trick W32, incumbent-plus-four, and unchanged MC-LCB
as the comparison baseline. Do not promote immediate scoring, diversity, or
the best-CE checkpoint based on these probes. Do not equate better absolute
CE/MAE with better action ranking or final gameplay.

The audit found a horizon distribution difference and verified the actual
consumer, but no load-bearing selector arithmetic defect in the traced cases.
The next mechanism test compared point versus level-utility selection on
common rollout matrices, without relaxing the confidence gate or increasing
model capacity. Its result is below. First reconcile Claude's already-running
ACDEF-v2 and queued LR1e-4 gameplay comparisons before another large experiment.

## Selector objective ablation (completed)

The model ranks expected signed level utility, while production MC scores raw
attacker points. To isolate that mismatch we froze the four finished-trick
models' shortlists on all 52 FIT roots. Each root gets one common N30 selection
and R300 report matrix, obtained from the actual native heuristic rollout.
Both objectives then consume those values through the **registered production
MCBot.decide_play** implementation, not an independently rewritten selector.
The independent 1,024-world reference from the prior full-panel run is reused;
it never selects the challenger or supplies the confidence statistic.

The point control reproduced all 208 saved model-position controls, including
no-search roots, candidate order, selected/challenger indices, means, paired
SE, report seed/gap/statistic and work counts. The alternative uses
`40 * attacker_level_utility(points)`: the model's uncapped utility, not the
legacy `LEVEL_OBJECTIVE` option's three-level cap plus `.2 * points` term.
The point-shy rule and its numeric epsilon of 2 stay unchanged (equivalent to
.05 utility units in the level arm); report alpha, critical value and minimum
gain are unchanged. This specifies an objective intervention, not a claim that
the units of every threshold are inherently interchangeable.

| Model | Point-based final reference gain | Level-based final reference gain | Level minus point, exploratory paired 95% interval |
|---|---:|---:|---:|
| ACD v1 | +.04435 | +.04569 | +.00134 [-.00219, +.00692] |
| ACD v2 | +.03367 | +.03501 | +.00134 [-.00219, +.00692] |
| ACD v2 LR1e-4 | +.03930 | +.04064 | +.00134 [-.00219, +.00692] |
| ACDEF v1 | +.04435 | +.04569 | +.00134 [-.00219, +.00692] |

Each model changes six submitted moves, with the same per-root reference
effect. The effect is small, inconclusive, and leaves relative model gaps
unchanged. This does **not** establish that objective mismatch explains model
scaling or that the level variant beats the existing policy in gameplay.

A useful case is root `06528b83`: point selection nominates SA and the report
keeps incumbent SQ. Level selection nominates H10 and its report lower bound
clears zero. H10 is +.16602 reference utility versus SQ on the saved independent
worlds. Other changed decisions lose value, including root `0e6731df`
(-.04199), so the example must not substitute for the full-panel result.

The complete run used 71,940 fresh native candidate-world continuations,
reused the same matrices for both objectives and all four models, and took
16.09 seconds on one nice-10 CPU worker. Replayed MC records' work counters
denote logical matrix lookups; they are **not** additional fresh rollouts.
No neural inference, training, new games, validation outcomes or live jobs
were involved. Source tests exercise objective-induced decision reversal in
both team perspectives, positive-mean/negative-LCB refusal, high kitty-point
utility without clipping, no-search roots, control mismatches, FIT admission
and deal-weighted summaries. 31 focused native tests passed.

Evidence: `~/shengji-archive/2026-09-07/cwv-selector-objective.HBuGwT/run/`.
Reusable CLI: `server/scripts/cwv_selector_objective_audit.py --help`.
Per-root atomic outputs preserve completed work and bind the saved decisions
and reference artifact. No default, registry entry or production source changes.

## Scope, cost and reproducibility

- First diagnostic: 59.24 seconds summed scoring wall on one Mini CPU worker.
  Expanded four-model comparison: 114.63 seconds. No retraining or new games.
- Per-root atomic files support same-config resume. An initial two-root run
  was resumed for the other 50, preserving the first two outputs.
- 37 native focused tests passed; 23 pure core/runner/shortlist tests passed.
  Tests exercise actual MC selection/report wiring, real consumer score parity,
  repeated sampled worlds, fourth-seat/terminal controls, fit-only selection,
  retained provenance and completed-peer recovery after a failure.
- Existing live jobs and source trees were not modified.
- Diversity delta: 31 native focused tests passed, including a forced CLI-to-MC
  wiring change at equal K/N/R, failed-throw acceptance, full-vector equality,
  incumbent aliases, and stable backfill ordering. No production file changed.
- Private evidence root on Mini:
  `~/shengji-archive/2026-09-07/cwv-horizon-shared-fit.NNogWA/`:
  `panel.json`, `run/`, `expanded-models/`, `advantage-analysis.json`,
  `analyze_advantages.py`, `lead-equivalence-census.json`, and the case extension.
- Diversity/corroboration evidence on Mini:
  `~/shengji-archive/2026-09-07/cwv-effective-diversity.Jn3Qq9/`:
  `run/`, `trace_selection.py`, `selection-trace/`, `corroborate_panel.py`, and
  `full-panel-1024/`. Per-case/root outputs retain sampled-world hashes, raw
  point/level return matrices, fixed choices and source bindings; completed
  peers survive a later failure. Raw teacher positions remain private.
- CLI: `server/scripts/cwv_horizon_audit.py prepare --help` and `run --help`.
  Run with the native extension built, `SHENGJI_FAST=1`,
  `SHENGJI_REQUIRE_VOIDS=1`, and one BLAS/Torch thread per process.

This does not overturn the fresh 520-deal gameplay comparison: ACD-v2 minus
v1 was +.05096 levels/round, interval [-.00673, +.10673], hence inconclusive.
Nor does it close trick-local features for consumers that actually score
within-trick states. No new broad training sweep is the next action.
