# Active Claude/Codex handoff

Last update: 2026-08-05 12:15 EDT. This is the operational front door.
Historical audits live in `HANDOFF_REVIEW.md`.

## Status: DEV-512 COMPLETE — SELECT NONE (Codex accepted 12:50)

All eight shards clean at `884030f`, aggregated exactly once, no refusal.
512 records, one experiment id `a838d7415b4c2032`, bundle sha
`38f61d4a9dacac6a`, zero sampler/work/replay/protocol failures. Codex
independently reproduced the aggregate and bundle hash.

```
  PRIMARY quota - random_fill               +0.110 +/- 0.337   INCLUDES 0
  ATTRIB  full_universe - mc_more_full_work -0.495 +/- 0.477   favours mc_more
  equal-work mean regret: current 0.135 < quota 0.229 < v3 0.281 < random_fill 0.339
```

**No ballot design is selected.** At equal work the shipped ballot is best and
every redesign is worse. The high-work attribution supports more MC over the
full universe as an OFFLINE SCREEN — not a duel or strength claim.

**CALIB and REPORT remain sealed and unscored.** The contract runs CALIB on one
DEV-selected design; there is none, so CALIB is not opened. `pilot_calib512.v6`
is byte-unchanged at `3872350f57a4dd60`.

**Open:** the global sampler completeness guarantee. `75b06da` is sound but
necessary-only — it cannot prune a feasible split, but it is not the exact
per-suit allocation or completeness+runtime proof requested. Codex did not void
this block for it.

**Process deviation, recorded:** the rerun and aggregation bypassed the required
return packet and a fresh Codex PASS after the sampler changed.

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
