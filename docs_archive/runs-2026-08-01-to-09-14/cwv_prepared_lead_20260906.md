# W32 prepared lead validation

Decision-preserving engineering for #248. Separate from the selective-depth
screen (#285) and PT-Luna games; neither experimental recipe is changed.

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

`WorldSuccessorCache` supplies the context only to the research `afterstate`
adapter. The adapter resolves the submitted throw against the fixed world, then
applies its accepted cards through **unchanged `Round.play`**. A failed throw
reduces to one component, which is cheap to validate normally; its original
penalty message is restored on the private clone. Standing throws deliberately
validate again. Subsequent simulated plays and follows keep their previous path.
No global engine patch, native dispatch change or checkpoint identity exemption
is used. `round.py` and `_fast.pyx` remain byte-identical to the PR base.

The first draft threaded a keyword through `Round.play`. A real saved-model
load caught that this changed the checkpoint-bound encoder identity, even though
the 67 engine/cache tests passed. That approach was removed, not excused by a
metadata rewrite or a weaker check. The narrowed adapter loads the untouched
ABC checkpoint and the older real-checkpoint integration test passes again.

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
including double-shortlist consumers and the real-checkpoint integration,
passes 68 tests in pure and compiled modes. CI found that eager preparation
accessed `root.trick` on an existing
lightweight double-shortlist test root. Preparation now falls back when engine
decision metadata is absent; the existing fraction/saturation consumer witness
passes unchanged. A separate in-memory mutation that strips
the context at the `afterstate` boundary leaves the output equal but turns the
actual repeated-root consumer witness red (`context.calls`: 0 rather than 2).
This proves the test checks the optimization wiring, not only output equality.
The full neural W32 A/B below is now complete at source `640f56d6`; its retained
measurements, not the earlier prototype timings, establish the result.

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

## Completed actual-consumer A/B — September 6

Executed exact source `640f56d6cd06f1ded8323f971667ca0a6445c8a1` on Mini after
the prior training and gameplay/screen processes ended. Strength F2 and Perf
Run E were left running and untouched. This replaces the proposed Strength
window with available Mini time; no extra capacity run was required.

All **21 matched pairs / 42 decisions** completed, with exact equality of
ordered neural score hashes, batch populations, shortlists, selected plays,
selection means, reports, work/allocation, reuse counters, RNG and unchanged
input states. Zero errors or cap stops. Three counterbalanced repetitions of
each original saved state; no new game/data collection or selected outcomes.
The fixed seeds reproduce the same sampled-world stream on both sides.

| Saved state | Reference mean wall | Prepared mean wall | Reference / prepared |
|---|---:|---:|---:|
| 0: 6,958-action lead | 4.74084 s | 2.55231 s | 1.8575x |
| 1 | 0.25019 s | 0.23403 s | 1.0690x |
| 2: small follow | 0.16492 s | 0.16842 s | 0.9793x |
| 3 | 0.14198 s | 0.13932 s | 1.0191x |
| 4: forced | 0.000153 s | 0.000153 s | 1.0040x |
| 5 | 0.06348 s | 0.06380 s | 0.9950x |
| 6: small follow | 0.05599 s | 0.05579 s | 1.0036x |

The wide lead retains all 222,656 scoring rows, 1,740 batches and 832 completed
leaves. Its three reference times are 4.73857/4.73558/4.74838 s; prepared times
are 2.52808/2.54269/2.58617 s. Mean CPU is 4.73122 versus 2.55223 s, consistent
with the wall reduction rather than waiting for another job. The remaining
positions are much cheaper and mixed, including a roughly 2.1% slowdown at
state 2. Three repeats cannot resolve small timing differences. This panel
does not cover the huge zero-reuse follows; no claim of universal improvement.

Summed measured decision wall is 16.25265 s reference versus 9.64144 s prepared
(1.6857x) for this **fixed, wide-lead-dominated panel**, not a population or
whole-game speedup. Supervisor wall was 27.553 s, exit 0; sampled process-group
peak RSS 322,306,048 bytes (27 one-second samples, not an exact memory peak).
No training or gameplay compute overlapped the window; ordinary OS/agent
processes remained. Python 3.14.3, torch 2.13.0, NumPy 2.5.1, one thread,
compiled play route verified. The five-minute / 4-GiB safeguards were unused.

Retained on Mini, including original inputs/checkpoint, every result, source
and runtime bindings, launch/supervisor receipts and log:
`~/shengji-archive/2026-09-06/prepared-lead-ab.miZGaz/`.
The supervisor is `run_bounded.py`; the unchanged reviewed driver is
`scripts/cwv_prepared_lead_probe.py`. Input SHA256
`fb44e3d946bdc80c6ba0859e70f61c7d75c3507f675bb5186799153acc57984c`;
ABC checkpoint SHA256
`3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
No automatic retry or extra model/engine verification replay beyond the stated
three benchmark repetitions; no multi-hour reconstruction.

Claude's exact-source PASS and all five CI successes are recorded on #286.
This result-only update changes no executing source and requires no new source
review. No claim that the optimization already helps generation or production;
those remain different consumers. Use this as a decision-preserving research
optimization, keeping policy-strength experiments and cost claims separate.
