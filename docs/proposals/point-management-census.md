# Point-management census and representation proposal

Date: 2026-08-13. Author: Claude (independent reviewer). Status: proposal
only — nothing here authorizes a screen, adoption, deployment, or strength
claim. Ledger entries: exploration at `6e0cb8b`, addendum at `ae4771f9`.

## Question

Is S4 point banking too narrow, and where are the larger point-management
opportunities? Measured against the 46 human game logs in `logs/*.jsonl`
(the `human_v8` sources: 23 games, 7 players; manifest `allowed_use` includes
teacher-disagreement-mining and counterfactual-pilot design).

## How points are represented today

- Engine/search: a point is only a terminal tally. `Round.attacker_points`
  accumulates per trick; the kitty bonus lands at round end; `MCBot._rollout`
  returns that single float per determinized world. `LEVEL_OBJECTIVE`
  (bracket-aware value) exists and is off. `MARGIN = 5.0` tethers the ballot
  to the heuristic pick inside a ±5-point band.
- Unseen points enter only through world sampling (`Memory.unseen`, void
  constraints). Each world is played by memoryless `HeuristicBot`;
  `MCSmartRoll` (memory-aware rollouts) exists at ~5x cost, unused.
- `Memory.points_left()` — the one aggregated availability signal — is
  consumed by nothing in production (`POINTS_DRY` is off).
- RL encoder v1: card planes + `attacker_points/200` + per-action point sum.
  No points-left, per-suit availability, trick-points, or bracket-distance
  features.

## Measurements (scripts in `server/scripts/point_census/`)

**E1 — census vs SmartBot** (3,539 decisions, 60.1% exact agreement).
Largest point-relevant disagreement classes: FEED-EARLIER — human feeds a
partner-winning trick before last seat where the strong-or-last gate refuses
(136); LEAD point-card splits in both directions (112 bot-leads vs 78
human-leads; context-dependent); CONTEST of low-point tricks the bot
surrenders (82, mid-game); human DECLINES of winnable empty endgame tricks
the bot takes (46, end-heavy); S4's bank-at-last class appears 25 times =
0.7% of decisions.

**E2 — production `mc-s0-report-lcb` on those classes** (seed-pinned, 40
states/class): FEED-EARLIER recovered 8/40; LEAD 3/40; CONTEST-LOW 3/40 with
19/40 third-action overrides; BANK-AT-LAST 1/25. Only DECLINE-END is
half-recovered (16/40). Control: MC matches the human 19/30 on random
decisions — the failures are class-specific.

**E3 — LEVEL_OBJECTIVE flips** (same seed, same worlds): ~9% of contested
decisions flip, concentrated in FEED-EARLIER (9/40, 4 toward the human);
0/40 flips on generic endgame states. Real but modest at per-decision level.

**E5 — ground truth from the games**: mid-trick partner-winning decisions
with point cards in hand: FED n=304 → partner held 82% (4,795 pts kept vs
910 lost ≈ +12.8 pts realized per feed); HELD n=248 → partner held 79%.
Near-identical hold rates: the risk was structural, not selective; the
literal strong-or-last gate is far more conservative than the empirical
hold rate justifies.

**P1 — rollout feed-rate**: inside production MC worlds (25,464
partner-winning mid-trick opportunities), HeuristicBot rollouts feed 53.4% —
indistinguishable from the human 55% aggregate. The FEED gap is
distributional, not volumetric: the gate feeds on LITERAL strength (trump
ruffs, top ranks — common in rollouts); the unrecovered human feeds sit at
INFERRED-boss states (counted-out honors, known voids).

**P2 — POINTS_DRY mis-targets DECLINE-END**: at the 41 endgame decline
states, `points_left()` was 0 in only 3 (median 15). Humans reserve winners
against the remaining point mass — reserve pricing, not a zero-check.

## Proposal: representation before rules

1. **`PointContext` primitive** (highest leverage): one struct per decision
   from public info — `trick_points`, `points_left` (total/per-suit),
   `bracket_distance`, and `effective_boss(cards, seats_still_to_act)` from
   `Memory.unseen` + void inference. Consumers: the rollout feed gate (the
   P1-refined fix: change the boss predicate, not the feed rate), endgame
   reserve pricing (the P2-refined fix), lead policy, encoders, telemetry.
   Maintainable incrementally inside rollouts under the `_trusted_rollout`
   contract (PR #90 pattern), provably inert when gated off.
2. **Rollout point-flow attribution**: per-world counters of point transfers
   (fed / contested / discarded / kitty), S4-telemetry style. Zero decision
   change; makes every point mechanism screenable with matched-null
   discipline.
3. **Bracket-aware value**: screen `LEVEL_OBJECTIVE` behind 1–2; pairs with
   `bracket_distance`.
4. **Affordable memory-aware rollouts**: incremental Memory maintenance
   inside worlds to collapse MCSmartRoll's 5x multiplier (perf track,
   successor to PR #90/#92).
5. **Encoder v2 point features**: points_left, trick_points,
   bracket_distance, feed-security bit — bundle with the next planned
   ENC_VERSION bump (bumps invalidate datasets/checkpoints by contract).
6. **Exact endgame widening**: the disabled `EXACT_ENDGAME` solver is
   point-perfect on <=4-card endings; screen 5–6 cards.

Suggested sequence: build 1+2 together (small, public-info only, bit-identical
off), screen the feed-gate consumer first (strongest human-data support),
LEVEL_OBJECTIVE screen behind it, track 4 in parallel on the perf lane.

## Caveats

Human data is hypothesis-generation scale (7 players, 23 games, mixed skill,
selection effects). Every direction above must pass the normal design →
review → one-shot screen → confirmation pipeline before any adoption.
