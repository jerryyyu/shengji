# Learning and search research plan

Last reconciled: **2026-09-22 (release 29: the policy/value search with the soft head is
production)**. This document owns the research architecture, the estimands and the decision
tree. `BACKLOG.md` owns priority; live compute and review asks are in `HANDOFF_ACTIVE.md`;
policy names and deployment state are in `AI_POLICIES.md`; immutable receipts and verdicts are
in `HANDOFF_REVIEW.md`; every training run and screen is on the scaling page
(`docs/scaling_log/`) and the search atlas. The retired lines (BELIEF, privileged teachers,
the shortlist-era screens) are summarised once below and live in `docs_archive/`.

## Objective and evidence standard

Build a Shengji policy that is demonstrably stronger than what production plays, under a
correct engine and a reproducible evaluator. Production is release 29: the soft head
`8ecd4fea` served as one NumPy package, its policy head admitting eight candidates over 64
sampled worlds and its value head pricing them, no Monte Carlo playouts in play, value-guided
hybrid bury. The champion for every strength claim is therefore the served release-29 bot,
and from 2026-09-22 every NEW search comparison runs against production W64/K8 (Jerry's
direction, recorded on #436). Historical MC-LCB results keep their original labels; MC-LCB is
no longer the prospective control.

Evidence labels:

- **MECHANICS:** code, legality, parity, leakage, throughput, or rehearsal.
- **OFFLINE:** held-out prediction, calibration, stability, or teacher value.
- **SCREEN:** fresh state or whole-round evidence that selects a design.
- **CONFIRM:** pre-registered fresh mirrored evidence supporting a strength claim.
- **REJECT/SELECT NONE:** the exact registered recipe failed its bar.

The primary policy metric is paired signed level utility per round, clustered by deal seed.
Win rate, role splits, advancement tails and catastrophic losses are required diagnostics.
Offline loss, Brier score, point regret, Elo pools and human agreement never substitute for a
fresh whole-game comparison, and every strength claim goes through `scripts/evaluate.py` with
a bar.

## Operating modes (rigor tiers)

| tier | what it supports | keep | drop |
|---|---|---|---|
| **i — exploratory / DEV** | pipeline works; a model exists; a diagnostic number | score-free until sealed, reproducibility stamp (git SHA, seeds, hashes), receipts | pre-registration, confirmation machinery |
| **ii — selection screen** | choosing between designs | tier i plus a pre-registered comparison, literal parent, matched control | the tier iii machinery |
| **iii — confirmation** | a deploy or strength claim | the full immutable machinery: exact-head freeze, one-shot admission, independent reconstruction, ledger markers | — |

A lane enters tier iii only when a candidate beats the champion on a tier ii paired screen.
Screens run five 520-cluster windows first and extend to ten only when the five-window point
exceeds +0.015 and the interval crosses zero; a five-window null is "not large", not "equal".

## Current program

0. **Production is release 29** (2026-09-22). Evidence chain, in order: the soft head alone
   beats SmartBot under public information (+0.052); as the whole search it beats MC-LCB at
   W16, W32 and W64 in the world-scaling ladder (W64/K8 +0.187 [+0.144, +0.231]; W4 loses);
   vs the release-28 package in card play
   +0.086 [+0.042, +0.131] on 800 matched deals and +0.122 on fresh deals; served with hybrid
   bury vs release 28 as served +0.049 [+0.003, +0.095] over five clean windows (narrow, I²
   49%; a common-opponent, summary-level read, not paired served-vs-served inference). Rollback is one `SHENGJI_BOT` line. The next production claim needs a served-bot
   contrast against release 29 on the same design.
1. **The generation loop (gen-4, #538).** Four runs on the full 20-store corpus, order
   1 → 4 → 3 → 2: run 1 (JS-M1 extended, hard targets) sealed and null as a package, positive
   but not separable from the family in the W64 search; run 4 (soft targets) sealed 09-22
   02:29Z and its served PV-search screen is running (lane v34r4); run 3 (grid trunk, soft, all
   data) training; run 2 (depth 6, soft) armed behind it. Every model goes through BOTH the
   W64/K8 card-play screen vs production and the served/package screen.
2. **Gen-5: data from the search itself (#592).** The release-29 search generates the next
   corpus (`harvest.trajectory` over the pv-search bot: the admitted ballot, the value head's
   means as the soft policy target in their own units, the outcome as the value target, an
   exploration draw from the full legal set that must never displace production's admission;
   reviewed on #597, merging on CI).
   Decisions taken: W64/K8, explore rate 0.1, two stores then a read, MC-LCB stores leave the
   training mix for the SSD after run 2. Data generation yields the boxes to screens.
3. **Search scaling (#577).** Worlds were the lever through 64; the ladder shows no resolved
   gain beyond 64 (W128−W64 +0.024 [−0.034, +0.083], W256−W64 +0.024 [−0.033, +0.081]: not
   equivalence bounds, unresolved); K8 not K16; the T1 value cutoff is a gain over terminal-level MC
   while a learned continuation adds nothing at 68× the cost; bounded PUCT lost at 2× wall;
   depth (one extra trick, heuristic or policy) completed its 3 × 12-pair qualification on the
   cloud against a frozen release-29 card-play control (clean; 0.16 / 0.21 / 2.9 s a move for
   current-trick / heuristic-extra / policy-extra, no fallbacks): mechanics only, no strength
   claim; a 260-pair strength screen (~3.5 h) needs Jerry's word and is not armed.
4. **What would change production next:** a head that beats release 29 on the served-bot
   design, or a search change whose served contrast clears zero. Nothing else.

## What the scaling work taught (models)

Every row is on the scaling page with its receipt; these are the conclusions.

- **Offline loss does not order play.** The best validation CE of the programme (grid S-d4,
  0.6057) played like the leader; a 0.0376 CE gain from the v2 encoder was real in play while
  later CE gains were not. Read val_ce as calibration; the search consumes ranking.
- **Data volume inside the shortlist saturated.** 72k → 96k → 144k → 176k clusters: the last
  full doubling bought −0.0036 CE and no resolved play difference at ten windows (twelve
  proposer swaps all crossed zero).
- **Width and depth alone did not move play** (h256–h2048, d4 residual) at the shortlist
  instrument; the two-head M1 recipe (outcome + search-mean heads) was the only shortlist-era
  model to confirm on fresh deals (+0.021 [+0.004, +0.039]).
- **Encoders:** v2 was the one real gain; v3/v4/v5 bought nothing in play; v5 is closed.
- **Warm-started generations were null as packages** inside the shortlist (gen-1, gen-2,
  gen-3-warm, gen-4 run 1): the shortlist instrument ties 54–62% of deals, so the package screen
  cannot resolve small head differences.
- **The soft target is the ingredient with the largest point estimate** in the head-driven
  search (soft +0.086 vs its hard twin +0.024 on the same deals, paired +0.063 exploratory);
  no head in the W64 family is shown superior to another; a confirmation is owed.
- **Corpus seeds are decks.** A screen window inside a corpus's seed range replays decks the
  trained model saw; ranges are recorded on #436 and excluded per model.

## What the search work taught

- **Model proposes, search decides** (the W32 shortlist, +0.139 on 256 rank-2 deals) was the
  first learned win; K4 beat K8; wider worlds, more final rollouts, adaptive allocation and one
  extra trick of guided depth all failed to add to it.
- **The head as the whole search** replaces playouts: the policy head admits, the value head
  prices, and it beats MC-LCB by +0.095 at W16 and +0.187 at W64 at a fraction of the cost;
  W4 loses. More worlds beyond 64 are not shown to help.
- **Policy head alone is SmartBot-level** under public information; the gap to the search is
  the value pricing, not the prior.
- **Terminal-level MC vs a T1 value cutoff:** the cutoff is the gain; learned continuations
  and PUCT over sampled worlds lose or add nothing at large multiples of the cost.
- **The served read is smaller than the card-play read** (+0.049 [+0.003, +0.095] served vs
  +0.086 [+0.042, +0.131] in card play, on different deals and designs). The served number is
  a common-opponent, summary-level random-effects estimate, not paired served-vs-served
  inference; own declare and bury and the opponent mix are possible explanations for the
  difference, not a measured cause. The deploy gate is the served design.

## Search and teacher strategy

1. **Candidate admission and search cost.** Keep the release-29 recipe as the reference;
   separate exact speedups from policy changes; compute-match controls when a claim is about
   cost.
2. **Depth and allocation.** Test one bounded change against the frozen release-29 control
   before any larger tree recipe; the ballot-rooted PUCT ladder is closed.
3. **Model and teacher transport.** Improve data and targets against the actual consumer (the
   search's own values as the target), preserve held-out deals, then test the resulting head in
   the same search on fresh seeds. Neither a better teacher nor better offline prediction
   guarantees this link.

Measure search work, world quality, consumer decision dose and whole-game utility separately.

## Retired lines (summary; details in the archive)

- **BELIEF R4/R5** (closed 2026-08-31): the offline Brier gain did not survive its label
  control; the DEV consumer showed no policy signal; R5 reopens only on an oracle-belief
  probe. The information contract (public facts / actor-private / beliefs / privileged labels;
  hidden-twin invariance; worlds sampled, never marginals) is retained in
  `docs_archive/BELIEF_V1_*.md` and `docs_archive/rl-plan-through-2026-08-15.md`.
- **Privileged and LLM teachers** (PT0/PT1/PT-Full, Sol/Luna): small or negative transport
  into whole-game play; Luna data retained as evidence, no active lane.
- **Global learned rankers, V11, Direct-Q, T4 widening, S4/S6 mechanisms, C0:** better label
  fit did not transport; none cleared a registered bar. Do not revive unchanged.
- **The shortlist era (releases 22–28)** is condensed in `AI_POLICIES.md`.

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

Trajectory corpora record the generating policy's identity, work and value units per store
(`policy_flags`); a corpus's deal-seed range is excluded from every screen of a model trained
on it (#436). Human data supplies policy diversity and behavioral evidence. Use all trump
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
- An interval overlap is not a difference test; superiority between two arms needs a
  contrast that clears zero on a common opponent or paired deals.
- Five windows first, extend to ten only when the point exceeds +0.015; capped (300 s) and
  uncapped screens are separate populations.

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
