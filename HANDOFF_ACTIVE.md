# Active Claude/Codex handoff

Last update: 2026-08-05 12:15 EDT. This is the operational front door.
Historical audits live in `HANDOFF_REVIEW.md`.

## Status: DEV gate passed; run stopped fail-closed at 7/8 shards

Codex passed the registered v6 DEV-512 launch in `5ef4fe6`.
The gate artifacts remain:

- DEV `pilot_dev512.v6.json`:
  `af78748586034f6f97e96a167008b2c540c0e4b1670a683ef6b5f05ec85d3e7b`
- CALIB `pilot_calib512.v6.json`:
  `3872350f57a4dd602d958182c0a0aecc27c6bf99c9330e8265bcf84c9c3dce05`

Mini shards 0–3 and Air shards 4, 6 and 7 completed: 64 states each,
identical experiment ID `862b00e20a56b230...`, clean `5ef4fe6`, zero
sampler counters, work violations, replay errors or protocol failures.

**Air shard 5 has no result artifact.** Its first launch correctly refused
because Air lacked gitignored replay corpora (the observed error named
`rl_data/highn_late_air.jsonl`). Original, late and deep inputs are now present
and match the v6 provenance (`40ea1ae4788f2586`, `f2251f8267bf69ce`,
`ffccfde64932eb3a`). The protocol-identical retry then failed closed at:

```text
original:81002046:4
fold/sampler invariant failed: short={}, sampler={'rejected_worlds': 1}
```

No aggregate is authorized. Do not inspect arm outcomes from the seven
completed shards, drop this state, relax the counter gate, change the seed or
rerun until something passes. CALIB and REPORT remain unscored.

## What the DEV pilot compares

Every state is paired across the same independent report worlds. The first four
arms are capped at 14 candidates and approximately 168 proposal
candidate-world evaluations.

| arm | ballot/search treatment | question answered |
|---|---|---|
| `current` | Deployed MC lead ballot. | Baseline. |
| `v3` | Current ballot plus the earlier residual-shape/level lead-single expansion, capped at 14. | Does the specific V3 widening help? |
| `random_fill` | Protected heuristic lead plus random actions from the broad structured universe, capped at 14. | Does mere widening explain a gain? |
| `quota` | Protected lead plus round-robin structural archetype quotas and within-archetype diversity, capped at 14. | Does deliberate candidate selection beat random fill? |
| `mc_more_full_work` | The unchanged current ballot, but with enough proposal worlds to match the full universe's total proposal work. | Is more MC on the existing ballot enough? |
| `full_universe` | Every enumerated structured lead, deployed candidates and bounded component mutation; uncapped, 12 proposal worlds per action. | What is the high-compute coverage ceiling? |

The preregistered primary contrast is `quota - random_fill`: selection quality
at the same ballot budget. The attribution contrast is
`full_universe - mc_more_full_work`: broader sourcing versus spending the same
large amount of work pricing the current ballot. Comparisons with `current`
and `v3` are secondary. Twelve disjoint oracle worlds select the frozen
reference and twelve disjoint report worlds score every chosen action.

This is an offline lead-decision experiment. It can select a ballot design for
CALIB; it cannot by itself establish full-game strength or deployment.

## Package G — diagnose the shard-5 counter without moving the estimand

1. Preserve the seven complete JSON files, the original missing-input refusal
   logs and the shard-5 counter-failure log. Do not aggregate them.
2. Reproduce `original:81002046:4` under the exact shard-5 protocol in a
   bounded diagnostic that records the fold, draw index and rejection cause
   without changing RNG order.
3. Decide whether the rejection is:
   - an implementation/correctness bug with an invariant-preserving fix; or
   - expected behavior of the production sampler, meaning the preregistered
     zero-counter protocol is incompatible with this estimand.
4. Add a regression before any fix. Do not weaken the runner's refusal.
5. Add a two-machine preflight that requires every replay corpus and its live
   digest, not only HEAD/artifact/ballot/compiled-binary identity.
6. If code, sampler behavior or protocol changes, quarantine all seven completed
   shards and rerun **all eight** from one clean identical HEAD. Never combine
   pre-fix and post-fix shards.
7. Only after eight clean shards exist, copy them to one machine, run the strict
   aggregator exactly once, and report its refusal or complete table. Select at
   most one DEV design—or select none—before touching CALIB.

## Codex bounded diagnosis — 2026-08-05 12:15 EDT

**The rejection is reproduced and is an implementation failure, but the live
uncommitted fix is HOLD.** I loaded the committed `9a03304` `_assign` method
in-memory, leaving Claude's working tree untouched, and replayed the exact v6
state and independent fold streams. The sole rejected world is:

```text
state: original:81002046:4, acting/banker seat 0
fold: proposal
zero-based draw index: 30 of 137
strict attempts: 14/14 ended in pair_cap fill failure
last attempt: succeeded only after ignoring voids -> rejected_worlds += 1
state constraints: seat 2 void in clubs; seats 1, 2 and 3 each club pair_cap=0
whole replay total: rejected_worlds=1, impossible_worlds=0, pair_cap=263
```

This does not show that the state has no legal world: the real deal is one.
The committed sampler finds one void-feasible suit-count matrix per attempt,
then gives that matrix only eight randomized greedy card fills. Exhausting
those eight does not prove the matrix—or the world—is impossible.

The current dirty `mcbot.py` moves that same eight-try fill into every leaf of
the suit-count search. That is not ready to commit:

- it is still not complete, because each count matrix receives only eight
  randomized greedy card-order attempts;
- it creates a combinatorial performance failure. The exact replay had not
  passed proposal draw 54 after more than 90 seconds, and individual successful
  draws accumulated 23,868–73,458 failed matrix fills; the committed sampler
  replays all 161 worlds in about 0.3 seconds;
- `reject_cause["pair_cap"]` changes meaning from failed assignment attempts to
  every rejected count-matrix leaf and becomes enormous even on success; and
- it consumes a radically different RNG stream before each returned world.

Please replace this with a bounded card-code allocation for each suit (an exact
backtracking/DP assignment over at most two copies per code and receiver
quotas is the direct formulation), or otherwise prove both completeness and a
runtime bound. Add the exact fold/draw regression against the pre-fix behavior
first, then require zero rejects plus a sampler runtime regression. The
two-machine corpus presence/digest preflight remains independently open. Any
sampler fix still quarantines all seven pre-fix shards and requires all eight
to rerun from one clean HEAD.

## Required return packet

```text
STATE: READY_FOR_CODEX_GATE | BLOCKED
root cause and bounded deterministic reproduction:
rejection fold / draw / cause / world constraints:
fix or protocol decision, with why the estimand is unchanged:
regression test and targeted/full-suite results:
HEAD / origin / dirty state on Mini and Air:
status of the seven pre-fix shards (retained or quarantined):
eight replacement shard paths and manifest-identity audit, if rerun:
sampler/work/replay/protocol counters:
strict aggregate command and result, only if all eight validate:
CALIB/REPORT confirmation: unscored
```

Stop after returning this packet. No unrelated cleanup, sampler research,
training, CALIB scoring or online duel is authorized by this incident.
