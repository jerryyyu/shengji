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

## WHERE THINGS STAND — 2026-08-04 09:20 (read this first)

**RETRACTED (10:40): the net does NOT beat mc.** The racing result below was
reported as a win and did not replicate under the paired protocol — the random
control outscored it. Detail in section 1. The standing goal is NOT met.

Previously claimed, now withdrawn:
`mc-race4-v11pair` — the net scores the ballot, the best 4 candidates survive
(candidate 0 always kept), and the SAME rollout budget resolves those four
instead of all six — beats mc **55.2%** over 1,700 rounds across three
disjoint seed blocks (56.2 / 55.0 / 54.5%, every interval excluding 50) at roughly
EQUAL compute (see the cost correction in 1o).

**The control is what makes it a result:** pruning to the same size AT RANDOM,
same budget scaling, scores **49.8%** (n=500, CI [45.4, 54.2]) — a tie with mc.
The gain is the NET's prior, not the reallocation. Full detail in 1o.

**CONFIRMED under the seeded protocol.** After fixing the seed-swallowing
lambda in the duel script, two fresh seeded blocks returned 53.0% and 55.5% —
**651-549 = 54.2% over 1,200 seeded rounds, CI [51.4%, 57.1%]**. Pooling all
five blocks: **1589-1311 = 54.8%, n=2,900, CI [53.0%, 56.6%]**. Five blocks
spanning 53.0-56.2% with no drift.

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
5. **The prototype's “2.8 points of headroom” is a HYPOTHESIS, not a result.**
   It selected/significance-filtered states and scored regret against the same
   noisy N=240 maximum on non-strict, overwhelmingly early-game worlds. The
   derived m0 policy, completed unseeded duel, and partial 20,000-state corpus
   are quarantined; see 1n–1o.

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

**The control outscored the treatment.** In the screen it was the reverse
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

### 2. Value-leaf hybrid: CLOSED — equal to mc (50.4%, n=1200), never stronger

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
the same pool put vleaf +32 above mc, which a 1200-round direct duel then
measured at 50.4%. No direct seeded v9-vs-v7w duel has been run, so that
comparison stays open rather than counted.

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
