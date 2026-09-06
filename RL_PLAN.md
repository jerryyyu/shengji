# Learning and search research plan

Last reconciled: **2026-09-06 (W32 milestone)**. This document owns research architecture,
estimands, and the decision tree. `BACKLOG.md` owns priority; live compute and
exact review asks are in `HANDOFF_ACTIVE.md`; policy names and deployment state
are in `AI_POLICIES.md`; immutable receipts and verdicts are in
`HANDOFF_REVIEW.md`.

Historical model chronology remains in
`docs_archive/rl-plan-chronology-through-2026-08-03.md`,
`docs_archive/rl-plan-experiments-1b-1o.md`, dated archives, and Git history.
Do not append run diaries or duplicate exact packet hashes here.

## Objective and evidence standard

Build a Shengji policy that is demonstrably stronger than the exact live
`mc-s0-report-lcb` champion under a correct engine and reproducible evaluator.
The only confirmed strength gain to date is RLCB itself (`+0.338 ± 0.068`
signed levels vs `mc-strong`, 2,048 clusters). Earlier component gains often
failed to improve play; the September 4 retrospective (ledger `0088544f`)
shifted the emphasis to direct consumer tests and rigor proportional to the
claim. PT-Sol/Luna and now **A+B+C W32 shortlisting** are positive exploratory
whole-round results, not new confirmed/deployed policies. W32 is particularly
useful because it uses sampled worlds available to a real policy, not true
opponent hands. Its equal-compute advantage is still unresolved.

Evidence labels:

- **MECHANICS:** code, legality, parity, leakage, throughput, or rehearsal.
- **OFFLINE:** held-out prediction, calibration, stability, or teacher value.
- **SCREEN:** fresh state or whole-round evidence that selects a design.
- **CONFIRM:** preregistered fresh mirrored evidence supporting a strength claim.
- **REJECT/SELECT NONE:** the exact registered recipe failed its bar.

Primary policy metric is paired signed level utility clustered by deal seed.
Win rate, role splits, advancement tails, and catastrophic losses are required
diagnostics. Offline loss, Brier score, point regret, Elo pools, and human
agreement never substitute for a fresh whole-game comparison.

## Operating modes (rigor tiers)

Rigor is matched to the claim a run supports, never applied at flat rate.

| tier | what it supports | keep | drop |
|---|---|---|---|
| **i — exploratory / DEV** | pipeline works; a model exists; a diagnostic number | score-free until sealed (private artifacts closed until `terminal.json`), reproducibility stamp (git SHA, seeds, input hashes), never-delete, resumable runs, one up-front pipeline review for leakage and reproducibility | immutable freezes, one-shot admission, launch packets, per-launch confirmations, capacity rebinds, exact-head artifact coupling, machine markers, independent reconstruction |
| **ii — selection screen** | choosing between designs | tier i plus a preregistered comparison, literal parent, matched null | the tier iii machinery |
| **iii — confirmation** | a deploy or strength claim | the full immutable machinery: exact-head freeze, one-shot admission, independent reconstruction, ledger markers | — |

Value V2 moved to tier i at ledger `295136ba`. A lane enters tier iii only
when a candidate beats the champion on a tier ii paired screen.

## Current decision tree

1. **Keep optimized A+B+C W32 as the experimental reference.** It ranks the
   exhaustive legal set on 32 constrained sampled worlds, keeps four
   alternatives plus the heuristic incumbent, and lets production N30/R300
   full rollouts decide. On 256 paired rank-2 deals it gained +0.1387 signed
   levels/round; exact-trajectory engineering cut decision wall 2.849×, to
   3.53× production. See [the diagram and full comparison](AI_POLICIES.md#experimental-w32-shortlist).
   This is not a claim that an accurate standalone leaf value has been solved.
2. **Integrate the decision-preserving speedup before another scaling run.**
   Main-sync #249 → #252 → #254, run focused parity plus normal CI, then ask
   Claude for one consolidated exact-head merge review. No extra gameplay or
   repeated model reconstruction merely to integrate unchanged semantics.
3. **Next policy question: four → eight alternatives.** Hold W32, N30/R300,
   checkpoint, sampler and continuation fixed. Measure whether admitting more
   candidates improves paired utility enough to justify the added final
   selection cost. W64 and N60/R600 both cost more without a demonstrated
   improvement; their crossing-zero intervals do not close those ideas
   universally. K8 is proposed, not already run.
4. **Improve cost without silently changing policy.** Profile zero-reuse wide
   follows and bypass useless cache bookkeeping where equivalence is proven;
   schedule known expensive replay pairs earlier and show straggler-aware ETA.
   Ranking still takes 73% of W32 decision wall. Two-stage candidate pruning,
   selective work allocation and deeper search are separate policy experiments,
   not part of the bit-identical optimization.
5. **Improve the model against its actual consumer.** Train on independently
   grouped trajectory sources; measure full-legal candidate admission, not
   just top-k ordering within production's existing ballot. The current win
   uses an MLP with an auxiliary points head, CE-selected from A+B+C; it does
   not validate a Transformer, a learned policy prior or a BELIEF dependency.
   A+C+D is the next data/model comparison, with checkpoint changes tested
   separately from shortlist settings. Run B largely reuses Run A deals, so
   more rows must not be counted as more independent games.
6. **Keep teacher quality and collection efficiency separate.** Retain the
   stronger Sol/Luna planning data and compare cheap batched collection with
   the original rollout-enabled teacher before scaling it for fitting. Use
   fresh deal-disjoint fit/selection/final-validation sets and name the actual
   continuation behind every value target. Cheap play-only prompts do not
   inherit historical teacher strength. See the teacher section below.
7. **Confirm strength last, with a useful matched control.** The original
   W32−production-x10 difference is unresolved at comparable wall; optimized
   W32 is cheaper but not exactly matched to production x3. A fresh comparison
   must separate learned candidate admission from extra compute and cover
   diverse trump ranks with an appropriately trained model. Repeated tuning
   on the opened rank-2 deals is not independent confirmation.

Codex owns shortlist engineering/scaling; Claude owns the separate PUCT and
model experiments. Share measured findings, not an assumption that shortlist
automatically becomes PUCT. BELIEF R4/R5 remains closed. D64's retained
256-slot/255-realization set remains coverage-audit evidence only, not a
slot-targeted training recipe.

The current prioritized form of this tree is in `BACKLOG.md`.

### What the milestone does and does not establish

The promising division of labor is **model proposes over a broad legal set;
sampled-world full rollouts verify a small set**. Candidate admission is a
plausible mechanism, not isolated causal proof of the win. More samples reduce
Monte Carlo noise but cannot by themselves repair model or continuation bias.
The completed W64/final-MC experiments tested the payoff directly and found no
resolved increment. Do not infer that their failure proves a particular bias.

Recursive MCTS/PUCT would additionally maintain interior states, allocate
visits using priors and backed-up values, and resolve hidden-information and
partnership choices. W32 has none of that tree machinery. Keep it as the
working reference while testing any deeper consumer. The eventual
search→data→model loop needs a measured improvement at each link; offline
loss or extra tree depth alone does not establish it.

## Retired BELIEF world-model contract

This section preserves the R4 design and information boundary for possible
future re-entry. It is **not active work or the W32 model architecture**.

### Four information layers

The most important design constraint is that these are different types, not
interchangeable features:

1. **Public facts:** rules, trump, banker, declarations actually visible to
   the table, accepted plays, current trick, scores, hand sizes, and logically
   proven void/pair/run bounds.
2. **Actor-private facts:** the acting seat's hand and, for the banker only,
   its own buried cards.
3. **Beliefs:** probabilities inferred from compatible deals and behavior—for
   example whether a seat is nearly void, still holds a higher pair, is likely
   out of points, or retained a joker. These are not hard facts merely because
   the action is suggestive.
4. **Privileged labels:** true other hands and hidden burial available only in
   simulation/offline training and evaluation.

Runtime bytes contain layers 1 and 2 only. Layer 4 must live in separately
sealed artifacts. Two states with identical actor-visible information but
different hidden worlds must produce byte-identical runtime observations.

### Tactical representation

`ActorObservationV1`/its reviewed successors encode the acting hand, trump and
role context, ordered declarations and plays, current/completed tricks, public
points, remaining card population, hand sizes, void evidence, and pair/run or
declaration constraints. The target records the true count of each physical
card code at each hidden receiver: three other hands plus the burial.

The retired R4 model was a small recurrent ownership predictor:

1. canonical public events are tokenized in chronological order;
2. a GRU summarizes the variable-length declaration/play history;
3. static actor/context features are combined with that summary; and
4. a shared output head predicts, for each card code and possible receiver, a
   distribution over 0/1/2 copies.

The recurrent model is appropriate because an action's meaning depends on what
happened before it: failing to feed, playing a joker under pressure, following
short, or declining a declaration can update the posterior. Each decision in a
round supplies a supervised example and is scored against the true hidden
allocation. The GRU is a V1 engineering choice, not a claim that recurrence is
optimal. Comparing a Transformer, set/graph or hybrid ownership encoder would
require a separately justified reopening, not another R4/R5 run by default.

### What V1 can and cannot express

Per-card ownership probabilities directly answer questions such as “who is
likely to hold either ace?” and same-code pair probabilities. They do not by
themselves define a legal joint hand distribution. Suit length, trump length,
points held, tractors, multi-card throws, ruff ability, and kitty composition
depend on cross-card correlation.

Therefore the consumer path is:

```text
actor-visible history
        ↓
per-card ownership posterior
        ↓
constraint-aware joint projection / complete-world sampler
        ↓
derived tactical distributions
        ↓
equal-work Monte Carlo search
```

Derived outputs can include distributions over suit/trump length, remaining
pairs/tractors, boss ownership, point holdings, kitty points, follow/ruff/beat
availability, and uncertainty itself. Search must consume complete compatible
worlds or an explicit joint model; it must not pretend independent marginals
or one MAP world are the hidden truth.

### Baselines and learning claim

`REF-C` is the current constraint-consistent sampler converted to ownership
marginals. It already receives every sound hard fact available to the actor.
BELIEF earns an offline claim only by improving held-out proper scoring beyond
REF-C after symmetric Monte Carlo-noise treatment, while satisfying mechanics,
leakage, negative-control, seed-stability, and reliability gates.

A model may learn behavioral likelihoods from true hidden labels—for example
that a policy tends to feed points when partner is secure—but the inference
input remains actor-visible. Policy-dependent evidence must be audited under
chronology ablation and across champion, named-bot, and human play. It is a
probability, never silently promoted to a deduction.

## R4 and R5

### R4: terminal — `NO_PRIMARY_POLICY_SIGNAL`

R4 is closed (ledger 2026-08-31). Offline, the preserved synthetic-primary
cohort reduced held-out count Brier by 21.40% versus REF-C, but the
permuted-label control also improved materially and failed on demand — a
predictive channel, not behavioral belief learning. On the opened-DEV
consumer diagnostic (104 rounds, identical ballot/work/RNG), belief weighting
was operationally indistinguishable from the production sampler: ESS 97–99.5%
of maximum, final-action flips 1/104 (control 0/104), paired true-world value
difference exactly zero for both primary−production and primary−control. The
sealed R4 test population was never opened and stays sealed. R4 checkpoints
are preserved as diagnostics only.

### R5: closed unless an oracle-belief probe justifies reopening

No R5 source, freeze, rehearsal, or execution. The lane reopens only if a
separate oracle-belief probe — the production sampler given the true hidden
worlds versus production — shows a gain worth a learned model. Like the value
and prior probes, this is an expensive heuristic diagnostic rather than an
upper-bound ceiling, and a weak/null result is non-closing. C0 (perfect
information inside the fixed production planner lost to both parents) already
suggests that upside may be small. The
operational lessons listed for R5 in earlier revisions (all trump ranks,
disjoint human data, host-independent inputs, parallel cache/projection,
curves, graceful truncation, in-loop deadlines) are retained as reusable
artifacts and performance work, not as a reason to run.

### Offline gates

The exact design owns thresholds, but the conceptual gates are:

1. **Mechanics:** legal support, conservation, hard facts, hidden-twin
   invariance, actor/target isolation, exact artifact identity.
2. **Primary calibration:** paired proper-score improvement versus REF-C on a
   frozen held-out allocation population, with finite-reference Monte Carlo
   bias handled symmetrically.
3. **Behavior:** preregistered, adequately powered action-history strata; an
   underpowered stratum is not a pass.
4. **Negative controls:** chronology or label controls fail in the expected
   direction; controls run through an explicitly typed path rather than forged
   production rows.
5. **Reliability:** non-vacuous curves and failing-direction witnesses for
   marginal-expressible events; joint events wait for a sampleable posterior.
6. **Training stability:** multi-seed cohort behavior is reported as stability,
   not eight independent population confirmations.
7. **Usefulness readiness:** exact projection succeeds, its calibration drift
   is measured, and no gate merely restates the primary Brier comparison.

## Retained belief-to-policy ladder (inactive)

If a future belief lane is justified, its staged consumer checks remain:

1. **Prediction only:** establish held-out ownership calibration.
2. **Sampler only:** generate legal complete worlds from the posterior and
   compare post-projection marginals with the certified model output.
3. **Search-value mechanism:** on fixed public states, compare rollout value
   error/variance under BELIEF worlds versus REF-C at equal work.
4. **Decision dose:** measure how often BELIEF changes the N=30 nomination or
   R=300 protected final action on natural decisions.
5. **Fresh state screen:** test the changed decisions under an independent
   report population.
6. **Whole-game screen and confirmation:** literal champion, belief treatment,
   and behavior/work-matched null on fresh mirrored deals.

Search remains final authority through the first strength campaign. Learned
value/Q/pairwise heads can later enter as bounded proposals, allocation signals,
or calibrated leaves only after passing their own causal gate.

## Privileged and perfect-information teachers

Perfect information is useful only if its consumer turns it into better
actions. Prior work exposed the distinction:

- **PT0:** small exact late-endgame advantage over weak baselines, inconclusive
  versus production.
- **PT1:** exact teacher action guidance changed many actions but failed its
  required utility gates.
- **PT-Full:** evaluating only the literal true world performed badly; repeated
  true-world search recovered the collapse but still did not beat the public
  ensemble.
- **C0:** fixed true-world consumer variants all lost to their required
  parents, despite improving some visible local symptoms.
- **PT-Sol0:** the reviewed 26-root/52-role full-round diagnostic gave Sol exact
  hidden state plus engine-owned observe/rollout/play tools. Against the same
  roots it averaged `+17/26` signed levels over exact production arm A,
  `+37/52` over true-world production B, and `+23/26` over C0-S. Its exact
  execution head is `e73f970e`.
- **PT-Luna0:** the lower-cost Luna replication completed and independently
  reopened all 52 roles. It averaged `+5/13` over A, `+23/52` over B, and
  `+8/13` over C0-S, while trailing Sol by `-7/26`. Its exact execution head is
  `2394140b`.

This is the first reviewed evidence that two flexible reasoning agents can
turn perfect information plus engine rollouts into better full-round decisions
than the exact production-policy arm on the bounded open-DEV roots. It is a
teacher milestone, not a fresh whole-game strength or deployment result: the
roots are opened development evidence, the agents are privileged, and neither
is a callable production policy.

The key implication is that BELIEF and consumer policy are complementary.
Perfect hidden-state prediction cannot fix a poor objective, partnership model,
continuation, candidate ballot, or planning procedure. Before distilling a
privileged teacher, prove the teacher itself beats the public production policy
on exact states and then in realistic full-round populations.

The sealed `pt-luna-rpc-isolated-b0b1bd95-r1` dataset (32 complete games,
ledger `6c71bee3`) and earlier reopenable Luna decisions remain teacher
evidence; Sol remains the higher-quality reference on the shared measured
roots. The old collection attempt is complete, not a permanent prohibition
on new bounded teacher experiments.

The newer token-efficiency investigation found **2.70× completed rounds per
token and 2.08× rounds per wall time** for a four-decision batch on four
matched starting rounds. A 16-game cost extension completed with no failures.
Those are engineering/cost observations, not strength or quality equivalence
to the historical tool-using planner. Before a larger collection, compare the
compact/batched play-only recipe with the rollout-enabled teacher on a fresh
quality bridge. Only batch current decisions from distinct deals; do not put
mirrored/future turns from one deal into the same request. Host-side routing
is not a semantic privacy guarantee inside a shared model context.

Use fresh independent deal groups, keep validation separate from fit and
selection, and label the continuation actually played. If one value estimand
is intended, apply the same named engine continuation to relabel states;
mixed teacher outcomes are not interchangeable targets. Sol can first supply
a bounded compatibility/cost sample, followed by a declared sampling recipe.
Neither this plan nor the W32 result launches scaled collection. Details:
[teacher efficiency investigation](https://github.com/jerryyyu/shengji/blob/724d811676363a13e164d6d8d7ceca16745b7c2f/TEACHER_TOKEN_EFFICIENCY.md).

## Search and teacher strategy

The active research program has three connected questions:

1. **Candidate admission and search cost.** Keep the positive W32 reference;
   separate exact speedups, wider shortlists and compute-matched controls.
2. **Allocation and depth.** Test a small change against that reference before
   building a larger PUCT recipe. The old T4 compute-confounded widening result
   and the new full-legal W32 result are different experiments.
3. **Model and teacher transport.** Improve data/targets against the actual
   search consumer, preserve held-out games, then test the resulting policy.
   Neither a better teacher nor better offline prediction guarantees this link.

More search on a bad world distribution can waste compute; a better belief with
a bad consumer can also lose. Measure search work, posterior quality, consumer
decision dose, and whole-game utility separately.

## Literature-derived design constraints

This is an architecture filter, not evidence that a method transfers to
four-seat partnership Shengji.

| system | useful result | Shengji constraint |
|---|---|---|
| [AlphaGo](https://storage.googleapis.com/deepmind-media/alphago/AlphaGoNaturePaper.pdf), [AlphaZero](https://arxiv.org/abs/1712.01815) | Policy focuses search, value truncates it, and improved search supplies later training targets. | Preserve the division of labor, but operate at a public-belief root. Fully observed two-player MCTS and one scalar observation value do not transfer directly. |
| [Suphx](https://arxiv.org/abs/2003.13590) | Human pretraining, distributed self-play, decision specialization, privileged-information policy curriculum, and per-hand adaptation. | Privileged scalar subtraction was not a faithful Suphx test. Separate decision surfaces and gradually remove privileged policy features if this lane reopens. |
| [DouZero](https://proceedings.mlr.press/v139/zha21a.html) | Role-specific recurrent action values learned from terminal returns at scale. | A faithful successor is from-scratch, role/action-conditioned Q with immutable actors and correct signed returns—not a warm-started oracle-residual hybrid. |
| [Libratus](https://noambrown.github.io/papers/17-Science-Superhuman.pdf), [Pluribus](https://noambrown.github.io/papers/19-Science-Superhuman.pdf), [depth-limited solving](https://arxiv.org/abs/1805.08195) | Imperfect-information search reasons over ranges and robust continuation strategies. | Keep a fixed blueprint/partner policy and test a small continuation portfolio. Poker equilibrium guarantees do not transfer to decentralized partnership play. |
| [DeepStack](https://arxiv.org/abs/1701.01724), [bridge belief Monte Carlo search](https://www.ieee-jas.com/article/doi/10.1109/JAS.2024.124488) | Maintain ranges over private hands; the bridge work supervises a belief network on true deals and samples deals from it for Monte Carlo search. | This is the closest BELIEF precedent: privileged labels, actor-visible inference, calibrated complete-world sampling, then search. Offline calibration is not strength. |
| [Bayesian Action Decoder](https://arxiv.org/abs/1811.01458) | Public actions update approximate beliefs over private information. | Feeding, withholding, joker use, failed throws, and declaration timing may inform probabilities, but require policy-shift and chronology controls. |
| [ReBeL](https://papers.nips.cc/paper/2020/hash/c61f571dbd2fb949d3fe5ae1608dd48b-Abstract.html), [Student of Games](https://arxiv.org/abs/2112.03178) | Public state plus a distribution over private states is an explicit search state. | Search a belief/range, not one determinization; two-player zero-sum convergence claims do not transfer. |
| [Meowjong](https://arxiv.org/abs/2202.12847), [Mortal](https://mortal.ekyu.moe/), [Mahjax](https://arxiv.org/abs/2605.20577) | Specialized decisions plus enormous fast-simulator experience can make simple learning recipes strong. | Treat simulator/native throughput as research leverage and specialize heterogeneous Shengji surfaces; speed cannot repair a wrong target. |
| [AutoGo](https://evjang.com/2026/04/28/autogo.html#cover) | Make the complete collect→train→evaluate loop work on a smaller domain before scaling and automation. | Rehearse the exact mechanics path at small scale, then freeze. Automation may execute a reviewed metric; it may not invent or promote one. |

## Data and artifact contract

Keep these artifact classes distinct:

1. **State reservoir:** reconstructable actor-visible state plus frozen split;
   old labels are not generic truth.
2. **Belief corpus:** actor row and separately sealed hidden-allocation target,
   with physical cross-binding and no world-generating metadata in model input.
3. **Counterfactual teacher set:** complete ballot, common worlds,
   continuation, objective, perspective, and paired outcomes—not only argmax.
4. **Episodic RL set:** immutable actor/checkpoint identity, sequential history,
   role-correct return, and retry-free provenance.
5. **Human behavior set:** replay key, pseudonymous player/deal grouping, actual
   action, source completeness, and counterfactual price before policy use.

Every dataset binds selection and split, source/engine, observation semantics,
ballot, sampler, continuation, objective/perspective, budget, producer, model,
and transitive source identity. Repeated valid sampled worlds are retained with
replacement when they represent probability mass. Invalid actor visibility,
private-kitty drift, or target cross-binding quarantines an asset regardless of
shape compatibility.

Human data supplies policy diversity and behavioral evidence. Use all trump
ranks and player/deal-disjoint splits; do not call mixed-skill human moves an
oracle or infer true-person disjointness from mutable display names.

## Compute, review, and recovery rules

- Before authorizing a projected multi-hour run, review its complete execution
  DAG with the user. The packet must identify any repeated full-data pass and
  justify why it is not duplicate integrity work; give the worker count and
  expected utilization for every expensive node; show the exact checkpoint,
  resume, and partial-result behavior for each failure boundary; and put the
  fastest learning-bearing pilot or intermediate artifact before scale. A
  byte-integrity check is not automatically entitled to another multi-day
  recomputation.
- Profile the actual end-to-end DAG before setting caps. Admission uses measured
  pace; a conservative wall cap must not intentionally sterilize usable time.
- Long stages enforce deadlines inside their loops and publish stage, completed,
  total, percent, elapsed, ETA, worker count, and deadline headroom.
- Safe parallel stages should use available cores; GPU use must be justified by
  measured end-to-end improvement, determinism, memory, and transfer cost.
- A deadline may seal the best complete common epoch as explicitly truncated.
  Truncation is valid evidence only when it cannot masquerade as convergence.
- Durable capture/reference/index/cache/checkpoint/calibration artifacts should
  be reusable across a repaired run only when their exact contract permits it.
- Rehearsals exercise every DAG edge, refusal, reopen, and terminal route on a
  small non-scientific population. They may not tune scientific seeds,
  thresholds, architecture, or stopping behavior.
- Review the smallest consolidated source+freeze packet once. Request another
  review only after a load-bearing finding or material byte change.
- Training and calibration may inspect train/calibration splits. Test bytes
  remain closed until a durable readiness record proves every upstream artifact
  independently reopens and the terminal path has headroom.
- A missing/dirty manifest, seed-forwarding failure, hidden leakage, impossible
  world, silent short-work fallback, or unreconciled counter invalidates the
  result regardless of score.
- Negative, incomplete, and resource-failed attempts remain in the ledger with
  their useful artifacts and explicit non-claims. Rigor must prevent cherry
  picking without erasing operational learning.

## Measurement rules

- Use deterministic factories and mirrored deal-seed clusters; report paired
  uncertainty over the actual randomization unit.
- Keep selection and strength separate. Sibling duels/Elo choose candidates;
  only fresh direct comparison against the named champion supports strength.
- Use common hidden worlds inside a fixed comparison and domain-separated RNG
  streams across folds.
- Select a complete multi-seed cohort by the frozen rule, never a lucky seed.
- Bind target, perspective, continuation, state distribution/horizon, ballot,
  encoder, and objective in every checkpoint.
- Report utility primary plus win rate, role splits, and signed advancement
  distribution. Do not replace the primary metric post hoc.
- A local mechanism gain must survive realistic full-round composition.
- A positive point estimate that misses its gate is a clue, not permission.

## Archive boundary

The compact plan above is the current research contract. Detailed v1–v13,
DMC/DMC2, Direct-Q, O0, Teacher T3/T4, S3–S6, H0, high-N, and old artifact
chronology stays in the existing RL archives, `HANDOFF_REVIEW.md`, incident
records, and Git history. The closed BELIEF V1 design set
(`docs_archive/BELIEF_V1_SPEC.md`,
`docs_archive/BELIEF_V1_V2_DESIGN.md`,
`docs_archive/BELIEF_V1_B2_DESIGN.md`,
`docs_archive/BELIEF_V1_B2_RUNBOOK.md`) and
`docs_archive/SUPHX_MICRO_SPEC.md` moved to `docs_archive/` on 2026-09-04.
Their archived paths remain source-bound for reproducible future re-entry.
On 2026-09-05 the closed code lanes themselves (belief, suphx,
douzero_learning_screen, distill, the dead rl lineage, the S0/S3/S4/S5,
teacher, v11, H0, pair-ballot and RLCB campaign scripts, and the early-August
one-off scripts) were deleted from the tree; the tag
`archive/code-lanes-pre-cleanup-20260905` and the `archive/pr-*` tags keep
them, and `docs_archive/PRIVILEGED_TEACHER_V1_PROPOSAL.md` holds the closed
PT1 proposal.  `shengji/teacher_v1.py`, `rl/douzero_micro.py` and
`rl/torch_policy.py` stay because live modules or registry rows import them.
Update this file only when the architecture, estimand, or live decision tree
changes.
