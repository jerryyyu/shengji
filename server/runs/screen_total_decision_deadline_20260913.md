# Future screens: 300-second total play deadline

Status: implemented in PR #400; review required before merge/use. Tracks #396.
Jerry selected **300 seconds total per play**, replacing the issue's proposed
600 seconds. This is a new screen recipe, not a change to active windows.

## Behavior

- Start one monotonic deadline at decision entry. Include fallback preparation,
  legal enumeration, world sampling, neural ranking, MC selection and the
  independent report. Never reset the clock between phases.
- Prepare a legal heuristic fallback before expensive search. On expiry, return
  that move; retain the round and its actual outcome in the paired results.
- Discard unfinished selection/report evidence. Never present partial means,
  an earlier move's receipt, or a partially filled report as completed search.
- Apply the same deadline to both policies. Label this a capped-policy comparison,
  not decision-preserving optimization or equal-compute evidence. Host contention
  can change which moves expire even with the same deadline.
- Bury/declaration are outside this **play** deadline. They need separately named
  budgets rather than silently sharing or resetting it.
- Old configurations without a deadline retain their old interpretation. A fresh
  screen must explicitly bind the 300-second deadline and fallback version in
  its configuration and resume identity. Never mix capped and uncapped shards.

## Enforcement: do not promise a hard cap with a Python timer

The original `search_screen.TimedPolicy` measures after `decide_play` returns;
`CwvTimedPolicy` attaches shortlist receipts. `screen_deadline.DeadlineSession`
now supervises those wrappers from the game-owning process.

An in-process signal/cooperative check alone is insufficient: Python may not
handle it until a native operation returns. The implementation supervises search
in a spawned process, with game state and legal fallback owned by the supervisor.
The supervisor stops waiting at the deadline, rejects late
results, terminates unfinished work and continues with the fallback. Record
actual return latency and cancellation overshoot; ordinary scheduling and
cleanup still prevent a real-time guarantee of exactly 300.000 seconds.

One persistent child per cluster shares evaluator caches across all bots. Only
completed requests commit bot state/counters/RNG; timeout restores the previous
checkpoint and clears stale decision evidence. A replacement child recreates
models and restores those checkpoints (cold restart counts in the next play's
budget). Completed work preserves the uncapped action, RNG and receipts. Linux
uses a parent-death signal as well as explicit kill/reap cleanup; macOS has normal
daemon/finally cleanup, not a parent-SIGKILL orphan guarantee. Registration has
a separate 120s startup guard. Unexpected crashes refuse the shard; they are not
misreported as timeouts. Completed shards remain available for recovery.

## Telemetry (every move, including forced moves)

For each side report:

- Total decisions, timeout count and timeout percentage.
- Counts/fractions above 10, 30, 60 and 300 seconds; p50/p95/p99/max latency.
- Each timeout's deal/mirror/seat/trick, last observed phase, known legal-action
  count (null if enumeration was unfinished), fallback and elapsed/overshoot.
- Completed versus interrupted work separately. Do not count lost worker
  counters as zero CPU or zero work; label incomplete accounting explicitly.

Aggregate decision denominators across all moves, not just decisions with an MC
receipt. Timeout rates remain visible even when gameplay strength is neutral.
300 seconds is emergency containment, not an acceptable normal latency target.

## Required consumer tests before use

1. A fast decision gives the same move, RNG continuation and completed receipts
   with and without the wrapper.
2. A blocked native-like worker is stopped by the external deadline; a legal
   fallback reaches the engine and the round continues without dropping a deal.
3. Enumeration + ranking + selection + report share one budget: individually
   short phases whose sum exceeds the budget must still expire.
4. Expiry during each phase cannot publish partial or stale search evidence.
5. Late replies cannot satisfy the next request. Cancellation followed by the
   next move works, preserves declared RNG recovery, and leaves no orphan worker.
6. Both policy factories use the wrapper. Forced and timed-out moves appear in
   the exact per-side summary counts; configuration drift refuses shard reuse.

Use short injected deadlines in tests. Then qualify wrapper overhead and
cancellation on a bounded saved-state comparison, including a wide-tail state.
No repeated multi-hour capacity runs, no changes to live windows, no deployment.

## Entry points and local qualification

Both `cwv_shortlist_screen` and `cwv_screen_queue` default to
`--decision-deadline 300`. `--decision-deadline 0` explicitly selects uncapped
behavior. This does not retrofit frozen/older checked-out runners. There are no
registry, Fly or production default changes.

`scripts/check_screen_deadline.py` exercises the actual W32 model and saved tail:

```
PYTHONPATH=server python server/scripts/check_screen_deadline.py \
  --checkpoint /path/to/w32-fd6bb411.npz \
  --wide-snapshot /path/to/prefix-profile.json --out /new/path/result.json
```

2026-09-13 local qualification (not an isolated cloud performance claim):

- Checkpoint `fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9`,
  W32 / selection 30 / report 300 / mlp-static / successor reuse.
- Four pairs on seed 431, including one warmup: identical actions, RNG, complete
  non-timing receipts and rollout counts. Three warm direct calls 2.420–2.474s;
  supervised calls 2.533–2.777s. Startup 0.636s. Not a broad overhead estimate.
- Saved seed 13561373 follow with 379,753 actions: deliberately shortened 2s
  deadline cancelled ranking at 2.013s, engine accepted fallback, next request
  restarted and completed. This validates cancellation, not strength.
- Artifact: `~/shengji-archive/2026-09-13/deadline-qualification.json`.
- Focused tests include GIL-held native hangs in all five phases, total-budget
  expiry, rollback, fast real MC parity, a complete mirrored driver retaining
  four timeouts per side, per-policy summary bins, crash refusal, CLI/queue
  defaults and capped/uncapped shard separation.
- Validation: 48 tests passed across `test_screen_deadline.py`,
  `test_cwv_shortlist_screen.py`, `test_cwv_double_shortlist_screen.py` and
  `test_cwv_screen_queue.py`; independent source review passed.
