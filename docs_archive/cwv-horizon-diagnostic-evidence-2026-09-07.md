# CWV model-to-shortlist diagnostic — September 7, 2026

Status: development evidence; no policy/default change or deployment.
Diagnostic source: `f2306753476f1e7e768ce9032b328925c6f699c4` (PR #292).

Latest readout (23:20 EDT): **default ACDEF-v2 `3cd27716` remains the leading
experimental W32 checkpoint**. Its lower-LR counterpart has better validation
CE but loses their completed 520-deal paired comparison by .05865 whole signed
levels/round, exploratory 95% interval [-.10577, -.01154]. This is evidence
against promoting that checkpoint on CE alone, not proof that CE is generally
adverse or that the within-run epoch selector is broken.

Seven checkpoints share the original 52-root FIT probe, including preserved
H256 epoch10. Only 16 roots exercise the shortlist cutoff; the H256/H512 ties
are not equivalence evidence. The default/lower-LR pair now also completes a
52-root cutoff-focused panel: 36 new roots and 16 reused without recompute.
They change 27 retained sets but only three submitted moves. Lower LR's final
reference delta is -.00361, interval [-.02016, +.00931]: unresolved, with a
concrete nomination failure and a concrete improvement both retained below.
No tested horizon, diversity or selector-objective intervention establishes a
gain. Keep finished-trick W32/K4/N30/R300 and its MC-LCB selector; the report-veto
diagnostic remains a hypothesis, not a policy recommendation.

The #294/#296 engineering stack has exact natural-trajectory parity and
25.7% less observed shortlist wall in a small contended-host window. PR #298
separately proposes another 2.44% fixed-state reduction; it is not yet merged.
The teacher-collection fixes in PR #299 are now merged at `d23c084d`. Neither
better-teacher data nor model-width scaling has a completed learning result
yet. ACDEF-v1 remains the lower-measured-cost comparator. No deployment or
controlled equal-wall strength claim follows from these results.

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
now complete below. ACD's lower-LR gameplay comparison is inconclusive;
ACDEF's subsequently completed lower-LR comparison favors its default model
(see "Completed lower-LR ACDEF gameplay comparison").

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
  select the best playing model. Both ACD and ACDEF lower-LR screens have now
  completed; their separate follow-ups below preserve the model identities.
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
confirms an unchanged recipe resumes and K4→K8 refuses. The direct unnamed
factory regression was subsequently repaired at `01f844be`.

[PR #299 now passes source review at `6efef18f`](https://github.com/jerryyyu/shengji/pull/299#pullrequestreview-5136761462).
It also closes two later reproduced failures: replacing a checkpoint after
registration now refuses, and using a supported knob no longer records a
second shortlist bot's ballot as production's. Re-review passed 27 focused
tests plus the actual compiled collector on the original FIT witness: its
recorded production ballot exactly matches independently constructed MC-LCB.
The reviewed `6efef18f` replacement guard compared 8-hex checkpoint IDs. The
subsequent `ffd986ef` hardening now compares the full loaded checkpoint digest
to the digest captured at registration; that delta and the actual merge
`d23c084d` were independently inspected. No collection was launched by this
review. These source fixes do not change
the earlier fixed-recipe optimization evidence or demonstrate training gains.

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

Both lower-learning-rate gameplay results below are now complete, as is the
selected ACDEF lower-LR model's final reporting and parameter reconciliation.
Claude is running the user-requested controlled width ladder, not a broad recipe
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

The ACD and ACDEF lower-LR models now each have a completed 520-deal gameplay
comparison, separately recorded below. The selected ACDEF weights are the
same as this retained FIT diagnostic; the gameplay comparison does not require
replaying those model predictions.

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

## Completed lower-LR ACDEF gameplay comparison

The ACDEF-v2 LR1e-4 model `8d92dd6e` completed all 520 deals / 1,040 mirrored
rounds at seed0 91261190. Both completed configurations were checked before
reading their outcomes; seed, rank, suit, banker and mirrored team/role
identities match exactly. Only this model and the default comparator were
re-read, retaining the default's previously verified summary/shard hashes.

| ACDEF-v2 checkpoint | Tuning CE (rounded) | Whole signed levels/round vs production |
|---|---:|---:|
| Default LR, `3cd27716` | .6218 | +.125962 |
| LR1e-4, `8d92dd6e` | .6106 | +.067308 |

**Lower LR minus default: -.058654, exploratory paired 95% interval
[-.105769, -.011538].** Across 520 deal-level contrasts, 68 favor lower LR,
108 favor default and 344 tie. Lower LR itself still beats production on
this window: +.067308 [.022115, .110601]. These are signed levels, not win
rates. Both mirror rounds stay together in 10,000 bootstrap resamples,
seed20260907. Minor interval-endpoint differences from Claude's ledger use
different resampling settings, not different observed scores.

This focused comparison answers a previously stated question, but the
population is the reused exploratory DEV window. It is not independent
confirmation after model selection. It supports retaining the default
checkpoint and shows why lower validation CE cannot suffice for promotion.
One checkpoint pair does **not** establish that CE is generally adversarial,
that lowering LR is always harmful, or that validation-based epoch selection
is defective. The earlier two-seed CE difference is not a calibrated universal
noise floor.

It also bounds what the FIT proxy tells us. The earlier 52-root probe slightly
favored lower LR in final reference value, entirely on one deal; the gameplay
ordering goes the other way. FIT states with fixed heuristic continuations
are useful for tracing mechanisms, not a substitute for policy evaluation on
the distribution of states a policy actually reaches. The gameplay contrast
does not by itself distinguish prediction, cutoff coverage and final selection.

Both arms use W32/K4/N30/R300. The lower-LR screen uses the reviewed optimized
consumer and costs 3.576x production decision wall, versus 4.375x for the
default's older consumer. Those are unequal observed wall times, not a lower
world/rollout budget for the losing arm. Prior decision-parity evidence permits
using the comparison; the speed difference does not independently strengthen
the scientific quality finding. Preserve the original receipts and compare
future models on the same optimized source.

Evidence: `cwv-gameplay-precision.DE3xDH/acdef-lower-lr-fresh-520.json` and
`compare_acdef_lr_completed.py`, with exact model, summary, ordered-shard,
analysis-script and statistics-source hashes. No new simulation or model
inference was performed for this readout.

## Improve diagnostic coverage without another broad sweep

An input-only census of the same 3,900 Luna FIT decisions / 26 source deals
found 1,686 positions with at least six legal submitted actions, 662 forced
positions and zero unknown counts. Eligible counts by current trick position
are 843 lead, 298 first follow, 268 second follow and 277 last follow. The
census reproduced all 52 old panel action counts and took 1.287 seconds;
it used engine reconstruction/legality, no predictions or new world draws.

Applying the original input-only hash rule within rank/trick-position strata,
now requiring at least six legal actions, produces 52 cutoff-focused roots
over 26 deals: **16 identical old roots and 36 new roots**. There is no
upper-width filter: 10,287 submitted actions total, maximum 5,016 at one root.
Submitted-action counts are not distinct effective actions in sampled worlds.
Selection controls exclude smaller ballots and ignore outcome/model-score
fields. This does not create more independent games or open validation data.

The panel is conditional on cutoff eligibility, not representative
natural-frequency or fresh gameplay evidence. The completed two-model run
below reuses compatible scores, choices and reference values at the 16
overlapping roots and evaluates only 36 missing roots. A future width follow-up
must similarly evaluate only missing roots/columns on common per-root worlds
and candidate unions. Do not replay completed work merely because the parent
panel hash changed or pool overlapping panels as independent evidence.

Evidence: `cwv-cutoff-census.pKF8V6/{census.py,rows.jsonl,summary.json,prepare_panel.py,panel.json}`;
panel SHA256 `048672b5df256dceaf788af9bde45e405c2cb0ac936c894ba443c758cbf81e33`.
All 26 Luna validation deals remain unopened by this audit.

### Completed cutoff-focused default / lower-LR comparison

Both frozen models use W32/K4/N30/R300, finished-trick leaves and 1,024 shared
reference worlds per root. Lower LR uses immutable selected epoch7 `38b01331`,
whose parameter tensors/configuration were already reconciled exactly with
the gameplay alias `8d92dd6e`. There are 52 roots from 26 source deals, all with
at least six legal submitted actions. No further width/outcome filter is used.

| Checkpoint | Union coverage regret | MC selection regret | Final reference gain over incumbent |
|---|---:|---:|---:|
| Default `3cd27716` | .003080 | .018567 | +.071352 |
| Lower LR `38b01331` | .008126 | .017127 | +.067746 |

Lower LR minus default final value is **-.003606**, exploratory paired-deal
95% interval **[-.020157, +.009315]**. This uses equal deal weighting after
averaging selected roots, 10,000 bootstrap draws, seed20260907. The small
negative point estimate agrees with gameplay ordering but does not resolve
the mechanism of the 520-deal loss. Reference utilities are model half-integer
signed levels under native heuristic continuations, not gameplay whole levels,
optimal play, or realized values in the one recorded hidden world.

Coverage is relative to the common union of the two shortlists, including
their shared incumbent, not the exhaustive legal set. The generic new-root
runner saves additional production-ballot reference columns; those columns
are excluded here to match the old roots' union scope. Each root uses the
same worlds for both models; old/new roots retain their respective RNG domains.
These domains sample the same distribution and are not comparison arms.

**27/52 retained sets change, but only 3/52 submitted moves change.** Another
16 cases have the same retained set in a different order; none changes the
submitted move. All changed moves, not only favorable examples, are recorded:

| State prefix | Legal actions | Default → lower-LR submitted action | Lower-LR reference delta | Trace |
|---|---:|---|---:|---|
| `135415ba` (new) | 5,016 | H10/ HK/ S10/ SJ → H10/ H7/ HK/ S10 | -.174805 | Lower LR spends trump H7 in all four alternatives; default retains it. Both chosen moves pass the report gate. |
| `0d60e643` (new) | 7 | D7 → D6 | +.000977 | Near tie under the reference; both report gaps are 4.4 points. |
| `027c6f02` (reused) | 66 | CA → BJ | +.242188 | Lower LR includes the useful BJ single omitted by default; the existing report gate then accepts it. |

At rank7 state `135415ba`, default/lower-LR report LCBs are +8.014 / +4.985
points. Coverage regret worsens by .177734 while selection regret improves
by .002930, summing exactly to the -.174805 final delta. This particular loss
comes from the retained action family, not vetoing the better retained move.
It does not establish a general rule never to spend that trump. The favorable
BJ case is the previously identified old-panel example, not fresh confirmation.

For the 36 new roots only, lower LR's per-world prediction MAE and action-mean
MAE are worse by .01898 and .02384 respectively; both paired-deal intervals
include zero. Old 64-world prediction errors use another union and are not
pooled with these values. Do not treat a narrow FIT metric as a demonstrated
offline replacement for gameplay; the original panel's ordering already failed
to predict this pair's gameplay ordering.

Execution completed 52/52 with 16 roots reused without inference/rollouts.
The 36 new roots cost 249.40 summed state-wall seconds on one nice19 CPU worker;
peak RSS was 405,848,064 bytes. A 600-second invocation deadline was not reached.
This uses the existing native audit producer `20605956` before #294/#296 and
is not a speed benchmark of the optimized consumer. Live training was preserved.
Read-only adapter witnesses reject changed retained reference values and prove
an extra out-of-union column cannot alter coverage; per-root arithmetic checks
bind final delta to the sum of coverage/selection deltas.

Evidence: `cwv-cutoff-pair.Ap2jCh/{README.md,run_pair.py,analyze_pair.py,run/,analysis.json}`;
configuration SHA256 `8f71bc45f17cac01b287ea0136d674da0452426d7d382e064642d20f94ad8a41`.
Atomic outputs preserve all positions and the three changed decisions.

### Offline selection: useful proxies, not a new proven promotion metric

The completed default/lower-LR receipts show CE .621821 → .610583 while recorded
validation top-four regret worsens .0380903 → .0384375. This is consistent with
their gameplay ordering, but the small regret difference has no demonstrated
precision or predictive validity. Those stored-ballot metrics rank true-world
afterstates using U(E[points]); they do not rank all legal actions across W32
worlds, include production's incumbent, or estimate E[U] from per-world returns.
The earlier epoch audit also found default's CE-selected epoch already minimizes
its recorded top-four regret. Simply changing the selector is not an established
repair.

Keep CE for outcome-distribution fit and training diagnostics. For search-facing
nomination, report actual retained-set coverage regret; for final policy use,
report the MC-selected move's reference regret. Pairwise advantage error helps
separate state-value calibration from ordering useful alternatives, with a
zero-advantage control to expose gains driven by nearly tied actions. Evaluate
on common states/worlds, preserve the incumbent, match the deployed horizon,
and state the candidate-union/continuation scope. Report cutoff-eligible and
natural-frequency populations separately, clustered by independent source deal.

Use the completed screens only to nominate a simple candidate proxy, not to fit
a flexible composite and claim validation on the same reused results. Check its
ordering on a future frozen checkpoint and fresh gameplay before replacing
gameplay screening. Differing recipes' own validation populations are not a
common benchmark. The two-model cutoff diagnostic does not supply enough
independent checkpoints or games to settle that metric choice.

### Six-checkpoint proxy check, with no new inference

The existing width-reference cache provides one fixed action union on all
52 original FIT roots/24 deals. Recompute coverage, selection and final regret
from the saved action means and fixed choices for all six checkpoints with
completed 520-deal gameplay. Bind each diagnostic checkpoint to its gameplay
identity; the lower-LR epoch/final alias uses the retained exact tensor
reconciliation. No new outcomes, checkpoints or policy choices are selected.

| Checkpoint | FIT coverage regret | FIT selection regret | FIT final regret | Gameplay vs production |
|---|---:|---:|---:|---:|
| ACD v1 | .003764 | .009399 | .013163 | +.04808 |
| ACD v2 | .012573 | .011271 | .023844 | +.09904 |
| ACD v2 LR1e-4 | .005086 | .013123 | .018209 | +.09712 |
| ACDEF v1 | .001709 | .011454 | .013163 | +.08750 |
| Default ACDEF v2 | .005005 | .013204 | .018209 | +.12596 |
| ACDEF v2 LR1e-4 | .001953 | .011210 | .013163 | +.06731 |

Lower FIT regret is better; higher gameplay is better. Their units differ
(model half-level reference versus whole gameplay levels): compare orderings,
not absolute magnitudes. The reference union includes previously nominated
immediate/diverse actions; it is fixed across all rows/models and not exhaustive.
Every reconstructed metric agrees with the previously published reference
summary. The table reuses completed readouts rather than rescoring gameplay.

**This small panel does not reliably rank the screened checkpoints either.**
ACD v1, ACDEF v1 and ACDEF-v2 lower LR have identical final reference values
at all 52 roots, yet different gameplay means. Default ACDEF v2 and ACD-v2
lower LR tie in aggregate final regret despite different gameplay means.
This does not establish those gameplay gaps as significant; it falsifies the
claim that these diagnostic point estimates reproduce the observed ordering.

The original panel has only 16 roots where K4 plus incumbent excludes any
legal action, and the reference follows a fixed heuristic rather than each
model's ongoing W32 policy. The newer two-model cutoff panel improves action
coverage but still uses the same small pool of Luna source deals. Those are
reasons to improve the diagnostic population/continuation match, not proof
of which mismatch explains each loss. Do not fit a correlation/composite to
six dependent checkpoints and call it a validated selection metric.

Next use input-only selected states from the already-planned W32 trajectory
collection, distributed across more independent FIT deals; preserve the
generator/checkpoint and continuation identity. No additional bulk collection
or screen replay is requested for this. Keep the old panels for mechanism
debugging and reuse their frozen cells for width comparisons. A future
prediction of gameplay ordering needs a prospectively held checkpoint/deal
comparison, not another retrospective metric chosen for these six numbers.

Evidence: `cwv-epoch-selection.67bjlx/{compare_search_proxies.py,search-proxy-comparison.json}`.
The read-only script checks metric decomposition, selected-action membership,
per-deal aggregation, model identity and all 52 saved result rows. It reads
60 small existing evidence files, with no engine/model import or new rollout.

## Incremental unused-Memory optimization

[PR #298](https://github.com/jerryyyu/shengji/pull/298), head `5bdbda69`,
reuses validated v1 public unseen counts while applying the same canonical
v2 feature arithmetic. It avoids rebuilding unused Memory deductions in the
fused MLP path; banker kitty semantics and fallback refusals are unchanged.
The nine checkpoint-bound encoder source files are untouched.

The actual W32 consumer completed 104 matched decision pairs (52 FIT roots,
two counterbalanced repetitions), with all scores, decisions, work counters
and RNG state exact. Wall fell 17.7555→17.3220 seconds (**2.44%**), CPU
17.4443→17.0849 seconds (**2.06%**). Both repetitions improved wall. This is
one contended Mini process, not whole-game or isolated production throughput;
the cumulative 360.39 MiB RSS is not a paired memory reduction. Do not add
this percentage to the earlier natural-game percentage from another workload.

130 focused tests pass in both pure and compiled modes, including actual
evaluator wiring, private-kitty and fallback witnesses. Source-matched receipts
and analysis are in `cwv-v2-unseen.pgTPWO/`. Review is pending; no running
consumer was replaced and no new benchmark is required just for publication.

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
# September 8 follow-up: value knowledge versus action-gap knowledge

This section was appended after the original 1,202-line evidence record was
preserved. The new small experiment does not revise those original results.

Artifact: `~/shengji-archive/2026-09-07/cwv-residual-fit.lvZHuj/`:
`run_residual.py`, `run/config.json`, 36 retained per-root prediction matrices,
`run/summary.json`, `analyze.py`, `analysis.json`. Config SHA
`0b2626ec1392d13164245b89384e68a8484dfb128c124ec67989d12770defe4c`.

The 36 roots / 22 independent source deals are precisely the prior cutoff
panel's non-reused roots with complete per-world returns. The older 16 retain
only means and were not secretly reconstructed. Input/hash selection, no new
deal or outcome selection. Default `3cd27716` and immutable lower-LR epoch7
`38b01331` (already tensor-reconciled to gameplay `8d92dd6e`) only. Every
regenerated 1024-world matrix matches its saved world hash and both prior MAE
statistics per model/root. Rollout entry points are tripwired to refuse; zero
new full rollouts, no training or held-out deal opening. Model prediction
matrices are now retained, rather than discarded after computing an MAE.

Fixed coefficient one: estimate each action's advantage over the incumbent
as its model mean over 384 cheap worlds plus mean rollout-minus-model
advantage over 32 or 128 separate paired worlds. Another 512 worlds supply
the reference. All three sets are disjoint per permutation; 16 permutations
reuse the same finite world population and are not independent observations.
Each model keeps its own original five-move shortlist, incumbent first, with
argmax selection. This does not implement production's points objective or
its MC-LCB gate; returns are model half-integer signed-level units.

| Diagnostic | Default ACDEF-v2 | Lower-LR ACDEF-v2 |
|---|---:|---:|
| State-value residual variance / raw variance | .6247 [.5633, .7019] | .6131 [.5499, .6942] |
| Action-gap residual variance / raw variance | .9881 [.9807, .9961] | .9856 [.9763, .9948] |
| 32-rollout corrected-minus-plain choice regret | +.001197 [-.000250, .002864] | -.000244 [-.003000, .002533] |
| 128-rollout corrected-minus-plain choice regret | -.000331 [-.001706, .001002] | -.000972 [-.003294, .000857] |

Equal deal weight after within-deal averaging; 10k paired-deal bootstrap,
seed20260907, unadjusted exploratory intervals conditional on sampled worlds.
Lower-LR's 32-rollout gap MSE improves .021894→.021106 (difference -.000787,
interval [-.001713, -.000053]), but choice regret is unresolved. Do not turn
that one MSE result into a strength claim. Adding finite cheap-mean variance
gives estimated total estimator-variance ratios .9944/.9900 at 32 corrections
and 1.0133/1.0031 at 128, before charging for model evaluations.

Interpretation: models capture substantial common state/world quality, but
most of that signal cancels when comparing actions in the same world. The
paired MC estimator already cancels common world difficulty. This is not
proof that model capability is absent or that all hybrids fail; it does not
justify implementing this particular fixed-coefficient correction yet. Do
not fit new coefficients or selection rules on these results and present
them as independently validated. Revisit one existing leaf consumer with
the frozen current model pair; do not repeat a broad historical grid.

Work: 130.39s summed model scoring + 3.47s world reconstruction, on one nice
single-threaded CPU alongside Claude's live Mini training/reporting; peak
RSS 473,251,840 bytes. Not an isolated end-to-end performance comparison.
Nine pure tests cover constant offset cancellation, adverse prediction
(fourfold variance increase), exact raw-MC equivalence for a constant model,
disjoint sample wiring, exact selection values and input refusal. Original
same-sample correction/understated-SE defect documented in `leaf_policy.py`
is not revived: no residual SE is substituted into a production LCB.

## September 8: current checkpoints in the existing points-leaf consumer

The alternate-consumer probe is complete, not pending. Reused the cutoff
panel's 52 FIT roots / 26 deals, model-specific five-move W32 nominations
(incumbent first), default `3cd27716` and lower-LR epoch7 `38b01331`, and the
saved independent reference values. Fixed N30/R300 samples and seeds. Only
full continuation was replaced by the existing T1 auxiliary-points leaf in
both selection and report stages; no reranking, new model or new reference
population. T1 finishes the current trick, not one additional full trick.

| Leaf viewpoint | Default leaf-minus-MC reference value | Lower-LR leaf-minus-MC reference value |
|---|---:|---:|
| Existing next-mover encoding | -.04687 [-.08054, -.01641] | -.02914 [-.05695, -.00632] |
| Training-aligned last-actor encoding | -.04587 [-.07762, -.01822] | -.02492 [-.05054, -.00387] |
| Last-actor minus next-mover, paired | +.00100 [-.02403, .02629] | +.00422 [-.00709, .01666] |

Units are model half-integer signed-level reference utility, **not** wins or
observed whole-game levels. Equal deal weight, within-deal averaging, 10k
paired-deal bootstrap seed20260907; exploratory intervals conditional on
these finite reference samples. Mover-view changes 32/52 and 30/52 baseline
decisions. Changing viewpoint changes 21/52 and 15/52 decisions, but gives no
resolved improvement. It does not establish a production fix.

The viewpoint discrepancy is real in source: `cwv_data.bridge_record` and
`value_afterstate.example_from_trajectory_record` encode the successor from
the seat that just acted. `MCValueLeafSearch._leaf_value` passes `clone.turn`
instead. The diagnostic wrapper recovers the last actor from the current or
last completed trick. This is a global final-attacker-points head; **no sign
flip** is applied. The ideal target is viewpoint-invariant, but learned
features need not be. Both viewpoints share the existing banked-point clamp.

**Continuation-policy limitation, not a newly discovered source bug.** The
ACDEF source manifests and the earlier data table in this record identify
actual MC games with differing ballot/work settings. `harvest/trajectory.py`
binds `outcome_for(result.attacker_points, ...)` to the engine's final result;
`cwv_data.bridge_record` uses that outcome for both category and points labels,
not the stored search means. The independent cutoff/reference pipeline instead
uses native heuristic continuation. Accordingly, a loss here measures failure
to preserve choices valued by that heuristic reference. It is not proof that
the leaf's predicted outcome under its training-policy mixture is wrong, nor
that it loses actual gameplay. The same limitation applies to the residual
probe above. Per-record continuation labels are not universally populated;
source manifests carry the provenance. Keep this distinction in any new
offline-metric evaluation; do not tune a proxy to reproduce old gameplay ranks.

Concrete failure in both mover-view models: root
`0ac1b8ee2dadc14d0cbdbda2a76ae5d575fe912fe09839bdaac23d1416da12a3`
(rank5, two plays already in the trick, 21 legal actions). Full MC chooses
`CK,HQ`; the leaf falls back to incumbent `H7,HQ`. Both actions were retained.
Reference value drops .999023→.255859. Full MC's report challenges with
`CK,HQ`; the leaf's report challenges with `C4,HQ`, so their report gaps are
**not** estimates of the same contrast. This is an evaluation/selection
example, not missing shortlist coverage or evidence of an SE arithmetic bug.

Validation: all 52 roots preserve ballot order, per-candidate dose, sampled
world records, RNG state and report seed. A no-truncation canary reproduces
the real full-MC choice and report fields. Four-seat encoder rows match v2
training tensors exactly; NumPy/Torch aux-points errors are below .000021
points. Seven new helper tests plus nine residual tests pass in both pure
and native modes (16 each), exercising the consumer, both leaf stages, inside-
and after-trick viewpoints, unchanged root, no-truncation identity and exact
refusal on changed RNG state. Production registry/defaults are untouched.

Artifacts on Mini (runner, config, canary, 52 rows, summary and analyses):

- `~/shengji-archive/2026-09-07/cwv-leaf-fit.ZGAUah/`, config
  `be6018c54caef38f9c1447beb10478fca32a917e5878c1cec402fec9037dbdf5`.
- `~/shengji-archive/2026-09-07/cwv-leaf-lastactor.he7WlF/`, config
  `b8096f4ed105c198548586cb05fee7f8294a414ebb9c6879b8fd717c44517470`;
  `view-comparison.json` contains the paired viewpoint contrast.

Each model/view uses 39,000 predicted leaves, zero exact/terminal leaves.
Summed leaf-search walls: mover 9.03/8.92s, last-actor 8.97/8.97s; peak RSS
494/489MB. One nice, single-threaded CPU, no live-job edits. These are not
isolated full-game speedup numbers. Two canaries reran full-MC searches; no
reference returns, training or held-out games were regenerated. Initial
`cwv-leaf-fit.lTUe4r` smoke stopped before publishing a root because JSON
lists were compared with live RNG tuples; it remains preserved. Logical JSON
normalization fixed that comparison, with a real changed-state refusal test.

Next: retain the default W32 baseline and CE training. Coordinate one bounded
gameplay comparison with a fixed alternate consumer and the same checkpoint
pair; do not gate that scientific question solely on agreement with heuristic
continuation, and do not expand to a depth/model grid. Independently collected
W32 FIT roots should validate candidate action-gap/coverage metrics before
those metrics choose checkpoints or motivate a new training loss.
