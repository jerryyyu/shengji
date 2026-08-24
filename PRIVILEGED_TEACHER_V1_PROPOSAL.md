# Privileged Teacher V1 proposal

Status: proposal only. This document authorizes no implementation, compute,
test opening, gameplay change, strength claim, promotion or deployment.

## Decision this lane should answer

Can we first learn or search a materially stronger Sheng Ji policy when the
complete hidden state is available, and then turn that capability into
actor-legal action values that remain useful after the hidden state is removed?

This separates two questions that earlier “oracle” work often conflated:

1. **Capability ceiling:** can a policy exploit a fully known deal better than
   the current heuristic or Monte Carlo continuation?
2. **Information-set teaching:** for one public history, which actions remain
   good on average over all compatible hidden worlds rather than only in the
   true world used to create a label?

A positive answer to the first question does not answer the second. An
omniscient action can depend on information a runtime player cannot possess,
can assume equally omniscient partners and opponents, and can teach impossible
signalling conventions. It is a ceiling and a source of counterfactual values,
not a deployable policy.

## Why this is materially different from prior oracle work

The repository contains several useful but narrower assets:

- `oracle.py` learned a full-hand scalar value from heuristic self-play. It did
  not optimize a full-state action policy.
- DMC2 and high-N/v13 learned value or proposal targets under named existing
  continuations. A target generated with hidden cards was not evidence that
  the continuation using those cards was strong.
- Suphx O0/O0-v2 tested short privileged curricula. They did not establish a
  stable, improving full-information policy and did not transfer robustly.
- exact-endgame and Teacher diagnostics measured selected roots. They were not
  a whole-game self-play hill climb.
- BELIEF predicts hidden ownership. It does not choose moves and cannot by
  itself repair a weak policy after the hidden world is sampled.

The missing asset is therefore not another scalar oracle head. It is a
measured full-state policy-improvement loop plus an explicit reduction from
full-state action values to public-information targets.

## Typed estimands

Let:

- `h` be the actor-visible information state: public history, public
  deductions and the acting player's hand;
- `w` be one complete hidden world compatible with `h`;
- `a` be a legal action at `h`;
- `Q_T(h, w, a; pi_cont)` be a privileged teacher's signed-level value after
  forcing `a` and continuing with the frozen policy `pi_cont`; and
- `P(w | h)` be a named world distribution, initially a constraint-consistent
  reference and later a separately certified BELIEF distribution.

The runtime-safe teacher target is not `argmax_a Q_T(h, w_true, a)`. It is:

```text
Q_info(h, a) = E_{w ~ P(w | h)}[Q_T(h, w, a; pi_cont)]
```

The artifact should also retain world-conditioned dispersion and action-rank
instability. High disagreement is useful supervision: it tells a public
student or search controller where certainty is impossible and more sampling
is valuable.

Every result must name `P`, `pi_cont`, legal-action enumeration, actor/team
perspective, return definition and horizon. Changing one creates a new target.

## Proposed ladder

### PT0 — exact mechanics and baseline packet

Build a small, score-free harness before self-play:

- exact two- and three-decision endgames where exhaustive action values can be
  enumerated;
- paired role/seat rotation and signed-level accounting;
- forced-action counterfactual replay for every legal candidate;
- baseline policies: `heuristic`, `smart`, `mc-strong` and the exact
  `mc-s0-report-lcb` continuation where affordable;
- hidden-twin fixtures proving that public-target aggregation is byte-identical
  when only the true hidden world changes; and
- resource/progress receipts, checkpoint recovery and a bounded deadline.

PT0 passes only if exhaustive action values, terminal utility, rotation and
forced-action replay reproduce exactly and every named mutation changes a
specific test. It produces instrumentation, not a learned policy.

### PT1 — acquire a full-state teacher

Train or search a policy with complete state available during both acting and
evaluation. The first implementation should be deliberately simple:

- role-conditioned, action-conditioned return prediction rather than a lone
  state-value head;
- legal-action features plus complete hands, kitty and current round state;
- whole-round signed-level return as the primary target, with trick points and
  action regret diagnostic only;
- immutable policy checkpoints, optimizer state, curves and replay/trajectory
  manifests at every epoch; and
- independent initialization seeds, with no best-seed promotion.

Candidate acquisition may combine policy improvement from privileged search,
off-policy action-return learning and self-play. Centralized training with a
privileged critic is allowed, but any later public actor must be evaluated
without privileged features.

### PT2 — prove the teacher improved

Use a small policy population rather than a single latest-checkpoint opponent.
Each candidate plays mirrored fresh deals across all trump ranks, roles and
banker/attacker perspectives against:

- the immediately previous teacher;
- frozen heuristic/search baselines; and
- a fixed mixture of earlier accepted checkpoints.

Promotion requires a positive conservative lower bound in signed levels versus
the incumbent and no material regression versus the policy mixture. Exact
endgame regret must not regress. A new checkpoint that merely exploits its
current self-play partner is rejected. This is a PSRO-like guard against
cycling, not a claim of equilibrium in four-player partnership Sheng Ji.

The all-omniscient league establishes only that full-state policy improvement
is possible. Failure here is decisive: there is no reason to distill a teacher
that did not beat the existing continuations even with extra information.

### PT3 — information-set aggregation

For actor-visible DEV states, enumerate or sample compatible worlds and score
every retained legal action with the accepted privileged teacher. Publish:

- `Q_info(h, a)` under the named reference distribution;
- within-action value variance across worlds;
- probability each action is best across worlds;
- regret of the public-information argmax relative to each world's oracle;
- effective world count, legal-support coverage and action-ranking stability;
  and
- direct comparisons with uniform/constraint-only and shuffled-world nulls.

The true hidden world may be one evaluation label but may not select the target
action. Public-twin states must produce identical target bytes. World identity,
deal seed, other hands and kitty remain excluded from runtime/student input.

### PT4 — public student or rollout consumer

Only after PT3 passes should one public consumer be chosen:

- a recurrent action-value student conditioned on actor-visible history;
- a bounded proposal/ranker inside fresh search; or
- the privileged teacher used only as a continuation over belief-sampled
  worlds, with search still making the public decision.

Do not combine these consumers in the first screen. Measure held-out action
value error, ranking/regret, hidden-twin invariance, natural decision-flip dose,
latency and robustness across at least two named continuation policies.

### PT5 — gameplay causality

The first online screen holds root actions, world count and continuation work
fixed and compares:

1. current public sampler/current continuation;
2. the single privileged-teacher-derived consumer; and
3. an exact same-work shuffled or information-destroyed null.

Only a positive causal effect with sufficient natural dose may advance to a
fresh whole-round confirmation against `mc-s0-report-lcb`. A privileged-policy
win, an offline distillation win or a state-screen win is not strength.

## Data and leakage contract

- Full hands and kitty are allowed only in privileged teacher inputs and
  target construction. A public student receives only its typed actor row.
- Human games may evaluate transfer and provide public histories, but human
  actions are not truth labels. Consent, exclusion and sparse strata remain
  explicit.
- All trump ranks, banker/attacker roles, declaration surfaces and early/mid/
  late play must be represented. Fixed-rank self-play cannot support a general
  policy claim.
- Train, calibration and unopened test populations remain separate. The
  teacher policy pool and world distribution are frozen before opening test.
- Failed throws and declaration information use the engine-observer contract,
  not server-private attempted-card logs.
- A public-target builder reads only actor payloads plus separately opened
  world/teacher artifacts under the offline controller. Runtime code cannot
  import the privileged row type.

## Recoverability and performance

The first expensive run must not repeat an all-or-nothing evidence design:

- checkpoint, optimizer, curve and population artifacts seal incrementally;
- a deadline seals the best common completed epoch as
  `truncated_by_deadline=true` rather than discarding healthy learning;
- a truncated cohort cannot masquerade as patience-converged;
- resource caps use measured pace, not an upper-bound estimate as admission
  pace;
- progress reports stage, percent, completed/total units, active workers,
  elapsed time and deadline headroom;
- cached public-history encodings and counterfactual branches are shared
  without changing action or target bytes; and
- parallelism is measured under the real memory cap before a scientific
  freeze. More workers are not automatically faster when each duplicates the
  same corpus pages.

R4 and R5 remain untouched. PT development uses a separate branch, namespace,
host allocation and seed registry. It may not consume the BELIEF test split or
compete with a live reviewed scientific unit.

## Entry and stop rules

The lane should stop or redesign at the earliest failed scientific boundary:

1. **PT0 mechanics fail:** repair instrumentation; no learning run.
2. **PT1 cannot improve training/calibration action return across seeds:**
   revise representation/credit/optimizer on DEV only.
3. **PT2 teacher does not beat incumbent and mixture:** close that teacher
   recipe. Do not distill it.
4. **PT3 aggregation gains vanish versus same-information null or violate
   public twins:** close for leakage or no transferable information.
5. **PT4 has negligible final-decision dose or no held-out regret advantage:**
   do not spend a whole-game screen.
6. **PT5 misses its conservative causal bound:** no strength confirmation.

Conversely, passing PT2 authorizes only information-set target construction;
passing PT3 authorizes one public-consumer proposal; passing PT4 authorizes one
fixed-work screen; passing PT5 authorizes one fresh confirmation design.

## Relationship to BELIEF R4/R5

BELIEF and the privileged teacher are complementary but independently
falsifiable:

- If R4/R5 show calibrated ownership learning, PT3 can aggregate teacher
  values under both REF-C and BELIEF and measure the incremental value of the
  learned posterior.
- If BELIEF selects none, PT3 can still use the exact constraint-consistent
  sampler; the teacher question remains meaningful.
- If the privileged teacher cannot beat current continuations with full state,
  better BELIEF alone cannot repair that continuation. Search may still benefit
  from better worlds, but this teacher lane closes.
- If both work, belief-weighted teacher targets become a principled candidate
  for public action-value learning and rollout search.

PR #127's bare-point-lead cases and PR #130's point-risk tie breaker are useful
DEV evaluation states: an improved teacher should price round utility and
future control rather than imitate “low single from longest plain suit.” They
must not be promoted to test labels or used to claim that the teacher solves
the reported production symptom.

## Literature-derived constraints

- [Suphx](https://arxiv.org/abs/2003.13590) combines supervised initialization,
  distributed self-play, global reward prediction, oracle-guided training and
  runtime adaptation. The relevant lesson is a staged policy curriculum, not
  permanent hidden-card access.
- [DouZero](https://proceedings.mlr.press/v139/zha21a.html) supports direct,
  role-specific action-return learning with parallel actors; it motivates
  action-conditioned Q targets rather than another scalar residual oracle.
- [ReBeL](https://papers.nips.cc/paper_files/paper/2020/hash/c61f571dbd2fb949d3fe5ae1608dd48b-Abstract.html)
  and [Student of Games](https://arxiv.org/abs/2112.03178) motivate public-belief
  state plus guided search/self-play. Their two-player zero-sum theory does not
  grant an equilibrium claim in Sheng Ji.
- [COMA](https://ojs.aaai.org/index.php/AAAI/article/view/11794) motivates a
  centralized privileged critic with decentralized actors and counterfactual
  credit assignment.
- [Policy-Space Response Oracles](https://papers.neurips.cc/paper_files/paper/2017/file/3323fe11e9595c09af38fe67567a9394-Paper.pdf)
  motivates measuring candidates against a policy population rather than only
  the most recent self-play partner.

These are design constraints, not evidence that their assumptions or results
transfer to Sheng Ji.

## First reviewable implementation capsule

After proposal review, the smallest implementation is PT0 only:

1. exact endgame state schema and legal-action enumeration;
2. forced-action terminal evaluator with signed-level utility;
3. frozen baseline adapter and paired seat/rank rotation;
4. public-twin information-set aggregation fixture; and
5. progress/resource/checkpoint schema with an end-to-end miniature run.

It must contain no trainable production policy, no live registry entry and no
fleet launch script. One source review should cover this complete capsule; a
separate freeze review is required only when a concrete self-play run exists.
