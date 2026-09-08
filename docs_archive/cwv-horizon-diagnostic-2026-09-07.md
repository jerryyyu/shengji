# CWV model-to-shortlist diagnostic — September 7, 2026

Status: development evidence; no policy/default change or deployment.
Diagnostic source: `f2306753476f1e7e768ce9032b328925c6f699c4` (PR #292).

Latest readout: seven saved checkpoints now share the 52-root FIT probe,
including the preserved ten-epoch H256 snapshot. Its final decisions have the
same reference values as H512 lower LR here, despite eight changed shortlists.
Only 16 roots have more than 5 legal moves: this is not evidence of equivalence.
The completed H512 run's final alias has exactly the audited epoch's model
parameters, so no diagnostic replay was necessary.
No tested horizon, diversity or selector-objective intervention establishes a
gain. Cross-fitted reference substitutions show limited, model-dependent
nomination and selection headroom, not a deployable improvement. Keep
finished-trick W32 with its existing MC-LCB selector; do not select
a replacement model from tuning CE alone. The separate **520-deal comparison
is now complete**: ACDEF-v2 has the highest measured mean and separates from
the older ACD-v1 reference, but not from ACDEF-v1 or ACD-v2, in exploratory
paired intervals. It is the leading strength candidate; ACDEF-v1 is the
lower-measured-cost comparator. This is not an equal-work or deployment claim.
The #294/#296 engineering stack now also has a completed natural-game parity
check: exact trajectory bytes, with 25.7% less observed shortlist wall in a
small contended-host window. The completed dropout follow-up does not change
the leading candidate. A report-veto diagnostic finds a small, model-dependent
source of lost nomination gains; it does not justify changing the gate. The
width ladder remains unresolved.

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

## Mechanism decision from the FIT diagnostics

Keep optimized finished-trick W32, incumbent-plus-four, and unchanged MC-LCB
as the comparison baseline. Do not promote immediate scoring, diversity, or
the best-CE checkpoint based on these probes. Do not equate better absolute
CE/MAE with better action ranking or final gameplay.

The audit found a horizon distribution difference and verified the actual
consumer, but no load-bearing selector arithmetic defect in the traced cases.
The next mechanism test compared point versus level-utility selection on
common rollout matrices, without relaxing the confidence gate or increasing
model capacity. Its result is below. The ACDEF-v2 gameplay reconciliation is
now complete below. ACD's lower-LR gameplay comparison is also complete and
inconclusive; ACDEF's lower-LR model has no completed gameplay comparison.

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

## Completed ACDEF-v2 model and gameplay reconciliation

ACDEF-v2 checkpoint `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`
selected epoch 5 at validation CE .6218207448. It uses 96,000 distinct deals,
not 120,000; 76,800 fit / 9,600 validation / 9,600 test. Its completed receipt
now includes the post-training evaluation. At this first comparison the
separate LR1e-4 ACDEF trainer was still live; its later completed checkpoint
is reconciled below. No evolving checkpoint was read.

We independently paired the completed **initial 260-deal** screens by seed,
rank, suit, banker, mirror and team/seat assignment. Both role mirrors stay
inside the deal bootstrap. This is the reused DEV/selection panel, not another
fresh confirmation. Numbers are whole signed levels per played round, unlike
the half-integer model utility used in the sampled-world diagnostics.

| Initial 260-deal screen | Mean utility vs production | ACDEF-v2 minus this model, paired 95% interval |
|---|---:|---:|
| ACD v1 | +.10192 | -.07308 [-.14615, .00000] |
| ACD v2 | +.05192 | -.02308 [-.09808, +.05000] |
| ACDEF v1 | +.04615 | -.01731 [-.10000, +.06346] |
| ACDEF v2 | +.02885 | reference |

ACDEF-v2's own 10,000-resample interval is [-.04038, +.09808]. The original
summary uses 1,000 resamples/a different seed and prints [-.04038, +.10385].
This is bootstrap resolution, not conflicting observed means. No comparison
here establishes an improvement or a general v2 regression. Earlier ACD-v2
already changed ordering on its separately reported 520-deal panel.

The ACDEF-v1/v2 screens bind identical recorded source maps; the older ACD
screens include source/performance revisions. Recorded decision-wall ratios
are 4.64x / 4.72x / 3.10x / 4.74x production respectively, with different host
contention. These are not equal-wall comparisons; the `3x` directory label is
a target, not measured cost. Do not silently pool the 260 and 520 panels.

### Same-state extension, without repeating old inference

The new completed model alone was scored at both horizons on the same 52 FIT
roots and shared W32/MC streams. This took 55.15 seconds on one nice-10 CPU
worker. We retained all earlier model decisions and 1,024-world return columns.
Only ten newly nominated action columns needed additional reference rollouts:
10,240 candidate-world continuations, 2.00 seconds. Reconstructed world hashes
matched the retained reference before adding a column. Every old final-value
metric remained exactly unchanged; no models or actions were reselected using
the reference values.

| New model/horizon | Final reference gain over incumbent | Diagnostic contrast |
|---|---:|---|
| ACDEF-v2 finished | +.03930 | same final moves as ACD-v2 LR1e-4 on all 52 roots |
| ACDEF-v2 immediate | +.03580 | immediate minus finished -.00350, interval [-.01050, .00000] |

Finished ACDEF-v2 changes 8 retained sets versus the best-CE LR1e-4 model but
**zero final moves**; versus ACD-v1 it changes 11 retained sets and 2 submitted
moves. Its final reference value is -.00505 below ACD-v1 and +.00564 above
baseline ACD-v2 here. These sparse, 24-deal FIT contrasts are not gameplay
strength; their bootstrap intervals condition on finite reference worlds.
The exact final tie between models with different data, CE and nominations
further shows why offline loss cannot choose the playing policy by itself.

Evidence: `~/shengji-archive/2026-09-07/cwv-acdef-v2-extension.n0c9TT/` contains
the same-state run, `compare_gameplay.py`, `gameplay-260.json`,
`extend_reference.py`, and the atomic `reference-1024/` extension.

## Direct nomination-versus-selection substitution

To avoid inferring a selector bottleneck from repeated final-choice ties, we
reused the original four finished-model shortlists and all saved N30/R300
point matrices. The candidate menu is exactly the **union of those four
shortlists**, not an exhaustive legal oracle. Each root's 1,024 reference
worlds is split jointly across actions into even and odd rows. One half
supplies reference ranking/direct choices; the opposite half judges them.
The halves swap roles, are averaged within root, then roots within deal.
This removes direct same-draw argmax evaluation; the previously inspected
FIT data do not become an untouched validation set.

The four cells are:

1. Existing model shortlist + actual MC-LCB (reproduced control).
2. Reference-ranked incumbent-plus-four from the fixed union + actual MC-LCB.
3. Existing model shortlist + highest reference mean inside it.
4. Reference-ranked shortlist + highest reference mean inside it.

Reference ranking uses canonical action-index ties and preserves the incumbent.
Direct selection uses ballot-order ties, incumbent first. Actual MC cells use
unchanged raw-point utility, point-shy rule, N30 selection and R300 report.
The direct-reference selector changes precision, objective and confidence rule
together; it is a diagnostic signal substitution, **not a same-cost policy or
an instruction to remove the report gate**.

| Finished model | Model + MC | Reference nominations + MC | Model + reference selection | Both reference substitutions |
|---|---:|---:|---:|---:|
| ACD v1 | +.04435 | +.04435 | +.04989 | +.05265 |
| ACD v2 | +.03367 | +.04435 | +.04163 | +.05265 |
| ACD v2 LR1e-4 | +.03930 | +.04435 | +.04824 | +.05265 |
| ACDEF v1 | +.04435 | +.04435 | +.05243 | +.05265 |

Values are model-unit reference gains over the incumbent, not full-game
strength. Independent units remain **24 deals**, not 104 fold-cases, 52 roots,
four models or four independent confirmations. Main paired intervals:

- Reference nomination alone is exactly zero in reference utility for v1
  and ACDEF-v1; it adds +.01068 for baseline v2 and +.00505 for LR1e-4,
  both with intervals touching zero. Some submitted moves still differ even
  where their reference returns tie.
- Reference selection within the existing shortlist adds +.00554 for v1,
  interval [-.00119, +.01293]; +.00796 for v2 [.00028, +.01741]; +.00893
  for LR1e-4 [.00080, +.01878]; and +.00808 for ACDEF-v1 [.00039, +.01759].
- Both substitutions add +.00830 for v1 [-.00016, +.01834] and +.01899 for
  v2 [.00331, +.03826]. These 10k deal-bootstrap intervals are exploratory,
  conditional on finite reference draws and not multiplicity-adjusted.

Thus the observed gap is **model-dependent and spans both stages**. Baseline
v2 loses some value through nomination on this menu. The existing v1 choices
are harder to improve merely by better nominations, while all models have
some point-estimate headroom from more informative final selection. This does
not establish that MC is the universal bottleneck, that the network has enough
accuracy, or that a proposed cheaper selector would realize the reference gain.

The reference-selection gap was also decomposed over **all** fold-cases,
including losses and ties, not selected winners. For v1, +.00248 of the
equal-deal gap comes from a different N30 nominee and +.00306 from preferring
the challenger that the report rejected. For v2 those contributions are
+.00170 and +.00626. These classifications locate differences under the
reference substitution; they do not label the corresponding MC decision a
bug or prove that increasing one sample budget is sufficient.

All 208 model-MC records were reproduced before accepting counterfactuals.
The control's two-fold average exactly recovers its earlier 1,024-world value.
Zero new neural evaluations, native rollouts or games were needed; summed case
processing was 3.57 seconds. A two-root partial output was resumed to all 52,
with both original artifact hashes preserved. Fifteen new focused tests pass;
31 pass including existing objective replay/control tests. A same-world
choose-and-judge mutant is killed by the explicit disjoint-fold witness.
Independent bounded methods/source review passed.

## Completed fresh 520-deal panel and current recommendation

All four default-learning-rate screens are complete: 520 identical seeded
deals, 13 ranks and both role mirrors (1,040 played rounds per arm), seed0
91261190. This is fresh relative to the initial 260 selection panel, **not**
a new confirmatory population immune to subsequent reuse. We reopened only
completed artifacts and independently matched seed, rank, suit, banker,
mirror and team/seat identity for every arm. Each deal remains one bootstrap
unit. Initial and fresh panels are reported separately, never pooled.

| Saved MLP checkpoint | Mean signed levels/round vs production | Recorded decision wall / production |
|---|---:|---:|
| ACD v1 (`528dbbe0`) | +.04808 | 3.79x |
| ACD v2 (`633663cd`) | +.09904 | 4.39x |
| ACDEF v1 (`528b3a7a`) | +.08750 | 2.73x |
| ACDEF v2 (`3cd27716`) | **+.12596** | 4.37x |

All arms use finished-trick W32, incumbent plus four alternatives, N30
selection and an independent R300 production MC-LCB report. These are whole
signed levels per played round, **not wins per round** or the half-integer
utility used by the sampled-world FIT diagnostics. All four original
arm-versus-production 95% intervals are positive on this panel.

| Paired model contrast | Mean levels/round | Exploratory paired 95% interval |
|---|---:|---:|
| ACDEF v2 minus ACD v1 | +.07788 | [+.02596, +.13173] |
| ACD v2 minus ACD v1 | +.05096 | [-.00673, +.10673] |
| ACDEF v1 minus ACD v1 | +.03942 | [-.01058, +.08846] |
| ACDEF v2 minus ACDEF v1 | +.03846 | [-.01154, +.08942] |
| ACDEF v2 minus ACD v2 | +.02692 | [-.02788, +.08365] |
| ACD v2 minus ACDEF v1 | +.01154 | [-.04327, +.06635] |

10,000 paired deal resamples, seed 20260907, no multiplicity adjustment.
Small endpoint differences from Claude's 4,000-resample ledger or the
original 1,000-resample summaries do not change the observed means. The
corner-to-corner comparison is the only one of these six whose unadjusted
interval excludes zero. This is evidence worth following, not proof that
both individual factors work, an interaction exists, or this checkpoint is
best among all possible checkpoints. The initial ordering reverses on this
panel; that is consistent with selection bias and sampling noise, not by
itself proof of which caused the reversal.

### What changed, and what did not

- **Data:** ACD has 72,000 distinct deals and 10,559,236 rows; ACDEF has
  96,000 deals and 14,077,520 rows (+33%, not 120,000 deals). E/F2 also use
  N90/R900 continuations rather than N30/R300, so this is a data-volume **and
  source/continuation-mixture** change, not an isolated IID scaling factor.
  The common bridge uses engine afterstates and terminal level distributions;
  different continuation labels must retain their source provenance.
- **Model:** these are saved MLPs, not a GRU/transformer architecture comparison.
  Encoder v2 adds 29 public columns; its lower validation CE does not by itself
  select the best playing model. Completed training is not silently treated
  as completed gameplay: only the ACD lower-LR screen has played this panel.
- **Runtime:** recorded policy/selector blobs (`cwv_shortlist`, `mcbot`,
  `teacher_v1`) match across these screens. Other revisions add v2 routing,
  fused static inputs and prepared-lead reuse. Native binary hashes differ,
  and the old receipts do not bind every native source; the audit does not
  certify whole-run binary equivalence. Host contention also differed.
  Consequently the measured wall ratios are useful observations, not a
  controlled intrinsic cost ranking or proof of an equal-cost strength gain.
- **Reporting defect:** all four summaries incorrectly inherit
  `arm_description: identity control` from the shared summarizer despite
  `arm: learned`. Checkpoint/config and recorded outcomes identify the real
  arms. Keep these original artifacts unchanged; fix future summary writers
  and attach this correction rather than replaying games to repair a label.

### Best-supported next recipe

For the next **experimental strength candidate**, use completed ACDEF-v2
checkpoint `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600`
with the existing finished-trick W32/K4/N30/R300 recipe. Retain ACDEF-v1 as the
lower-observed-cost comparator and ACD-v1 as the named historical reference.
This prioritizes the highest fresh-panel mean without pretending it reliably
beats every alternative, changing production, or silently selecting on CE.

### Next-data recommendation, not a proven optimal mixture

The leading existing training base is ACDEF (96,000 independent deals), but
the comparison does not isolate an optimal source ratio:

| Source | Deals | Collection recipe |
|---|---:|---|
| A | 8,000 | Production MC, first-round setup, N30/R300 |
| C | 32,000 | Wider MC ballot, first-round setup, N30/R300 |
| D | 32,000 | Wider MC ballot, sampled rank/banker setup, N30/R300 |
| E + F2 | 24,000 | Wider MC ballot, sampled rank/banker setup, N90/R900 |

These manifests specify 10% candidate-injection opportunities with two legal
exploration candidates, **not** a 10% probability of playing a random move.
The played policy still selects from its candidates. CWV's value target is
the realized terminal outcome after the recorded action, not an average of
the search scores. Thus N90/R900 changes the behavior and continuation that
generate the labels; it does not merely lower Monte Carlo label noise.

For the next bounded data experiment, preserve ACDEF and compare an addition
from optimized, frozen ACDEF-v2 W32 against an equal-sized fresh MC addition.
Use diverse sampled rank/banker setups, complete rounds, disjoint source
deals and fixed training settings. Count mirrored games as one independent
deal. Keep both winning and losing trajectories. W32 is a stronger observed
playing policy, but its usefulness as a training-data source remains untested.
The rank-2 pricing smoke is not the diversity recipe or a reliable scale ETA.

This comparison intentionally changes the generating policy, including its
future play. Preserve that provenance: a pooled model learns the chosen
source mixture, not a pure fixed-policy value. To isolate state-distribution
quality from continuation quality later, relabel the selected states under
one common continuation; do not claim the first addition test isolates both.
Assess held-out nomination and actual W32 gameplay, not validation CE alone.
Existing PT-Luna/Sol fit data can remain a separately labeled candidate source;
their playing strength does not establish the right bulk mixture or sample
weight. This recommendation does not launch collection or authorize a scale.

The integrated `a80af5da` source had a specific recipe-binding gap:
changing the resolved shortlist K4 to K8
leaves trajectory config, code identity and run ID unchanged, and the actual
resume gate accepts the change. A no-game witness reproduced this on a
disposable run slot. Bind the resolved teacher recipe into config/run identity
and check it on worker construction and resume; preserve existing completed
fixed-recipe outputs. The finding is separate from #294/#296 optimization
parity, which remains PASS. See
[the collection review](https://github.com/jerryyyu/shengji/pull/292#issuecomment-5577508273)
and `cwv-pricing-path.9bKPfR/shortlist-recipe-identity.json`.
Claude repaired the registered route at `9c7cc30b`: the policy name binds a
digest of the resolved recipe. Independent actual-`_open_run` verification
confirms an unchanged recipe resumes and K4→K8 refuses. One narrow regression
remains in this exact head's direct unnamed `make_shortlist_bot` call: the
fallback naming call omits its now-required recipe argument. The registered
collection path supplies a name and works. This does not invalidate the
fixed-recipe timing/parity evidence or reopen the optimization review.

Keep the horizon, effective-action diversity and selector objective unchanged:
the focused interventions did not establish gains. The mixed cross-fitted
headroom does not justify a universal claim that either network prediction,
shortlist coverage or MC selection alone is the bottleneck. In particular,
making reference rankings available does not necessarily change the final
action; improving selection under a much richer reference is not a cheap
deployable improvement.

PR #294 provides a separate decision-preserving v2 MLP optimization: reuse the
static v1 base and canonical v2 widening instead of constructing history the
MLP discards. Its independent source review passed. On the real saved
ACDEF-v2 model, 104 paired fixed-state decisions had exact semantic parity
and 1.137x throughput (12.1% less wall) on a contended Mini. That is not a
whole-game or strength result. Adopt only in a **new** named consumer after
integration, never into a running screen; no retraining is needed. See
[the performance report](https://github.com/jerryyyu/shengji/blob/61fcc714aff0108938ad3e99aaa9b0b12671d8ef/docs_archive/cwv-v2-static-widen-2026-09-07.md)
in that PR.

The ACD lower-learning-rate gameplay result below is now complete, as is the
selected ACDEF lower-LR model's final reporting and parameter reconciliation. Claude
is running the user-requested controlled width ladder, not a broad recipe
grid. If a new gameplay comparison is warranted,
use the same optimized source and actual measured work for all candidates,
preserve a fresh validation population, and report uncertainty alongside
cost. No additional large experiment or deployment is authorized by this note.

### Reusable evidence and remaining scope

`~/shengji-archive/2026-09-07/cwv-gameplay-precision.DE3xDH/` contains:

- `completed-fresh-520.json` and `remaining-fresh-520.json`: all six contrasts,
  matched checkpoint/summary/ordered-shard hashes and reproducible scripts;
- `precision.json`: the earlier completed panels, descriptive paired standard
  errors and detectable-effect scale (not a new sample-size authorization);
- `runtime-source-diffs.json`: mapping of recorded runtime hashes to Git blobs;
- `v2-static-consumer/`: the separate resumable fixed-state performance probe.

None of this opens Luna's 26 held-out validation deals or relabels selected
FIT probes as fresh validation. The scoped correctness checks and ablations
are complete; the new width ladder and any independent confirmation remain
outstanding. Failed or inconclusive mechanism
tests, old source revisions and all original screen outputs remain preserved.

The separate cross-fitted substitution evidence is in
`~/shengji-archive/2026-09-07/cwv-stage-substitution.0y4n8c/`:
`run/`, `analyze_selection_gaps.py`, and `selection-gap-stages.json`.
Reusable CLI: `server/scripts/cwv_stage_substitution_audit.py --help`.
Conditional diagnostics alone do not justify training scale or a new selector.

## Lower-LR ACDEF-v2: retained selected epoch and completed final report

The ACDEF-v2 LR1e-4 trainer early-stopped at epoch 10, selecting epoch 7 by
its existing validation-CE rule (rounded CE .6106). Its epoch checkpoint is
immutable after the training loop; the `best.pt` alias is later rewritten
with expanded report metadata. We verified epoch 7 and the current alias were
byte-identical, then bound the diagnostic to **epoch-07.pt** SHA256
`38b013318c9d6373eee995bc737fed31250420e56a347ace64aa71a41d22d1fc`.
The final report subsequently completed after 13,445.9 seconds total wall.
Its rewritten best alias SHA256 is
`8d92dd6e3ba39bfc535d3aef75559c7cda4312cdb265a4202068719d6e6eeea9`.
All six model tensors, model configuration and encoder identity exactly match
the audited epoch7; the file hash changed because report metadata changed.
`final-reconciliation.json` records the comparison without another forward,
rollout or gameplay run. No model was selected from test or gameplay outcomes.

Only this checkpoint was added to the same 52 FIT roots / 24 deals, both
horizons and shared W32/N30/R300 streams. One nice-19 CPU worker completed
the states in 52.13 summed seconds. Seven new nomination columns needed
7,168 extra native continuations (2.17 seconds); all earlier fixed-action
reference values were retained exactly. No training, new games or Luna
validation opening was needed, and existing live jobs stayed unchanged.

| Selected lower-LR checkpoint result | Reference value / contrast |
|---|---:|
| Finished-trick gain over incumbent | +.04435 |
| Immediate gain over incumbent | +.03100 |
| Immediate minus finished, deal-bootstrap 95% | -.01335 [-.03021,+.00071] |
| Finished minus default-LR ACDEF-v2, deal-bootstrap 95% | +.00505 [0,+.01514] |

Versus default-LR ACDEF-v2, 10/52 retained sets change but only one final
submitted move changes. All of the gain comes from one of the 24 deals;
the other 23 effects are zero. At root `027c6f02`, the lower-LR shortlist
includes BJ and MC chooses it rather than CA, a +.24219 within-root reference
gap. This post-hoc example is not a whole-game or population strength claim.
The lower-LR finished reference gain equals ACD-v1/ACDEF-v1 on this panel.

These are model half-integer utility units on finite sampled worlds, not
whole-game levels. The 10k source-deal intervals are conditional on those
worlds and unadjusted. Separate nomination unions can have different coverage
regrets; the cross-run comparison uses fixed-action values on identical
original reference draws, not incomparable union-relative regret scores.
No horizon or model-selection recommendation changes from this FIT probe.

Evidence: `~/shengji-archive/2026-09-07/cwv-acdef-lr-fit.9eI2wm/` retains the
input/producer explanation, per-state run, reference extension, all 52 paired
choice records and reproducible scripts. The first invocation from a newer
scratch tree refused at import because its native engine was absent, before
opening inputs or producing run data. The successful run reused the existing
native `20605956` audit tree after checking its relevant producer code was
unchanged at `8231df45`; no engine rebuild or completed-work replay followed.

The now-completed 520-deal lower-LR gameplay screen uses **ACD**, not this
ACDEF checkpoint; its result is recorded below. The completed ACDEF report
does not substitute for an ACDEF lower-LR gameplay comparison.

## Optimized W32 cost attribution and model-size follow-up

A single bounded cProfile pass at PR #294 head `b8424cd1` reused all 52 FIT
roots and the completed ACDEF-v2 model. Every ordered score, shortlist,
submitted move, report, work count and RNG record matched the prior
unprofiled optimized consumer. The run took 22.124 profile wall seconds,
21.812 CPU seconds and 348.67 MiB peak process RSS. These are instrumentation-
and contention-affected attribution measurements, not new speedup evidence.
The existing 104-pair unprofiled 1.137x A/B remains the performance result.

Root candidate construction/ranking costs 10.224 cumulative profile seconds;
the independent R300 report fold costs 9.992. They are disjoint direct
children of the decision path. Nested costs include tensor construction
(5.165), all selection/report rollouts (6.508), world sampling (4.774),
probability evaluation including stacking/softmax (1.218), and the network
forward itself (0.805). Do not sum nested components into an end-to-end total.

Three concrete follow-ups were identified; the first now has a focused A/B:

- v2's encoder property constructs a fresh lambda per access, but the tensor
  cache keys on encoder identity. Stabilize the versioned callable to restore
  cross-batch reuse. Counters show 9,534 finished-leaf constructions versus
  15,233 tensor constructions. The subsequent 104-pair A/B restored one
  tensor construction per finished leaf on this panel (30,466 → 19,068),
  preserving scores/batches/actions/work/RNG. Summed wall 23.8771 → 21.3826s,
  CPU 22.8157 → 20.4879s: about 10% lower cost on the contended Mini,
  not an isolated-host or whole-game guarantee. The bounded cache may still
  evict entries on other populations. Fix is on [PR #296](https://github.com/jerryyyu/shengji/pull/296);
  no live consumer has changed. Evidence: `cwv-stable-encoder.1WNpF3/ab/`.
- The v2 added columns build full `Memory` 15,233 times (1.852 profile
  seconds) solely to read unseen trumps. A lightweight static equivalent
  should preserve `own_kitty=False` and exact float32 features without
  changing frozen encoder identities.
- 112,768 requested rows need only 15,233 actual tensor constructions under
  reuse. Explore bounded model-output reuse for immutable duplicate leaves;
  bind the model and perspective and test exact output parity under different
  batch shapes before adopting it. This reuse is across candidate actions
  reduced to the same accepted move within one world, not a collapse of
  distinct hidden worlds. Existing input caching does not eliminate repeated
  forwards.

Batch utilization is already high: 864/895 batches are full 128-row batches,
98.44% filled row capacity overall. Larger-batch or cross-process scheduling
is therefore not the first demonstrated bottleneck. The 13 leads/39 follows
are diagnostic strata, not natural-frequency prevalence estimates.

The existing MLP is only 610,764 parameters (`--hidden 512`, trunk 512→256).
Suggested first size comparison: `--hidden 1024` (1,483,468 parameters) and
`2048` (4,015,308), keeping ACDEF data, encoder v2, split, seed, batch,
dropout, auxiliary objective and validation selection fixed. Start at LR
1e-4 and compare with the existing matching 512-wide fit, using 3e-4 only as
a targeted optimization follow-up. These counts exclude the auxiliary head.
Evaluate validation ranking, W32 cost and matched gameplay as well as CE;
test/Luna holdouts must not choose hyperparameters. This is a proposal, not
evidence that larger networks improve strength or preserve current latency.

Full per-state profiles, preserved semantic comparisons and reproducible
driver: `~/shengji-archive/2026-09-07/cwv-w32-profile.WIMsEZ/`.
The model-size proposal is posted in PR #292 comment `5576541381` and sent
to Claude. No existing screen adopts new inference code midway through.

The .805/22.124 forward share is **not a bound on full-game network cost**.
cProfile changes component shares, and this panel does not represent natural
game prevalence. A later teacher-pricing audit found different source routing
and wide-follow workloads; neither its whole-game timing nor this profile
isolates a model-width effect. See PR #292 comments `5577192471`/`5577235396`.

### Natural-game adoption of #294 and #296

The integrated consumer at `a80af5da96604f1539497bb21088a3f1616d9db6`
contains #294 `b8424cd1` and #296 `34cf7352`. Its optimized policy/encoding
files match those reviewed heads. Engine, MC, memory, shortlist algorithm
and trajectory generation are unchanged against the old teacher source
`912679340aafd0a0fe05d762035636da0cda19e8`.

Claude ran before/after A,B,B,A pricing windows on the actual ACDEF-v2
checkpoint: four rank-2 rounds / two deals, one native worker, same seed
91004401 and exploration recipe. Independent reopening found every full
serialized trajectory row identical across all four same-policy repetitions:
244 shortlist rows and 272 production rows per repetition. No row fields were
removed. Configuration, counts and recorded realized work also match exactly.
These repeated runs are not additional independent deals. Trajectories do
not expose all discarded scores; the existing FIT-root score/batch/RNG
witnesses remain the evidence for those internal invariants.

| Consumer | Before seconds/decision | After | Observed wall change |
|---|---:|---:|---:|
| W32 shortlist | 1.51612 | 1.12595 | -25.73% (1.347x throughput) |
| Production control | .12827 | .13176 | +2.72% |

These use generator `runtime.json`, excluding shell startup. The separate
shell-inclusive calculation gives 1.344x, consistently. This is a small
contended-host result, not a universal teacher-cost ratio, independent
width effect or strength gain. In particular, its rank-2 seed has very wide
follow ballots absent from the earlier fixed-state profile. The old toy-v1
versus real-v2 timing comparison also changed encoder routing and deal seeds;
it must not be described as the cost of increasing model width alone.

The optimized run's original printed summary accidentally read the old run's
status path. Raw runtimes and shards were correct; Claude repaired the
reporter to use `PRICE_STATUS`. The independent readout uses each run's own
runtime, retaining the original mistaken summary rather than replaying games.

Adoption parity PASS and exact source/receipt evidence are posted in
[PR #296](https://github.com/jerryyyu/shengji/pull/296#issuecomment-5577422990).
`cwv-pricing-path.9bKPfR/adoption-comparison.json` and its script retain the
comparison. Use the stack in future consumers; do not swap live screen code.

Integration is now complete on main: #294 merged at `28565ccd`; #296 first
merged into its old stacked base rather than main, so #297 cherry-picked its
identical four-file patch onto main without reverting #295. #297 is merged
at `4bf63d91`. The reviewed patch identity and existing parity carry forward;
no duplicate benchmark was required.

## Saved validation curves: CE versus ranking selection

Four completed receipts' recorded CE-selected epochs exactly match the
earliest strict validation minima. No selector-wiring defect was found.

| Model | CE epoch | Top-1-regret minimum epoch | Top-4-regret minimum epoch | Top-4 regret at CE epoch → minimum |
|---|---:|---:|---:|---:|
| ACD v1 | 8 | 3 | 1 | .04824074 → .04337963 |
| ACDEF v1 | 5 | 3 | 1 | .04284722 → .04197917 |
| ACDEF v2 | **5** | 3 | **5** | **.03809028 → .03809028** |
| ACDEF v2 LR1e-4 | 7 | 5 | 5 | .03843750 → .03732639 |

Loss and ranking can favor different epochs, but the leading observed
gameplay model already chose its top-4 minimum. Changing the epoch selector
does not explain that model's scaling limit. The lower-LR e5/e7 pair is a
specific possible later probe, not a reason to launch a selector grid.

These are tuning-data minima, not confidence intervals or expected gameplay
gains. The ranking proxy uses stored ballots in true worlds, no incumbent
union, and U(E[points]); W32 uses exhaustive legal actions in sampled worlds.
Counterfactual early stopping may change which epochs would exist. Preserve
the current selection rule until an actual-consumer comparison supports a
change. Evidence: `cwv-epoch-selection.67bjlx/validation-curves.json`, with
exact receipt identities and extraction script; no new evaluation was run.

## Completed lower-learning-rate gameplay follow-up

The already-running ACD-v2 LR1e-4 screen completed all 520 deals / 1,040
mirrored rounds. Checkpoint `4dc21822` gives +.0971154 whole signed levels
per round versus production, compared with +.0990385 for default-LR ACD-v2
and +.1259615 for default-LR ACDEF-v2. The last remains the highest observed
mean, not a proven winner over every other model.

Paired 10,000-deal-bootstrap contrasts, seed20260907, unadjusted exploratory
intervals (same fresh520 panel, no pooling with the initial panel):

| Lower-LR ACD-v2 minus | Mean levels/round | 95% interval |
|---|---:|---|
| Default-LR ACD-v2 | -.001923 | [-.052885, +.050000] |
| Default-LR ACDEF-v2 | -.028846 | [-.078846, +.021154] |
| ACD-v1 | +.049038 | [-.003846, +.101947] |
| ACDEF-v1 | +.009615 | [-.042308, +.062500] |

Better validation CE has not established better W32 gameplay. These intervals
also do not establish equivalence: small gains remain unresolved. Lower LR
is therefore a training candidate, not a strength-backed default replacement.
Observed decision wall was 4.397x production under the existing pinned
consumer; this is not a controlled same-wall comparison across model runs.
Recomputed completed summaries, deal/mirror identities and ordered shard
bindings are in `cwv-gameplay-precision.DE3xDH/lower-lr-fresh-520.json`, with
`compare_lr_completed.py`; no new games or holdout reads were needed.

Claude's user-requested size ladder is H256 → H1024 → H2048 on ACDEF,
holding the existing H512 lower-LR fit fixed, seed1 and LR1e-4. It originally
used a ten-epoch budget. H256 reached that budget while still improving;
Claude preserved that snapshot and restarted H256 with twenty epochs.
Distinguish the ten-epoch snapshot below from the new fit and disclose actual
epoch budgets/stopping when comparing widths. Select on the fixed validation
rule and assess nomination, gameplay and cost separately; do not tune from
repeated test/Luna-holdout readouts.

## H256 snapshot and the report-veto bottleneck

The preserved H256 e10 checkpoint `596d5125` has validation CE .6163904
versus .6105834 for H512 lower LR. H256 is budget-limited, not converged.
Its immutable checkpoint now lives under
`train-out/cwv/cap-h256.budget-limited-10ep/checkpoints/epoch-10.pt`;
the original `cap-h256` name belongs to the replacement twenty-epoch run.
The relocation preserves the exact checkpoint SHA. Do not replay or silently
substitute the newer model through the old diagnostic's recorded pathname.

Finished-trick W32/K4/N30/R300 is unchanged. The new probe took 21.382 seconds
summed root wall on the earlier diagnostic producer, **not** the optimized
runtime. Only one newly nominated reference action needed 1,024 continuations;
the reference extension took .277 seconds summed wall. Previously scored actions were reused and
their values remained exact. On the common reference union:

| Model | Coverage regret | MC selection regret | Final gain over incumbent |
|---|---:|---:|---:|
| H256 v2 LR1e-4 e10 | .003764 | .009399 | +.044349 |
| H512 v2 LR1e-4 e7 | .001953 | .011210 | +.044349 |
| H512 v2 default LR | .005005 | .013204 | +.039303 |

H256 changes 8/52 retained sets versus H512 lower LR but only one submitted
move; both submitted alternatives have identical reference returns. Of 52
roots, 36 already retain all legal actions, including 11 forced roots; only 16
exercise the shortlist cutoff. Zero final-reference difference is not a
population equivalence result or a measurement of inference-cost savings.

At root `04ba4ee9`, H512 nominates SQ while H256 misses it. On the retained
1,024 independent worlds, SQ is worth -.123047 versus CQ at -.209961, a
.086914 difference in expected signed levels. The H512 selection fold also
prefers SQ, but its report has mean gain 1.6167 points, paired SE 1.1033, and
LCB `1.6167 - 1.7*1.1033 = -.2590`: the report veto falls back to CQ.
H256 submits C6+C6+CQ, which is forced to CQ in all 32 ranking worlds and has
the same 1,024-world level returns as CQ. This is a concrete nomination gain
absorbed by the report gate, not proof that the gate is wrong generally.

One post-hoc counterfactual checks that mechanism across all seven models:
accept the already-evaluated candidate if its complete report mean is positive
despite its failed LCB, leaving every other decision unchanged. Existing MC
records and independent reference values suffice; no model calls, new worlds,
holdout reads or gameplay are involved. Selected results:

| Model | Changed roots | Reference lift over its actual decisions | Exploratory paired 95% interval |
|---|---:|---:|---|
| Default ACDEF v2 | 4 | +.005208 | [+.000041, +.013489] |
| H512 ACDEF v2 LR1e-4 | 2 | +.001892 | [0, +.005595] |
| H256 ACDEF v2 LR1e-4 | 1 | +.000081 | [0, +.000244] |
| Default ACD v2 | 3 | +.002950 | [-.001058, +.009908] |

The default ACD-v2 changes include one worse reference decision. These are
post-hoc, unadjusted 24-deal bootstrap intervals conditional on finite sampled
worlds, not independent confirmation across seven models or strength evidence.
The positive ACDEF-v2 result rests on four deals and measures no downstream
trajectory changes. Keep the existing report gate. This is a candidate for a
single targeted follow-up, not justification for a report-threshold sweep.

Evidence: `cwv-width-fit.O4FkQA/h256/{run,reference-1024}`, README admission
and relocation record, `extend_reference.py`, `test_identity_extension.py`,
and `analyze_report_veto.py` / `report-veto.json`. The identity control gives
zero new reference calls, identical choices and exact zero contrasts on all 52
retained H512 roots. The merge guards refuse changed retained values/choices;
the counterfactual's controls distinguish positive, nonpositive and incomplete
reports and leave already-approved decisions unchanged.

## Completed dropout follow-up

The ACD-v2 dropout0.2 checkpoint `4e6fc12e` completed the same 520 deals /
1,040 rounds on the old pinned consumer. Its mean versus production is
+.092308 whole signed levels/round, exploratory 95% interval
[+.043269, +.140385]. This is a positive policy result, not an improvement
over the default model:

| Dropout0.2 minus | Mean levels/round | Exploratory 95% interval |
|---|---:|---|
| Default ACD-v2 | -.006731 | [-.055769, +.044231] |
| Lower-LR ACD-v2 | -.004808 | [-.055769, +.046154] |
| Default ACDEF-v2 | -.033654 | [-.085577, +.016370] |

Default ACDEF-v2 remains the highest observed mean. Neither the lower-LR nor
dropout follow-up establishes better gameplay than default ACD-v2; neither
establishes equivalence either. These are reused exploratory deals, not
independent confirmation after model selection. Observed wall was 4.364x
production, not a controlled equal-wall comparison. Same deal/mirror/role
pairing, original summary/ordered-shard bindings and 10,000 paired bootstrap
resamples are retained in `cwv-gameplay-precision.DE3xDH/dropout-fresh-520.json`
with `compare_dropout_completed.py`. Only completed summaries were admitted
before outcome reads. No games were rerun.

## v1/v2 target-to-consumer correctness check

A separate bounded reader traced the actual code at `1fc72cc7`; primary review
also inspected the consumer and ran its three v1/v2 routing witnesses (all pass).
No load-bearing sign, seat, unit, bin-support or version-dispatch defect was found:

- `cwv_data.py` rebuilds the acting seat, checks its team role, applies the
  recorded action and labels its outcome with `signed_level_category` from
  that same seat's perspective. The stored utility is cross-checked against
  the category's mapped value.
- `CompleteWorldEvaluator.score_many` feeds the root-seat perspective to the
  versioned encoder. Softmax probabilities and exact terminal distributions
  both use the identical `category_signed_level` support.
- A disposable no-model serving probe returned +.5 / -.5 for the same 80-point
  outcome from attacker / defender perspectives. Mapping checks through 4,120
  points retain +101.5 / -101.5 rather than clipping or reversing the utility.
- Existing actual-consumer tests verify 561-wide v2 routing and refusal of
  bare v1 rows; #294 legally uses the 532-wide fused base followed by canonical
  v2 widening. The original three routing tests ran
  successfully in the compiled test environment, without training or data reads.

One unused helper, `cwv_data.tensors_rows`, always constructs v1 tensors.
There are no callers in the inspected tree; neither training nor inference
uses it. This is deferred compatibility debt, not an explanation for these
results, and does not justify altering live runs or retraining.

The audit does not certify arbitrary custom checkpoints or all engine terminal
accounting. More importantly, correct signs and widths do not make a learned
value function accurate under a different continuation policy.

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
within-trick states. Finish the already-running size comparison; do not add
another broad training sweep in response to these small FIT diagnostics.
