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
