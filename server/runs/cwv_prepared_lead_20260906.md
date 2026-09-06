# W32 prepared lead validation

Decision-preserving engineering for #248. Separate from the live selective-depth
screen (#285) and PT-Luna games; neither executing checkout is changed.

## Why this cost remains

The fixed saved wide lead has 6,958 submitted actions and 32 sampled worlds:
222,656 model rows. Existing successor reuse already reduced finished leaves to
832, but identifying those duplicates still builds and validates every submitted
afterstate. Multi-component throw validation repeatedly scans the same three
opponent hands for a higher single, pair, or tractor of the required length.

The unprofiled reference decision measured 7.477 s, including 7.155 s ranking.
Its separately instrumented cProfile run took 16.049 s: `validate_lead` had
9.397 s cumulative time and neural linear operators 0.824 s. These are overlapping
instrumented costs, not additive wall shares or a promised speedup ceiling.

Evidence and fixed snapshot provenance:
[profile and prototype record](https://github.com/jerryyyu/shengji/issues/248#issuecomment-5562288378).
Retained local artifacts: `~/shengji-archive/2026-09-06/w32-ranking-profile.td1ljS/`.

## Implementation boundary

Prepare opponent facts once per fixed root/world cache. For each effective suit
and component pair length, cache the highest opponent single/pair/tractor top.
Then perform the original hand-membership, uniform-suit, decomposition, strict
comparison and lowest-beatable-component checks for each submitted action.
Ordering and hand snapshots bind the facts; mismatches fall back to the ordinary
validator. Facts and leaf caches are bounded and belong to one world instance.

`WorldSuccessorCache` explicitly supplies the context through `afterstate` to
the first `Round.play`. Only trusted determinized rollout clones accept it.
The native `round_play` entry accepts the same private keyword and forwards a
supplied context to the Python method, where the trust and binding checks live.
Native leads already used that Python path. Ordinary `Round.play`, production
policy defaults, later simulated plays and follows keep their previous path.
No global engine patch or inspection of saved native-dispatch internals is used
by the code; the native extension must be rebuilt for this source revision.

All root afterstates are still constructed and validated. No candidate is pruned,
no score row is deduplicated, batch sizes/order and precision do not change, and
no model or search budget changes. Computing accepted keys before cloning is a
possible later optimization, **not part of this change**. Neither are prepared
contexts in production rollout continuations or data generation.

## Existing hypothesis evidence, not a shipping benchmark

A private single-process prototype compared seven existing snapshots through
the actual W32 consumer. Scores, batches, shortlist decisions, report, RNG,
inputs and reuse counts were identical in all seven pairs. The wide-lead pair
measured 7.672 s reference and 4.158 s prepared (1.845x). Small-state timings were
mixed, including one regression. Mini was contended; these observations justify
testing the implementation, not a whole-game or isolated speed claim.

The prototype temporarily patched the validator within its private diagnostic
process. That mechanism is deliberately absent from the shipping implementation.

## Validation and next measurement

Focused tests compare ordinary/prepared acceptance, exact refusal and penalty
messages, full engine state, finished leaves/tensors and cache accounting. They
cover lead structures, trump/no-trump, equal ranks, changed-world fallback,
invalid cards, untrusted injection, follows, terminal and eviction behavior.
The cache-to-engine witness must turn red if the preparation is disconnected.

At the prepared implementation, the focused lead/cache/native-play suite,
including double-shortlist consumers, passes 67 tests in pure and compiled
modes. CI found that eager preparation accessed `root.trick` on an existing
lightweight double-shortlist test root. Preparation now falls back when engine
decision metadata is absent; the existing fraction/saturation consumer witness
passes unchanged. A separate in-memory mutation that strips
the context at the `afterstate` boundary leaves the output equal but turns the
actual repeated-root consumer witness red (`context.calls`: 0 rather than 2).
This proves the test checks the optimization wiring, not only output equality.
The full neural W32 A/B described below is still pending; do not substitute the
earlier prototype timings for that check.

The repeatable actual-consumer A/B uses the existing ordered seven-snapshot
panel and ABC checkpoint. Each state keeps W32/K4/N30/R300, static MLP encoding,
batch 128 and successor reuse. Reference/prepared order alternates by state and
repetition. Completed measurements survive interruption; failed measurements
remain failures and are not automatically retried. No new games, labels or
outcome-dependent state selection are involved.

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -B -m scripts.cwv_prepared_lead_probe \
  --states-json SAVED_SEVEN_STATES.json --checkpoint ABC.pt \
  --out NEW_MEASUREMENT_ROOT --repetitions 3 --decision-seconds 60
```

The probe's reference/prepared factory switch is confined to one single-thread
diagnostic process. The code exercised beneath it uses the explicit context.
Require identical ordered neural scores, batches, full shortlist, report, chosen
action, work counts, RNG state and unchanged inputs before any speed claim.

Run the wall A/B in an isolated host window, not beside Luna, the selective-depth
screen or Run E. The initial bound is at most 42 fixed decisions, three repeats
of seven matched states, 60 seconds per decision, inside a five-minute / 4-GiB
process-group supervisor. Publish every result and
separate wide-lead benefit from no-reuse follow behavior. This is not a gameplay
strength comparison or permission to change an executing job.
