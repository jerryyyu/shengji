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
7. Eval hygiene: 30-pair in-run evals every 5 min.
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
