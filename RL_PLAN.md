# RL Plan: training a learned Sheng Ji policy

Goal: a neural policy that **beats MCBot in the Elo tournament pool**
(the standing "Elo > 1137" milestone — pool-relative, so operationally:
rl above mc in the same pool). Hardware: one Mac mini (M4, 10 cores,
MPS). Everything measured: mirrored deals, fixed-seed probes, direct
duels, Elo pools, human-agreement tripwire. Toggle-level results live in
AI_POLICIES.md; run archives in `server/runs/`.

---

## WHERE THINGS STAND — 2026-08-04 01:30 (read this first)

**RESIDUAL/OVERRIDE LEARNING WORKS — the first positive result from the
learned line.** `rl-override-v11pair` (SmartBot + a learned override, NO
search, p50 0.4ms) beats SmartBot **57.7%** (n=480). Against mc it is **NOT better**: 51.1% over n=4080, Wilson [49.6%, 52.6%] —
the interval includes 50, so the standing goal is not met. Those blocks were
exploratory, not seeded (retraction in 1i); a seeded confirmation is running. A gated variant
(search only on the ~12% of states the net flags as high-stakes) scores 53.3%
vs mc at 55% of the wall-clock. Details in 1i and 1k.

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

**Settled today, do not re-litigate:**

| Question | Answer | Where |
|---|---|---|
| Does residual/override learning work? | **YES, once implemented correctly** — 57.7% vs smart, n=480 across two disjoint blocks | 1i |
| Is the value-leaf hybrid stronger than mc? | **No** — 50.4% at n=1200, CI [47.6, 53.2] | above, 1 |
| Does a better VALUE HEAD make a better hybrid? | **No** — v7w 60%, v9warm 53%, v9scratch 48% on the same seeds. The best head is the OLDEST. | 1f |
| Does the flywheel work (train on hybrid data, get a better hybrid)? | **No** | 1b |
| Residual distillation (net as a learned override on SmartBot)? | **REJECTED** — 47% vs smart, and its bar was to beat smart | 1h |
| Does the banker knowing its own burial help? | **No measurable effect** — 49.7%, CI [44.0, 55.3] | 1g, AI_POLICIES |
| Does rollout-policy strength matter? | **No** — tied twice, second time with a 93-Elo-stronger roller | AI_POLICIES |

**The through-line: nothing about making the EVALUATOR better has moved this
game's search.** FIVE independent attempts — the hybrid itself, a better value
head, the flywheel, a learned override, a stronger rollout policy — all landed
within noise of the thing they were meant to beat.
That is now the most informative pattern in the project, and it points away
from "train a better net" and toward asking what the search is actually
limited by.

**P0 fixed today (Codex):** BANKER_KITTY double-subtracted the burial and left
the banker's world sampler unable to build ANY world — the banker played with
no search at all for ~40 minutes. gen-v4 proven clean via its recorded
`teacher_git`. Full write-up: `incidents/2026-08-03-banker-search-disabled.md`.

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
or gen-v4's labels are not actually better despite coming from a
higher-rated teacher (plausible: the hybrid's ADVANTAGE over mc is
itself unproven — 53.3% with a CI including 50%).

### 1c. Epoch count: SETTLED — strength peaks near epoch 8

v9warm-16 probe curve: ep05 56%, **ep08 60%**, ep11 56%, ep13 54%,
ep15 52%. A clean rise-and-fall, so the 6-epoch arms WERE undertrained
and 16 is past the peak. Best snapshot anchors: **56% vs smart** (the
best any standalone net has managed) and 37% vs mc. Standing recipe:
~8 epochs with per-epoch snapshot-probe selection.

### 1d. LABEL-NOISE CEILING DIAGNOSTIC — the labels are NOT the binding
constraint (2026-08-03 21:00, Codex's #1 recommended test)

120 frozen real decision states, 8 independent N=30 teacher seeds each,
plus an N=200 reference:

| measurement | value |
|---|---|
| teacher self-agreement (modal share of 8 seeds) | **78.5%** |
| ONE teacher sample vs the N=200 reference | **75.2%** |
| student (v9warm16-ep08) vs the same reference | **55.8%** |
| states where the 8 teacher seeds disagreed at all | **63.3%** |

**Interpretation (Codex's stated rule): the student is ~19 points BELOW
what a single noisy teacher sample achieves, so more student capacity
CAN still recover signal that is demonstrably present. The labels are
noisy — 63% of states see the teacher disagree with itself across seeds
— but they are not yet the ceiling.**

This argues AGAINST an architecture-ceiling conclusion and FOR the next
rungs of the diagnostic ladder: optimizer/capacity sanity on a small
clean set, then the representation test (does adding the banker's buried
cards, declaration owner, pair_void, ordered history and team levels
close the gap with the SAME model?). It also strengthens the case for
residual distillation: predicting Delta from the baseline is a far
easier target than reproducing an absolute ranking through this much
label noise.

### 1e. CAPACITY SANITY — the model/optimizer is NOT binding
(2026-08-03 21:30, diagnostic ladder rung 2)

Overfit test: 6,000 UNAMBIGUOUS rows (teacher's best beats second by
>=8 points, so the label is not sampling noise), current architecture,
lr 1e-3, 60 epochs.

**Final train accuracy: 99.6%.**

The model can memorise clean labels essentially perfectly. So the
trainer, capacity and optimiser are NOT the bottleneck — which, combined
with 1d (labels are noisy but leave ~19 points of recoverable signal),
narrows the diagnosis to two remaining candidates:

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

### 1i. RESIDUAL/OVERRIDE LEARNING WORKS — beats smart, LEVEL with mc (2026-08-04)

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
- **The conclusion survives.** Unseeded opponents add variance but no bias;
  the mirrored pairing still controls deal luck. 51.1% over 4,080 rounds
  remains good evidence that v11pair is LEVEL with mc, and the standing goal
  is still not met.
- **The protocol claim does not.** This was exploratory evidence, not the
  declared reproducible confirmation, and JOBS' claim that block 6 was
  "deterministic, so the machine does not matter" was simply false.
- The v11-vs-Smart result is unaffected: SmartBot is deterministic.

`make_bot` now forwards kwargs and `tests/test_duel_factories_seeded.py`
exercises the exact factory FORM the scripts use, so this cannot recur
silently. A properly seeded confirmation is running.

**What fixed it vs v10res (47% vs smart):**

1. Optimise the DEPLOYED quantity. v10res regressed rows independently and was
   never told what a_0 was, so it never learned `q_i - q_0` — the thing the
   override rule gates on.
2. Match the ballot. Collection valued `MCBot._candidates()`; inference
   enumerated `enumerate_actions()`. **11 of 12 decisions enumerated
   differently** (13 vs 26 candidates on seed 5) — the Elo-798 failure again.
3. Fit the threshold off-split (0.02 on half A, reported on half B).

None of that is scale. The signal was present in v10res's data all along.

**Production-ready** (measured 2026-08-04): numpy path, no torch, **p50 0.4ms
/ p95 0.5ms** against mc's 57/107ms; 2MB weights; 33MB RSS; 33ms cold start;
parity with torch verified on 90 real decisions (max diff 7.5e-8, zero argmax
disagreements) from COMMITTED fixtures. Deploying it is a COST decision, not a
strength upgrade.

### 1k. The gated variant: same strength, ~half the compute (2026-08-04)

`mc-gate-v11pair` uses the net's delta as a ~2ms detector of HIGH-STAKES
states and spends search only on the ~12% it flags: **160-140 = 53.3%** vs mc
(n=300, CI [47.7%, 58.9%]) while the table ran at **55% of an all-mc table's
wall-clock**.

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

## TONIGHT RUNBOOK — 2026-08-04 (ordered; no blind compute)

**Decision:** do not launch another training run or full data-generation job
tonight. Do not rerun the entire v11-vs-MC duel merely to repair its seed
provenance: the 4,080 unseeded-search rounds are already enough to say the
effect is approximately a tie and too small to be the next lever. The only
long run allowed tonight is a corrected confirmation of the selective MC gate,
and it earns that run only by passing the cheap gates below. An idle machine is
better than another invalid or uninformative block.

### T0 — repair the measuring instrument (30–60 minutes, CPU-light)

- [ ] Standardise the registry factory contract and forward `seed` through the
  **exact** factories used by `v11_extend.py` and `gate_duel.py`. Do not catch a
  blanket `TypeError` around `factory(**kw)`: that can swallow a real exception
  raised *inside* a constructor and silently instantiate a different policy.
- [ ] Tests: same seed produces the same RNG state; different seeds differ;
  the exact 10-seed pairing run twice produces byte-identical outcomes. Run
  with `SHENGJI_STRICT_SAMPLING=1` and fail on every fallback.
- [ ] Freeze a manifest containing git SHA, checkpoint SHA-256, policy/ballot
  configuration, engine mode, seed range, and calibration/report split. Mark
  the six old v11-vs-MC blocks as useful exploratory evidence, not seeded
  confirmation. Do **not** spend tonight recreating them.
- [ ] Clean `JOBS.md` to one authoritative RUNNING section before launching
  anything. A job absent from the manifest and ledger does not run.

**Exit gate:** exact-factory determinism is green twice from a clean source
tree. Otherwise stop; no experiment starts.

### T1 — one trustworthy selective-search evaluator (60–90 minutes)

Extend one runner rather than adding another one-off duel. It must write one
JSONL row per deal seed and flip plus a manifest, and report:

- round winner, signed level change, and fallback/error counters;
- policy-local `net_calls`, `mc_calls`, sampled worlds, and p50/p95 latency;
- paired/clustered uncertainty by deal seed (not Wilson over two correlated
  flips); and
- an interleaved or in-round all-MC timing baseline, not a shorter later run
  on different seeds extrapolated 4x.

**Exit gate:** replaying the same 10 clusters reproduces every non-timing field
byte-for-byte, counters reconcile with decisions, and no fallback fires.

### T2 — offline gate/proposer screen (<=45 minutes; reuse existing data)

Fix the evaluator's raw-points versus `/100` unit mismatch and implement an
actual shard-disjoint calibration-A/report-B split. On valued gen-v4 rows:

1. Fit the v11 stakes threshold on A and read B once.
2. At the identical `mc_call_rate`, compare v11 with (a) a random gate and
   (b) a candidate-count/lead-follow complexity gate. Define missed
   opportunity as `max_i Q_i - Q_0` on states where search is skipped.
3. Report three independent shard blocks and the consequential-state slices;
   do not call max predicted delta “confidence.”
4. Report candidate-0 + v11 top-K teacher-best coverage and opportunity regret
   for K=1/2/4/8. This informs root racing; it does not authorize hard pruning
   tonight.

**Promotion gate:** on untouched B, the v11 gate must reduce mean missed
opportunity by at least 15% relative to **both** matched-rate cheap gates, with
the same direction in all three shard blocks. If it fails, stop the gate line
and leave the machine idle. Do not rescue it with a threshold chosen on B.

### T3 — small online screen (only if T2 passes; about 150 seed clusters/arm)

Use the same frozen seed block and strict runner for:

1. full MC N=10;
2. v11 stakes-gated MC;
3. random-gated MC at the same search-call rate; and
4. complexity-gated MC at the same search-call rate.

This is a screen, not a strength claim. Continue only if the v11 gate beats
both cheap gates on the point estimates for paired level utility, has no
fallbacks, achieves at least 48% round wins versus full MC, loses no more than
0.03 signed levels per round, and consumes at most 60% of the all-MC table
wall-clock. Record these rules before starting.

### T4 — the only permitted overnight run

If and only if T0–T3 all pass, launch **one** preregistered confirmation of
v11-gated MC versus full MC (1,000 deal-seed clusters, two flips each). Primary
metric is paired signed level utility; round win-rate is secondary. Promotion
requires:

- clustered 95% lower bound above -0.03 signed levels/round;
- clustered 95% lower bound above -2 percentage points in round win-rate;
- table wall-clock <=60% of all-MC; and
- zero silent fallback, timeout, or zero-world decisions.

If it misses, record the result and stop. Do not extend until an interval
crosses the line. If T2 or T3 fails, **run nothing overnight**.

### Explicitly do not run tonight

- no more v11 epochs, wider-ballot training, or full gen-v5 corpus;
- no standalone-policy duel (park it as a diagnostic baseline);
- no v11 pairwise head as an MC leaf;
- no AWAC/DMC restart—the role-sign and immutable-artifact issues are not yet
  closed by tests;
- no PUCT/MCTS: a calibrated absolute information-state value and a belief
  model are prerequisites; and
- no belief weighting until the hard sampler itself never emits an impossible
  world under strict mode.

## ROADMAP AFTER TONIGHT (ordered by information per unit compute)

1. **Establish the deployment Pareto frontier.** Keep SmartBot, direct v11,
   MC N=5/10/20, the settled value-leaf speed arm, and any surviving selective
   gate on one reproducible strength/latency table. Product promotion can use
   non-inferiority plus speed; “beats MC” still requires superiority.
2. **Representation diagnostic, not another bulk training run.** Create a
   versioned raw-state dataset that stores episode/seed/decision ids, role,
   phase, ballot hash, and teacher artifact. On a small high-N frozen set,
   compare the current encoder against exactly one enriched encoder using the
   same model, initialization, data, and three training seeds. Add
   trump-relative canonicalisation, ordered recent tricks, declaration
   owner/cards, pair-voids, team levels, and banker-private burial where legal.
   Generate a full corpus only if untouched high-N regret improves >=10% in
   all three seeds.
3. **Active high-N expert iteration.** Spend expensive MC labels on v11/MC
   disagreements, high predicted opportunity, ensemble disagreement, and
   score-bracket/late-round states; keep an anchor replay mixture. This is more
   likely to move v11 than another epoch over the same noisy N=30 corpus.
4. **Root racing before tree search.** Give every candidate a small common-
   world rollout floor, then allocate the remaining fixed budget using v11's
   ranking plus empirical uncertainty. Compare at equal total wall-clock.
5. **Fix then improve the belief sampler.** Enforce suit voids, pair-voids, and
   declared-card pins without a constraint-dropping fallback; then test
   tempered belief weights with effective-sample-size reporting against
   uniform worlds.
6. **A real absolute value model.** Predict the attacker-perspective scoring-
   bracket distribution / expected signed level utility under a named fixed
   continuation policy, with calibration metrics. Do not use noisy `max_a Q`
   as the default target. It may share v11's trunk but must have a separate
   contract and API.
7. **AWAC last.** Resume only after role symmetry, immutable checkpoint
   promotion, strict fallbacks, and the active-label pipeline are tested. Keep
   policy advantages out of the absolute value head and start with a bounded
   shadow run.

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

- Mirrored deals everywhere; n≥120 round-level or n≥200 games; ties
  (<55%) are not adopted — EXCEPT menu-widening changes, which adopt at
  neutral (they compound with future evaluation improvements; preference
  rules must pay now).
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
- Policies rated in Elo pools, never a single opponent; pool numbers are
  pool-relative; promotion to server default requires a full-game
  mirrored match vs `mc`.
- Negative results are archived, not deleted (`server/runs/`,
  AI_POLICIES experiment log).

---
## ARCHIVE

Day-by-day chronology moved to `docs_archive/rl-plan-chronology-through-2026-08-03.md`
(2026-08-03). Conclusions live in KEY LEARNINGS above; that file is the record
of how each was reached, including the dead ends.
