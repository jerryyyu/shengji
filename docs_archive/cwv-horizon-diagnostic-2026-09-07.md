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

## Horizon result

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

## Concrete miss and next ablation

At saved root `01422afe`, v2 finished excludes SK+SQ and chooses HK; v2 immediate
keeps SK+SQ and MC chooses it. v1 behaves in the opposite direction. A post-hoc
1,024-world evaluation over all 11 legal moves still ranks SK+SQ first
(+.55664 utility vs HK +.25781). However, in the **recorded true world every
move loses** under that heuristic continuation. This is a nomination example,
not a claim that the alternative would win that recorded game.

An additional lead-only census found that v1 finished's 55 retained submitted
actions represent only 45 distinct accepted-card vectors across W32; 5 of 13
lead roots contain duplicates. Different throws can consume shortlist slots
while producing the same sampled outcomes. The next bounded research ablation
is to test effective-action diversity at the cutoff. Equality across 32 worlds
is not equivalence in all worlds; such a change is a policy experiment, not a
decision-preserving speedup. Preserve the incumbent and do not deduplicate
merely because scalar model values happen to match.

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
- Private evidence root on Mini:
  `~/shengji-archive/2026-09-07/cwv-horizon-shared-fit.NNogWA/`:
  `panel.json`, `run/`, `expanded-models/`, `advantage-analysis.json`,
  `analyze_advantages.py`, `lead-equivalence-census.json`, and the case extension.
- CLI: `server/scripts/cwv_horizon_audit.py prepare --help` and `run --help`.
  Run with the native extension built, `SHENGJI_FAST=1`,
  `SHENGJI_REQUIRE_VOIDS=1`, and one BLAS/Torch thread per process.

This does not overturn the fresh 520-deal gameplay comparison: ACD-v2 minus
v1 was +.05096 levels/round, interval [-.00673, +.10673], hence inconclusive.
Nor does it close trick-local features for consumers that actually score
within-trick states. No new broad training sweep is the next action.
