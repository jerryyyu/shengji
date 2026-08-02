# RL Plan: training a learned Sheng Ji policy

Goal: a neural policy that beats MCBot (Elo 1137), trained on the Mac mini
(M4, 10 cores, MPS). Approach: DouZero-family Q(state, action) learning with
AlphaGo-style search distillation, adapted to laptop scale. Every claim gets
measured: mirrored deals, the Elo tournament pool, and the human-agreement
tripwire (`AI_POLICIES.md`).

---

## COMPLETED

**Phase 0 — fast environment** ✓
Ordering lookup tables (+11% single-core → 400 rounds/s); multiprocess
harness `rl/fastenv.py`: **2,067 rounds/s aggregate** (target >2,000).
Net-driven actors: ~45 rounds/s (6 workers). MC self-play: ~2.4 r/s (9 workers).

**Phase 1 — encoding & actions** ✓
`rl/encode.py`: 531-feature observation (card-count planes, trump/banker/
points context, void flags; ENC_VERSION 1) + 60-feature action encoding.
`rl/actions.py`: exhaustive lead enumeration; **exhaustive follow
enumeration** (validator-driven, brute-force-verified; added after the gap
analysis showed ~20% of humans' legal plays missing from the ballot).

**Phase 2 — behavior cloning** ✓ (gate passed)
`rl/bc_generate.py` + `rl/bc_train.py`. 20k SmartBot rounds → 89.7%
imitation → **48% vs SmartBot** (even with teacher) but **29% vs MCBot**
(search exploits the clone's ~10% imitation errors). Checkpoint:
`ckpt_bc.pt`. Conclusion: the encoding carries the game.

**Phase 3 attempt 1 — DMC recipe v1** ✗ (closed; infrastructure ✓)
`rl/dmc.py` (actor pool, replay ring, MPS learner, in-run evals) works.
The recipe failed: flat ~30-34% vs SmartBot over 400k rounds. Measured
cause: value regression crushed the BC output scale (cross-candidate
spread 22.5 → 0.26 = action-blind) and per-action signal (±0.25) drowned
in deal-luck label noise (±1.12); degraded policy then generated 34M
samples of its own confusion. Full record: `server/runs/dmc_v1.md`.
Root insight: DouZero trains from scratch — raw-return regression never
meets a pretrained ordering it can destroy. Warm start + raw returns is
the specifically broken combination (canonical precedent: AlphaGo 2016
kept separate SL/RL nets for this reason).

**Supporting assets** ✓
Elo tournament + mirrored evaluate; human validation set (245 decisions,
227 as labeled shards via `rl/human_shards.py`, grows with every prod
game); live X-ray debugger; MCBot exposes per-candidate values
(`last_eval`) for distillation.

---

## IN PROGRESS

**Distillation data generation** — 30k rounds of MCBot self-play recording
per-candidate search values (`rl/distill_generate.py`, 9 workers, ~3h).
Dense per-action targets from the 1137-Elo teacher; no credit-assignment
problem.

---

## PLANNED (in order)

### Step 1 findings so far (2026-08-01 evening, partial 450k-decision data)

Four trainer iterations, all failing the gates (targets 60%/45%):
| v | change | vs Smart / vs MC |
|---|---|---|
| v1 | single Q, MSE+CE | 32% / 22% |
| v2 | + CE temperature | 30% / 27% |
| v3 | separated policy/value heads | 32% / 24% |
| v4 | + soft value-distribution targets, lr 1e-3 | 38% / 32% |
| v5 | v4 recipe on the FULL dataset (2.6M decisions, 5 epochs) | 42% / 38% |
| v6 | same, 12 epochs | **51% / 41%** |

**v6 is the strongest standalone net: beats BC on both axes (48/29) and
reaches parity-plus vs SmartBot.** Val agreement plateaued (~55.5%) while
gate strength kept climbing v5→v6 (+9/+3) — more evidence that agreement
measures near-tie matching, not strength. Still shy of the formal 60/45
gates, but the trend (v4 38/32 → v5 42/38 → v6 51/41) hasn't bent yet;
next data-side lever is a bigger/regenerated teacher dataset (N>10 world
evals for less label noise) or aux heads.

v5 confirms the data-starvation hypothesis: the v1→v4→v5 line (32→38→42
vs Smart) hasn't plateaued, and val metrics were still improving at epoch
5 with no overfit gap. Headline: **38% vs MCBot makes v5 the most
search-resistant net so far** (BC: 29% — search exploits imitation
errors; the distilled student, trained on search's own judgments, holds
up). Human tripwire: 47% (healthy). Still short of the 60/45 gates.
Remaining levers: more epochs/data, aux heads, averaged teacher values,
and an AWAC-style policy-head update so PolicyValueNet checkpoints can
enter dmc2 (its learner currently requires the dueling Q interface).

**v5-hybrid: preview did NOT survive confirmation.** The 55% (n=40) duel
vs plain mc reversed to **37% at n=60 in the tournament** (pooled ~44%,
n=100); the human player's "feels wonky" preceded the statistical
verdict. Full 5-policy Elo pool (2026-08-01 night, 60 rounds/pairing):

| policy | Elo |
|---|---|
| mc | 1141 |
| **rl-v5 (bare net)** | **1088** |
| mc-v5roll (hybrid) | 1074 |
| smart | 1055 |
| heuristic | 1000 |

Two findings: (1) **the bare net out-rates the hybrid built from it** —
v5-as-rollout-policy actively degrades the search vs heuristic rollouts
(net failure modes in the tails that search amplifies + 100x cost);
full-net rollouts are a dead end, the value-leaf design remains the
Phase-4 path and must clear this cleaner baseline. (2) **the net line
passed SmartBot**: rl-v5 1088 > smart 1055, from a standing start this
morning. v6 (51/41, stronger than v5) is unrated in the pool — likely
~1100+; goal remains Elo > mc.

Diagnosis: MCBot is a STOCHASTIC teacher (10-world sampling decides
near-ties — the majority of decisions), and ~70% of its choices are just
SmartBot's picks via the margin, so the learnable signal is BC-plus-noise;
its true edge (rare confident overrides) is the rarest label. Soft
targets recovered real ground (+6/+8 pts) and remain the right form.
Next levers, in order: full 30k dataset (2x data), more epochs at lr
1e-3 with early stop, aux losses, THEN averaged teacher values (N>10
world evals recorded at generation) if still short. BC (48%/29%) remains
the strongest net and the overnight dmc2 warm start.

**Evening addenda (same day, later):**
- **Generation complete**: 29,997 rounds, 36 shards, ~2.6M search-labeled
  decisions (169MB) — the "full dataset" lever is now loaded for the retry.
- **dmc2 shakeout validated the alarm**: warm-starting from QNet-BC (the
  unprotected architecture) collapsed cross-candidate spread 23.3 → 4.6 in
  ~300 steps; the spread alarm halted the run in 2 minutes. v1's failure
  mode is now caught live instead of post-mortem.
- **BC retrain into QNetDueling** (for a protected warm start): epoch 0 =
  78.0% imitation (vs QNet's 80.5% — a ~2.5pt constraint tax) → 32% vs
  SmartBot at epoch 0 (NOT comparable to QNet's final 48%; the
  imitation→strength curve is convex). Epoch-2 verdict pending; if it
  stalls well below 48%, the dueling constraint tax is material for
  imitation and a PolicyValueNet-style free policy head + dueling only on
  the regression path becomes the alternative.
- **Trainer engineering debt**: the per-decision BC loop is MPS-dispatch-
  bound (~60 min/epoch regardless of free cores); port BC to the
  vectorized ragged-batch trainer (first code task tomorrow — the same
  data trains in ~1/4 the time).

### Step 1 — Search distillation (the AGZ move: search is the teacher)
Build `rl/distill_train.py`: regress Q toward per-candidate MC values +
cross-entropy on the chosen action; filter forced single-candidate
decisions from action batches. Benchmark the distilled net: expect
~MCBot-level play at 1/15th the decision cost.
**Gate: ≥60% round-level vs SmartBot and ≥45% vs MCBot** (i.e., clearly
above BC's 48%/29%) before proceeding. Also run the human-agreement
tripwire (~50% expected; ~30% = broken).

### Step 2 — DMC recipe v2 (self-play beyond the teacher)
Warm-start from the distilled net. Changes vs v1, all adopted from the
2026-08-01 research pass (AGZ/KataGo/Suphx/OpenAI Five/AWAC):
1. **Dueling head split** Q = V(s) + A(s,a), mean-zero A — scale shifts
   move V; ranking structurally cannot be crushed.
2. **Oracle value baseline** (Suphx): train V_oracle(all four hands) —
   we are the simulator — and regress toward `return − V_oracle`,
   cutting label noise toward the true-signal scale. Training-time only.
3. **Annealed BC anchor** — keep action ordering near the distilled
   policy early, decay to zero (permanent anchor caps improvement).
4. **Checkpoint gating** — a new net must beat the incumbent ~55% on
   mirrored duplicate deals before it becomes the data generator.
5. **Opponent pool** — ~80% latest / 20% past checkpoints + SmartBot.
6. Auxiliary heads (round points, opponent voids) for dense gradients;
   ENC_VERSION 2 adds team levels to the observation.
7. Eval hygiene: 30-pair in-run evals every 5 min; the human-agreement
   tripwire on every gated checkpoint.
8. **Version/ballot freeze** (2026-08-01 incident): the action
   enumeration and ENC_VERSION are FROZEN for the duration of the run —
   play-time ballots must be byte-identical in distribution to training
   ballots. Any change ⇒ regenerate, retrain, re-verify (the exhaustive-
   follows change silently collapsed the deployed net to Elo 798).
9. **Spread-collapse alarm**: log the cross-candidate score spread
   (mean max−min per decision) alongside loss — v1's failure signature
   was spread 22.5 → 0.26; alert/halt if it drops >5x from the warm
   start. Cheap, and directly detects the known failure mode.
10. **Oracle upkeep**: early-stop + weight decay (prototype overfits
    after epoch 0); RETRAIN V_oracle periodically on the current
    policy's own self-play — an oracle fitted to heuristic play drifts
    off-distribution as the net's style departs from it.
11. **Exploration schedule**: anneal ε 0.15 → 0.05 (v1 used fixed 0.1);
    watch policy entropy stays in a band (Suphx).
12. **Replay-ratio cap** (~≤4 gradient visits per sample; v1 ran ~10 on
    a stale ring) and forced single-candidate decisions excluded from
    action batches (measured 27% dead weight).
13. **Bookkeeping**: every run archived in `server/runs/` (config, eval
    curve, verdict — the dmc_v1.md precedent); keep the last ~5 gated
    checkpoints for the opponent pool.
**Gate: beats the distilled net ≥55% AND Elo > mc (1137) in the pool.**

### Step 3 — Phase 4 hybrid (search + learned evaluation)
Once the net is the best evaluator available:
- **Truncated rollouts**: MCBot plays a few tricks per sampled world, then
  the net's V scores the leaf (~20x cheaper than full net rollouts — full
  rollouts measured at 2s/decision, unusable live).
- Candidate pruning by net priors; net as rollout policy where affordable.
- KataGo-style search-budget randomization if we iterate distillation
  (expert-iteration loop: better net → better search → new targets).
**Gate: hybrid beats both parents head-to-head; becomes server default
only after a full-game mirrored match vs `mc` (the standing promotion
rule).**

### Contingencies
- Distillation gate fails → audit encoder information content first
  (aux-head probes), not more training.
- v2 curve climbs but slowly → this is THE trigger for rented compute
  (fat-CPU actor box + one GPU learner, ~10-30x throughput); hardware
  is explicitly not the fix for anything else.
- Human-style play (separate goal): fine-tune on the human corpus once
  it reaches a few thousand decisions.

---

## Measurement rules (unchanged, non-negotiable)
Mirrored deals everywhere; policies rated in the Elo pool, never against a
single opponent; every checkpoint through the human-agreement tripwire;
negative results archived in `server/runs/`.
