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

## Current synthesis — 2026-08-09 06:20 EDT

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
  design rather than bulk ordinary-state scaling. A real-output absolute-path
  adapter delta is under superseding review; no labels or training are yet
  authorized.
- **Search challengers:** the independently reviewed live-parent contract now
  binds S3a and S3b to exact report-LCB and makes formal-S0/`mc-strong`
  re-entry unreachable. S3b v2 then failed its operational preflight: its
  first exact-treatment cluster exceeded the frozen cumulative 250k-node cap,
  so no receipt or strength screen is authorized. S3a's separately reviewed
  512-state mechanism screen is now terminal PASS: structured bury beat the
  live incumbent, legacy-four and trigger-matched random widening with every
  frozen state-level LCB above zero. This is proposal-generation evidence, not
  bot strength. The next gate is a fresh mirrored full-game duel against exact
  report-LCB with a champion-matched null.
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
   Mine uncertainty/disagreement, escalate uncertain labels to gold/exact-late,
   and gate hard-tail regret separately.
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

The production baseline is no longer “MC in general.” It is the exact
`mc-s0-report-lcb` decision rule confirmed by RLCB-C1. Every new search,
teacher or learner experiment must bind that named parent at freeze time and
include a matched null/control; inheriting formal S0's stale `mc-strong`
meaning is a protocol bug. `BACKLOG.md` owns live order and machine assignment.
This section owns why the lanes fit together.

### Lane A — improve search directly

1. **Structured bury (S3a).** Burial happens once per round and has a
   combinatorial action set, so it is a high-leverage place to spend more
   proposal and rollout work. The existing 512-state mechanism screen compares
   a structured ballot with the legacy four candidates and trigger-matched
   random widening on disjoint report worlds. It must first be reparented to
   report-LCB. A PASS only licenses a fresh full-game duel design; the state
   screen cannot promote a bot.
2. **Sampled exact endgame (S3b).** When all hands have at most four cards,
   solve each determinized world exactly within the proved 250k-node bound
   instead of finishing with the heuristic. The mechanics challenge and
   2,048-screen/8,192-confirm runner already exist. Reparent the currently
   unreachable report-LCB lane, run a score-free throughput preflight, then
   spend strength compute only if the frozen capacity gates pass.
3. **Later proposal work.** DEV-512 rejected its registered generic widening
   designs. A future lead proposer must arise from a new hypothesis and fresh
   population; it cannot append arms to inspected DEV or call more candidate
   count by itself a strength mechanism.

### Lane B — make a teacher that can exceed the champion

Teacher-v3 Stage B established that cheap N=30 labels agreed with gold on the
sampled ordinary states. The running 64-state audit asks the harder question:
whether those choices remain good under full downstream report-LCB
continuation. Stage B does not prove fidelity on high-SE/disagreement tails.

After the audit:

- PASS permits a fresh Stage-C contract, not automatic bulk generation. Mine
  uncertainty/disagreement strata from non-evaluation states, escalate uncertain
  labels to gold or exact-late continuation, and separately gate hard-tail
  regret.
- FAIL or INCONCLUSIVE means diagnose the smallest continuation/selection
  failure and redesign; do not make the same labeler more precise at scale.
- Only after untouched teacher gain should three-seed/state-count curves train
  a pairwise/listwise ranker plus a calibrated scoring-bracket head. Integrate
  first as a proposal/ranking/allocation feature inside MC. Fresh paired games
  against report-LCB decide whether a 10k/50k wave is justified.

### Lane C — learn beyond MC imitation

Direct-Q and Suphx O0 both reached terminal SELECT NONE, but they failed
different gates. Direct-Q's gameplay was positive while held-out role learning
failed; O0 learned an aggregate oracle-public edge but not robustly across
seeds, and its policies remained nearly uniform. This is evidence of
implementation/credit-assignment risk, not a broad rejection of either family.

The next learner is one fresh mechanism battery, not an extension of either
inspected run. Common-random-number evaluation and at least eight independent
training seeds are shared inference infrastructure. Then isolate sharpening,
dose, target/credit and feature-use changes factorially enough that a result
names the mechanism that moved. Privileged-feature removal (O1), AWAC and large
opponent-pool self-play wait until this small learner can robustly acquire and
use its oracle signal.

### Flywheel

Mine states where the live champion is uncertain or disagrees with bounded
proposal sources; label them with a stronger continuation/oracle; train a
ranker and calibrated outcome head; use the model to focus rather than replace
search; confirm one frozen composition against the live champion; then make a
promoted policy the next teacher. Compute buys a stronger decision or target,
not just more rows.

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
and full-game confirmation, as required by the archived
`docs_archive/ballot-plan-through-2026-08-05.md` contract.

### Historical training-data inventory

The byte/row inventory rebuilt on 2026-08-04 is historical operational detail,
not the current experiment queue. Its exact table remains in
`docs_archive/daily-log-2026-08-04.md`; later quarantine and usage conclusions
are synthesized above.

The surviving rule is simple: raw replayable state reservoirs may be reused
under a newly frozen contract, but contaminated encodings are regenerated and
old heuristic/non-strict labels are never relabelled “oracle.” Dataset size is
not evidence of target quality.

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
