# Double-shortlist: stop copying pure Ordering memos

DEV-only engineering follow-up to #265. No search/depth/world/finalist,
model, RNG, production default, or scoring change.

## Evidence and change

At #265 head `bc6cdcb677e57b4c9a5c454288e8c44df2fd467f`, the fixed fit
follow (panel coordinate 2, banker 0, round 0, decision ordinal 12) measured
110.057s with inner reuse off and 93.326s on: **1.179x**, with exact
evaluator batches/outputs, MC decision record, input and post-decision RNG.
Both opening cases stopped at the 300s operational limit; neither is a
completed parity witness or a game-strength result.

The subsequent isolated cProfile run completed the same optimized follow:
282.689s profiled wall, `_copy_state` cumulative 257.156s and `score_many`
6.640s. These are attribution numbers, not wall-clock speedup estimates.
The deep-copy graph includes the Ordering's increasingly large pure
decomposition/tractor memos, multiplied by 2,385 state copies.

`_copy_state` now seeds deepcopy's memo with the existing Ordering **only**
for exact `Round`, `Ordering`, and `HeuristicBot` types. Production MC and
`afterstate` already share this fixed-trump, pure-memo object. All remaining
game state is still deeply copied, including hands, burial, completed/current
tricks, trusted trick caches, extra mutable attributes and internal aliases.
Custom types retain full deepcopy. No global `__deepcopy__` override or new
engine behavior is installed.

## Proofs

- Real `decide_play` compared against the old deepcopy algorithm in learned,
  uniform and heuristic modes: exact batches, model outputs, complete
  non-timing/cache record, selected action, RNG and input state. An Ordering
  deepcopy tripwire and a nonzero actual copy count witness the wiring.
- Whole heuristic continuations compare every play/state and terminal points,
  including partial trusted tricks and kitty resolution.
- Direct mutation witnesses isolate hands, burial, history/current plays,
  extra caches and preserve `last_trick is history[-1]` within each clone.
- Round/Ordering/policy subclasses keep their original deepcopy isolation.

Local pure engine: 69 focused tests pass, including 13 new copy witnesses.
Compiled-path and wall A/B results will be attached to the PR at the exact
head; no inference from merely setting the native environment flag.

## Retained measurement pointers

Strength source/artifact root:
`/root/cwv-double-reuse-20260906.2R6k7q`.
Mini archive:
`~/shengji-archive/2026-09-06/double-shortlist.IMv7YS/`.

| Artifact | SHA256 |
|---|---|
| `cost-ab/summary.json` | `2e57286e8b343e9ec1880a40cc366c6fb6c518e2caece5f7488b78b348a33638` |
| `inner-profile/profile.pstats` | `adecb8ccd30323648c4ecf56be2a911915d4101719cf31f600f6f63a4d08db80` |
| `inner-profile/status.json` | `81c59f04319bef96a2704d24f0f339c5b1d40d824e04028231b63301db40b61b` |

Next measurement: exact source, existing ABC checkpoint and fixed fit follow;
old deepcopy versus the memo-seeded copy, both with inner cache reuse enabled.
Also time the optimized opening alone; do not repeat its twice-expired old
baseline or claim that this unpaired timing proves opening parity.
Retain per-case receipts and compare the entire existing semantic cost record.
One numerical thread, no competing Strength job,
300s per decision, 10 GiB process bound. Do not report a timeout as parity or
extrapolate two decisions to game speed/strength. The 26-pair strength
experiment remains unlaunched and keeps its requested one-extra-trick depth.
