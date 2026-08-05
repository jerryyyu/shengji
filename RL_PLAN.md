# RL Plan: training a learned Sheng Ji policy

## Objective and evidence standard

The product objective is **maximum verified Shengji strength**, under a correct
engine and a reproducible evaluator. Deployment latency is not a meaningful
tradeoff for the champion policy; compute is still recorded to attribute
experiments and understand operational cost. “Put RL inside search” is a
hypothesis, not the goal.
The research-superiority milestone remains beating the current `mc` policy in
a preregistered paired direct comparison; pool Elo is useful for screening but
cannot establish that claim.

Primary promotion metric: paired signed level utility by deal seed. Round
win-rate is secondary; a final deployment candidate gets a mirrored full-game
level-progression check. Every reported number is labelled **HYPOTHESIS**,
**SCREEN**, **CONFIRM**, or **REJECT**. The current fleet is an M4 Mac mini plus
an intermittently available MacBook Air; every manifest records the actual
worker/config rather than treating hardware as part of the claim. Toggle
results live in `AI_POLICIES.md`; run archives in `server/runs/`.

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
   term champion path is still hard-valid, calibrated belief sampling; a wide
   contextual lead ballot; a common-world rollout floor; then sequential root
   allocation. That directly attacks the measured sourcing gap without taking
   on hidden-information tree-search semantics.
2. **Use learned models first where the target is identifiable.** v11pair can
   rank/propose actions on its exact ballot. The next learned proposer should be
   trained on the winning ballot and split lead from follow. A value model must
   name its perspective, belief, continuation policy and horizon; otherwise it
   is not a leaf contract.
3. **Treat rollout-policy uncertainty explicitly.** After the ballot/dose tests,
   compare the incumbent single continuation against a small fixed portfolio
   (for example current Smart, conservative/tempo, and point-aggressive
   continuations) at equal total work. This is a robustness experiment, not a
   claim that a stronger standalone roller automatically makes stronger MC.
4. **Run faithful self-play probes, not another hybrid recipe bundle.** One
   Suphx-style privileged-policy curriculum and one DouZero-style direct-Q
   baseline should each get a tiny synchronous shadow run with invariant tests.
   Only a stable learning curve earns fleet-scale asynchronous actors.
5. **Belief-state search is the long-term tree-search lane.** Learn action-
   conditioned card ownership/ranges, calibrate them against held-out hidden
   deals and exact toy posteriors, then search public belief states with a fixed
   continuation-policy portfolio. ReBeL's convergence result is two-player
   zero-sum; Shengji should borrow the representation, not claim the theorem.

### Current DMC2 is not a valid Suphx or DouZero test

The negative result remains useful as a pipeline alarm, but it is not evidence
against the underlying RL families:

- **There is a defender-perspective sign defect.** `round_value()` and the
  oracle are attacker-perspective. `actor_batch()` signs terminal return by the
  acting seat, but ingestion computes `adv = signed_return - V_attacker` for
  every seat. A defender needs `-return - (-V_attacker)`, not
  `-return - V_attacker`. The unused `seat_l` list is consistent with a missing
  intended sign transform. This alone invalidates the dmc2 learning verdict.
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
- **Run integrity is not immutable.** Actor tasks receive the mutable
  `generator.pt` pathname while promotion overwrites it; candidate/generator
  gates use only 20 mirrored deals at a 55% threshold. Snapshot identity and a
  clustered evaluator must be fixed before interpreting another curve.

Verdict: preserve the spread alarm, replay cap, opponent-pool idea and run
bookkeeping, but do not resume AWAC or DMC on top of the current target path.
First add unit tests for attacker/defender target symmetry, role symmetry,
immutable actor snapshots and exact resume/replay behavior. Then compare the
two faithful microbaselines independently so a recipe bundle cannot hide which
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
| **v11pair** | Corrected v10 around the deployed decision: optimize `(q_i-q_0)` against `(Q_i-Q_0)` with Huber loss and boundary weighting, use the exact valued ballot at inference, and fit the 0.02 threshold on one split before reporting another. | `rl-override-v11pair` **CONFIRMED** 57.7% vs SmartBot (277-203, n=480, two disjoint blocks). Its 51.1% vs MC over 4,880 rounds used MC factories that silently discarded their seeds, so it is a SCREEN of approximate parity, not superiority or non-inferiority. Gating and root racing were not confirmed; using pairwise deltas as a leaf is invalid because cross-state scale is unidentified. | The only confirmed online gain in v7-v13, and the key lesson is exact objective/ballot alignment. Keep it as a direct override or root proposal/ranking candidate; it has not beaten MC. |
| **v12** | No model, checkpoint, or experiment used this number. | — | Skipped; do not infer a missing failure. |
| **v13abs** | Warm-started v7w and fit the value output to absolute 240-world means from 20,845 high-N states, using inverse-variance weighting. The actual target is raw-point action value under heuristic continuation, `Q^H(s,a)`, not a generic state value. The trainer updated the whole network, not only a detached head. | Offline SCREEN: unweighted RMSE improved `0.1052 -> 0.0699` and stored-ballot regret `1.478 -> 1.293`. Online leaf SCREEN: v13 and v7 each won 52.8%; v13 was `-0.004 +/- 0.206` versus the MC reference and v7 `+0.024 +/- 0.215`. The direct paired v13-minus-v7 contrast, computed from the shared JSONL, is **`-0.028 +/- 0.185`** (250 seed clusters; win-rate difference 0). There were two train/deploy shifts: 90% of training states were at ply <=15 while deployment followed four simulated tricks, and high-N labels covered `MCBot._candidates()` while the leaf maximized over `enumerate_actions()`'s pinned v1 ballot. | **NOT CONFIRMED.** It learned its offline labels better but did not improve the bot. This tested a doubly misaligned leaf deployment, not whether correctly targeted absolute value learning can help. |

The progression is therefore not “each version got stronger.” v7 reduced
teacher noise; v8 repaired the data and behavior-target contract; v9 tested
initialization, duration, and one flywheel turn; v10-v11 showed that an
implementation can make a valid hypothesis look inert until the trained
quantity and ballot exactly match deployment; v13 improved supervised fit but
exposed a state-distribution and value-contract mismatch. No v7-v13 model has
yet shown a verified advantage over `mc`; v11's confirmed gain over SmartBot is
the one positive learned-policy result.

Before any v14-style leaf experiment, checkpoint metadata must name and assert
the target, perspective, continuation policy, state sampler/horizon, ballot
version, and encoder version. A mismatch is an invalid run, not a negative ML
result.

---

## Current state — 2026-08-04

1. **`mc` remains the strength incumbent.** No standalone model or learned
   search hybrid has a verified advantage over it.
2. **v11pair is the learned line's one confirmed gain.** The direct SmartBot
   override wins 57.7% (n=480, two disjoint blocks). Its 51.1% vs MC is only an
   unseeded-MC SCREEN, and its gate and root-prior search variants have not
   survived paired confirmation. Use v11 only for relative decisions at the
   root; it is not an absolute leaf value.
3. **Neither learned leaf is promoted.** The historical v7 settling run
   reported 50.4% at n=1,200, but its leaf factory silently discarded policy
   seeds. The current hardened screen puts v7 at `+0.024 +/- 0.215` versus the
   MC reference. v13 fit its offline labels better but changed both the state
   and action-ballot distributions at deployment; it was
   `-0.028 +/- 0.185` directly versus v7 on the same 250 seed clusters.
4. **Hard-constraint sampling P0 passed; posterior fidelity is P1.** The clean
   `eea78d2` artifact found zero invalid worlds over 38,399 accepted reservoir
   draws and reached every enumerated legal world in 120/120 toy states. Count-
   matrix and capped-card weighting are still biased, so the old non-strict,
   capped-ballot, same-world-selected high-N labels remain a diagnostic
   reservoir rather than an oracle.
5. **The next compute is bounded and unblocked.** Run the preregistered fresh
   N=30 confirmation and the clean lead-ballot pilot; neither is permission for
   another bulk training corpus. The separate action-semantics gate remains
   open on the exact six-card tied-level decomposition witness in `BACKLOG.md`.
6. **DMC2 is implementation-invalid, not an RL rejection.** Its defender
   residual subtracts an attacker-perspective oracle with the wrong sign, and
   the method is neither Suphx's privileged-policy curriculum nor DouZero's
   role-specific direct-return baseline.

**Current decisions:**

| Question | Answer | Where |
|---|---|---|
| Does residual/override learning work? | **YES as an override of SmartBot**, once the pairwise target and ballot match — 57.7% vs smart, n=480 | 1i |
| Is direct v11 proven equal to MC? | **No formal confirmation.** 51.1% over 4,880 unseeded-MC exploratory rounds suggests parity; superiority is not shown. | 1i |
| Is the value-leaf hybrid stronger than mc? | **Not shown.** The historical n=1,200 arm was unseeded; the current hardened v7 screen is `+0.024 +/- 0.215` versus the MC reference. | above, 1 |
| Does a better value head make a better hybrid? | **No detected benefit yet.** v13 improved offline fit but its direct paired contrast versus v7 was `-0.028 +/- 0.185`. | lineage table |
| Does the flywheel work (train on hybrid data, get a better hybrid)? | **Not in the v9 attempt.** This is a pipeline result, not a general rejection of expert iteration. | 1b |
| Did v10res test residual learning? | **No.** It was a near-no-op with a train/play ballot mismatch; v11pair is the corrected test. | 1h, 1i |
| Is selective v11-gated MC ready? | **No.** T2 did not earn confirmation; the later T3 runner was invalid and halted. | 1l, 1m |
| Does the banker knowing its own burial help? | **No measurable effect** — 49.7%, CI [44.0, 55.3] | 1g, AI_POLICIES |
| Does rollout-policy strength matter? | **No** — tied twice, second time with a 93-Elo-stronger roller | AI_POLICIES |
| Did DMC2 disprove Suphx/DouZero-style self-play? | **No.** The defender oracle sign is wrong, the “oracle guiding” mechanism is different from Suphx, and the warm-started residual/dueling recipe is not a faithful DouZero baseline. | literature/DMC2 audit above |

**The through-line:** changing rollout or leaf evaluation has not improved MC;
correctly learning *relative root decisions* did improve SmartBot. The next
search question is therefore fixed-budget root allocation with common worlds,
not another rollout-policy swap and not forcing pairwise v11 into a leaf API.

**P0 fixed today (Codex):** BANKER_KITTY double-subtracted the burial and left
the banker's world sampler unable to build any world. gen-v4 predates that
defect according to its recorded `teacher_git`. Full write-up:
`incidents/2026-08-03-banker-search-disabled.md`.

---

## STATE OF PLAY (2026-08-04, day 5)

### 1. ROOT-PRIOR RACING — RETRACTED: did not replicate (2026-08-04 10:40)

I reported this as beating mc. **The paired confirmation refutes it**, and the
claim is withdrawn.

The confirmation ran all three arms on the SAME 250 mirrored deals, with a
manifest, per-seed records, and paired level utility clustered by seed — the
protocol Codex asked for:

| arm | win% vs mc | paired level utility/seed |
|---|---|---|
| race4 (net prior) | 49.8% [45.4, 54.2] | **−0.012 ± 0.209** |
| rand4 (RANDOM prune, the control) | 55.4% [51.0, 59.7] | +0.188 ± 0.224 |
| mcref (mc vs mc, sanity) | 49.6% [45.2, 54.0] | 0 by construction |

**The control was nominally higher, but neither arm cleared zero.** In the
screen it was the reverse
(race4 54.8% over 2,900 rounds, control 49.8% over 500). Both arms moved about
five points and swapped places, on a harness whose mc-vs-mc arm sits correctly
at 49.6%.

**What that means.** Block-to-block variance is far larger than the binomial
intervals imply, because rounds inside a mirrored pair and inside a seed
cluster are correlated — exactly Codex's objection that Wilson treats them as
independent. Five blocks agreeing at 54-56% felt like reproduction; it was five
draws from a distribution wide enough to produce that by luck. The paired
statistic, which is the one that respects the clustering, puts race4 at
−0.012 ± 0.209: a tie.

**Status: REJECTED as a strength claim.** Not "promising", not "needs more n" —
the honest reading is that nothing here beats mc, and the standing goal is NOT
met. If the idea is revisited it starts from scratch with the paired protocol
and a preregistered n, and any screen that disagrees with a paired
confirmation loses.

**The lesson is the one this project keeps re-learning at increasing cost.**
The vleaf 60% headline died the same way, the v11 52% died the same way, and I
still treated five consistent blocks as evidence rather than as five
correlated draws. Consistency across blocks is not independence.

### 2. Value-leaf hybrid: CLOSED — no verified edge over mc

`mc-vleaf-v7w-ep02` truncates MC rollouts after four tricks and scores leaves
with v7w's value output. Its original 60% and pool-leader headlines came from
invalid pooling. A later preregistered two-machine run reported 605-595 =
50.4%, but the post-run audit found that its leaf factory accepted `**kw` and
failed to forward them, leaving that stochastic arm unseeded. It is useful
historical evidence against a large effect, not a seeded confirmation of
equality.

The current hardened evaluator gives the v7 leaf 52.8% and
`+0.024 +/- 0.215` paired utility versus the MC reference. That does not show
superiority. v13, trained on high-N absolute `Q^H` labels, also failed to
improve it directly (`-0.028 +/- 0.185`). The strength path is retired unless
a correctly targeted leaf distribution and value contract earn a new test.

Production-ready regardless of the verdict: numpy inference
(`rl/npnet.py`), no torch in the image, 14ms/decision, identical play
verified vs torch.

### 3. Standalone policy line: still stuck — but the OVERRIDE line is not

Standalone nets remain ~38-48% vs mc across every lever tried: more data,
better-than-search labels (gen-v4), more epochs, a margin-aware target, and
warm-vs-scratch init. Codex's caveat stands: the 6-epoch v9 arms both peaked
at their last epoch and used different LRs, so warm-vs-scratch is "no DETECTED
difference", not an equivalence result.

**What changed on 2026-08-04:** the same nets, used as a learned OVERRIDE on
top of SmartBot rather than as a standalone policy, beat SmartBot 57.7% over
n=480. The signal was there all along; asking the net to pick from scratch was
the wrong question to ask it. That reframes the ceiling: it may be less about
what the net knows than about what it is asked to decide.

### 4. gen-v4: the dataset every current arm trains on

36,360 rounds / 1.96M decisions, teacher `mc-vleaf-v7w-ep02`, fast engine,
choice-only TRACTOR_LOCK rows included (19,691 per epoch). Proven clean of the
banker-search bug via its recorded `teacher_git` (367a822, seven hours before
the defect landed).

The earlier claim that `rl-v9warm` sat "27 Elo above rl-v7w" came from the
seeded pool, and pool gaps under ~40 Elo have since been shown unreliable —
the same pool put vleaf +32 above mc, while a later n=1,200 run with an
unseeded leaf arm landed at 50.4%. No direct seeded v9-vs-v7w duel has been
run, so that comparison stays open rather than counted.

### 5. Measurement discipline (all learned the hard way today)

- Anchor/pool opponents were UNSEEDED until 08-03: the same v7w anchor
  read 41% then 31%; the same vleaf pairing read 58% then 47.5%. FIXED
  (`play_pairing` seeds both sides; pairings now reproduce exactly).
- Consequence: every pre-fix single-pairing comparison under ~10 points
  is noise, including "v8 is below v7w" (retracted).
- Do not pool heterogeneous blocks as one binomial.
- A mid-run PROGRESS number is not a result.
- Verify the artifact, not the exit code (four silent no-ops today).

## KEY LEARNINGS (load-bearing; each cost real compute to buy)

1. **Sourcing beats preference.** Every hard-coded "play X first" rule
   measured ≤53% (ties); widening what the search *sees* measured 62%.
   Ballot coverage of human plays went 84.7% → 99.3% in one day
   (`scripts/audit_sourcing.py` is the tripwire). Same shape at the RL
   layer: ballots must be wide at *data generation*, then frozen.
2. **Label quality out-predicts architecture.** bc < distill < N=30
   textbook tracks the checkpoint ladder exactly; capacity (1024-trunk)
   and temperature sweeps were nulls; soft targets (T=0.05) were the one
   recipe fix that mattered (stochastic teacher ⇒ distribution targets).
3. **Ballot/encoding freeze.** Play-time enumeration must match training
   distribution byte-for-byte — the exhaustive-follows change silently
   collapsed a deployed net to Elo 798. Any change ⇒ regenerate,
   retrain, re-verify.
4. **The value pathway is fragile; ask the net small questions.**
   Raw-return regression on a warm start crushed action ordering (spread
   22.5 → 0.26, twice, alarm-verified); net-as-rollout-policy amplified
   tail errors (37% vs mc at 100x cost). Full-information oracle study:
   only 43-47% of outcome variance is predictable on its training
   distribution. The dmc2 collapse is additionally confounded by a defender-
   sign bug and a non-Suphx baseline, so it cannot establish a value ceiling.
   Ask one identifiable question at a time: relative root ranking, world
   likelihood, or a calibrated value under one named continuation policy.
5. **Warm starts are safe only under an unchanged objective.** v6→v6.1 (same
   distillation loss) was stable; BC→raw/residual Q regression destroyed the
   checkpoint. This is a warning about scale and objective shift, not a reason
   to require warm starts in a faithful from-scratch DouZero baseline.
6. **Strength overfits before val metrics notice.** v6cont: gates fell
   51/41→44/32 while val agreement moved 0.4pt. Model selection =
   per-epoch snapshot **strength probes**, never loss. Peak lands ~ep3-8.
7. **Small samples reverse.** 55% (n=40) → 37% (n=60) killed the v5
   hybrid; 54% (n=200) → 51% (n=400) killed PAIR_VOID_BOSS. Extensions
   are mandatory; and probes only compare *within* one seed batch —
   game-level and round-level rates are not interchangeable (games
   compound round edges: 52% rounds ≈ 88% games vs heuristic).
8. **Direct duels > transitive probes** for close calls (protocol below).
9. **Agreement ≠ strength**, measured twice: v6's val agreement froze
   while strength climbed; wide-ballot mc gained 12pts h2h with
   agreement flat (55%, leads 31% vs 30%). Agreement is a style/sanity
   metric — the tripwire, and the human-blend target — not a strength
   signal.
10. **Elo is pool-relative.** mc rated 1141/1104/1067 across pools with
    no code change. Only within-pool gaps, fixed-seed gates, and direct
    duels transfer between tables.

---

## RUN STATUS — 2026-08-04 22:15

The rewritten-sampler N=30 confirmation is preregistered and running on the
mini: one 504-cluster block, fresh 99M seeds, N=30-minus-N=10 primary, a true
same-policy/different-RNG null, no N=5 arm and no extension. The lead-ballot
pilot remains next. P0 sampler validity/support is closed; distribution
fidelity and the reopened six-card action-semantics witness are separate
correctness work. No bulk RL/data run is authorized by either screen.

The re-entry discipline applies to anything new: preregister the bar, seed both
sides through a factory that forwards kwargs, write immutable manifests and
per-seed records, and treat a first block as selection only.

## DECISIONS TAKEN (Codex, 2026-08-04 07:31 — answers to the standing questions)

These settle questions that had been open for a day. Recorded here because
they change what gets built, not just what gets said.

| question | decision |
|---|---|
| Standalone policy line | **Pause as a development line, keep as the cheap diagnostic/deployment baseline.** It already moved the Pareto frontier, so "stop" must not mean delete. |
| Primary metric | **Paired signed level utility** for promotion; round win-rate secondary; full-game level progression is the final deployment check. |
| Architecture-ceiling vs undertrained | A controlled DATA-SCALING study on independently evaluated high-N states, v1 vs richer encoder, ≥3 train seeds. A full-corpus run is earned only if untouched regret keeps improving with data. **More epochs on the same noisy labels cannot answer this.** |
| Direct-V target | A calibrated scoring-BRACKET distribution (or expected signed level utility) under one fixed continuation policy — **not `max_a Q`**, which inherits selection optimism and is not the value of the policy that actually continues the round. |
| My first-number habit | Label every number **HYPOTHESIS / SCREEN / CONFIRM / REJECT**; freeze one primary metric and one untouched report set; never extend a first block on reused seeds because its interval nearly crosses. |
| Silent fallbacks | **One bounded repository-wide sweep first**, converting each boundary into a strict invariant or counter, then site-by-site enforcement while touching code. A sweep without durable invariants decays; local-only work misses the next hidden boundary. |
| Frontend soak | Deterministic tests are strong enough for a RELEASE CANDIDATE. Run one bounded multi-tab reconnect/takeover/chat soak before production promotion — minutes, not a project — and it does not gate the ML stop decision. |

## ROADMAP FROM HERE (ordered by information per unit compute)

1. **Finish the two live champion-path screens.** Settle N=30 with the one
   preregistered online block. In parallel, fix the six-card action-semantics
   witness, then run the clean 512-state lead pilot across current, contextual-
   14, full-universe/high-compute, V3, random-fill and `MC-more` controls. The
   current sampler can select; a winning ballot arm must be re-priced after P1
   distribution calibration before its final online confirmation.
2. **Measure and correct the belief distribution.** Exact-enumerate toy
   posteriors, report TV distance/card-seat marginals/exchangeability, then
   weight suit-count matrices by their admissible per-code completions and
   sample capped fills uniformly. After the hard posterior is calibrated, fit
   an action-likelihood/ownership model only as a measured soft refinement.
3. **Turn the winning ballot into a learned proposer.** Cleanly relabel
   disagreement, late-ply and high-uncertainty states under one frozen
   `BallotSpec`; train separate lead and follow proposal/ranking heads; compare
   against contextual quota, random fill and equal-work `MC-more`. v11pair is
   an initializer/diagnostic only where its old ballot is exact.
4. **Test continuation robustness before a scalar leaf.** At equal total
   rollout work, compare the incumbent continuation against a preregistered
   small policy portfolio. Record per-policy action values and covariance. If
   no arm changes online strength, close this lane rather than train another
   generic leaf on heuristic-only outcomes.
5. **Run two faithful synchronous RL microbaselines.** Suphx lane: one policy
   objective with a scheduled privileged-information mask, plus a partial-only
   and simple-distillation control. DouZero lane: from-scratch role-conditioned
   Q networks, direct signed episodic returns, sequential action history and
   immutable actors. Unit-test role signs and snapshot identity; a 20–30 minute
   shadow must preserve action spread and improve a held-out fixed-policy metric
   before either gets fleet scale.
6. **Build belief-state search only after those contracts hold.** Represent
   public history, calibrated hand ranges and a small continuation-strategy
   portfolio. Start with root/subgame search and policy-preserving partner
   behavior. A calibrated bracket/level value may assist it, but must name the
   belief, role, horizon and continuation policy in checkpoint metadata.
7. **Operate the flywheel AutoGo-style.** Every run gets one immutable
   `ExperimentSpec`: hypothesis, code/data/ballot/encoder hashes, frozen actor
   paths, budget, primary metric, null and stop rule. Keep collect→train→evaluate
   synchronous until replay/resume is exact; only then let a dispatcher fill
   the fleet from a preregistered queue. Promotion remains a separate human-
   visible paired gate.

For online selection, paired signed level utility is primary because it is the
actual game objective; round win-rate remains the higher-power secondary
metric, and a final candidate gets a full-game confirmation. Standalone policy
scaling remains paused; only the two bounded, faithful self-play microbaselines
above may reopen it, and only after their implementation invariants pass.

## Training-data doctrine: spend compute vertically before horizontally

The important 2026-08-04 change was not simply generating more rows. The old
pipeline spent compute **horizontally**: it collected roughly 1-2 million
sequential self-play decisions and attached relatively low-dose N=10/N=30 or
hybrid-teacher labels. That gave broad trajectory coverage, but each close
action comparison was noisy, the natural deal stream overrepresented early
play, and the available targets were irrevocably restricted to the ballot and
sampler used during collection.

`highn_corpus` spent compute **vertically** instead. It rebuilt 20,000 fixed
states, evaluated every offered action over 240 shared hidden worlds, and
stored action means, candidate-0 paired differences, uncertainty estimates and
the raw state needed for replay. Common worlds make close actions much easier
to compare than independently sampled labels. This was a useful diagnostic
shift: it exposed the early-ply skew, quantified a low-N label ceiling and
localized much of the actionable forfeit to lead decisions.

It did **not** create a final oracle. Those labels use the pre-repair non-strict
sampler, the old finite ballot, raw points, heuristic continuation and
same-world selected maxima; the state distribution is overwhelmingly early.
They estimate the specifically named quantity `Q^Heuristic(s,a)` under that
contract, not generic state value or expected level utility. v13 fitting these
labels substantially better offline without improving online is the durable
warning: **higher precision cannot repair the wrong estimand, action set or
state distribution.** Keep high-N as a replayable reservoir and provisional
diagnostic set, not the foundation for an unqualified bulk retrain.

Three artifacts must remain separate:

1. A **state reservoir** stores reconstructable setup/history and a frozen
   deal-disjoint assignment, but no action scores. The planned deep-lead
   capture is initially this artifact, not training data.
2. A **counterfactual teacher set** fixes the ballot, belief sampler,
   continuation policy and utility target, then evaluates every compared
   action on common proposal worlds with disjoint report worlds. It stores raw
   per-world returns or sufficient paired statistics, not only the selected
   action.
3. An **episodic RL set** stores immutable actor identity, role-correct signed
   terminal returns and sequential public/action history. It must not be mixed
   with search-distillation rows as though their targets were interchangeable.

The next clean teacher data is therefore earned in this order:

1. retain the closed hard-validity/support certification while measuring and
   correcting posterior weighting;
2. use the lead pilot to select and freeze the proposal ballot;
3. freeze deal-disjoint DEV/CALIB/REPORT state assignments *before* labels are
   inspected, with explicit early/mid/late and attacker/defender coverage;
4. relabel the highest-information regions first: ballot disagreements,
   late-ply decisions and high-uncertainty states, using common proposal worlds
   and independent report worlds;
5. train separate lead/follow proposal or ranking heads and require untouched
   CALIB regret/recall improvement before authorizing bulk collection;
6. preserve REPORT for the single selected design and require a paired online
   gate before calling the new data strength-producing.

Every generated dataset must name and digest its state-selection rule, split,
`BallotSpec`, engine, sampler, continuation policy, target/perspective, world
budget, generator and source checkpoint. Incompatible shards are never merged
silently. Corpus size is not progress by itself; progress is lower held-out
decision regret under the deployment contract followed by verified online
strength.

## Evaluation asset inventory (rebuilt from disk 2026-08-05)

Evaluation sets are listed here because their provenance and intended use are
part of the learning contract, but they are **not training data**. In
particular, DEV may select one design, CALIB may judge that frozen design once,
and neither may be pooled into a teacher corpus. REPORT remains unselected and
unscored until a separately preregistered audit.

| artifact | size / identity | what it is | status / allowed use |
|---|---|---|---|
| `rl_data/deep_leads.v1.jsonl` + `deep_lead_split.v1.json` | 768 raw lead states; 256 each DEV/CALIB/REPORT; 48 split/trick/role cells x16; data hash `ffccfde64932eb3a` | Reconstructable state reservoir captured before ballot scoring. It supplies the late/deep coverage missing from the older corpora. | **FROZEN reservoir.** May build registered evaluation sets; never train from split identity or inspect REPORT outcomes. |
| `rl_data/pilot_dev512.v6.json` | 512 unique deals; hash `af78748586034f6f`; bands 170/171/171; size 0/72/98, 11/131/29, 152/19/0; roles 85/85, 86/85, 86/85; source 129/41/0, 17/154/0, 0/1/170 | DEV worksheet for the lead-ballot design screen. Frozen from clean `53d9b67` by a fail-closed freezer: size now DRIVES deal selection, and a shortage or replay error publishes nothing instead of a short file. | **0/512 scored, awaiting Codex gate PASS.** Do not score or train on it until then. Supersedes v5 (`097ea3851cd3bb9c`), whose dedup keyed on the marginal cell so 52/512 exact DEV states changed under row reversal. v3/v4/v5 are retained only as named test negative controls. |
| `rl_data/pilot_calib512.v6.json` | 512 unique deals, disjoint from DEV; hash `3872350f57a4dd60`; identical band/size/role allocation | Untouched holdout to judge exactly one frozen DEV-selected design. No action labels or scores. | **UNTOUCHED.** Do not tune, train, or score. Supersedes v5 (`00ca4de1915d8c4f`). |
| `pilot_{dev,calib}512.v4.json` | 512 + 512 planned, hashes pending | Promotion-grade successors with identical predeclared band-size marginals, exact role marginals, fail-closed publication and full 1,024-row replay/split/disjointness validation. | **NOT YET FROZEN.** They become the registered DEV/CALIB sets only after the live gate in `HANDOFF_ACTIVE.md` passes. |

The 512+512 design is sized for **selection followed by an independent
holdout**, not for a final strength claim. It should resolve a practically
meaningful paired offline effect, while a tiny edge may remain inconclusive.
The observed per-state paired variance must be reported; do not extend DEV
after seeing results. Full-game confirmation receives its own fresh-seed power
calculation, as required by `BALLOT_PLAN.md`.

## Training data inventory (rebuilt from disk 2026-08-04)

| dataset | size | what it is | teacher | used by |
|---|---|---|---|---|
| `rl_data/highn_corpus` | 20,000 states / 31 MB / **37.1M candidate evaluations** | each old-ballot candidate scored over 240 shared worlds, with marginal and candidate-0 paired SEs; raw states rebuild exactly. Non-strict sampler, same-world max selection, overwhelmingly early states, and raw-point labels | MCBot N=240, heuristic continuation | rebuildable state reservoir; provisional `Q^Heuristic(s,a)` labels for representation/calibration diagnostics, **not** an unbiased oracle, bracket target, or generic state value |
| `rl_data/gen_v4_all` | 205 shards / 245 MB / **~2.05M decisions** | the current corpus: hybrid-teacher values, wide v2 ballot, TRACTOR_LOCK rows recorded as choice-only. Provenance in META (`teacher_git` 367a822) | `mc-vleaf-v7w-ep02` | v9warm/v9scratch, v10res, **v11pair** |
| `rl_data/gen_v3_all` | 162 shards / 276 MB / ~1.62M | first fast-engine generation; superseded by gen-v4 | upgraded MCBot | v8a/v8b |
| `rl_data/gen_v3_quarantine` | 4 shards / 24 MB | **CONTAMINATED — never merge.** Written by orphaned workers running buggy code for 10h | — | nothing, deliberately |
| `rl_data/distill_n30` | 24 shards / 102 MB / ~1.2M | low-noise N=30 search distillation | upgraded MCBot | v7, v7w |
| `rl_data/distill` | 36 shards / 158 MB / ~1.8M | original N=10 distillation | MCBot (pre-CONTROL_LEADS) | v4, v5, v6, v6.1 |
| `rl_data/bc` | 35 shards / 160 MB / ~1.75M | SmartBot behaviour cloning, no values | SmartBot | ckpt_bc |
| `rl_data/oracle` | 1 shard / 10 MB / ~322k | full-information states + outcomes | self-play | oracle value study (43-47%) |
| `rl_data/human_v6` | 1 shard / **2,169 decisions** from 81 completed rounds | live human play, current v2 ballots (v1-v5 superseded) | live humans | blends, agreement audits |
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
- **Strength vs selection (v7w lesson, 2026-08-02):** STRENGTH claims
  come only from anchor pairings vs smart AND mc (round-level).
  Net-vs-net duels against the incumbent are for SELECTION among
  sibling checkpoints and tiebreaks — descendants exploit ancestors
  (v7w: 64.5% over v6, yet ~v6-level on anchors), so a family duel is
  never a ladder claim.
- **Partial-checkpoint protocol:** every snapshot gets (1) fixed-seed
  round-level probe vs current SmartBot (n=60, compare only within a
  seed batch) AND (2) a direct mirrored duel vs the incumbent best net
  (n=200). Blend checkpoints also get the human-agreement eval.
- Elo pools and sibling duels select candidates; direct seeded pairings against
  named anchors establish strength. Promotion to server default requires the
  declared non-inferiority/superiority gate plus a full-game mirrored match.
- A run with a missing/dirty manifest, reused output, seed-forwarding failure,
  impossible sampled world, silent fallback, or unreconciled counter is INVALID
  regardless of its score.
- Negative results are archived, not deleted (`server/runs/`,
  AI_POLICIES experiment log).

---
## ARCHIVE

Day-by-day chronology moved to `docs_archive/rl-plan-chronology-through-2026-08-03.md`
(2026-08-03). Conclusions live in KEY LEARNINGS above; that file is the record
of how each was reached, including the dead ends.
