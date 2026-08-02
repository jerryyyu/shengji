# AI policy ledger

Every bot policy, its design, and its measured performance. Update this file
whenever a policy is added, changed, or re-benchmarked. RL training plan and
post-mortems: RL_PLAN.md.

## Using policies

Registered by name in `server/shengji/ai/registry.py`; the server reads
`SHENGJI_BOT` (**default `mc`**):

```bash
SHENGJI_BOT=smart uv run shengji-server   # e.g. an easier table
```

Benchmarking (always mirrored deals — each seed runs twice with teams
swapped, so card luck cancels; identical policies score exactly 50/50):

```python
from shengji.ai.env import evaluate
from shengji.ai.registry import make_bot
evaluate(make_bot("mc"), make_bot("smart"), n_games=300)
```

Multi-policy Elo: `uv run python -m shengji.ai.tournament`. Human-agreement
tripwire: `uv run python scripts/eval_vs_human.py "../logs/*.jsonl"`.
Noise guide: ±3% at n=200, ±2% at n=400; round-level evals ±4.5% at n=120.

## The ladder (Elo, round-level, heuristic = 1000)

IMPORTANT caveat learned 2026-08-01: Bradley-Terry ratings are
POOL-RELATIVE — absolute numbers shift with pool composition (mc rated
1141, 1104, and 1137 across three pools; anchors move too). Only
within-pool gaps and head-to-head rates transfer between tables.

**Latest pools (2026-08-01 night, post-throw-fix code):**

| policy | Elo | pool | note |
|---|---|---|---|
| **mc** (server default) | **1141** | A | champion; beat rl-v5 53%, mc-v5roll 63%, rl-v6 60% |
| rl-v5 (bare net) | 1088 | A | distilled net, no search at inference (~2ms/decision) |
| mc-v5roll | 1074 | A | net-as-rollouts DEGRADES search — its 55% preview vs mc (n=40) reversed to 37% at n=60; bare net out-rates its own hybrid |
| smart (v3) | 1055 | A | |
| rl-v6 | 1032* | B | *pool B (mc 1104, smart 1006): ~25-30 above smart, ~70 below mc — v6 is the strongest standalone net (see rl section) |
| heuristic | 1000 | A+B | anchor |

Earlier pools (same day, pre-throw-fix code): mc 1137 > mc-smartroll
1129 (tie at 5x cost) > mc-argmax 1092 (margin worth ~45 Elo) >
mc-lite 1077 > smart 1032 ≈ smart-v1 1022 ≈ smart-v2 1020 > heuristic
1000.

Full-game rates compress/amplify differently: smart beat heuristic 86-90%
of GAMES while only ~52% of rounds — game wins come from winning rounds
BIGGER (brackets), compounding over ~37-round games.

## Active policies

### `mc` — MCBot (server default)
Determinized Monte Carlo (`ai/mcbot.py`): samples 10 opponent-hand worlds
consistent with public info (hand sizes, observed voids, card counts; own
kitty knowledge as banker), rolls ≤8 candidates to round end with heuristic
rollouts, argmax — guarded by:
- **Confidence margin** (5.0 pts/round): candidates[0] is SmartBot's pick;
  the search overrides only when it wins by the margin. Rollouts are
  noisiest early; the margin is worth ~45 Elo vs pure argmax.
- **TRACTOR_LOCK**: heuristic tractor leads are final (56% vs unlocked).
- **Point-shy tiebreak** (2.0): among near-tied candidates, risk the fewest
  points (a beaten 10-10 lead gifts 20 immediately).
- ~30ms/decision (invisible inside the 0.7s bot pacing); ~400x slower than
  heuristics in headless sim — benchmark with small n or round-level.
- Hyperparameters fully swept and flat: N∈{5..30} (N=10 best), margin
  {0,2.5,5,7.5,10} (5 best), candidates {4,8,12} (8), SmartBot rollouts
  (tie at 5x cost), LEAD_MARGIN {8,12,999} (ties), LEVEL_OBJECTIVE / MC_BURY
  toggles (ties, available off by default). **Flat-MC is plateaued**; next
  strength requires learned evaluation (RL_PLAN.md).
- vs SmartBot v2: 36-4 (90%) mirrored full games, n=40.
- Exposes `last_eval` (per-candidate values) for search distillation, and
  powers the /debug/xray live inspector.

### `smart` — SmartBot v3
`ai/smart.py` + `ai/memory.py`: heuristic layered with public-information
memory — card counting, boss detection ("is this the highest card still
out?"), void inference, ruff/beat risk. Leads safe throws (every component
provably unbeatable) → boss pairs/tractors → tractor pressure → boss
singles; always contests in-suit (tempo); spends trump only on tricks worth
taking; feeds points only when partner's win is secure; buries toward voids
gated on trump strength; endgame control (contest everything in the last ~6
tricks); eager declaration (8/6 thresholds).
Lineage (all mirrored vs heuristic): v1 (memory only) 66% → v2 (+safe
throws +17pt, bury-to-void, eager declare) 86% → v3 (+endgame control +2,
trump-gated bury +1) ~88-90%. Registry keeps smart-v1/smart-v2 reproducible.

### `heuristic` — baseline
`ai/heuristic.py`: stateless rules; the fixed reference (Elo anchor 1000).

### `rl` — RLBot (experimental, opt-in)
`rl/torch_policy.py`: Q-net (QNet or dueling QNetDueling, auto-detected)
argmaxing over enumerated legal actions; needs `uv sync --group rl` +
`SHENGJI_RL_CKPT` (checkpoints local, gitignored).
- **Checkpoint ladder** (gates = mirrored n=120 vs SmartBot / vs MCBot):
  | ckpt | method | vs Smart | vs MC |
  |---|---|---|---|
  | ckpt_bc | BC of SmartBot (20k rounds) | 48% | 29% |
  | ckpt_bc_dueling | same, dueling arch | 38% | — |
  | ckpt_distill_full (v5) | search distillation, full data, 5 ep | 42% | 38% |
  | **ckpt_distill_v6** | same, 12 epochs | **51%** | **41%** |
  v6 is the strongest standalone net: beats BC on both axes, parity-plus
  vs SmartBot, Elo ~25-30 above smart / ~70 below mc in its pool. The
  distillation series (v1-v3 failed at 32/22-ish; v4 soft targets 38/32;
  v5 42/38; v6 51/41) — full iteration history in RL_PLAN.md.
- **Dueling-architecture tax (measured)**: at near-equal imitation
  (88.2% vs 89.7%), dueling-BC plays 10 points worse than free-logits BC
  (38% vs 48%) — mean-zero A is a poor medium for a policy; free policy
  heads win for play, dueling only where value regression happens.
- **Hybrids (net-as-rollout-policy): measured dead end.** BC-hybrid 45%
  vs mc (n=40); v5-hybrid previewed at 55% (n=40) then REVERSED to 37%
  at n=60 — the bare v5 net out-rates its own hybrid in the pool (1088
  vs 1074). Net tail-failures get amplified by search, at ~100x cost
  (~2s/decision); a human player's "feels wonky" preceded the
  statistical verdict. Phase 4's remaining path: truncated rollouts +
  value-head leaves (unbuilt), which must beat plain mc to matter.
- **Ballot-mismatch incident (2026-08-01)**: the exhaustive-follow
  enumeration change silently broke the deployed net — trained on
  search-candidate ballots, it was suddenly scoring dozens of unseen
  action encodings at play time and collapsed to **Elo 798** in the pool
  (18% vs SmartBot). Fixed by matching play-time ballots to the training
  distribution (exhaustive mode retained for human-coverage analysis);
  recovery verified at exactly 48%. Lesson: encoding/enumeration changes
  invalidate every trained checkpoint — bump versions and re-verify.
- DMC self-play recipe v1: **closed** — flat ~30-34% vs SmartBot across
  400k rounds; measured cause: value regression crushed the BC score scale
  (cross-candidate spread 22.5 → 0.26 ≈ action-blind) under deal-luck
  label noise. Run record: `server/runs/dmc_v1.md`.
- **DMC self-play: still unsolved** — dmc2 (anchor + oracle baseline +
  gating + spread alarm) halted twice by its own alarm: Q-regression
  toward near-unpredictable advantage targets collapses ANY policy
  pathway it trains (regress-to-mean → action-blind), even
  scale-matched. Designed fix, unbuilt: AWAC-style advantage-weighted
  policy-head update. Oracle baseline validated offline (43-47% of
  outcome variance explained).
- **In progress overnight (2026-08-02)**: N=30 teacher-data regeneration
  (~24k rounds, 3x less label noise) → v7 trains on it in the morning.
  Plan, gates, full iteration history: RL_PLAN.md.

## Shared-code changes affecting ALL policies

- **2026-08-01 throw-ruffing fix**: no bot could contest a 甩牌 (candidate
  generator returned None for multi-component leads). Now all bots build
  shape-matching trump sets. Smart-vs-heuristic compressed 90% → 76% on the
  same seeds (the baseline can now punish safe throws — SmartBot's
  signature weapon). Numbers dated before this are pre-fix; Elo pool rerun
  pending.
- 2026-07-31 rules corrections (defend-at-A, format-scaled kitty
  multiplier) similarly shifted all measurements made before them.

## Experiment log (measured and rejected — reproducible via registry/toggles)

| idea | result | verdict |
|---|---|---|
| last-trick reserve (`smart-reserve`) | 55% alone, -15pt combined | hoarding loses; expert version (endgame control) adopted instead |
| trump draining v1 (`smart-trumpdrain`) | -4% | wastes trump control |
| trump draining v2 (banker-side, cheap trumps) | -4% | lost a third time, even expert-conditioned |
| feed on any partner ruff (`smart-feedtrump`) | -9% | overtrumped feeds gift points |
| tractor leads into ruff risk (`smart-anytractor`) | -4% | ruffed tractors lose big |
| conservative declaration (10/8) | -4% vs 8/6 | declaring is worth more than a perfect hand |
| declare the weaker suit + point-level eagerness | -2% | suit quality matters more than folk wisdom claims |
| partner-void feeding | neutral alone, -4% combined | interferes with endgame control |
| LEAD_MARGIN 8/12/999 (tempo hypothesis) | 51/47/50% ties | margin-5 + heuristic prior already filter the passive-rollout lead bias |
| mc-strong (N=30) | 61% ≈ default | sampling isn't the bottleneck; rollout quality is |

## Human-play validation set

Logs are the corpus (`logs/*.jsonl`, gitignored; server logs fetched via
`fetch_fly_logs.sh`). As of 2026-08-01: 245 genuine human play decisions
(per-play bot flag — watchdog takeovers excluded), 227 with outcome labels
converted to training shards (`rl/human_shards.py`).
- Agreement (all policies): heuristic 52%, smart 51%, mc 50%, rl-bc 49% —
  a STYLE metric, not strength (ranking inverts the Elo ladder).
- Gap decomposition: forced plays 100% agreement (after the exhaustive
  follow-enumeration fix; previously ~20% of humans' legal plays in narrow
  spots weren't on the ballot); leads 19% vs follows 59%; of disagreements,
  62% are value-ties (|Δ|≤3 pts), 23% favor the bot, 15% favor the human
  (mean -0.8). Realistic agreement ceiling for ANY policy: ~65-70%.
- Uses: regression tripwire (a policy dropping to ~30% = broken — would
  have caught the DMC collapse instantly); distribution-shift check for RL
  checkpoints; future human-style fine-tune.

## Lessons

- **Measure everything; adopt nothing on intuition.** Feature toggles +
  mirrored evals found every real gain and killed every plausible-but-wrong
  idea. Single-opponent numbers mislead: rate against the pool.
- **Hoarding loses, tempo wins** — every measured failure withheld strength
  (reserve, draining); every win spent it sooner (in-suit contesting, safe
  throws +17pt, eager declaration). The expert refinement that survived:
  contest everything in the endgame, not "save the big one for last".
- **Search beats heuristics; guarded search beats raw search.** MCBot's
  margin (heuristic prior unless the search is confident) out-rated pure
  argmax by 45 Elo — early-lead rollouts are noise-dominated.
- **Learned-policy pitfalls are measurable**: BC clones inherit skill but
  not robustness (29% vs the search); naive value regression destroys a
  pretrained policy's ordering before it can rebuild (audit: candidate
  score spread 22.5 → 0.26). Dense per-candidate targets (distillation)
  and anchored objectives are the countermeasures.
- **The expert-iteration chain works (2026-08-01 night)**: distill the
  search's EVALUATIONS, not its choices — its choices are part RNG
  (10-world sampling decides near-ties), so train toward
  softmax(candidate values/T) (v4, +6pts) and feed it enough data (v5,
  2.6M decisions, +4 more). The student comes out SEARCH-RESISTANT (38%
  vs MCBot; BC clone: 29%) because it learned the judge's values instead
  of a fixed teacher's habits. Then close the loop: that student as
  MCBot's rollout policy beat plain MCBot 55% — the first agent above
  the champion — confirming the sweeps' finding that rollout quality was
  flat-MC's binding constraint. Better net → better search → (next)
  better teacher.
