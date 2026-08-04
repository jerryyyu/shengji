# CORRECTNESS.md — engine correctness: tracking, validation, incident log

(Named CORRECTNESS rather than SAFETY to avoid ambiguity — this is about
the game engine never silently changing behavior. Sibling doc: PERF.md.)

**Why this outranks everything**: training data, Elo pools, probes, and
prod games all sit on the engine. A silent rules change poisons datasets
retroactively and invalidates every measurement taken after it. Speed
bugs cost hours; correctness bugs cost weeks and are invisible.

## The validation suite — run after ANY change to engine/ or ai/

```bash
cd server && uv run python -m pytest tests/ -q
```

Layers (all must pass, **87 tests** as of 2026-08-04; run in BOTH modes when
the compiled path is involved: plain, and `SHENGJI_FAST=1`):
1. **Unit tests** — test_engine.py, test_game.py, test_memory.py,
   test_rl.py: rules primitives, game flow, memory inference, RL codec.
2. **Golden histories** — test_engine_parity.py: fixed-seed full rounds
   for heuristic/smart/mc must reproduce BYTE-IDENTICAL play sequences.
   Catches any behavior change, intended or not.
3. **Cached-vs-reference parity** — every memoized/fast-path primitive
   equals its uncached/validated reference on randomized inputs.
4. **Invariant property tests** — test_invariants.py (being added by the
   2026-08-02 audit): points conservation, deck accounting, beats()
   antisymmetry, bot-play legality over random rounds, shard round-trip.

## Rules

- **Golden regen policy**: `uv run python tests/test_engine_parity.py
  --regen` ONLY when a change deliberately alters behavior — in the
  same commit, with the reason in the commit message. A regen without a
  stated reason is treated as a bug.
- **Optimizations ship with differential tests**: optimized vs
  reference path, identical seeded histories, before any generated
  data is trusted. Pure-Python reference implementations are never
  deleted — they are the source of truth (and the fallback).
- **Ballot/encoding freeze** (Elo-798 rule): play-time enumeration for
  a net must match its training distribution; enumeration/encoding
  changes ⇒ regenerate data, retrain, re-verify. Never hot-enable.
- **Killing generation jobs**: `pkill -f <parent cmdline>` does NOT
  match multiprocessing workers (they appear as bare `python3 -`).
  Always follow with a process-age audit and kill survivors by PID, or
  the old code keeps writing into the live dataset.
- **Dataset provenance**: every generated dataset carries META.json
  (ballot family, teacher git SHA, config). Data from an engine state
  that later proves buggy is quarantined, not silently kept.
- **Determinism is a correctness property**: fixed seeds must reproduce
  across processes (PYTHONHASHSEED-independent). Iterating sets/dicts
  where order can influence a choice is a bug even when outputs look
  fine.
- **Compiled ports (Cython/Rust)**: may not merge until the full suite
  passes byte-identical WITH the fast path active, goldens untouched.

## House rules (deliberate divergences from other implementations)

Jerry's table, ruled 2026-08-03 after the Codex audit flagged them:
- **Kitty multiplier** = 2 x the final play's CARD COUNT (pair+single on
  the last trick multiplies by 6). rbtying uses 2 x longest component.
- **Declaration self-overcall** with a DIFFERENT suit is allowed.

These are configuration, not defects — do not "fix" them toward another
implementation's profile. Open rules questions still under review:
component-wise dominance for throws, and partial-shape obligations when
following tractors.

## Incident log (why these rules exist)

| date | incident | class | caught by |
|---|---|---|---|
| 08-01 | exhaustive-follows change collapsed deployed net to Elo 798 | ballot mismatch | pool anomaly |
| 08-02 | tournament chunk workers disagreed on pairing indices (one pairing ran 3x, two never ran) | hash-ordered set iteration | result audit |
| 08-02 | MCBot default flip silently widened RL play-time follow ballots | shared-helper config leak | Jerry's question |
| 08-02 | find_tractor_runs memo returned mutable lists; throw-penalty path mutated the cache | mutable-cache aliasing | golden test, day 1 |
| 08-02 | Memory deck scan iterated set(make_deck()); world sampling differed per process | hash-order nondeterminism | golden test, day 1 |
| 08-03 | memo caches keyed on sorted cards but computed on caller order — equal-level trump-rank pairs could return a different physical split per caller | cache-key/computation mismatch | audit agent |
| 08-03 | _throw_penalty returned a live alias into the decompose cache (latent poisoning) | mutable-cache aliasing | audit agent |
| 08-03 | Cython prototype implemented PRE-audit memo semantics (sorted keys vs caller-order) — quarantined same day, fixed in phase 0 | two-implementation drift | contract tests, day one |
| 08-03 | SAME BUG on the Air: 7 phase-1 workers survived the 08:24 pkill and ran 2h alongside phase-2 — the machine looked "14 hot / 900%" (healthy) while half its cores did discarded work; no data written (buffers hadn't flushed) | orphaned-worker waste | fleet_status integrity section |
| 08-03 | (same bug, second instance) the mc-vleaf vs mc POOL pairing read 70-50 on one run and 57-63 on a re-run — the headline Elo 1163 rested on the first | non-reproducible measurement | seeded-protocol re-run |
| 08-03 | Elo pool bots are UNSEEDED (`REGISTRY[name]()` -> `MCBot(seed=None)` -> OS entropy), so pool numbers are not reproducible run-to-run: an accidental re-run of the same vleaf pairing gave 85-35 where the original gave 84-36 | non-reproducible measurement | accidental duplicate run |
| 08-03 | pkill by parent cmdline left 2 multiprocessing WORKERS orphaned on buggy-memo code for 10h; they silently wrote 2 more shards into the live dataset | orphaned-worker contamination | fleet check (process-age audit) |
| 08-03 | failed throws forfeited the FIRST beatable component, not the lowest (scan order over-punished) | rules bug | Jerry, from play |

Update this table whenever a correctness incident occurs — the log is
the argument for the rules.
