# BELIEF-to-search end-to-end design

Status: research design only. This document grants no data opening, training,
compute launch, gameplay registration, strength claim, merge, promotion, or
deployment authority.

This design extends the research ladder in `RL_PLAN.md`. It does not replace
the BELIEF R4 protocol, the PT protocols, or the production-policy contract in
`AI_POLICIES.md`.

## Decision

The target architecture is:

```text
actor-visible history
        |
        v
facts + calibrated belief over hidden allocations
        |
        v
correlated, physically legal complete-world samples
        |
        v
engine-owned legal expansion and transitions
        |
        +---- policy/proposal score orders branches       [optional learner]
        +---- Q score ranks actions inside sampled worlds [optional learner]
        +---- value score truncates selected rollouts      [optional learner]
        +---- uncertainty allocates more search            [optional learner]
        |
        v
search aggregates outcomes across actions and belief worlds
        |
        v
final engine-legal action
```

This is a modular destination, not one model or one run. The first consumer
contains no learned policy, Q, value, or allocation head: BELIEF changes only
the distribution of complete worlds seen by the existing production search.
Each later experiment introduces at most one additional learned function.
Search remains final action authority through the first confirmed strength
campaign.

The minimum path is deliberately shorter than the full diagram:

```text
R4 belief verdict -> legal-world sampler -> equal-work search mechanism -> whole games
```

The teacher/Q path is independent until both BELIEF and the teacher have their
own valid evidence. Current MC search already performs planning by expanding
legal actions and simulating continuations; Q or value learning is therefore
an optional way to prioritize branches or stop rollouts earlier, not a
prerequisite for planning. The privileged teacher is an offline label source,
never a live dependency. This design does not propose training belief, policy,
Q, value, and allocation end to end in one run.

## Why this is materially different from earlier learning

| Prior evidence | Lesson carried into this design |
|---|---|
| RLCB is the only confirmed deployed strength gain. | Preserve engine search and conservative aggregation as the spine. |
| V8 improved held-out teacher-choice agreement from roughly 43% to 62.5% without proving strength. | Imitating argmax actions is not the target; measure counterfactual action value and online utility. |
| V9 warm/scratch did not create an expert-iteration flywheel. | Do not assume another training turn improves its own teacher. Teacher quality is a separate gate. |
| V11Pair beat SmartBot but its corrected direct policy was `-0.141 +/- 0.070` versus live. | Relative pairwise scores may propose or rank; they are not a universal leaf value or final policy. |
| V13abs improved offline error while failing to improve online play. | Bind ballot, ply/surface, continuation, perspective, and deployment use to the training estimand. |
| Direct-Q had a positive gameplay tail but failed seed/held-out learning gates. | Q remains promising, but requires stable multi-seed learning before search integration. |
| T4's uninformed widening arm was positive but used more worlds and searches than champion. | Candidate diversity and compute must be separated with work-matched controls. |
| S4, S6, pair-aware, and other local mechanisms did not transport to a whole-game winner. | Measure natural decision dose and fresh whole-game utility; local plausibility is insufficient. |
| PT-Full and C0 showed that a true-world collapse can lose to a public ensemble. | Preserve uncertainty across compatible worlds; never substitute one MAP or literal true world for a public posterior. |
| PT-Sol0 showed large positive open-DEV mechanism contrasts over A, B, and C0-S. | A flexible planner with engine rollouts is a more promising teacher than fixed privileged consumers, but it still needs fresh confirmation before a strength claim. |
| BELIEF R4 is the first clean held-out posterior test and is not yet terminal. | A working learned belief is a hypothesis, not an input assumption. R4 decides whether the first consumer is justified. |

The two new opportunities are therefore conditional:

1. BELIEF may provide a calibrated behavioral posterior rather than only the
   hard deductions and generic allocation preferences in the current sampler.
2. A reviewed reasoning-and-rollout teacher may provide better counterfactual
   supervision than the fixed policies used by earlier students.

Neither opportunity is enough alone. Better belief with a poor consumer can
lose, and a strong privileged teacher can leak or fail to transfer into a
public policy.

## Confidence boundaries

High-confidence architectural choices are the separations, not the unmeasured
model gains:

- legal engine search remains the decision spine and final guard;
- belief is tested first by changing only the world distribution;
- privileged reasoning produces offline counterfactual evidence, never a live
  clairvoyant feature;
- a Q/value learner receives a policy-, ballot-, world-, and horizon-bound
  target rather than an unqualified scalar; and
- every later consumer must beat literal search and a same-work null before it
  composes with another learned component.

The empirical claims remain conditional. R4 has not yet established that the
current belief recipe beats REF-C; PT-Sol0 has not yet established a fresh
whole-game teacher advantage; no current Q head has passed both stable
learning and online-use gates; and no evidence says all three pieces improve
when composed. A negative result at any rung stops that branch without
invalidating the modular architecture or forcing the other branch to wait.

## Information and authority contracts

### Runtime information

The live decision path may read only:

- public game, declaration, trick, score, and accepted-play history;
- sound deductions derived from that history;
- the acting seat's private hand; and
- the banker's own burial only when the acting banker legally knows it.

True other hands, a non-banker-visible burial, simulator seeds, target paths,
and teacher-private reasoning never enter runtime model bytes. Hidden twins
with identical actor-visible information must produce byte-identical model
inputs and, under the same named RNG streams, the same distribution of final
actions.

### Offline privileged information

Offline generation may use true hands and burial for three bounded purposes:

1. ownership labels for BELIEF;
2. exact-world counterfactual outcomes for teacher/Q targets; and
3. audit labels that measure whether a behavioral inference was correct.

Actor rows and privileged targets remain separately sealed and hash-bound. A
public learner never consumes a world-generating seed or raw private teacher
transcript. Chain-of-thought is not a training target.

### Sampled-world information

At live inference a complete sampled world is a hypothesis drawn from the
actor-visible posterior, not the true hidden world. An optional
world-conditioned Q/value model may inspect that hypothesis inside search.
The final value and action must still aggregate across the frozen belief-world
population; no single sampled world becomes truth.

### Search authority

The engine owns legality and transitions. Learned components may:

- order legal branches;
- estimate continuation value at a leaf;
- propose additional legal actions;
- identify high-disagreement states; or
- allocate a bounded amount of extra search.

They may not silently drop engine-legal actions required by the registered
ballot, fabricate transitions, exceed the reviewed work budget, or bypass the
final search/LCB guard.

## Versioned artifacts

The first implementation should expose small, independently reopenable
objects rather than a monolithic checkpoint:

1. **`ActorObservationV1`** — canonical actor-visible decision state.
2. **`BeliefPosteriorV1`** — calibrated per-card ownership distributions plus
   exact hard-constraint masks and model identity.
3. **`BeliefWorldEnsembleV1`** — ordered legal complete worlds, weights,
   projection diagnostics, RNG identities, and pre/post-projection marginals.
4. **`TeacherCounterfactualV1`** — one public observation, complete legal
   ballot, common world set, named continuation policies, action outcome
   distributions, work receipts, and teacher identity.
5. **`PublicActionValueV1`** — actor-visible observation/action input with a
   distributional signed-level target aggregated across compatible worlds.
6. **`SearchDecisionReceiptV1`** — candidate population, work by branch/world,
   proposal/value sources, uncertainty, protected incumbent, final action,
   and exact replay identity.

The names are conceptual until their source contracts receive review. Each
artifact must have a closed schema, canonical bytes, strict source/runtime
bindings, failing-direction witnesses, and an all-false authority map.

## Value and Q targets

Action value is policy-relative. Every label binds the partner policy,
opponent policies, ballot, continuation portfolio, objective, perspective,
search budget, and terminal utility.

For a fully specified world `w`, public observation `o`, and legal action `a`:

```text
Q_world(w, o, a; pi) = distribution of signed level outcome
                        after action a under continuation contract pi
```

For the live public information set:

```text
Q_public(o, a; pi) = E[w ~ P(w | o)] Q_world(w, o, a; pi)
```

The artifact retains more than the mean:

- probability of each signed level outcome;
- expected signed level utility;
- downside or protected-LCB statistic;
- between-world variance and quantiles;
- teacher/search uncertainty; and
- probability that each action is best across compatible worlds.

A state value is derived from the registered decision rule, not trained as an
unqualified universal scalar:

```text
V_public(o; pi) = value of the action selected from Q_public under pi
```

Win probability may be reported, but signed level distribution is primary
because Shengji promotion utility is not binary. Separate banker/attacker and
lead/follow/bury surfaces are required diagnostics and may justify separate
heads if the data do; they are not silently pooled into one claim.

## Staged program

The dependency graph has two branches and one deliberately short path:

```text
E0 R4 -> E1 legal sampler -> E2 sampler mechanism -----> E6 sampler-only games
                                  |
                                  +---------------------+
                                                        |
reviewed PT confirmation -> E3 teacher packet ----------+--> E4 one Q head
                                                                  |
                                                                  v
                                                            E5 one Q use
                                                                  |
                                                                  v
                                                       E6 Q-assisted games
```

The diagram expresses evidence dependencies, not a requirement to execute
every box. An E2 sampler win may proceed directly to an E6 sampler-only game
test. The Q branch is optional and cannot delay that shorter path. PT schema
and extractor mechanics may progress in parallel with E0-E2, but a large
teacher packet waits for a reviewed PT result. E4 waits until both the E2
world-distribution contract and E3 target contract are frozen; otherwise the
learner would be trained against a different posterior or continuation from
the one search later consumes. No screen introduces a new sampler and a new Q
consumer together.

### E0 — close BELIEF R4

Question: does the current public-history model predict true hidden ownership
better than REF-C on the sole frozen test population?

Required evidence:

- valid terminal mechanics and leakage gates;
- held-out proper-score verdict versus symmetrically treated REF-C;
- seed stability, reliability, negative controls, and learning curves; and
- immediate plus independent byte-exact reconstruction.

Routing:

- a valid positive verdict opens E1;
- a valid negative verdict closes the current belief recipe and triggers a
  representation/data/optimization postmortem before any R5 scale-up;
- a mechanics/resource refusal authorizes only repair of the failed boundary,
  not an efficacy interpretation.

### E1 — sampler mechanics only

Question: can the certified marginals become legal correlated complete worlds
without destroying their calibration?

Treatment changes only the world sampler. Proposal policy, ballot,
continuations, objective, search budgets, and final selection remain literal
production.

Gate:

- every world satisfies physical counts and hard facts;
- projection succeeds on the full opened-development population;
- pre/post-projection marginal drift stays below a preregistered floor;
- hidden-twin and actor-visibility invariants hold;
- support/duplication/effective-sample-size diagnostics are acceptable; and
- REF-C and BELIEF receive equal world and search work.

No Q, value, policy, teacher, or strength claim enters E1.

### E2 — belief-to-search mechanism

Question: at equal work, do BELIEF worlds improve the decisions search is
trying to make?

On a frozen opened-development state population, compare:

- current REF-C world sampling;
- BELIEF world sampling; and
- a behavior/work-matched null that preserves compute and candidate geometry
  without the learned posterior signal.

Measure:

- error and variance of rollout/action values against held-out true-world
  counterfactual evidence;
- final N=30 nomination and R=300 protected-action flip dose;
- conditional utility of changed decisions;
- work, latency, sampler diversity, and world disagreement; and
- effects by natural decision surface and role.

Advance only when value quality improves, final-action dose is nontrivial, and
the dose-times-conditional-effect estimate supports a powered fresh screen.

### E3 — teacher counterfactual packet

Question: can a stronger planner produce stable action-value supervision, not
merely impressive chosen actions?

Use a reviewed PT successor to score a complete named ballot on common exact
worlds. The teacher may adaptively request engine rollouts, but every action's
label must be comparable under the same continuation and work contract.

The current PT-Sol0 private transcripts are design evidence, not automatically
training data. A reviewed extractor must prove which engine-returned outcomes
are complete, how repeated requests aggregate, and that no private prompt,
model text, completion token, or hidden-world identity enters a public row.

Before a large packet, require:

- a fresh PT confirmation or a deliberately descriptive-only label scope;
- teacher repeatability and action-value calibration on a held-out subset;
- a complete-ballot or explicitly bounded-proposal contract;
- common random numbers/worlds across actions where valid;
- state/deal/player-disjoint splits; and
- a cost/throughput receipt that sizes generation rather than guessing.

### E4 — one learned Q/ranking head

Question: can one model compress the teacher's action comparisons stably?

The first learner is one head only. It does not include a new belief encoder,
policy prior, leaf value, and allocation head simultaneously.

Recommended first target:

- input: actor-visible observation plus one legal action;
- label: `Q_public` signed-level distribution aggregated over the reviewed
  world/teacher packet;
- secondary labels: between-world disagreement and best-action probability;
- loss: proper distributional outcome loss plus a bounded pairwise ranking
  term against the protected production action; and
- selection: a preregistered multi-seed stability gate on held-out deals,
  roles, and surfaces.

An optional `Q_world` learner may follow if the public model loses important
world disagreement. It is evaluated only inside sampled worlds and never on
the literal true hidden state at live play.

Advance only if the model improves held-out value calibration/regret, is
stable across seeds, and survives ballot/perspective/continuation mutations.
Offline fit alone grants no policy authority.

### E5 — Q-assisted search mechanism

Question: does the learned head improve equal-work search while search remains
the guard?

Choose exactly one treatment:

1. Q orders the existing ballot before rollout allocation;
2. Q proposes a bounded number of extra legal actions;
3. Q supplies a leaf estimate at a frozen depth; or
4. Q uncertainty allocates a bounded extra budget.

Do not combine these in the first screen. Compare literal search, Q-assisted
search, and a work/behavior-matched null on fresh states. Report final-action
flip dose, protected-incumbent override rate, conditional utility, catastrophic
tail, and exact work. A positive offline Q gate with a null E5 result closes
that consumer; it does not justify a larger whole-game retry.

### E6 — whole-game screen and confirmation

Only an E2 or E5 consumer with adequate natural dose and positive fresh-state
mechanism evidence reaches whole games.

The first whole-game packet contains at least:

- literal `mc-s0-report-lcb` champion;
- the exact BELIEF/Q consumer;
- a behavior/work-matched null; and
- mirrored roles/deals with deal-clustered signed-level inference.

The numerical whole-game bar is intentionally per experiment because the
natural dose, measured variance, latency, and minimum worthwhile effect differ
between a sampler-only and Q-assisted consumer. It is nevertheless fixed
*before any E6 selection deal is drawn*. One consolidated E6 design review
must bind:

- the exact champion, challenger, and matched-null policy bytes;
- the minimum worthwhile challenger-versus-champion effect `delta_min`;
- one-sided alpha `0.05`, the paired deal-cluster estimator, interval method,
  role mirroring, and tail/legality/latency guards;
- fixed `n_selection` and `n_confirmation`, disjoint seed namespaces, and a
  no-interim-look/no-extension stopping rule;
- a conservative variance source that contains no E6 outcomes; and
- a power calculation showing `n_confirmation` has at least 80% power to
  reject zero when the true challenger-versus-champion effect is
  `delta_min`, plus adequate power for the challenger-versus-null attribution
  contrast at its separately declared design effect.

If that powered size does not fit the reviewed compute cap, E6 is not admitted;
the effect bar is not weakened and the sample is not frozen merely to keep a
host busy. The selection population may choose at most one exact challenger
but grants no strength claim. On the untouched confirmation population,
promotion requires both one-sided 95% lower bounds—challenger minus champion
and challenger minus matched null—to exceed zero, the challenger-minus-
champion point estimate to meet `delta_min`, all safety/latency guards to pass,
and an independent terminal reconstruction. The null-versus-champion result
is always reported; if the null itself wins, it opens a simpler compute or
widening hypothesis rather than being credited to belief/Q. Selection and
confirmation are never pooled or extended after outcomes are visible. A
belief, teacher, Q, or state-screen PASS alone never supports deployment.

## Complexity and reliability budget

R4 demonstrated that scientific and operational complexity can erase days of
valid compute. The following constraints are part of the research design, not
optional engineering polish:

1. **One new causal axis per screen.** Belief sampler first; one Q use later.
2. **Reuse immutable inputs.** Capture, reference, cache, checkpoint, and
   teacher artifacts are separately reopenable and are not deleted merely
   because a downstream stage refuses.
3. **Mechanics rehearsal before one-shot evidence.** A small synthetic or
   opened-development rehearsal exercises the exact stage graph, artifact
   publication, deadlines, progress, and reconstruction. Its outcomes cannot
   tune a frozen scientific population or threshold.
4. **Graceful, interpretable truncation.** A wall deadline seals the best
   complete common unit with a visible `truncated` status where the protocol
   permits; it does not erase healthy learning or masquerade as convergence.
5. **Measured admission, immutable scientific cap.** Capacity uses measured
   pace and whole-service resources. A cap is not raised after observing that
   a candidate barely misses it.
6. **Progress everywhere.** Every long stage reports completed/total units,
   percent, elapsed, ETA, worker population, CPU/device utilization, memory,
   and the current artifact boundary.
7. **Use all safe parallelism.** Shard independent states/worlds/actions across
   all available cores or devices when canonical merge order and bit identity
   are proven. Do not parallelize shared mutable RNG/model state implicitly.
8. **One consolidated review per immutable stage.** Review source, exact
   inputs, capacity, freeze, terminal rule, and can-fail witnesses together.
   Add another round only for a load-bearing defect or materially changed
   bytes.
9. **Witness the wiring.** Every identity, authority, and metric that carries a
   verdict has an end-to-end failing-direction test, not only a helper test.
10. **No all-or-nothing diagnostic deletion.** Partial operational artifacts
    remain sealed and diagnosable; incomplete scientific populations cannot
    make efficacy claims or be cherry-picked.

## Human and policy-diverse data

Human play is valuable for behavioral belief only when the actor-visible event
channel is complete and comparable. Future R5 or successor corpora should:

- include all trump ranks and no-trump games at natural or explicitly reported
  sampling rates;
- split by player and deal so the same person's tendencies do not leak across
  train/evaluation;
- distinguish human, champion, and named-bot policy strata;
- log declaration timing, pass events, attempted/accepted play information
  exactly as visible to the actor; and
- report transfer intervals rather than interpreting an underpowered null as
  policy invariance.

Human actions are not teacher-optimal labels. They supply proposal diversity,
behavioral likelihood evidence, and hard cases whose actions must be scored
counterfactually by the named teacher/search contract.

## Interpretation matrix

| Result | Interpretation | Next action |
|---|---|---|
| R4 negative | Current public-history representation/training does not beat REF-C. | Stop E1; inspect curves, strata, data mix, and architecture before any R5 run. |
| R4 positive, E1 projection poor | Marginals learned, but the joint sampler destroys or cannot realize them. | Fix sampler/projection only; do not retrain belief. |
| E1 passes, E2 null | Better hidden-card prediction does not improve current search at equal work. | Diagnose consumer/objective/continuation; do not claim belief strength. |
| PT confirmation negative | Current reasoning teacher is not stable enough to supervise a strength program. | Keep descriptive lessons; do not scale distillation. |
| PT positive, E4 negative | Teacher is useful but the chosen learner/target cannot compress it. | Change one learner axis; do not weaken the teacher gate. |
| E4 positive, E5 null | Q predicts labels but does not help the registered search use. | Close that integration mode; preserve search. |
| E2/E5 positive, whole-game null | Mechanism does not transport at natural frequency or scale. | Select none; use dose and role/surface diagnostics for a materially different design only. |
| Whole-game confirm positive | The composed public-belief search policy is stronger under the named contract. | Begin deployment review; do not infer broader architecture superiority. |

## First actionable milestone after R4

If and only if R4 returns a valid positive offline verdict, write one immutable
E1/E2 design for a **sampler-only consumer**:

- existing R4 model and REF-C identities frozen;
- opened-development states selected without test outcomes;
- exact correlated projection and complete-world sampler;
- unchanged production ballot, continuations, objective, and final search;
- equal accepted-world and search-work budgets;
- REF-C, BELIEF, and matched-null arms;
- projection drift, value error/variance, decision-flip dose, and conditional
  utility gates; and
- one consolidated source/capacity/freeze review.

In parallel, PT work may prepare the `TeacherCounterfactualV1` schema and a
small mechanics-only extractor. It must not launch a large teacher dataset or
start Q training until the PT result is reviewed and R4 has been interpreted.

## Deferred choices

The following are deliberately not frozen by this document:

- GRU versus transformer/set/graph belief encoder;
- public Q versus sampled-world Q;
- direct Q, pairwise ranking, value, or uncertainty as the first learned head;
- model width/depth, optimizer, or warm start;
- teacher model identity and rollout budget;
- population size and fleet allocation; and
- stage-specific practical effect floors and numerical thresholds, which must
  be frozen in that stage's reviewed design before its selection population is
  generated, as E6 specifies for whole games.

Those choices depend on R4 curves, the reproduced PT result, profiling, and a
score-free prevalence/capacity census. Freezing them now would add complexity
without evidence.

## Success definition

The architecture succeeds only when the evidence chain remains intact:

```text
better held-out belief
  AND legal projection with low drift
  AND better equal-work search estimates
  AND meaningful natural final-action dose
  AND positive fresh-state utility
  AND positive confirmed whole-game signed-level utility
```

Any missing conjunction is a diagnostic milestone, not a strength result.
