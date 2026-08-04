# AI policy ledger

Every bot policy, its design, and its measured performance. Update this file
whenever a policy is added, changed, or re-benchmarked. RL training plan and
post-mortems: RL_PLAN.md.

## Current status — 2026-08-04 08:15

- **Deployment-cost candidate:** `rl-override-v11pair` beats SmartBot 57.7%
  (n=480) and runs at p50 0.25ms / p95 0.52ms on the production numpy path.
  Its 51.1% against MC over 4,880 rounds is **SCREEN** evidence only because
  every MC factory in those blocks was OS-seeded. It is plausibly near MC, not
  formally confirmed equal and not superior.
- **Strength incumbent:** `mc` remains the default. Its search is not yet a
  correct belief sampler: normal mode may use a last-retry world that discards
  proven suit voids, and pair-voids are not enforced. Strict mode now rejects
  and counts the suit-void relaxation, but does not close the pair-void gap.
  Treat improvements and high-N labels built without strict evidence as
  provisional.
- **Retired strength arm:** `mc-vleaf-v7w-ep02` is 50.4% vs MC at n=1,200. It
  is an equal-strength speed candidate, not a stronger agent.
- **Not promotable:** `mc-gate-v11pair` has one encouraging n=300 online
  screen, but its T2 did not earn confirmation. The later five-arm T3 runner
  was invalid, partially run, and terminated; it produced no result. A repaired
  runner exists but has not passed artifact replay/all-seat fallback gates and
  has not produced a new result.
- **High-N prototype is not evidence yet.** Its reported 2.803-point MC regret
  is computed against a selected maximum on the same non-strict worlds used to
  choose/significance-filter 148 early-state rows. The completed 600-row set,
  partial 845-row corpus, refitted m0 policy, and completed but unseeded m0
  duel are debugging/SCREEN artifacts—not a stronger teacher or promotion
  result.
- **No valid v11 leaf exists.** v11pair predicts relative action deltas; its
  cross-state scale is unidentified. Root reranking/allocation is a valid use;
  MC/MCTS leaf evaluation requires a separately trained absolute value model.

Policy objective: maximize verified strength per unit of latency/compute.
RL-guided search is one contender and must beat direct v11, plain MC, and cheap
allocation rules on a common Pareto table.

## Using policies

Registered by name in `server/shengji/ai/registry.py`; the server reads
`SHENGJI_BOT` (**default `mc`**):

```bash
SHENGJI_BOT=smart uv run shengji-server   # e.g. an easier table
```

Benchmarking uses factories, deterministic policy seeds, and mirrored deal
clusters. Do not use `env.evaluate(make_bot(...), make_bot(...))` for a
reproducibility claim: it constructs stochastic bots without explicit seeds
and reuses their RNG state. The pairing harness no longer catches constructor
`TypeError`, but is still not a confirming harness: `_seeded()` currently
returns `None` for a seedless factory whose bot has no `rng`, and the repeat
test retains aggregate totals rather than per-seed/flip records.

```python
from shengji.ai.registry import make_bot
from shengji.ai.tournament import play_pairing

make_a = lambda **kw: make_bot("mc", **kw)
make_b = lambda **kw: make_bot("smart", **kw)
play_pairing(make_a, make_b, n_seeds=150, seed0=1_000_000)
```

Multi-policy Elo: `uv run python -m shengji.ai.tournament`. Human-agreement
tripwire: `uv run python scripts/eval_vs_human.py "../logs/*.jsonl"`.
Every confirming runner must also emit a manifest and per-seed/per-flip JSONL,
report paired signed level utility with clustered uncertainty, and fail on
fallbacks. Pool Elo and small-n rates are selection screens, not strength
claims.

## Ballot V3, lead layer — sourcing gap CONFIRMED, the fix NOT CONFIRMED (2026-08-04)

Codex's audit (verified exactly): the ballot MC actually searches covers 94.2%
of human plays, but misses **15.5% of LEADS** (93/601) against 2.0% of follows.
Per suit it only ever offers the top card and the lowest non-point card, so
every middle rank is unreachable. Nothing downstream can repair that — race4
only removes candidates from this list, and the high-N corpus values only what
is on it.

`mc-v3lead` offers one single per DISTINCT effective level, recovering **51 of
the 93 missed leads** (15.5% -> 7.0%) within the same cap.

Evaluated through `scripts/evaluate.py` (arm, control and reference on the same
400 mirrored deals, paired per-seed utility clustered by seed, bar declared
before the run):

| arm | win% vs mc | paired level utility/seed | rollouts |
|---|---|---|---|
| mc-v3lead | 47.5% | +0.065 ± 0.144 | 845,890 |
| reference (mc vs mc) | 46.2% | 0 | 725,910 |
| control (same slots, ARBITRARY singles) | 50.5% | +0.245 ± 0.247 | 847,890 |

**NOT CONFIRMED.** The arm's interval includes 0, and the random-fill control
scores nominally HIGHER — so whatever small movement exists is not attributable
to better sourcing. The arm also spends 17% more rollouts than mc for the
fuller ballot.

**The sourcing gap is real and the fix is not.** Recovering the missing leads
does not by itself make the search stronger: MC still has to VALUE them, and 10
worlds spread over a fuller ballot resolves each candidate worse. That points
at Codex's three-layer design — generation, then an archetype-aware SELECTOR,
then evaluation — rather than at simply generating more.

## Seeded pool of 2026-08-04 (current; heuristic = 1000)

| policy | Elo |
|---|---|
| mc-randrace4 (RANDOM-prune control) | 1159 |
| mc-race4-v11pair (net prior) | 1152 |
| mc | 1131 |
| rl-override-v11pair | 1129 |
| smart | 1091 |
| heuristic | 1000 |
| mc-vleaf-v7w-ep02 | 979 |

**Read this pool as unresolved, not as a ranking.** Every gap is <=28 Elo, and
gaps under ~40 have twice failed to survive a direct duel here (its predecessor
put vleaf +32 over mc; 1,200 rounds then measured 50.4%). Direct pairings at
120 rounds: mc-race4 52.5% vs mc, mc-randrace4 55.8% vs mc, and randrace4
edges race4 59-61.

What it DOES add: the RANDOM-prune control ranks at or above the net-prior arm
here, as it did in the paired confirmation. Two independent looks now agree the
learned prior adds nothing detectable, which is why the racing claim stays
retracted.

## Selection pool of 2026-08-03## Active policies

### `mc` — MCBot (server default)
Determinized Monte Carlo (`ai/mcbot.py`): samples 10 opponent-hand worlds
from public card counts and hand sizes, then rolls a bounded ballot to round end
with heuristic continuations. **Known correctness caveat:** the final sampling
retry may relax proven suit voids, pair-void constraints are not applied, and
normal mode may use the relaxed world. Used/rejected relaxation counters now
exist and strict mode rejects the suit-void relaxation; pair-voids remain
unenforced. It is determinized search, not yet a strict belief model. Choice is
guarded by:
- **Confidence margin** (5.0 pts/round): candidates[0] is SmartBot's pick;
  the search overrides only when it wins by the margin. Rollouts are
  noisiest early; the margin is worth ~45 Elo vs pure argmax.
- **TRACTOR_LOCK**: heuristic tractor leads are final (56% vs unlocked).
- **Point-shy tiebreak** (2.0): among near-tied candidates, risk the fewest
  points (a beaten 10-10 lead gifts 20 immediately).
- Current deployment table: p50 77ms / p95 150ms per decision on the mini
  (N=10, wide ballots). `SHENGJI_FAST=1` reduces full-round simulation from
  about 5.7s to 1.7s, but does not repair belief correctness.
- Hyperparameters fully swept and flat: N∈{5..30} (N=10 best), margin
  {0,2.5,5,7.5,10} (5 best), candidates {4,8,12} (8), SmartBot rollouts
  (tie at 5x cost), LEAD_MARGIN {8,12,999} (ties), LEVEL_OBJECTIVE / MC_BURY
  toggles (ties, available off by default). **Flat-MC parameter tuning is
  plateaued**; the next levers are constraint-correct beliefs, root allocation,
  and only then learned absolute evaluation (RL_PLAN.md).
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
  | **snapshots_v8a/ep03 (v8a)** | warm from v7w on gen-v3 (43k rounds, 2.33M dec, choice-only rows included) | 46%* | 34%* — NO improvement over v7w despite 2.2x data from a stronger teacher; suggests the TARGET (raw values vs acting policy) is the binding constraint, not data volume |
  | **snapshots_v7w/ep02 (v7w)** | WARM from v6, 4 ep on N=30 textbook (~1.5h) | 45%* | 32.5%* vs wide-mc |
  **v7w was the strongest STANDALONE net** (beat v6 in all 4 snapshots,
  best 64.5% n=200 games; ep02 selected by probe). Superseded as the
  interesting line entirely: standalone nets plateau at 38-48% vs mc,
  while the same weights used as an OVERRIDE on SmartBot beat it 57.7%
  (n=480). See `rl-override-v11pair` above. The clean anchor rerun that
  this entry once promised was made moot — those anchors were measured
  under a briefly-corrupted follow ballot, and the whole standalone line
  has since been measured many times under seeded anchors. Previously:
  v6 was the strongest standalone net. The
  distillation series (v1-v3 failed at 32/22-ish; v4 soft targets 38/32;
  v5 42/38; v6 51/41) — full iteration history in RL_PLAN.md.
- **Dueling-architecture tax (measured)**: at near-equal imitation
  (88.2% vs 89.7%), dueling-BC plays 10 points worse than free-logits BC
  (38% vs 48%) — mean-zero A is a poor medium for a policy; free policy
  heads win for play, dueling only where value regression happens.
- **Search hybrids are settled by role.** Replacing the rollout policy tied
  twice (the early v5 55% preview reversed, and a later 93-Elo-stronger roller
  still tied). The valid truncated-rollout + v7 absolute-value leaf reached
  **50.4% vs MC at n=1,200**: cheaper, not stronger. The v11pair “leaf” test is
  invalid because relative action deltas have no cross-state value scale.
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
- **DMC self-play: implementation unresolved, not a hypothesis rejection.**
  dmc2's spread alarm correctly halted two action-blind collapses, but those
  runs show that pipeline/target was unsafe—not that every Q or policy-gradient
  method must fail. AWAC-style policy updates remain a design candidate only
  after role-sign, immutable-checkpoint, replay, and fallback invariants pass.
  The oracle study explains 43-47% of outcome variance on its own distribution;
  it is a diagnostic, not a deployable value proof.
- **Overnight sweeps (2026-08-02, all probed vs current SmartBot on fixed
  seeds; CONTROL: v6 = 55%)**: temperature 0.03/0.10 → best 52%/52%
  (**null — 0.05 was right**, and sharp targets train unstably);
  big-trunk 1024 → best 47% (**null — capacity doesn't help; stay small**);
  v6.1 human-blend ep0 → 57% human-agreement vs v6's 51% (+6, the
  blend took). Strength: probe 50% (v6 control 55%) and DIRECT duel vs
  v6 46% (n=200) — a small strength tax (~2-4pts, borderline noise) is
  the likely price, not the free lunch the probe alone suggested.
  Caveats: agreement partly in-sample; direct-duel protocol added for
  all partial checkpoints after this exact case. Recipe robustness confirmed →
  **v7 = v6's exact recipe on the N=30 low-noise textbook** (20k rounds,
  24 shards, pairfix+voiddump teacher). That historical run is complete;
  standalone development is now paused pending a representation diagnostic.
  Plan, gates, and chronology: RL_PLAN.md.

## Shared-code changes affecting ALL policies

- **DECLARER_PIN (2026-08-03, MCBot default ON)**: sampled worlds place
  the declarer's SHOWN cards in the declarer's hand. Declarations are
  public, but the sampler was scattering them — a declared trump-rank
  PAIR got split across hands, making a beatable K-pair lead look boss
  (RTLT R9 T1: HK-HK valued best-on-ballot without the pin, second-worst
  with it; the bot's pick changes). Correctness-grade, `pair_is_boss`
  precedent; confirmation duel queued.
- **Throw penalty -> LOWEST beatable component (2026-08-03)**: a failed
  甩牌 now forfeits the smallest/lowest beatable part, not whichever the
  component scan met first (scan order put bigger structures first, so
  throws were systematically over-punished). Jerry's ruling from play;
  goldens deliberately regenerated.
- **Determinism + cache-safety fixes (2026-08-03)**: caller-order memo
  keys, defensive copies out of caches, sorted deck iteration. See
  CORRECTNESS.md incident log.

- **Memory.pair_void (2026-08-02)**: per-seat proof of "no pair left in
  this suit", inferred from the forced pair-matching rule (a follower who
  answers a pair/tractor lead with fewer in-suit pairs than led has, by
  rule, none). Free public info available to every consumer. The
  heuristic lead gate built on it (PAIR_VOID_BOSS) tied at n=400; the
  sharper use is constraining MC's world sampling. **That constraint is not
  implemented yet**, and the sampler's final retry can also drop ordinary suit
  voids. Any document saying sampled worlds are fully public-information
  consistent is stale.

- **CURRENT pool (2026-08-02 ~02:45, all four night upgrades incl.
  CONTROL_LEADS + TEMPO_GUARD, seeds 3000)**: mc 1067 > **smart 1061
  (statistical tie with the champion — mc's head-to-head edge narrowed
  to 53%)** > rl-v6 1023 > heuristic 1000. The night's heuristics closed
  most of the search's margin; the frozen net now trails both hand-built
  tiers (smart beat it 58%) — the bar v7 must clear. Human-agreement on
  the 827-decision corpus: heuristic/smart/mc all 55%, rl-v6 51%.
- **2026-08-02 night, four user-sourced upgrades (all adopted, stacking)**:
  pair_is_boss (+13pt, below), **TEMPO_GUARD** (no premium trumps on 0-point tricks — XCYB BJ incident), **VOID_DUMP** (junk dumps empty short suits
  first — 55% h2h vs prior smart, n=150), **CONTROL_LEADS** (leader
  hierarchy: non-boss pairs J+ → short-suit emptying → forcing non-point
  singles → junk last — **67% h2h, n=150, largest single-toggle gain
  measured**). Post-fix Elo re-baseline (seeds 2000): mc 1097 > rl-v6
  1068 > smart 1012 > heuristic 1000 (v6's apparent rise vs smart was
  noise: n=240 recheck = 54%, matching pre-fix). Pending measurement:
  RISKY_THROWS (near-boss A+QQ throws on MCBot's ballot), TRUMP_BALLOT
  (trump pair/top-trump candidates). Night record: server/runs/night_20260801.md.
- **2026-08-01 ~23:55 pair_is_boss fix (+13pt)**: pairs are beaten only by
  higher PAIRS — the old any-higher-card check vetoed unbeatable pairs
  (holding A+KK, AA is impossible, yet KK read "not boss"). User-spotted
  from prod-log lead-shape analysis (bots: 86% single leads, AA+K present
  but A+KK absent — the exact fingerprint). Post-fix smart vs heuristic:
  **89%** (was 76% on identical seeds). Affects SmartBot leads, MCBot
  candidates/rollouts, and all teacher data generated AFTER the fix (the
  N=30 set spans the fix; ACCEPTED rather than regenerated, and superseded
  anyway by gen-v3/gen-v4, which are entirely post-fix).
  All Elo/gate numbers measured before this are pre-pairfix.

- **2026-08-01 throw-ruffing fix**: no bot could contest a 甩牌 (candidate
  generator returned None for multi-component leads). Now all bots build
  shape-matching trump sets. Smart-vs-heuristic compressed 90% → 76% on the
  same seeds (the baseline can now punish safe throws — SmartBot's
  signature weapon). Numbers dated before this are pre-fix; Elo pool rerun
  pending.
- 2026-07-31 rules corrections (defend-at-A, format-scaled kitty
  multiplier) similarly shifted all measurements made before them.

## Toggle registry (canonical) — every flag, what it does, and its record

**SmartBot / HeuristicBot** (h2h = head-to-head vs same bot without the flag):

| flag | default | what it does | record | verdict |
|---|---|---|---|---|
| SAFE_THROWS | ON | leads multi-part throws (甩牌) only when card-counting proves every part unbeatable — free multi-card winners, penalty can never trigger | +17pt vs heuristic | adopted |
| CONTROL_LEADS | ON | when in the lead with no boss cards: try pairs (J+) first, then empty a 1-2 card suit, then a forcing high non-point single — junk only as true last resort | 67% h2h, n=150 | adopted |
| LATE_TRUMP_PAIRS | ON | with ≤12 cards left, lead the top trump pair — depleted opponents can't answer pairs (mined from human play: +7.3/decision, 8/8) | 60% h2h, n=150 | adopted |
| VOID_DUMP | ON | when discarding junk, shed from the SHORTEST suit first — empties suits to open future ruff opportunities | 55% h2h, n=150 | adopted |
| TEMPO_GUARD | ON | refuses to spend rank-trumps/jokers winning tricks worth 0 points (prod bot once burned BJ beating a rank-4 for nothing) | root-fix, verified on position | adopted |
| ENDGAME_CONTROL | ON | in the last ~6 tricks, contest every winnable trick regardless of points — controlling the finish beats saving cards | +2pt | adopted |
| BURY_TRUMP_GATE | ON | banker buries kitty points only when trump is strong enough to defend the last trick (11+ trumps incl. big joker); weak trump = never bury points | +1pt | adopted |
| BURY_VOID | ON | banker's bury deliberately empties 1-3 card suits (ruff setup) instead of spreading discards | ~+1pt | adopted |
| DECLARE 8/6 | ON | declares trump at 8 projected trumps (7 in the grace window) — eager beats waiting for a perfect hand (10/8 measured −4) | +2pt vs 9/7 | adopted |
| SAFE_TRACTOR_ONLY | ON | won't lead tractors into suits where an opponent has shown void (they'd get ruffed) | disabling: −4 | adopted |
| TEMPO_SEEK v2 | off | spends trump (even jokers, if the prize is big) to win the lead when boss pairs/tractors are waiting to be played | v1 48%, v2 53%, combo 49% n=200 | tie — noise |
| ANY_PAIR_OVER_JUNK | off | last-resort leads prefer any pair (even low) to a passive low single | 52%; combo 49% | tie — noise |
| TRACTOR_FIRST | off | ranks tractors above boss pairs in the lead order | 51% h2h | tie (tractors already led at step 2) |
| PARTNER_VOID_LEAD | off | leads suits your partner is void in so they can ruff for points | 50% alone, −4 combined | rejected |
| DECLARE_TUNE | off | declares the WEAKER of two long suits + extra-eager on point levels (5/10/K) — folk wisdom from strategy guides | −2pt | rejected |
| TRUMP_DRAIN | off | leads boss trumps from long holdings to strip opponents' trumps early | −4pt | rejected |
| TRUMP_DRAIN_V2 | off | same idea, banker-side only with cheap trumps (expert-conditioned version) | −4pt | rejected |
| FEED_ON_TRUMP | off | throws point cards to a partner winning with trump even when they could be overtrumped | −9pt | rejected |
| RESERVE_LAST | off | attackers hold back a boss pair/tractor for the last trick (kitty multiplier) | −11pt | rejected (hoarding loses) |
| POINTS_DRY | off | once points-in-circulation hits 0, stop spending premium trumps outside the endgame window (user idea; Memory.points_left is exact from public info) | 100-100, 50% n=200 | tie — the regime is real but rare + TEMPO_GUARD/search already cover most of it; points_left() kept in Memory for future consumers |
| ACE_SEQ | off | cash boss singles in follow-able suits before ruff-risky ones (expert research #1) | 50% h2h n=200 | tie — search/ruff-risk already covers it |
| NO_OPEN_POINT_SUIT | off | don't open point-bearing suits without their boss (expert research #3) | 50%; combo also 50% | tie |
| TEMPO_SEEK v2 (re-test 08-03) | off | re-measured on the current stack + fast engine | 98-102, 49% n=200 | tie confirmed |
| DECLARER_PIN | **ON** | sampled worlds place the declarer's SHOWN cards in the declarer's hand (public info the sampler ignored) | **60-60, 50% n=120** | KEPT on correctness grounds: provably-correct information, fixes verified blunders (RTLT R9 T1 flips), costs nothing. Correctness-grade changes must not LOSE, not necessarily win. |
| KITTY_POINT_POLICY | off | expert research #2: numeric bury caps — locked hand (13+ trumps, BJ) deliberately banks 10s/Ks behind the kitty multiplier; weak trump makes points near-unburiable | 101-99, 50% n=200 | tie |
| TREE_PLANTING (树套) | off | expert research #4: with a 6+ card side suit holding top pairs, lead LOW early to exhaust the suit, then run the retained tops (deliberately overrides pairs-first) | **90-110, 45% n=200**; combined with kitty 46% | **rejected — the only expert candidate to measurably HURT** |
| BANKER_KITTY | **ON** (correctness) | the banker counts its OWN buried cards as known | **149-151 = 49.7%, Wilson95 [44.0%, 55.3%]** (n=300, fixed code, seeds 900k, `scripts/kitty_duel.py`) — no measurable strength effect either way | kept because it is true information the sampler already used; the three earlier duels are VOID (they ran while this flag silently disabled banker search — incident 2026-08-03) |
| SIZE_FIRST | off | strict "more cards is better" lead order: any ruff-safe tractor, then any ruff-safe pair, before all smaller leads | 52% h2h, n=200 | tie (consistent with its halves TRACTOR_FIRST + ANY_PAIR_OVER_JUNK both null) |
| PAIR_VOID_BOSS | off | leads a LOW pair once every opponent has PROVEN pair-void in its suit (forced pair-matching makes a broken answer proof) | 54% first n=200, 48% fresh n=200 → 51.0% at n=400 | tie — small-n mirage caught by extension; Memory.pair_void tracker kept (see shared-code changes) |

**MCBot** (search-level knobs on top of SmartBot):

| knob | value | what it does | record | verdict |
|---|---|---|---|---|
| MARGIN | 5.0 | SmartBot's pick is the incumbent; the search only overrides it when a candidate wins the rollouts by 5+ points/round — guards against early-round rollout noise | beat argmax 62% (~45 Elo) | adopted |
| N_DETERMINIZATIONS | 10 | how many hidden-hand worlds are sampled per decision | 5→48%, 10→62%, 15→65%, 30→61% | adopted (≥10 flat) |
| MAX_CANDIDATES | 8 | how many candidate plays the search evaluates | 4→58%, 12→60% | adopted |
| TRACTOR_LOCK | ON | when the heuristic wants to lead a tractor, that's final — no rollout override | 56% h2h | adopted |
| POINT_SHY_EPS | 2.0 | among near-tied candidates, play the one risking the fewest points (a beaten 10-10 lead gifts 20) | from the 10-10 lead analysis | adopted |
| LEVEL_OBJECTIVE | off | scores rollouts by scoring brackets (the 80/40-point cliffs) instead of raw points | 59% vs 62% ref | tie |
| MC_BURY | off | searches the banker's bury: heuristic pick vs loose/strict/no-void variants over sampled worlds | 62% = ref | tie |
| LEAD_MARGIN | off | a higher override bar for leads specifically | 8/12/999 → 51/47/50% | tie |
| SmartBot rollouts | off | uses the memory-aware bot instead of the fast heuristic to play out sampled worlds | tie at 5x cost; **RE-TESTED 2026-08-03 with SmartBot now 93 Elo above heuristic: 62-58 = 52%, still a tie** | rejected — twice. Rollout-policy STRENGTH does not matter even at a large gap; rollout seats reward robustness and speed, not skill. |
| RISKY_THROWS | off | puts near-boss throws (A+QQ where only one higher pair threatens) on the ballot; worlds price the risk | 53% at MC, n=120 | tie (combo w/ TRUMP_BALLOT pending) |
| TRUMP_BALLOT | off | adds trump-pair and top-trump lead candidates (钓主) for the worlds to price | 53% at MC, n=120 | tie (combo pending) |
| WIDE_LEAD_BALLOT | **ON** | leads roll out EVERY pair, tractor, and near-boss throw in every suit incl. trump (lead cap 8→14). Fix for the JVRA sourcing gap: ♣A♣A/♣8♣8 never reached the rollouts | **62% vs narrow mc (75-45, n=120), +7% latency** | **adopted — largest MC gain since the margin rule; sourcing > preference confirmed** |

**Engine corrections** (not flags — permanent): throw-ruffing (all bots
can contest 甩牌), pair_is_boss (+13pt), beats() alternative
decompositions, defend-at-A, format-scaled kitty multiplier, throw
penalty forces the beaten component, exhaustive-follow enumeration
(analysis-side).

## Sourcing coverage (rerun 2026-08-04, human corpus n=2,061)

Does the action ballot actually contain the move a human played?

| ballot | missing | coverage |
|---|---|---|
| v1 (narrow) | 312/2112 | 85.2% |
| **v2 (widened — throws + component combos)** | **19/2112** | **99.1%** |

The v2 ballot is what teacher generation and training use. Residual misses are
concentrated in rare follow-throws and one pair case. The 2026-08-02 audit that
motivated the widening (n=1052, v1 missing 15.3%) is in
`docs_archive/sourcing-audit-2026-08-02.md`.


## Learned override (residual distillation)

| policy | what it is | measured | verdict |
|---|---|---|---|
| `rl-override-v11pair` | SmartBot + learned pairwise override on `(q_i - q_0)`, threshold 0.02 fitted on calibration A and read on report B, matched train/play ballot | **CONFIRM vs Smart:** 57.7% (277-203, n=480). **SCREEN vs MC:** 51.1% over n=4,880, but every MC opponent was unseeded; no superiority and no formal non-inferiority claim | current deployment-cost candidate; no search, numpy p50 0.25ms / p95 0.52ms |
| `mc-vleaf-v11pair` | attempted to use v11pair's pairwise head as a leaf | 32.5% vs MC (39-81, n=120) | **INVALID configuration**, not a leaf-learning result: cross-state scale is unidentified; quarantined and unregistered |
| `mc-gate-v11pair` | v11 delta detects states on which the registered policy escalates from SmartBot to full MC | online **SCREEN** 53.3% vs MC (n=300); 55% timing was extrapolated. T2 missed its declared bar, but noisy max-Q/candidate-count bias prevents the stronger “cheap gate explains it” conclusion | not adopted; the attempted equal-budget T3 was invalid/terminated. Its repaired runner has no valid replayed result yet |
| `rl-override-v11pair-m0` | same net with the override margin removed, post-hoc fit on the prototype N=240 estimates | offline selected-max regret was lower than deployed on its held-out half (1.132 vs 1.141); online **SCREEN** 235-265 = 47.0% vs OS-seeded MC, Wilson [42.7%, 51.4%] | **not promoted**. It did not show an advantage; it was not a seeded same-block comparison with the 0.02 rule and is not a clean rejection |
| `rl-override-v10res` | the same idea with an independent-row objective and a MISMATCHED play-time ballot | 47% vs smart; overrode 1.5% of states where the teacher overrode ~15% | near no-op — the checkpoint failed, not the idea |

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
| TRACTOR_FIRST (tractors above boss pairs) | 51% h2h tie, n=150 | tractors already prioritized at step 2 + tractor-lock; the ordering margin is rare |
| TEMPO_SEEK (cheap trump for the lead when boss follow-up waits) | 48% h2h tie, n=150 | in-suit tempo rule + endgame control already capture most tempo value |
| TEMPO_SEEK v2 (premium trumps allowed for big follow-ups) | 53% h2h, n=150 | +5 over v1 in the predicted direction but still within noise; off |
| ANY_PAIR_OVER_JUNK (last-resort pair leads at any level) | 52% h2h tie, n=150 | control-leads hierarchy already avoids most passive junk |
| mc-strong (N=30) | 61% ≈ default on the small sweep | increasing N alone did not establish a gain; this does not identify rollout quality as the bottleneck |

## Human-play validation set

**Current shard: 1,850 human decisions** (`rl_data/human_v4`, verified from the
NPZ shape on 2026-08-04). The 59-round / 1,592-decision statistics and 99.2%
ballot-coverage analysis below were computed on the superseded `human_v3`
snapshot; retain them as historical diagnostics until v4 is re-audited.
That v3 miner found humans ahead on early trump-pair leads (+2.0/decision) and
late mixed throws (+1.8), while the bot was ahead on late trump-single leads
(-9.6/decision).

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
  idea. Small pools and single point estimates both mislead: use pools for
  selection and preregistered paired direct anchors for strength.
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
- **Distillation works; the expert-iteration flywheel did not close.** Soft
  per-candidate search values improved standalone students over behavior
  cloning, and the correctly implemented v11 pairwise objective produced a
  strong direct override. But the early 55% rollout-policy preview reversed,
  a second stronger-rollout test tied, and training on hybrid-generated data
  did not produce a better value leaf. Current lesson: optimize the exact
  deployed root decision, preserve ballot identity, and do not infer
  “better net → better search” without a direct equal-budget result.
