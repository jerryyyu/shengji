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

## Current synthesis — 2026-08-09 09:55 EDT

### Canonical terminal-results table

This is the one compact index of decision-changing AI evidence. Detailed
mechanics remain below and exact job chronology remains in `JOBS.md` and the
dated archive. Other documents should link here instead of copying a second
results table.

| date | lane | terminal verdict | headline result | what it means |
|---|---|---|---|---|
| 08-07 | report-LCB / RLCB-C1 | **CONFIRM** | `+0.338 +/- 0.068` signed levels versus `mc-strong`; matched null `-0.019 +/- 0.068` | The deployed one-round decision rule is stronger than its named N=30 parent. It does not prove adaptive allocation or multi-round progression. |
| 08-07 | formal S0 | **SELECT NONE** | S0c outcomes remain unread | The evidence chain failed before the corrected evaluator parsed scores. Never retry, pool or infer a numerical result. This does not undo independent RLCB-C1. |
| 08-05 | DEV-512 lead ballot | **SELECT NONE** | quota-minus-random `+0.110 +/- 0.337`; incumbent had the lowest equal-work regret | The registered widening/selectors did not earn CALIB or a duel. It does not reject all proposal search. |
| 08-07 | V11 direct-v2 | **SELECT NONE** | v11-minus-current `-0.141 +/- 0.070`; v11-minus-null `-0.110 +/- 0.070` | No direct or protected-anchor composition. V11 survives only as a proposal/ranking and teacher diagnostic hypothesis. |
| 08-07 | Direct-Q 144M | **SELECT NONE** | gameplay `+0.163 +/- 0.059`, but seed 1 and both pooled role held-out MSE gates failed | The attractive gameplay tail cannot override the registered learning failure. Redesign rather than extend. |
| 08-08 | Suphx O0 | **SELECT NONE** | oracle-minus-public `+0.073`, LCB `+0.0025`; seed means `+0.344/-0.207/+0.082` | Full information produced an aggregate signal but not robust seedwise benefit. O1 is unauthorized. |
| 08-09 | Suphx O0-v2 | **SELECT NONE** | CRN control oracle-minus-public `+0.015`, LCB `-0.067`; plus-margin `-0.047`, LCB `-0.109`; interaction `-0.062` | Shared-public CRN repaired the comparison mechanics but did not make oracle use robust. Margin sharpening was directionally worse, no cell advanced, and O1 remains unauthorized. |
| 08-08 | Teacher-v3 Stage B / audit-v2 | **STAGE B PASS / AUDIT OPERATIONAL REFUSAL** | cheap-minus-gold regret upper bound `0.0195 < 0.10`; audit shard 6 stopped on an incomplete champion-report continuation and published no labels/gate | Cheap labels agreed on sampled ordinary states. The continuation audit produced no ML verdict and is nonretryable; reviewed score-free diagnostics now gate a fresh versioned synthetic contract. |
| 08-09 | Teacher-v3 fresh champion audit | **PASS / STAGE-C DESIGN** | cheap-choice all-64 regret upper bound `0.0354`; N=30-choice upper bound `0.0439`, both below `0.10`; N=30 boundary-8 diagnostic upper bound `0.1421` | The cheap and N=30 choices are champion-faithful on the frozen 64-state complement. The boundary diagnostic motivates hard-tail escalation. Reviewed adapter `56ccefbd…c2442` now freezes that design-only contract; it authorizes no labels, training or promotion. |
| 08-09 | S3a full-game score-free preflight | **CAPACITY PASS / SCREEN LAUNCHED AFTER REVIEW** | 4/4 clusters in 255.3 seconds; exact structured work; screen projection `72.62` fleet-hours / `9.08` max-shard hours under the frozen 2× factor | Structured bury is non-vacuously wired and the preregistered full-game screen fits Mini. Separate packet review passed and the sealed screen is running; this row itself remains capacity evidence, not strength evidence. |
| 08-08 | S3b v2 throughput | **HOLD / NO SCREEN** | first exact-treatment cluster exceeded the frozen cumulative `250,000`-node cap; no receipt published | The registered four-card sampled-exact recipe is not operationally admissible under its zero-overflow rule. No strength conclusion; no retry or 2,048 screen. |
| 08-08 | S3a v2 sizing | **CAPACITY PASS / NO STRENGTH VERDICT** | frozen projection `0.142` fleet-hours / `0.0178` max-shard hours, exact work and zero failed worlds | This cleared placement for the subsequently reviewed and completed 512-state screen; sizing itself made no strength claim. |
| 08-08 | S3a structured-bury screen | **MECHANISM PASS / AUTHORIZE DUEL DESIGN** | structured-minus-live-incumbent `+0.997 +/- 0.401` (LCB `+0.597`); minus legacy-four `+0.878 +/- 0.380`; minus matched random widening `+3.253 +/- 0.561` | Structured proposal generation improved the frozen state-level bury objective against every preregistered control. This is the first positive S3 mechanism signal, but only a fresh full-game duel can establish bot strength. |

Evidence anchors, in the same order:

- RLCB-C1 aggregate `83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea`.
- Formal S0 closeout `ef0a3659859b38d0b9362376e5e403fecb625f59c475600ed09906ce695fde9a`.
- DEV-512 state asset `af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b`.
- V11 direct-v2 aggregate `b7c90ba4c1a9bb421a4cfcc788dbf1eb44365868f65ee0eb58257b38205d21ad`.
- Direct-Q aggregate `1fa6789eded784e03778f5ede841e45039579625477dbaa249d63c5ccc8ce791`.
- Suphx O0 gate `592a009aaf6fbd6680b6d9bab5e9738832050d1654b71dc6f2e19612d0bd407c`.
- Suphx O0-v2 gate `0dbd9aa8bdefb1980535e52cee7c8bcc0bb28f2759b9c20189db2c341bfff24e`;
  independent semantic replay returned `verified=true`.
- Teacher-v3 Stage-B gate `f607b48986aaa8b05194f88e8638540bc5c9360f09f3c28a7565d8d8cac89694`.
- Teacher-v3 fresh audit gate `8a1532b7b9a610452609bb2a7a69c9b13a9f1800ad74428d0278e9572aba91f8`;
  supervisor final `02f4f8b02d674ad3f59f9fa5b607692c7c8d31bdc5d26e2c64f66c983956f237`;
  terminal adapter `56ccefbd62d9ea2aef30a4c6e54e11a0d2231e464f129e754b84b3488f1c2442`.
- S3a full-game preflight `09692f823d26d38ea76c7c6e36ea007a5031c0f05ca1a76795c84e7d0722edf0`;
  supervisor final `56943242f3620b09774a55eab992fbac0bce6ad224c3ada6a7b54a5634799e9f`;
  reviewed screen packet `de16247bfea13bde516cfb45317f7d21d46d758ae700441b9b747b41f3d5cdd4`;
  admission `567e8aa8bb1107314373f7e5756e4f8646e419a70fa1afed9594ee36edf41c5e`;
  live receipt `2c89bed3e5727b4e116f3efb2fcdc184cc1dc683860be66dd842a5310b6cbb2c`.
- S3b v2 closeout: clean head `cd44ea8a6fefb8fba258d01bcca4bed98169a217`,
  runner SHA `ed4252b2f957e2855446ca63858e7da973949934850684e8f92e5950ca74050d`;
  final and partial receipts absent by fail-closed design.
- S3a v2 sizing receipt `cf7702770e2dd416b0ecfcdcc2ba6a5c32ab262aef0319d87346d05bcdf5c431`.
- S3a screen aggregate `74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd`;
  supervisor final `d3f2b1ab48085ccf37534b5dd7f20ea6cf0d7644c6c49304b644ecf895169a6b`.

### Production search

- **Live policy:** compiled `mc-s0-report-lcb`, Fly release 17, image
  `latency-cd6789e`, digest `047bcfe4...5b300`; `mc-strong` is the
  policy rollback. N=30 nominates a challenger, a disjoint R=300 common-world
  fold rechecks the fixed pair, and only a positive one-sided paired LCB
  overrides the incumbent.
- **Evidence boundary:** S0a/S0b and fresh RLCB-C1 were independently positive;
  the canonical table carries the confirmation. Equal work did not explain the
  gain, adaptive allocation added no resolved increment, and N=60 did not beat
  N=30. Formal S0 remains a separate unread/nonretryable SELECT NONE.
- **Runtime boundary:** release 17 preserves decision semantics while moving an
  isolated snapshot off the event loop, overlapping pacing and discarding stale
  work before commit. Live claim/reconnect/X-ray and ordinary-room timing passed;
  concurrent multi-room tails remain open. See `PERF.md` and `DEPLOY.md`.

### Correctness, sampler and data

- Package H passed bounded hard validity/support on original, late and deep
  reservoirs under compiled strict execution. It does **not** prove posterior
  calibration or a globally complete constructive dealer. Physical-deal bias
  remains material; posterior-changing sampler flags stay off.
- DEV-512 selected none: the shipped ballot had the lowest equal-work regret and
  CALIB/REPORT remain sealed. This rejects its registered designs, not every
  future proposal-search hypothesis.
- S3a now supplies that missing positive proposal-search signal specifically
  for bury decisions: structured widening beat the incumbent, legacy-four and
  trigger-matched random widening on 512 frozen states. Its per-state evidence
  is inspected and non-promotable; the mechanism must move to fresh full-game
  clusters before any policy claim.
- High-N and late assets are replayable state reservoirs, not oracles; their
  labels use old ballots, non-strict sampling, raw points and heuristic
  continuation. Relabel fresh named strata under the current contract.
- The August 9 Fly-snapshot-only human refresh replayed 122 complete rounds and
  accepted 2,830 plays plus 45 buries under the repaired public/no-private-
  kitty encoder. It explicitly rejected seven incomplete rounds, excluded 12
  legacy local-only rooms, found 25 human plays outside the broad exhaustive-
  follow analysis ballot, and found points in 22/45 human buries. This is
  proposal/coverage evidence, not proof that human actions or round-return
  labels are stronger. Use player/deal-disjoint splits and counterfactual
  relabeling before training beyond a separately measured BC control. Clean
  producer is `b52dc33`; corpus manifest SHA-256 is `b9699790…16553`.
- Encoder identity includes semantics and transitive bytes. Drifted banker-
  private-kitty assets remain quarantined; `gen_v4_all`, which trained
  v11pair, is clean. House progression is uncapped; `+/-3` is only a named
  legacy RL target.

### Human-observed policy surfaces

- **Kitty:** production is strongly point-shy rather than incapable of
  burying points. S3a explicitly constructs point/void/trump alternatives; its
  state mechanism passed and its sealed full-game screen is the active strength
  test.
- **Point banking:** root MC can source a point-bearing winner, but shared
  heuristic continuation selects the cheapest winner when a cheaper non-point
  winner also exists. The proposed S4 treatment changes continuation only and
  must include team-aware positive/negative witnesses plus a trigger-matched
  null. It is not yet a strength result.
- **People-facing target:** human agreement is a style/coverage diagnostic.
  After bot-vs-bot confirmation, a blinded opt-in `HUMAN-C1` must compare the
  candidate with the live champion across the same human cohort, balanced by
  team/banker/seat and clustered by player session. Evaluation games never
  enter training or selection.

### Learned policies and RL

- V11pair's confirmed 57.7% result over SmartBot shows within-ballot ranking
  signal, but direct-v2 selected none against current search and rejected
  protected composition. Use it only as a bounded proposal/ranking and teacher
  diagnostic, never a scalar leaf.
- v13 fit its offline target better without improving play; existing value-leaf
  and learned-rollout hybrids have no verified gain. A private observation has
  no strategy-independent scalar value without a named belief/continuation.
- Direct-Q's positive gameplay tail failed held-out role learning. Suphx O0's
  aggregate oracle-public signal failed seed robustness and stayed nearly
  uniform. O0-v2 then completed the fresh eight-seed shared-public CRN
  mechanism battery: coupling and semantic replay passed, but the control
  cell's oracle-minus-public LCB was `-0.067` and margin sharpening moved the
  mean down by `0.062`. All select none. The next learner needs a new target,
  credit/data or adaptation mechanism—not O1 or another estimator-only repair.
- Historical DMC2 had role-target, actor and promotion defects and was not a
  faithful AWAC/Suphx/DouZero implementation. Preserve its alarms, not its
  algorithmic verdict.

### Execution ownership

This ledger intentionally carries no live queue. Current order, blockers,
machine assignment and milestone gates live only in `BACKLOG.md`. The durable
conclusion is that new S3 mechanisms must bind exact report-LCB, Teacher scale
waits on its champion/hard-tail gates, V11 is proposal/diagnostic only, and a
fresh learner must change the target, data/credit assignment or adaptation
mechanism under the now-proven CRN/replay evaluation boundary.

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

## Durable decision rules

- **Name the reference.** “Current” and “champion” are not identities.
  Strength work freezes the exact live policy and a matched null; today that is
  `mc-s0-report-lcb`, not formal S0's `mc-strong`.
- **Guarded paired reevaluation is the proven search mechanism.** Ordinary
  N=30 nominates; a disjoint R=300 common-world report fold overrides only on a
  positive conservative LCB. More uniform width and adaptive allocation have
  not shown an additional gain.
- **Screens reject/select designs; confirmations establish strength.** Elo,
  human agreement, offline regret and small blocks may prioritize work, but
  promotion requires deterministic factories, paired deal clusters, an
  explicit null, exact work/counters, immutable manifests and fresh evidence.
- **Correct data is a named estimand.** Ballot, sampler, continuation, role,
  perspective, utility, encoder semantics and transitive bytes are part of a
  target. High-N/late assets are replayable reservoirs, not generic oracles;
  drifted banker-private-kitty encodings remain quarantined.
- **A legal sampler is not automatically calibrated.** Package H proves bounded
  strict validity/support on its registered reservoirs. Posterior fidelity and
  global constructive completeness remain separate questions.
- **Learned models need an identifiable role.** Pairwise V11 scores may
  propose/rank within a ballot but are not scalar leaves. Better offline fit
  did not imply better play. Direct-Q and O0 failures require a fresh,
  mechanism-isolating learner experiment, not more compute on inspected runs.
- **Correctness and throughput are gates, not strength.** A fixed engine bug,
  green code gate, faster simulator or larger corpus enables an experiment; it
  does not count as an AI win.
- **House progression is uncapped.** A clipped `+/-3` value is legal only as
  an explicitly versioned legacy RL target, never as an engine/evaluator
  validator.

## Archive boundary

The former dated working notes are recoverable at
`git show ca556c2:AI_POLICIES.md`. Day-by-day evidence lives in
`docs_archive/daily-log-2026-08-04.md` through the current daily log.
`RL_PLAN.md` owns model lineage and design rationale; this file keeps only
callable policy/toggle contracts, canonical terminal results and conclusions
that still govern decisions.

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
