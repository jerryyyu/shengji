# Learning and search research plan

Last reconciled: **2026-10-03 (release 38 live since 09:41 ET: release 36's model, the gen-5 SMV3
outcome head in the release-30 policy/value search, + four search rules; every new screen compares
against release 38)**. This document owns the research architecture, the estimands and the decision
tree. Priority is tracked on GitHub: the board issue #707 (its predecessor #679 is closed and holds everything finished through 2026-10-03), its topic issues, and open issues and PRs (`BACKLOG.md` was deprecated 2026-10-03); live compute and review asks are on GitHub issues and in
`server/scripts/fleet_status.sh` (`HANDOFF_ACTIVE.md` was deleted, #674);
policy names and deployment state are in `AI_POLICIES.md`; immutable authority markers are
in `HANDOFF_REVIEW.md` (frozen to its markers, #674; prose lives on GitHub issues); every training run and screen is on the scaling page
(`docs/scaling_log/`) and the search atlas. The retired lines (BELIEF, privileged teachers,
the shortlist-era screens) are summarised once below and live in `docs_archive/`.

## Objective and evidence standard

Build a Shengji policy that is demonstrably stronger than what production plays, under a
correct engine and a reproducible evaluator: beat the live policy on fresh mirrored whole games with a
single learned model that keeps improving from its own search data, and keep production's latency
tail bounded. Production is release 38 (deployed 2026-10-03 09:41 ET)
on release 36's model: the gen-5 SMV3 checkpoint `3e89e86f`'s outcome head served as one
NumPy package (`smv3out-491ee4bf.npz`) inside the search release 30 served unchanged — its policy
head admitting eight candidates over 64 sampled worlds and its value head pricing them, no Monte
Carlo playouts in play, value-guided hybrid bury — plus, from release 38, four search rules:
admission diversity, refusal-constraint sampling, a points tie-break and lead-anchor (release 37,
2026-10-01, was a phone-HUD fix on release 36's bot). The champion for every NEW strength claim is
therefore the served release-38 bot (Jerry, 2026-10-03: every new screen compares against release 38;
screens already read against release 36 or the combo keep their comparator; release 29/30's reads below are the labeled historical
evidence of the soft head 8ecd4fea, which releases 29–35 served). Historical MC-LCB results
keep their original labels; MC-LCB is no longer the prospective control.

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

## Current program

The work queue and each lane's state are on the board issue [#707](https://github.com/jerryyyu/shengji/issues/707)
(corpus status: row M6); production and its rollback are in `DEPLOY.md` "Current production".

#663 (what to train and screen next) and the data-use audit #667 own the next decision. The
release-30-era program (gen-4 #538 and the gen-5 search corpora #592, both closed; search scaling
#577, parked) is recorded in Atlas v2 (`docs/atlas_v2/registry.json`).

**What would change production next:** a head that beats the production release (release 38 as
served, since 2026-10-03) on the served-bot design, or a search change whose served contrast
clears zero. Nothing else. (The search rules of release 38 are the first search change to do so
since release 29.)

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
- **Policy head alone beats SmartBot after the units fix:** +0.24 vs SmartBot (arm F,
  2026-09-30; through gen 3 it was SmartBot-level); the gain does not show in served play.
- **Admission and selection rules beat tree search here** (2026-10): diversity, refusal-aware
  worlds and a points tie-break on the release-36 search were CONFIRMED in combination and
  lead-anchor on top was POSITIVE incremental (above; not a second confirmation), while PUCT on
  the same package lost (−0.417 signed levels per round vs release 36) and adaptive K16 did not
  resolve. Alone, div, rc and tb were unconfirmed or inconclusive; lead-anchor alone was positive
  exploratory, below the extension triage.
- **Terminal-level MC vs a T1 value cutoff:** the cutoff is the gain; learned continuations
  and PUCT over sampled worlds lose or add nothing at large multiples of the cost.
- **The served read is smaller than the card-play read** (+0.049 [+0.003, +0.095] served vs
  +0.086 [+0.042, +0.131] in card play, on different deals and designs). The served number is
  a common-opponent, summary-level random-effects estimate, not paired served-vs-served
  inference; own declare and bury and the opponent mix are possible explanations for the
  difference, not a measured cause. The deploy gate is the served design.

## Search and teacher strategy

1. **Candidate admission and search cost.** Keep the release-38 recipe as the reference;
   separate exact speedups from policy changes; compute-match controls when a claim is about
   cost.
2. **Depth and allocation.** Test one bounded change against the frozen release-38 control
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
- Use all safe cores for independent work and record the measured scaling; do not stack competing
  heavy jobs merely to report utilization. Optimize the path before scaling the population.
- Opaque multi-hour stages publish progress, active workers and ETA at least every 60 seconds.
- Material nodes are atomic, immutable, idempotently reopenable and resumable; a failure leaves a
  typed diagnostic and preserves completed work.
- Align with the user before a design adds a duplicate multi-hour reconstruction or integrity pass.
  An independent reproduction must answer a meaningfully independent question, not call the same
  implementation again.
- Seal the first interpretable scientific result before optional or independent reconstruction;
  track later verification separately, and a verifier failure must not erase valid datasets,
  checkpoints or sealed results.
- Build and exercise recovery before a one-shot opening. Recovery reuses byte-bound valid inputs and
  completed checkpoints and reruns only invalid or incomplete descendants.
- Rehearse the exact production terminal path, not just training or helper functions: a witness must
  reach the recorded output at the altitude where a regression would matter.
- Do not raise a frozen resource cap merely because the measured projection exceeds it; a cap change
  needs an independent rationale, renewed headroom analysis and explicit review.
- Prefer one optimized critical-path owner; do not keep serial and optimized copies competing for
  hosts unless the fallback has a named, still-useful role.
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
- Five windows first, extend to ten only when the point exceeds +0.015 and the interval crosses
  zero; a five-window null is
  "not large", not "equal". Capped (300 s) and
  uncapped screens are separate populations. Screens are 520-cluster mirrored windows. A five-window
  triage has an MDE80 of about 0.033 on the shortlist-era capped screens and about 0.05 on the
  served policy/value-search screens. Ten shared-control windows are a nominal read, and only
  fresh held-out deals confirm.

## Archive boundary

Closed lanes live in `docs_archive/` and the tag `archive/code-lanes-pre-cleanup-20260905`.
Update this file only when the architecture, estimand, or live decision tree
changes.
