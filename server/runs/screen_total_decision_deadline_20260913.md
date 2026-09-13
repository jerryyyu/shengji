# Future screens: 300-second total play deadline

Status: implementation contract, not an implemented timeout. Tracks #396.
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

Current `search_screen.TimedPolicy` measures a move after `decide_play` returns;
`CwvTimedPolicy` attaches shortlist receipts. Neither enforces a deadline.

An in-process signal/cooperative check alone is insufficient: Python may not
handle it until a native operation returns. The implementation should supervise
search in a separate process, with the game state and legal fallback owned by
the supervisor. The supervisor stops waiting at the deadline, rejects late
results, terminates unfinished work and continues with the fallback. Record
actual return latency and cancellation overshoot; ordinary scheduling and
cleanup still prevent a real-time guarantee of exactly 300.000 seconds.

Use persistent workers so model loading is not repeated per move. Do not fork
an already-threaded Torch/MPS process. Explicitly define RNG/state recovery after
cancellation; retaining a half-mutated bot or reseeding it silently is not safe.
Completed work must preserve the uncapped action, RNG continuation and receipts.
Parent/worker cleanup must not leave orphan searches consuming screen cores.

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
