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

1. **Search capacity:** preserve generic widening as a measured hypothesis,
   not a same-work win. Its positive T4 null arm used 14.8% more accepted
   worlds and 80.9% more searches than champion. Confirm it with champion,
   widening-at-champion-work, and widening-at-null-work arms before assigning
   causality. Spend the merged performance dividend on more worlds, more
   candidates, or narrower confidence intervals.
2. **World representation:** use BELIEF-V1 first to improve which hidden worlds
   search evaluates. Test memory-aware continuations separately afterward.
3. **Learning:** use the wider, belief-aware search as a teacher only after its
   public-information decision advantage is established.

This ordering prevents another model from learning a more precise version of
the wrong sampler, ballot, continuation, or target.

It also preserves existing work rather than rebuilding it:

- the positive but compute-confounded ballot-widening arm should receive its
  own three-arm work-controlled confirmation independently of BELIEF-V1;
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
| Logically deduced | exact unseen multiplicities; proven voids; sound non-banker declaration pins; pair/run upper bounds | Input and hard constraint at the altitude the schema can express |
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
- chronological public play history with engine-actual cards and the public
  failed-throw signal; returned attempted cards are retained only for the actor
  that made that attempt, never exposed to another seat;
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

The receiver set is explicit and actor-relative. It contains the other three
seats and, for a non-banker actor, the hidden kitty. A banker's known burial is
actor-private input and is therefore excluded from the hidden receiver set.

V1 exposes two views of the same posterior:

1. **ownership weights:** a distribution over each unknown physical card's
   eligible receiver, plus the probability of zero/one/two copies of a card
   code at each receiver; and
2. **sample-derived marginals:** per receiver and effective suit, distributions
   over length, top rank, point count, pair count, longest tractor, trump
   length, and boss-holding events.

The first model deliberately does not claim to represent every card-to-card
correlation. Its ownership logits are converted into complete worlds by a
constrained joint assignment, and the derived marginals are measured from
those complete samples. Exact hand-size, copy, void, declaration, and kitty
constraints therefore remain joint even where the learned soft model is
factorized. If this factorization cannot calibrate pair/tractor or top-rank
events, V1 closes or advances to a separately specified autoregressive model;
it does not relabel inconsistent marginals as a posterior.

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

### Behavioral inference is probabilistic and policy-bound

BELIEF-V1 does cover information in *which public action was chosen*, including
negative evidence from an action that was available but not taken. This is the
main delta over `Memory`: `Memory` derives policy-independent logical bounds;
the belief model may learn policy-dependent likelihoods from the complete
public sequence. Examples include:

- declining to feed a partner-winning trick, which may downweight remaining
  point cards or useful pairs at that seat;
- following a trump-pair lead with a forced singleton joker, which can sharply
  reduce the posterior probability of another trump pair and of long trump;
- discarding an unforced point card off-suit, which may increase the posterior
  probability of shortness, void, or deliberate point unloading; and
- declining a higher pair, tractor, ruff, overruff, or boss play when that
  action was publicly plausible under the actor's legal surface.

None of those is promoted to a fact. The output remains a calibrated
distribution and carries:

- `behavior_model_schema` and model/source hashes;
- the training corpus' policy mixture (human, champion, or named bot);
- the observation domain and policy-shift stratum; and
- an explicit `probabilistic_policy_conditioned` information tag.

V1 uses a learned history encoder for these soft likelihoods rather than a
growing table of hand-authored feed/joker/discard multipliers. The existing
`Memory` deductions remain hard guards. This division makes forced legality
and conservation exact while letting the learned layer capture behavioral
signals whose direction and magnitude vary by policy.

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

### First tactical implementation and consumer

The first implementation is intentionally narrower than the full architecture:

1. reconstruct `ActorObservationV1` from the complete public transcript at
   each captured decision rather than adding a mutable belief cache to
   `Round`;
2. train one public-history ownership head with privileged hands/kitty used as
   labels only;
3. apply `Memory` constraints as zero/one masks, then project the learned soft
   ownership weights onto exact card, hand-size, and kitty conservation;
4. use those weights only inside `BeliefSamplerV1` to choose among complete
   constraint-consistent assignments; and
5. keep the existing ballot, continuation policy, value, N/R, and final search
   decision rule unchanged for the first causal screen.

This recompute-from-history design is slower than an incremental cache but is
easy to replay, hash, rotate, and audit. B0/B1 measure its real capture cost
before scale. An incremental implementation is considered only if profiling
shows the recompute cost matters after correctness.

The feed gate, memory-aware rollout continuation, uncertainty-based search
allocation, and learned-policy encoder are four **later consumers**, not bundled
into V1's first estimand. Each requires its own matched null. In particular,
the first sampler result cannot be cited as evidence for a feed threshold or a
belief-aware rollout policy.

## Training and data design

### Population

Capture fresh natural decisions from the exact champion, stratified before any
labels by:

- actor role and relative seat;
- declaration type and strength;
- lead/follow surface (the V1 actor contract is play-phase only; bury decisions
  require a later contract version);
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

Every quantitative belief claim names two references. They are called `REF-C`
and `REF-H` here to avoid collision with the B0-B5 work-package names below:

- **REF-C — current constraint-consistent proposal** (the review-side B0,
  sometimes described informally as “uniform-consistent”): the current sampler
  with all `Memory` hard facts and its exact randomized backtracking/split
  behavior. The project has not proved this proposal mathematically uniform
  over accepted worlds, so V1 must not use that stronger label; and
- **REF-H — current hand-coded context** (the review-side B1): REF-C worlds
  plus the exact `Memory`/`PointContext` fact and action-context fields
  available to today's decision code, but no learned behavioral likelihood.

For hidden-ownership calibration REF-C and REF-H may have the same world
weights; that is an honest result, not a reason to invent a second prior. For
derived action context and fixed-work search, REF-H is the stronger current-
feature baseline. BELIEF-V1 must not win by withholding an existing hard fact
or PointContext field from a control.

### Exact acceptance invariants — zero tolerance

- **E1 — conservation:** for each unknown card, expected copies across eligible
  hidden receivers equal its unknown multiplicity; receiver expectations equal
  exact remaining hand and kitty sizes. Every sampled world satisfies integer
  conservation exactly.
- **E2 — hard-fact respect:** played and actor-known cards have zero hidden
  mass; proven void receivers have zero mass for that effective suit; a proven
  zero-pair cap has zero same-code-pair mass. Only sound declaration pins have
  probability-one hand ownership. A banker-declarer's shown card is eligible
  for either the banker hand or hidden kitty because burial is legal. Run caps
  are joint constraints enforced by the later complete-world sampler, not by a
  marginal-only validator.
- **E3 — public-twin bit identity:** two states with byte-identical public and
  actor-private transcripts but different inaccessible hands/kitty produce
  byte-identical actor inputs and belief outputs.
- **E4 — perspective symmetry:** absolute seat relabeling preserves the full
  actor-relative posterior and sampled-world distribution.
- **E5 — target isolation:** privileged labels live in separately sealed
  artifacts and are absent from runtime inputs, caches, sampler APIs, and
  inference logs.

### Calibration and negative-control invariants

- **C1 — proper-score lift:** on untouched complete-round folds, BELIEF-V1 has
  a positive preregistered lower bound in ownership log-loss or Brier score
  over REF-C and no material regression versus REF-H on load-bearing strata.
- **C2 — behavioral-stratum lift:** improvement is reported separately after
  declined feeds, forced trump/joker evidence, and unforced point discards. A
  claimed behavioral model must improve at least one preregistered behavioral
  stratum and may not hide a reversal behind aggregate frequency. An offline
  rung whose natural population was not sized for those strata must label C2
  descriptive and make no behavioral claim.
- **C3 — marginal reliability:** predicted versus empirical curves are
  reported for receiver count classes and linear expectations derivable from
  those marginals (suit/trump length, point count, pair count). Void/ruff,
  tractor, boss/top-rank and other cross-code joint events move to B3, where a
  complete-world posterior exists. Ranking without calibration does not pass.
- **C4 — exact synthetic posterior shim:** a frozen enumerable fixture must
  prove the encoder/count-head/training/projection path can recover a known
  posterior and that a uniform control fails. Its design must state which
  full-game capture mechanics it does not certify.
- **N1 — history ablation:** for a powered positive behavioral stratum,
  withholding or within-stratum shuffling the public action chronology
  collapses behavioral lift toward REF-C. Underpowered point ratios are
  diagnostic, not mandatory-closure gates.
- **N2 — permuted labels:** training on round-grouped shuffled hidden labels
  produces no held-out lift.
- **N3 — policy shift:** human, champion, and named-bot strata are scored
  separately; the transfer gap is reported rather than assumed away.

Before any online screen, usefulness also has to pass:

- **U1 — true-world proper score:** in marginal-only B2 this is the same test
  as C1 and may not be presented as independent evidence. Joint true-world
  likelihood belongs to B3; and
- **U2 — fixed-world value variance:** at equal world count and unchanged
  continuation, the belief sampler reduces preregistered rollout-value error or
  variance without introducing measured bias.

U2 is a mechanism result, not a strength result. Failure of U1 or U2 stops the
sampler route before a whole-game run.

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
