# RL_PLAN experiment sections 1b-1o, archived 2026-08-04 10:15

Every conclusion below is carried forward in RL_PLAN's findings table; this
file keeps the REASONING, which is the part that cost compute to buy. Read it
when you are tempted to re-run one of these.

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
The non-strict 20,000-state corpus was found still running after the ledger
called it stopped and was terminated at 845 rows; the m0 duel completed but was
unseeded at its actual call site. Neither is a confirming result, and active
high-N labelling is not authorised yet.

### 1o. m0's offline gain did not transfer in an unseeded online screen (2026-08-04 08:17)

This experiment is a useful warning, but its committed “seeded rejection”
interpretation is stronger than the evidence.

The prototype suggested v11's problem might be calibration, so the decision
rule was refitted on even deal seeds and reported on odd deal seeds. The fitted
rule removed the margin entirely (trust the net's argmax):

| rule | offline regret, significant states | offline regret, ALL states |
|---|---|---|
| v11 @0.02 (deployed) | 2.870 | 1.141 |
| v11 @0 (fitted) | **2.152** | **1.132** |

The online screen was **235-265 = 47.0%** vs MC, Wilson [42.7%, 51.4%]. It did
not earn promotion. It was not seeded: `v11_extend.py` accepted `**k` but called
`make_bot(opp)` without forwarding it, so MC used OS entropy. The deployed
0.02 rule's ~51% came from different, also-unseeded blocks rather than a paired
same-seed control. Therefore this is neither a statistically clear loss nor a
clean measurement of reversal.

**Plausible explanation to test, not an established cause:** each candidate's
prototype value assumes HeuristicBot finishes the round. A deployed policy that
deviates repeatedly induces a different continuation distribution, and errors
can compound across many decisions. Same-world selected-max bias is another
explanation. A valid paired control is required to separate them.

The result is consistent with the warning against training a state value on
`max_a Q`, but does not prove one-ply action values are useless. A direct
`V(state)` still needs a named action-and-continuation policy and calibrated
bracket/level-utility target. The corpus stores forced-action Q estimates under
a heuristic continuation; those are not automatically that V target.

**Consequences:**
1. Offline prototype regret may generate hypotheses; it cannot promote or
   reject a rule until worlds, selection/report split, state distribution, and
   coverage are valid. Only a seeded paired online duel promotes.
2. Do not train on the prototype argmax or treat forced-action Q as direct V.
   Rebuild the target contract first.
3. Keep the deployed margin at 0.02. m0 showed no evidence of improvement and
   is a diagnostic registry entry only.
