# RL Plan: training a learned Sheng Ji policy

## Objective and evidence standard

The product objective is **maximum verified Shengji strength**, under a correct
engine and a reproducible evaluator. Deployment latency is not a meaningful
tradeoff for the champion policy; compute is still recorded to attribute
experiments and understand operational cost. “Put RL inside search” is a
hypothesis, not the goal.
The first research-superiority milestone—beating deployed `mc-strong` in a
preregistered paired direct comparison—is closed by report-LCB. The next
challenger must beat the confirmed report-LCB champion; pool Elo remains useful
for screening but cannot establish that claim.

Primary promotion metric: paired signed level utility by deal seed. Round
win-rate is secondary; a final deployment candidate gets a mirrored full-game
level-progression check. Every reported number is labelled **HYPOTHESIS**,
**SCREEN**, **CONFIRM**, or **REJECT**. The current fleet is an M4 Mac mini plus
an intermittently available MacBook Air; every manifest records the actual
worker/config rather than treating hardware as part of the claim. Toggle
results live in `AI_POLICIES.md`; run archives in `server/runs/`.

---

## Current synthesis — 2026-08-07 16:15 EDT

This is the current decision layer. The lineage table below owns model history;
**Data and evaluation contract** owns dataset provenance; `AI_POLICIES.md`
owns callable policy conclusions; `BACKLOG.md` owns the live queue; and
`JOBS.md` owns exact run artifacts. Historical evidence does not reopen a
closed lane.

### Champion and search lane

- **Production champion: compiled `mc-s0-report-lcb` (N=30, R=300).** It keeps
  the incumbent MC ballot and selection fold, evaluates the empirical winner
  on a disjoint report fold, and overrides the heuristic only when the
  one-sided paired Student-t lower confidence bound is positive. `mc-strong`
  is the immediate operational rollback.
- **Formal evidence:** S0a measured `+0.353 +/- 0.069` versus `mc-strong`;
  S0b independently measured `+0.357 +/- 0.066`. Fresh RLCB-C1 then confirmed
  the exact production rule over 2,048 new mirrored clusters at
  `+0.338 +/- 0.068`, with a collision-free current-policy null of
  `-0.019 +/- 0.068`. Every registered dose, finite-statistic,
  stream-independence and superiority criterion passed. Canonical aggregate
  SHA-256:
  `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
- **Claim boundary:** this proves one-round paired level-utility superiority
  over `mc-strong`. It does not prove adaptive allocation, multi-round
  progression, or arbitrary changes to N, R, ballot, sampler or confidence
  rule. Equal-work controls showed that extra compute alone did not explain the
  earlier gain. Adaptive allocation added only `+0.037 +/- 0.060` versus
  uniform report-LCB, so the simpler confirmed policy remains preferred.
- **Formal S0 is separately closed SELECT NONE.** S0c provenance refused before
  outcomes could be parsed; its result is unread and nonretryable. Closeout SHA
  `ef0a365…fde9a` and terminal parent `ca556c2` authorize no S0 repair,
  extension or reinterpretation. RLCB-C1 is a fresh experiment, not a
  retroactive repair.
- **More uniform width is not the next lever.** Current-code N=30 beat N=10 at
  `+0.222 +/- 0.140`; N=60 versus N=30 was `-0.002 +/- 0.119`.

### Learned-policy and teacher lanes

- **V11pair remains a useful learned milestone, not a deployable policy.** It
  beat SmartBot 57.7% (277-203, n=480), but corrected direct-v2 failed against
  current search on 2,048 clusters: v11-current `-0.141 +/- 0.070`,
  v11-minus-null `-0.110 +/- 0.070`, and null-current
  `-0.031 +/- 0.068`. The artifact-only repair replayed no games and set
  `protected_composition_authorized=false`. Retain v11 only as a root
  proposal/ranker and teacher diagnostic.
- **Direct-Q 144M is terminal SELECT NONE.** Its gameplay treatment-control
  tail was encouraging (`+0.163 +/- 0.059`, n=256), but seed 1 and both pooled
  role-specific held-out MSE lower-bound gates failed. The registered learning
  screen therefore failed; do not deploy, extend or tune this recipe from the
  inspected positive tail. A future Suphx-style or other role-correct learner
  needs a separately frozen contract.
- **Teacher-v3 is the live strength job.** Canonical action handling, fresh
  capture, diagnostics, exact 64-state freeze and an independent champion-
  continuation audit are code-complete. Air is running eight attribution-only
  Stage-B N=30 gold shards. After all eight validate, seal the Stage-B gate and
  label only the separately frozen 64-state audit. Stage-B outcomes may not
  move the audit population or rule.
- **Suphx O0 is the independent parallel RL gate.** Exact repair `7b15338` and
  corrected material snapshot `9aabf0b` freeze the fixed three-seed
  oracle-acquisition question,
  chronologically legal hidden-hand/burial witnesses, 128 DEV deals, six
  64-update arms, inference, stop rule and sole artifact root. The legal-world
  gate reconstructs post-burial hands and replays every public trick through
  the real engine; this repaired 13 snapshot-plausible alternatives that
  contradicted an earlier pair obligation or successful throw. It still has no
  training authority. The chronology mechanics and exact material snapshot
  passed review; the one allowed freeze produced verified packet SHA
  `6d4e6772…1ed65`, which now needs its separate admission review. Once
  admitted, O0 belongs on Mini while Teacher-v3
  continues on Air. O1 depends on O0 proving oracle acquisition, not on the
  Teacher result; only training that consumes Teacher-v3 labels waits for the
  Teacher audit.
- **Historical DMC2 is invalid evidence, not an RL rejection.** Its defender
  sign, actor immutability and promotion contracts were defective, and it was
  not a faithful AWAC, Suphx or DouZero implementation. Preserve its useful
  alarms, but do not scale or cite its old target path.

### Structured search, data and next decision

- The six-arm DEV-512 ballot screen is closed SELECT NONE. The shipped ballot
  had the lowest equal-work mean regret; CALIB-512 and REPORT remain sealed.
  This rejects the registered designs at that resolution, not all sourcing or
  action-selection improvements.
- Structured bury and sampled exact-endgame code are feature-off. Before either
  spends strength compute, reparent its screen and confirmation to the
  confirmed report-LCB champion. Each mechanism must beat that exact parent;
  any deployment candidate still needs a mirrored multi-round progression
  check.
- Sampler hard validity/support P0 is closed at `aea3774`: 36,000/36,000
  worlds accepted across original, late and deep states, plus exhaustive toy
  support. Posterior fidelity is still a separate, versioned question. Old
  capped-ballot, same-world-selected high-N rows are diagnostics, not oracles.
- High-N and late-ply corpora are replayable state reservoirs. Use them to find
  failure strata and freeze fresh challenges, then generate new strict
  counterfactual labels under a named ballot, sampler, continuation and utility.
  Do not treat corpus size or private-information search as proof of label
  quality.
- **Immediate order:** (1) monitor the shipped production scheduler without
  changing report-LCB semantics; (2) finish Teacher-v3 Stage-B and its frozen
  64-state audit on Air; (3) in parallel, re-review, freeze, hash-admit and run
  Suphx O0 on Mini; (4) let Teacher evidence choose the next teacher-derived
  learner and let O0 independently decide whether O1 feature removal exists;
  and (5) reparent the best structured-search candidate to report-LCB. The next
  strength promotion must beat report-LCB, not the retired MC baseline.

### Settled experiment evidence

| question / arm | evidence that survives | current conclusion |
|---|---|---|
| Root-prior racing | Paired 250-seed confirmation: race4 49.8%, `-0.012 +/- 0.209`; random-prune control 55.4%, `+0.188 +/- 0.224`; MC self-reference 49.6%. This reversed the unpaired screen (54.8% race4 over 2,900 rounds, 49.8% control over 500). | **REJECTED.** Hard pruning did not beat MC or its control. Five agreeing unpaired blocks were correlated evidence, not replication. |
| v7 value leaf | Historical 605-595 (50.4%, n=1,200) used a leaf factory that discarded seeds. The hardened screen was 52.8%, `+0.024 +/- 0.215` versus the MC reference. | No verified edge; retain only as historical initializer/control. Numpy inference remains useful engineering (about 14 ms/decision and torch-identical play). |
| v13 absolute-value leaf | Offline fit improved, but direct paired v13-minus-v7 was `-0.028 +/- 0.185`; train/deploy shifted both ply distribution and ballot. | **NOT CONFIRMED.** Better fit to `Q^Heuristic` did not improve the bot. |
| Standalone learned policy | Across more data, better labels, epochs, margin-aware targets and warm/scratch starts, standalone nets remained roughly 38-48% versus MC. | Pause as a strength-development line; keep as a cheap diagnostic/deployment baseline. |
| gen-v4 flywheel | About two million decisions from 36,360 rounds, teacher `mc-vleaf-v7w-ep02`, fast engine, choice-only `TRACTOR_LOCK` rows retained; recorded `teacher_git` `367a822` predates the banker-search defect. v9 did not produce a stronger leaf or standalone policy. | Clean enough for the historical v9-v11 questions, but not a reason to scale the same teacher contract. Pool-Elo gaps under about 40 are not direct evidence. |
| Rollout-policy replacement | Two superiority tests tied, including one with a roller rated 93 Elo stronger; neither was an equivalence test. | No continuation has been shown stronger. This is not evidence that continuation strength cannot matter. |
| Banker knows its burial | Corrected duel 149-151 = 49.7%, CI [44.0, 55.3]. | No measurable strength effect; retain the information because it is correct. Incident: `incidents/2026-08-03-banker-search-disabled.md`. |

### Durable lessons and operating decisions

1. **Coverage is a contract, not by itself a strength claim.** Historical
   widening moved human-play coverage 84.7% -> 99.3% and produced a 62% screen,
   but DEV-512 selected no redesign. Generate on a wide, explicit ballot;
   freeze its identity through training and deployment; require paired online
   evidence for strength. The old exhaustive-follows mismatch once collapsed a
   deployed net to Elo 798.
2. **Target quality and alignment dominate recipe tweaks.** The historical
   `bc < distill < N=30 < gen-v4` ladder tracked net quality, while capacity and
   temperature sweeps were nulls; soft stochastic-teacher targets were useful.
   v11 worked only when pairwise objective, threshold and deployed ballot
   matched. More precise labels do not repair the wrong estimand, action set,
   continuation or state distribution.
3. **Ask value models one identifiable question.** Warm-start raw-return
   regression collapsed cross-candidate spread `22.5 -> 0.26`; a net rollout
   policy reached 37% versus MC at about 100x cost; the full-information oracle
   explained only 43-47% of outcome variance on its own distribution. A value
   target must name perspective, belief, continuation and horizon. Direct-V
   means a calibrated scoring-bracket distribution or expected signed utility
   under one fixed continuation, never selected `max_a Q`.
4. **Warm starts are safe only under an unchanged objective.** v6->v6.1 was
   stable under the same loss; BC->raw/residual-Q was not. A faithful
   from-scratch DouZero baseline should not inherit a warm-start requirement.
5. **Strength overfits before validation notices.** v6cont's gates fell
   51/41 -> 44/32 while validation agreement moved 0.4 points; snapshots need
   per-epoch strength probes, with historical peaks around epochs 3-8.
   Agreement is a style/sanity metric, not strength: wide-ballot MC gained 12
   head-to-head points while agreement stayed 55% (lead agreement 31% vs 30%).
6. **Small or unpaired samples reverse.** Examples include 55% (n=40) -> 37%
   (n=60) for the v5 hybrid and 54% (n=200) -> 51% (n=400) for
   `PAIR_VOID_BOSS`. Compare only inside one seed batch; game- and round-level
   rates are not interchangeable (historically, 52% rounds was about 88% games
   versus heuristic). Mid-run progress is not a result.
7. **Direct paired duels outrank transitive evidence.** Elo is pool-relative
   (`mc` appeared at 1141/1104/1067 with no code change); sibling duels select
   checkpoints but cannot promote them. Missing seeds, manifests, counters or
   artifacts make a run invalid regardless of its exit code.

Current operating decisions follow from those lessons: no old-contract bulk
RL/data run; three-seed/state-count scaling only after untouched teacher gain;
separate ranking and outcome heads; strict invariants at every silent-fallback
boundary; and one bounded frontend soak before production promotion, tracked
outside this RL plan. The current roadmap below is the executable consequence.

---

## Literature-derived design constraints — 2026-08-04

This is an architecture filter, not a list of famous systems to imitate. The
transfer question is whether a result survives Shengji's four seats, two
cooperating teams, decentralized private hands, combinatorial plays, and
action-dependent information. Detailed run history remains below; this section
states what the external evidence changes now.

| system | useful result | Shengji consequence / non-transfer |
|---|---|---|
| [AlphaGo](https://storage.googleapis.com/deepmind-media/alphago/AlphaGoNaturePaper.pdf), [AlphaGo Zero](https://www.nature.com/articles/nature24270), [AlphaZero](https://arxiv.org/abs/1712.01815) | A policy focuses search, a value model truncates it, and search can generate improved policy targets for the next self-play generation. | This is the right *division of labour*, but those searches act on fully observed two-player states. A scalar observation value plus ordinary MCTS is not a sound direct transplant into hidden-information team play. Use the expert-iteration idea first at the root over a belief distribution. |
| [Suphx](https://arxiv.org/abs/2003.13590) | Human-log pretraining followed by distributed self-play; controlled entropy; separate decision models; privileged-information **policy** curriculum; and per-hand Monte-Carlo policy adaptation (pMCPA). Simple oracle distillation did not deliver the same result. | Faithful tests are (a) gradually remove full-hand features while training the same policy objective, and (b) bounded round-local adaptation over sampled worlds. Our full-information scalar subtraction is not Suphx oracle guiding. Lead/follow, declaration and burial deserve separate heads or models before another monolith. |
| [Meowjong](https://arxiv.org/abs/2202.12847), [Mortal](https://mortal.ekyu.moe/), [Mahjax](https://arxiv.org/abs/2605.20577) | Other Mahjong systems reinforce two practical themes: decision-type specialization and a simulator fast enough that simple on-policy/self-play recipes see enormous, diverse experience. | Split the heterogeneous Shengji surfaces before adding a more exotic loss, and treat native/vectorized simulation as research leverage. Simulator throughput improves the experiment; it does not repair a wrong target or evaluator. |
| [DouZero](https://proceedings.mlr.press/v139/zha21a.html) | Deep Monte Carlo learned action values directly from terminal returns at scale, with explicit action encoding, action-history recurrence, and separate networks for the three asymmetric roles. It did not need inference-time search. | The closest faithful baseline is from-scratch, role-conditioned/action-conditioned Q learning with immutable actor snapshots and direct signed returns. Warm-starting a dueling policy head and regressing an oracle residual is a different algorithm, so its collapse does not reject DouZero. |
| [Libratus](https://noambrown.github.io/papers/17-Science-Superhuman.pdf), [Pluribus](https://noambrown.github.io/papers/19-Science-Superhuman.pdf), [depth-limited solving](https://arxiv.org/abs/1805.08195) | A blueprint plus real-time search can exceed either alone; hidden-information subgames depend on ranges and off-path strategy. Pluribus evaluates leaves against a small portfolio of continuation strategies rather than pretending one scalar continuation is universal. | Keep a fixed blueprint/partner policy during root search and test a small continuation-policy portfolio as a robustness arm. Do not label one heuristic-continuation `Q(s,a)` target a generic value. Poker's equilibrium guarantees do not transfer to a decentralized four-player partnership. |
| [ReBeL](https://papers.nips.cc/paper/2020/hash/c61f571dbd2fb949d3fe5ae1608dd48b-Abstract.html), [Student of Games](https://arxiv.org/abs/2112.03178), [policy search in cooperative partially observed games](https://arxiv.org/abs/1912.02318) | Search in imperfect information needs a public belief/range state and policy-consistent continuation; a private observation does not possess one strategy-independent scalar value. Cooperative search must preserve the policy teammates use to interpret public actions. | The long-term search state is public history plus beliefs over hands and continuation policies. Root determinization with fixed public-information rollouts is a useful approximation; independent per-world MCTS or a v11 relative score used as a leaf is not. |
| [AutoGo](https://evjang.com/2026/04/28/autogo.html#cover) / [repository](https://github.com/ericjang/autogo) | Simple learning loops become productive when experiments are self-contained, fleet jobs are reproducible, and collect→train→evaluate is first made stable synchronously; asynchronous throughput comes later. | Adopt one immutable `ExperimentSpec`, frozen actor/checkpoint paths, bounded automated queues, and machine-readable gates. Let automation schedule preregistered work, never invent a new metric or promote a checkpoint. This is experiment infrastructure, not evidence for one RL algorithm. |

### What this changes in the strength plan

1. **Do not make “MCTS with the RL policy” the primary objective.** The near-
   term champion path is confidence-aware evaluation and allocation on the
   current ballot, followed independently by structured burial and endgame
   search. DEV-512 selected no widening design, so contextual lead expansion is
   a closed screen result rather than an active prerequisite.
2. **Use learned models first where the target is identifiable.** v11pair can
   rank/propose actions on its exact ballot and is the natural alternative to
   SmartBot as MC's protected root anchor. Teacher-v1 should compare the exact
   current ballot, Smart/v11 choices and registered proposal actions, then
   train separate lead/follow ranking surfaces only if untouched teacher
   metrics support them. A value model must name its perspective, belief,
   continuation policy and horizon; otherwise it is not a leaf contract.
3. **Treat rollout-policy uncertainty explicitly.** As a later bounded
   robustness arm, compare the incumbent single continuation against a small
   fixed portfolio (for example current Smart, conservative/tempo, and
   point-aggressive continuations) at equal total work. This is not a claim
   that a stronger standalone roller automatically makes stronger MC.
4. **Run faithful self-play probes, not another hybrid recipe bundle.** One
   Suphx-style privileged-policy curriculum and one DouZero-style direct-Q
   baseline should each get a tiny synchronous shadow run with invariant tests.
   Only a stable learning curve earns fleet-scale asynchronous actors.
5. **Belief-state search is the long-term tree-search lane.** Learn action-
   conditioned card ownership/ranges, calibrate them against held-out hidden
   deals and exact toy posteriors, then search public belief states with a fixed
   continuation-policy portfolio. ReBeL's convergence result is two-player
   zero-sum; Shengji should borrow the representation, not claim the theorem.

### Historical DMC2 was not a valid Suphx or DouZero test

The negative result remains useful as a pipeline alarm, but it is not evidence
against the underlying RL families:

- **There was a defender-perspective sign defect.** `round_value()` and the
  oracle are attacker-perspective. `actor_batch()` signs terminal return by the
  acting seat, but ingestion computes `adv = signed_return - V_attacker` for
  every seat. A defender needs `-return - (-V_attacker)`, not
  `-return - V_attacker`. The unused `seat_l` list is consistent with a missing
  intended sign transform. The executable now records raw attacker return plus
  role sign and computes `sign * (return - oracle)`; antisymmetry is tested.
  This repair cannot rehabilitate the historical learning verdict.
- **The “Suphx oracle baseline” is a different method.** Suphx trained a
  full-information policy and gradually removed privileged inputs. Here a
  scalar value trained on heuristic trick-start states is subtracted from a
  chosen-action regression target at arbitrary decision states. Suphx also
  reported that simple oracle distillation did not work.
- **The “DouZero-style DMC” omits defining parts of the baseline.** It warm-
  starts a dueling CE/distillation network, uses one network across roles,
  compresses history into aggregate card planes, and fits oracle-residual
  targets. DouZero trained role-specific action-value networks from scratch on
  direct episodic returns with sequential history and massive actor throughput.
- **Run integrity was not immutable.** Actor tasks received mutable
  `generator.pt`/`candidate.pt` paths, and a passing gate overwrote the generator
  with the learner's later state rather than the exact candidate it evaluated.
  Workers now receive path+SHA identities, snapshots are atomic and never
  overwritten, promotions use the evaluated bytes, and every actor batch has a
  named seed and ledger entry. The 20-pair/55% legacy gate is still not a
  strength gate. `e49cf60` now closes transactional learner/optimizer/replay
  resume, interruption poison, implicit-global-RNG exclusion, Python-side
  learner/optimizer state and exclusive generation publication.

Verdict: target symmetry and immutable actor/candidate boundaries are now
closed, and a bounded smoke records itself as non-promotable. Preserve the
spread alarm, replay cap, opponent-pool idea and bookkeeping, but do not resume
AWAC or scale DMC2. The next gate is now the concrete Suphx/DouZero algorithm
and its own exact resumed-output test, so a recipe bundle cannot hide which
idea worked.

---

## Model lineage: BC through v13 (authoritative summary)

This section owns the experiment history: what changed, what question it
tested, and what survived. `AI_POLICIES.md` owns runnable policy names and
their current deployment status. Keeping the full ladder in both files caused
model checkpoints, policy wrappers, and search roles to be conflated.
The detailed day-by-day chronology remains in
`docs_archive/rl-plan-chronology-through-2026-08-03.md`.

The early project reused version numbers in three namespaces. **Distillation
v1-v13** below names model/training iterations; **DMC recipe v1/v2** names a
self-play training branch; **ballot v1/v2/v3** names action enumerators. They
are not successive versions of one artifact. Historical pre-v7 gates also
predate the current seeded, paired evaluator and are directional screens, not
promotion evidence.

| model / branch | improvement / hypothesis tested | best evidence | conclusion |
|---|---|---|---|
| **BC baseline** (pre-v1) | Behavior-cloned SmartBot from about 20k rounds using the original 531-dimensional observation and 60-dimensional action encoding. | 89.7% teacher imitation; historical gates 48% vs SmartBot and 29% vs MC. A later play-time ballot expansion sent the same family to Elo 798 until the training ballot was restored. | The encoder carried substantial game signal, but small imitation errors were exploitable by search. Established the ballot/version-freeze requirement. |
| **DMC recipe v1 branch** | Warm-started BC, then regressed raw terminal returns in self-play. This was a self-play branch, not distillation model v1. | Flat 30-34% vs SmartBot over roughly 400k rounds; cross-candidate score spread collapsed `22.5 -> 0.26`. | Closed as an unsafe implementation/target combination: raw-return regression destroyed the pretrained ordering and the degraded policy generated its own data. It did not prove self-play RL cannot work. |
| **distill v1** | Single-Q search distillation with MSE on MC candidate values plus CE on the selected action, on the partial N=10 corpus. | Historical gate 32% vs SmartBot / 22% vs MC. | Dense search labels alone were insufficient under this loss and data scale. |
| **distill v2** | Added a CE temperature to decouple choice learning from raw value scale. | 30% / 27% in the same historical gates. Later `0.03` and `0.10` sweeps did not beat the `0.05` recipe. | No detected standalone gain from temperature tuning. |
| **distill v3** | Split policy and value heads so value-scale movement could not directly define the policy scores. | 32% / 24% in the historical gates. | Architecture separation alone did not solve the noisy stochastic-teacher target. |
| **distill v4** | Added soft value-distribution targets for the stochastic teacher and used the stabilized `lr=1e-3` recipe. | 38% / 32%, a `+6/+8` directional move over v3 in the original small gate. | First useful distillation recipe improvement; soft targets were retained, but the old gate cannot isolate every recipe change or establish strength. |
| **distill v5** | Ran the v4 recipe for five epochs on the full N=10 corpus (about 2.6M decisions in the original ledger). | 42% / 38%; historical pool placed the bare net above SmartBot, while the v5-as-rollout-policy hybrid's 55% preview reversed to 37% in its next small block. | More data helped the standalone student. Replacing heuristic rollouts with the net was both slower and weaker in that test. |
| **distill v6 / v6cont** | Extended the same corpus/recipe to 12 epochs; `v6cont` tested six more lower-LR epochs. | v6 reached 51% / 41% in the historical gates and beat v5 only 54% in a direct n=200 sibling duel. `v6cont` fell to 44% / 32% while validation agreement moved only 0.4 points. | Best pre-v7 standalone checkpoint, but not MC-level. Established per-epoch strength probes: validation loss/agreement did not detect strength overfit. |
| **v6.1 human blend** | Fine-tuned v6 on the small human corpus to test style adaptation without rebuilding the machine-data line. | Human agreement rose about 51% to 57%; direct sibling duel scored 46% vs v6 at n=200. | The blend mechanism worked, with a possible small strength tax. Keep as a style branch, not a strength successor. |

`v12` was never assigned to a model or experiment; the sequence intentionally
jumps from v11 to v13. A version number is not a promotion, and historical
small-n or unseeded results below are labelled as such.

| model | improvement / hypothesis tested | best evidence | conclusion |
|---|---|---|---|
| **v7 / v7w** | Same dueling policy-plus-value architecture, but trained on the lower-noise N=30 `distill_n30` teacher corpus. `v7w` warm-started v6; the scratch v7 arm was stopped early. | v7w won the sibling-selection duel against v6 (best snapshot 64.5%) and was selected as the next initializer. Those family duels did not establish strength against MC. The old v7-leaf “50.4%, n=1,200” settling run predated the seed-forwarding fix; in the current hardened screen the v7 leaf control was 52.8%, `+0.024 +/- 0.215` paired utility versus the MC reference. | Lower-noise labels produced a useful successor checkpoint, not a verified MC improvement. Retain v7w as the historical initializer and leaf control only. |
| **v8 family** (`v8a`, `v8b`, `v8along`) | Moved to the larger `gen_v3` corpus and fixed the trainer so choice-only TRACTOR_LOCK rows were no longer discarded. A was the raw-value soft-target control; B added the acting policy's +5 candidate-0 margin to the policy target while leaving the value head absolute; A-long tested 12 epochs. | Margin-aware B raised held-out teacher-choice agreement from roughly 43% to 62.5%, proving the loss/metric mismatch was real. The strength anchors were run before the stochastic-opponent seeding repair and did not show a reliable gain; longer A training and the v8 value-head screen also showed no detected benefit. | Important data-contract and target-alignment fix, but no promotable strength result. Better imitation alone did not imply a better bot. |
| **v9 warm / scratch** | Trained on `gen_v4`, whose teacher was the v7 value-leaf hybrid; directly tested warm versus random initialization and then extended both arms to 16 epochs. This was the first flywheel attempt: train on the hybrid teacher, then reuse the new value head in the hybrid. | Warm and scratch had no detected difference after six epochs. In later n=120 screens both peaked near epoch 8 and then weakened; the logged warm arm was 56% vs Smart / 37% vs MC and scratch 47% / 33%. A v9-leaf head did not improve on the v7 head in the same small screen. | No evidence that warm start, more epochs, or one expert-iteration turn improved strength. The negative result is about this pipeline, not proof that expert iteration cannot work. |
| **v10res** | First residual override attempt: regress `Q(s,a_i)-Q(s,a_0)` and let SmartBot's candidate 0 stand unless predicted gain clears a threshold. | It overrode only about 1.3-1.5% of states where the teacher overrode about 15%; pairwise RMSE was 6.1995 versus 6.2112 for predicting zero, and it scored 47% vs Smart in its screen. The model still scored rows independently without a pairwise loss, train/play ballots differed, training and deployment read different heads, and the registered epoch initially differed from the evaluated one. | **Invalid test of the residual-learning hypothesis.** The checkpoint was a near no-op; do not count it as evidence that residual learning failed. |
| **v11pair** | Corrected v10 around the deployed decision: optimize `(q_i-q_0)` against `(Q_i-Q_0)` with Huber loss and boundary weighting, use the exact valued ballot at inference, and fit the 0.02 threshold on one split before reporting another. | `rl-override-v11pair` **CONFIRMED** 57.7% vs SmartBot (277-203, n=480, two disjoint blocks). Its 51.1% vs MC over 4,880 rounds used MC factories that silently discarded seeds. The later clean 2,048-cluster current-MC block was strongly negative (`-0.132 +/- 0.070`), but exact source audit showed it inferred with a banker-private-kitty encoder never seen in training; it validly rejects that implementation and is not a clean model ablation. Gating/root racing were not confirmed; pairwise deltas are invalid as scalar leaves. | The only confirmed online gain in v7-v13, and the key lesson is exact objective/ballot/encoder alignment. Keep it as a direct override or root proposal/ranking candidate; it has not beaten MC. A corrected-encoder direct rerun is required before the learned hypothesis receives a current-contract verdict. |
| **v12** | No model, checkpoint, or experiment used this number. | — | Skipped; do not infer a missing failure. |
| **v13abs** | Warm-started v7w and fit the value output to absolute 240-world means from 20,845 high-N states, using inverse-variance weighting. The actual target is raw-point action value under heuristic continuation, `Q^H(s,a)`, not a generic state value. The trainer updated the whole network, not only a detached head. | Offline SCREEN: unweighted RMSE improved `0.1052 -> 0.0699` and stored-ballot regret `1.478 -> 1.293`. Online leaf SCREEN: v13 and v7 each won 52.8%; v13 was `-0.004 +/- 0.206` versus the MC reference and v7 `+0.024 +/- 0.215`. The direct paired v13-minus-v7 contrast is **`-0.028 +/- 0.185`** (250 clusters). There were two train/deploy shifts: early-state and ballot mismatch. A later byte audit adds a third, terminal defect: `highn_train.py` consumed `rl_data/highn_enc`, whose 5,923 banker rows all use the private-kitty drift. | **INCOMPATIBLE / NOT CONFIRMED.** It learned contaminated offline tensors better but did not improve the bot. Rebuild `highn_enc`, retrain and freshly evaluate any successor; the existing checkpoint cannot become valid merely by regenerating the cache. This does not rule out a correctly targeted absolute-value model. |

The progression is therefore not “each version got stronger.” v7 reduced
teacher noise; v8 repaired the data and behavior-target contract; v9 tested
initialization, duration, and one flywheel turn; v10-v11 showed that an
implementation can make a valid hypothesis look inert until the trained
quantity and ballot exactly match deployment; v13 improved supervised fit but
exposed a state-distribution and value-contract mismatch. No v7-v13 model has
shown a verified advantage over the deployed `mc-strong`; v11's confirmed gain
over SmartBot is the one positive learned-policy result.

Before any v14-style leaf experiment, checkpoint metadata must name and assert
the target, perspective, continuation policy, state sampler/horizon, ballot
version, and encoder version. A mismatch is an invalid run, not a negative ML
result.

---

## ROADMAP FROM HERE — strength first, correctness as a gate

1. **Test the implemented S0 confidence-aware search.** The sanitised incident
   keeps `SAAK` as candidate 0 while two named N=30 streams choose `DJ`. S0 now
   separates incumbent point-margin 5 from report minimum-gain 0, nominates on
   N=30 worlds, and tests the fixed pair on an exact independent R=300 fold.
   It includes deterministic/random adaptive selection, an equal-total-work
   uniform control, exact counters and replayable decision logs. The clean
   first-150-DEV / first-20-override calibration found 12 positive N=300 gaps,
   mean +0.570; its predeclared grid selected R=300. Run S0a (report mean vs
   report LCB vs extra uniform compute), then S0b allocation only for the
   selected rule, then an independent 8,192-cluster paired current/null
   confirmation. Because the historical null has a lag-17 cross-cluster RNG
   dependency, terminal interpretation additionally requires the pre-outcome
   frozen score-blind 18-input seal and two collision-free 4,097/4,095-seed
   color gates; the original iid aggregate cannot close S0 alone. That closes
   the S0 research milestone. A confirmed candidate
   still receives a separately registered full-game progression/stress check
   before product deployment; do not pool that product check into S0 evidence.
2. **Build a teacher that can exceed the old teacher.** Follow
   `TEACHER_V1_SPEC.md`: mechanics first, then a gold continuation-quality gate,
   then generate a 2,048-state pilot outside every evaluation split, balanced
   by phase/role/lead-follow/
   candidate count/disagreement. Store 512 common worlds per action, per-world
   terminal points and signed scoring bracket, exact ballot/sampler/
   continuation identity, paired uncertainty and counters. Use a strong or
   exact-late gold subset to validate the cheap continuation before scaling;
   require the cheap-selected action's gold-regret 95% upper bound to stay at
   or below 0.10 signed levels, otherwise relabel with the stronger
   continuation rather than training a more precise imitation of a bad target.
3. **Train for the deployed decision and for calibrated outcome separately.**
   Use a v11pair-style pairwise/listwise ranking head on exact candidates plus a
   separate scoring-bracket distribution head. Train three seeds and state-count
   curves. First test the model as an MC ranker/pruner/allocator; only an
   untouched teacher gain and fresh paired win earns direct override or a 10k/50k
   relabelling wave.
4. **Run faithful self-play that is not bounded by MC imitation.** Role-sign,
   immutable actors and the checkpoint primitive pass; close interruption,
   global-RNG and Python-side learner-state behavior next, then
   run short synchronous Suphx-style privileged-feature-removal and DouZero-
   style role-conditioned direct-Q baselines. Stable
   action spread plus held-out improvement earns fleet scale and opponent-pool
   iteration. AWAC may optimize the valid replay later; it cannot repair a bad
   target.
5. **Attack two orthogonal game decisions.** The feature-off structured-bury
   core and authored 512-state runner use disjoint reporting plus exact equal-
   work legacy/random controls; accept the runner only after its verifier
   redraws named worlds and replays every raw score. The feature-off
   exact-endgame core now exhaustively solves <=4-card determinized worlds,
   refuses hidden-state/budget boundary violations and shares one context-safe
   solver/cache per common world. Its frozen cumulative 250k-node challenge
   completed 140/140 frontiers with zero refusal/overflow; next register the
   terminal-champion-matched feature-on policy and full-game screen. Freeze
   targeted strength references only after those gates, then duel the
   terminal production champion directly. No S3 strength result exists.
6. **Keep the closed sampler P0 out of the critical path.** The clean current
   original/late/deep certificate passed with zero accepted-path loss.
   Posterior research remains separately versioned; it must not consume the
   strength budget unless a policy experiment depends on it.
7. **Operate the flywheel AutoGo-style.** Every run gets one immutable
   `ExperimentSpec`: hypothesis, code/data/ballot/encoder hashes, frozen actor
   paths, budget, primary metric, null and stop rule. Keep collect→train→evaluate
   synchronous until replay/resume is exact; only then let a dispatcher fill
   the fleet from a preregistered queue. Promotion remains a separate human-
   visible paired gate.

## v11pair utilization plan — preserve the milestone, test the missing role

The project did not literally leave v11 unused: direct override, search gating,
hard root-prior pruning and an invalid leaf configuration were exercised. But
none tested the composition most directly licensed by its confirmed 57.7%
result versus SmartBot. Production MC treats SmartBot's action as candidate 0
and protects it with a five-point margin. A thresholded v11 action can replace
that **anchor** while keeping the entire ballot and every N=30 rollout.

This differs from the closed arms:

- racing deleted actions before MC; the anchor hybrid deletes none;
- gating decided whether to search; the anchor hybrid always runs equal N=30;
- a leaf needs comparable values across states; an anchor needs only v11's
  valid within-state ranking.

Execute in this order:

1. Preserve the completed v1 aggregate exactly. On 2,048 fresh 121M clusters,
   the frozen NPZ (`cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003`)
   failed against current compiled `mc-strong`: `-0.132 +/- 0.070`; its matched
   null contrast was `-0.159 +/- 0.069` and the true null was sane. The block's
   source used the drifted banker encoder, so the verdict rejects that exact
   deployed composition and cannot adjudicate corrected checkpoint semantics.
2. Run one fresh versioned direct block under `OBS_SCHEMA=rl-observation-v1-public-no-private-kitty`
   and the `66aad44` transitive source digest, on disjoint seeds with the same
   true-null and accepted-dose contract. Do not pool it with v1 or overwrite
   v1's stored authorization bit.
3. Keep both direct verdicts separate from the blind composition protocol in
   `7ecffd5`. After a corrected direct block is protocol-valid with a sane null,
   wait for terminal S0 and screen the exact champion-matched
   anchor on 2,048 fresh 137M clusters even when standalone v11 is neutral.
   This asks whether search filters v11's costly tail; it does not reinterpret
   standalone evidence.
4. In that screen, preserve the terminal champion's complete ballot/world/work,
   report and allocation contract. Compare v11 anchor, same-trigger random,
   literal champion and champion-matched null. Require all three anchor LCBs
   >0 and a null interval containing zero. Only PASS admits the independent
   8,192-cluster 138M confirmation; only confirmation can reach deployment
   review.
5. Once the adaptive estimator is valid, test a soft v11 priority after a
   common-world floor against uncertainty-only and random priorities. Do not
   revive top-k pruning.
6. In teacher-v1, retain frozen v11 as a baseline/disagreement miner and train
   a `v11.1` pairwise/listwise successor with a separate bracket head. Compare
   warm-start and scratch; deploy first as anchor/ranker/allocator.

Using v11pair as a rollout **policy** is semantically valid because it chooses
from each acting seat's observation; using its relative score as a leaf is not.
Teacher-v1 Stage B should first measure whether v11 continuation changes gold
rankings usefully. Earlier Smart/v5 rollout-policy ties make this a bounded
secondary test rather than the first fleet bet.

## Data and evaluation contract

Old distillation spent compute **horizontally**: roughly 1-2 million sequential
self-play decisions received low-dose N=10/N=30 or hybrid-teacher labels. That
bought trajectory coverage, but close choices stayed noisy, early play was
overrepresented, and the targets were locked to the collection ballot and
sampler. New compute must instead buy deeper common-world comparisons on a
frozen deployment contract, followed by untouched and online tests.

**Encoder identity is data identity.** Encoder v1 is now explicitly
`rl-observation-v1-public-no-private-kitty`: even a banker observation must be
invariant to which legally hidden cards occupy the kitty. Its implementation
identity combines both `rl/encode.py` and `ai/memory.py`. The August 3 Memory
default change silently violated that contract without changing `ENC_VERSION`;
`66aad44` restores it and adds a counterfactual banker test. Never admit an
encoded shard or inference result merely because its vector dimension/version
matches. Require the combined implementation digest or producer git/source
provenance that proves equivalent semantics. Assets generated in the drift
window are quarantined until that audit is explicit; historical v11 training
metadata predates the change and is compatible with restored v1.

`highn_corpus` spent compute **vertically** instead. It rebuilt 20,845 fixed
states, evaluated every offered action over 240 shared hidden worlds, and
stored action means, candidate-0 paired differences, uncertainty estimates and
the raw state needed for replay. Common worlds make close actions much easier
to compare than independently sampled labels. This was a useful diagnostic
shift: it exposed the early-ply skew and selected-maximum problem, and
localized a diagnostic surface to lead decisions.

It did **not** create a final oracle. Those labels use the pre-repair non-strict
sampler, the old finite ballot, raw points, heuristic continuation and
same-world selected maxima; the state distribution is overwhelmingly early.
They estimate the specifically named quantity `Q^Heuristic(s,a)` under that
contract, not generic state value or expected level utility. v13 fitting these
labels substantially better offline without improving online is the durable
warning: **higher precision cannot repair the wrong estimand, action set or
state distribution.** Keep high-N as a replayable reservoir and provisional
diagnostic set, not the foundation for an unqualified bulk retrain.

### Historical high-N workbench — diagnose, never promote

There is one comparison the old labels support more cleanly than “regret to
the selected high-N best.” A policy trained independently of this artifact can
choose one stored action, then be compared directly with stored candidate 0 on
their 240 common worlds. The action pair is fixed before these labels are read,
so this avoids selected-maximum winner's curse. It still measures only
historical acting-team raw-point `Q^Heuristic`, not game strength.

`scripts/highn_v11_audit.py` applies that contract to frozen v11pair:

| DEV reservoir | rows / deals | override rate | v11 minus Smart, raw `Q^H` points per decision | harmful / >2 paired-SE harmful overrides |
|---|---:|---:|---:|---:|
| original high-N | 12,340 / 3,085 | 12.4% | `+0.397 +/- 0.037` | 18.0% / 8.9% |
| later-ply supplement | 7,292 / 1,823 | 13.4% | `+0.334 +/- 0.047` | 25.7% / 12.9% |

Both runs rebuilt with zero errors and current Smart matched stored candidate 0
on every row. The apparent v11 signal survives the shift into mostly mid-game
states, but the loss tail gets worse. That is consistent with its confirmed
win over Smart and with the earlier observation that v11 hits often but misses
expensively. It strengthens the case for an MC anchor that can correct the
tail; it does not prove the anchor works, because stored means cannot simulate
a stochastic N=30 decision. It also explains why blindly lowering the v11
threshold was the wrong use of this corpus.

The lead diagnosis is now more specific. The old selected-best table and the
independent human coverage audit both pointed to leads, but DEV-512 showed that
naive widening did not improve selection. In the fixed-pair audit v11's
original-corpus lead overrides are positive on average (`+0.515 +/- 0.065`),
yet their action-type tails differ sharply: non-point-single to pair is strong
in this surrogate, while point-single to pair and single to tractor are noisy.
Those post-hoc archetypes are hypothesis strata, **not deployable filters**.

### Artifact boundaries and clean-teacher sequence

The inspected high-N rows may only diagnose and generate hypotheses. Mine DEV
at no more than one state per deal into named strata (clear v11 wins/losses,
threshold disagreements, high paired-SE choices and lead transitions), preserve
every denominator, and leave old CALIB/REPORT assignments uninspected. Freeze
any resulting state-selection rule, then apply it to **fresh non-evaluation
deals**; never fit a production filter or successor on the mined rows. The
original corpus has zero true-late DEV decisions and the supplement only eight,
so the frozen deep-lead reservoir supplies missing state coverage, not labels.
Old clear-loss rows may remain regression/challenge fixtures, but not a
promotion set. Do not rerun all 37.1M historical evaluations, refit another
threshold to their surrogate, or train a generic leaf from them.

Keep three artifact classes separate:

1. A **state reservoir** stores reconstructable setup/history and a frozen
   deal-disjoint assignment, but no action scores. The frozen deep-lead capture
   is such a reservoir, not training data.
2. A **counterfactual teacher set** fixes the ballot, belief sampler,
   continuation policy and utility target, then evaluates every compared action
   on common proposal worlds with disjoint report worlds. It stores raw
   per-world returns or sufficient paired statistics, not only a selected
   action.
3. An **episodic RL set** stores immutable actor identity, role-correct signed
   terminal returns and sequential public/action history. It must not be mixed
   with search-distillation rows as though their targets were interchangeable.

Teacher-v1 earns scale in this order:

1. retain the closed hard-validity/support certificate and explicitly version
   any posterior weighting;
2. pass the 64-state mechanics and 128-state gold-continuation gates;
3. freeze a fresh, non-evaluation, deal-disjoint selection rule with explicit
   early/mid/late, role, lead/follow, candidate-count and disagreement coverage;
4. relabel the union of the exact current ballot, Smart choice, frozen-v11
   choice and registered proposal actions with common proposal worlds,
   independent report worlds and signed scoring-bracket outcomes;
5. train separate ranking and calibrated-outcome heads across three seeds and
   state-count curves; untouched teacher metrics must improve before a
   10k/50k collection wave;
6. preserve REPORT for one selected design, then require fresh paired games
   before calling the new data strength-producing.

Every generated dataset must name and digest its state-selection rule, split,
`BallotSpec`, engine, sampler, continuation policy, target/perspective, world
budget, generator and source checkpoint. Incompatible shards are never merged
silently. Corpus size is not progress by itself; progress is lower untouched
decision regret under the deployment contract followed by verified online
strength.

### Frozen evaluation assets — rebuilt from disk 2026-08-05

These assets are **not training data**. DEV may select one design and CALIB may
judge that frozen design once; neither may be pooled into a teacher corpus.
Because DEV-512 selected none, its CALIB and REPORT assets remain sealed. Any
new teacher or strength audit receives a separately versioned split.

| artifact | size / identity | what it is | status / allowed use |
|---|---|---|---|
| `rl_data/deep_leads.v1.jsonl` + `deep_lead_split.v1.json` | 768 raw lead states; 256 each DEV/CALIB/REPORT; 48 split/trick/role cells x16; data hash `ffccfde64932eb3a` | Reconstructable state reservoir captured before ballot scoring. It supplies the late/deep coverage missing from the older corpora. | **FROZEN reservoir.** May build registered evaluation sets; never train from split identity or inspect REPORT outcomes. |
| `rl_data/pilot_dev512.v6.json` | 512 unique deals; hash `af78748586034f6f`; bands 170/171/171; size 0/72/98, 11/131/29, 152/19/0; roles 85/85, 86/85, 86/85; source 129/41/0, 17/154/0, 0/1/170 | DEV worksheet for the lead-ballot design screen. Frozen from clean `53d9b67` by a fail-closed freezer: size drives deal selection, and a shortage or replay error publishes nothing instead of a short file. | **512/512 SCORED; SELECT NONE.** Eight clean shards at `884030f`, strict aggregate reproduced; no design advanced and this asset may not train a model. Supersedes v5 (`097ea3851cd3bb9c`), whose marginal-cell dedup moved 52/512 exact DEV states under row reversal. v3/v4/v5 remain named negative controls. |
| `rl_data/pilot_calib512.v6.json` | 512 unique deals, disjoint from DEV; hash `3872350f57a4dd60`; identical band/size/role allocation | Untouched holdout to judge exactly one frozen DEV-selected design. No action labels or scores. | **UNTOUCHED.** Do not tune, train, or score. Supersedes v5 (`00ca4de1915d8c4f`). |
| `tests/data/s0_override_audit.v1.json` | 150 frozen DEV decisions; first 20 actual N=30 overrides each carry all 300 fresh signed paired deltas; SHA-256 `9703b50817fb03622c3739e44f73e19083b1e8337300be7054774e2308e13ef5` | Reproducible calibration/challenge asset for report-fold dose and both-role override semantics. It selected R=300 by a committed rule. | **INSPECTED DEV DIAGNOSTIC.** May regression-test S0 mechanics and dose identity; never a strength result, promotion set, generic teacher or training corpus. |
| Mini `runs/logs/s0a-v1.aggregate.json` | 2,048 mirrored clusters, seeds 132,000,000–132,002,047; SHA-256 `0fcd53d4f782a705bfef9ea8ec6155c49db45d76ec71ce25891a9f864413de49` | Fresh decision-rule mechanism screen: report-LCB +0.353 +/- 0.069 versus current and +0.293 +/- 0.066 versus equal-work uniform; null flat. | **SEALED / REPORT-LCB SELECTED.** Non-promotable parent for S0b only; not training data or deployment evidence. |
| Mini `runs/logs/s0b-lcb-v1.aggregate.json` | 2,048 mirrored clusters, seeds 134,000,000–134,002,047; SHA-256 `25c0177e27c0e185e96701ad788313a7ea14b892e24586186df02466bf144803` | Fresh allocation screen under report-LCB: report-uniform replicated at +0.357 +/- 0.066 versus current; adaptive added unresolved +0.037 +/- 0.060. | **SEALED / ADAPTIVE SELECTED BY REGISTERED POINT ESTIMATE.** Parent for exact S0c-adaptive-LCB only. Shows report-rule replication, not measurable allocation benefit; never training data. |

The completed screen's primary 95% half-width was 0.337. Holding that
variance fixed, 2,048 comparable states would narrow it only to about 0.169,
and roughly 5,800 would be required to resolve a 0.10 regret effect. The right
response is therefore **not** to append to inspected DEV-512 or cycle more
ballot arms through it. Preserve it as a negative design worksheet. The new
2,048-state `teacher-v1` proposal is a different asset: non-evaluation states,
much deeper common-world counterfactual labels, per-world outcomes and an
iterative training purpose. It may grow to 10k/50k only after held-out teacher
metrics and fresh paired games show that its learned mechanism improves the
champion. A final strength claim receives its own fresh-seed power calculation
and full-game confirmation, as required by `BALLOT_PLAN.md`.

### Historical training-data inventory — rebuilt from disk 2026-08-04

| dataset | size | what it is | teacher | used by |
|---|---|---|---|---|
| `rl_data/highn_corpus_all.jsonl` | 20,845 states / 31 MB / **37.1M candidate evaluations** | each old-ballot candidate scored over 240 shared worlds, with marginal and candidate-0 paired SEs; raw states rebuild exactly. Non-strict sampler, same-world max selection, overwhelmingly early states, and raw-point labels | MCBot N=240, heuristic continuation | rebuildable state reservoir; provisional `Q^Heuristic(s,a)` labels for fixed-pair diagnostics, **not** an unbiased oracle, bracket target, or generic state value |
| `rl_data/highn_enc` | 20,845 encoded rows; 5,923 banker / 14,922 nonbanker | **ENCODER-CONTAMINATED.** Byte replay against the raw high-N JSONL found every banker row matches only the August-3 drifted private-kitty semantics; nonbanker rows are unchanged. `enc_version=1` did not detect the semantic change. | derived encoding only | **QUARANTINED; regenerate from raw under the `66aad44` public/no-private-kitty schema before any training.** Raw high-N labels/states are unaffected. |
| `rl_data/highn_late_air.jsonl` | 12,000 states | same historical N=240 label contract, captured after a minimum-play threshold. The DEV audit is mostly teacher-v1 mid-game: only 8/7,292 rows reach trick >=12 | MCBot N=240, heuristic continuation | distribution-shift/fixed-pair diagnostic and raw reservoir; does **not** supply clean true-late labels |
| `rl_data/gen_v4_all` | 205 shards / 245 MB / **~2.05M decisions** | the current corpus: hybrid-teacher values, wide v2 ballot, TRACTOR_LOCK rows recorded as choice-only. Provenance in META (`teacher_git` 367a822) | `mc-vleaf-v7w-ep02` | v9warm/v9scratch, v10res, **v11pair** |
| `rl_data/gen_v3_all` | 162 shards / 276 MB / ~1.62M | first fast-engine generation; superseded by gen-v4 | upgraded MCBot | v8a/v8b |
| `rl_data/gen_v3_quarantine` | 4 shards / 24 MB | **CONTAMINATED — never merge.** Written by orphaned workers running buggy code for 10h | — | nothing, deliberately |
| `rl_data/distill_n30` | 24 shards / 102 MB / ~1.2M | low-noise N=30 search distillation | upgraded MCBot | v7, v7w |
| `rl_data/distill` | 36 shards / 158 MB / ~1.8M | original N=10 distillation | MCBot (pre-CONTROL_LEADS) | v4, v5, v6, v6.1 |
| `rl_data/bc` | 35 shards / 160 MB / ~1.75M | SmartBot behaviour cloning, no values | SmartBot | ckpt_bc |
| `rl_data/oracle` | 1 shard / 10 MB / ~322k | full-information states + outcomes | self-play | oracle value study (43-47%) |
| `rl_data/human_v4/v5/v6` | 1,850 / 2,061 / 2,169 decisions | **ENCODER-CONTAMINATED.** Byte classification found 509 / 551 / 551 banker rows with private-kitty semantics; all remaining rows are nonbanker-invariant. Raw replay is currently available for 1,592/1,850 v4 rows and all v5/v6 rows. | live humans | **QUARANTINED; rebuild from raw under restored v1 before training or new agreement claims.** Historical policy-as-run diagnostics remain historical. |
| `../logs/*.jsonl` | 26 games | raw human corpus source, rebuildable in seconds. Local test games live in `logs/local/` (17) and are NEVER mined | live play | audits, miner |

Two asymmetries still hold: the quality ladder bc < distill < n30 < gen-v4
tracks net strength, and the human pile is ~1,000x smaller but the highest
signal per byte. The v1-ballot bias critique no longer applies to gen-v3/v4 —
both carry throws, component combos, and choice-only lock rows.

---

## Measurement rules (non-negotiable)

- Mirrored deal-seed clusters everywhere, with deterministic factories and an
  immutable manifest. Report paired/clustered uncertainty and signed level
  utility; a raw round count or Wilson interval over correlated flips is not a
  confirmation. Small n is a SCREEN only.
- **Strength vs selection (v7w lesson, 2026-08-02):** net-vs-net sibling duels
  and Elo pools select checkpoints; they do not establish a ladder claim.
  Descendants exploit ancestors (v7w beat v6 64.5% yet stayed near v6 on
  anchors). Legacy distillation snapshots may still use the fixed-seed n=60
  Smart probe plus n=200 sibling duel, but both are SCREEN diagnostics.
- Strength requires a fresh direct paired comparison against the named deployed
  champion and registered controls. Promotion requires the declared
  superiority/non-inferiority gate plus a full-game mirrored match.
- A run with a missing/dirty manifest, reused output, seed-forwarding failure,
  impossible sampled world, silent fallback, or unreconciled counter is INVALID
  regardless of its score.
- Negative results are archived, not deleted (`server/runs/` and the
  `AI_POLICIES.md` experiment log).

---

## ARCHIVE

Day-by-day chronology moved to `docs_archive/rl-plan-chronology-through-2026-08-03.md`
(2026-08-03). Current conclusions live in the synthesis and lineage above; the
archive records how they were reached, including the dead ends.
