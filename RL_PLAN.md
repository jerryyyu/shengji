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

## Current synthesis — 2026-08-09 13:35 EDT

Exact terminal numbers and SHAs live in the canonical table at the top of
`AI_POLICIES.md`; `BACKLOG.md` owns live order. This section records only
what those results change in the research plan.

### State of play

- **Champion:** compiled `mc-s0-report-lcb`. It uses N=30 to nominate a
  challenger, re-evaluates that fixed pair on a disjoint R=300 common-world
  fold, and overrides only on a positive conservative LCB. Three independent
  blocks were positive, including fresh RLCB-C1 confirmation with a sane null.
  More uniform width and adaptive allocation have not established an
  incremental benefit.
- **Formal S0:** terminal SELECT NONE because its evidence chain failed before
  corrected outcome parsing. Its unread population is nonretryable. The
  independent RLCB-C1 result, not S0 reinterpretation, supports production.
- **Learned policies:** V11 direct-v2, Direct-Q, Suphx O0 and its O0-v2
  shared-public-CRN successor all selected none.
  These are different failures: V11 lost directly; Direct-Q's gameplay tail was
  positive but held-out role learning failed; O0 learned an aggregate
  oracle-public edge but failed seed robustness and stayed nearly uniform;
  O0-v2 repaired coupling and replay semantics but measured control
  oracle-minus-public at only `+0.015` with LCB `-0.067`, while its isolated
  margin-sharpening cell was worse at `-0.047` with LCB `-0.109`.
  V11 survives only as a bounded proposal/ranking/teacher diagnostic.
- **Teacher:** Stage B passed on sampled ordinary states. The first sealed
  64-state continuation audit refused operationally before publishing a label
  or gate, so it produced no ML verdict and is nonretryable. Score-free
  diagnostics, bounded unscored-retry semantics, the untouched complement and
  a fresh one-shot controller subsequently passed review. The fresh audit is
  now terminal PASS and independently byte-recomputed at gate
  `8a1532b7…91f8`: cheap-choice all-state regret upper bound `0.0354` and
  N=30-choice `0.0439` both beat the frozen `0.10` limit. N=30's boundary-8
  diagnostic remained weak at `0.1421`, so PASS routes to a hard-tail Stage-C
  design rather than bulk ordinary-state scaling. Claude passed the
  real-output absolute-path adapter delta at exact `60d46e1`; canonical adapter
  `56ccefbd…c2442` was created once and independently verified. Its only next
  authority was Stage-C packet design/review. Pre-review audit superseded v1:
  it mismatched the adapter identity, did not reopen the authenticated live
  parent, and pinned closed S4 v1. Exact `b0ef0f9` freezes repaired v2 at
  `45802e47…a350`: 2,048 states split 1,024 DESIGN / 512 CALIB / 512 REPORT,
  with 1,920 play and 128 separately modeled bury states. A later executable
  audit superseded its H0 v1 parent, so Stage-C v2 is held pre-review. Repair
  the binding only after H0 v2 PASS. No capture, labels, compute or training.
- **Search challengers:** the independently reviewed live-parent contract now
  binds S3a and S3b to exact report-LCB and makes formal-S0/`mc-strong`
  re-entry unreachable. S3b v2 then failed its operational preflight: its
  first exact-treatment cluster exceeded the frozen cumulative 250k-node cap,
  so no receipt or strength screen is authorized. S3a's separately reviewed
  512-state mechanism screen is now terminal PASS: structured bury beat the
  live incumbent, legacy-four and trigger-matched random widening with every
  frozen state-level LCB above zero. This is proposal-generation evidence, not
  bot strength. Its reviewed full-game score-free preflight subsequently
  completed exact work and projects the 2,048-cluster screen at `72.62`
  fleet-hours / `9.08` max-shard hours. Claude passed the separately frozen
  one-shot packet at exact `c599b42`; one admission `567e8aa8…41c5e` and
  receipt `2c89bed3…cbb2c` launched eight sealed Mini shards against exact
  report-LCB with a champion-matched null. Await terminal verification without
  inspecting partial outcomes. PASS can open confirmation-packet review only.
- **Point-banking S4:** v1 is closed HOLD without outcomes because its claimed
  material digest did not reproduce. Exact `1b35fb7` repaired that evidence
  boundary and a secondary utility bug while preserving the observed
  continuation-only mechanism outside sealed MCBot/registry source. Treatment
  and matched null preserve the root ballot and baseline decision to contest;
  treatment acts only from the secure last seat and only while retaining a
  higher winner. Named continuations show both +10 immediate value and -10
  future-control risk. Fresh score-free asset `4538be85…6b5f` froze 64
  exact-late states from unique deals, 32 per role. Independent verifier
  `b0ef0f9` rescanned all 69,047 ascending deals and reproduced every row at
  `3079fb16…f0a9`. After external PASS, the one authorized Air execution
  exactly verified terminal `abd9f36f…cdc00`: overall acting-team point delta
  `+5.156` with one-sided LCB `+3.029`, positive attacker and defender means,
  35 wins / 4 losses / 25 ties, and level utility `+0.25`. This establishes
  the narrow exact-late mechanism. A pre-review adversarial audit superseded
  the first full-game packet without launch or outcomes: its record validator
  admitted wrong-signed/unbounded utility, underfilled report work and direct
  shards without reviewed authority. Exact `cad3992` freezes repaired v2:
  treatment, analysis-identical matched null and champion share mirrored deals
  and RNG streams; raw round points reconstruct every signed utility; each
  search consumes exactly 30+300 accepted worlds; and every canonical shard
  reopens the reviewed packet/admission/receipt chain before compute. Fresh
  score-free Air preflight `fcc8b891…ee060` passed in 321.32 seconds, projected
  the screen at 91.40 fleet-hours / 11.42 max-shard hours, and packet
  `17036e63…1385` fully recomputes. External review still gates its only Mini
  launch; confirmation is hard-closed pending a future reviewed controller.
- **Human data:** the atomically refreshed Fly-snapshot-only `human_v8` corpus
  passed independent publication review at producer `b52dc33`, source manifest
  `07ff18fb…a5e` and corpus manifest `b9699790…16553`. It contains 2,830 plays,
  45 buries and explicit replay/refusal provenance. It authorizes one H0 design
  packet only—not labels, training or a strength claim. Exact `9770313` has
  now frozen that score-free design: 384 DESIGN and 128 player/deal-disjoint
  AUDIT play keys, every late/off-analysis-ballot row, all 36/9 split buries,
  and no outcomes. Packet `9ff160a9…247d3` independently passed split/design
  review, but later executable audit found its V11 SHA names no artifact, so
  it cannot parent a controller. Exact `12dac55` v2 binds the executable
  checkpoint, portable live parent and explicit disjoint 30/300 selection/
  report rule at packet `2cccf580…8f2b`; it reproduced exactly on Air and
  awaits rereview. A
  latest complete server pull at 16:07 UTC found every one of the 30 source
  files unchanged, so this remains the current production snapshot. The split
  is name-derived pseudonymous-player/deal disjoint, not provably true-person
  disjoint if one person used multiple names. That limits H0 to diagnostics;
  HUMAN-C1 needs consented stable evaluation-session identity.
- **Data/sampler:** the bounded strict sampler certificate passed, but posterior
  fidelity and global constructive completeness remain open. High-N and
  late-ply data are replayable state reservoirs under old named targets, not
  generic oracles. Contaminated encoder caches remain quarantined.

### Decisions that survive

1. Optimize against the named live champion, not “MC” or pool Elo.
2. Spend compute vertically on disjoint common-world comparisons and stronger
   continuations before horizontally generating more old-target rows.
3. Train a within-state ranking head and a calibrated scoring-bracket/outcome
   head separately; never force relative V11 deltas into a scalar leaf.
4. A Teacher PASS licenses a new hard-tail contract, not automatic bulk scale.
   Hard tail is not “openers”: protect early leads, follow and bury decisions,
   late play, both roles, uncertainty/disagreement and human-observed mechanism
   strata; escalate uncertain labels to gold/exact-late and gate their regret
   separately.
5. Direct-Q/O0 successors share CRN evaluation and at least eight independent
   training seeds, then isolate sharpening, dose, target/credit and feature-use
   mechanisms instead of bundling them.
6. Every experiment binds code, engine, policy, ballot, sampler, continuation,
   encoder, data/split, actor, seeds, work, metric, null and stop rule. Missing
   or drifting identity makes a run invalid regardless of score.
7. Screens choose one candidate; only a fresh paired confirmation against the
   named champion establishes strength. Correctness repairs, green pipelines,
   faster simulation and larger corpora are enabling work, not AI wins.
8. S3a is the first positive structured-search mechanism: preserve its frozen
   proposal recipe and move to fresh full-game evidence. Do not tune from the
   inspected 512 states or treat per-state bury gain as signed-level utility.
9. Human actions are candidate sources, not labels. Measure whether they add
   useful actions and survive counterfactual evaluation before imitation.
10. Bot-vs-bot paired evidence is the controlled strength gate; the product
    claim ultimately requires a blinded candidate-versus-champion comparison
    against the same human cohort plus an absolute experienced-human benchmark.

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
2. **Use learned models first where the target is identifiable.** v11pair may
   rank/propose actions on its exact ballot, but direct-v2 has since rejected
   its protected-anchor composition. Teacher work may compare its proposal
   recall/regret with a same-budget random diversifier, then train separate
   lead/follow ranking surfaces only if untouched teacher metrics support them.
   A value model must name its perspective, belief, continuation policy and
   horizon; otherwise it is not a leaf contract.
3. **Treat rollout-policy uncertainty explicitly.** As a later bounded
   robustness arm, compare the incumbent single continuation against a small
   fixed portfolio (for example current Smart, conservative/tempo, and
   point-aggressive continuations) at equal total work. This is not a claim
   that a stronger standalone roller automatically makes stronger MC.
4. **Use the completed faithful probes to isolate the next mechanism.**
   Direct-Q found positive gameplay but failed held-out role learning; Suphx O0
   found aggregate oracle acquisition but failed seed robustness. A successor
   uses common-random-number evaluation and at least eight training seeds, then
   varies sharpening/dose/target mechanisms without bundling them into one
   uninterpretable recipe. Only robust held-out learning earns fleet scale.
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

## ROADMAP FROM HERE — live-champion flywheel

The baseline is the exact deployed `mc-s0-report-lcb` policy, not “MC” in the
abstract. Every challenger binds that parent plus a matched null at freeze
time. The immediate milestone is **T3: turn human-observed weaknesses into one
reviewed live-champion challenger and a better hard-tail Teacher**. Live order
and machine ownership remain in `BACKLOG.md`; this section explains how the
strength loop works.

### T3 decision tree

1. **Finish the sealed S3a screen.** The structured-bury 512-state mechanism
   screen already passed and its fresh 2,048-cluster full-game screen is live
   on Mini. Terminal PASS permits freezing an 8,192-cluster confirmation packet
   for external review; it does not permit an automatic launch or promotion.
   SELECT NONE closes this exact recipe without tuning or retry.
2. **Carry S4 from mechanism evidence to whole-game evidence.** The reviewed
   one-shot exact-state screen passed in both roles at terminal
   `abd9f36f…cdc00`. The repaired complete-round v2 controller and packet are
   frozen at `cad3992` / `17036e63…1385`, preserving natural trigger traffic
   against the exact live champion and an analysis-identical matched null.
   External review must precede launch, and Mini remains occupied by S3a. Do
   not treat `+5.156` points as a duel-strength estimate: using a K now can
   still waste future control over a full continuation.
3. **Repair then review the Teacher Stage C contract.** Exact `b0ef0f9` defines
   2,048 fresh states and fixed 250k-deal scan windows for each split. Cheap
   labels remain only on ordinary anchors; uncertainty/disagreement/bury use
   live report-LCB gold, exact-late uses an information-set-legal solver or the
   live gold fallback, and S4 is conditional on its own terminal PASS. Repaired
   v2 also reopens the authenticated live parent and defines independent
   audit/reference folds plus equal-budget proposal-recall LCBs, but its H0 v1
   parent is now superseded. Freeze a new binding only after H0 v2 PASS; review
   still precedes capture, labels, compute and training.
4. **Rereview the repaired human-action counterfactual pilot boundary.** Human moves broaden the action
   and state distribution beyond heuristic self-play, but raw imitation or
   final-round return is not a strength target. Reconstruct and validate each
   decision, add the human action to the champion/structured ballot, and
   compare all actions on common worlds under named continuations. V1's split
   review remains informative but cannot authorize a controller because its
   V11 digest was non-executable. Exact `12dac55` v2 repairs that identity and
   makes V11 a raw within-ballot proposal rather than a scalar leaf. Fresh v2
   PASS may authorize only a fail-closed, score-free controller freeze and
   another review—not execution, labels or training. Human data proposes
   alternatives; the counterfactual Teacher decides whether they are supported.

T3 exits with one verified S3a terminal verdict, its conditional reviewed
confirmation packet or immutable closeout, a reviewed S4 complete-round
packet, a reviewed Stage-C design, and a reviewed H0 design plus frozen
execution-controller packet.
This is useful even if every strength screen selects none: the next attempt
starts from a diagnosed mechanism rather than another undifferentiated corpus.

### Lane A — improve search directly

- **S3a structured bury** directly tests the observed point-shy kitty policy.
  The incumbent can bury points in rare void/trump cases; S3a is broader because
  it explicitly constructs one-/two-suit voids containing points and evaluates
  them through rollouts.
- **S4 point-banking continuation** has passed its exact-state mechanism
  screen in both roles and its score-free complete-round capacity gate. Packet
  `17036e63…1385` is frozen. The remaining empirical question is deployment
  relevance: does the continuation-only change improve complete-round utility
  under natural traffic against the live champion and matched null?
- **Later exact search** requires a new operational hypothesis. S3b-v2 is
  terminal after its first treatment cluster exceeded the frozen 250k-node
  budget; raising the cap after inspection is not a continuation of v2.
- Generic candidate widening remains closed on DEV-512. New action sources
  must come from a named mechanism—structured tactics, human proposals or a
  model—and beat a same-budget random diversifier on fresh states.

### Lane B — build a Teacher beyond heuristic self-play

The Teacher should not merely make the existing heuristic target less noisy.
Its candidate set and continuation portfolio must expose strategies the
heuristic never generates or systematically misprices.

The Stage-C progression is:

1. capture fresh non-evaluation states with explicit early/mid/late,
   lead/follow, banker/non-banker and action-count cells;
2. oversample champion uncertainty, champion-versus-V11/human/structured
   disagreement, point-bearing kitty voids, point-banking winners and
   exact-late opportunities;
3. evaluate the union of incumbent, structured, V11 and human proposals on
   common proposal worlds plus independent report worlds;
4. compare named continuation contracts: the production continuation for
   deployment relevance, S4 when applicable, and exact/perfect-information
   late play only as a bounded privileged diagnostic—not a public-policy label;
5. escalate high-SE/disagreement rows to larger budgets or exact-late labels
   and gate hard-tail regret on untouched states;
6. train separate pairwise/listwise ranking and calibrated signed-outcome
   heads across seeds and state-count curves; integrate first as proposal,
   ranking or allocation help inside search;
7. spend 10k/50k-scale collection only after untouched teacher metrics and a
   fresh paired bot screen improve.

“Hard tail” is not synonymous with openings. Early leads matter because their
continuations are long and existing data overexposed lead weaknesses, but bury,
follow, late play and role-specific decisions remain separate strata. Report
per-surface gains so a narrow opener improvement cannot masquerade as a general
policy improvement.

### Human-data lane — diversify, then verify

The August 9 `human_v8` rebuild repairs the old path's provenance failures: it
is Fly-snapshot-only, stages updates atomically, verifies source hashes, records
reasoned replay refusals, binds the repaired public encoder, pseudonymizes
players and includes bury decisions. Its 2,830 plays and 45 buries remain human
behaviour, not strength truth. The earlier v6.1 blend increased human agreement
but scored 46% against v6 in a small sibling duel: evidence for style transfer,
not strength.

The current pseudonymous-player split is the strongest separation available
from historical logs, but a display-name-derived identity cannot prove that a
person who changed names stayed in one fold. Treat H0 as a bounded diagnostic
and proposal source. A formal people-strength gate must assign stable,
consented pseudonymous participant/session IDs before play and keep those
evaluation logs physically and logically out of all training builders.
Forward-only exact range through `b198839` implements the logical half: a
HUMAN-C1 schema or any `training_excluded=true` event makes the builder refuse
the entire publication—even on a malformed round with no `round_start`—if
someone copied an evaluation file into the corpus glob. An evaluation log
failure terminally invalidates its room before a retry or deal task can create
apparently complete selective evidence. This does not alter or re-authorize
frozen `human_v8`/H0 evidence. The inert server-side identity/logging seam adds
complementary hidden blocks, participant-derived pair clustering, separate
per-arm policy/Git/image/ballot identity, a disjoint log root, policy and
0/2-human-versus-1/3-bot binding, name/chat redaction and fail-closed writes.
It is deliberately unreachable from the live WebSocket. Consent/token ingress,
reviewed assignment construction, runtime artifact reopening, disconnect
invalidation, synthetic C0 and a terminal estimator are still required.

Use human data in three bounded stages:

1. **Freeze the honest split.** Player/deal connectivity leaves only five
   independent components, and two contain almost all rows. Use the large
   three-player/78-deal component for DESIGN, the separate one-player/28-deal
   component for AUDIT, and the remaining three tiny components only as a
   RESERVE diagnostic. Calling these data a meaningful three-way
   DEV/CALIB/REPORT split would overstate their independence; formal REPORT
   remains fresh synthetic/full-game and `HUMAN-C1` evidence.
2. **Counterfactual action pilot.** Exact `9770313` v1 froze 384 DESIGN and 128
   AUDIT play decisions, caps each deal at eight, includes every late and every
   off-analysis-ballot action, and balances lead/follow and role. Add
   the actual human action to the current ballot and measure human-versus-
   champion action deltas on shared worlds. Record where humans introduce a
   genuinely new candidate, where the production continuation reverses it,
   and where a second continuation changes that ranking.
   Treat the 36 DESIGN and nine AUDIT buries as a separate surface rather than
   forcing them into the play estimand. Its split review passed, but its V11
   digest names no executable artifact. Exact `12dac55` v2 preserves the rows
   and binds `ep07.npz` at `cd89d6ed…c003`, the portable live parent and fixed
   selection/report semantics. Rereview v2 before implementing a score-free
   controller; review that controller again before one counterfactual outcome.
3. **Only then choose the learning use.** Strong supported actions can train a
   proposal/prior head; disagreement states feed Stage C; raw behavioral
   cloning remains an initialization/style control. Promotion still requires
   fresh paired play against the live champion.

This breaks the closed heuristic-self-play loop without declaring every human
move optimal or leaking private full-deal information into a deployable model.

### Lane C — learn beyond MC imitation

Direct-Q and O0/O0-v2 failed different gates and do not reject RL broadly.
Their reusable result is the evaluation chassis: common-random-number tests,
semantic replay and at least eight independent training seeds. The next small
learner changes one substantive mechanism—target/credit, decision-type
specialization, data curriculum or bounded policy adaptation—while holding
that chassis fixed. O1, AWAC and large opponent-pool self-play wait until a
small model robustly acquires and uses the intended signal.

### Flywheel

Human play, structured tactics and model disagreement propose states/actions
outside the incumbent's habits. A stronger counterfactual Teacher evaluates
them under explicit continuation contracts. A ranker then focuses search on
the supported alternatives; fresh paired games decide whether the composition
beats the named champion. A promoted policy becomes the next parent and the
next Teacher reference. Compute buys a new strategy or a better target—not
just more rows generated by the same heuristic.

### Strength against people

Paired bot games are the laboratory instrument, not the final product metric.
They provide common deals and tight uncertainty, so every candidate must first
beat the exact live champion there. A confirmed candidate then enters an
opt-in, blinded human screen: randomize candidate versus champion across the
same player cohort, balance banker/team/seat, cluster by player session, and
measure signed level utility plus game win, fallback, completion and latency.
Human evaluation games are permanently excluded from training and selection.

The people-facing claim has two parts: candidate-minus-champion improvement
against the same human cohort, and absolute performance against a named
experienced cohort. Raw site-average win rate is descriptive because changing
player mix can move it without any bot change. `HUMAN-C1` should predeclare a
one-sided candidate-minus-champion utility gate and non-inferiority experience
guards before policy identities or outcomes are opened.

The end target is not “best in the policy pool.” A bot is product-strong only
after it first beats the live champion on paired deals, then improves against
the same blinded human cohort, and finally reports absolute signed level
utility against a named experienced-player cohort. Those three questions are
different and must not share selection games.

## v11pair's surviving role

The corrected 2,048-cluster direct-v2 result selected none:
v11-minus-current was `-0.141 +/- 0.070`, v11-minus-null was
`-0.110 +/- 0.070`, and protected composition was unauthorized. Do not rerun
the direct or protected-anchor recipe, revive top-k pruning, or use pairwise
deltas as a scalar leaf.

The confirmed 57.7% result versus SmartBot still says the frozen model contains
within-ballot ranking signal. Its only live hypotheses are therefore bounded
proposal diversification, ranking/diagnosis and Teacher disagreement mining.
Any proposal experiment must compare v11 recall/regret against a same-budget
random diversifier; “the model proposed it” is not a control or a strength
claim.

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

### High-N and artifact boundary — compact surviving result

The old high-N labels are useful only for fixed-pair diagnosis. On 240 shared
worlds per action, v11 beat Smart's stored action by `+0.397 +/- 0.037` raw
heuristic points on 12,340 original rows and `+0.334 +/- 0.047` on 7,292 later
rows, but harmful overrides rose from 18.0% to 25.7%. This explains “many small
wins, expensive misses” and motivates an MC anchor; it does not establish bot
strength. The labels use an old ballot, non-strict sampler, raw points and one
heuristic continuation. Post-hoc lead archetypes are hypothesis strata, never
deployable filters.

Keep artifact classes separate:

1. A **state reservoir** stores reconstructable public/private replay state and
   a frozen split, but no claim that old scores are current truth.
2. A **counterfactual Teacher set** binds ballot, belief sampler, continuation,
   signed utility and common/report worlds, retaining paired outcomes rather
   than only an argmax.
3. An **episodic RL set** binds immutable actor identity, sequential history and
   role-correct terminal return.
4. A **human-behaviour set** binds replay keys, pseudonymous player grouping and
   the actual human action. It is a proposal/prior source until counterfactually
   relabeled; mixed-skill imitation is not an oracle.

Current frozen assets are indexed, not re-described here:

- `deep_leads.v1` is a 768-state DEV/CALIB/REPORT reservoir for missing depth;
- `pilot_dev512.v6` selected none and cannot train; its CALIB asset stays sealed;
- `s0_override_audit.v1` is an inspected report-fold regression fixture;
- high-N and historical human encodings generated during banker-private-kitty
  drift remain quarantined;
- the refreshed human corpus is published only with source hashes, explicit
  replay/rejection counters and the public/no-private-kitty encoder identity.

Detailed inventory remains in `docs_archive/daily-log-2026-08-04.md` and
`docs_archive/daily-log-2026-08-05.md`. Every new dataset binds selection and
split, ballot, engine, sampler, continuation, utility/perspective, budget,
producer, encoder and actor/checkpoint identity. DEV may select one design,
CALIB may judge it once, REPORT remains untouched, and incompatible artifact
classes never merge silently. Scale follows lower untouched hard-tail regret
and fresh online strength—not row count.

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
