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

At `87552e9649627de002201d5a9c480c15beb57e18`, 69 focused tests passed
in both pure and explicitly activated compiled mode. The isolated real-fit
follow measured 88.3999s with old deepcopy versus 9.2515s with shared Ordering
(9.555x), with the entire semantic cost record identical. The optimized
opening completed in 112.041s; its expired old baseline proves neither parity
nor a speedup. Copy-cost summary SHA:
`9d976a100914f30dd2ac783d5b1fa505c1f14f021dbd46940b9661f6ee481a22`.

## Full-game memory failure and retention repair

The first 26-deal, balanced-13-rank screen started eight workers at
2026-09-06 10:59:17 UTC. At 11:05:17 the 27 GiB cgroup limit OOM-killed a
worker, before a requested manual stop reached it. Peak aggregate memory was
27 GiB (one observed worker exceeded 7 GiB RSS); no pair shard completed.
The learned arm and success-dependent followup queue are terminal. Uniform
and flat controls did not start. This is an operational failure, not a
negative strength result. It also demonstrates that fixed-position timing
and parity did not establish full-game memory safety.

The shared Ordering retains the union of pure memo entries from simulated
continuations. A bounded 120s probe on an already-submitted seed (91261166,
rank 4) observed 457,855 decomposition entries and 7,709 tractor entries,
with 1.24 GiB peak RSS before its diagnostic timeout. That seed was not
identified as the largest failed worker: this is evidence of cache retention,
not proof that caches explain every byte of the OOM.

The repaired path clears decomposition memos above 65,536 entries and tractor
memos above 8,192 entries at copy, parent-enumeration and model-batch
boundaries. These are retention thresholds, **not action/search caps or hard
peak-memory guarantees**: one exhaustive enumeration may temporarily exceed
them. Entries are pure and recomputed on a miss. Clearing is in place because
native `_fast_ctx` retains aliases to the exact dictionaries; replacing an
attribute would leave the old native cache alive. Exact custom types retain
the previous behavior, as in the copy optimization.

Eight added tests cover native aliases, pure-engine caches, custom types,
inclusive thresholds, and real learned/uniform decisions with root/inner
reuse on and off. Forced tiny limits witness nonzero clearing in actual
multi-row ranking batches, while actions, evaluator inputs/outputs, MC
records, RNG and physical input state remain exact. Removing the batch trim
must fail that consumer witness rather than be masked by later copy trims.
Repaired-head compiled validation and bounded wall/memory evidence are
published on PR #266 before any full-screen restart.

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

The initial copy A/B, failed screen and diagnostic artifacts are retained at
`/root/cwv-double-copy-20260906.cgL6DU` and the Mini archive above. A repair uses
a new immutable source archive and output attempt, never edits the failed
source/config in place. The existing 26-deal window and one-extra-trick
4/30-guidance recipe remain unchanged. Next: bounded same-seed memory
measurement and exact fixed-follow comparison, then the same full population
only if the repaired path has credible resource headroom. No new seed
selection, depth reduction, outcome claim from incomplete work, or repeat of
the twice-expired old opening probe.
