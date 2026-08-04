# CORRECTNESS.md — engine correctness: tracking, validation, incident log

(Named CORRECTNESS rather than SAFETY to avoid ambiguity — this is about
the game engine never silently changing behavior. Sibling doc: PERF.md.)

**Why this outranks everything**: training data, Elo pools, probes, and
prod games all sit on the engine. A silent rules change poisons datasets
retroactively and invalidates every measurement taken after it. Speed
bugs cost hours; correctness bugs cost weeks and are invisible.


### Human-corpus contamination paths (found 2026-08-04 maintenance)

Two at once, both silent:

1. **`fetch_fly_logs.sh` wrote to the wrong directory.** It did `mkdir -p logs`
   relative to the cwd, so running it from `server/` created `server/logs/` —
   and 14 fetched prod games sat there, never reaching the corpus the shard
   builders read. Fixed by `cd`-ing to the repo root inside the script.
2. **A dev server predating the LOG_DIR change still writes to the corpus.**
   The uvicorn on :8899 started 2026-08-03 21:18, before `LOG_DIR` was moved to
   `logs/local/`, so its local test games (XNDT, NWDP) landed in `logs/`.
   Quarantined. Any dev server started before that commit has the old path —
   check the process start time, not just the code.

The general lesson: a corpus can be corrupted by writes as easily as by bad
labels, and neither of these announced itself. The `logs/local/` split only
helps for processes launched after it existed.

## The validation suite — run after ANY change to engine/ or ai/

```bash
cd server && uv run python -m pytest tests/ -q
```

Layers (all must pass; the 2026-08-04 audit ran **112 passed / 2 skipped** in
both plain and `SHENGJI_FAST=1` modes):
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
- **Multi-component throw comparison** uses the engine's top-component rule,
  not component-by-component dominance against the incumbent throw.
- **Partial tractor following** requires a full matching tractor when one is
  available; otherwise it preserves the required pair count but does not force
  the strongest available shorter tractor before unrelated pairs.

These are deliberate house rules, not open defects. Do not “fix” them toward
another implementation's profile without a new explicit table ruling.

## Open correctness gates (block new search data/evaluation)

1. **Belief worlds are not strict.** MCBot's last sampler retry sets
   `respect_voids=False`, and `Memory.pair_void` is never enforced in sampled
   hands. Used/rejected counters now distinguish the final relaxation and
   `SHENGJI_STRICT_SAMPLING` rejects it, but normal mode still accepts it and
   strict mode does not yet enforce pair-voids. Close that remaining contract
   before trusting high-N labels or selective-search comparisons.
2. **The seed boundary still has a fallthrough.** `registry.make_bot` and
   `tournament._seeded()` now dispatch by signature rather than swallowing
   constructor `TypeError`, but `_seeded()` returns `None` when a seedless
   factory returns a bot without `rng` (including direct SmartBot factories).
   Return the bot unconditionally, test an exploding constructor through the
   exact boundary, and compare per-seed/per-flip records rather than only
   aggregate scores.
3. **Raw-state datasets need round-trip proof.** A “rebuildable” record is not
   authoritative until a versioned loader reconstructs it and reproduces the
   same legal candidates, observation, role/phase, and continuation. The
   current high-N prototype has no such test. The 600-row artifact predates the
   sidecar-manifest patch; current code overwrites the sidecar while appending
   JSONL, so it does not prevent mixed runs.

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
| 08-03 | BANKER_KITTY cards were removed from `Memory.unseen`, then removed again by the sampler; banker search returned zero worlds and silently fell back to candidate 0 | search correctness / silent fallback | Codex audit; strict banker regression |
| 08-04 | duel call-site lambdas accepted `seed=` but dropped it, so 4,880 v11-vs-MC rounds labelled seeded actually used OS-entropy MC opponents | evaluation provenance | exact-factory audit |
| 08-04 | five-arm T3 runner launched without common skip policies, strict fallback evidence, manifest, paired analysis, or exclusive output; partial run terminated | evaluation harness / compute waste | preflight handoff audit + process inspection |
| 08-04 | a supposedly disjoint T3 gate RNG used Python's process-randomized string `hash()`, so identical runs diverged | nondeterministic evaluator | required replay diff |
| 08-04 | `_seeded()` TypeError repair introduced a no-`rng` fallthrough returning `None`; direct deterministic tournament factories break | boundary fallback / missing return | direct boundary probe |
| 08-04 | ~~`v11_extend.py` and `gate_duel.py` accept seed kwargs but drop them~~ **RESOLVED 08-04**: both scripts deleted; the one evaluator is `shengji/evaluation.py` and `test_evaluation_lib.py` asserts all four seats get distinct seeds | evaluation provenance / false test coverage | partial m0 duel audit |

Update this table whenever a correctness incident occurs — the log is
the argument for the rules.
