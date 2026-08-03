# INC-07: Memo keys did not capture order-dependent computation

**Date**: 2026-08-03 (introduced ~23:30 08-02, found ~01:30)
**Severity**: S1 — data-corrupting (deterministic per run, so invisible
to golden tests)
**Status**: fixed (exact-order keys), guarded by a contract test

## What happened
Two hot functions (`decompose`, `find_tractor_runs`) were memoized to cut
generation cost. The cache key was `tuple(sorted(cards))` — but both
functions are **greedy and order-dependent** when two distinct cards
share a level (off-suit trump-rank pairs, e.g. `S7S7` vs `D7D7` when 7 is
the trump rank). The first caller's argument order decided the answer
every later caller received.

## Impact
A cache hit could hand back a different *physical card split* than the
reference implementation would compute for that caller — i.e. bots could
play different cards than the engine's own rules code says they should.
Live repro: `decompose` returned `[D7D7, S7S7]` where the reference gives
`[S7S7, D7D7]`. No corrupted data was shipped (found within ~2 hours,
and the affected window's shards were quarantined under INC-10).

## Root cause
A cache key must capture **everything the computation depends on**. We
keyed on the multiset of cards and assumed order was irrelevant; the
greedy tie-break made it relevant.

## Why the existing guards missed it
Golden histories are byte-identical *within a run*, and the bug was
perfectly deterministic in a single process — the same first-caller
always won. Only a differential test comparing **cached vs uncached on
adversarially ordered inputs** could see it, which is exactly what the
correctness audit added.

## Fix
Exact caller-order keys (`tuple(cards)`), so the cache never merges two
orderings that can produce different results.

## Prevention (shipped)
- `tests/test_invariants.py`: cached-vs-reference parity on randomized
  hands, plus an explicit exact-order contract test for both functions.
- A cache-integrity test that recomputes every live cache entry against
  the reference after a full MC round.
- These same contract tests later caught the Cython port re-introducing
  the old semantics (INC-08) — the guard paid for itself within a day.

## Lesson
**Determinism is not correctness.** A bug that reproduces perfectly is
still a bug; "the goldens pass" only means behaviour did not *change*,
not that it is right.
