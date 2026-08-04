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
**SCREEN**, **CONFIRM**, or **REJECT**. Hardware: one Mac mini (M4, 10 cores,
MPS). Toggle results live in `AI_POLICIES.md`; run archives in `server/runs/`.

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
4. **Correct belief sampling and evaluation gate more compute.** Normal MC
   still lacks pair-void enforcement. The high-N corpus used the old non-strict
   sampler, capped ballot, same-world selected maximum, early-state-heavy
   distribution, and raw-point `Q^H` targets. It is a diagnostic reservoir,
   not an oracle.
5. **Both machines are intentionally idle.** The next work is the ballot and
   representation/evaluator gates below, not another bulk training run.

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
   only 43-47% of outcome variance is predictable at all. Surviving
   net-in-search designs ask one bounded question: value at a truncated
   leaf (vleaf, in gate), world likelihood (belief sampling, queued),
   candidate priors (proposer, queued).
5. **Warm starts are safe iff the objective matches.** v6→v6.1 (same
   distill loss): fine. BC→DMC (raw returns): destroyed the checkpoint.
   v7-warm tests whether "init from incumbent" becomes standing policy.
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

## RUN STATUS — 2026-08-04 10:15

Jerry reactivated the goal ("use RL to beat MC — check codex and proceed") and
the stop that preceded it is superseded. Running now: the paired racing
confirmation (mini), the seeded Elo pool including race4 and its control
(mini), and the high-N corpus (Air, ~7,200/20,000).

The re-entry discipline still applies to anything new: preregister the bar,
seed both sides through a factory that FORWARDS kwargs, write a manifest and
per-seed records, and treat a first block as a screen.

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

## ROADMAP FROM THE CURRENT STOP (ordered by information per unit compute)

1. **Repair correctness and measurement boundaries.** Fix the belief sampler
   and `_seeded()` fallback, add strict counters/invariants, and build one
   manifest-driven paired evaluator. These are prerequisites, not experiment
   arms.
2. **Establish the deployment Pareto frontier.** Compare SmartBot, direct v11,
   MC N=5/10/20, and the settled v7 value-leaf speed arm on one reproducible
   strength/latency table. Do not include selective gates until their runner
   passes re-entry. Product promotion may use a preregistered non-inferiority
   margin plus speed; “beats MC” still requires superiority.
3. **Build a valid small high-N diagnostic set—then stop and inspect it.** The
   completed 600-state Air output came from a prototype and is debugging-only,
   not an unbiased reference or training corpus. `highn_build.py` uses the
   constraint-relaxing sampler; selects the apparent best and tests it on the
   same worlds (paired SE alone does not remove max-selection bias); truncates
   each round after early sampled decisions; uses potentially colliding
   `seed * 31 + ply` RNG ids; and has no tested round-trip loader. The completed
   artifact predates the sidecar manifest; current code overwrites that sidecar
   while still appending JSONL, so it can still mix runs. Before any rerun or
   evidentiary use, add:
   - a versioned schema and reconstruction test including initial banker,
     declaration timing/final declaration, phase, ballot hash, engine/config
     hashes, and exact seed ids;
   - strict legal-world sampling, disjoint selection/evaluation worlds (or a
     simultaneous multiple-comparison interval), and stored covariance or
     per-world differences;
   - deal-grouped splits plus explicit early/mid/late and score-bracket quotas;
   - exclusive output and a small cost estimate. Generate only a tiny frozen
     pilot after these gates pass.
4. **Representation diagnostic, not bulk training.** On that independently
   evaluated pilot, compare the current encoder against exactly one enriched
   encoder using identical model/initialization/data and at least three train
   seeds. Add trump-relative canonicalisation, ordered recent tricks,
   declaration owner/cards, pair-voids, team levels, and banker-private burial
   where legal. A full corpus is earned only if untouched high-N regret improves
   at least 10% in every seed.
5. **Root racing before tree search.** Give every candidate a small common-
   world rollout floor, then allocate the remaining fixed budget using v11's
   ranking plus empirical uncertainty. Compare against uniform allocation and
   simple complexity allocation at equal total rollout/time budget.
6. **A real absolute value model.** Predict the attacker-perspective scoring-
   bracket distribution or expected signed level utility under a named fixed
   continuation policy, with calibration metrics. Do not use noisy `max_a Q`
   as the target. It may share v11's trunk but needs a separate contract/API.
7. **Active labels, then AWAC; MCTS last.** Spend high-N labels on verified
   disagreements and consequential phase/score slices while retaining an
   anchor mixture. Resume AWAC only after role symmetry, immutable checkpoint
   promotion, strict fallbacks, and the active-label pipeline are tested.
   Revisit PUCT/MCTS only after both a calibrated absolute value and a correct
   belief model exist.

For online selection, paired signed level utility is primary because it is the
actual game objective; round win-rate remains the higher-power secondary
metric, and a final candidate gets a full-game confirmation. Standalone policy
development is paused until the representation diagnostic supplies a positive
offline result.

## Training data inventory (rebuilt from disk 2026-08-04; local + gitignored)

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
| `rl_data/human_v5` | 1 shard / **2,061 decisions** from 77 rounds | live human play, current v2 ballots (v1-v4 superseded) | live humans | blends, agreement audits |
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
