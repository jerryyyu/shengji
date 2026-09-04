# CORRECTNESS.md — engine correctness: tracking, validation, incident log

(Named CORRECTNESS rather than SAFETY to avoid ambiguity — this is about
the game engine never silently changing behavior. Sibling doc: PERF.md.)

**Why this outranks everything**: training data, Elo pools, probes, and
prod games all sit on the engine. A silent rules change poisons datasets
retroactively and invalidates every measurement taken after it. Speed
bugs cost hours; correctness bugs cost weeks and are invisible.


### Human-corpus contamination paths and repair

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

The August 9 refresh closed two more silent paths. Fly SFTP refuses to
overwrite an existing local filename, while the old fetch script swallowed
that error, so growing production rooms remained stale. The fetcher now stages
and JSON-validates every remote file, preserves changed local copies, replaces
them atomically and writes a source-hash manifest. Five of 30 production files
were stale on the first repaired refresh.

The old human shard builder also caught every replay exception and continued
without counters, emitted no source/producer/encoder manifest, and ignored
bury decisions. The versioned builder now publishes only from fully replayed
and score-matched rounds, counts every rejection, verifies source hashes before
and after reading, pseudonymizes player grouping, records replay sidecars, and
captures human buries separately. Its `.npz` remains a behavior/proposal asset:
coarse final-round return and mixed human skill are not Teacher or strength
truth.

## The validation suite — run after ANY change to engine/ or ai/

```bash
cd server && uv run python -m pytest tests/ -q
```

Layers (all must pass; current S0 packet collects **365 tests**, with both the
plain and `SHENGJI_FAST=1` routes required):
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
- **Fleet absence requires positive proof**: an empty filtered process list is
  `UNKNOWN`, not `IDLE` or `DEAD`. Before launching a replacement, reconcile
  the expected PID set, a broad raw Python inventory, every worker heartbeat
  or log mtime, and terminal output count. Identify jobs by exact script and
  immutable run namespace; signal explicit PIDs and verify every stop.
- **Dataset provenance**: every generated dataset binds source bytes, producer,
  engine/encoder, ballot, target, split and accepted/rejected work. Data from an
  engine state that later proves buggy is quarantined, not silently kept.
- **Determinism is a correctness property**: fixed seeds must reproduce
  across processes (PYTHONHASHSEED-independent). Iterating sets/dicts
  where order can influence a choice is a bug even when outputs look
  fine.
- **Belief worlds and hands are multisets.** A sampler's list insertion order
  is not game state. Canonicalise at the rollout-policy boundary and preserve
  end-to-end decision witnesses; otherwise HeuristicBot continuation can give
  two representations of one world different values and flip MC's argmax.
- **Compiled ports (Cython/Rust)**: may not merge until the full suite
  passes byte-identical WITH the fast path active, goldens untouched.

## Search-decision provenance and exact-work boundary

A legal sampled world is necessary but not sufficient for a trustworthy MC
decision. Every contested current/S0 search now records the registry policy,
git/dirty/code and derived ballot identity, restorable pre-selection RNG state,
named child-stream seeds, all candidates/means/paired SEs, raw winner, final
played card/reason, elapsed time, exact selection/report work and per-decision
sampler deltas. The server refuses to attach a decision record whose played
multiset differs from the move it received. Tractor-lock and one-candidate paths
clear prior state before returning, so a later play cannot inherit an earlier
search's explanation.

Sampler counters obey `attempts = accepted + failed`. A registered exact search
or report fold that cannot fill its dose returns candidate 0, increments
`short_search_decisions`, and makes an evidence run fail closed. Retrying a
failed draw is not itself a protocol failure when the final accepted dose is
exact and counters reconcile; silently searching fewer worlds is. Report folds
run on a named stream disjoint from selection, and partial folds never decide.

**Independent draws do not mean unique realized worlds.** Hidden-world folds
sample with replacement from the posterior. Repeated world identities inside a
fold, or the same realized world appearing in two domain-separated folds, are
valid and must retain their probability mass. Candidate actions within one
fold deliberately share the same sampled worlds for paired comparison;
selection/report/audit folds use independent RNG streams. Deduplicating
realized worlds both flattens the posterior and can make a finite-support late
state underfill despite thousands of successful draws. Telemetry should report
duplicates and cross-fold identity overlap, never discard them.

The immutable S0 challenge/calibration asset is
`server/tests/data/s0_override_audit.v1.json` (SHA-256
`9703b50817fb03622c3739e44f73e19083b1e8337300be7054774e2308e13ef5`).
It is an inspected DEV diagnostic, not a sampler certificate, strength result or
training set.

## Hidden-world sampler correctness boundary

MC values are meaningful only if each determinization is compatible with the
public history. “The sampler returned a hand” is not evidence of that. A valid
world must conserve the complete 108-card multiset across the observer's hand,
played cards, other hands and hidden kitty; preserve hand sizes and public
declarations; and obey every proven suit-void, remaining-pair and remaining-
tractor-run constraint. A decision that produces zero valid worlds is a
protocol failure, not permission to fall back silently to candidate zero.

The earlier claim that P0 closed at `eea78d2` is **withdrawn as a population
claim**. Its single global limit was exhausted inside the 20,845-row `original`
source, so it exercised zero `late` rows while advertising original+late; it
also predates named replay-skip counters. `c1ceca1` is useful current-original
evidence only and ran 40 rather than the registered 120 toys. Neither artifact
certifies the stated population.

`fc19d26` repaired the population contract, and `aea3774` closed the remaining
fail-closed holes. The clean v3 artifact requires exact original/late/deep
500/500/500 quotas, 36,000 requested = accepted, zero rejected/invalid/named
skips, 120/120 exhaustive support and real witnesses, clean current HEAD, and
compiled+strict execution. The bounded P0 certificate is therefore **closed**.

The certification work found real producer defects: greedy card-first allocation
could dead-end despite a feasible assignment; a pinned declared card could be
completed into a pair the history forbade; and pair limits did not enforce the
distinct tractor-run constraint. The certifier itself also initially collapsed
seat identity, failed to distinguish an overlarge enumeration from an empty
legal set, silently dropped unreplayable rows, and starved later sources behind
a global limit. The durable rule is that sampler certification needs an
independent history-derived validator, explicit population accounting and
exhaustive small worlds; producer-owned invariants and “some world appeared
within N retries” are insufficient.

The closed gate proves two bounded claims only:

- **validity:** accepted strict worlds satisfy the tested public constraints;
- **support:** every legal world is reachable on the exhaustive toy family.

It does **not** prove **distribution fidelity**. `_splits()` samples feasible
suit-count matrices without weighting by how many card-level completions each
admits, and `_deal_suit()` takes the first cap-respecting card from a shuffled
list. Both can give legal worlds the wrong probabilities. More worlds reduce
Monte Carlo variance around that biased distribution; they do not remove the
bias.

Operational consequences:

- every data, pilot and confirmation runner must require
  `SHENGJI_REQUIRE_VOIDS=1`, record it in its manifest, and fail on any
  impossible-world, rejected-world or zero-world counter unless a rejection
  policy was explicitly preregistered;
- production `mc` still retains a final lenient retry when that environment
  guard is absent, so its worlds are not unconditionally strict by construction;
- `highn_corpus` predates this repair and remains provisional. Passing today's
  certifier cannot retroactively clean its labels;
- `RL_PLAN.md` owns the resulting data/training contract, while
  `AI_POLICIES.md` records which callable policies use this sampler and how the
  uncertified posterior limits their evidence.

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

## Open correctness gates (each item states what it blocks)

1. **Posterior probabilities are not certified.** Exact-enumerate small legal
   posteriors and measure total-variation distance, per-card/seat marginals and
   exchangeability. Then sample count matrices proportional to admissible
   card-level completions and make capped fills uniform. Until that closes,
   common worlds support DEV selection screens but a winning structured ballot
   must be re-priced under the corrected distribution before promotion or new
   teacher labels.
2. **Strictness is runner-enforced, not the production default.** The final
   sampler retry may still ignore observed voids unless
   `SHENGJI_REQUIRE_VOIDS=1`. All evidence-producing paths now fail closed on
   this, but production should either make strict construction unconditional
   or retain explicit telemetry and a deliberate product-level exception.
3. **Raw-state datasets need round-trip proof.** A “rebuildable” record is not
   authoritative until a versioned loader reconstructs it and reproduces the
   same legal candidates, observation, role/phase, and continuation. The
   current high-N prototype has no such test. The 600-row artifact predates the
   sidecar-manifest patch; current code overwrites the sidecar while appending
   JSONL, so it does not prevent mixed runs.

The new deep-lead schema closes that obligation for its own rows, not for the
legacy high-N rows: it stores every accepted declaration at its exact deal
position, final trump/banker, deck, bury and ordered plays; its independent
loader replays those events without invoking a current bot. Capture round-
trips each row before admission and merge replays every selected row again.
Partial shards and final artifacts use completion-marker renames, and manifests
bind script, engine, compiled binary, sampler, Memory, actor, replay, ballot,
configuration and git identities.

Its sampler admission rule is deliberately narrower than “ignore a counter.”
If strict sampling rejects a proposed world, that world was not used, but the
action used fewer than the registered 30 worlds; capture therefore excludes
the **entire deal**, counts both the rejected worlds and excluded deal, and
continues scanning. A zero-world heuristic fallback or an actually used
void-violating world still aborts the shard. Shard schema v2 separates zeroed
accepted-trajectory counters from observed counters on excluded deals, and
merge validates the accounting. This preserves the accepted actor contract
without making a 60,000-seed scan impossible because one invalid proposal was
safely refused.

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
| 08-04 | sampled/acting hands with the same card multiset but different list order changed HeuristicBot rollout continuations and could flip MC's action | actor-distribution nondeterminism | layer probe plus preserved seeds 772006/772045 |
| 08-05 | tractor-lock / one-candidate plays could retain the preceding search record; raw winner could be logged as the played move after a fallback | live observability could explain the wrong action | direct stale-sentinel and server-seam regressions |
| 08-05 | adaptive search could re-admit a pruned candidate on its frozen noisy mean, strand residual work, and omit disjoint-report work/time from counters | search/action and equal-work correctness | exact-work S0 controls and sanitised incident accounting witness |
| 08-05 | JSON preserved RNG bytes but decoded tuples as lists that `Random.setstate()` rejects; partial report folds with >=2 worlds could still decide | claimed replay/refusal contract was not executable | exact JSON replay and underfilled-fold regressions |
| 08-09 | Fly SFTP refused existing filenames while the fetch script swallowed errors; five growing production logs stayed stale locally. Human extraction then silently discarded replay failures and emitted no provenance or bury surface. | corpus freshness / silent data rejection | atomic hash-manifest refresh + fail-closed human-v1 builder |
| 08-10 | Stage-C label v1 discarded repeated realized hidden worlds within and across independent folds; six shards refused and retained worlds had flattened posterior mass | statistical sampler semantics / terminal no-use labels | iid-v2 with-replacement regression, domain-separated fold RNG and retained-overlap telemetry |
| 08-12 | a mistyped Air process filter reported a healthy S6 census idle; a duplicate eight-worker cohort ran for about a minute before exact PID/namespace reconciliation stopped only the duplicate | fleet-monitor false negative / wasted compute | broad process inventory plus advancing original logs ([INC-12](incidents/INC-20260812-12-fleet-monitor-false-negative.md)) |
| 08-12 | a reviewer called the real S4 `launch()` behind an ineffective wrapper-module monkeypatch, unintentionally starting 16 gameplay workers for about five minutes; no result completed, but the immutable packet and full seed interval were retired | reviewer authority-boundary failure / wasted compute | exact Cloud process reconciliation and namespace inventory ([INC-15](incidents/INC-20260812-15-reviewer-witness-launched-gameplay.md)) |
| 08-12 | S4's Pair-to-search queue used broad `pgrep -f`; the persistent tmux server retained the capture command in its argv and would have caused a false post-capture `HOLD` despite zero Python workers | fleet-transition false positive / idle-compute near-miss | executable plus exact argv reconciliation before handoff ([INC-16](incidents/INC-20260812-16-s4-queue-process-filter-false-positive.md)) |
| 08-12 | a Codex-authored S5 marker template was accidentally written at column one and looked like an independent PASS to a prefix-only scan; author-heading validation caught it before implementation | review-authority provenance near-miss | exact prefix plus preceding independent-reviewer heading ([INC-17](incidents/INC-20260812-17-request-template-looked-like-review-pass.md)) |
| 08-13 | PR #74's executable gate accepted the Codex request template as its independent-review marker; a queue consumed the S5 admission and ran the producer for 41.7 seconds before termination, publishing no result. The queue also checked the wrong admission path | review-authority provenance failure / spent one-shot / wasted compute | unexpected perf-host process plus exact systemd, namespace and admission audit ([INC-18](incidents/INC-20260813-18-request-template-self-authorized-s5.md)) |
| 08-24 | R5's generic `resource cap drift` refusal hid which dimension fired; the completed component population (27.8 GB) exceeded the 24 GiB host-memory limit, not the 64 GiB storage limit, and `MemoryPeak` in the systemd evidence settled it | measurement-invalidating diagnosis / no bad data | typed per-dimension refusal messages plus systemd resource evidence in every terminal ([INC-20](incidents/INC-20260824-20-r5-cache-resource-misdiagnosis.md)) |
| 08-29 | BELIEF R4 was built as a confirmatory experiment — strict freezes, one-shot openings, byte bindings, independent verification — before a cheap exploratory answer existed; every late defect became a multi-day operation and the first scientific answer arrived weeks late | process failure / wasted compute and delayed learning; the anchor for the 2026-09-04 program reset (ledger `0088544f`) | rigor tiers matched to claim altitude (`RESEARCH_PRINCIPLES.md` §11) ([INC-21](incidents/INC-20260829-21-r4-confirmatory-before-signal.md)) |
| 08-30 | the first reviewed Value V2 capacity census refused between inference-batch arms because the harness compared raw float32 logits for byte identity across batch sizes, an artifact the design never required | wasted reviewed admission / no data opened | compare the reviewed decision artifact, not an intermediate tensor ([INC-22](incidents/INC-20260830-22-v2-capacity-artifact-altitude.md)) |

Update this table whenever a correctness incident occurs — the log is
the argument for the rules.

## Sampler certificate — original+late+deep, aea3774 (2026-08-05)

The FIRST certificate covering all three reservoirs. Stored at
`server/runs/logs/certify_sampler_v3.json` (SHA-256
`e31e67f9aeb4739aa598faa66051ec4004fd47751b297457242dc95a30cc224c`).

```
  states 1,500 = 500 original + 500 late + 500 deep
  worlds 36,000 requested = 36,000 accepted, 0 rejected, 0 invalid
  toys   120/120 fully reachable, real deal reached in 120/120
  skips  all four counters 0
  git aea3774, tree_dirty false, compiled ACTIVE, strict voids ON
```

**SUPERSEDED — none of these is original+late+deep certification:**

- `eea78d2` — the long-standing "P0" certificate. `reservoir_states` kept ONE
  global counter across ordered paths and `original` holds 20,845 rows, so it
  exhausted its limit inside `original` and exercised ZERO `late` rows. It was
  original-only while advertising original+late.
- `c1ceca1` — my attempted replacement. Same defect, plus 40/40 toys against a
  registered 120.
- the dirty `v2` run — generated before the implementing commit
  (`tree_dirty=true`), so not a clean-current artifact.

Scope: this closes the bounded P0 certificate ONLY. It does not prove posterior
fidelity, and it does not prove the production dealer globally complete under
all declaration-pin/run-cap combinations. Both remain open in `BACKLOG.md`.
