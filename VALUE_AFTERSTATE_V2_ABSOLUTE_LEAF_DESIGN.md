# Value-Afterstate V2 — absolute leaf value

Status: draft design for review. This document grants no data opening,
implementation, compute launch, training, audit opening, gameplay, PUCT,
BELIEF integration, merge, strength, promotion, or deployment authority.

Date: 2026-08-29

Value V1 exact source:
`c98bdeb666df18f2640d717f408194b6e60e62bd`

Value V1 terminal external SHA-256:
`7011a716ad621cfdd1a0825676d63a4e519d5a25d17742941b9dc31a7f3a7798`

Value V1 independent reconstruction receipt SHA-256:
`2c361a3e859da2c41dfc4293ef00d8326b097f9ad831fead3f3c6625500e4a35`

## 1. Decision

V2 is one minimal known-world absolute leaf-value experiment. It does not
retry Value V1, build search, add a policy head, or bundle the proposed
one-trick rollout consumer.

The permanent callable contract is:

```text
V_theta(any legal play-phase state, root-team perspective)
    -> distribution over terminal signed-level outcomes
    -> expected signed-level value
```

This is the value interface needed by later MCTS/PUCT. V2 changes the data,
representation, and training target needed to test that interface; it does
not create a Shengji-specific action ranker that cannot score arbitrary tree
leaves.

## 2. Why this is a new lane

Value V1 ended in the independently reconstructed terminal route
`SELECT_NONE_NO_ACTION_ADVANTAGE`.

- V0's apparently large population was 520 selected state groups and 7,446
  candidate/replica rows, but only 126 distinct deal clusters. Its 364 train
  states came from 56 deals. The model's held-out lift survived controls that
  destroyed action/world association and therefore was not usable value.
- Its paired-label ceiling was real: 321 eligible states, mean action signal
  `+0.084112` signed levels, interval `[+0.036050, +0.134259]`, and 23.3644%
  non-incumbent dose.
- The learner had only 44 independent fit deals and 11 selection deals for
  212,377 parameters. Fit loss improved while selection loss was already
  worse than the exact-zero predictor at epoch one and never recovered.
- On 49 natural audit states from only 21 deal clusters it changed 35 actions,
  31 changes were nonpositive, conditional selected utility was `-0.085714`,
  and only 1/8 seeds was positive.
- Complete-world features changed predictions, but their removal did not hurt
  action utility. Controls otherwise behaved correctly.
- The two continuation replicas were noisy: replicate correlation was 0.219.

V2 therefore tests a smaller structured absolute value on more independent
deals with more precise labels. More epochs or a wider V1 model is not a
repair.

## 3. MCTS/PUCT compatibility invariants

The implementation and every serialized inference row must enforce:

1. The input is a complete engine state plus a fixed root-team perspective.
2. An action enters only after the engine applies it and produces a successor.
3. Incumbent identity, ballot position, action index, source, teacher,
   continuation policy, rollout depth, search counts, outcome, seed, fold,
   and artifact identity are absent from inference tensors.
4. Empty and nonempty current tricks are both valid. The model may score a
   start-of-trick state, a partial trick, or any later nonterminal tree leaf.
5. The root-team perspective remains fixed while value is backed up through a
   future search tree.
6. Terminal states bypass learning and return their exact outcome.
7. Future PUCT consumes normalized expected value; the full distribution is
   retained for calibration and tail analysis.
8. Known-world V2 remains separate from BELIEF. Future belief aggregation may
   average or otherwise aggregate V across compatible complete worlds, but it
   is not part of this experiment.

For diagnostics only, sibling action advantage is derived as:

```text
A_theta(s, a, incumbent)
    = E[V_theta(engine(s, a))]
      - E[V_theta(engine(s, incumbent))]
```

The callable model never receives the pair or emits an action-specific head.

## 4. Estimand and labels

For complete state `s`, root partnership `t`, frozen continuation policy
`pi_c`, and continuation identity `r`:

```text
z(s, t, pi_c, r)       = terminal signed-level outcome for t
V^{pi_c}(s, t)         = E_r[z(s, t, pi_c, r)]
```

The engine owns every transition and outcome. The same continuation identity
is used across sibling candidate actions, so candidate-minus-incumbent
differences use common random numbers.

Every root and engine-reached successor receives exactly eight continuation
replicas in the first scientific design. Replicas 0--3 and 4--7 form frozen
precision halves. The R=2/4/8 curve informs only a later design; it cannot
change V2 after outcomes are visible.

The freeze binds `pi_c` completely: all four actor policy/checkpoint
identities, policy configurations, root-team perspective convention, and the
domain-separated seed schedule. V2 estimates value under this named policy;
it does not claim optimal value.

## 5. Outcome-blind population scale

V2 uses fresh independent deal groups and exactly one selected root state per
deal. Raw action, candidate, and continuation rows are never reported as
independent samples.

The score-free capacity gates choose exactly one of these preregistered tiers
before a scientific population is generated:

| tier | natural fit | diverse fit | mechanics fit | select | audit | total |
|---|---:|---:|---:|---:|---:|---:|
| D256, minimum | 128 | 0 | 32 | 48 | 48 | 256 |
| D512, preferred | 256 | 64 | 64 | 64 | 64 | 512 |
| D1024, maximum | 512 | 128 | 128 | 128 | 128 | 1,024 |

Thus the learner receives 160, 384, or 768 independent fit deals. At the
50,000-parameter ceiling, those tiers improve independent-fit-deals per
parameter by about 15x, 37x, or 74x over V1's 44 deals / 212,377 parameters.
Candidate successors provide additional supervised states, but never inflate
these independence ratios or the statistical sample size.

The chosen tier is the largest whose exact source supply exists and whose
complete-DAG projection passes Section 13 with 2x wall headroom. Ties choose
the smaller tier. The rule consumes no outcomes, model predictions, or
continuation labels. D256 is the minimum admissible experiment; if it does
not fit, the design closes. The exact tier, attempted-deal ceilings, member
counts, and every source identity bind into the immutable freeze.

Deal-to-split assignment is complete before any deal is played. The freeze
first constructs an exact slot ledger whose rows bind split, source, required
phase/position/role cell or mechanics surface, trump-rank slot, and trump-mode
slot. Within each split/source group, slots have ordinal `i = 0..n-1` and use
these literal orders:

```text
phase/position/role = lexicographic(
    [early, middle, late], [lead, follow], [attacker, defender])
mechanics_surface   = [multi-card, wide-ballot, late/high-point]
trump_rank          = [2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K, A]
trump_mode          = [spades, hearts, diamonds, clubs, no-trump]
```

The former singleton joint-ordinal layout is superseded for every FIT group.
Each FIT group count is even and is partitioned into adjacent pairs
`(2j, 2j+1)`. Natural and diverse pair members share
`phase_position_role[j mod 12]`, `trump_rank[j mod 13]`, and
`trump_mode[j mod 5]`; mechanics pair members share
`mechanics_surface[j mod 3]`, `trump_rank[j mod 13]`, and
`trump_mode[j mod 5]`. A deterministic pair ID is derived from the validated
canonical slot ID and is independent of outcomes, labels, and predictions.
Pair members retain distinct slot and attempted-deal identities. Select
pairing remains the separate epoch-select/precision-select construction below.
This is a slightly coarser paired marginal balance than singleton assignment,
and is the frozen geometry required by the world reassignment control.
This changes no `V^pi_c` label, estimand, model input authority, or execution
authority; it changes only the outcome-blind pairing geometry and control
reassignment.
Natural attempted deal identities are then derived from the domain-separated
`tier | split | slot_id | attempt_index` hash schedule. Eligible sealed
external-source game identities are ordered by a separately domain-separated
game hash and assigned to their already-source-bound slots before replay.
An attempt may fill only its assigned slot and may never cross a split,
source, or stratum boundary. Replacement, when a preregistered outcome-free
eligibility reason fires, advances only to the next preassigned identity for
that slot and remains inside its frozen attempted ceiling. The builder API
does not receive or persist terminal outcomes while assigning slots.

For the first D256 scientific run, that ceiling is exactly **128 attempts per
slot**.  This is a scientific population ceiling, not the capacity runner's
separate 384-attempt total.  It was fixed from the repaired-head score-free
preflight before any continuation outcome existed: 32 fixtures were retained
after 301 attempted deals.  The pooled acceptance estimate is 32/301 and its
one-sided 95% Wilson lower bound is 0.0805; under the explicitly planning-only
i.i.d. approximation, 128 attempts gives the conservative family-wise bound
`256 * (1 - 0.0805)^128 < 0.0056`.  That approximation sizes the cap; it does
not assert equal acceptance across strata.  A slot that exhausts all 128
identities remains unfilled and routes to `REFUSE_RESOURCE_INCOMPLETE`; it may
not borrow an identity, slot, split, source, or stratum, and it does not
authorize a retry.

Population construction is part of the service wall even though it precedes
the composed label/training DAG.  The runner records the exact wall
nanoseconds needed to retain its 32 preflight fixtures and projects each tier
as `measured_wall * tier_population / 32`, rounding up.  The typed receipt
requires D256 complete wall to equal that population projection plus the
composed label/training critical path, and the outcome-blind tier gate applies
the 21,600-second ceiling to that sum.  Omitting the population term is a
receipt refusal, not a reviewer-side arithmetic convention.  This preserves
the promised 2x headroom under the immutable 43,200-second service deadline.

Select slots use a paired construction before play. For pair ordinal
`j = 0..(select_count / 2)-1`, create two distinct deal slots with the same
`phase_position_role[j mod 12]`, `trump_rank[j mod 13]`, and
`trump_mode[j mod 5]`. Pair member 0 is `epoch-select`; pair member 1 is
`precision-select`. The distinct slot id yields a distinct attempted-deal hash
schedule, so the two halves contain independent deals while having byte-exact
matching phase/position/role, rank, and mode census rows. The frozen
D256/D512/D1024 counts produce exact 24/24, 32/32, and 64/64 halves, which the
builder must rederive or refuse. Only epoch-select may choose a common epoch.
Precision-select labels remain unopened until the common checkpoints and all
precision-select predictions seal.

Mechanics-hard deals are selected without outcomes in equal thirds across
multi-card action, wide-ballot, and late/high-point surfaces, with a
canonical state-hash remainder rule. They may improve representation coverage
but cannot determine an audit claim. Diverse-fit deals are also training only
and follow the source contract in Section 6.

Natural roots are balanced over:

```text
early / middle / late
    x lead / follow
    x attacker / defender
```

The population also balances all 13 trump ranks and the five trump modes
(four suits plus no-trump). No rank is fixed to 2. Whole deals remain in one
split and one bootstrap cluster.

State selection is outcome-blind. Each deal is assigned a required stratum
before play, and the canonical smallest state hash satisfying it is selected.
Eligibility requires at least two legal comparison actions. The population
builder must freeze attempted and accepted deal counts; it may not silently
replace a deal after labels are generated.

The candidate population is the complete production ballot plus one
hash-selected legal action outside that ballot when one exists. On a
diverse-fit root, the source policy's played action is also included if legal
and not already present. The legal-tail/source origins measure successor and
proposal support; neither origin is an inference feature.

Exactly one state per deal is intentional. It directly repairs V1's effective
sample failure and makes the tier totals equal the independent sample counts.
Up to one state per phase becomes eligible only in a later successor after a
one-state-per-deal V2 model and consumer both pass.

## 6. Data and teacher contract

V2 distinguishes three jobs that prior datasets sometimes blurred:

1. **State source:** which policy reached a complete-world position.
2. **Proposal source:** which legal actions are worth adding to the production
   ballot.
3. **Numeric labeler:** the one continuation policy `pi_c` defining
   `V^{pi_c}`.

The natural fit, select, and audit deals use fresh engine self-play from the
same frozen trajectory policy. Select and audit are always natural; diverse
and mechanics-hard deals are fit-only. D512's 64 diverse slots are 32 fresh
PT-Sol, 16 fresh PT-Luna, and 16 complete-provenance human deals. D1024 doubles
those counts. "Fresh" means a distinct complete deal cluster with zero
overlap with every prior Value, PT, BELIEF, and human evaluation population.
If a named source is unavailable, incomplete, or fails complete-world replay,
that tier is ineligible; slots are not silently reassigned.

Existing PT-Sol/Luna artifacts remain opened-DEV/OOD diagnostics and may not
fill fresh slots. All decisions from one original game remain one cluster.
Sol is the preferred action/state teacher because it was stronger; Luna adds
policy diversity. PT actions may enter the candidate ballot as legal
proposals, but PT prose, confidence, argmax, and mixed-policy final outcomes
are never scalar value truth. Existing PT-Luna0 is not Luna-vs-Luna self-play.

Fresh PT state-source collection is a separate score-free acquisition stage
with its own pre-execution capacity and budget receipt. The receipt freezes
source counts, wall and token caps, worker layout, progress reporting, failure
semantics, and provider headroom. Collection finishes and its complete deal
identities are sealed before the V2 population freezes; its time and tokens
are excluded from the scientific V2 service clock, and its outcomes remain
unavailable to tier choice and state selection.

Every diverse root is chosen by the same assigned-stratum/canonical-state-hash
rule as a natural root. The PT or human game's terminal outcome, narration,
confidence, and retrospective analysis are unavailable to selection and are
excluded from model inputs and numeric labels.

Human records supply representativeness and proposal coverage only when the
complete world is mechanically reconstructed and provenance permits training.
Human or PT state sources do not change the label definition: every candidate
successor is relabeled with the same frozen `pi_c` and seed schedule.

The design review may nominate production `mc-s0-report-lcb` or one stronger,
fully reproducible engine-only continuation as `pi_c`. A stronger candidate
must have a named policy/checkpoint/configuration and independently reopened
paired whole-round evidence whose one-sided deal-cluster lower bound against
production is strictly positive at frozen information and work. It must also
pass the exact-32 census for determinism, common-random-number pairing, and
economics. DEV point estimates, local decision tails, teacher prose, and
unmatched-work contrasts are ineligible evidence classes. Sol/Luna API calls
are not eligible numeric labelers. The choice is frozen before any V2 label or
prediction exists and cannot be made from V2 outcomes. If no stronger
candidate clears those requirements, production remains `pi_c`.

The population packet publishes, by split and source: independent deal count,
root count, candidate-afterstate count, continuation-row count, trump
rank/mode, phase, position, role, and overlap checks. Learning curves and
inference always cluster by original deal.

## 7. P0 precision early stop

P0 is exactly 96 natural fit deals, exactly eight per phase/position/role
cell, selected by the smallest canonical pre-label deal hashes. It generates
all eight continuation replicas before any model training.

One shared state-selection function and source hash implements the assigned-
stratum/smallest-canonical-state-hash rule for P0, remaining fit, select, and
audit populations. Split-specific selection code or parameters are forbidden.

For each direction, choose from the complete frozen candidate set with one
replica half, breaking every tie to the incumbent. On the other half, score
`chosen outcome - equal-weight candidate-mean outcome`, then reverse. This
tests whether independent replicas support a reproducible ordering without
requiring any candidate to beat the strong production incumbent. Also report
chosen-minus-incumbent utility separately. It does not enter label-
reproducibility gates 1--3; its combined point estimate is the worthwhile-
effect gate below, while its variance is diagnostic only. Cluster inference
by deal.

P0 advances only if:

1. both directional point estimates are positive;
2. the combined deal-bootstrap lower bound is strictly positive;
3. at least 5% of sibling pairs have the same nonzero advantage sign in both
   replica halves, and the two half-sample sibling-advantage vectors have a
   strictly positive deal-bootstrap correlation lower bound; and
4. the combined two-direction chosen-minus-incumbent point estimate is
   at least `+0.10` signed levels; and
5. transition, continuation, perspective, and symmetry checks pass.

Publish R=2/4/8 action agreement, return-mean error, intraclass correlation,
nonzero-advantage dose, and both directional utilities. If P0 statistical
gate 1, 2, or 3 fails, publish `STOP_NO_REPRODUCIBLE_VALUE_LABEL`; do not label
any non-P0 deal or train. If gate 4 fails, publish
`STOP_BELOW_WORTHWHILE_VALUE_FLOOR`; a reproducible but smaller signal is not
silently promoted into a full spend. A P0 gate-5 mechanics or integrity
failure instead routes to `REFUSE_MECHANICS_OR_CONTROL`. The unlabeled
remainder is 160 deals for D256, 416 for D512, or 928 for D1024.

P0 publishes the Bessel-corrected standard deviation of its incumbent-
relative cross-fit utility as a label-selector diagnostic only. It is not a
power calculation for the trained model's action-selection rule and cannot
route `STOP_UNDERPOWERED`. The matched model-selector power calculation occurs
on untouched precision-select deals in Section 9.

## 8. Structured absolute-value model

V2 trains one fixed structured model, not a width tournament:

- 16-dimensional shared rank/suit/card embeddings;
- 8-dimensional relative receiver/seat/team embeddings;
- a shared 32-wide card/zone encoder over 54 card codes and five receivers;
- permutation-aware receiver/team aggregation;
- a shared 32-wide public-history event encoder followed by a 32-wide GRU;
- a 32-wide non-card public-context encoder;
- a 64-wide fused trunk; and
- a 204-category terminal signed-level distribution head.

The hard ceiling is 50,000 trainable parameters. The implementation publishes
the exact parameter count before any capacity run.

Required representation fixtures cover partial tricks, trick boundaries,
every trump rank and no-trump, multi-card actions, root-team rotation,
identical-state byte stability, and rejection or absence of incumbent, ballot,
teacher, continuation-depth, and artifact metadata.

## 9. Training objective

The primary output and primary loss remain absolute terminal value. For one
outcome category `y` and predicted probabilities `p`:

```text
L_absolute = -log(p_y) / log(204)
```

V2 also uses one fixed auxiliary constraint on the expectation emitted by that
same absolute head:

```text
L_pair = squared error(
    E[V(candidate)] - E[V(incumbent)],
    mean_r[z(candidate,r) - z(incumbent,r)])
```

Let `sigma_pair_squared` be the population variance of the P0 eight-replica
mean candidate-minus-incumbent targets, computed over non-incumbent pairs and
frozen before training. Define:

```text
L_pair_normalized = L_pair / max(1.0, sigma_pair_squared)
L_total = L_absolute + L_pair_normalized
```

The two dimensionless terms are weighted 1:1. The auxiliary changes training
only; it does not change the MCTS-facing interface or create a ranking head.
No Smooth-L1, ranking-only, policy, Q, confidence, or abstention loss is
present.

Loss is averaged first within root across replicas and candidates, then across
deals. The primary ensemble trains four fixed seeds for at most 20 epochs with
patience 3 and one common epoch selected from epoch-select only. There is no
warm start, member-specific selection, retry, seed dropping, or audit-driven
extension.

The natural-versus-complete-world-shuffle claim has two independent, frozen
four-seed training blocks. Block 1 is the primary natural ensemble and its
seed-paired shuffle control. Block 2 uses four fresh initialization/data-order
seeds for a confirmatory natural ensemble and its seed-paired shuffle control;
block-2 models never contribute to primary value or action predictions. Each
block must independently satisfy both gate-5 deal-bootstrap lower bounds, and
at least 3/4 paired members in each block must have positive natural-minus-
shuffle mean differences for both metrics. This is training-seed replication,
not eight members presented as one ensemble. Every block and its full cost is
included in the capacity projection, and each four-member cohort follows the
same epoch-select-only common-epoch selection rule.

After the nested 25/50/100% curve completes, the three block-1 controls and
block-2 natural cohort use the outcome-blind fastest measured cohort width
from `{1, 2, 4}`.  Every cohort still fixes four members and the four cohorts
still expose exactly 16 independent model-training tasks; data, seeds,
selection, predictions, and evidence are never pooled.  Width one runs the
two stage controllers serially and seals each complete stage prefix.  Width
two or four runs the controls and block-2-natural controllers together, with
the controls stage using the remaining measured slots internally.  Block-2
complete-world shuffle starts only after all four cohorts complete.  A child
refusal terminates a concurrent sibling, while already sealed immutable epoch
shards remain resumable.  Capacity admission projects the exact topology of
the selected cohort-concurrency arm: width one serializes the three controls
and block-2 natural; width two serializes the controls in one branch beside
block-2 natural; width four runs all four cohorts concurrently.  The natural /
nested prefix remains serial, and block-2 complete-world shuffle starts only
after the selected-width wave seals.  Admission may neither invent unmeasured
overlap nor serialize concurrency that the selected arm already measured.

### Pre-audit recipe diagnosis

The audit is not the first time the training recipe is allowed to fail. Before
full training or audit opening, publish this ordered diagnostic ladder:

1. **Label ceiling:** Section 7 cross-fits independent continuation halves.
   Failure means the leaf comparison/continuation target is too noisy or
   incorrectly signed; it is not evidence about model data or architecture.
2. **Optimizer/wiring canary:** use the complete sibling-candidate sets of the
   16 smallest-hash P0 roots, one fixed model seed, and 500 optimizer steps
   with no early stopping. Let
   `L_empirical` be the exact empirical-distribution entropy plus zero paired
   residual for those eight-replica targets. Require all gradients and weights
   finite, `L_initial > L_empirical`, and
   `(L_initial - L_final) / (L_initial - L_empirical) >= 0.80`.
   Failure publishes `REFUSE_TRAINING_RECIPE` before full training.
3. **Nested data curve:** train the identical primary recipe and fixed seed on
   source/stratum-preserving canonical deal-hash prefixes containing 25%, 50%,
   and 100% of fit deals. Evaluate all three on epoch-select only. The
   25%/50% models cannot become ensemble members; the 100% model is member 0
   only when its checkpoints byte-match the primary schedule. Publish absolute
   RPS/error, paired-error, train-select gap, and fit/select slopes versus log
   independent-deal count.
4. **Primary stability:** publish all four members' per-epoch fit and epoch-
   select curves, gradient norms, parameter/update norms, prediction entropy,
   paired target error, and common-epoch dispersion. No member may be dropped.
5. **Pre-audit learning admission:** after the common checkpoints and target-
   free precision-select predictions seal, open precision-select labels once.
   The ensemble must have strictly positive one-sided deal-bootstrap lower
   bounds for RPS improvement over the natural-fit prior and paired-advantage
   error improvement over zero, with at least 3/4 members positive on mean RPS
   improvement. Failure publishes `SELECT_NONE_PREAUDIT_LEARNING` and leaves
   every audit label unopened.
6. **Matched model-selector power:** on each precision-select deal, let `u_d`
   be the equal-weight eight-replica outcome of the action selected by the
   sealed primary ensemble minus the equal-weight outcome of the production
   incumbent, using the identical tie-to-incumbent rule as audit. Let
   `s_model` be the Bessel-corrected standard deviation across those deal-level
   utilities. For one-sided alpha `0.05`, power `0.80`, and minimum worthwhile
   effect `delta = +0.10`, compute:

   ```text
   n_required = ceil(((1.644854 + 0.841621) * s_model / delta)^2)
   ```

   If `n_required` exceeds the frozen audit-deal count, publish
   `STOP_UNDERPOWERED` before audit opening. This calculation now matches the
   model-selection rule, incumbent baseline, continuation averaging, and
   deal-level statistic used by production-action usefulness gate 1. Final
   inference still uses the preregistered deal bootstrap.

Interpretation is preregistered rather than reconstructed after audit:

| observed before audit | diagnosis |
|---|---|
| label ceiling fails | continuation/leaf-comparison recipe is invalid or too noisy |
| optimizer canary fails | implementation, optimizer, loss scaling, or model expressivity is broken |
| fit improves, select degrades; larger prefixes reduce the gap | data-limited overfitting |
| fit remains poor after canary passes and the data curve is flat | representation/capacity or irreducible-target problem |
| members diverge materially under identical data | optimization/hyperparameter instability |
| fit and select proper scores improve but action utility does not | valid value learning without evidence of beating the production action |

The last three diagnoses are evidence, not perfectly identifiable causes. A
flat data curve cannot by itself distinguish architecture from a poorly chosen
optimizer. Any successor that changes width, optimizer, or data mixture is a
train/select-only development design and may not reopen V2 audit outcomes.

## 10. Target-free audit and gates

Predictions for every natural audit deal in the chosen tier and every control
seal and independently reopen before audit outcomes open once.

The audit has two layers so production strength is not confused with training
correctness.

**Absolute-value learning gates:**

1. Ranked-probability-score improvement over a smoothed train-only
   phase/role/points prior has a positive deal-bootstrap lower bound.
2. Expected signed-level absolute-error improvement over that prior has a
   positive lower bound.
3. Paired-advantage absolute-error improvement over exact zero has a positive
   lower bound.
4. At least 3/4 members have positive mean ranked-probability-score
   improvement.
5. In each of the two frozen training-seed blocks, natural-minus-complete-
   world-shuffle lower bounds are strictly positive for ranked probability
   score and paired-advantage error, and at least 3/4 seed-paired member means
   are positive for both metrics.
6. Every negative control fails on demand.

**Production-action usefulness gates:**

1. Ensemble action utility over retaining the production action has a
   deal-bootstrap lower bound of at least `+0.10` signed levels.
2. At least 3/4 members have positive mean action utility.
3. Non-incumbent selection dose is at least 5%.
4. Natural-minus-complete-world-shuffle action-utility lower bound is strictly
   positive.

Passing the learning layer but not the usefulness layer proves only that the
recipe predicts held-out values better than non-action baselines. It does not
claim better decisions, gameplay strength, or a useful search consumer.

For ordered outcome categories `1..204`, ranked probability score is:

```text
RPS(p,y) = (1 / 203) * sum_{k=1}^{203}
           (sum_{j<=k} p_j - 1[y<=k])^2
```

The prior is computed from **natural fit rows only** in the frozen
`early/middle/late x attacker/defender x attacker-points-[0,40)/[40,80)/[80,+inf)`
bucket. Each of 204 categories receives a Jeffreys `0.5` pseudocount. An empty
bucket falls back to the identically smoothed global natural-fit prior. Scores
average first across actions/replicas within a root and then equally across
deals.

For every paired improvement, positive means `baseline loss - model loss` or
`model utility - baseline utility`. Use 10,000 deterministic deal-bootstrap
replicates whose seed is the first unsigned 64 bits of SHA-256 over the frozen
audit-population SHA plus metric name. The one-sided lower bound is the fifth
percentile under the frozen integer-nearest-rank rule.

CVaR-10, the worst `ceil(0.10 * audit_deal_count)` selected-action deal
utilities, is a mandatory diagnostic with its bootstrap interval, not an
underpowered gate.

The smallest worthwhile mechanism effect is `+0.10` signed levels per audited
decision. P0 must first show an independently cross-fit label-selector ceiling
at least that large. Precision-select then determines whether the frozen audit
count can resolve the same floor under the trained model's actual selection
rule. If not, V2 publishes `STOP_UNDERPOWERED` before audit opening and does
not enlarge the population in place.

Required positive/integrity controls that must pass are identical-successor
exact-zero advantage, root-team mirror, hidden-metadata absence, and
transition/legality/hash/fold mutations that refuse before prediction.

Learning controls are within-root action/successor association permutation,
label permutation within frozen outcome-blind collection/noise strata
(`source x early/middle/late x lead/follow`), and complete-world reassignment
by the canonical FIT pair ID only. Reassignment pairs roots from the two
adjacent slots using distinct deal/root donors; it preserves each recipient's
public, history, perspective, labels, successor and candidate identity, and
replaces only world tensors. Recipient candidate 0 maps to donor candidate 0;
recipient candidate `j > 0` maps to donor `1 + ((j-1) mod (n_donor-1))`.
Each candidate's eight-replica family moves together, and donor root plus
candidate are bound in evidence. At least 90% of FIT roots must have a pair,
and changed world tensors must cover at least 90% of the complete FIT
population, not merely 90% of the pairable subset; singleton or undercovered
populations refuse. D256's full 128-natural plus 32-mechanics FIT population
must reopen as exactly 64 natural pairs plus 16 mechanics pairs before any
training stage begins. Before pair lookup, every reopened row must bind its
source, split, rank, mode and natural phase/position/role cell to the canonical
slot ledger; the material-input boundary additionally binds each mechanics
slot to its named mechanics surface. Label permutation moves one whole
candidate-by-eight-replica target family from a distinct donor and never
crosses its collection/noise stratum; it deliberately does not condition on
trump, role, points, or ballot width because those exact buckets can make the
frozen numeric-dose floor mathematically unattainable even when every donor
binding is deranged. The association- and label-permuted cohorts
must each fail at least one of absolute-value learning gates 1--4 when scored
as a candidate cohort. World reassignment must be rejected by both gate-5
natural-minus-shuffle lower bounds. Gate 6 is the nonrecursive conjunction of
those three demanded failures. Failing only a production-action usefulness
gate is insufficient. Failure of the association- or label-permutation
component forces `REFUSE_MECHANICS_OR_CONTROL`, even when the natural model
would otherwise route to `PASS_ABSOLUTE_VALUE_LEARNING_ONLY`; failure of the
world-reassignment component instead routes to `SELECT_NONE_NO_WORLD_SIGNAL`.
Association permutation must change at least 90% of bindings and successor
tensors. Label permutation must change at least 90% of donor bindings and 40%
of numeric targets. World reassignment must change at least 90% of all FIT world
tensors. Association and label controls use the primary four seeds. Complete-
world reassignment uses both disjoint four-seed blocks and the paired natural block
defined in Section 8. All cohorts use the common-epoch rule and target-free
audit order. Any incomplete or deadline-truncated member in either comparison
block routes to `REFUSE_RESOURCE_INCOMPLETE` before audit opening; a forensic
checkpoint cannot satisfy gate 5.

History chronology shuffle is diagnostic only. A complete Markov state may
legitimately make history redundant, so its failure cannot close an otherwise
valid absolute leaf value.

## 11. Human-readable error atlas

Publish a 12-example descriptive atlas from P0/select only, never from audit,
report, or provider rows:

- three confident harmful action changes;
- three missed reproducibly positive actions;
- three largest absolute calibration failures; and
- three seed-unstable or partial-trick/boundary failures.

Examples are selected deterministically by frozen severity and then state
hash. Each shows public/trick context, privileged world clearly marked, legal
actions, production action, eight continuation outcomes, predicted
distribution/expectation, member spread, and the first continuation
divergence. Category denominators accompany examples so anecdotes cannot be
read as prevalence.

PT-Sol/Luna may receive a target-free OOD forecast appendix. It is not an
error atlas or efficacy claim.

## 12. Pre-implementation compute/economics gate

Design review comes before learner implementation. The first compute work is
one score-free, out-of-namespace census using the existing engine and V1 state
extractor. It persists no terminal outcome or advantage.

Use exactly 32 accepted independent preflight deals from a domain-separated
namespace. The first exact post-implementation census at source `ba17ab1e`
correctly refused before arm or DAG measurement: only 14 of the frozen 96
attempts supplied an eligible fixture. That score-free result falsified the
original 96-attempt sizing assumption; it did not open a label or outcome.

The repaired preflight keeps the 32-fixture target and the same deterministic
identity derivation; the former singleton first-96 schedule is superseded by
the pair-reservation prefix below.
Before general filling it predeclares and reserves 16 natural-fit roots as
eight complete adjacent slot pairs. Each reserved batch schedules only the
still-missing slots, and the general schedule excludes those already-reserved
slots, so accepted partners do not consume later attempts. It
then retains at most 17 natural-fit
roots, so at least 16 of 17 are pairable, while retaining exactly 32 unique
slots with epoch-select, precision-select, and audit coverage. Neutralizing
the reservation or failing to complete it is a capacity refusal. The runner
raises only the hard attempt ceiling to 384, and runs
the CPU-bound attempts in fixed index-ordered batches of at most 16 processes.
Each batch is also bounded by the number of fixtures still needed, so it cannot
produce an eligible surplus requiring post-hoc selection. The measured
14/96 supply would yield 56 fixtures over 384 attempts at the same rate; 32
remain the fixed retained population. Fewer than 32 accepted deals by the new
ceiling is still a score-free capacity refusal. Measure:

- stratum acceptance and deal attempts needed per accepted state;
- production-ballot and legal-tail candidate counts;
- successor construction wall, CPU, memory, and bytes;
- continuation throughput with outcomes discarded at 1/2/4/8/12/16/32 workers;
- R=2/4/8 projected label CPU, wall, and storage;
- full D256/D512/D1024 projected label cost, including each nominated
  continuation policy; and
- whether label shards can seal and reopen independently.

The complete arm census is the cheap gate: every preregistered state/successor,
continuation, member, inference-batch, and reconstruction arm must be measured
and byte-validated before the expensive 19-stage full-DAG run begins. A
missing arm or failed byte identity is a conservative pre-DAG refusal; it is
not repaired by extrapolating from a neighboring width. The census uses exact
nanosecond wall and process/cgroup CPU counters from each operation, and the
immediate-next-arm rule is evaluated on those exact counters.

Implementation proceeds only if at least D256's projected label stage is at
most three hours wall and 48 aggregate CPU-hours on the 16-core host, stays
below 85% of a 30-GiB no-swap memory envelope, and has at least 25% storage
headroom. The receipt reports every tier and teacher candidate without
choosing from outcomes. This census clears label economics only; it does not
authorize or predict the composed scientific DAG. A failure changes or closes
the design; it does not move a cap to fit the projection.

## 13. Post-implementation score-free capacity gate

After implementation, but before a scientific freeze, measure on the isolated
16-logical-CPU Perf host:

The capacity, freeze-input, freeze, scientific, spawned-controller, terminal,
and reconstruction processes all require `SHENGJI_FAST=1` and
`SHENGJI_REQUIRE_VOIDS=1`.  The exact in-tree `_fast` native-extension path and
SHA-256 plus both environment values are part of the runtime profile.  The
freeze permits that one hash-bound ignored native binary and refuses every
other ignored loadable file; a missing, foreign, symlinked, or changed native
binary closes before capacity or admission.  This prevents the measured path
from silently falling back to the materially slower pure-Python engine.
Every scientific controller binds and rechecks that runtime in its own child;
every nested capacity, label, and reconstruction process pool uses the same
identity as an explicit worker-initializer argument, seeds that verified
identity for any worker descendants, and the parent rechecks before accepting
a child result.  The binding must not rely only on ambient environment
inheritance because a multiprocessing forkserver may predate controller
admission.  On the Linux execution host, every profile also requires the
mapped shared-library device/inode from `/proc/self/maps` to equal the exact
path whose bytes are hashed, closing the import-then-atomic-replace window.
Binding only the outer CLI or only rehashing the pathname is insufficient.

| stage | measured variants |
|---|---|
| state/successor construction | 1, 2, 4, 8, 16, 32 workers |
| continuation mechanics | 1, 2, 4, 8, 12, 16, 32 workers |
| member concurrency | 1, 2, 4 members |
| cohort concurrency | 1, 2, 4 simultaneous cohorts, each with four fixed members |
| Torch threads per member | 1 (pinned; no width-selection arm) |
| inference batch | 32, 64, 128, 256 |
| reconstruction | 1, 4, 8, 16, 32-worker scoring/hash verification |

The member- and cohort-concurrency arms each train every fixed model on one
identical 128-example score-free batch.  The batch is assembled from complete
candidate-by-eight-replica roots drawn across the 32 retained preflight
materials in the production epoch order; roots are never split.  Every
retained material is bound into the capacity-label identity, so changing an
unselected material still changes the measured workload.  Deterministic
pseudo-targets exercise the real collation, loss, optimizer, and state-digest
path but open no continuation or outcome.  The member arm always trains four
models and the cohort arm always trains four complete four-member cohorts;
only executor concurrency changes between variants.  Each cohort constructs
its models and optimizers inside its outer cohort task, matching the scientific
stage altitude; serially constructing all 16 models before the outer executor
is forbidden.  A retained population
that cannot form the exact complete-root 128-example batch refuses before
measurement rather than falling back to a singleton or partial root.

Inference-batch arms must seal byte-identical **production prediction
values**: the ordered six-decimal canonical probabilities and their exact PPB
encoding. Raw pre-softmax float32 logits are not an artifact identity. They
may differ by a few ulps across otherwise equivalent batch-shaped matrix
kernels, which is the numerical freedom the already-frozen inference
canonicalization exists to resolve. A materially different canonical
probability or PPB row still refuses the arm comparison.

The fastest memory-eligible byte-identical cohort arm is the executable
production layout.  Widths 1, 2, and 4 all perform the same four complete
cohorts, and the success receipt publishes every exact arm wall plus the
selected width.  The scientific supervisor must consume that selected width;
it may not insist on four-way concurrency when a narrower arm completes the
same fixed workload faster.

The cohort selector runs one score-free first pass at widths `1,2,4`, then a
second pass in reverse order `4,2,1`.  Every pass executes the same complete
16-model workload and is subject to the command deadline, memory, swap,
runtime, and byte-identity checks.  For each width, the receipt-bearing arm
aggregates both passes: elapsed wall, CPU, and disk work are summed; resource
peaks are maximized; and samples are concatenated.  Selection therefore ranks
the same fixed two-pass workload for every width, and the receipt's command
wall and peak-task reconstruction include all six executions.  This fixed
balanced order prevents first-import/page-cache startup from deciding the
production topology; it is not an outcome-dependent repeat or retry.

The composed projection uses the same selected-width topology as production.
Block-1 natural and nested 25/50/100 remain serial.  At width one, the three
controls and block-2 natural follow serially.  At width two, the serial controls
branch and block-2 natural run concurrently.  At width four, the three controls
and block-2 natural are four independent branches.  Block-2 complete-world
shuffle starts after every selected-width branch seals.  The selected cohort
arm is the empirical authorization for that topology; no unmeasured overlap or
arithmetic-only parallelism may be introduced.

The capacity command is bounded to two hours, 30 GiB, zero swap, and 4,096
tasks. Freeze the fastest byte-identical configuration below 85% memory and
choose the largest eligible D256/D512/D1024 tier by the outcome-blind rule in
Section 5.
Publish exact model parameters, candidate distribution, per-epoch wall,
composed peak memory, CPU utilization, and projected P0, label, train, audit,
and reconstruction walls. The complete composed projection includes the
optimizer canary, nested 25/50/100% data curve, natural cohort, and every
learning-control cohort. Reconstruction must reopen the immutable
continuations and repeat audit scoring/control arithmetic exactly once,
matching the scientific immediate verifier without rebuilding labels,
continuations, or models. Later routine verification is receipt-only unless
an explicit rescore is requested. The projection must be at most six hours,
providing 2x measured headroom under the immutable 12-hour scientific service
cap. GPU support is
out of scope. The composed peak artifact projection must retain at least 25%
free-disk headroom after temporary and final artifacts coexist.

Representative label buckets may contain fewer deals than the selected worker
width.  Their retained-population wall is therefore projected from exact
measured process CPU work divided by the separately measured saturated
continuation-mechanics utilization, with the representative wall retained as
a fixed-cost/largest-task floor.  The projection may not multiply an
underfilled representative makespan by the deal-count ratio.  If the composed
projection refuses a cap, the immutable failure receipt retains the complete
projected wall/CPU/unit grids, exact measured wall/CPU nanoseconds, DAG edges,
resource peaks, named violated caps, and the complete already-passed arm-census
assessments; refusal must not discard the result that explains why the
capacity run failed.

Independent deals, candidate successors, continuation replicas, control
cohorts, inference batches, and reconstruction shards are the permitted
parallel units. The capacity receipt publishes aggregate busy-core seconds,
mean/p50/p95 CPU utilization, scaling efficiency, queue depth, and wall share
for every stage. A CPU-bound stage consuming at least 5% of projected wall
must either sustain at least 85% aggregate utilization on the 16-core host or
show that the next measured worker arm is byte-identical but slower. Otherwise
the design repairs or closes before freeze. The chosen worker and batch
layouts are the fastest byte-identical arms, not automatically the largest
arms; Torch training width is fixed at the pinned value above and is not
selected by this gate.

Wall share is projected from measured stage work units; it is never fabricated
as a convenient fraction of the composed wall. The representative full-DAG
all-core gate is derived from the exact per-stage process/cgroup CPU and wall
nanoseconds, then projected to the retained population. It is not a second
measurement or an assumed 16-core utilization value. The capacity run starts
from a fresh repaired-head virtual environment whose resolved prefixes and
``pyvenv.cfg`` identity are bound into the runtime profile. No c17 artifacts,
old virtual environment, or prior capacity namespace may be reused.

This amendment changes executable contracts, so the capacity receipt, arm,
projection, measurement-scope, failure, execution-freeze, population input,
early-stage input, population-controller config, and terminal-input schemas are
version-bumped. Legacy wire bytes refuse rather than inheriting the widened
worker domain or repaired runtime identity implicitly.

The first repaired-head capacity attempt refused honestly before freeze: its
unconditional serial projection was 24,283 seconds against the fixed
21,600-second cap.  Replaying the same sealed stage walls through the exact
selected-width topologies gives 24,283 seconds at width one, 22,965 at width
two, and 16,941 at width four.  The legacy failure receipt did not retain the
selected cohort arm, so it cannot establish which counterfactual applies.
These numbers diagnose a projection/execution mismatch; they are not new
capacity evidence.  The cap remains fixed, the failed namespace is not
retried, and this accounting repair alone does not predict a passing fresh
census: widths one and two still refuse, while width four fits.

This correction bumps the capacity receipt, composed/rejected projection,
failure, and measurement-scope schemas.  The arm wire schema and production
stage contract are unchanged.  No valid earlier capacity receipt exists to
migrate.  A late full-DAG refusal retains the complete already-passed arm
census and the selected cohort width so the next optimization is based on
measured evidence rather than another blind full census.

The resource mapping is closed: continuation-label stages use the
continuation-mechanics arm, cohort training/optimizer stages use the
member-concurrency arm, the four independent cohorts use the distinct selected
cohort-concurrency arm with four fixed members per cohort, precision inference
uses the inference-batch arm, and
reconstruction uses the reconstruction arm. P0, nested-25/50/100,
precision-select evaluation, and audit have no matching selectable arm in V2;
the receipt may not borrow evidence from another workload. A stage is material
when its projected wall is at least 5% of the sum of all projected stage walls,
evaluated by exact integer cross-multiplication. Any material unmapped stage
below 85% aggregate 16-core utilization refuses. For a material CPU-bound
mapped stage below 85%, the only permitted saturation witness is the
byte-identical, memory-eligible **immediate next** member of that exact arm
grid taking strictly longer in exact nanoseconds. A later nonadjacent arm is
irrelevant, and a low-utilization fastest 32-worker arm refuses because no
next arm exists.

### V2 capacity amendment: deterministic intra-model Torch width

The post-implementation capacity repair removes cross-width Torch training
selection. CPU-threaded reductions can alter post-training model bytes across
hosts, so comparing Torch widths as byte-identical arms is not an admissible
reproducibility claim. Production has exactly one Torch training configuration:
intra-model Torch threads are pinned to 1. This is a runtime invariant, not a
selectable capacity arm, so a `(2, 4)` member/thread layout cannot enter
production. The selected fixed configuration therefore remains reproducible
while measured member concurrency still represents
independent parallel work across model members; worker, batch, and
reconstruction arms remain measured as specified above.

The representative full-DAG utilization gate remains load-bearing. If training
is a material share of projected wall and is underutilized, the receipt refuses
unless the permitted next worker arm is slower but byte-identical; pinning
Torch width does not waive that refusal condition.

The capacity wire schema is bumped because the former receipt and arm
population are incompatible with this layout. No migration is provided: the
prior capacity run refused before publishing a receipt, so there is no
previous production artifact to migrate.

### Census-11 projection-only re-adjudication

The exact `8ff9c79c` census completed every arm and every one of the 19
representative-DAG stages, then refused only because its width-two composed
D256 wall was 23,065 seconds against the unchanged 21,600-second and
two-for-one limits.  The immutable refusal is file SHA-256
`06019851ec4a2aecdc8541d623a02e9d8355c3d68d69c9fe29572a3d0d5be14d`
and internal receipt SHA-256
`3a059e3de3c506117bac71611acf20ec3e2fbfdeb3c64e1baadd8d145db5a8b7`.
It retains the exact measured/projected wall, CPU, unit, resource, and DAG
grids.  Repeating label generation, training controls, audit, or
reconstruction would add no information and is forbidden for this recovery.

The only unresolved quantity is sustained cohort topology.  The original
selector trained each cohort for one epoch over one 128-example batch; fixed
process/import/checkpoint overhead dominated the roughly 16-second arm and
selected width two.  Recovery therefore runs one fresh score-free 32-deal
preflight and exactly two production-topology cohort arms, widths two and
four.  Each arm trains the same natural block-two cohort and the same three
block-one controls, four fixed members per cohort, for up to eight common
epochs under the unchanged patience rule.  Width two uses the production
two-controller layout with the three controls serial in one child and natural
in the other; width four runs the same two children with three controls
concurrent in the controls child.  One warm pass runs `2,4`, then one measured
pass runs `4,2`; both passes are charged and their exact wall/CPU/resource
samples are combined.  Outputs must be byte-identical and all four cohorts
must reopen their four selected checkpoints.  No outcome, scientific label,
or audit row is opened.

The fastest memory-eligible sustained arm is selected by exact combined wall.
If width four is selected, it must either reach the unchanged 85% material
CPU-utilization gate or refuse; there is no unmeasured wider arm.  If width two
remains fastest, its immediate-next width-four witness must be strictly slower
and the recomposed projection must still pass.  Recovery replaces only the
cohort worker count and corresponding frozen DAG edges.  Every retained stage
wall/CPU/unit value must be byte-for-byte equal to Census-11, while peak memory
is the maximum of the old DAG and new arm peaks and free disk is the minimum of
the old and new observations.  A fresh preflight wall supplies population
construction economics; it may not reuse the unsealed progress log.

The output is a typed composite capacity receipt binding the entire old
failure bytes, current source/runtime, fresh preflight, both sustained arms,
the inherited six-category passed assessments, the recomposed tiers, and the
all-false authority map.  Downstream freeze/training/terminal adapters accept
that composite through one shared capacity-evidence reopener and consume only
its authenticated selected variants.  A composite may authorize a freeze only
if D256 passes every unchanged wall, two-for-one, label, memory, disk,
all-core, byte-identity, and exact-source gate.  A refusal spends only the new
re-adjudication namespace; it never changes or retries Census-11.  The
re-adjudication command is bounded to one hour, 30 GiB, zero swap, and 4,096
tasks and emits the standard progress/resource fields.

## 14. Progress and recovery

Every expensive stage emits at least every 60 seconds or 1%:

- stage/substage and completed/total deals, states, actions, and replicas;
- active workers/threads and CPU utilization;
- elapsed wall, rolling ETA, and deadline headroom;
- current/peak cgroup memory; and
- immutable shard/checkpoint count.

Every scientific controller runs in its own process group under the one
admission-relative 12-hour monotonic deadline.  Stage-local limits are capped
by that original absolute deadline rather than renewed on resume or stage
entry.  At expiry the supervisor terminates the controller process group
before selecting `REFUSE_RESOURCE_INCOMPLETE`; no controller, nested worker,
audit read, or artifact publication may continue behind the terminal route.

Population and split seal before labels. Each completed deal-label shard seals
independently. Resume may reopen only verified shards under the same admission;
it cannot regenerate, replace, or select them. Training checkpoints every
common epoch. Deadline truncation may preserve the best complete common epoch,
but audit cannot open unless every required upstream artifact is complete.

The audit attempt is durably published and its parent directory fsynced before
the first audit-label byte is read. One audit opening and one immediate
independent reconstruction are allowed.
Reconstruction reproduces the decision without retraining or repeating engine
continuations whose exact immutable rows already reopen.

A reboot never authorizes scientific resume because the persisted monotonic
clock is no longer comparable.  A dedicated closeout-only command may reopen
the frozen identity, admission tombstone, completed event prefix, and verified
shards to seal a receipt-only `REFUSE_RESOURCE_INCOMPLETE` record.  That path
records both boot identities and the honest audit-open count; it cannot invoke
controllers, create shards, open new audit data, score, train, or reconstruct.
The same receipt-only closeout is used after a deadline-killed controller so a
spent admission is durable without pretending that incomplete work completed.

## 15. Terminal routes

- `REFUSE_MECHANICS_OR_CONTROL`
- `REFUSE_RESOURCE_INCOMPLETE`
- `REFUSE_TRAINING_RECIPE`
- `STOP_NO_REPRODUCIBLE_VALUE_LABEL`
- `STOP_BELOW_WORTHWHILE_VALUE_FLOOR`
- `STOP_UNDERPOWERED`
- `SELECT_NONE_PREAUDIT_LEARNING`
- `SELECT_NONE_NO_ABSOLUTE_VALUE`
- `SELECT_NONE_NO_ACTION_SENSITIVITY`
- `SELECT_NONE_NO_WORLD_SIGNAL`
- `PASS_ABSOLUTE_VALUE_LEARNING_ONLY`
- `PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN`

`PASS_ABSOLUTE_VALUE_LEARNING_ONLY` means every absolute-value learning gate
passed but at least one production-action usefulness gate failed. It may
justify a separately reviewed data-scale, recipe, or consumer design; it is
not evidence of a better action selector. The stronger PASS means both layers
passed. Either PASS authorizes design only and grants no PUCT, rollout,
BELIEF, gameplay, strength, merge, promotion, or deployment authority.

`REFUSE_RESOURCE_INCOMPLETE` preserves every verified population, label shard,
and complete common-epoch checkpoint and records the exact incomplete stage.
It forbids any new audit opening or audit work after the route is selected and
records whether the one-shot marker had already opened before an interruption.
It grants no retry under the spent admission.

Terminal precedence is frozen and first-match-wins:

1. unexpectedly missing/unsealed evidence required for the currently reached
   stage, or an exceeded resource/deadline cap ->
   `REFUSE_RESOURCE_INCOMPLETE`; intentionally absent downstream artifacts
   after an earlier valid stop do not satisfy this predicate;
2. any mechanics/integrity failure available at the currently reached stage
   -> `REFUSE_MECHANICS_OR_CONTROL`;
3. failed P0 statistical gate 1, 2, or 3 ->
   `STOP_NO_REPRODUCIBLE_VALUE_LABEL`;
4. P0 gate 4 below the minimum worthwhile `+0.10` point estimate ->
   `STOP_BELOW_WORTHWHILE_VALUE_FLOOR`;
5. failed optimizer/wiring canary -> `REFUSE_TRAINING_RECIPE`;
6. failed precision-select learning admission ->
   `SELECT_NONE_PREAUDIT_LEARNING`;
7. precision-select `n_required` above the frozen audit count ->
   `STOP_UNDERPOWERED`;
8. after the complete audit opens, the association- or label-permutation
   component of derived learning-control gate 6 fails ->
   `REFUSE_MECHANICS_OR_CONTROL`;
9. audit learning gates 1, 2, or 4 fail ->
   `SELECT_NONE_NO_ABSOLUTE_VALUE`;
10. gates 1, 2, and 4 pass but paired-advantage gate 3 fails ->
   `SELECT_NONE_NO_ACTION_SENSITIVITY`;
11. gates 1--4 pass but either seed block's natural-minus-world-shuffle gate-5
    lower bound or paired-member stability requirement fails (and therefore
    the world-shuffle component of gate 6 fails) ->
    `SELECT_NONE_NO_WORLD_SIGNAL`;
12. all absolute-value gates pass and any production-action usefulness gate
    fails -> `PASS_ABSOLUTE_VALUE_LEARNING_ONLY`;
13. both complete gate layers pass ->
    `PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN`.

Steps 8--13 are evaluated only after a complete single audit opening. Earlier
stops leave audit labels unopened. A later reason may never replace an earlier
route after outcomes are visible.

## 16. Conditional successors

If either learning PASS occurs, the next step may be a separately reviewed
one-trick consumer:

```text
candidate action
  -> engine continues until one additional trick completes
  -> V_theta(leaf)
```

It compares literal full-continuation MC, one-trick-plus-V, and identical
one-trick paths with permuted leaf values at equal wall. Immediate depth-zero
V is diagnostic only. Do not test two depths at once.

Only a positive consumer mechanism may justify increasing states per deal or
exceeding D1024. That successor freezes replica count from V2's R=2/4/8 curve
and only then considers up to one state per phase per deal.

## 17. Review path and non-goals

Use two review moments only:

1. this estimand/data/economics design before implementation; and
2. one consolidated source + population + capacity + rehearsal + immutable
   freeze review before scientific execution.

Do not build in V2:

- PUCT/MCTS integration or search-visit policy targets;
- one- or multi-trick rollout consumers;
- policy, Q, ranking-only, confidence, or abstention heads;
- BELIEF or compatible-world aggregation;
- PT imitation or Luna-vs-Luna outcome labels; bounded fresh PT state-source
  collection is allowed only to fill the exact diverse-fit slots in Section 6;
- human value labels without complete-world provenance;
- exhaustive legal-action search expansion;
- GPU support or a model-width tournament;
- any V1 audit/report/provider reopening; or
- gameplay, strength, promotion, or deployment authority.
