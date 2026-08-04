# RL Plan: training a learned Sheng Ji policy

Goal: a neural policy that **beats MCBot in the Elo tournament pool**
(the standing "Elo > 1137" milestone — pool-relative, so operationally:
rl above mc in the same pool). Hardware: one Mac mini (M4, 10 cores,
MPS). Everything measured: mirrored deals, fixed-seed probes, direct
duels, Elo pools, human-agreement tripwire. Toggle-level results live in
AI_POLICIES.md; run archives in `server/runs/`.

---

## STATE OF PLAY (2026-08-03, end of day 4)

### 1. Value-leaf hybrid: the leading candidate, NOT a proven win

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

**Settling experiment (preregistered, not yet run):** a fresh
deterministic duel over 300-500 INDEPENDENT mirrored seed clusters, no
seed reuse, per-seed records saved, paired level-utility reported
alongside round wins, and an equal-wall-time gate (the hybrid reallocates
compute). Predeclare the bar before running: lower bound >50%, or the
stronger >55% adoption target.

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

### 2. Standalone policy line: no lever has moved it vs mc

Tried and null so far: more data, better-than-search labels (gen-v4),
more epochs, a corrected margin-aware target, warm-vs-scratch init.
Nets sit ~38-48% vs mc throughout. **However** (Codex, accepted): the
6-epoch v9 arms BOTH peaked at their last epoch, so they are
undertrained; they also used different LRs, so warm-vs-scratch is
"no DETECTED difference", not an equivalence result. Extensions to 16
epochs are running. A stronger-teacher failure AFTER convergence, with
the baseline feature representable, would be evidence for an
architecture/encoding ceiling — the current result is not.

### 3. gen-v4: the first dataset whose labels come from a hybrid teacher

36,360 rounds / 1.96M decisions, teacher `mc-vleaf-v7w-ep02`, fast
engine, choice-only TRACTOR_LOCK rows included (19,691 per epoch).
`rl-v9warm` trained on it sits 27 Elo above rl-v7w in the seeded pool —
the first movement in the net line for several generations, though a
clean direct seeded v9-vs-v7w comparison has NOT been run yet.

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

## ROADMAP (ordered)

1. ~~v7 / v7-warm~~ **DONE**: warm won (all 4 snapshots > v6, best
   64.5%; scratch killed at ep1/8). Standing policy: init every
   generation from the incumbent.
3. **MCValueLeaf gate — FAILED (45%, 54-66 n=120 vs wide-ballot mc,
   2026-08-02 evening).** v1 config: 4-trick truncation + v6 value head
   (trained on old-teacher values). Not retired as a pathway: retry
   cheaply with a v7w/v8 value head + truncation sweep, else fall back
   to continuation-strategy leaves. Original design notes: (was running) — truncated rollouts + v6 value leaf,
   vs upgraded mc. Pluribus precedent: depth-limited search with leaf
   evaluation was its enabling trick (5 orders of magnitude compute
   reduction, ran on a 64-core workstation). Poker-transfer variant if
   the plain version falls short: *continuation-strategy leaves* —
   evaluate leaves under k biased rollout policies (aggressive-trump /
   conservative / point-feeding) instead of one, so opponents at the
   leaf get to "choose" their bias (robustness without a net).
4. **Belief-weighted world sampling** — Pluribus updates beliefs over
   hidden cards by Bayes' rule under an assumed strategy. Our version:
   weight determinizations by likelihood that the heuristic (as opponent
   model) would have played the observed actions given the sampled hand
   — computable exactly with no net, generalizes pair_void's hard
   proofs. Gate: weighted-sampling mc vs uniform mc, n=120. Learned
   belief net later if the exact version pays.
5. **Ballot-v2 teacher generation — RUNNING (gen-v3, both machines,
   overnight)** — the dataset fixes all three
   known biases at once: CONTROL_LEADS-era teacher, throws + component
   combos on the ballot (99.3% human-play coverage), TRACTOR_LOCK
   decisions recorded as choice-only samples. Then v8 students.
6. **AWAC-style dmc2 rewrite** — self-play beyond the teacher via
   advantage-weighted policy-head imitation (values stay in their own
   head; the measured-fatal Q-regression pathway never touches the
   policy). Reuses ~90% of dmc2.py, incl. oracle baseline + spread
   alarm + gating (archive: 13-point spec).
7. **Contingency** — if the net line stalls with all of the above:
   encoder audit (aux-head probes) before more training; rented compute
   (fat-CPU actors + GPU learner, 10-30x throughput) only if a curve is
   climbing but slowly.

---

## Training data inventory (2026-08-02, all local + gitignored)

| dataset | size | what it is | teacher | trained |
|---|---|---|---|---|
| `rl_data/bc` | 1.73M decisions / 35 shards / 155M | SmartBot behavior cloning (~20k rounds): obs + chosen action, no values | SmartBot | ckpt_bc, ckpt_bc_dueling |
| `rl_data/distill` | 1.66M decisions / 36 shards / 155M | search distillation: full ballots + MC per-candidate rollout values, N=10 | MCBot (pre-CONTROL_LEADS) | v4, v5, v6, v6.1 base |
| `rl_data/distill_n30` | 1.06M decisions / 24 shards / 104M | the low-noise textbook: same format, N=30 (3x less label noise), pairfix+voiddump teacher | upgraded MCBot | v7 (in training) |
| `rl_data/human` | 801 decisions / 1 shard | FROZEN while v6.1 trains on it — superseded by human_v2 | live humans | v6.1 blend |
| `rl_data/human_v2` | **1,003 decisions** / 1 shard (2026-08-02, post-fly-fetch) | rebuild with **v2 ballots** (exhaustive follows + lead throws): human throws now compete against rival throws | live humans | next blend |
| `rl_data/oracle` | 1 shard / 10M | full-information states + outcomes (own schema) | self-play | oracle value study (43-47%) |
| `../logs` | 21 games / ~1M | raw JSONL — human corpus source, 1,052 decisions and growing (rebuildable in seconds) | live play | audits, agreement, miner |

Key asymmetries: quality ladder bc < distill < n30 tracks net strength;
all 4.4M machine decisions share the v1 ballot's biases (75% follows, no
TRACTOR_LOCK leads, ~0% risky throws) — roadmap #5 fixes all three; the
human pile is 4,000x smaller but highest signal-per-byte.

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

## ARCHIVE (chronology, compressed — details in git + server/runs/)

**Phases 0-2 (complete):** fast env (2,067 rounds/s multiproc); 531-dim
obs + 60-dim action encoding (ENC_VERSION 1); exhaustive follow + v2
lead enumeration; BC gate passed (89.7% imitation → 48% vs smart / 29%
vs mc — search exploits clone errors; encoding carries the game).

**DMC v1 (closed):** warm start + raw-return regression = flat 30-34%
over 400k rounds; value regression crushed BC ordering (spread
22.5→0.26); degraded policy then fed itself. `server/runs/dmc_v1.md`.
Root insight: DouZero trains from scratch; AlphaGo 2016 kept SL/RL nets
separate for exactly this reason.

**Distillation series:** v1 32/22 → v2 (+CE temp) 30/27 → v3 (split
heads) 32/24 → v4 (+soft targets) 38/32 → v5 (full data) 42/38 → **v6
(12 ep) 51/41** — no bend in the curve until data ran out. Diagnosis:
teacher is stochastic and ~70% of labels are SmartBot-via-margin; soft
targets average the teacher's RNG.

**Snapshot sweep:** 20-epoch run probed per epoch: 38% ep0 → 53-57%
plateau ep3-10 → wobble after. v6cont (6 extra epochs) NEGATIVE (44/32).
Strength peaks early; probe-select thereafter.

**Hybrid v1 (net rollouts): dead.** 55% preview (n=40) reversed to 37%
(n=60); bare v5 out-rated its own hybrid in-pool (1088 vs 1074); "feels
wonky" preceded the stats.

**dmc2 (halted twice by its own spread alarm):** the 13-point recipe
(dueling split, Suphx oracle baseline, annealed anchor, gating, opponent
pool, aux heads, ballot freeze, spread alarm, oracle upkeep, ε schedule,
replay cap, run bookkeeping) remains the AWAC rewrite's scaffolding —
the alarm works (caught spread collapse in 2 min); the Q-regression
core is what AWAC replaces.

**Overnight sweeps (2026-08-02):** temperature 0.03/0.10 null; 1024
trunk null; MC-level stack validation 57% (heuristic-level h2h testing
inherits to MC); RISKY_THROWS/TRUMP_BALLOT 53%/53% solo (superseded by
wide ballot).

**Historical pools:** 2026-08-01 A: mc 1141 > rl-v5 1088 > mc-v5roll
1074 > smart 1055 > heuristic 1000. Pool B: mc 1104 > rl-v6 1032 >
smart 1006 > heuristic 1000. 2026-08-02 night: mc 1067 > smart 1061 >
rl-v6 1023 > heuristic 1000 (heuristic adoptions closed most of the
search's margin). Cross-pool numbers do not compare.

**Play-test notes:** Jerry vs v6 live (2026-08-02): "some passive plays
but feels decent" — corroborates the 75%-follow dataset bias; fixes:
lead-weighted loss arm, ballot-v2 teacher data.
