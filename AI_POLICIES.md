# AI policy ledger

This is the authoritative synthesized ledger for callable bot policies,
policy-affecting behavior, and conclusions that survived the measurement
rules. It is deliberately **not** a notebook or live conversation.

- Active priorities and gates: `BACKLOG.md`
- Running and completed compute: `JOBS.md`
- Reviewer/Claude discussion: `HANDOFF_REVIEW.md`
- Model chronology and post-mortems: `RL_PLAN.md`
- Superseded detail: `docs_archive/`

**Structure.** Everything above the `# Working notes` fold is synthesis and
durable reference: what is true now, what is callable, what each flag does.
Everything below is dated measurement detail, kept because a number without its
protocol is how six claims were made and lost — but it is not what a reader
should act on.

Update the top only when a policy's behavior or role changes, or when new
evidence changes a synthesized conclusion. Append run reports below the fold,
and when a run changes a conclusion, EDIT the synthesis rather than letting the
newest entry sit on top and speak for the file.

## Current synthesis — 2026-08-05 18:50

- **More search width is not the next lever.** N=5->N=10 was large,
  N=10->N=30 was +0.262 +/- 0.154 confirmed, and N=30->N=60 was
  **-0.002 +/- 0.119 on current main**. That last block found no advantage but
  did not test equivalence; do not repeat it without a new mechanism and full
  accepted/rejected-world accounting.
- **N=30 REPRODUCES ON CURRENT MAIN.** Frozen-current confirmation, 504
  preregistered fresh clusters (seeds 102M): **+0.222 +/- 0.140** vs N=10,
  arm-minus-null +0.230 +/- 0.139, null -0.008 +/- 0.154, win rates
  55.2/50.9/51.2. The `e3aeec1` result (+0.262 +/- 0.154) therefore transfers
  to the deployed executable despite the sampler, ballot and decompose changes
  in between. Caveat: these shards predate the `rejected_worlds` counter, so
  like the N=60 lane this is a policy-as-run comparison rather than proof of an
  exact accepted dose.
- **DEPLOYED STRENGTH INCUMBENT:** prod runs compiled `mc-strong` (N=30),
  exposed as `{"bot":"mc-strong","fast":true}`. The production image builds
  the Cython extension, taking the measured path from about 45ms/decision
  (N=10 pure Python) to 36ms (N=30 compiled). A fresh current-main block over
  504 preregistered clusters confirmed `+0.222 +/- 0.140` versus N=10;
  arm-minus-null was `+0.230 +/- 0.139` and null was `-0.008 +/- 0.154`.
  No learned policy, value leaf, learned search prior or ballot variant has a
  verified edge over it.
- **Best learned result:** `rl-override-v11pair` beats SmartBot 57.7% (n=480)
  and is very fast, but its MC comparison is unseeded screen evidence. It is a
  deployment-cost candidate, not the strongest verified bot.
- **Main strength hypothesis — TESTED AND NOT SUPPORTED (2026-08-05).** The
  hypothesis was that improving lead-ballot SELECTION, then letting MC evaluate,
  would buy strength. The DEV-512 screen ran all six registered arms on 512
  frozen lead states and **selected no design**: primary `quota - random_fill`
  `+0.110 +/- 0.337` includes 0, and at EQUAL WORK the shipped ballot has the
  lowest mean regret (0.135) with every redesign worse — quota 0.229, v3 0.281,
  random_fill 0.339. Codex reproduced the aggregate and accepted SELECT NONE.
  The one contrast that resolves is the high-work pair, favouring more MC over
  brute-force widening (`-0.495 +/- 0.477`). So the lever is not WHICH actions
  get priced but HOW MUCH search prices them — and the N=60-vs-N=30 lane already
  found no confirmed gain above N=30. State this carefully: DEV supports only
  that **no REGISTERED ballot design advances at this resolution** — it does not
  establish that action selection can never be a lever, and the N=60 interval
  was a superiority test that did NOT establish equivalence. Both lanes are
  measured and neither produced a winner; that is weaker than "neither is a
  path forward", which is what this entry said before Codex corrected it. Mark it a DEV SCREEN, not a strength
  claim: DEV selects designs, it does not establish playing strength. CALIB and
  REPORT remain sealed, because the contract runs CALIB on one DEV-selected
  design and there is none. The 51.2%/0.9% structured-omission figures still
  describe the ballot's coverage; they no longer motivate a redesign.
- **Data conclusion:** the 20,845-state high-N artifact is a replayable state
  reservoir, not an oracle. Its old-ballot/non-strict/same-world-selected labels
  have produced no online gain. The 12,000-state late supplement is raw-state
  distribution correction and has not yet been cleanly relabelled or trained.
- **Correctness work bought no measurable STRENGTH**, but bought trustworthy
  measurement: current `mc` vs the pre-fix bot layer is -0.054 +/- 0.156
  (provisional; the old bot's zero-world decisions make it not protocol-clean).
  N=30 was unconfirmable before the sampler rewrite and confirmable after.
- **Sampler distribution fidelity is materially biased, and measured.** Mean TV excess
  0.161 over the sampling-noise floor; 6 of 8 enumerable states materially
  biased. This blocks posterior-correctness and clean-label claims; it did not
  block the completed DEV screen, whose estimand deliberately froze the
  production sampler as part of each policy. Shared proposal/report worlds
  lower variance but do not make the posterior correct.
- **Sampler P0 certificate is temporarily OPEN after a population audit.** The
  earlier `eea78d2` artifact was original-only because one global limit starved
  later sources, despite being described as original+late, and it predates skip
  counters. `fc19d26` now requires original/late/deep with exact 500/500/500
  quotas and 120 toys, but the retained v2 artifact is pre-commit and dirty;
  the gate also needs `rejected == 0` and `accepted == requested` wired into
  `certified` before one clean current rerun. The underlying work did find and
  fix allocator dead-ends, forbidden declared-card pair completion and ignored
  tractor run caps; do not turn those real fixes into an overstated population
  certificate.
  **NOT certified: distribution fidelity — now MEASURED, and the two named
  causes do not account for it.** Against a uniform-over-PHYSICAL-DEALS
  reference on 24 enumerable states (paired, pairing machine-verified):
  `_splits` sampling count matrices roughly uniformly is a real contributor —
  weighting them cuts excess TV by `-0.060 +/- 0.031`, CONFIRMED. `_deal_suit`
  preferring distinct codes is NOT — `-0.0001 +/- 0.0027`, bounded to nothing.
  A third cause is unidentified: baseline excess stays at `0.109` after the
  reference itself was repaired, so it is neither of the named biases nor an
  artifact of the old flat-over-multisets reference (which explained only ~6%).
  Two counting defects were found and repaired in the measurement apparatus
  itself: the reference collapsed physical deals into multisets, and `_fills`
  counts `AABB, 2/2` as 3 rather than the physical 6.
  **TV excess is a weak proxy for what the pilot cares about, because the
  enumerable population is mostly decision-degenerate.** 54 of 84 enumerable
  states have every candidate returning an identical value on every world — with
  two cards left `C2` and `H2` are the same move — so no sampler could change
  the choice there, yet those states carry the TV. On 30 decision-LIVE states
  (N=30, 600 reps) the bias-attributable excess argmax disagreement is
  `-0.0066 +/- 0.0169` and excess regret `-0.0098 +/- 0.0171` — neither
  distinguishable from zero — while a PERFECT sampler at the same N already
  disagrees with the exact argmax up to 20.3% from Monte Carlo noise alone.
  **But "zero on average" is not "harmless per state":** only 9 of 30 live
  states disagree at all, and among those the excess swings from `+0.158`
  (seed 880050: biased 32.2% vs control 16.3%) to `-0.160` (seed 880060, where
  the bias happened to help). So the bias does move individual decisions
  materially in BOTH directions, with no detectable systematic direction. This
  is bounded evidence that noise dominates bias in aggregate at N=30 — NOT
  evidence the sampler is correct, and not a reason to ignore per-state
  variance in a pilot that aggregates per-state regret. NOTHING IS ADOPTED — all
  sampler flags default OFF. **Two estimands, decided 2026-08-05 (Codex):**
  the CORRECTNESS estimand — does the sampler draw the true physical-deal
  posterior — is NOT certified and stays open; weighted splits are slow and
  still biased, so all three flags remain OFF. The STRENGTH-SCREEN estimand —
  which ballot/search design decides best when paired with the sampler
  production actually deploys — is legitimate and is what DEV-512 answers. The
  sampler is frozen as PART OF THE POLICY under test. So: do NOT call the
  distribution posterior-correct or the bias harmless, and do NOT block the DEV
  screen on an exact-posterior research project. A DEV winner needs CALIB plus
  paired online confirmation before promotion, and must be revalidated if the
  sampler ever changes. No further enumerable-regime posterior or
  decision-sensitivity measurement is requested.
  `CORRECTNESS.md` is authoritative for the exact proof obligations,
  certification boundary and sampler incidents.
- **Determinization is version-pinned CONFIRMED.** On the corrected sampler,
  the preregistered fresh 504-cluster block measured N=30 minus N=10 at
  `+0.262 +/- 0.154`, with a flat true null. It ran before the later action-
  semantics/tractor-ballot changes, so it establishes the sampled version's
  dose result but does not by itself promote current `main`.
- **RL/search architecture boundary:** AlphaZero-style MCTS is not the next
  champion path. Shengji is a four-seat, decentralized hidden-information team
  game, so a private observation has no strategy-independent scalar leaf value.
  Near-term search stays at the root over calibrated beliefs with a better
  proposal/allocation policy; long-term tree search requires public belief
  state and policy-consistent continuation. Literature mapping and sources are
  in `RL_PLAN.md`.
- **DMC2 is implementation-invalid, not an RL rejection.** It signs terminal
  return by the acting team but subtracts the attacker-perspective oracle from
  defenders without flipping the oracle sign. Its scalar residual is also not
  Suphx's privileged-policy curriculum, and the warm-started dueling recipe is
  not DouZero's from-scratch role-specific direct-Q baseline. Preserve the
  alarms/scaffolding; do not interpret the two halted runs as testing either
  paper's hypothesis.
- **Next strength work:** the ballot lane ended at SELECT NONE; CALIB and REPORT
  remain sealed. The next named hypothesis is fixed-budget common-world root
  allocation on the incumbent ballot, with matched uniform and random-
  allocation controls. Register power/feasibility first and reject without a
  run if the remaining fresh deals cannot resolve the declared effect.

## Policy status details

- **Deployment-cost candidate:** `rl-override-v11pair` beats SmartBot 57.7%
  (n=480) and runs at p50 0.25ms / p95 0.52ms on the production numpy path.
  Its 51.1% against MC over 4,880 rounds is **SCREEN** evidence only because
  every MC factory in those blocks was OS-seeded. It is plausibly near MC, not
  formally confirmed equal and not superior.
- **Strength incumbent:** deployed `mc-strong` is N=30 search over the current
  MC policy. Its count-first sampler now
  consumes declaration, void, remaining-pair and remaining-tractor-run
  constraints. Normal mode can still use the final void-relaxing retry, while
  evidence-producing evaluation requires `SHENGJI_REQUIRE_VOIDS=1` and clean
  sampler counters. The current three-reservoir P0 certificate is pending the
  clean rerun described above; posterior fidelity is also open. Old non-strict
  labels therefore remain provisional even though strict policy evaluations
  can fail closed on their own counters. See
  `CORRECTNESS.md` for the certified boundary rather than inferring it from a
  policy result.
- **Retired strength arm:** `mc-vleaf-v7w-ep02` has no verified edge over MC.
  Its historical 50.4% at n=1,200 predated the leaf factory's seed-forwarding
  repair. In the current hardened screen it scored 52.8% and
  `+0.024 +/- 0.215` paired utility versus the MC reference: not confirmed.
- **v13abs is not promotable:** it improved offline `Q^H(s,a)` fit, then tied
  v7 at 52.8%; the direct paired v13-minus-v7 contrast was
  `-0.028 +/- 0.185`. Its training states were much earlier than its deployed
  leaves, and its high-N `MCBot._candidates()` training ballot did not match
  the pinned-v1 `enumerate_actions()` ballot maximized at the leaf.
- **Closed strength arm:** `mc-gate-v11pair` had one encouraging n=300 screen,
  but its offline gate failed and its attempted multi-arm run was invalid.
  Learned root-prior racing was independently refuted by a random-prune
  control. Neither is on the current champion path.
- **The high-N corpus is diagnostic, not an oracle.** The completed artifact
  has 20,000 Air states plus an accidentally merged 845-state mini partial,
  but uses non-strict worlds, the old capped ballot, raw-point heuristic
  continuation labels, and an overwhelmingly early-state distribution. Its
  selected-maximum “regret” analyses and the unseeded m0 duel are SCREEN
  artifacts, not promotion evidence.
- **No valid v11 leaf exists.** v11pair predicts relative action deltas; its
  cross-state scale is unidentified. Root reranking/allocation is a valid use;
  MC/MCTS leaf evaluation requires a separately trained absolute value model
  whose state, action-ballot, perspective, and return contracts match the leaf.

Policy objective: maximize verified strength. Latency is not a tradeoff for
the champion policy; measured compute and matched-work controls remain useful
for attribution. The immediate contender is structured lead proposal plus MC,
not another broad standalone-RL or value-leaf run.

## Using policies

Registered by name in `server/shengji/ai/registry.py`; the server reads
`SHENGJI_BOT` (**default `mc`**):

```bash
SHENGJI_BOT=smart uv run shengji-server   # e.g. an easier table
```

Benchmarking uses factories, deterministic policy seeds, and mirrored deal
clusters. The factory seed boundary is now tested and constructor failures are
not swallowed. `play_pairing` and Elo pools remain selection tools; every
strength claim goes through `scripts/evaluate.py`, which writes exclusive
per-seed/per-flip records and a manifest, clusters uncertainty by deal seed,
enforces the preregistered bar, and reports the paired arm-minus-control
contrast.

```python
from shengji.ai.registry import make_bot
from shengji.ai.tournament import play_pairing

make_a = lambda **kw: make_bot("mc", **kw)
make_b = lambda **kw: make_bot("smart", **kw)
play_pairing(make_a, make_b, n_seeds=150, seed0=1_000_000)
```

Multi-policy Elo: `uv run python -m shengji.ai.tournament`. Human-agreement
tripwire: `uv run python scripts/eval_vs_human.py "../logs/*.jsonl"`. Pool Elo,
unpaired blocks, and small-n rates are selection screens, not strength claims.

## Active policies

### `mc` — MCBot (server default)
Determinized Monte Carlo (`ai/mcbot.py`): samples 10 opponent-hand worlds
from public card counts and hand sizes, then rolls a bounded ballot to round end
with heuristic continuations. The count-first allocator consumes declaration
pins, suit voids, and remaining-pair constraints; normal mode may still use its
final void-relaxing retry, while confirming runs require strict voids. The
independent full-history certifier remains open, and even a legal-world sampler
is not automatically a calibrated posterior. It is determinized search, not a
certified belief model. Choice is guarded by:
- **Confidence margin** (5.0 pts/round): candidates[0] is SmartBot's pick;
  the search overrides only when it wins by the margin. Rollouts are
  noisiest early; the margin is worth ~45 Elo vs pure argmax.
- **TRACTOR_LOCK**: heuristic tractor leads are final (56% vs unlocked).
- **Point-shy tiebreak** (2.0): among near-tied candidates, risk the fewest
  points (a beaten 10-10 lead gifts 20 immediately).
- Current deployment table: p50 77ms / p95 150ms per decision on the mini
  (N=10, wide ballots). `SHENGJI_FAST=1` reduces full-round simulation from
  about 5.7s to 1.7s, but does not repair belief correctness.
- Most hyperparameters are flat at the high end: margin {0,2.5,5,7.5,10}
  (5 best), candidates {4,8,12} (8), SmartBot rollouts (tie at 5x cost),
  LEAD_MARGIN {8,12,999} (ties), and LEVEL_OBJECTIVE / MC_BURY (ties, off by
  default). The old sampler did not establish N=30 over N=10
  (`+0.101 +/- 0.150` on fresh confirmation); one post-rewrite selection block
  was positive (`+0.290 +/- 0.210`) but formally void and unconfirmed. Run one
  clean dose confirmation, but treat lead proposal/selection—not indiscriminate
  search scaling—as the main structural lever.
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
`rl/torch_policy.py`: net argmaxing over enumerated legal actions; needs
`uv sync --group rl` + `SHENGJI_RL_CKPT` (checkpoints local, gitignored).

**This line is PAUSED as a development target** (Codex ruling 2026-08-04):
kept as the cheap diagnostic and deployment baseline, not pursued for strength.
Standalone nets historically screened around 38-48% vs mc across the tested
levers. No single cause has been established; label quality, representation,
ballot coverage, and train/deploy alignment have all been confounded at least
once.

**Model history lives in one place.** See RL_PLAN.md, “Model lineage: v7
through v13,” for the authoritative intervention/evidence/verdict table. This
ledger intentionally does not duplicate that chronology; it records callable
policies and their present roles.

Operationally, the standalone checkpoint line is paused; v11pair is retained
as a direct override/root-ranking candidate because it is the only learned
model with a confirmed gain (against SmartBot, not MC); and v13abs is an
experimental absolute action-value leaf that was **NOT CONFIRMED**. The old
prototype's “~2.8 points of headroom” is a selected, non-strict early-state
HYPOTHESIS, not a measured global ceiling. v13 cannot validate or refute that
hypothesis because its training distribution and deployed leaf distribution
did not match in either state phase or action ballot.

- **Dueling-architecture tax (measured)**: at near-equal imitation
  (88.2% vs 89.7%), dueling-BC plays 10 points worse than free-logits BC
  (38% vs 48%) — mean-zero A is a poor medium for a policy; free policy
  heads win for play, dueling only where value regression happens.
- **Search hybrids are settled by role.** Replacing the rollout policy tied
  twice (the early v5 55% preview reversed, and a later 93-Elo-stronger roller
  still tied). The truncated-rollout + v7 absolute-value leaf has no confirmed
  strength edge: its historical n=1,200 run had an unseeded leaf arm, and its
  current hardened screen was `+0.024 +/- 0.215` versus the MC reference. The
  v11pair “leaf” test is invalid because relative action deltas have no
  cross-state value scale.
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
  dmc2's spread alarm correctly halted two action-blind collapses, but the
  target has a concrete role-sign defect: defender returns are negated while
  the attacker-perspective oracle is not. The “Suphx oracle” label is also
  wrong—Suphx gradually removed privileged features from a policy—and the
  recipe is not a faithful DouZero baseline. AWAC/DMC may resume only after
  attacker/defender symmetry, immutable-checkpoint, replay and fallback
  invariants pass. The oracle's 43-47% explained variance is a diagnostic on
  its own heuristic trick-start distribution, not a value ceiling.
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

- **Memory pair constraint (2026-08-04)**: when a follower answers a pair or
  tractor lead with fewer pairs than were led, forced following proves zero
  pairs remain in that suit. `Memory.pair_cap` records zero, `pair_void` is its
  compatibility view, and MCBot now consumes the bound. A rule-derived test
  checks both engine legality and the real hidden hand. The first independent
  certifier nevertheless exposed a pin-plus-sampled-copy interaction, now
  fixed; full sampler certification remains open as described above.

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
| SmartBot rollouts | off | uses the memory-aware bot instead of the fast heuristic to play out sampled worlds | tie at 5x cost; **RE-TESTED 2026-08-03 with SmartBot now 93 Elo above heuristic: 62-58 = 52%, still a tie** | rejected — twice, on cost. Both are FAILED SUPERIORITY tests: a 93-Elo-stronger roller did not win, which does NOT establish that rollout strength is irrelevant. The honest reading is that no continuation has been shown stronger at 5x cost; equivalence was never tested. |
| RISKY_THROWS | off | puts near-boss throws (A+QQ where only one higher pair threatens) on the ballot; worlds price the risk | 53% at MC, n=120 | tie (combo w/ TRUMP_BALLOT pending) |
| TRUMP_BALLOT | off | adds trump-pair and top-trump lead candidates (钓主) for the worlds to price | 53% at MC, n=120 | tie (combo pending) |
| WIDE_LEAD_BALLOT | **ON** | leads roll out EVERY pair, tractor, and near-boss throw in every suit incl. trump (lead cap 8→14). Fix for the JVRA sourcing gap: ♣A♣A/♣8♣8 never reached the rollouts | **62% vs narrow mc (75-45, n=120), +7% latency** | **adopted — largest MC gain since the margin rule; sourcing > preference confirmed** |

**Engine corrections** (not flags — permanent): throw-ruffing (all bots
can contest 甩牌), pair_is_boss (+13pt), beats() alternative
decompositions, defend-at-A, format-scaled kitty multiplier, throw
penalty forces the beaten component, exhaustive-follow enumeration
(analysis-side).

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

---

# Working notes

Dated run reports and measurement detail. Nothing here is a
conclusion on its own — the synthesis above is what a reader should
act on. Entries are kept because a number without its protocol is
how six claims were made and lost, but they are deliberately below
the fold.

## Did the correctness work buy strength? NO measurable gain (2026-08-05)

`mc` (current) vs `mc-prefix` (the BOT layer frozen at `b3f8f61`: old greedy
sampler, no `pair_cap`/`run_cap`, no canonical hand order), both N=10, 504
clusters at seeds 103M, control `mc-prefix-null`.

**NOT preregistered** (corrected 2026-08-05 — this section previously said it
was). No block size, bar or primary contrast was registered before the run, and
it is protocol-failed besides, so it is a post-hoc SCREEN and cannot confirm or
refute anything on its own.

| contrast | result |
|---|---|
| **current minus pre-fix (PRIMARY)** | **-0.054 +/- 0.156, INCLUDES 0** |
| current minus null | -0.183 +/- 0.155, excludes 0 |
| null minus pre-fix | +0.129 +/- 0.153, includes 0 |

win rates 48.3% / 52.1% / 49.0%.

**PROVISIONAL, not confirmable.** The aggregator refused a clean report: 4
zero-world decisions, all in the pre-fix arms. That is the exact defect the
sampler rewrite removed, so the old bot exhibiting it is expected — but it
means exposure is unequal and the contrast is not protocol-clean. Reported with
`--allow-problems`.

**The honest reading: today's correctness work did not measurably improve
playing strength.** The point estimate is slightly NEGATIVE and the interval
comfortably includes zero. The three contrasts are arithmetically consistent
(-0.054 - 0.129 ~ -0.183), so the one interval that excludes zero is explained
by the control's draw rather than by the arm being worse.

This matters because it contradicts an intuition worth naming: Jerry observed
the bots seeming to play noticeably better, and more 甩牌 leads appearing. The
throws part is real and mechanical — `find_tractor_runs` was omitting tied-code
tractors, so fixing it literally added lead candidates. But "plays better" does
not survive measurement at n=504.

**What the correctness work DID buy** is measurement that can be trusted. The
old sampler produced zero-world decisions — searches that fell back to the
heuristic pick with no search at all — and they appear in this very run. N=30
over N=10 was NOT confirmable before the rewrite (+0.101 +/- 0.150) and IS
after (+0.262, then +0.222 on current main). So the value was in making
strength claims possible, not in strength itself.

**Caveat on scope.** `mc-prefix` runs on the CURRENT engine, so the engine
changes of 2026-08-05 (canonical `decompose` input, tied-code tractors) are
shared by both arms and cancel. This measures the bot layer only. Its ballot
digest differs (`4d73f8cb` vs `a68f7b8b`), so it is also not a
sampler-only contrast.

## N=30 CONFIRMED over N=10 on the rewritten sampler (2026-08-04, preregistered)

**First strength claim in this project to clear a preregistered confirmation.**

| contrast | result | n |
|---|---|---|
| **N=30 minus N=10 (PRIMARY)** | **+0.262 +/- 0.154, excludes 0** | 504 |
| N=30 minus null control | +0.310 +/- 0.153, excludes 0 | 504 |
| null control minus N=10 | -0.048 +/- 0.162, **includes 0** | 504 |

win rates 55.4% (N=30) / 49.2% (N=10) / 49.1% (null).

Preregistered in `JOBS.md` before launch: one block, 504 clusters, seeds
99,000,000+, disjoint from every earlier block, `--bar "paired_utility > 0"`,
**no extension regardless of result**, screen block NOT pooled. Aggregated
through `scripts/aggregate_shards.py`, which reported no problems — equal
label counts, no duplicate (label, seed, flip), one commit, one schema, zero
zero-world decisions.

**The null control is what makes this different from the six claims that
died.** `mc-null` is `mc` with a different RNG stream — same ballot digest,
same N=10, no differing config attribute. It scored -0.048 +/- 0.162 against
`mc`: the harness produces nothing from nothing. And arm-minus-control excludes
zero, so the effect is attributable to search width rather than to the pipeline.

**Individual shards all read NOT CONFIRMED and that is expected**, not a
caveat being waved away: at n=84 a shard's interval is about +/-0.37, far too
wide. The preregistered unit of analysis was the 504-cluster aggregate,
declared in advance precisely so a shard-level result could not be cherry-picked.

**Why this reverses the afternoon's verdict.** On the OLD sampler the same
comparison gave +0.101 +/- 0.150 and did not confirm. The plausible mechanism
is that the sampler now emits worlds that respect voids, pair caps and tractor
obligations, so additional worlds carry real information; when a fraction of
sampled worlds were impossible, more of them bought less. That is a hypothesis
consistent with the data, not a demonstrated causal claim.

**Caveats, stated rather than buried.**

- It ran on the PRE-FIX `decompose` kernel; the action-semantics fix landed
  after launch. The ambiguity is common-mode across arms so the contrast
  holds, but the absolute policy differs slightly from current `main`.
- N=5 was deliberately excluded. The dose ladder is a separate diagnostic and
  including it re-creates the three-treatment design that voided the last run.
- This is MC-vs-MC search width. **The goal — an RL policy beating MC — is
  still not met.** This is the strongest verified bot, not a learned one.
- `mc-strong` costs 3x the search of `mc`. Latency is not an optimisation
  target here, but this is a deployment decision for Jerry, not an adoption
  that follows automatically from the measurement.

## N=60 vs N=30 — NO CONFIRMED ADVANTAGE (2026-08-05)

Preregistered orthogonal lane on CURRENT main, one fixed block, no extension.

| contrast | result | n |
|---|---|---|
| **N=60 minus N=30 (PRIMARY)** | **-0.002 +/- 0.119, INCLUDES 0** | 504 |
| N=60 minus null | +0.004 +/- 0.129, includes 0 | 504 |
| null minus N=30 | -0.006 +/- 0.134, includes 0 | 504 |

win rates 49.7% / 49.2% / 49.7%.

Seeds 101,000,000+, disjoint from every prior block. Control `mc-strong-null`
is `mc-strong` with a different RNG stream — same ballot digest, same N=30, zero
differing config attributes. Aggregated via `scripts/aggregate_shards.py` with
no problems reported: equal label counts, no duplicate seeds, one commit, one
schema, zero zero-world decisions.

**This is the tightest interval any block has produced today (+/-0.119) and it
is centred on zero.** It fails the preregistered superiority bar and bounds the
primary effect to roughly `[-0.121, +0.117]`; it was not an equivalence test,
so it does not prove zero effect or saturation.

The evaluator also omitted `MCBot.rejected_worlds` from its per-game counters.
The records therefore cannot prove that every nominal N=60/N=30 search
accepted exactly 60/30 worlds. This remains a valid comparison of the two
`f506a7e` policies as actually run, but not an exact accepted-world dose audit.
Future dose claims must record and gate rejected proposals.

**The dose curve, assembled:**

| step | result |
|---|---|
| N=5 -> N=10 | large, -0.347 +/- 0.145 for N=5 (two independent blocks) |
| N=10 -> N=30 | +0.262 +/- 0.154 CONFIRMED (pinned to `e3aeec1`) |
| N=30 -> N=60 | **-0.002 +/- 0.119, no confirmed gain** |

The evidence does not justify more production search dose above N=30 as the
next lever. WHICH actions get priced and HOW worlds are sampled are better
current hypotheses. That is a priority decision from a tight null-centred
interval, not proof that determinization count is exhausted.

Practical consequence: there is no measured reason to promote N>30, and
`mc-strong` at N=30 remains the strongest verified policy — still pinned to
`e3aeec1`, still undeployed, still needing a fresh frozen-current confirmation
before promotion.

## Sampler distribution fidelity — MATERIAL BIAS MEASURED (2026-08-05)

Certification established every emitted world is LEGAL and every legal world is
REACHABLE. Neither speaks to FREQUENCY. The bounded probe Codex asked for
(`scripts/sampler_posterior.py`) measures it against an exact reference on
states small enough to enumerate every legal world.

| state | legal worlds | TV | noise band | **excess** | worst marginal gap |
|---|---|---|---|---|---|
| 880001 | 6 | 0.186 | 0.027 | **0.159** | 0.186 |
| 880002 | 6 | 0.012 | 0.027 | 0.000 | 0.009 |
| 880003 | 48 | 0.318 | 0.059 | **0.259** | 0.066 |
| 880004 | 54 | 0.228 | 0.064 | **0.164** | 0.025 |
| 880005 | 36 | 0.334 | 0.053 | **0.282** | 0.051 |
| 880006 | 14 | 0.406 | 0.035 | **0.371** | 0.119 |
| 880007 | 12 | 0.027 | 0.033 | 0.000 | 0.018 |
| 880008 | 42 | 0.113 | 0.056 | **0.056** | 0.083 |

**Mean TV excess 0.161 over the sampling-noise floor; 6 of 8 states exceed
0.05.** The noise band is the 95th-percentile TV a PERFECT uniform sampler
shows at this draw count, so the excess is the part that is not finite-sample
noise. Without that band a raw TV of 0.2 could not be distinguished from the
floor at all.

**Zero legal worlds were never drawn**, in every state. So this is purely a
proportions failure. Completeness is intact; weighting is not.

**SUPERSEDED 2026-08-05 by a 24-state paired block against a repaired
reference — the attribution above was wrong.** This n=8 table stands as the
historical first measurement; its numbers are against a reference that has
since been shown incorrect, and the sentence that once followed it ("exactly as
the two named biases predict") is withdrawn. Only ONE of the two named biases
contributes:

| cause | paired dTV_excess, physical reference, n=24 | verdict |
|---|---|---|
| `_splits` uniform over count matrices | **-0.060 +/- 0.031** | CONFIRMED contributor |
| `_deal_suit` first-legal preference | **-0.0001 +/- 0.0027** | bounded to nothing |

Baseline excess against the repaired reference is `0.109`, versus `0.116`
against the old flat-over-multisets one — so the wrong reference explained only
~6% of the bias and **a third cause remains unidentified.** Two defects were
also found in the measuring apparatus rather than the sampler: the reference
collapsed physical deals into multisets, and `_fills` counts `AABB, 2/2` as 3
where the physical count is 6.

**Consequence for the pilot.** Codex's condition was "repair first only if that
bounded probe shows material bias". It does. Sharing proposal and report worlds
gives low-variance paired comparisons but does NOT cancel a biased belief
distribution when the bias changes which action is best — and a bias this size
plausibly does. **Pilot scoring should not start on this sampler.**

Reference is uniform over PHYSICAL DEALS consistent with the public record,
because that is what "an uninformative prior over deals" means with a double
deck. The original reference was flat over deduplicated multiset worlds, which
is a different distribution: `AABB` split 2/2 is three multisets but six deals
(weights 1/4/1), so the old reference under-weighted balanced worlds — the same
direction the `_splits` repair pushes. That is why the `-0.060` was re-derived
against the corrected reference before being believed; it got LARGER, not
smaller, so it is not an artifact of the reference's own error.

## Sampler certification status — P0 passed; posterior fidelity open

The first certifier was only an availability screen. The repaired version at
`eea78d2` consumes the original and late raw-state reservoirs, re-derives
constraints independently of `Memory`, checks full deck/kitty conservation,
declaration pins, voids, remaining pair/run obligations and every failed draw,
and records clean-tree provenance. Its final artifact reports:

| claim | result |
|---|---|
| reservoir validity | 1,600 states; 38,399/38,400 worlds produced; 1 rejected draw; **0 invalid** |
| exhaustive toy support | **120/120** states reached every enumerated legal world; 0 worlds missed |
| planted witness | real deal reached in **120/120** toy states |

That closes the bounded P0 validity/support claim. A reconstruction audit also
confirmed that all 1,600 accepted rows matched their stored banker, trump rank,
and final declaration, although the certifier should still replay stored
declarations directly rather than rely on today's bots reproducing them.

It does **not** close distribution fidelity. Two biases are identified
analytically and unmeasured: count matrices are sampled without weighting by
how many concrete card assignments they admit, and the pair-cap card draw
greedily prefers distinct codes. Shared bias may partially cancel in paired
arms, but a wider structured ballot can interact with it, so robustness is an
experiment—not an assumption. P1 is exact toy-posterior/marginal calibration,
then a weighted per-card-code DP or equivalent uniform constrained sampler.

## World sampler rewrite — P0 certified, distribution calibration open

The sampler was a greedy first-fit: shuffle the unseen pool, give each card to
a random seat that still has room. That dead-ends on states where a legal world
plainly exists — place two off-suit cards early and the only seat that can take
the next suit is already full. **Fourteen of those dead-ends landed inside the
determinization confirmation blocks**, each forcing `PROTOCOL FAILURES` and
invalidating the run it appeared in. It also never consumed `pair_cap`, which
Codex raised four times.

**Counts before cards.** There are at most five effective suits and four
receivers (three seats plus the kitty), so the count matrix is tiny and can be
searched exactly: most-constrained suit first, complete lazy enumeration of
splits in random order, forward checking on remaining capacity. If any legal
assignment exists this finds one. Cards are distributed inside a suit only
afterwards, where pair caps apply.

**`pair_cap` replaces `pair_void`.** The first rewrite got the rule wrong and a
real rule-derived regression corrected it: if a follower shows fewer pairs
than were led, `validate_follow` proves they played every pair they held. The
remaining cap is therefore **zero after both a pair and a tractor lead**.
`pair_void` survives as the derived `cap == 0` view.

| measure, 300 rounds / ~18.2k searches | before | after |
|---|---|---|
| zero-world decisions | 14 in the confirmation blocks | **0** |
| worlds rejected under REQUIRE_VOIDS | 5 | **0** |
| worlds violating a proven void | — | **0** |
| wall clock | 234s | 235s |

Two bugs of my own along the way, both caught by tests rather than review: the
first rewrite indexed into a shared list while also writing slices back into
it, which dealt a **third copy of a two-copy card** — fixed by taking cards by
REMOVAL so conservation is structural; and `_take` collided with
`HeuristicBot._take`, silently breaking follow generation from a subclass.

The ~18.2k-search screen pinned useful allocator invariants but was not a
certificate. Its independent successor first found another real bug—an already
pinned declared card could combine with a sampled copy into a forbidden pair—
then was repaired to check the full P0 contract. The clean `eea78d2` artifact
closes reservoir validity and exhaustive-toy support. Distribution fidelity is
still a separate question and no old non-strict label is upgraded by this
result.

**This changes `mc`'s play.** Golden histories were regenerated deliberately.
Prod runs `mc`, so this is a behaviour change awaiting a strength check and
Jerry's go — it is a CORRECTNESS fix and is not claimed to be a strength gain.

## Static ballot coverage audit — dev split, REFRESHED 2026-08-05

**Refreshed after the tied-code tractor fix, and the headline did NOT move:
51.2% leads / 0.9% follows, unchanged.**

I told Codex the 51.2% was an undercount because the diagnostic reference
shared the tied-tractor omission. That was wrong in a way worth recording: the
omission lived in `find_tractor_runs`, which is called by BOTH the deployed
ballot (`MCBot._candidates`, 2 sites) and the reference generator
(`rl.actions.enumerate_actions:70`). Fixing it added the same actions to both
sides, so the omission FRACTION is legitimately unchanged.

The fix did propagate — offered tractor candidates rose 1,701 -> 1,736, offered
pairs 14,037 -> 14,033, omitted pairs 19 -> 23 — it simply moved numerator and
denominator together. The baseline is now honest and the lead pilot is
unblocked on this prerequisite.

## Static ballot coverage audit — dev split, 2026-08-04

**CORRECTED 17:45** after a Codex audit: the structured-action filter was wrong
and the headline number moved from 54.0% to 51.2%.

12,340 dev-split states rebuilt by replay, **0 rebuild errors**. That number is
itself a result: the corpus is a sound state reservoir, so replaying it reuses
20,845 states without re-running 37M evaluations.

Fraction of the *structured* action space (singles, pairs, true tractors) the
deployed ballot never offers:

| surface | omitted |
|---|---|
| leads | **51.2%** (n=3,960) |
| follows | **0.9%** (n=8,380) |

**What was wrong.** `structured()` accepted any multi-card action whose card
multiplicities were all two — which also accepts two UNRELATED pairs thrown
together. That is a throw, not a tractor. It now asks the engine: an action is
structured iff it decomposes into exactly one component. Leads move 54.0% ->
51.2%, follows 0.9% (Codex independently computed 51.18% and 0.883%; both
reproduce).

Two other overstatements from the first write-up, both corrected in the script:

- "fraction of the legal space" was too strong. `enumerate_actions()` caps
  exhaustive follows at 64, skips large fill products, and bounds lead throws
  to 2-3 components. It is a DIAGNOSTIC reference, not the legal universe.
- the per-ply table used the throw-dominated all-actions counter, so its
  83-91% figures said nothing about structured sourcing. On the structured
  counter, omission **declines** with ply: 44.8% at ply 0-4, ~33-35% through
  ply 19, 25.8% by ply 25+. Late-ply sourcing is not the gap.

**Follows are effectively solved: 0.9%.** Pairs are covered almost everywhere
(19 omitted against 14,037 offered), and zero tractors are missed. Every
remaining structural gap is lead SINGLES — 45,191 of them, because the ballot
offers only the top card and the lowest non-point card per suit.

**The caution this raises.** That singles gap is exactly what the V3 arm added,
and V3 did NOT confirm online (+0.065 +/- 0.144, with its random-fill control
scoring higher). So coverage is measured AND known not to be the binding
constraint. A Phase 1 quota arm must justify itself by SELECTION quality inside
a fixed budget, not by how much of the space it recovers.

Audit outputs now carry git SHA, tree-dirty state, and digests of the script,
corpus, split and ballot.

## Determinization dose — mixed evidence, no verified N=30 edge

On the old sampler, the two fresh confirmation blocks gave N=30 minus N=10
`+0.101 +/- 0.150` over 504 seed clusters: not confirmed. Those blocks also
contained 14 zero-world fallbacks, so their N=10-over-N=5 dose contrast is only
provisional. A stale 40-record partial contaminated the first published
selection aggregate; `aggregate_shards.py` now refuses duplicate/unequal
records, mixed commits/schemas, or zero-world fallbacks.

After the sampler rewrite, one new block measured N=10-minus-N=5
`+0.369 +/- 0.221` and N=30-minus-N=10 `+0.290 +/- 0.210`. Its formal verdict
is void because `mc-strong` was incorrectly supplied as the evaluator's null
control, but the measurement reopens the dose hypothesis under changed sampler
behavior. It is one selection block, not a strength claim. N=30 remains
undeployable until a fresh preregistered confirmation with an actual null
control clears.

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

## Root-prior racing — closed

The seeded selection pool put the random-prune control at or above the v11pair
prior, and the paired confirmation agreed: the learned prior added nothing
detectable. Pool gaps were all within the project's unresolved band, so their
Elo ordering is not retained here as a policy ranking. Exact screen artifacts
and chronology belong in `RL_PLAN.md` and `docs_archive/`.

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


## What the high-N corpus actually taught us (2026-08-04 14:40)

Measured across all 20,845 states, not selected ones.

**Leads are the strongest next target, but this corpus does not prove their
headroom.** Splitting the provisional same-world metric by role:

| role | mean selected-max gap from the heuristic pick | unadjusted gap > 2 paired SE |
|---|---|---|
| **leads** | **2.959 points** | **49%** |
| follows | 1.006 points | 16% |

This is directional, not “half of leads are provably improvable.” The best
candidate was selected and tested on the same 240 worlds without a
multiple-comparison correction. Leads also average **11.08 candidates** versus
**6.14** for follows, and the unadjusted significant rate rises from 9.7% at
two candidates to 54.5% at fourteen. That winner's-curse confound inflates the
lead/follow contrast. Leads still show larger gaps within matched candidate
counts, so they remain a good hypothesis; only disjoint report worlds can
quantify the effect.

**This converges with the sourcing audit from a completely different
direction.** That audit found the deployed ballot misses **15.5% of human
LEADS** and only **2.0% of follows**. The two diagnostics therefore agree on
where to investigate first: leads. They do not establish that lead changes
will be worth three times as much online.

**The provisional metric is roughly flat across the round:**

| ply band | forfeit | significant |
|---|---|---|
| 0-3 | 1.497 | 25% |
| 4-7 | 1.593 | 26% |
| 8-11 | 1.749 | 28% |
| 12-15 | 1.806 | 29% |
| 16+ | 1.718 | 27% |

The late-ply corpus is still needed to match the leaf deployment distribution.
These selected-max figures show no obvious rising late-game trend, but they
cannot establish that a correctly sampled late-ply set will reveal no new
opportunity.

**What the corpus did NOT deliver.** No strength gain has come from it. v13
learned its labels 34% better (RMSE 0.1052 -> 0.0699) and played
indistinguishably (v13 minus v7 = -0.028 ± 0.185). Offline regret computed on
it has failed to predict online strength three times. Its headline "~2.8 points
of headroom" is a selected, non-strict, early-state figure — a hypothesis, not
a measured ceiling.

The honest summary: 37.1M candidate evaluations bought one robust negative
(better label fit did not transfer in the mismatched v13 deployment), one
useful directional target (leads), and a clear statement of the corpus's own
limits. The lead effect size remains unmeasured.

## Threshold hypothesis (margin 0.005) — NOT CONFIRMED (2026-08-04 14:15)

The offline split preferred 0.005 over deployed 0.02, but their direct online
paired contrast was **−0.032 ± 0.184 over 250 clusters**: indistinguishable and
nominally in the wrong direction. Together with the margin-0 and v13 results,
offline regret on the old high-N corpus has failed to predict online strength
three times. It may reject an obviously bad arm; it may not promote one.

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

The current artifact is `rl_data/human_v5`: **2,061 decisions from 77 rounds**,
with current v2 ballots. Older v1-v4 statistics are historical and live in the
archive; do not mix their denominators into current claims.

Human agreement is a style/regression tripwire, not a strength metric—the
policy ordering has previously inverted the Elo ordering. Its durable uses are
detecting catastrophic policy collapse, checking distribution shift, measuring
whether a ballot can express human actions, and mining outcome-weighted
disagreements. The current sourcing result is recorded above: deployed MC
misses 15.5% of human leads and 2.0% of follows, which supports investigating
lead selection but does not promote a policy.


## Scoring contract: the engine is uncapped BY RULE (2026-08-05, Codex ruling)

`Game.finish_round()` awards `(points-80)//40` levels with no cap, and
`README.md` states that as the house rule. `bc_generate.round_value()`'s `+3`
ceiling is an **RL TARGET CLIP**, not a game rule, so the two are not in
conflict — they are different objects. Do NOT cap the engine to match the
reward: that would change gameplay. Old labels stay valid under the named
clipped objective; if training must ever match game levels, add a NEW reward
version rather than relabelling history.

Separately, `ai.env.play_game`'s max-round cutoff awards team 0 on a tie. The
registered evaluator never reaches it (`evaluation.run_arm` uses one
`play_round`), and that legacy full-game path stays OUT of evidence until the
cutoff returns an explicit tie or refusal.
