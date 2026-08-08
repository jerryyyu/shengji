# AI policy ledger

This is the authoritative synthesized ledger for callable bot policies,
policy-affecting behavior, and conclusions that survived the measurement
rules. It is deliberately **not** a notebook or live conversation.

- Active priorities and gates: `BACKLOG.md`
- Running and completed compute: `JOBS.md`
- Reviewer/Claude discussion: `HANDOFF_REVIEW.md`
- Model chronology and post-mortems: `RL_PLAN.md`
- Superseded detail: `docs_archive/`

**Structure.** Current conclusions come first, followed by callable policy and
flag definitions. The final evidence map points to archived chronology. Do not
append run logs here: update the synthesis when evidence changes a conclusion,
and put exact run detail in `JOBS.md` or the dated archive.

## Current synthesis — 2026-08-08 07:38 EDT

### Production search

- **Live policy:** compiled `mc-s0-report-lcb` at Fly version 17 from exact
  image `latency-cd6789e`, digest `047bcfe4...5b300`; health reports
  `{"bot":"mc-s0-report-lcb","fast":true}`. It runs ordinary N=30 selection,
  then compares the fixed challenger/incumbent pair on 300 disjoint worlds and
  overrides only when the one-sided paired Student-t LCB is positive.
  `mc-strong` is the immediate rollback.
- **Operational boundary:** release 17 preserves N=30/R=300, the ballot, RNG
  advance and LCB decision semantics while moving isolated search off the event
  loop and overlapping the 0.7s pacing floor. A live claim/resume completed in
  20/17ms and caused the expected stale-search discard. During a real X-ray
  search, 25 WebSocket probes stayed responsive at p50 12ms/max 19ms. The
  first 42 ship-gate bot timings had search p50/p95/max
  1.136/1.857/3.104s and turn p50/p95/max 1.138/1.858/3.106s.
  The first ordinary post-fix room then completed five human-versus-three-bot
  rounds: 195 search-like turns (`compute_seconds >= 0.05`) measured
  0.896/1.714/1.906s and their full turns 0.904/1.716/1.907s at p50/p95/max.
  All 249 bot turns were offloaded and
  snapshot-isolated. This confirms the intended one-room product effect; it
  does not yet close concurrent multi-room tail performance.
- **Evidence:** S0a measured `+0.353 +/- 0.069` versus `mc-strong`; S0b
  independently replicated `+0.357 +/- 0.066`. Fresh RLCB-C1 then formally
  confirmed the same policy on 2,048 new paired clusters at
  `+0.338 +/- 0.068`; its collision-free current-policy null was
  `-0.019 +/- 0.068`. All exact-dose, finite-statistic, stream-independence and
  predeclared superiority criteria passed. Aggregate SHA-256:
  `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
  Equal-work uniform search did not explain the earlier gain. Adaptive
  allocation added only `+0.037 +/- 0.060` versus uniform report-LCB, so its
  extra complexity is not justified yet.
- **Formal boundary:** report-LCB is now a formally confirmed one-round search
  improvement over `mc-strong`; RLCB-C1 authorizes that claim only. It does
  not retroactively repair or promote S0, prove adaptive allocation, establish
  multi-round progression, or itself authorize deployment. S0 remains
  terminal `S0_COMPLETE_SELECT_NONE`; its numerical S0c result is unread and
  nonretryable under closeout SHA `ef0a365…fde9a` and parent `ca556c2`.
- **Search width:** N=30 over N=10 reproduced on current code
  (`+0.222 +/- 0.140`); N=60 over N=30 was
  `-0.002 +/- 0.119`. More uniform width is not the next lever.

### Correctness, sampler and data

- The count-first sampler consumes declarations, voids, remaining pairs and
  tractor-run caps. Package H passed bounded hard validity/support on original,
  late and deep reservoirs under compiled strict execution. This does **not**
  prove posterior calibration or a globally complete constructive dealer.
- Physical-deal posterior bias is material. Weighted count splits reduced but
  did not remove it and were too slow; all posterior-changing sampler flags
  remain off. Strict evaluation must report accepted/rejected/failed worlds and
  refuse short or zero-world searches.
- The six-arm DEV-512 lead-ballot screen selected none. At equal work the
  shipped ballot had the lowest regret; brute-force widening lost to more search
  on the incumbent ballot. CALIB/REPORT remain sealed. This rejects only the
  registered designs at that resolution.
- The 20,845-state high-N asset and 12,000-state late supplement are state
  reservoirs, not oracles: their labels use old ballots, non-strict sampling,
  raw points and heuristic continuation. Use them to choose fresh challenge
  strata, then relabel under a current named contract.
- Encoder identity includes semantics and transitive source bytes. Post-drift
  banker-private-kitty assets (`highn_enc`, `human_v4/v5/v6`) are
  quarantined; `gen_v4_all`, which trained v11pair, is clean.
- House level progression is uncapped. A `+/-3` range is valid only for a
  versioned legacy RL target, never for engine/evaluation validation.

### Learned policies and RL

- **Best learned milestone:** `rl-override-v11pair` beat SmartBot 57.7% on
  n=480, but has no valid superiority result over MC. Its pairwise head is a
  root action ranker/proposal on its exact ballot, not a scalar leaf.
- The corrected V11 direct-v2 artifact-only repair is terminal. From the
  immutable 2,048-cluster 142M population, v11-current was
  `-0.141 +/- 0.070`, v11-minus-null was `-0.110 +/- 0.070`, and
  null-current was `-0.031 +/- 0.068`. Exact dose and provenance passed, but both efficacy
  criteria failed; `protected_composition_authorized=false`. No game was
  replayed and no missing activation was invented. Frozen v11 remains useful
  only as a proposal/ranking and teacher diagnostic, not a protected anchor.
- v13 fit its offline target better without improving play. Existing value-leaf
  and learned-rollout hybrids did not establish gains; a private observation
  has no generic strategy-independent scalar value in this game.
- Historical DMC2 does not reject AWAC, Suphx or DouZero. Its role target and
  actor/promotion contracts were wrong, and it was not faithful to those
  algorithms. The repaired role-conditioned Direct-Q screen completed and
  produced encouraging paired gameplay (`+0.163 +/- 0.059`), but failed its
  predeclared learning gate: seed 1 and both pooled role-specific held-out MSE
  LCBs failed. Terminal result is SELECT NONE; do not deploy or extend this
  recipe from its attractive gameplay tail.
- **Suphx O0 is terminal SELECT NONE, without rejecting the whole algorithm
  family.** The exact six-arm Mini screen completed 384 updates with real
  midpoint resume and independently verified gate SHA `592a009a…bd407c`.
  Oracle-minus-initial cleared its deal-cluster LCB (`+0.336`, LCB `+0.274`),
  and the fixed ensemble barely cleared oracle-minus-public (`+0.073`, LCB
  `+0.0025`). But per-seed oracle-minus-public means were
  `+0.344/-0.207/+0.082`; seed 1 violated the preregistered all-seeds
  robustness gate. All legal-world, information-boundary, exact-work, finite-
  model, surface-coverage, entropy and same-model-null checks passed. O1 is
  therefore unauthorized. Preserve the positive oracle-learning signal as a
  diagnostic, but do not extend this inspected recipe or tune on its DEV set;
  a successor must freshly test why policies remained nearly uniform and why
  privileged information did not help robustly across seeds.

### Immediate strength queue

1. Monitor release-17 timing in ordinary human rooms; retain release 16 as the
   scheduler/runtime rollback and `mc-strong` as the policy rollback.
   Scheduling hardening is shipped without changing report-LCB's
   N=30/R=300/ballot/LCB semantics.
2. Preserve Teacher-v3 Stage-B's terminal PASS and obtain independent review
   of the mechanics-only audit publication repair. Then run the unchanged
   frozen 64-state champion-continuation audit under its fresh v2 identity;
   use that evidence to choose the next teacher upgrade rather than scaling
   labels.
3. Treat terminal Suphx O0 and Direct-Q as complementary diagnostics: O0 found
   aggregate oracle acquisition but seed instability; Direct-Q found positive
   gameplay but failed held-out learning. Request an independent strategy
   review, then freeze one fresh mechanism-level learner screen rather than
   extending either inspected run.
4. Keep v11pair as a root proposal/ranking feature and teacher diagnostic;
   the protected-anchor lane is closed by direct-v2.
5. O0's SELECT NONE retires this exact recipe and blocks O1. A successor may
   reuse the tested mechanics, but it needs fresh seeds/data and a predeclared
   explanation of how reward credit, feature scaling, update dose or policy
   learning will produce a robust oracle-public separation.
6. Reparent any structured-bury or sampled-exact contender to confirmed live
   report-LCB before spending strength compute.

## Policy status details

- **Deployment-cost candidate:** `rl-override-v11pair` beats SmartBot 57.7%
  (n=480) and runs at p50 0.25ms / p95 0.52ms on the production numpy path.
  Its 51.1% against MC over 4,880 rounds is **SCREEN** evidence only because
  every MC factory in those blocks was OS-seeded. It is plausibly near MC, not
  formally confirmed equal and not superior. The later seeded/current v1 block
  failed strongly but used a drifted banker encoder; preserve that as-run FAIL
  and require a fresh corrected-encoder direct block before changing the model
  conclusion.
- **Production candidate and rollback:** deployed `mc-s0-report-lcb` adds a
  disjoint R=300 report fold to the current N=30 MC policy. `mc-strong` remains
  its evidence parent and immediate rollback. Their count-first sampler
  consumes declaration, void, remaining-pair and remaining-tractor-run
  constraints. Normal mode can still use the final void-relaxing retry, while
  evidence-producing evaluation requires `SHENGJI_REQUIRE_VOIDS=1` and clean
  sampler counters. The current three-reservoir bounded P0 certificate passed;
  posterior fidelity is still open. Old non-strict labels therefore remain
  provisional even though strict policy evaluations can fail closed on their
  own counters. See
  `CORRECTNESS.md` for the certified boundary rather than inferring it from a
  policy result.
- **S0 family:** `mc-s0-report-lcb` was manually deployed on replicated S0a/b
  development evidence and is now independently confirmed by fresh RLCB-C1.
  `mc-s0-report-mean` isolates the report rule; `mc-s0-uniform-work` isolates
  extra compute; `mc-s0-adaptive[-mean]` and `mc-s0-random[-mean]` isolate
  evidence-directed allocation. None of those other S0 arms is deployed.
- **Experimental sampled-exact family, not deployed:** `mc-exact-endgame`,
  `mc-s0-report-lcb-exact-endgame`, and `mc-s0-adaptive-exact-endgame` clone the
  corresponding possible terminal S0 champion and change only
  `EXACT_ENDGAME=True` at the proved <=4-card/250k-node boundary. The named
  champion-matched nulls shift only RNG. They exist solely for the `79985a2`
  score-free-throughput -> 139M screen -> 140M confirmation protocol and have
  no strength or production authorization yet.
- **Retired strength arm:** `mc-vleaf-v7w-ep02` has no verified edge over MC.
  Its historical 50.4% at n=1,200 predated the leaf factory's seed-forwarding
  repair. In the current hardened screen it scored 52.8% and
  `+0.024 +/- 0.215` paired utility versus the MC reference: not confirmed.
- **v13abs is not promotable:** it improved offline `Q^H(s,a)` fit, then tied
  v7 at 52.8%; the direct paired v13-minus-v7 contrast was
  `-0.028 +/- 0.185`. Its training states were much earlier than its deployed
  leaves, and its high-N `MCBot._candidates()` training ballot did not match
  the pinned-v1 `enumerate_actions()` ballot maximized at the leaf. It is also
  encoder-incompatible: training consumed the now-proved contaminated
  `highn_enc` cache. Rebuilding that cache requires retraining and fresh
  evaluation; never reuse the existing v13 checkpoint as corrected evidence.
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

Registered by name in `server/shengji/ai/registry.py`; the source fallback is
`mc`, while production explicitly sets `SHENGJI_BOT=mc-s0-report-lcb`:

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

### `mc` — base MCBot (source fallback, not production)
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
- The compiled path materially reduces full-round simulation cost but does not
  repair belief correctness. The base N=10 policy is retained for controls;
  `mc-strong` N=30 is its verified stronger search-dose descendant.
- Most other hyperparameters were flat: margin 5 was best in its grid,
  candidates 8 was enough, SmartBot rollouts tied at about 5x cost, and
  `LEAD_MARGIN`, `LEVEL_OBJECTIVE` and the old four-choice `MC_BURY` did not
  establish gains.
- vs SmartBot v2: 36-4 (90%) mirrored full games, n=40.
- Exposes `last_eval` (per-candidate values) for search distillation, and
  powers the /debug/xray live inspector.

### `mc-s0-report-lcb` — production

Runs the complete `mc-strong` N=30 ballot and selection, nominates one
challenger, then compares that fixed pair on 300 disjoint common worlds. It
overrides candidate 0 only when a conservative one-sided paired Student-t LCB
is above zero; short folds fail back to candidate 0 and all accepted work is
recorded. S0a measured `+0.353 +/- 0.069` and S0b independently measured
`+0.357 +/- 0.066` versus `mc-strong`. A compiled preflight on the named hard
lead state measured 0.390s median versus 0.127s for `mc-strong`. It was manually
deployed for strength on 2026-08-07, with `mc-strong` as rollback. Formal fresh
RLCB-C1 confirmation is complete: on 2,048 new paired clusters the exact
production rule measured `+0.338379 +/- 0.067706` versus `mc-strong`, while the
collision-free current-policy null was `-0.019043 +/- 0.068270`. This confirms
one-round paired level-utility superiority only; it does not prove multi-round
progression or authorize changes to N, R, ballot, sampler or confidence rule.

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

The standalone checkpoint line is paused as a strength target and retained as
a cheap diagnostic/deployment baseline. The durable learned-policy conclusions
are:

- `v11pair` is useful as an exact-ballot root proposal/ranker; it beat SmartBot
  but has no valid superiority result over MC and cannot be used as a generic
  scalar leaf.
- v13 fit its offline target better without improving play. Offline loss and
  old-surrogate agreement are not promotion metrics.
- Ballot or encoder changes invalidate trained checkpoints even when tensor
  dimensions stay constant. Every consumer must bind semantic identity and
  rerun its direct gate.
- Replacing the rollout policy and the tested value-leaf hybrids did not
  establish gains. Preserve the complete root ballot; corrected direct-v2
  rejected v11 protected anchoring, so learned signals remain bounded
  proposal/ranking or teacher diagnostics until a new contract passes.
- Historical DMC/DMC2 runs exposed action-spread collapse, a role-sign defect
  and incomplete algorithm fidelity; they do not reject AWAC, Suphx or
  DouZero. The repaired Direct-Q screen produced positive gameplay but failed
  its held-out learning gate and selected none; the next learner must use a
  separately frozen recipe rather than extend 144M.

The authoritative model-by-model chronology, including v1-v13, lives in
`RL_PLAN.md`; exact old run narratives live in `server/runs/` and the dated
archive.

## Cross-policy correctness and identity

- **Engine semantics:** tied effective codes preserve physical card identity;
  throws can be ruffed; failed throws force the lowest beatable component;
  pairs are beaten only by higher pairs; level progression is uncapped under
  the house rules. Historical evidence measured before these corrections is
  not directly comparable to current play.
- **Sampler knowledge:** declaration pins, known banker kitty, suit voids,
  remaining pairs and remaining tractor runs are consumed once. Package H
  passed the bounded strict validity/support gate on original, late and deep
  reservoirs. Posterior calibration and global constructive completeness are
  still open.
- **Public memory:** forced follow responses update suit void and pair/run caps;
  search may use only information derivable from public history plus the
  acting player's private hand.
- **Reproducibility:** factory seeds reach every stochastic policy; deck and
  ballot iteration are ordered; caches use canonical keys and return defensive
  copies; strict evaluation refuses short or zero-world searches and records
  sampler counter deltas.
- **Artifact identity:** policy evidence binds source, ballot, sampler,
  continuation, encoder semantics and transitive bytes. The drifted
  banker-private-kitty assets remain quarantined even though their vector
  dimensions match clean assets.

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
| PAIR_VOID_BOSS | off | leads a LOW pair once every opponent has PROVEN pair-void in its suit (forced pair-matching makes a broken answer proof) | 54% first n=200, 48% fresh n=200 → 51.0% at n=400 | tie — small-n mirage caught by extension; `Memory.pair_void` remains a correctness input |

**MCBot** (search-level knobs on top of SmartBot):

| knob | value | what it does | record | verdict |
|---|---|---|---|---|
| MARGIN | 5.0 | SmartBot's pick is the incumbent; the search only overrides it when a candidate wins the rollouts by 5+ points/round — guards against early-round rollout noise | beat argmax 62% (~45 Elo) | adopted |
| N_DETERMINIZATIONS | base 10; strong/prod selection 30 | hidden-hand worlds per candidate | fresh current-main N=30 minus N=10 `+0.222 +/- 0.140`; N=60 minus N=30 `-0.002 +/- 0.119` | N=30 adopted; no width-only case above 30 |
| MAX_CANDIDATES | 8 | how many candidate plays the search evaluates | 4→58%, 12→60% | adopted |
| TRACTOR_LOCK | ON | when the heuristic wants to lead a tractor, that's final — no rollout override | 56% h2h | adopted |
| POINT_SHY_EPS | 2.0 | among near-tied candidates, play the one risking the fewest points (a beaten 10-10 lead gifts 20) | from the 10-10 lead analysis | adopted |
| LEVEL_OBJECTIVE | off | scores rollouts by scoring brackets (the 80/40-point cliffs) instead of raw points | 59% vs 62% ref | tie |
| MC_BURY | off | searches the banker's bury: heuristic pick vs loose/strict/no-void variants over sampled worlds | 62% = ref | tie |
| LEAD_MARGIN | off | a higher override bar for leads specifically | 8/12/999 → 51/47/50% | tie |
| SmartBot rollouts | off | uses the memory-aware bot instead of the fast heuristic to play out sampled worlds | tie at 5x cost; **RE-TESTED 2026-08-03 with SmartBot now 93 Elo above heuristic: 62-58 = 52%, still a tie** | rejected — twice, on cost. Both are FAILED SUPERIORITY tests: a 93-Elo-stronger roller did not win, which does NOT establish that rollout strength is irrelevant. The honest reading is that no continuation has been shown stronger at 5x cost; equivalence was never tested. |
| RISKY_THROWS | off | puts near-boss throws (A+QQ where only one higher pair threatens) on the ballot; worlds price the risk | 53% at MC, n=120 | tie; combined arm unmeasured and not prioritized |
| TRUMP_BALLOT | off | adds trump-pair and top-trump lead candidates (钓主) for the worlds to price | 53% at MC, n=120 | tie; combined arm unmeasured and not prioritized |
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

# Archived evidence map

The former dated working notes were compacted on 2026-08-07. Their exact
pre-compaction bytes remain recoverable at commit `ca556c2`:

```bash
git show ca556c2:AI_POLICIES.md
```

Use `docs_archive/daily-log-2026-08-04.md`,
`docs_archive/daily-log-2026-08-05.md` and
`docs_archive/daily-log-2026-08-06.md` for chronological detail. The current
day is `docs_archive/daily-log-2026-08-07.md`. The synthesis and policy
definitions above are authoritative; this map preserves only the durable
lessons needed to find old evidence.

## Search and decision rules

- N=30 over N=10 reproduced on current code; N=60 did not establish an
  advantage over N=30. Width alone is not the next lever.
- Wide lead and follow ballots fixed real sourcing omissions. The later
  six-arm DEV-512 redesign screen selected none; more brute-force widening was
  not better than spending work on the incumbent ballot.
- The fixed five-point point-estimate margin occasionally admits noisy bad
  overrides. A disjoint R=300 report fold fixed that mechanism, beat
  `mc-strong` in two independent development blocks, and then formally
  confirmed at `+0.338 +/- 0.068` on fresh RLCB-C1 with a sane null. Extra
  work alone did not explain the gain.
- Adaptive allocation was not measurably better than uniform report-LCB
  (`+0.037 +/- 0.060`). Keep the simpler policy unless new evidence isolates
  the increment.
- The S0c numerical outcome is not evidence: the lag-17 dependency repair
  refused before parsing, formal S0 closed SELECT NONE, and the sealed
  population is nonretryable.

## Sampler and correctness

- Package H certifies bounded hard validity/support on original, late and deep
  reservoirs under compiled strict execution. It does not prove posterior
  calibration or global constructive-dealer completeness.
- Physical-deal posterior bias is material. Weighted count splits reduced but
  did not remove excess total variation and were too slow; all experimental
  posterior flags remain off.
- Important fixed defects include banker-kitty double subtraction, greedy
  allocation dead ends, declaration-pin pair completion, pair/run caps,
  zero-world fallbacks, failed-throw component choice, pair boss logic and
  tied-code tractor enumeration.
- Encoder/data identity must bind semantics and transitive source bytes, not
  only vector size or a version integer. Drifted banker-private-kitty assets are
  quarantined; historical v11 training data is clean.

## Learned policies and teachers

- v11pair's pairwise/listwise action objective is the strongest learned
  milestone: it beat SmartBot, but not MC under a valid seeded proof. It is a
  root proposal/ranker on its exact ballot, not a cross-state scalar leaf.
- v13 improved offline fit without improving play. Better imitation of
  `Q^Heuristic` is not automatically a stronger teacher or policy.
- Root-prior hard pruning, learned rollout replacement and existing value-leaf
  hybrids did not establish gains. Corrected direct-v2 also rejected v11
  protected anchoring. Preserve all candidates and use learned signals only as
  proposal/ranking or teacher diagnostics until a fresh mechanism passes.
- Historical DMC2 runs do not reject AWAC, Suphx or DouZero: the role-sign,
  actor immutability and promotion contracts were wrong, and the algorithms
  were not faithful implementations. Repaired Direct-Q completed its bounded
  screen and selected none despite positive gameplay because its independent
  learning diagnostics failed.
- The high-N and late-ply corpora are replayable state reservoirs, not oracles.
  Use them to choose fresh challenge strata; generate new strict
  counterfactual labels under a named ballot, sampler, continuation and utility.

## Evaluation and experiment discipline

- Strength claims require deterministic seeded factories, paired deal clusters,
  explicit nulls, exact work/counters, immutable manifests and a fresh
  confirmation. Elo pools, human agreement and offline regret are screens.
- DEV may select one design; CALIB/REPORT remain sealed if DEV selects none.
  Never append arms after inspecting a split.
- Full-game cutoff now refuses instead of scoring unfinished games. House level
  progression is uncapped; `+/-3` belongs only to a versioned legacy RL
  target.
- Code-gate completion, correctness repairs and more generated rows are not
  strength gains. Compute should buy a stronger decision rule, a stronger
  target, or genuine policy improvement.

## Reproduction pointers

| topic | durable source |
|---|---|
| callable policies and flags | this file + `server/shengji/ai/registry.py` |
| model v1-v13 chronology | `RL_PLAN.md` |
| current execution order | `BACKLOG.md` |
| exact run/artifact status | `JOBS.md` |
| sampler/engine boundary | `CORRECTNESS.md` |
| reviewer decisions and retractions | `HANDOFF_REVIEW.md` |
| full removed working notes | `git show ca556c2:AI_POLICIES.md` |
