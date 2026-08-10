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

## Current synthesis — 2026-08-10 02:00 EDT

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
- **Teacher:** Stage B and the fresh 64-state champion audit passed. On ordinary
  states, cheap-choice and N=30-choice regret upper bounds were `0.0354` and
  `0.0439`, both below `0.10`; N=30's boundary-eight diagnostic was weaker at
  `0.1421`. The lesson is to retain cheap ordinary anchors and spend deeper
  work on the hard tail, not mass-produce more heuristic-self-play labels.
  Frozen Stage-C v3 source `20bdb95`, asset `1a29418` and packet
  `f213314a…3b4` now define exactly 1,024 DESIGN / 512 CALIB / 512 REPORT
  states, 20/33 play/bury caps and at most 10,494,720 candidate-world rollouts.
  Hard-tail selection/report folds use `HeuristicBot` continuation and zero
  recursive-MC continuation rollouts. Raw human actions cannot become labels;
  supported proposal rules and S4/S3c/S5 mechanisms enter only through their
  own gates. Claude passed the design at `d92f595`; replacement H0-v3 and
  S3c-v2 then passed at `205b6af`. Minimal rebind source `7018f36` / packet
  `b60c4298…7b18` passed independently at `cb9471b`, preserving all seven
  curriculum commitments exactly. Replay-authenticated capture-v3 source
  `0b697b6` / packet `d58a9308…c91` now proves every one of the 750,000 scan
  dispositions, but still awaits its fresh external marker. Label source
  `c98b608` separately binds finite fold/world work and is awaiting
  source-readiness review. Zero states, labels or models exist.
- **Search challengers:** the independently reviewed live-parent contract binds
  S3a/S3b to exact report-LCB and prevents old baselines from silently
  re-entering. S3b v2 remains closed on its 250k-node capacity failure. S3a's
  structured bury proposals beat every control on the selected 512-state
  objective, but the fresh 2,048-cluster complete-round screen terminally
  returned **SELECT NONE**: structured-minus-champion `+0.0464`, LCB
  `-0.0041`; aggregate `20609613…271f` and final `32156d79…c9ff` verified.
  This is the useful distinction the flywheel needs:
  candidate generation improved locally, while the composed policy did not
  earn confirmation. Close the consumed stream without tuning or retry; retain
  its disagreements as diagnostic/Teacher supply. Only a separately
  preregistered fresh larger design could revisit the near-miss.
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
  `17036e63…1385` fully recomputes. Claude independently passed that packet at
  `51a864c`. After S3a closed, exactly one 2,048-cluster Mini screen ran under
  admission `1d99bb55…bdbf` and receipt `20a420d2…5cc`. Terminal verification
  passed: treatment-minus-live report-LCB was `+0.086914 +/- 0.056166` signed
  levels with LCB `+0.030748`; matched-null-minus-champion was exactly zero.
  Aggregate `3c7f27b8…4268` and final `e188f7e8…0f2b` authorize only a fresh
  confirmation-packet review. Confirmation launch and deployment remain closed.
- **Small-endgame S3c:** the independently passed census contains 256 natural
  roots in each one-/two-/three-card band. One-card roots are forced moves;
  two-card roots have median/max 2/3 legal actions and three-card roots 3/7.
  Controller source `e9db4a2` / packet `f58d23b7…3874` passed component review,
  then a real admission test found its consumed lock dirtied Git and prevented
  runtime reopen. Replacement source `4ebcd09` / packet `cafbee43…f23e`
  repaired that seam and passed externally at `205b6af`. One later mechanics
  execution is eligible; zero solver work or strength evidence exists, and
  two-card work remains gated.
- **Human data / H0:** reviewed `human_v8` contains 2,830 plays and 45 buries.
  Bounded H0 v3 evaluates production, human, V11 and matched-random proposals
  under fixed candidate caps and disjoint shared-world folds rather than
  imitating people. Source `6977dbb` / packet `3f68dc6e…7fcf` passed component
  review but failed the real admit→runtime seam. Replacement source `4ebcd09` /
  packet `cf074871…35392` repaired that boundary and passed externally at
  `205b6af`. Its single T4 execution then completed 555/557 rows and terminally
  refused two seven-card follow throws whose live actions were absent from the
  generic analysis enumerator. Exactly 705,750 candidate-world rollouts were
  accounted, but no aggregate utility was published. The consumed namespace
  cannot retry or expose its 555 partial outcomes, so no human-derived proposal
  rule enters Stage C. Name-based historical splits still do not prove
  true-person independence; the forward-only HUMAN-C1 ladder owns people-facing
  strength.
- **Human loss forensics:** the initial aggregate claim that bots slough nearly
  twice as many points as humans was withdrawn after seat-count normalization
  (roughly 19 versus 17 points per seat-round). The surviving DEV signals map
  to S3a bury, S4 point-banking and S3c endgame work. A narrower defensive
  point-protection hypothesis remains, but H0 contains human decisions rather
  than the bot-seat mistakes around them. Baseline follow logic already tries
  to avoid points and the MC ballot already contains point-avoiding and
  point-seeking follows, so S5 begins with exact source-bound replay, legal
  alternative enumeration and current-champion reproduction—not a policy
  patch or strength run. Claude passed draft PR #4's replay logic. Commit
  `2351b36` adds the required lower-ranked-but-equal-point negative witness and
  makes the named `<`→`<=` mutation fail. Claude passed that boundary at
  `205b6af`; one score-free census freeze is eligible, but no census or
  treatment exists.
- **Throw sourcing S6:** KESP replay exposed three ballot surfaces that the live
  search does not guarantee: a top/near-boss bundle despite retained lows, a
  boss-component bundle despite ruff risk, and whole remaining plain-suit
  evacuation. These are proposal failures, not proof that the throws are good.
  Freeze exact fixtures and negative triggers, then compare a dedicated source
  with an equal-count/equal-work null. Keep S6 outside the already-frozen Stage-C
  population; a later Stage-C version may consume only a separately supported
  rule.
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
8. S3a showed that structured ballot proposals can improve a selected-state
   objective, then selected none in fresh full games. Preserve both facts:
   close the policy recipe, but use its disagreements to diagnose when better
   proposals fail to translate through search and continuation.
9. Human actions are candidate sources, not labels. Measure whether they add
   useful actions and survive counterfactual evaluation before imitation.
10. Bot-vs-bot paired evidence is the controlled strength gate; the product
    claim ultimately requires a blinded candidate-versus-champion comparison
    against the same human cohort plus an absolute experienced-human benchmark.
11. Human-loss aggregates generate hypotheses only after per-seat normalization.
    Replay bot decisions separately from H0, prove the legal counterfactual and
    reproduce it under the current policy before creating a new mechanism.

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

Teacher-v3 is intentionally absent from the model rows: it validated a labeler
and froze a Stage-C design, but it has not captured the 2,048-state Stage-C
asset, published labels, trained a checkpoint or produced a challenger. Those
are separate future milestones and must not be implied by calling the Teacher
audit “training.”

No checkpoint to date has been trained on label rows generated by the deployed
`mc-s0-report-lcb` policy. V11 and later learners were evaluated against that
champion, and the fresh Teacher audit used it as a reference, but neither act
created training targets. Reviewed Stage-C execution plus T4 training is the
first planned path that uses report-LCB gold on hard-tail rows.

Before any successor model experiment, checkpoint metadata must name and assert
the target, perspective, continuation policy, state sampler/horizon, ballot
version, and encoder version. A mismatch is an invalid run, not a negative ML
result.

---

## ROADMAP FROM HERE — live-champion flywheel

The baseline is the exact deployed `mc-s0-report-lcb` policy, not “MC” in the
abstract. Every challenger binds that parent plus a matched null at freeze
time. **T3 was the execution-ready strength bridge:** S3a is terminal negative,
S4 has now passed its fresh whole-game screen, and the human/Teacher/endgame
lanes became executable. It did not itself claim that a learned model became
stronger. **T4 is the first closed Teacher generation:** H0 has conservatively
closed without an admitted human source; now capture, label, train, integrate
and test one challenger end to end. Live order
and machine ownership remain in `BACKLOG.md`; this section owns the durable
decision tree.

### T3 decision tree

1. **Preserve the terminal S3a result.** The structured-bury 512-state
   mechanism passed, but the fresh 2,048-cluster full-game screen selected none.
   The exact policy recipe is closed without confirmation, tuning, retry or
   pooled inference. Its candidate disagreements may remain diagnostic input.
2. **Close S4's whole-game screen and preserve its next boundary.** The reviewed
   one-shot exact-state screen passed in both roles at terminal
   `abd9f36f…cdc00`. The repaired complete-round v2 controller and packet are
   frozen at `cad3992` / `17036e63…1385`, preserving natural trigger traffic
   against the exact live champion and an analysis-identical matched null.
   Claude independently passed the repaired packet at `51a864c`; exactly one
   2,048-cluster Mini screen ran under admission `1d99bb55…bdbf` and receipt
   `20a420d2…5cc`. It terminally measured `+0.086914 +/- 0.056166` signed levels
   against live report-LCB, LCB `+0.030748`, while the matched null was exactly
   flat. This authorizes confirmation-packet review only, not launch or deploy.
3. **Close H0 conservatively after its one reviewed execution.** H0 used the
   production ballot plus bounded human, V11 and matched-random proposals with
   disjoint common-world folds. Exact source `4ebcd09` / packet
   `cf074871…35392` ran once and terminally refused at 555/557 rows: two
   seven-card follow states falsified the analysis-ballot membership assumption.
   No aggregate utility was published, partial outcomes are closed, and no
   human-derived proposal rule enters Stage C. Preserve the failures as ballot
   regressions; do not retry this namespace.
4. **Implement capture from the passed Teacher Stage C v3 rebind.** Frozen source `20bdb95`,
   asset `1a29418` and packet `f213314a…3b4` define the 2,048-state split,
   ordinary anchors, hard-tail selection/report folds, 20/33 candidate caps,
   conditional mechanism cells and 10,494,720 maximum candidate-world work.
   `HeuristicBot` continuation keeps recursive MC at zero. Claude passed that
   curriculum design at `d92f595`. Source `7018f36` / packet `b60c4298…7b18`
   rebinds passed H0-v3/S3c-v2 while leaving every curriculum hash unchanged;
   its 105-test combined battery and external review passed at `cb9471b`.
   Replay-authenticated capture source `0b697b6` / packet `d58a9308…c91` is
   staged on Mini and awaits its exact v3 external marker. Label source
   `c98b608` is separately reviewable. After capture, independently review the
   2,048-state set, run the mandatory no-retained-outcome capacity preflight,
   then freeze and review the label packet. Labels and training remain closed
   until those gates pass.
5. **Run the passed S3c one-card controller only as T4 mechanics.** The score-free
   curriculum and source `e9db4a2` / packet `f58d23b7…3874` passed component
   review, but shared H0's unignored-lock reopen failure. Replacement source
   `4ebcd09` / packet `cafbee43…f23e` repaired it and passed at `205b6af`.
   One-card roots are forced, so a later run measures mechanics/capacity only;
   two-card action selection and every strength claim remain behind later gates.
6. **Route the loss-forensics gap through an S5 replay gate.** Bind the same
   frozen Fly source manifest, reconstruct bot-seat losing follows, enumerate
   all legal lower-point alternatives, record production-ballot membership and
   ask both the current champion and its rollout policy to replay each state.
   Close the hypothesis if the action was forced or no longer reproduced. Only
   a reproducible defect may open a separately reviewed treatment/null design.

T3 closed with S3a immutably negative, the now-positive S4 whole-game screen,
executable reviewed H0 and Stage-C contracts, and the leakage-safe
human ladder plus executable reviewed S3c feasibility asset. H0-v3, S3c-v2 and
the minimal Stage-C rebind all passed externally with zero outcomes, solver
sessions or captured states. S5 replay remains useful support work and does not
silently expand the T3 exit gate. A review is a routing boundary, not a
strength result.

### T4 — first closed stronger-Teacher generation

T4 must produce artifacts and a challenger, not another design-only audit:

1. preserve H0's terminal refusal: it admits no human-derived proposal rule,
   while its two missing-ballot throws remain regression and S6 sourcing input;
2. capture the frozen 2,048-state Stage-C asset, publish acceptance/rejection
   counters, and label ordinary versus hard-tail rows under their named budgets;
3. train at least eight seeds of separate play-ranking and calibrated-outcome
   heads, with bury separate, and choose the recipe/checkpoint only on CALIB;
4. open the untouched REPORT fold once; only a passing recipe becomes the one
   bounded proposal/ranking challenger;
5. run that challenger in a fresh paired whole-game screen against report-LCB
   plus a same-budget random/null arm; and
6. grow to 10k/50k states only if the 2,048-state learning curves and online
   screen show the intended signal. Otherwise classify the failure as data,
   target, capacity or composition and route a new mechanism instead of merely
   closing the family.

S3c runs in parallel as the small-domain search/Teacher lane. A passed
one-/two-/three-card exact-root policy can both improve late play directly and
produce privileged diagnostic targets for a cheap distilled endgame head.

### Lane A — improve search directly

- **S3a structured bury** tested the observed point-shy kitty policy. Explicit
  point/void/trump proposals improved the selected-state objective, but the
  full-game screen selected none. The policy recipe is closed; its useful
  residue is a set of proposal/continuation disagreement states for Stage C.
- **S4 point-banking continuation** passed both its exact-state mechanism screen
  and its sole fresh complete-round screen. Against live report-LCB it measured
  `+0.086914 +/- 0.056166` signed levels with LCB `+0.030748`, while the matched
  null was exactly flat. This is screen evidence, not confirmation. Freeze and
  review the 8,192-cluster confirmation packet separately; do not launch or
  deploy under the current goal.
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
| **Teacher Stage C v3 (design/rebind passed, not executed)** | Capture 2,048 fresh split-safe states; mix ordinary anchors with uncertainty/disagreement, human/V11/structured proposals, bury, point play and tiny endgames. Use cheap labels where certified and deeper disjoint root comparisons on the hard tail, without recursively calling MC inside MC. | Base `20bdb95` / `f213314a…3b4` freezes the exact 1,024/512/512 split, 20/33 caps and 10,494,720 maximum work. Rebind `7018f36` / `b60c4298…7b18` passed at `cb9471b` with the curriculum unchanged. **No impact result yet:** zero states, labels, checkpoints or challengers exist. | Implement/review capture and labeling; train at least eight seeds and require an untouched Teacher gate plus fresh whole-game win. |

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

#### H0 plan and version history

H0 is the project label for the first **human-action counterfactual pilot**.
It does not train a model and it does not assume the human move is correct. It
holds the historical decision fixed, adds bounded human/model/random proposals
to the production ballot, and asks which action survives fresh shared-world
evaluation.

The population is fixed across versions: 384 DESIGN and 128 disjoint AUDIT
play decisions, plus 36 DESIGN and nine AUDIT buries. The play sample keeps
every eligible late and off-analysis-ballot witness, caps repeated decisions at
eight per deal, and balances role/lead/follow as far as the small connected
human corpus allows.

| version | what changed | terminal status | lesson / next authority |
|---|---|---|---|
| **H0 v1** — exact `9770313`, packet `9ff160a9…247d3` | Froze the population, DESIGN/AUDIT split and no-outcome authority; intended to compare production, human, V11 and random proposals. | Split/design review PASS, then **SUPERSEDED PRE-EXECUTION**: the pinned V11 SHA named no executable artifact. No controller or outcome existed. | The sampling/split geometry survives, but v1 cannot parent execution. |
| **H0 v2** — exact `12dac55`, packet `2cccf580…8f2b` | Preserved the rows and bound the real `ep07.npz` V11 checkpoint, portable live report-LCB parent and disjoint 30-world selection / 300-world reporting idea. | Claude passed the identity repair at `9fdb67a`, then a score-free implementation audit **SUPERSEDED IT PRE-CONTROLLER**. “Analysis ballot” had no hard cap, report-LCB was conflated with downstream continuation, and requested candidate recall had no defined relevant-action universe. No outcomes existed. | V2 proved the real artifacts and parent could reopen; it did not define a finite executable estimand. |
| **H0 v3** — source `b02b6de`, packet commit `d6214ce`, packet `4d3f0a35…8cc3c` | Preserves every v2 play row, freezes all bury keys, caps the union at 17 play / 33 bury actions, draws V11 and random from the same novel pool, separates report-LCB root choice from `HeuristicBot` rollout continuation, uses three disjoint folds and caps total work at 1,329,210 candidate-world rollouts. | **TERMINAL REFUSAL / NO AGGREGATE UTILITY.** The replacement controller ran once, completed 555/557 rows and accounted 705,750 candidate-world rollouts. Two seven-card follow throws exposed that the generic analysis enumerator omitted live-ballot actions. | Close the namespace without retry or use of partial outcomes. Admit no human-derived proposal rule to Stage C; retain the two failures as ballot/S6 regression witnesses. |

After the one reviewed T4 execution, H0 publishes proposal-source membership
and survival, paired human/model/champion utilities, continuation ranking flips
and per-surface heterogeneity. Supported novel actions become proposal/prior
candidates; disagreement states enter Stage C's DESIGN mining. Unsupported
human moves remain useful error-analysis cases. Raw H0 actions never become
strength labels merely because a person played them, and H0 AUDIT never becomes
the final model-selection REPORT.

H0 answers “was the human's action a useful proposal?” It does **not** answer
“why did the bot seat lose that trick?” The latter requires replaying every bot
event from the source logs, because `human_v8/play_decisions.jsonl` indexes only
human actions. S5 therefore uses the same source-manifest hashes but publishes
a separate score-free bot-decision census: current ownership of the trick,
whether any legal action could win, point totals for every legal losing follow,
production-ballot membership, historical action and current champion/rollout
reproduction. Those human-game states remain DESIGN witnesses. A passing
trigger definition is transferred to fresh bot-generated CALIB/REPORT states;
the cited losses themselves never select or confirm a policy.

Use human data in three bounded stages:

1. **Freeze the honest split.** Player/deal connectivity leaves only five
   independent components, and two contain almost all rows. Use the large
   three-player/78-deal component for DESIGN, the separate one-player/28-deal
   component for AUDIT, and the remaining three tiny components only as a
   RESERVE diagnostic. Calling these data a meaningful three-way
   DEV/CALIB/REPORT split would overstate their independence; formal REPORT
   remains fresh synthetic/full-game and `HUMAN-C1` evidence.
2. **Preserve the bounded counterfactual's refusal.** H0-v3 ran once and stopped
   at 555/557 rows when two legal seven-card follow actions were not members of
   the generic analysis ballot. It published no aggregate utility. Do not retry,
   use the partial outcomes or infer quality from mere ballot membership.
3. **Use the conservative learning decision.** No human-derived proposal rule
   is admitted. Stage C keeps its frozen V11, structured and matched-random
   sources; raw behavioral cloning remains only a future initialization/style
   control. The two failures become exact ballot regressions and S6 design
   input. Promotion still requires fresh paired play against the live champion.

In parallel, use S5 replay to decide whether defensive point protection is a
real missing mechanism or merely a misleading observational label. If exact
replay supports it, Stage C gains a named hard-tail stratum and a separately
reviewed candidate/continuation source. If not, preserve the negative and do
not manufacture a “never discard points” rule that duplicates existing logic.
Draft PR #4 / source `c7bba40` contains the score-free replay census. Its logic
passed review, and commit `2351b36` adds the required equal-point-only negative
fixture plus mutation proof. Re-review remains before a deterministic freeze.

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
