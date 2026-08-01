# RL Plan: training a learned Sheng Ji policy

Goal: a neural policy that beats MCBot, trained by self-play on this Mac
(M-series: CPU actor processes + MPS learner). Approach: **DouZero-style
Deep Monte Carlo** (proven on DouDizhu, the closest solved neighbor), not
AlphaZero-MCTS (poor fit for hidden information + combinatorial actions).

Progress gate for every phase: the Elo tournament (`shengji.ai.tournament`)
against the frozen pool — never a single fixed opponent.

Current assets: pure engine with legality validators; `ai/env.py` headless
self-play (~360 rounds/s single-core with heuristics); `Memory` (public-info
card counting = ready-made compressed history features); policy interface
(`decide_declare/bury/play`); registry + Elo harness; mirrored-deal
evaluation; MCBot flat-search plateau at ~62% round-level vs SmartBot v3
(the bar to clear).

New code lives in `server/shengji/rl/`; PyTorch goes in an optional
dependency group (`uv sync --group rl`) so the server stays lean.

## Phase 0 — fast environment (the schedule risk; do first)

RL lives on throughput. Target: **>2,000 rounds/s aggregate** across worker
processes for heuristic rollouts.

1. `rl/fastenv.py`: strip `play_round` to a hot loop — no logging, no
   record, preallocated; profile with `cProfile` and attack the top 3
   (likely: `decompose` Counter churn, `Ordering.level` dict hits, Memory
   rebuilds in SmartBot — cache per-round orderings, memoize levels).
2. Multiprocess: N-1 worker processes each running independent games with
   distinct seeds, pushing trajectories through a `multiprocessing.Queue`.
3. Acceptance: benchmark script prints rounds/s single-core and aggregate;
   ≥3x single-core speedup from profiling alone is realistic.

## Phase 1 — encoding (obs, actions, and the Q(s,a) trick)

1. `rl/encode.py` — observation for the acting seat, all card-count planes
   as 54-dim vectors (counts 0-2, two decks):
   - own hand; cards played by each of the 4 seats (4 planes); current
     trick's plays (3 planes, seat-relative); union of unseen cards;
   - scalars/one-hots: trump suit (5), trump rank (13), seat-relative
     banker position (4), attacker points bucket (12), tricks remaining
     (25), am-I-attacker, per-opponent void flags per suit (from Memory);
   - total ≈ 600 floats. Version the encoding (`ENC_VERSION`) from day 1.
2. `rl/actions.py` — `legal_plays(rnd, seat) -> list[list[str]]`:
   exhaustive for singles/pairs/tractors/required follows, bounded for
   throws (safe throws + forced components only). Encode each candidate
   action as its own 54-dim count vector + shape features (pair-run
   lengths, is-trump, points in play).
3. Model scores `(obs, action)` pairs (DouZero's trick): variable action
   sets need no fixed action space, and MCBot's candidate generator is the
   fallback if exhaustive enumeration explodes.
4. Acceptance: round-trip tests — every action produced is engine-legal;
   encode 10k positions/s.

## Phase 2 — behavior cloning (pipeline shakeout, cheap baseline)

1. `rl/dataset.py` — trajectory writer: for every play decision, store
   `(obs, action_vecs, chosen_idx, final_attacker_pts)`; shard to
   `.npz` files (~1 GB ≈ 2M decisions ≈ 80k rounds ≈ 1-2 h of Phase-0
   generation with SmartBot).
2. `rl/model.py` — MLP: concat(obs, action) -> 512 -> 512 -> 256 -> scalar
   (~1M params; upgrade to a small transformer only if MLP stalls).
3. `rl/bc_train.py` — cross-entropy over softmax of candidate scores
   (chosen action = label). MPS, batch 1024, ~1 h.
4. `rl/torch_policy.py` — implements `decide_play` (declare/bury stay
   SmartBot for now): argmax over scored legal actions. Register as
   `rl-bc`.
5. Acceptance: `rl-bc` within ~50 Elo of SmartBot v3 in the tournament.
   This validates encoding + enumeration + inference end to end before any
   RL is attempted.

## Phase 3 — Deep Monte Carlo self-play (the main event)

**Starting point (2026-08-01):** Phases 0-2 complete. Throughput 2,067
rounds/s aggregate (heuristic; net-driven actors ~30 rounds/s aggregate
estimated). BC checkpoint `ckpt_bc.pt`: 89.7% imitation of SmartBot,
**48% vs SmartBot v3** (even), **29% vs MCBot** — search exploits the
clone's ~10% imitation errors. Phase 3 success = self-play closes
29% → >50% vs MCBot (Elo > 1137 in the tournament pool).

1. Reward: terminal per round, the level-bracket value already implemented
   in `MCBot._score` (LEVEL_OBJECTIVE scaling: brackets ±40, deal ±20,
   0.2/point tiebreak), from the acting team's perspective.
2. Actors (CPU): play rounds with the current net, epsilon-greedy over
   legal actions (ε: 0.2 → 0.05); every decision logs `(obs, actions,
   chosen, G)` with G = the actual terminal value — Monte Carlo return, no
   bootstrapping (that's what makes DMC stable and simple).
3. Learner (MPS): MSE regression of Q(obs, action) toward G from a replay
   buffer (~2M decisions, FIFO). Checkpoint every ~30 min.
4. Opponent pool: seats drawn from {current net, 3 recent checkpoints,
   SmartBot} to prevent self-play cycling; one shared net for all seats
   (seat/role features carry the asymmetry).
5. Monitoring: every checkpoint enters the Elo tournament vs the frozen
   pool (heuristic / smart-v1 / smart / mc). Expect: BC-level quickly,
   SmartBot+100 within a day of wall-clock training, MCBot-level within a
   few days. Plateau → raise buffer size, add per-trick point shaping
   (small, e.g. 0.05x trick points), or widen the net.
6. Acceptance: checkpoint with Elo > `mc` in the tournament.

## Phase 3 findings — first DMC attempt (2026-08-01) and the fix list

First 90-min run (lr 1e-4, eps 0.1, 70/30 self-play/vs-SmartBot, terminal
bracket reward): **flat at ~34% vs SmartBot across 243k rounds** — below
the 48% BC starting point, no recovery trend. Diagnosis: the terminal
return is dominated by deal luck (±3 brackets) while the per-action
signal is tiny (±0.25 brackets); value regression destroyed BC's action
ordering immediately (48%→32% in 2 min) and cannot rebuild it from this
signal-to-noise at laptop scale. Loss fell throughout — the net learned
to judge HANDS, not PLAYS.

Fixes, in adoption order:

1. **MC search distillation first (expert iteration)** — new step before
   more DMC: generate MCBot self-play data recording per-candidate MC
   values + final choices; train the net on these DENSE per-action
   targets (no credit assignment problem at all). Teacher = 1137 Elo
   (vs SmartBot's 1032); a net that internalizes search evaluations is
   also exactly the value function the Phase 4 hybrid needs. Cost: MC
   data is ~100x slower — parallel workers make 20k rounds ≈ 2-3h
   (overnight). Inherits MC's known biases (passive-rollout lead tilt),
   which DMC then gets to correct.
2. **BC/policy anchor** — auxiliary loss keeping the net's action
   ordering near its supervised starting point (annealed), so DMC never
   pays the objective-switch dip; outcome learning accumulates on top of
   the floor instead of underneath it.
3. **Advantage baseline** — add a V(s) head; regress action scores
   toward G − V(s). V absorbs deal luck; what remains is the action's
   marginal contribution ("fed points to partner's ace and the round
   beat the position's expectation" finally becomes a direct signal).
4. **Mild reward shaping** (reserve dial) — small per-trick point-swing
   term (~0.05x) to densify feedback if curves still crawl.
5. **Eval hygiene** — 30-pair in-run evals (±6, was ±9); add team levels
   to the observation (ENC_VERSION bump) so game context is learnable.
6. **Scale honesty** — DouZero needed days of server compute; overnight
   (~1.5-2M rounds) is the minimum serious attempt, and fixes 1-3 exist
   to make those hours count.
7. **Opponent pool** (once improving) — add past checkpoints to the
   actor opponent mix so progress can't cycle against one frozen foe.
8. **Later refinements** — game-context reward weighting (level cap at
   A, defend-at-A championship rounds), inference-weighted world
   sampling for the hybrid.

Revised ladder: BC(SmartBot) ✓ → **distill(MCBot)** → anchored DMC with
advantage, warm-started from the distilled net → Phase 4 hybrid
(MC search with the net as value function / rollout policy).

### Research notes — AlphaGo-family stabilization (2026-08-01)

Survey of AGZ/AlphaZero, KataGo, DouZero, Suphx, OpenAI Five, AWAC
(sources in git history). Validations: DouZero trained from SCRATCH — no
pretrained ordering to destroy, which is precisely why raw-return DMC
worked for them and broke our warm start; original AlphaGo kept separate
SL/RL policies because RL collapsed the SL policy's usable structure
(the canonical precedent). Adopted into recipe v2:

1. **Oracle value baseline (Suphx)** — we ARE the simulator: train
   V_oracle(all four hands, state) and regress Q toward
   `return − V_oracle`. Perfect-info baseline explains away deal luck
   far better than partial-info V(s); should cut label noise from ~1.12
   toward the ~0.25 true-signal scale. Training-time only, so legal.
2. **Dueling head split Q = V(s) + A(s,a), mean-zero A** — objective
   scale shifts move V; ranking lives in A and cannot be crushed.
3. **Checkpoint gating (AGZ-style)** — a new net must beat the incumbent
   ~55% on mirrored duplicate deals before it generates data (kills the
   degraded-generator spiral; right regime at laptop scale — AlphaZero
   only dropped gating because its throughput kept data microseconds
   stale).
4. **Auxiliary heads (KataGo)** — predict round points captured, final
   margin, opponents' per-suit voids: dense low-variance gradients for
   the trunk, discarded at play time.
5. **Search-budget randomization (KataGo's playout cap)** — distill with
   full MC search on a random ~25% of decisions, cheap policy for the
   rest: volume AND target quality on 10 cores.
6. **Opponent pool (OpenAI Five)** — ~80% latest net / 20% past
   checkpoints + the heuristic bot, anchoring the data distribution.
7. **Anneal the BC anchor** (RLHF-style decaying KL) — a permanent
   anchor caps improvement; AWAC-style weighting if we move off pure
   regression.

## Phase 4 — integration & beyond

1. Register the winner as `rl`; make it the server default after a
   full-game mirrored match vs `mc` (n>=40) confirms the round-level Elo.
2. Hybridize: MCBot with the net as rollout policy and/or value function —
   search + learned evaluation usually beats either alone; this directly
   attacks the "rollout quality" bottleneck the sweeps identified.
3. Later: train declare/bury heads on the same terminal value; ISMCTS with
   the net as prior if more strength is wanted; distill to a smaller net if
   inference latency ever matters.

## Risks

- **Phase 0 throughput miss** → everything downstream is 5-10x slower.
  Mitigate: profile before writing any RL code; consider Rust/Cython for
  `decompose`+`beats` only if Python profiling caps out below target.
- **Encoding bugs** are silent killers → Phase 2's BC gate exists to catch
  them (BC failing to match SmartBot ⇒ the pipeline, not RL, is broken).
- **Self-play collapse** (policies cycling) → opponent pool + Elo-vs-frozen
  monitoring makes it visible immediately.
- **Compute reality**: DouZero used days on a server; expect 3-7 days of
  Mac wall-clock to pass MCBot. The machine stays usable (actors nice-d,
  learner on MPS).
