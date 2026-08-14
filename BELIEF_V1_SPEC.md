# BELIEF-V1: actor-visible world model and belief-sampled search

Status: research specification. This document authorizes no corpus opening,
training run, strength run, promotion, or deployment.

## Goal

Design, implement, and validate a versioned actor-visible world model that
makes fixed-work search better by sampling likely public-consistent hidden
worlds instead of treating all constraint-consistent worlds alike.

BELIEF-V1 is complete when it either:

1. passes mechanics, leakage, held-out calibration, sampler-integrity, and
   same-work decision gates against both the current sampler and a shuffled-
   belief null; or
2. produces a reviewed terminal negative result that identifies which gate
   failed and closes the exact recipe without spending a whole-game screen.

A BELIEF-V1 pass opens a separately reviewed whole-game design. It does not by
itself establish bot strength.

## Tangible outcomes

BELIEF-V1 is not “train a smarter model” as an open-ended goal. It must leave
behind five inspectable things:

1. **One typed actor-view record.** Given a replay prefix and seat, a canonical
   artifact shows exactly what was public, what that actor privately knew, what
   was logically deduced, and which bytes are simulator-only labels. A hidden-
   world counterfactual tool proves that changing inaccessible cards cannot
   change the actor input.
2. **One belief report.** For a decision, an actor-visible X-ray shows expected
   suit lengths and point mass by opponent/kitty, void probabilities, pair and
   tractor probabilities, and the chance each legal lead/throw is beaten,
   ruffed, or remains boss. Every number is labelled fact, deduction, or
   probability.
3. **One calibration report.** Held-out reliability plots and proper scores
   show whether “70% likely” events occur about 70% of the time, including role,
   phase, declaration, pair, and kitty strata. The current constraint sampler
   is reported beside it.
4. **One drop-in research sampler.** The sampler produces complete legal worlds
   from the belief, with exact card/hand/kitty conservation, reproducible RNG,
   weights, and work counters. It is selectable for experiments but is not
   silently installed in production.
5. **One causal decision verdict.** With ballot, N/R, continuation, utility,
   and work held fixed, the belief sampler either beats both the current
   sampler and a shuffled-belief null, or it closes honestly. The result also
   states natural dose, implied whole-round effect, and whether a powered
   whole-game test is economically justified.

Concrete examples of what a successful report can answer are:

- “Seat 2 is proven void in hearts; seat 3 is 68% likely void.”
- “The unseen higher heart pair exists, but only has a 21% posterior chance of
  being legally playable by a remaining opponent.”
- “This three-component throw is legal to attempt and has 74% posterior chance
  of surviving intact; its most likely failure is the low pair.”
- “Twenty-four point-card points remain publicly unaccounted for; the hidden
  kitty contains an expected 6.2, so only 17.8 are expected in hands.”
- “The candidate changed world weights on 83% of searched decisions and gained
  a paired 0.04 utility on those decisions at exactly the incumbent work.”

The last sentence is illustrative, not a threshold or claimed result.

## Why this is different from the current representation

Today the project has three useful but separate mechanisms:

- `Memory` reconstructs exact public facts and conservative deductions from
  public play plus the acting hand. It knows seen cards, proven voids,
  declaration pins, pair/run upper bounds, and whether a card is *provably*
  boss. Its risk helpers answer questions such as “could somebody beat this?”;
  they are not calibrated probabilities.
- `rl-observation-v1-public-no-private-kitty` is a fixed 531-value tensor. It
  contains the acting hand, aggregate cards played by relative seat, the
  current trick, aggregate unseen cards, trump/banker/role/points/card-count
  fields, and proven voids. It intentionally excludes even the banker's known
  burial to preserve historical checkpoint identity. Much of the chronology,
  declaration structure, pair/run deductions, and uncertainty over ownership
  is absent or collapsed.
- `MCBot` samples assignments that satisfy hand sizes, declaration pins,
  voids, and pair/run caps. Subject to those constraints, it does not score a
  world by how likely the declarations and play history make it. The result is
  constraint-consistent determinization, not a calibrated posterior.

Chronological public-history and privileged-feature encoders also exist for
the DouZero and Suphx microbaselines. They establish useful mechanics, but they
do not currently produce a shared public belief state or weight search worlds.

BELIEF-V1 changes the abstraction from:

> known cards + aggregate unseen pool + hard possibility constraints

to:

> observed facts + actor-private facts + sound deductions + calibrated
> distributions over the remaining hidden ownership and action consequences.

It does **not** reveal the hidden deal. It represents uncertainty about it.

## Ordering with the other research pillars

The evidence orders the three pillars:

1. **Search capacity:** preserve and confirm generic widening because it is the
   measured positive. Spend the merged performance dividend on more worlds,
   more candidates, or narrower confidence intervals.
2. **World representation:** use BELIEF-V1 first to improve which hidden worlds
   search evaluates. Test memory-aware continuations separately afterward.
3. **Learning:** use the wider, belief-aware search as a teacher only after its
   public-information decision advantage is established.

This ordering prevents another model from learning a more precise version of
the wrong sampler, ballot, continuation, or target.

It also preserves existing work rather than rebuilding it:

- the already-positive same-work ballot-widening treatment should receive its
  own confirmation independently of BELIEF-V1;
- the running pair-aware terminal evidence should be read before choosing a
  memory-aware continuation experiment;
- `MCSmartRoll` and `LEVEL_OBJECTIVE` are existing continuation/value assets,
  not BELIEF-V1 features, and require their own dose-and-edge triage; and
- the reviewed `PointContext` work is the base point/boss fact boundary. When
  that source lands, BELIEF-V1 extends it with probabilistic opponent/kitty and
  action-consequence fields rather than introducing a competing point context.

## Information boundary

Every BELIEF-V1 row contains a perspective seat and a public replay prefix.
Fields are partitioned as follows.

| class | examples | runtime use |
|---|---|---|
| Public observed | ordered declaration event and shown cards; completed plays; current trick; banker and roles; public points; hand sizes | Input |
| Actor private | acting hand; banker-known burial when the actor is banker | Input |
| Logically deduced | exact unseen multiplicities; proven voids; declaration ownership pins; pair/run upper bounds | Input and hard constraint |
| Probabilistic belief | hidden-card ownership, hidden-kitty composition, unproven void/pair/run/boss/ruff/point distributions | Model output |
| Simulator privileged | exact hands of the other three seats and non-banker-hidden burial | Training label and audit only |

The public/actor input must be byte-identical for two simulator states that
differ only in hidden cards unavailable to the actor. The privileged target is
stored separately and may not be passed through the runtime feature API.

## Versioned contracts

### `ActorObservationV1`

Canonical, reconstructable input for one actor at one decision:

- exact engine, ordering, role, phase, trick, and cards-remaining context;
- acting hand;
- banker-known burial only when the actor is the banker;
- ordered declaration/show history, not just the final declaration summary;
- chronological public play history with attempted and engine-adjusted actions
  distinguished where the engine can force a failed throw component;
- exact public points and trick-point flow;
- `Memory` facts: played multiplicities, proven voids, declaration pins, and
  pair/run upper bounds;
- candidate action identity and decision surface only in the action-context
  consumer, not baked ambiguously into the state; and
- source, schema, ballot, and perspective identity.

The contract is reconstructable from an actor-visible round snapshot. It is
not required to remain a single dense vector; a fact tensor plus an ordered
event sequence is preferred to losing chronology for dimensional convenience.

### `BeliefTargetsV1` — simulator only

For each actor-visible observation, labels include:

- remaining count `0/1/2` of every card code in each other relative seat's
  hand (including the actor's partner);
- remaining count of every card code in the hidden kitty for a non-banker;
- exact effective-suit lengths, pairs, longest pair runs, and point-card totals
  by hidden receiver;
- true voids and higher-card/pair/tractor availability; and
- exact labels for action-relative events that can be reconstructed without a
  continuation policy, such as whether a remaining seat can follow, ruff, or
  beat a specified component in the true world.

The true hidden world is a label, not an oracle action. Search-derived action
values are a separate teacher artifact bound to sampler, continuation, budget,
and utility.

### `BeliefStateV1`

The public model output includes:

- `count_probability[card][receiver][0..2]` for the other three relative seats
  and the hidden-kitty receiver where applicable;
- expected card counts derived from those distributions;
- per-seat/effective-suit distributions for length, void, pair count, and
  longest pair run;
- per-seat and hidden-kitty point-count distributions, total and by effective
  suit;
- uncertainty/calibration summaries needed by the sampler and evaluator; and
- the observation/model/source identity that produced the belief.

Hard facts override probabilities. A proven void has probability one; a pinned
declaration copy has probability one at its owner; a banker-known buried card
is actor-private fact and is not predicted as hidden.

Conservation must hold exactly after projection:

- expected copies across eligible hidden receivers equal every unknown card
  multiplicity;
- expected and sampled hand sizes equal the engine's remaining hand sizes;
- hidden-kitty size is exact;
- impossible receivers receive zero probability; and
- pair/run summaries agree with sampled card multiplicities.

### `ActionContextV1`

This is derived for each legal candidate from `ActorObservationV1` plus
`BeliefStateV1`. It separates several ideas that were previously called
“available” or “boss”:

`ActionContextV1` is an extension of the existing immutable `PointContext`
proposal, not a rewrite. `PointContext`'s exact trick points, points-left,
bracket distance, and conservative public boss/ruff facts remain the fact
layer. BELIEF-V1 adds calibrated distributions beside those facts and keeps
the provenance of each field explicit.

- **legal shuai-pai availability:** an engine/ballot fact—what multi-component
  throws the actor can attempt from its hand;
- **shuai-pai success probability:** probability every component survives the
  remaining seats, with failure-component and penalty risk reported separately;
- probability a single, pair, or tractor is boss after each remaining seat;
- probability of an in-suit beat, ruff, and overruff;
- probability a higher pair or sufficient tractor is held by each seat;
- expected exposed, captured, fed, and hidden-kitty points; and
- probability the current winner remains winner through the trick.

“Points left” is also split: public point-card mass still unaccounted for,
posterior point mass in each opponent hand, posterior point mass in the hidden
kitty, and action-relative capturable/exposed points are different fields.

No hand-authored threshold in this context directly changes production play.
Consumers are separately reviewed and compared causally.

### `BeliefSamplerV1`

The first consumer draws complete worlds from `BeliefStateV1` while enforcing
all engine and `Memory` constraints. It must:

- use a named local RNG stream and deterministic canonical ordering;
- produce complete, legal, non-aliased hands and kitty;
- record proposal probability or an auditable equivalent weight;
- never relax proven voids or other hard deductions;
- preserve exact accepted/rejected/attempt/work counters; and
- fail closed rather than silently fall back to an incompatible distribution
  in confirmatory use.

The current constraint sampler remains the primary baseline. A same-work null
shuffles or masks belief weights while retaining candidate count, world count,
validation work, and RNG shape.

## Training and data design

### Population

Capture fresh natural decisions from the exact champion, stratified before any
labels by:

- actor role and relative seat;
- declaration type and strength;
- lead/follow/bury surface;
- early/mid/late phase;
- public void/pair/run evidence;
- shuai-pai candidate availability;
- points remaining and current trick value; and
- banker versus non-banker kitty visibility.

Split by deal seed or complete round before training. No public prefix from one
deal may cross train, calibration, and test folds. Natural frequencies are
retained for primary metrics; rare tactical strata may be separately reported
but cannot silently reweight the primary claim.

### Model and losses

The first model predicts hidden ownership and shape, not actions. Its primary
loss is proper probabilistic scoring on held-out hidden ownership, with exact
constraint projection. Auxiliary void, length, pair/run, point, boss, and
action-context heads are allowed only when their labels are mechanically
derived from the same frozen world.

Report negative log likelihood where the representation supports it, Brier
score for named binary events, calibration error/reliability curves, and sharp-
ness at equal calibration. Accuracy alone is insufficient.

After belief-sampled search passes, later learners may share the observation
encoder and train separate heads:

- belief/ownership and uncertainty;
- Direct-Q action value with role-correct returns;
- v11-style pairwise advantage relative to the champion action; and
- search-policy proposal probabilities.

Those heads are **not deliverables of BELIEF-V1**. In particular, a Direct-Q
head trained on search values is search distillation, not episodic-return
Direct-Q; it would inherit the clean-encoder, target-identity, and multi-seed
learning gates of that family. A v11-style head remains a bounded proposer or
ranker and may not become a leaf. BELIEF-V1 builds only the belief/ownership
model and uncertainty required to calibrate it.

Search teachers retain soft per-action values, common-world paired differences,
uncertainty, and continuation identity. A privileged model may help construct
targets during training, but its hidden features are masked or distilled away
and the public endpoint is tested independently.

## Evaluation ladder

### Gate A — mechanics and leakage

- exact reconstruction of public facts and legal private facts;
- counterfactual hidden-world invariance of `ActorObservationV1`;
- seat/team rotation and physical-copy symmetry;
- zero privileged bytes in the runtime API or serialized public artifact;
- exact count, hand-size, kitty-size, declaration, void, pair, and run
  conservation; and
- named rejection—not crash—on malformed or cross-schema input.

Any failure stops the recipe.

### Gate B — held-out belief quality

On a fresh untouched fold, compare BELIEF-V1 with the current constraint-
consistent baseline. The concrete design preregisters primary ownership NLL or
proper score, named secondary Brier/calibration metrics, bootstrap unit, role/
phase strata, and material-regression tolerance.

Advance only if the primary paired improvement has a positive lower bound and
no load-bearing role or decision surface has a preregistered material
regression. Report calibration even if ranking improves.

### Gate C — sampler fidelity

- zero illegal or incomplete accepted worlds;
- exact reproducibility and counter reconciliation;
- posterior predictive checks for declarations, voids, suit lengths, pairs,
  tractors, points, and kitty composition; and
- separate evidence that more likely held-out true worlds receive more weight
  than under the current sampler.

A model can pass offline prediction and still fail this gate if projection or
sampling destroys its signal.

### Gate D — same-work decision value

On fresh natural champion decisions, hold ballot, N/R, continuation policy,
utility, candidate order, and total accepted-world work fixed. Compare:

1. BELIEF-V1 sampler;
2. current constraint sampler; and
3. shuffled/masked BELIEF-V1 same-work null.

Use common random numbers inside each comparison and independent seed clusters
across decisions. Advance only if the candidate has positive preregistered
lower bounds versus both controls, exact work parity, no short/zero searches,
and no critical role/phase reversal. Repeat the smallest decisive robustness
view with a second named continuation policy before composition.

### Gate E — transport and whole-game permission

Measure natural decision dose and transport the Gate-D effect into a plausible
whole-round effect with uncertainty. A whole-game design is permitted only if
its minimum detectable effect is smaller than that transported effect with a
predeclared safety margin.

The whole-game run, confirmation, production use, and teacher generation each
require their own later decision. BELIEF-V1 does not inherit authority from an
offline or state-level pass.

## Work packages

| package | output | cheapest decisive failure |
|---|---|---|
| B0 — contract | canonical observation/target/belief/action-context schemas and adversarial fixtures | hidden-world invariance or information-class violation |
| B1 — corpus | fresh split-safe natural public prefixes with separately sealed hidden labels | duplicate deal leakage, missing strata, or unreconstructable actor view |
| B2 — calibrated baseline | current constraint prior and first ownership/shape model | no held-out proper-score gain or subgroup regression |
| B3 — belief sampler | complete weighted constrained worlds and posterior checks | illegal worlds, lost calibration, or unreconciled work/RNG |
| B4 — same-work search | three-arm candidate/current/shuffled-null decision screen | no positive causal lower bound or continuation fragility |
| B5 — transport memo | natural dose, implied whole-game effect, MDE, and next decision | effect too small to justify a whole-game run |

Packages B0-B3 are reusable research infrastructure, but no package is kept
alive merely because implementation was expensive. B4 or B5 may close the
recipe honestly.

## Economics and triage

BELIEF-V1 has dose at every decision where Monte Carlo samples a hidden world,
but **meaningful dose** is the fraction of natural decisions where learned
weights materially differ from the current constraint prior. B1 must measure
that distribution before B4 is sized.

No whole-game fleet reservation belongs to B0-B3. B0 uses synthetic and
replayed fixtures. B1/B2 first use a score-free preflight to measure capture,
label, and training cost; its concrete design must then state a wall-hour cap.
B3 uses tractable synthetic late states with enumerated compatible worlds plus
held-out natural posterior-predictive checks. B4 is one fixed-state three-arm
screen, not four independent whole-game screens.

Before B4, the packet must state:

- natural search-decision count and meaningful-belief-change dose;
- held-out calibration edge over the current prior;
- maximum states, worlds, wall hours, and host;
- minimum detectable conditional decision effect;
- implied whole-round effect range; and
- the terminal decision: close, revise calibration, or permit B5.

If the measured dose or calibration edge makes a useful B4 effect
undetectable within the cap, BELIEF-V1 stops before consuming that screen.

## Review and authority boundary

To reduce review churn while preserving the real boundaries:

1. one source review covers B0 mechanics plus the concrete B1/B2 offline
   design;
2. ordinary reproducibility review covers opened-development diagnostics;
3. one immutable design review binds a B4 population, exact model/sampler,
   controls, work, metrics, and stopping rule;
4. a separate execution admission is used only if B4 consumes sealed or
   one-shot evidence; and
5. one terminal review reopens and recomputes the result.

Review requests must state the decision they unlock. A design PASS never means
execution permission, and an offline calibration PASS never means strength.

## New-goal statement

> **BELIEF-V1 — Build and validate an actor-visible world model that improves
> same-work search.** Specify and implement public/actor/deduction/belief/
> privileged information boundaries; build a split-safe hidden-ownership
> corpus; beat the current constraint-consistent prior on held-out proper
> scoring and calibration; sample complete legal worlds without losing that
> signal; and test fixed-work search against both the current sampler and a
> shuffled-belief null on fresh natural states. Finish with either a positive,
> continuation-robust causal result plus natural-dose/MDE permission for a
> separately reviewed whole-game design, or a reviewed terminal negative that
> closes the exact recipe. Do not deploy, open sealed unrelated outcomes, or
> start whole-game strength evidence under this goal alone.
