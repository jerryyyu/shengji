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

## Current synthesis — 2026-08-11 15:41 EDT

Exact terminal numbers and SHAs live in the canonical table in
`AI_POLICIES.md`; `BACKLOG.md` owns live order and `JOBS.md` owns machines.
This section keeps only the research conclusions that change what we try next.

### State of play

- **Champion:** compiled `mc-s0-report-lcb`. N=30 nominates one challenger,
  R=300 fresh common worlds compare it with the incumbent, and a conservative
  lower bound decides whether to override. Fresh RLCB-C1 confirmed it over
  `mc-strong`; wider or adaptively allocated MC has not shown another gain.
- **Teacher generation one:** capture and corrected iid labels worked. Eight
  training seeds on 1,536 DESIGN/CALIB rows selected none: the play ranker was
  nearly flat and unstable, while bury was negative. A frozen protected play
  ensemble then received one untouched 480-row REPORT look, triggered 171
  times, and lost to candidate zero (mean `-0.008228`, LCB `-0.018944`).
  That REPORT and policy are closed—no threshold tuning or composition.
- **Teacher generation two:** the 7,040-state matched A/B and all untouched
  exams are terminal. More data made the old all-pairs loss stable; the new
  candidate-zero-relative loss did not win. Expanded bury then selected none
  on 32 fresh rows (`+0.03381`, LCB `-0.01525`). Expanded play had positive
  DESIGN/CALIB ensemble bounds, but its protected 480-row REPORT lost
  (`-0.00823`, LCB `-0.01894`). A predeclared powered exam used all 219
  untouched champion-uncertainty rows and also selected none: action
  `+0.01213`, SE `0.01011`, LCB `-0.00506`. Outcome-NLL improvement was
  strongly positive (`+0.47845`, LCB `+0.44201`) but nongating. This generation
  learned outcome/value structure better than reliable action ranking. A
  terminal post-hoc outcome-head argmax also selected none (`+0.00906`, LCB
  `-0.01184`), so simply swapping heads is not a successor. No composition or
  game screen follows.
- **Fresh mid/late successor:** the spent diagnostics suggest the ranker may be
  useful only after trick 5, when the horizon is shorter. This is a new
  post-hoc hypothesis, not a reinterpretation of the failed REPORT. PR #35
  gates before source/scope/model work; source-only PR #36/head `c9fa22b`
  freezes exactly 256 new one-state-per-deal mid/late × role triggers and
  prices protected-model, matched-random and literal-live final actions on a
  separate 3×N=300 fold. It opens no evidence yet. The two primary gates are
  treatment LCB > 0 versus both live and same-work null; null-versus-live is
  explanatory, not a third test.
- **Direct search:** S4 point banking passed exact-state and first whole-game
  screens; its independent fixed replication stayed positive but selected none
  (`+0.048828`, LCB `-0.006884`). S3a structured bury improved selected-state
  regret but selected none in fresh games. S6
  shuai-pai sourcing and S5 replay are bounded proposal/diagnostic follow-ups,
  not strength claims.
- **Learned/RL routes:** V11 direct-v2, Direct-Q, Suphx O0/O0-v2 and the first
  Stage-C model all selected none under different gates. This does not close
  RL. It says the next experiment must change data, objective, credit or model
  use—not merely train longer on the same target.
- **Human evidence:** `human_v8` contains 2,830 plays and 45 buries. H0's one
  counterfactual run completed 555/557 rows and correctly published no
  aggregate. Human actions remain candidate and diagnosis sources; ultimate
  people strength requires the separate blinded HUMAN-C1 ladder.
- **Endgames:** S3b's four-card exact rollout exceeded its frozen node cap.
  S3c restarts at naturally reached one-, two- and three-card roots. One-card is
  mechanics-only; two-card is the first meaningful action-selection problem.

### Decisions that survive

1. Optimize against the exact live champion, not “MC” or pool Elo.
2. Spend compute on new targets, proposals or continuations—not more copies of
   the incumbent's decisions.
3. Use common hidden worlds inside a comparison and independent RNG streams
   across folds; retain valid repeated worlds with replacement.
4. Select whole multi-seed cohorts on DESIGN/CALIB. Never select a lucky seed.
5. Keep ranking, calibrated outcome and proposal roles separate. A pairwise
   score is not automatically a scalar leaf.
6. Human actions are proposals, not truth labels. Counterfactually price them
   before training or policy use.
7. Local mechanism gains must survive fresh whole-game play; screens select and
   fresh paired confirmations establish strength.
8. Every claim binds source, engine, policy, ballot, sampler, continuation,
   encoder, split, seeds, work, metric, null and stop rule.
9. Correctness, throughput and larger data are enabling outputs, not AI wins.
10. High-N, late-ply and human corpora are replayable reservoirs under named old
    targets—not generic oracles.
11. Small-domain exact search may supply privileged diagnostics or Teacher
    targets, but public play still requires an imperfect-information policy.
12. People-facing success means candidate-minus-champion improvement against
    the same blinded cohort, then absolute performance against a named
    experienced cohort.
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
| [AutoGo](https://evjang.com/2026/04/28/autogo.html#cover) / [repository](https://github.com/ericjang/autogo) | Simple learning loops become productive when collect→train→evaluate first works on a smaller domain (the repository defaults heavily to 9×9), with self-contained experiments and reproducible fleet jobs; scale and asynchrony come later. | Use the same curriculum twice: make one-/two-/three-card Shengji endgames work before expanding exact search, and make one synchronous immutable Teacher→train→evaluate loop work before scaling actors. Automation may schedule a preregistered experiment; it may not invent a metric or promote a checkpoint. |

### Research constraints that survive

The table above is an architecture filter; the live execution plan is owned by
the roadmap below. Its durable constraints are: search a public belief or a
clearly named determinization approximation rather than pretending a private
observation has one universal value; specialize heterogeneous decision/role
surfaces; bind every value to its perspective, horizon and continuation
policy; introduce learned models first as bounded proposals/rankers unless a
calibrated value contract has actually passed; and establish the loop on a
small domain before scaling it. A small fixed continuation-policy portfolio is
a legitimate robustness experiment, but a stronger standalone rollout policy
does not automatically imply a stronger search policy.

Historical DMC2 is consolidated into the lineage below and the dated archive.
Its spread alarm caught a real collapse, but its defender sign, target,
algorithm identity and mutable actor/promotion boundaries made it neither a
faithful Suphx test nor a faithful DouZero test. Preserve the alarms, replay
cap, immutable bookkeeping and opponent-pool idea; do not resume or scale the
13-part recipe as one bundled hypothesis.

---

## Learned-model and training-system lineage (authoritative summary)

This section owns the experiment history: what changed, what question it
tested, and what survived. `AI_POLICIES.md` owns runnable policy names and
their current deployment status. Keeping the full ladder in both files caused
model checkpoints, policy wrappers, and search roles to be conflated.
The detailed day-by-day chronology remains in
`docs_archive/rl-plan-chronology-through-2026-08-03.md`.

The early project reused version numbers in three namespaces. **Distillation
v1-v13** names model/training iterations; **DMC recipe v1/v2**, Direct-Q and O0
name separate training branches; **ballot v1/v2/v3** names action enumerators.
They are not successive versions of one artifact, so newer work is recorded by
its real branch name rather than being relabelled `v14` or `v15`. Historical
pre-v7 gates also predate the current seeded, paired evaluator and are
directional screens, not promotion evidence.

| model / branch | improvement / hypothesis tested | best evidence | conclusion |
|---|---|---|---|
| **BC baseline** (pre-v1) | Behavior-cloned SmartBot from about 20k rounds using the original 531-dimensional observation and 60-dimensional action encoding. | 89.7% teacher imitation; historical gates 48% vs SmartBot and 29% vs MC. A later play-time ballot expansion sent the same family to Elo 798 until the training ballot was restored. | The encoder carried substantial game signal, but small imitation errors were exploitable by search. Established the ballot/version-freeze requirement. |
| **DMC recipe v1 branch** | Warm-started BC, then regressed raw terminal returns in self-play. This was a self-play branch, not distillation model v1. | Flat 30-34% vs SmartBot over roughly 400k rounds; cross-candidate score spread collapsed `22.5 -> 0.26`. | Closed as an unsafe implementation/target combination: raw-return regression destroyed the pretrained ordering and the degraded policy generated its own data. It did not prove self-play RL cannot work. |
| **DMC recipe v2 / DMC2** | Bundled dueling heads, a scalar “oracle residual,” annealed anchor, gating, opponent pool, auxiliary heads, exploration scheduling and replay controls as scaffolding for a later AWAC rewrite. | Its own spread alarm halted collapse twice. Later audit found the defender residual had the wrong perspective, the recipe was neither Suphx privileged-policy training nor DouZero direct role-Q, and mutable actor/candidate paths could detach promotion from evaluated bytes. | **INVALID ALGORITHM-FAMILY TEST.** The guards and immutable-resume repairs survive; the bundled DMC2 result does not reject AWAC, Suphx, DouZero or residual learning and should not be resumed as one recipe. |
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
| **v11pair** | Corrected v10 around the deployed decision: optimize `(q_i-q_0)` against `(Q_i-Q_0)` with Huber loss and boundary weighting, use the exact valued ballot at inference, and fit the 0.02 threshold on one split before reporting another. | `rl-override-v11pair` **CONFIRMED** 57.7% vs SmartBot (277-203, n=480, two disjoint blocks). Its 51.1% vs MC over 4,880 rounds used MC factories that silently discarded seeds; a later negative block used a banker-private-kitty encoder absent from training. The corrected-encoder direct-v2 test finally supplied the current-contract verdict: v11-minus-live `-0.141 +/- 0.070` and v11-minus-matched-null `-0.110 +/- 0.070`. | The only confirmed learned online gain is versus SmartBot, not MC or report-LCB. Direct/protected-anchor composition is closed. Pairwise deltas are not scalar leaves; V11 survives only as a bounded proposal/ranker and Teacher disagreement signal against a same-budget random control. |
| **v12** | No model, checkpoint, or experiment used this number. | — | Skipped; do not infer a missing failure. |
| **v13abs** | Warm-started v7w and fit the value output to absolute 240-world means from 20,845 high-N states, using inverse-variance weighting. The actual target is raw-point action value under heuristic continuation, `Q^H(s,a)`, not a generic state value. The trainer updated the whole network, not only a detached head. | Offline SCREEN: unweighted RMSE improved `0.1052 -> 0.0699` and stored-ballot regret `1.478 -> 1.293`. Online leaf SCREEN: v13 and v7 each won 52.8%; v13 was `-0.004 +/- 0.206` versus the MC reference and v7 `+0.024 +/- 0.215`. The direct paired v13-minus-v7 contrast is **`-0.028 +/- 0.185`** (250 clusters). There were two train/deploy shifts: early-state and ballot mismatch. A later byte audit adds a third, terminal defect: `highn_train.py` consumed `rl_data/highn_enc`, whose 5,923 banker rows all use the private-kitty drift. | **INCOMPATIBLE / NOT CONFIRMED.** It learned contaminated offline tensors better but did not improve the bot. Rebuild `highn_enc`, retrain and freshly evaluate any successor; the existing checkpoint cannot become valid merely by regenerating the cache. This does not rule out a correctly targeted absolute-value model. |
| **Direct-Q 144M** | Faithful bounded DouZero-style probe: learn role-conditioned, action-conditioned values from direct signed episodic returns with immutable actors rather than distilling MC choices. | Gameplay evaluation was attractive at `+0.163 +/- 0.059`, but seed 1 and both pooled-role held-out MSE gates failed. The preregistered learner gate therefore selected none. | The chassis is reusable and the gameplay tail is a follow-up clue, not permission to promote or simply train longer. A successor must isolate a target/credit or surface-specialization change and pass learning across at least eight seeds before larger fleet scale. |
| **Suphx O0** | Test whether a full-information training-time policy can acquire a signal that survives in its public-information counterpart. | Oracle-minus-public was `+0.073` with aggregate LCB `+0.0025`, but seed means were `+0.344/-0.207/+0.082`; the required seed robustness failed. | Full information was learnable in aggregate, but the benefit was not reliably transferred. O1 was not authorized. |
| **Suphx O0-v2** | Repair the comparison with shared-public common-random-number trajectories, then isolate extra oracle-margin sharpening from the control curriculum. | Control oracle-minus-public was `+0.015`, LCB `-0.067`; plus-margin was `-0.047`, LCB `-0.109`; interaction was `-0.062`. No cell advanced. | The repaired test is a clean negative for these two mechanisms. It does not reject privileged-policy curricula generally, but it closes O0/O0-v2 extension and the proposed sharpening step. |

The progression is therefore not “each version got stronger.” v7 reduced
teacher noise; v8 repaired the data and behavior-target contract; v9 tested
initialization, duration, and one flywheel turn; v10-v11 showed that an
implementation can make a valid hypothesis look inert until the trained
quantity and ballot exactly match deployment; v13 improved supervised fit but
exposed a state-distribution and value-contract mismatch; Direct-Q and O0 then
tested cleaner return-learning and privileged-policy mechanisms without
clearing their own learner gates. No learned model has shown a verified
advantage over the live report-LCB champion; v11's confirmed gain over
SmartBot remains the one positive learned-policy result.

The Stage-C Teacher is listed in the Teacher/data-generation table below rather
than given a synthetic `v14` name. It is now real model work: 2,048 corrected
first-generation labels, 5,504 additional labels, a frozen 7,040-state asset,
eight-seed ranking/outcome cohorts, and several untouched REPORT exams. It
learned a strong calibrated outcome signal but no action-selection rule that
beat the live champion out of sample. Calling the earlier Stage A/B audits
“training” is still wrong; calling the completed Stage-C generations only a
design is now equally wrong.

Stage C is also the first completed checkpoint family trained on hard-tail
labels referenced to the deployed `mc-s0-report-lcb` decision surface. That
closed an old data gap, but it did not remove the continuation ceiling: almost
all labels still priced actions under one heuristic rollout policy.

Before any successor model experiment, checkpoint metadata must name and assert
the target, perspective, continuation policy, state sampler/horizon, ballot
version, and encoder version. A mismatch is an invalid run, not a negative ML
result.

---

## ROADMAP FROM HERE — live-champion flywheel

The baseline is the exact deployed `mc-s0-report-lcb` policy, not “MC” in the
abstract. Every challenger binds that parent plus a matched null at freeze
time. **T3 was the execution-ready strength bridge:** S3a closed negative, S4
passed its fresh whole-game screen, and the human/Teacher/endgame lanes became
executable. It was not itself a claim that a learned model became stronger.
**T4 is the first closed Teacher generation:** execute H0 once,
capture, label, train, integrate and test one challenger end to end. Live order
and machine ownership remain in `BACKLOG.md`; this section owns the durable
decision tree.

### T3 closeout

T3 built the executable bridge from observations to bounded strength tests.
Its terminal outputs were mixed but useful:

- S4 point banking passed a fresh 2,048-cluster whole-game screen.
- S3a structured bury improved its selected-state objective, then selected none
  in whole games; preserve the disagreement states, close that policy recipe.
- H0 made human/V11 proposals measurable, but its only execution was incomplete
  and published no aggregate; no H0 rule entered Teacher training.
- Stage C produced a replayed 2,048-state split-safe population and corrected
  its hidden-world sampling estimand.
- S3c and S5 established bounded mechanics/replay boundaries, not strength.

T3 therefore delivered one promising search mechanism and a trustworthy
Teacher pipeline. It did not deliver a stronger learned policy. Reviews are
routing boundaries; only terminal model/report/game results change strength.
### T4 — first stronger-Teacher challenger

T4 must end in a challenger decision, not another design-only audit. Generation
one and generation two both completed with valid challenger decisions:

1. capture and label a split-safe hard-tail population — done;
2. expand to 7,040 DESIGN/CALIB rows and train matched eight-seed cohorts —
   done; scale helped more than the alternative loss;
3. test the selected bury capability once on untouched REPORT — done,
   `SELECT_NONE`;
4. test the selected broad-play capability with candidate-zero protection —
   done, `SELECT_NONE`;
5. power and execute a narrower champion-uncertainty exam chosen entirely from
   DESIGN/CALIB — done, independently reviewed `SELECT_NONE`; and
6. stop before composition because the required action LCB was not positive.

T4 therefore closes scientifically as **learned capability without a stronger
learned bot**. The important positive residue is a value/calibration signal;
the important negative result is that the global ranking/argmax use did not
transport. A successor must change model use, decision surface, proposal set or
continuation—not simply extend this training recipe.

S4 replication is terminal positive-but-inconclusive `SELECT_NONE`. S6 source review and
code/document cleanup use otherwise idle implementation time without competing
for Mini's Teacher slot.
### Lane A — improve search directly

- **S3a structured bury** tested the observed point-shy kitty policy. Explicit
  point/void/trump proposals improved the selected-state objective, but the
  full-game screen selected none. The policy recipe is closed; its useful
  residue is a set of proposal/continuation disagreement states for Stage C.
- **S4 point-banking continuation** passed its exact-state mechanism screen in
  both roles and its sole 2,048-cluster complete-round screen. The natural-
  traffic estimate is `+0.086914 +/- 0.056166` versus the live champion with
  positive LCB; matched null was exactly champion. Its independent fixed
  replication was `+0.048828 +/- 0.055712` with LCB `-0.006884`, so it did not
  repeat at the predeclared bar. Preserve both results, but do not retry,
  extend, confirm, promote or deploy this recipe.
- **S5 defensive point protection** is not yet an implementation hypothesis.
  Observational loss mining suggests a narrower avoidable-slough surface, but
  its original global headline disappeared after per-seat normalization.
  Because baseline follow logic already prefers non-points and MC already
  sources both follow extremes, exact replay must identify whether any defect
  lies in forced legality, ballot caps, search ranking, rollout continuation or
  an obsolete historical policy. Human loss states are DEV witnesses only;
  formal mechanism selection, if opened, uses fresh trigger-matched states.
- **S3c exact-root curriculum** is the new operational hypothesis, not an S3b
  retry. S3b-v2 is terminal after its first four-card treatment cluster
  exceeded the frozen cumulative 250k-node budget. Start from naturally
  replayed full-deal prefixes with at most one card per hand, then two, then
  three. At each root, sample compatible hidden worlds, reuse one exact
  partnership-minimax session per world across the bounded production ballot,
  require complete work or fall back unchanged, and compare against the live
  champion on fresh deal-disjoint states. Human endgames are DESIGN witnesses
  and error-analysis cases; formal selection uses fresh bot-generated prefixes.
  Four-card roots advance only if the three-card lane establishes both strength
  and a predeclared complexity envelope. This applies AutoGo's small-domain
  lesson while preserving the imperfect-information caveat: exact per-world
  minimax is a privileged approximation, not an exact public Shengji solution.
  The score-free census is now frozen: one-card is correctly mechanics-only;
  two-card is the first nontrivial action surface; and three-card remains
  bounded enough to justify a later gated design. It does not measure exact
  solver nodes, sampled-world acceptance or utility; those remain the purpose
  of separately reviewed controllers and runs.
- Generic candidate widening remains closed on DEV-512. New action sources
  must come from a named mechanism—structured tactics, human proposals or a
  model—and beat a same-budget random diversifier on fresh states.

### Lane B — build a Teacher beyond heuristic self-play

The Teacher should not merely make the existing heuristic target less noisy.
Its candidate set and continuation portfolio must expose strategies the
heuristic never generates or systematically misprices.

#### Teacher/data-generation lineage

“Teacher” has referred to several materially different things in this project.
This table separates them by the training signal they actually produced.

| strategy | how labels/states were created | measured impact | remaining gap / best next use |
|---|---|---|---|
| **SmartBot imitation (BC through early distillation)** | Generate broad self-play states and copy the heuristic's chosen action; later N=10 MC corpora attached noisy candidate values to the same general distribution. | BC learned substantial game structure, and soft MC targets plus more data improved the standalone student through v6. None reached MC strength. | More horizontal copies preserve the heuristic's action and continuation ceiling. Retain only as initialization and an ordinary-state anchor. |
| **N=30 MC Teacher (v7)** | Spend more worlds on the same style of MC candidate comparison, reducing label noise without changing the action source or heuristic continuation. | v7w was a useful successor/initializer and later enabled v11pair, but never showed a verified gain over MC/report-LCB. | Better precision is not a better strategy distribution. Use N=30 for cheap ordinary labels, not as universal gold. |
| **One-turn learned-Teacher flywheel (v9 / `gen_v4`)** | Use the v7 value-leaf hybrid as Teacher, train v9 on its choices, then try the learned head again inside the hybrid. | Warm versus scratch and longer training did not improve strength; the v9 leaf did not beat the v7 leaf. | The loop reproduced its own approximation and continuation bias. A future flywheel needs independently stronger action proposals/labels before self-training. |
| **High-N vertical relabeling (v13)** | Re-evaluate 20,845 selected states at 240 worlds and regress absolute action value under heuristic continuation. | Offline RMSE/regret improved, but online v13-minus-v7 was `-0.028 +/- 0.185`; the source also had banker-private-kitty encoding contamination and train/deploy ballot/state shifts. | Vertical compute is useful only with clean replay, a deployment-matched target and hard-tail coverage. Existing v13 data/checkpoint cannot be repaired retroactively. |
| **Teacher-v3 Stage A** | Run the complete dense label schema twice on the same 64 frozen states under distinct receipts. | Exact deterministic replay/mechanics passed and exposed multiple publication/identity defects before scale. | This certified the producer, not label quality or strength. Keep as the small falsifiability preflight for future Teacher versions. |
| **Teacher-v3 Stage B** | On 128 disjoint mostly ordinary states, compare cheap heuristic-continuation choices with much more expensive `mc-strong@N=30` continuation labels. | Cheap-minus-gold regret upper bound was `0.0195 < 0.10`; the cheap proxy was adequate on this sampled population. | It only showed agreement with the old MC continuation on ordinary states. It did not create a dataset/model or show labels beyond the live champion. |
| **Fresh live-champion audit** | On an untouched 64-state complement, compare frozen cheap and N=30 choices against the deployed report-LCB root evaluator. | Cheap and N=30 all-state regret bounds passed (`0.0354` and `0.0439`), but the eight boundary states had a weaker N=30 bound (`0.1421`). | Ordinary rows can be labeled cheaply; uncertain/boundary rows need escalation. This is the direct empirical reason for Stage C's mixed-budget hard tail. |
| **Teacher Stage C generation one** | Capture a split-safe hard-tail exam, label candidate actions with corrected iid hidden-world folds, and train eight-seed ranking/outcome cohorts on DESIGN/CALIB only. | Capture and 2,048/2,048 corrected labels passed. The 1,536-row model generation selected none; a protected play ensemble also selected none on one fresh 480-row REPORT (`-0.008228`, LCB `-0.018944`). | Close the spent REPORT and policy. The usable lesson is that model signal existed in strata but did not make reliable overrides. |
| **Teacher Stage C generation two** | Add 5,504 fresh DESIGN/CALIB labels for 7,040 total, train matched all-pairs/direct cohorts, then test bury and play capabilities on untouched populations. | All 96 cells and 576 checkpoints replayed. More data produced stable DESIGN/CALIB capability, but fresh use did not transport: expanded bury was `+0.03381` with LCB `-0.01525`; protected play was `-0.00823` with LCB `-0.01894`; the powered 219-state uncertainty exam was `+0.01213` with LCB `-0.00506`. Its outcome-NLL improvement was large (`+0.47845`, LCB `+0.44201`). All terminal results are independently reviewed. | Close direct global ranker use. Preserve the calibrated value signal for explicit common-world advantage/leaf tests and treat the post-hoc mid/late slice only as a fresh specialization hypothesis. |

In plain English, Stage B asked, “Can the cheap grader reproduce the expensive
grader on normal exam questions?” Stage C asks, “Can we write a better exam,
including the questions and candidate answers our current bot tends to miss,
and spend the expensive grader only where it matters?” Stage B validated a
cost-saving component; Stage C is intended to create new learning signal.

The Stage-C progression is:

1. capture fresh non-evaluation states with explicit early/mid/late,
   lead/follow, banker/non-banker and action-count cells;
2. oversample champion uncertainty, champion-versus-V11/human/structured
   disagreement, point-bearing kitty voids, point-banking winners,
   replay-verified defensive point-protection states and exact-late
   opportunities;
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

The current pseudonymous-player split is the strongest historical separation
available, but display-name identity cannot prove that one person who changed
names stayed in one fold. H0 is therefore a bounded diagnostic/proposal source,
not people-strength evidence. HUMAN-C1 is the separate forward-only ladder: it
requires stable consented session identity, complementary hidden assignment,
two humans versus two identical bots, exact policy/Git/image/ballot binding,
fail-closed logging and a disjoint `training_excluded` root. The inert code now
covers redaction, disconnect invalidation, registry reopening, authenticated
short-lived consent assertions and one-use reservations, while remaining
unreachable from the live WebSocket. Before traffic it still needs external
review, measured rather than merely declared runtime identity, an immutable
reviewed block ledger/namespace, a candidate receipt, synthetic C0 and the
terminal estimator. Implementation history belongs in the dated log and
`AI_POLICIES.md`, not in this roadmap.

#### H0 closeout and surviving human-data use

H0 asked a narrow question: when a person chose an action outside the live
bot's preference, was that action a useful candidate under common simulated
worlds? It never treated human play as ground truth.

V1 froze the player/deal-disjoint population but named a nonexistent V11
artifact. V2 repaired identity but left candidate caps and continuation
semantics ambiguous. V3 bounded the union and work, then its sole execution
completed 555/557 rows; two score-free refusals correctly forced
`NO_AGGREGATE`. The exact stream is closed. It neither supports a human/V11
Teacher rule nor proves those proposals are weak.

The surviving uses of human data are:

1. mine concrete off-ballot and loss witnesses, then replay legality/current
   policy before creating a mechanism;
2. use supported human actions as proposal-head or curriculum inputs on new
   DESIGN states—not as imitation labels;
3. keep human endgames as diagnostic cases while formal model selection uses
   fresh synthetic REPORT;
4. after a bot challenger is confirmed, run the separately consented,
   training-excluded and blinded HUMAN-C1 comparison.

The current historical split has only five connected player/deal components
and display names cannot prove true-person identity. It is adequate for
diagnosis, not a credible final people-strength REPORT. S5 therefore replays
bot-seat decisions separately from H0, and HUMAN-C1 remains the only route to a
people-facing claim.

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
