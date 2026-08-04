# RL Plan: training a learned Sheng Ji policy

## Objective and evidence standard

The product objective is **maximum verified Shengji strength per unit of
deployment latency and training compute**, under a correct engine and a
reproducible evaluator. “Put RL inside search” is a hypothesis, not the goal.
The research-superiority milestone remains beating the current `mc` policy in
a preregistered paired direct comparison; pool Elo is useful for screening but
cannot establish that claim.

Primary promotion metric: paired signed level utility by deal seed. Round
win-rate is secondary; a final deployment candidate gets a mirrored full-game
level-progression check. Every reported number is labelled **HYPOTHESIS**,
**SCREEN**, **CONFIRM**, or **REJECT**. Hardware: one Mac mini (M4, 10 cores,
MPS). Toggle results live in `AI_POLICIES.md`; run archives in `server/runs/`.

---

## WHERE THINGS STAND — 2026-08-04 08:10 (read this first)

1. **Direct v11pair is the learned line's first positive result and the current
   deployment-cost candidate.** `rl-override-v11pair` (SmartBot + learned
   pairwise override, no search) beats SmartBot **57.7%** (n=480). Against MC,
   all **4,880** rounds were mirrored but the MC factories were accidentally
   OS-seeded: the aggregate is 51.1%, useful **SCREEN** evidence of approximate
   parity, not a seeded confirmation. Production numpy latency is p50 0.25ms /
   p95 0.52ms versus MC's p50 77ms / p95 150ms on the measured mini.
2. **Combining v11 with search is unresolved.** The original gated online
   result (53.3% vs MC, n=300, about 55% table wall-clock) is a SCREEN. Its
   offline T2 did not earn confirmation and was itself over-interpreted: noisy
   max-Q labels favor high-candidate states and equal state-call rate was not
   equal compute. A later five-arm T3 runner violated its preregistration and
   was terminated after a partial full-MC arm. It produced **no result**. The
   runner has since gained a shared cheap policy, manifested exclusive output,
   stable RNG streams, paired seed analysis, and work-band enforcement, but it
   still lacks real artifact replay, complete all-seat fallback accounting,
   and a strict pair-void sampler. It has not earned a rerun.
3. **Use the model according to its contract.** v11pair is suitable as a direct
   action reranker and potentially a root proposer/prior or fixed-budget compute
   allocator. Its pairwise action deltas are not an absolute state value and
   therefore are not a valid MC/MCTS leaf. Replacing the rollout policy has tied
   twice and is not the next lever.
4. **Correctness and evaluation currently gate more compute.** The belief
   sampler's normal mode may use a final-retry suit-void relaxation and never
   enforces pair-voids. Strict mode now rejects/counts that suit relaxation.
   `tournament._seeded()` now dispatches by signature but falls through to
   `None` for seedless factories whose bot has no `rng`. The completed Air
   high-N artifact used the invalid prototype: no independent selection/eval,
   versioned round-trip schema, manifest, or strict-world evidence. No
   training, high-N rerun, T3 screen, or T4 confirmation is authorised today.

The machine is intentionally idle. A cheap policy or direct v11 winning the
strength/latency Pareto comparison is a success even if no RL-search design
ships.

**THE HYBRID IS NOT BETTER THAN mc. Settled 2026-08-03 23:20 at n=1200.**

The preregistered settling duel ran on both machines over disjoint independent
seed blocks, with the pooling rule and the bar declared before either result
existed:

| block | result | Wilson 95% |
|---|---|---|
| Air (seeds 7.1M+) | 303-297 = 50.5% | [46.5%, 54.5%] |
| mini (seeds 7.4M+) | 302-298 = 50.3% | [46.3%, 54.3%] |
| **POOLED** | **605-595 = 50.4%** | **[47.6%, 53.2%]** |

Level utility pooled: vleaf 680 vs mc 663 — no meaningful edge there either.
The two blocks agree to within 0.2 points, which is what a real coin flip
looks like. The original 60.3% headline was a mirage produced by invalid
pooling; the +32 Elo in the seeded pool was Bradley-Terry inferring a gap
from 120-round pairings that a 1200-round direct duel does not support.

**Consequence:** mc-vleaf-v7w-ep02 is retired as "the leading candidate." It
is an equal-strength, CHEAPER alternative to mc (truncated rollouts), which
makes it interesting for LATENCY, not for strength. Nothing should be adopted
or deployed on the basis of the old headline.

**Current decisions:**

| Question | Answer | Where |
|---|---|---|
| Does residual/override learning work? | **YES as an override of SmartBot**, once the pairwise target and ballot match — 57.7% vs smart, n=480 | 1i |
| Is direct v11 proven equal to MC? | **No formal confirmation.** 51.1% over 4,880 unseeded-MC exploratory rounds suggests parity; superiority is not shown. | 1i |
| Is the value-leaf hybrid stronger than mc? | **No** — 50.4% at n=1200, CI [47.6, 53.2] | above, 1 |
| Does a better VALUE HEAD make a better hybrid? | **No** — v7w 60%, v9warm 53%, v9scratch 48% on the same seeds. The best head is the OLDEST. | 1f |
| Does the flywheel work (train on hybrid data, get a better hybrid)? | **No** | 1b |
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

### 1. Value-leaf hybrid: MEASURED EQUAL TO mc (n=1200) — retired as a strength candidate

`mc-vleaf-v7w-ep02` = MC search, rollouts truncated at 4 tricks, leaves
scored by rl-v7w's VALUE head. It **tops the seeded pool at Elo 1151**
(mc 1119, smart 1093, rl-v9warm 1069, rl-v7w 1042, heuristic 1000).

**But it is not proven superior to mc** (Codex ruling, 18:20, accepted):
- The only corrected-protocol DIRECT evidence is the seeded pairing
  **64-56 = 53.3%, Wilson 95% CI [44.4%, 62.0%] — the interval INCLUDES
  50%.**
- The +32 Elo is an INDIRECT Bradley-Terry estimate, not a direct win.
- The earlier "404-316 = 56.1%, 3.3 sigma" pooling was **invalid**: it
  mixed mirrored seed clusters, reused/overlapping seed blocks, a
  sequentially extended test, and two explicitly unseeded runs.
- Earlier headlines in this file claiming "ADOPTED", 60.3%, and Elo 1163
  have been REMOVED. They were produced under the unseeded protocol.

**Settling experiment: COMPLETE 2026-08-03 23:20 — 605-595 = 50.4%, CI
[47.6%, 53.2%], n=1200 pooled over two disjoint blocks. VERDICT: not
distinguishable from mc.** Design as preregistered:
`scripts/vleaf_settle.py`, 300 independent mirrored clusters per machine on
disjoint seed blocks (Air 7.1M+, mini 7.4M+), per-seed JSONL, paired level
utility alongside round wins. The bar is declared in the script's docstring:
Wilson lower bound >50% means genuinely ahead, >=55% makes it an adoption
candidate (Jerry's call), an interval spanning 50% retires the "seeded-pool
leader" framing. Equal-wall-time is satisfied by construction — vleaf
truncates at 4 tricks and is the CHEAPER bot per decision.

Production-ready regardless of the verdict: numpy inference
(`rl/npnet.py`), no torch in the image, 14ms/decision, identical play
verified vs torch.

### 1b. FLYWHEEL TEST: NEGATIVE (2026-08-03 20:30)

v7w's value head generated gen-v4; v9warm learned from gen-v4. Does
v9warm's head make a BETTER hybrid than the head that produced its
training data?

**No.** `vleaf(v9warm-ep05)` vs mc = **64-56 (53%)** on the same seeds
where `vleaf(v7w-ep02)` scored 60%. Same seeds, same protocol — the new
head is no better, possibly slightly worse (well inside noise either
way). So one turn of the loop produced no compounding: a stronger
teacher yielded a student whose VALUE HEAD is not a stronger evaluator.

This is the single most informative negative of the day. The
expert-iteration flywheel requires each turn to improve the evaluator;
this turn did not. Either the value head is at its own ceiling
(architecture/encoding), or one generation is too small a step to see,
or gen-v4's labels are not actually better despite coming from a teacher that
was believed stronger at the time. The later n=1,200 duel settled that teacher
at 50.4% vs MC: equal, not stronger.

### 1c. Epoch count: SETTLED — strength peaks near epoch 8

v9warm-16 probe curve: ep05 56%, **ep08 60%**, ep11 56%, ep13 54%,
ep15 52%. A clean rise-and-fall, so the 6-epoch arms WERE undertrained
and 16 is past the peak. Best snapshot anchors: **56% vs smart** (the
best any standalone net has managed) and 37% vs mc. Standing recipe:
~8 epochs with per-epoch snapshot-probe selection.

### 1d. LABEL-NOISE DIAGNOSTIC — the student is below same-teacher repeatability; cause unresolved (2026-08-03 21:00)

120 frozen real decision states, 8 independent N=30 teacher seeds each,
plus an N=200 reference:

| measurement | value |
|---|---|
| teacher self-agreement (modal share of 8 seeds) | **78.5%** |
| ONE teacher sample vs the N=200 reference | **75.2%** |
| student (v9warm16-ep08) vs the same reference | **55.8%** |
| states where the 8 teacher seeds disagreed at all | **63.3%** |

**Interpretation:** the student is about 19 points below one sample of the same
teacher when both are judged against an N=200 estimate. This shows an
unexplained imitation/generalisation gap; it does **not** prove that the labels
are unbiased or that capacity alone can recover it. The N=200 reference shares
the same rollout policy and currently non-strict belief sampler, and 63% of
states show teacher disagreement.

This argues AGAINST an architecture-ceiling conclusion and FOR the next
rungs of the diagnostic ladder: optimizer/capacity sanity on a small
clean set, then the representation test (does adding the banker's buried
cards, declaration owner, pair_void, ordered history and team levels
close the gap with the SAME model?). It also strengthens the case for
residual distillation: predicting Delta from the baseline is a far
easier target than reproducing an absolute ranking through this much
label noise.

### 1e. MEMORISATION SANITY — optimizer can fit selected rows; generalisation remains open
(2026-08-03 21:30, diagnostic ladder rung 2)

Overfit test: 6,000 UNAMBIGUOUS rows (teacher's best beats second by
>=8 points, so the label is not sampling noise), current architecture,
lr 1e-3, 60 epochs.

**Final train accuracy: 99.6%.**

The model can memorise selected high-margin labels almost perfectly. That
rules out a gross implementation failure on this subset; it does not rule out
an architecture, regularisation, optimization, or representation limit in
out-of-sample generalisation. Combined with 1d, the main candidates are:

1. **Representation** — the observation may not carry what is needed for
   the decisions the net gets wrong (missing: banker's buried cards,
   declaration owner/cards, pair_void, ordered recent history, team
   levels; and no trump-relative canonicalisation).
2. **Learnability of the noisy majority** — the net fits confident rows
   but the other ~63% of states, where the teacher disagrees with
   itself, may be irreducibly ambiguous at N=30.

Next rung: the representation test — same model, enriched observation on
a diagnostic set. If added information cuts high-N regret, it is an
ENCODING ceiling, not an architecture one.

### 1f. VALUE HEADS ARE INTERCHANGEABLE (2026-08-03 22:00)

vleaf tested with three different value heads on the SAME seeds:

| value head | vs mc |
|---|---|
| rl-v7w-ep02 (the original) | 60% |
| rl-v9warm-ep05 (trained on hybrid-teacher data) | 53% |
| rl-v9scratch-ep05 (cold-trained, same data) | **48%** |

All three within ~12 points of each other on n=120, i.e. no head is
distinguishable from another, and the best is the OLDEST. Combined with
the flywheel negative (1b), this says the hybrid's strength does not
come from the quality of the value head — any competent evaluator seems
to do. That is a different, cheaper story than "we need a better net",
and it predicts the direct-V head will matter more for SPEED than
strength.

### 1g. RETRACTION: the kitty duels measured the wrong thing (2026-08-03 22:15)

Codex found that BANKER_KITTY double-subtracted the burial and left the
banker's world sampler unable to build ANY world — 0/20 on every seed. The
banker fell through to candidate 0, i.e. no search. The three duels reported
at 21:05-21:15 (50%, 46%, 54%) therefore compared a search-disabled banker
against a searching one, and say nothing about whether kitty knowledge helps.
Retracted. RE-RUN on fixed code (22:25): 149-151 = 49.7%, Wilson95 [44.0%, 55.3%] over n=300 — kitty knowledge makes no measurable difference to strength, so the flag stays ON purely because it is true information, not because it wins games. gen-v4 is clean (its
teacher_git predates the bug by seven hours). Full write-up in
incidents/2026-08-03-banker-search-disabled.md.

Worth noting what the accident measured instead: with the banker playing
*without search*, the side still went roughly even (299-301 pooled over 600
rounds). That is a third independent hint in the same direction as 1f and the
mc-smartroll tie — the search machinery around this game may matter far less
than its per-decision cost implies. It is a hypothesis, not a finding: the
comparison was never designed and the banker is one seat of four.

### 1h. v10res: the CHECKPOINT is rejected, the IDEA is untested (2026-08-03 23:50)

I originally ledgered this as "residual distillation REJECTED" on a duel
result (47% vs smart). Codex's post-mortem shows that was the wrong reading,
and I accept it: **v10res is a near no-op, so the duel could not have measured
the idea.** At the deployed 0.05 gate it overrides ~1.3-1.5% of states where
the teacher overrides ~15%. A policy that almost never fires necessarily plays
like SmartBot and necessarily scores like SmartBot.

Offline evidence (`scripts/residual_eval.py`, run on exactly the two shards
distill_train withholds, n=1491 valued states):

| metric | v10res | trivial baseline |
|---|---|---|
| pairwise delta RMSE | 6.1995 | 6.2112 (predict zero) |
| regret vs teacher-best @0.05 | 1.924 | 1.965 (always candidate 0) |
| override precision / recall | 68.3% / 75.9% (argmax, ungated) | — |

It beats "predict no override" by 0.2%. That is weak, badly calibrated signal
— not nothing, and not a refutation.

**Four implementation defects mean the strongest formulation was never
tried** (Codex): `--residual` transforms targets to Q(ai)-Q(a0) but the model
still scores rows independently and is never told what a0 was; the loss is
unweighted MSE with no ranking or threshold awareness around the consequential
+5 boundary; training reports agreement from the POLICY head while deployment
gates on the VALUE head; and collection used `MCBot._candidates()` while
`RLOverrideBot` infers over `enumerate_actions()` — a train/deploy ballot
mismatch of exactly the kind that produced Elo 798.

The registry alias also pointed at ep05 while the battery measured ep09, so
anyone playing `rl-override-v10res` got a different net than the one reported.
Fixed.

**Gate for the successor arm, declared now:** pairwise RMSE below the zero
predictor AND regret below always-candidate-0, at a threshold chosen on a
validation split rather than the reported one. Only then does it earn a seeded
duel. If a corrected arm fails offline, residual learning gets parked with an
honest "tried properly, did not work."

### 1i. RESIDUAL/OVERRIDE LEARNING WORKS — beats smart; MC parity is provisional (2026-08-04)

The first positive result from the learned line, and it came from fixing the
implementation rather than from more data or more epochs.

**vs SmartBot — its declared bar, cleared:** 277-203 = **57.7%** (n=480, two
disjoint seed blocks agreeing to 0.1 points, Wilson [53.2%, 62.0%]). v10res
scored 47% on the same bar.

**vs mc — NOT BETTER (and the protocol claim is retracted):**

| block | seeds | result |
|---|---|---|
| 1-6 | 3.3M / 9.2M / 10.5M / 11M / 12M / 13M | 52.2 / 53.0 / 51.3 / 51.0 / 50.9 / 50.6% |
| **pooled** | disjoint | **2085-1995 = 51.1%, n=4080, Wilson [49.6%, 52.6%]** |

**RETRACTION (Codex, 2026-08-04): these blocks were NOT seeded.** `_seeded()`
calls `make(seed=s)`, but every duel script passed
`lambda **k: make_bot("mc")` — a lambda that accepts a seed and silently drops
it — so the TypeError fallback never fired and every MC opponent ran on OS
entropy while the logs claimed a reproducible seeded protocol. This is the
SAME defect as the unseeded-anchor incident of 08-03, reintroduced one layer
up at the call site by the fix for it.

What survives and what does not:
- **A useful screen survives, not a confirmation.** Unseeded opponents add
  uncontrolled variance while mirrored deals still control deal luck. The
  result suggests approximate parity and clearly does not establish
  superiority; it cannot support a reproducibility or formal non-inferiority
  claim.
- **The protocol claim does not.** This was exploratory evidence, not the
  declared reproducible confirmation, and JOBS' claim that block 6 was
  "deterministic, so the machine does not matter" was simply false.
- The v11-vs-Smart result is unaffected: SmartBot is deterministic.

`make_bot` and `tournament._seeded()` now dispatch by factory signature rather
than catching constructor `TypeError`. The boundary is still open in two new
ways: `_seeded()` falls through to `None` when a seedless factory returns a bot
without `rng`, and the actual `v11_extend.py` / `gate_duel.py` lambdas still
accept `**k` but fail to forward it to `make_bot`. Their regression test uses a
different, correctly forwarding lambda. The end-to-end repeat test also
compares aggregate scores rather than per-seed/per-flip records. Do not call
the general harness repaired yet.

One more block completed after the retraction (409-391 = 51.1%, n=800), which
was ALSO launched before the fix landed and is therefore also unseeded. It
agrees with everything else. Across 4,880 exploratory rounds the estimate has
not moved off ~51%: v11pair is **plausibly near MC**, but this remains a
SCREEN. A genuinely seeded confirmation has not run; do not spend it merely to
turn an unpromising superiority hypothesis into a more precise tie unless a
deployment decision requires a formal non-inferiority bound.

**What fixed it vs v10res (47% vs smart):**

1. Optimise the DEPLOYED quantity. v10res regressed rows independently and was
   never told what a_0 was, so it never learned `q_i - q_0` — the thing the
   override rule gates on.
2. Match the ballot. Collection valued `MCBot._candidates()`; inference
   enumerated `enumerate_actions()`. **11 of 12 decisions enumerated
   differently** (13 vs 26 candidates on seed 5) — the Elo-798 failure again.
3. Fit the threshold off-split (0.02 on half A, reported on half B).

None of that is scale. The signal was present in v10res's data all along.

**Production-capable inference path** (measured 2026-08-04): numpy, no torch,
**p50 0.25ms / p95 0.52ms** against MC's 77/150ms in the current deployment
table; 2MB weights; 33MB RSS; 33ms cold start;
parity with torch verified on 90 real decisions (max diff 7.5e-8, zero argmax
disagreements) from committed fixtures. Production promotion still needs the
bounded frontend soak and an explicit decision about whether provisional MC
non-inferiority is sufficient. It is a cost/latency candidate, not a proven
strength upgrade.

### 1k. The gated variant: encouraging online SCREEN, not a strength result (2026-08-04)

`mc-gate-v11pair` uses the net's delta as a detector of high-predicted-gain
states and spends search only on the ~12% it flags: **160-140 = 53.3%** vs MC
(n=300, CI [47.7%, 58.9%]). The “55% wall-clock” figure was extrapolated from
a separate timing run, not measured as an interleaved equal-budget comparison.
This is hypothesis-generating only.

Calibration behind the design (held-out gen-v4, gain from acting on the net vs
keeping SmartBot's pick): **+3.23 / +1.51 / +0.31 / -0.02** as confidence
falls. Note this INVERTS Codex's proposal, which was to act when confident and
search when unsure: acting on the net still carries ~2.6 regret against the
search's best even at high confidence, so gating that way trades strength for
speed. Detecting where the decision MATTERS is the useful direction.

A first read of that calibration looked like the signal was anti-calibrated —
high-confidence buckets showed higher absolute regret. That evaporated once
regret was compared against the right baseline within each bucket: those are
simply higher-stakes states. Worth recording as a near-miss.

### 1l. T2 did not earn confirmation; what candidate count explains is unresolved (2026-08-04 05:50)

Codex's overnight plan required the stakes-gate to beat trivial alternatives
offline, at the SAME search rate, before earning a 1,000-cluster confirmation.
It does not. `scripts/gate_offline.py`, 3,000 held-out states, three blocks:

| search rate | v11 vs random | v11 vs candidate-count |
|---|---|---|
| 5% | +5.8 to +8.0% | −3.8 to +2.4% |
| 12% | +14.5 to +18.1% | +3.8 to +8.8% |
| 25% | +28.4 to +33.4% | +6.6 to +11.6% |

Bar was ≥15% against BOTH, in every block. **It clears random comfortably at
25% but never clears candidate-count at any rate.**

My first reading — "counting candidates captures most of what the net knows" —
**was stronger than this screen can support**, and Codex is right to push back
(07:31). Four reasons it cannot carry that conclusion:

1. `forfeit` is `max_i Q_i − Q_0` over NOISY gen-v4 teacher estimates, and the
   max of noisy estimates carries a winner's-curse bias that GROWS with the
   number of candidates. So candidate count is mechanically correlated with the
   very target used to judge candidate count. The oracle headroom inherits the
   same bias.
2. Matching the FRACTION OF STATES searched is not matching compute — search
   cost scales with candidate count, so the ncands gate deliberately selects
   expensive states and 12% vs 12% is not equal work.
3. The "three blocks" are `array_split` over two validation shards, not
   independent shards, with no calibrate-on-A / report-on-B split.
4. Candidate-count ties are broken by input order.

The docstring also promised a bootstrap interval the script never computed —
my own documentation describing an analysis that did not exist.

**What survives:** the operational verdict. The gate did not earn a
1,000-cluster run, and that is a stage-T2 screen result, not a scientific
conclusion about what the net knows.

This does not touch the override result (57.7% vs smart stands); it says the
*gating* application is weakly motivated. And it explains why the online screen
looked encouraging at 53.3%: spending search on high-branching states is a
plausible explanation to test, not an established substitute for the network.

The screen suggests possible but **unquantified** headroom: its 766/1,402
“oracle” comparison uses the same selected maximum of noisy labels and is not
true opportunity. Retain those numbers only as biased diagnostics.

The operational decision was “no 1,000-cluster confirmation.” A small online
diagnostic was subsequently proposed, but its implementation failed preflight
and was halted as described next. There is no current T3 or targeted-detector
authorization.

### 1m. T3 implementation was invalid and the partial run was terminated (2026-08-04 07:48)

The five-arm runner was committed and launched despite its no-go review. It
was stopped after calibration and roughly 50/300 rounds of the full-MC arm;
the partial log and a separate three-cluster JSONL smoke are quarantined and
must not be combined, extended, or interpreted.

Blocking defects:

- v11 used a learned cheap action while candidate-count/random fell back to
  SmartBot, confounding the gate with the skip policy;
- no manifest, run id, fallback field/counter, paired clustered analysis, or
  exclusive output existed;
- “strict sampling” could not detect the sampler's deliberate final-retry
  void relaxation or missing pair-void enforcement;
- timing excluded gating/ballot work, loaded Torch rather than the production
  numpy policy, and hot-loop counters changed MC's measured implementation;
- the compute band was reported but not enforced as an exit condition.

The random-calibration direction was fixed before the long launch, but the
other validity defects remained. A future root-allocation screen must first
replay 10 clusters byte-identically (excluding timing), use one identical cheap
policy across gates, isolate RNG streams, produce an immutable manifest plus
exclusive per-seed/per-flip JSONL, reconcile all counters, and fail on any
impossible-world fallback. Only then may a separately preregistered
150-cluster diagnostic be considered.

### 1n. HIGH-N PROTOTYPE SCREEN: the 2.8-point headroom claim is not established (2026-08-04 08:14)

The prototype evaluated each candidate on 240 shared worlds for 600 raw
states, then analysed the 148 rows where its selected best beat candidate 0 by
more than two paired SE. It reported:

| policy | mean regret vs selected N=240 best | picks that selected best |
|---|---|---|
| SmartBot (candidate 0) | 5.066 | 0.0% (by construction) |
| heuristic | 4.946 | 1.4% |
| mc N=10 (deployed) | 2.803 | 23.6% |
| mc N=30 (label teacher) | 2.419 | 30.4% |
| v11 override | 3.025 | 29.7% |

These are useful debugging numbers, but they do **not** establish deployable
headroom, a stronger teacher, a label ceiling, or a calibration-only failure:

1. The apparent best candidate and its significance were selected and scored
   on the same worlds. Paired SE reduces variance of a fixed comparison; it
   does not correct a maximum selected among up to 14 noisy candidates. The
   bias cannot “inflate every regret equally” because the policies choose that
   selected noisy argmax at different rates.
2. N=240 is a more precise estimate of the same determinized, heuristic-
   continuation surrogate. It has not beaten N=10 in a correct online pairing
   and is not game-strength ground truth. A distilled model can also outperform
   a stochastic teacher by averaging label noise, so “imitating MC caps the
   learner at MC” is not a theorem or a diagnosis supplied by this screen.
3. The artifact used non-strict worlds and no pair-void constraints. It was
   generated before the later sidecar-manifest patch and records no fallback
   counters. The current sidecar still overwrites while JSONL appends, so it
   does not prevent mixed runs.
4. The state sample is early-game-biased: 575/600 rows have `ply < 20`, the
   remaining 25 have `20 <= ply < 40`, and none are later; there are only 150
   deals because collection stops after four accepted states per deal.
5. `highn_analyze.py` silently skips replay/policy errors and off-ballot choices
   and originally restricted evaluation to the same 148 selected rows. Report
   coverage and failures per policy; never let them change denominators.

A read-only smoke did reconstruct all 600 stored candidate lists and core
turn/banker fields with zero declaration exceptions. That makes the raw format
promising, but it is not a committed schema/round-trip test.

**What survives:** a **HYPOTHESIS** that independent high-N root labels may be
useful and that v11's error distribution deserves study. Test it with strict
worlds, phase/score quotas, deal-disjoint selection and report world sets,
familywise or simultaneous uncertainty, and a final seeded online comparison.
The partial 20,000-state corpus and m0 duel launched from this analysis were
stopped and are not results; active high-N labelling is not authorised yet.

### 1n. ONE-PLY HIGH-N REGRET DOES NOT PREDICT ONLINE STRENGTH (2026-08-04 08:40)

An experiment that failed usefully, and the failure constrains how the whole
high-N programme can be used.

The reference said v11's problem was calibration, so I refitted its decision
rule against those unbiased labels, splitting states by seed and reporting only
on the half never used for fitting. The fitted rule was to REMOVE the margin
entirely (trust the net's argmax):

| rule | offline regret, significant states | offline regret, ALL states |
|---|---|---|
| v11 @0.02 (deployed) | 2.870 | 1.141 |
| v11 @0 (fitted) | **2.152** | **1.132** |

Then the online duel: **235-265 = 47.0%** vs mc, Wilson [42.7%, 51.4%] — where
the deployed 0.02 rule scores ~51%. **The offline improvement reversed
online.**

**Why this matters more than the individual result.** The reference value of a
candidate is its expected outcome when the HEURISTIC plays the rest of the
round. A policy that deviates from the heuristic more often drifts further from
the states where that estimate is accurate, so one-ply regret systematically
flatters aggressive overriding. Errors also compound over ~25 decisions in a
way a single-decision metric cannot see.

This is Codex's warning about `max_a Q` arriving empirically: selection
optimism plus a continuation-policy mismatch. Its recommendation — predict a
calibrated bracket distribution or expected signed level utility **under one
fixed continuation policy** — is exactly the shape that survives this finding.

**Consequences, adopted:**
1. Offline high-N regret is a SCREEN. It may reject a rule; it may not promote
   one. Only a seeded online duel promotes.
2. The one-ply argmax is the wrong training target. The corpus being generated
   is still the right asset, because what it actually stores IS the expected
   outcome under a fixed continuation policy — the target Codex recommends for
   a direct V head — but training to imitate its per-decision argmax would
   repeat this failure at scale.
3. The deployed margin of 0.02 stays. It was fitted on biased estimates and is
   apparently not optimal, but nothing measured so far beats it online.

### 2. Standalone policy line: still stuck — but the OVERRIDE line is not

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

### 3. gen-v4: the dataset every current arm trains on

36,360 rounds / 1.96M decisions, teacher `mc-vleaf-v7w-ep02`, fast engine,
choice-only TRACTOR_LOCK rows included (19,691 per epoch). Proven clean of the
banker-search bug via its recorded `teacher_git` (367a822, seven hours before
the defect landed).

The earlier claim that `rl-v9warm` sat "27 Elo above rl-v7w" came from the
seeded pool, and pool gaps under ~40 Elo have since been shown unreliable —
the same pool put vleaf +32 above mc, which a 1200-round direct duel then
measured at 50.4%. No direct seeded v9-vs-v7w duel has been run, so that
comparison stays open rather than counted.

### 4. Measurement discipline (all learned the hard way today)

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

## RUN STATUS — 2026-08-04 08:10 (supersedes the earlier T0-T4 authorization)

**RUNNING: nothing.** The attempted T3 screen was invalid and terminated. No
substitute high-N generation, training, duel, or confirmation is authorised.
The older T0-T4 sequence remains useful as an incident record; its actual
status is:

| stage | status | authoritative reason |
|---|---|---|
| T0 — measuring instrument | **INCOMPLETE** | Signature dispatch no longer swallows constructor `TypeError`, but `_seeded()` returns `None` when a seedless factory returns a bot without `rng`; the exact exploding-factory boundary is untested and repeat evidence is aggregate-only. |
| T1 — trustworthy evaluator | **PARTIALLY BUILT / NOT PASSED** | The repaired runner adds a manifest, exclusive JSONL, production numpy path, stable RNG streams, paired seed analysis, and enforced work band. Its advertised `--replay FILE` is not implemented, it permits non-strict runs, and it omits opponent fallback counters. |
| T2 — offline proposer screen | **STOP** | It did not meet its declared bar, and noisy selected-max labels plus unequal compute make the candidate-count/oracle interpretation scientifically inconclusive. |
| T3 — online diagnostic | **INVALID / TERMINATED; NO RERUN** | The first arms used different skip policies and partial artifacts are quarantined. Repairs have no valid result and have not passed the full re-entry gate. |
| T4 — confirmation | **NOT AUTHORISED** | Prerequisites did not pass. |

### Re-entry gate before any experimental compute

1. Return the constructed bot on every `_seeded()` path; test both a seedless
   no-`rng` bot and an exploding constructor through that exact boundary.
   Persist and compare each seed/flip outcome, not only the aggregate score.
2. Make strict sampling literal: retain the landed suit-relaxation counters and
   rejection, enforce pair-void constraints and declaration pins, count every
   rejected/relaxed world from all four seats, and fail the run if any
   impossible-world fallback occurs.
3. Use one immutable manifest (git SHA, checkpoint SHA-256, engine/fast mode,
   policy and ballot config, seed ranges, calibration/report split, schema
   version) and a new exclusive JSONL per run. Refuse an existing output.
4. Implement the advertised manifest-driven `--replay FILE`; do not silently
   ignore it. Replay the same 10 clusters and require byte-identical non-timing
   records. Counters must reconcile with decisions and sampled worlds.
5. For a gate comparison, hold the cheap action policy identical across arms,
   isolate gate/search RNG streams, match actual rollout or policy-local time
   budgets, and compute paired seed-cluster differences with uncertainty.

### Explicitly do not run yet

- no more v11 epochs, wider-ballot corpus, or standalone-policy duel;
- no T3 restart or targeted stakes-detector training;
- no high-N dataset from the current prototype (see roadmap gate below);
- no v11 pairwise head as an MC/MCTS leaf;
- no AWAC/DMC restart until role-sign, immutable promotion, and fallback tests
  are closed; and
- no PUCT/MCTS or belief weighting until the hard sampler is constraint-correct
  and a calibrated absolute information-state value exists.

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
| `rl_data/gen_v4_all` | 205 shards / 245 MB / **~2.05M decisions** | the current corpus: hybrid-teacher values, wide v2 ballot, TRACTOR_LOCK rows recorded as choice-only. Provenance in META (`teacher_git` 367a822) | `mc-vleaf-v7w-ep02` | v9warm/v9scratch, v10res, **v11pair** |
| `rl_data/gen_v3_all` | 162 shards / 276 MB / ~1.62M | first fast-engine generation; superseded by gen-v4 | upgraded MCBot | v8a/v8b |
| `rl_data/gen_v3_quarantine` | 4 shards / 24 MB | **CONTAMINATED — never merge.** Written by orphaned workers running buggy code for 10h | — | nothing, deliberately |
| `rl_data/distill_n30` | 24 shards / 102 MB / ~1.2M | low-noise N=30 search distillation | upgraded MCBot | v7, v7w |
| `rl_data/distill` | 36 shards / 158 MB / ~1.8M | original N=10 distillation | MCBot (pre-CONTROL_LEADS) | v4, v5, v6, v6.1 |
| `rl_data/bc` | 35 shards / 160 MB / ~1.75M | SmartBot behaviour cloning, no values | SmartBot | ckpt_bc |
| `rl_data/oracle` | 1 shard / 10 MB / ~322k | full-information states + outcomes | self-play | oracle value study (43-47%) |
| `rl_data/human_v4` | 1 shard / **1,850 decisions** | live human play, current v2 ballots (v1-v3 superseded) | live humans | blends, agreement audits |
| `../logs/*.jsonl` | 23 games | raw human corpus source, rebuildable in seconds. Local test games live in `logs/local/` and are NEVER mined | live play | audits, miner |

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
