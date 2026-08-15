# RL plan: belief-aware search and learned Sheng Ji

This file is the compact current research plan. It owns the scientific spine,
milestones and evidence standards—not the live queue or run chronology.

- Live priority/order: `BACKLOG.md`
- Fleet state: `JOBS.md`
- Current cross-agent handoff: `HANDOFF_ACTIVE.md`
- Callable policies and terminal synthesis: `AI_POLICIES.md`
- BELIEF contracts: `BELIEF_V1_SPEC.md`, `BELIEF_V1_B2_DESIGN.md`
- Full pre-compaction plan and model lineage:
  `docs_archive/rl-plan-through-2026-08-15.md`

## Objective and evidence standard

Build a policy that beats the exact deployed `mc-s0-report-lcb` champion on
fresh mirrored whole-round signed level utility, then improves against a fixed
blinded human cohort. Search, offline loss, throughput, Elo and human agreement
are intermediate instruments; none alone is a strength result.

Every strength claim binds engine, source, actor perspective, policy, ballot,
sampler, continuation, encoder, split, seeds, work, metric, null and stopping
rule. Screens select one design. Fresh paired confirmation establishes a claim.

## What the closed campaign proved

1. **The report-LCB search guard is a real strength gain.** It is the live
   champion and the parent every challenger must name exactly.
2. **This generation of learned action ranking did not transfer globally.**
   More data stabilized outcome prediction, but T4 global and trick-5+
   protected uses selected none.
3. **Local tactical patches were too sparse or failed composition.** S4 and S6
   selected none; Pair produced no whole-game evidence.
4. **The apparent generic-widening positive is attribution-incomplete.** Its
   null matched treatment work, not champion work: +14.8% accepted worlds and
   +80.9% searches versus champion. A valid confirmation needs champion,
   widening-at-champion-work and widening-at-null-work arms.
5. **Engine speed improved substantially, but strength did not.** Cheaper
   worlds can buy wider search, better continuations or statistical power; the
   performance result itself cannot choose among them.

The program therefore changes axis rather than adding another isolated rule.
The active milestone is BELIEF-V1: improve the hidden-world distribution that
search reasons over, validate it offline, then test it at fixed work.

## BELIEF-V1: tangible outcome

At a play decision, the existing engine has three different kinds of state:

| layer | examples | treatment |
|---|---|---|
| **Public fact / sound deduction** | cards played, current trick, proven suit void, legal follow obligations, declarations that remain logically informative | Enforce exactly. These are not learned probabilities. |
| **Actor-private fact** | the acting player's current hand | Available only to that actor and its search. Never exposed to another seat's model row. |
| **Belief about hidden state** | probability a player has 0/1/2 copies of a card, is short in a suit, retains a higher pair, holds points, can ruff or can beat a current winner | Predict and calibrate from actor-visible history; never label as certain unless mechanics prove it. |

The model does not store one guessed opponent hand. It emits a calibrated
distribution over ownership/count events for each hidden receiver, conditioned
on the public sequence and the acting hand. A later sampler projects those
marginals into complete legal hidden worlds. Search then evaluates the same
actions over better-weighted worlds at the same work budget.

Concrete tactical examples:

- “Seat 2 is out of hearts” is a hard fact only after a legal heart-follow
  opportunity proves it. Before that, point shedding or unusual trump use may
  raise the probability that seat 2 is short, but cannot set it to one.
- “Seat 1 has no pair” is suit- and history-specific. A failed pair response
  can impose a hard cap; declining to feed or choosing a single is behavioral
  evidence only.
- A joker spent when a cheaper trump could win may indicate low remaining
  trump, but the model should express a posterior over trump length rather than
  a hand-coded certainty.
- Feeding points while a teammate is already winning may update beliefs about
  remaining suit length, point inventory and alternative safe feeds. It is not
  itself proof of any one hidden card.

The first consumer is only the world sampler. PointContext already owns
trick-points, points-left and boss-related public context; BELIEF extends that
boundary rather than duplicating it. Learned value, Direct-Q, V11 pairwise
ranking, action allocation and memory-aware rollout policy remain later,
separately gated consumers.

## Current BELIEF state — 2026-08-15

- B0 typed actor/target boundaries, ownership schema and source contracts are
  merged.
- The B2 offline publication source and adversarial witnesses merged to main in
  `959c05d` after exact external PASS at head `3ee0eb8`.
- The repair covers reference-score debiasing, real mechanics derivation,
  history linkage, admission/provenance closure, cross-artifact binding and
  load-bearing mutation witnesses.
- Fresh Mini design `a8c5e05f…1fd53` now binds merged source `959c05d`, the
  105-file source manifest, current runtime/native/boot identity, fixed
  population/caps and an unused evidence namespace. It awaits exact external
  review.
- No evidence root, capture population, candidate training, calibration/test
  opening, sampler or scored run exists. A source PASS or design freeze is not
  execution authority; only the exact design marker may admit B2 once.

## BELIEF milestone ladder

| milestone | output | pass question | authority after pass |
|---|---|---|---|
| **B0 — boundary** | `ActorObservationV1`, separately sealed privileged targets, exact fact/private/belief types | Can hidden twins produce byte-identical actor rows, with no target path reachable by runtime inputs? | Source development only. |
| **B1 — population/design** | Frozen Mini runtime/source/design identities, deterministic actor-only and paired capture plan | Is the population reproducible, sized, leakage-safe and within caps? | One exact B2 pipeline admission after external design PASS. |
| **B2 — offline learning** | Candidate and negative-control cohorts, REF-C reference, mechanics/calibration/behavior reports, one terminal result | Does the learned belief improve held-out proper score beyond a debiased current-sampler reference without leakage or mechanics drift? | If and only if terminal PASS: propose B3 sampler implementation review. |
| **B3 — sampler** | Complete-world sampler that projects learned beliefs while preserving legal constraints | Do sampled-world marginals reproduce the certified belief and improve held-out true-world/value error at fixed worlds? What natural final-decision flip dose results? | One bounded same-work DEV mechanism screen design. |
| **B4 — search screen** | Current sampler vs belief sampler, identical root/continuation/work, shuffled-belief null | Does better belief causally improve decisions, not merely change compute or hide a stronger rollout policy? | One fresh whole-game confirmation design only if dose × conditional edge clears MDE. |
| **B5 — confirmation** | Fresh paired whole-round result versus champion and matched null | Does the complete policy beat production with integrity, role/tail and latency guards? | Promotion review; never automatic deployment. |

### Immediate execution sequence

1. Reopen main at exact merge `959c05d` on Mini; verify clean source, native
   extension, Python/runtime identity and no loadable shadows.
2. Freeze one unused host-specific B2 design without initializing an evidence
   root or opening any split.
3. Obtain one exact-design review marker. The review must authenticate the
   canonical append-only ledger and the frozen runtime/source hashes.
4. Run the consolidated B2 pipeline once under its caps. No retry, seed
   selection, partial population or early test opening.
5. Independently reopen the terminal artifacts and route exactly one result:
   mechanics/leakage refusal, no-learning closeout, or permission to design B3.

## B2 scientific gate

B2 is deliberately offline and asks whether there is real learnable ownership
signal before spending a scored fleet run.

- **Reference:** current constraint-consistent sampler marginals, with the
  finite-world Brier estimation bias corrected consistently in C1/N2/U1.
- **Candidate:** one ownership model family, trained as a fixed eight-member
  cohort; no lucky-seed selection.
- **Negative controls:** history ablation and sealed label permutation with
  explicit control schemas and nonzero dose.
- **Mechanics:** exact conservation, hard-fact respect, target isolation,
  hidden-twin invariance, seat rotation and synthetic small-domain checks.
- **Statistics:** round is the paired/bootstrap unit. Aggregate lift needs a
  positive lower bound and the frozen practical floor; behavior strata may not
  pass vacuously when underpowered.
- **Usefulness boundary:** marginal calibration is not yet a joint-world or
  strength result. B3 must measure projection drift, joint sampling and final
  search-decision dose.

The held-out real hands and kitty are labels only. Training learns from them in
the same sense that supervised vision learns from annotations: runtime receives
the observation, not the answer. Teacher labels should average values over
worlds compatible with the same public observation; disagreement among those
worlds is itself a useful uncertainty target.

## Literature-derived constraints

These systems inform architecture, not authority. Their equilibrium or
perfect-information assumptions do not automatically transfer to four-player
partnership Sheng Ji.

| evidence | durable constraint for Sheng Ji |
|---|---|
| [AlphaGo/AlphaZero](https://arxiv.org/abs/1712.01815) | Separate proposal, value and search roles. Search may teach later models, but each consumer needs its own gate. |
| [Libratus](https://noambrown.github.io/papers/17-Science-Superhuman.pdf), [Pluribus](https://noambrown.github.io/papers/19-Science-Superhuman.pdf), [ReBeL](https://papers.nips.cc/paper/2020/hash/c61f571dbd2fb949d3fe5ae1608dd48b-Abstract.html) | Hidden-information search needs public history plus ranges/beliefs and named continuation strategies. A private observation has no universal strategy-independent scalar value. |
| [Suphx](https://arxiv.org/abs/2003.13590) | Privileged hands may shape a training curriculum, never leak into runtime inference. Decision-type specialization and controlled adaptation deserve separate tests. |
| [DouZero](https://proceedings.mlr.press/v139/zha21a.html) | Direct return learning is a distinct role-conditioned/action-conditioned algorithm. Earlier residual/value experiments do not reject it wholesale. |
| [Student of Games](https://arxiv.org/abs/2112.03178) and cooperative partially observed search | Teammates interpret public actions through a shared policy; preserve actor perspective and continuation identity. |

The first BELIEF head is ownership only because it is the cheapest head to
falsify offline. Value, Q, pairwise and uncertainty heads wait until search has
a belief stack worth distilling.

## Post-null admission rules

A host-day-scale strength run begins only when:

1. natural trigger or final-decision flip dose × conservative conditional edge
   exceeds the intended whole-game MDE with margin;
2. treatment is contrasted with the literal champion and an exact same-work
   null;
3. sign is robust across two named continuations or preregistered natural
   role/phase strata;
4. the design explains how local effects reach whole-game utility without
   cancellation;
5. source plus concrete design use one consolidated review chain where
   possible, followed by one admission and one terminal review; and
6. the result unlocks a named decision, not merely machine utilization.

Compute may run cheap diagnostics and offline calibration in parallel when
their authority and data are disjoint. It must not invent scored work merely
to keep a host busy.

## Search and teacher architecture

| component | current role | next admissible test |
|---|---|---|
| Proposal | Structured, human or learned sources keep legal actions visible. | Three-arm widening attribution before claiming generic widening; no T4/S6 retry. |
| Belief sampler | Generates legal worlds consistent with actor-visible history. | BELIEF B2 offline calibration, then B3 projection/usefulness if B2 passes. |
| Continuation | Plays worlds to terminal or a named horizon. | Memory-aware/MCSmartRoll only after dose × edge and equal-wall economics are frozen. |
| Value/allocation | Truncates or allocates search. | Existing outcome/LEVEL_OBJECTIVE assets require a separate fixed-work gate. |
| Report guard | Protects production from noisy overrides. | Remains the final authority until a challenger beats it fresh. |

Better belief-aware search is also the intended future teacher: it can produce
targets averaged over compatible hidden worlds for Direct-Q or pairwise
ranking. Those learners remain downstream because earlier failures were
dominated by target, information and causal-attribution contracts rather than
raw model capacity.

## Data and evaluation contract

- **Actor-visible input only.** World-generating seeds, other hands and hidden
  kitty bytes are excluded from model inputs even when present in metadata.
- **Encoder identity is data identity.** Bind transitive source and semantic
  versions, not shape alone.
- **Artifact classes stay separate:** state reservoirs, counterfactual teacher
  sets, episodic RL trajectories and human behavior are not interchangeable.
- **Fresh splits:** DEV may develop, CALIB may choose once, REPORT/test remains
  unopened until the predeclared terminal step.
- **Mirrored clusters:** whole-game evidence pairs the same deals and role
  flips; utility is primary and win rate/tails are mandatory diagnostics.
- **Graceful failure:** exploratory artifacts may survive only under a frozen
  missingness rule. Confirmation remains fail-closed when missing work changes
  the estimand.
- **People claim:** a confirmed bot challenger must then improve against the
  same blinded, consented, training-excluded human cohort. Site-average win rate
  is descriptive, not a promotion metric.

## Parked research assets

- V11 pairwise and Direct-Q remain bounded proposal/learner assets, never
  generic scalar leaves.
- MCSmartRoll and LEVEL_OBJECTIVE are existing continuation/value hypotheses,
  not bundled into BELIEF-V1.
- Human actions and S6's bury-side states are proposal/diagnostic sources, not
  truth or execution authority.
- Small exact endgames remain a good privileged-teacher domain; two-card roots
  are the first meaningful action-selection case.
- Pair, S4, S5 and the exact T4 composition are closed. A successor must be
  materially new and pass the post-null admission rules.

## Archive boundary

The full model lineage, T3/T4 lane history, human-data narrative, high-N asset
inventory and older roadmap are preserved byte-for-byte in
`docs_archive/rl-plan-through-2026-08-15.md`. Earlier day-by-day chronology is
in `docs_archive/rl-plan-chronology-through-2026-08-03.md`. Update this file
only when the current scientific plan or evidence standard changes.
