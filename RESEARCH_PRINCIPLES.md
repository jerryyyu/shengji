# Research principles

This document records the durable rules for choosing Shengji research. It is
not a run queue, an evidence ledger, or execution authority. `BACKLOG.md` owns
current work, `AI_POLICIES.md` owns measured policy evidence, `RL_PLAN.md` owns
the roadmap, and `BELIEF_V1_SPEC.md` owns the next representation milestone.

## 1. Optimize verified whole-game strength

The product metric is paired signed level utility against the named live
champion on fresh mirrored rounds. State-level utility, imitation accuracy,
calibration, throughput, human agreement, and pool Elo are mechanism tests.
They can select what to investigate, but none substitutes for whole-game
evidence.

An honest `SELECT_NONE` is a successful experiment when it closes a useful
question. A large artifact or a clean run is not itself progress toward
strength.

## 2. Search is the current authority and the next teacher

The strongest positive arm in the closed campaign came from uninformed ballot
widening, while several targeted heuristic compositions did not survive
whole-game evaluation. That arm was work-matched to the learned treatment, not
to champion: it used 14.8% more accepted worlds and 80.9% more searches than
champion. It therefore supports a search-capacity hypothesis, not a clean
same-work strength claim. The next confirmation must separate policy width
from compute with three arms: champion, widening at champion work, and widening
at the earlier null-arm work. The merged native work makes that test cheaper
and can also buy statistical power rather than only more worlds per decision.

Search should remain the final decision-maker until a learned policy beats it
directly. A stronger public-information search can later generate better soft
action values, preferences, and uncertainty targets for learning.

## 3. Improve the worlds before adding more tactical patches

The current sampler generates worlds that satisfy known card counts, hand
sizes, declarations, voids, and pair/run caps. Those worlds are possible; they
are not a calibrated posterior over what opponents and the hidden kitty are
likely to contain.

The next representation milestone therefore improves three consumers in a
controlled order:

1. hidden-world sampling, while holding ballot and continuation fixed;
2. continuation policy, while holding sampled worlds and root search fixed;
3. learned proposal, value, or policy heads, after the first two have supplied
   a better teacher.

Each consumer gets its own causal comparison. They are not introduced as one
bundle.

Existing assets route this work: confirm generic ballot widening with the
three-arm work decomposition above; read the pair-aware continuation result before choosing
another continuation experiment; extend the reviewed PointContext fact
boundary; and treat MCSmartRoll and LEVEL_OBJECTIVE as separately triaged
continuation/value hypotheses rather than folding them into the belief model.

## 4. Every field has an information class

Every feature and label must be assigned to exactly one class:

- **public observed:** declarations, public plays, trick order, points, roles;
- **actor private:** the acting hand and, for the banker, the cards it buried;
- **logically deduced:** proven voids, declaration pins, pair/run upper bounds;
- **probabilistic belief:** calibrated ownership, void, pair, boss, ruff, point,
  and hidden-kitty distributions inferred only from the first three classes;
- **simulator privileged:** true opponent hands and hidden kitty, available only
  to build labels and audit calibration.

Deployed inference may consume the first four classes. Simulator-privileged
bytes may never enter the deployed observation, search leaf, action selector,
or runtime cache.

## 5. Preserve uncertainty instead of collapsing it early

“Could beat,” “probably holds,” and “is proven boss” are different claims.
Belief outputs retain probabilities or distributions until the consumer makes
a decision. A single determinized world, a single oracle argmax, or one scalar
state value must not be presented as public-information truth.

Inference from a public action not taken—such as a declined point feed or
higher pair—is actor-legal but policy-dependent. It must name the policy mix
that supplied the evidence, remain probabilistic, and report transfer gaps
between human, champion, and named-bot play. It may never silently harden into
a `Memory` fact or a universal tactical rule.

Teacher data should preserve per-action common-world outcomes, uncertainty,
and disagreement—not only the winning action.

## 6. Bind values to their meaning

Every value or preference binds:

- acting perspective and role;
- action ballot;
- hidden-world distribution;
- continuation policy or policy portfolio;
- search budget and horizon;
- reward/utility definition; and
- encoder and source identity.

An action ranker is not automatically a leaf value. A privileged outcome model
is not automatically a public policy. Better offline fit is not automatically
better play.

## 7. Demand attribution and natural dose before scale

A mechanism first beats both the live baseline and a same-work null that adds
the same candidates or compute without the claimed intelligence. Its natural
frequency in complete champion play must make the transported whole-game
effect detectable at the proposed sample size.

Sparse or hand-selected effects do not earn a large whole-game screen merely
because their conditional mean is positive. Robustness is checked across role,
phase, and at least two named continuation views before composition.

## 8. Keep correctness, performance, and strength separate

Bit-identical native code can ship after correctness and performance review;
it does not need a strength screen because it does not change decisions.
Representation, sampler, policy, or ballot changes do change the estimand and
need strength evidence. Faster execution may be used to enlarge a reviewed
test, but it does not inherit the old test's strength authority.

## 9. Use the smallest decisive gate

Offline, score-free, and opened-development diagnostics should use ordinary
code review plus reproducible artifacts. One concrete design review should
bind the source, population, metric, and stopping rule. A separate execution
gate is justified only when a run consumes a one-shot or sealed resource.

Do not manufacture a chain of reviews for facts already bound by the same
immutable design. Do not collapse source review, execution admission, and
terminal evidence review when they protect genuinely different boundaries.

## 10. Close recipes; preserve families

A negative result closes its exact population, model, target, sampler,
continuation, and composition. It does not disprove search, belief modeling,
privileged training, Direct-Q, pairwise ranking, or learning as broad families.

Re-entry requires a material change and a cheaper test that distinguishes the
new hypothesis from the closed one. “Train longer,” “add more patches,” and
“run it again” are not material changes.
