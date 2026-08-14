# Point-management census and representation proposal

Date: 2026-08-13 (methodology repaired same day per Codex review on PR #95).
Author: Claude (independent reviewer). Status: proposal only — nothing here
authorizes a screen, adoption, deployment, or strength claim. Ledger:
`6e0cb8b`, `ae4771f9` (original exploration), Codex methodology HOLD on
`0b20dfe3` accepted in full and repaired here.

## Question

Is S4 point banking too narrow, and where are the larger point-management
opportunities?

## Inputs, pinned

All measurements bind to the frozen ordered manifest
`server/scripts/point_census/manifest.json`, external and internal SHA-256
`8d6cc27f20f8b8953447b8c4f89ba81cccf1bf53bc66521438633a747106aeeb`
(46 files, 165 rounds, 10,631 play events; per-file content SHAs; exact
allowed-use metadata). The underlying human logs are private and deliberately
not committed. A fresh checkout can reproduce the synthetic test battery and
authenticate a separately supplied corpus against the manifest, but cannot
reproduce the human-data numbers without access to those private bytes. The
manifest is the complete cryptographic population boundary, not a claim that
the corpus is public.

Every script requires the independently supplied manifest-file SHA, closes
the manifest schema and population, strictly parses duplicate/nonfinite-free
JSON from one stable byte snapshot, iterates in manifest order, and derives
per-decision seeds from stable decision identity. It emits one canonical JSON
document on stdout with clean Git, load-bearing source/build hashes, runtime
flags, Python identity, and actual native-module path/hash. The 23-test
fixture battery runs every headline route and covers linked/mutated inputs,
rollout legality, complete objective-arm binding, determinism, and
no-implicit-writes in both pure and compiled modes
(`server/tests/test_point_census.py`).

## How points are represented today

- Engine/search: a point is only a terminal tally. `Round.attacker_points`
  accumulates per trick; the kitty bonus lands at round end; `MCBot._rollout`
  returns that single float per determinized world. `LEVEL_OBJECTIVE`
  (bracket-aware value) exists and is off. `MARGIN = 5.0` tethers the ballot
  to the heuristic pick inside a ±5-point band.
- Unseen points enter only through world sampling (`Memory.unseen`, void
  constraints). Each world is played by memoryless `HeuristicBot`;
  `MCSmartRoll` (memory-aware rollouts) exists at ~5x cost, unused.
- `Memory.points_left()`, `Memory.is_boss()`, `Memory.ruff_risk()` — the
  public-info counting primitives — are consumed by almost nothing in
  production (`POINTS_DRY` is off; the feed gate uses literal rank only).
- RL encoder v1: card planes + `attacker_points/200` + per-action point sum.
  No points-left, per-suit availability, trick-points, or bracket-distance
  features.

## Measurements (repaired pipeline; all reproducible from the scripts)

**E1 — census vs SmartBot** (3,539 human decisions, 60.1% exact agreement,
0 replay refusals). Largest point-relevant disagreement classes (phase-split
in the output): FEED-EARLIER — human feeds a partner-winning trick before
last seat, with a legal point-bearing follow available, where the bot's
strong-or-last gate refuses (112 across phases); LEAD point-card splits in
both directions (149 total); CONTEST of low-point tricks the bot surrenders
(65 mid-game); human DECLINES of winnable low-value endgame tricks the bot
takes (33 end-phase). S4's bank-at-last class remains under 1% of decisions.

**P1 — the boss-class table (the mechanism evidence).** Every mid-trick
partner-winning opportunity with a legal point-bearing follow, classified
with public info only (`Memory.is_boss`/`pair_is_boss`, ruff risk over the
seats still to act):

| class | human fed/n (rate) | rollout fed/n (rate) |
|---|---|---|
| literal (trump or top rank) | 164/204 (80%) | 14,664/14,666 (~100%) |
| inferred_strict (counted boss, no ruff risk) | 32/46 (70%) | 302/989 (31%) |
| inferred_loose (counted boss, ruff risk) | 10/17 (59%) | 669/1,956 (34%) |
| open (not provably boss) | 51/77 (66%) | 1,744/10,231 (17%) |
| complex (multi-component) | 47/51 (92%) | 829/1,787 (46%) |

The earlier 70%-vs-23% headline was invalid: the rollout denominator counted
states merely containing a point card even when follow-suit/shape obligations
made every point-bearing action illegal. With the exact engine ballot on both
human and rollout states, literal-strength rollouts feed almost always, while
the inferred-strict row remains directionally different (31% rollout versus
70% human). The open row still mixes human speculation and selection effects;
none of these observational gaps selects a consumer. Rollout sample: 12
manifest-keyed states and 29,629 exactly legal classified opportunities inside
their MC worlds.

**E5 — observational feed outcomes with legality filter.** Opportunities
require at least one legal point-bearing follow. FED n=304: partner held
82% (Wilson 95% [0.77, 0.86]); actor-contributed points 3,395; trick totals
4,795 kept / 910 lost (totals include points from other seats). HELD n=91
(the legality filter removes most of the originally reported 248): partner
held 84% [0.75, 0.90]. Observational only — no causal per-feed benefit is
claimed; the earlier "+12.8 points per feed" framing is withdrawn.

**E2/E3 — production search and objective, same-worlds verified.** Same-seed
twins bind exact pre/post RNG, the full ordered sampled-world commitments,
sampler before/after/delta, candidates and allocation, per-candidate and report
work, and all search/endgame counters. Any mismatch terminates nonzero rather
than being counted and skipped. Binding verified 150/150. Production
`mc-s0-report-lcb` recovers the human action in 17/40 FEED-EARLIER states
(control: 23/30), and `LEVEL_OBJECTIVE=True` flips 20/150 decisions (~13%):
6/40 feed-earlier, 7/40 endgame declines, 5/40 generic endgame, and 2/30
control. Only 3/20 flips move to the observed human action.

**P2 — endgame declines are not POINTS_DRY.** At the 41 human
decline-a-winnable-low-trick endgame states, `points_left()` was 0 in only
3 (median 15). Humans reserve winners against the remaining point mass —
reserve pricing, not a zero-check.

## Proposal: representation before rules

1. **`PointContext` primitive** (highest leverage): one struct per decision
   from public info — `trick_points`, `points_left` (total/per-suit),
   `bracket_distance`, and `effective_boss(cards, seats_still_to_act)`
   defined through exact engine combination/lead-obligation semantics.
   Consumers: the rollout feed gate (P1: change the boss predicate, not the
   feed rate), endgame reserve pricing (P2), lead policy, encoders,
   telemetry. Incrementally maintainable inside rollouts under the
   `_trusted_rollout` contract (PR #90 pattern) with an append-only
   version/fingerprint; provably inert when gated off (deepcopy,
   failed-throw actual cards, altered Ordering, and mutated-live-state paths
   must not reuse stale context).
2. **Rollout point-flow attribution**: per-world counters of point transfers
   (fed / contested / discarded / kitty), S4-telemetry style. Zero decision
   change; makes every point mechanism screenable with matched-null
   discipline.
3. **Bracket-aware value**: screen `LEVEL_OBJECTIVE` behind 1–2 (flip rate
   ~13% on verified same worlds; concentrated in feed/endgame classes).
4. **Affordable memory-aware rollouts**: incremental Memory maintenance to
   collapse MCSmartRoll's 5x multiplier (perf track, successor to
   PR #90/#92).
5. **Encoder v2 point features**: points_left, trick_points,
   bracket_distance, feed-security bit — bundle with the next planned
   ENC_VERSION bump.
6. **Exact endgame widening**: screen 5–6 cards for the point-perfect
   solver.

Sequencing per Codex guidance: land 1+2 (context + zero-effect attribution)
first as a separately screenable representation; then freeze an
independently reviewed feed-consumer design; LEVEL_OBJECTIVE, encoder, and
endgame changes stay out of that first estimand.

## Caveats

Human data is private, hypothesis-generation scale (7 players, 23 games,
mixed skill, selection effects; observational throughout). The corrected
table supersedes every earlier P1 percentage. Every direction above must pass
the normal design → review → one-shot screen → confirmation pipeline before
any adoption.
