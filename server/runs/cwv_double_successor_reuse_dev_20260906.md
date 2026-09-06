# Inner successor reuse for the double-shortlist diagnostic

Tracks [shortlist scaling #248](https://github.com/jerryyyu/shengji/issues/248).
This is an opt-in engineering change to the DEV-only extra-trick arm from
[PR #264](https://github.com/jerryyyu/shengji/pull/264). It does not change
production, the checkpoint, the root shortlist, depth, guidance fraction, or
MC-LCB selection/report semantics.

## Why this work precedes full paired games

At reviewed source `f21d60e1c64353630b3a33de6c6ebea9321af096`, a bounded
two-position probe found:

| Fixed fit position | Flat W32 | Uniform extra trick | Learned extra trick |
|---|---:|---:|---:|
| Opening lead, ordinal 0 | 0.743 s | 21.301 s | >150 s, timed out |
| Later follow, ordinal 12 | 0.261 s | 2.109 s | 108.325 s |

The diagnostic retained all six case receipts and continued after the single
timeout; total elapsed 4m45.63s, zero swaps. It measured decision latency on an
idle Strength Cloud with one numerical thread, not representative game cost.
The source-correct harness merged as opt-in DEV code; no paired-game arm had
started. [Full receipt and limits](https://github.com/jerryyyu/shengji/pull/264#issuecomment-5558463770).

The completed learned case evaluated 141,395 inner rows and finished 1,635
finalists. Its encoding/forward timer accounts for about 18.56 seconds and
heuristic finishes about 0.60 seconds. Inspection found that the inner loop
still rebuilt and completed every candidate successor, whereas root W32
already reused equivalent successors and model inputs. The timed-out case's
published work counters exclude its interrupted report stage; never divide
its partial counters by total elapsed to infer throughput.

## Exact optimization and checks

`--inner-reuse-successors` enables the existing 128-entry caches inside each
inner ranking wave. Every submitted legal action is still validated. Only
successors with the same engine-accepted action in the same parent/world can
share a finished leaf. Tensor keys include encoder, actual moving seat, and
exact leaf identity. Every original model row and forward batch boundary
remains present, including batches spanning parent boundaries. The default
heuristic must be exact-type matched; custom continuations retain their
original path. Finalist simulations copy cached leaves before mutation.

Policy counts remain separate from cache diagnostics. The cache toggle is
bound into the screen recipe/resume identity and defaults off. Neither a
fast helper nor equal final actions alone proves correctness: consumer tests
and the cost script compare ordered score bytes, batch shapes, root means,
report fields, chosen actions, RNG and unchanged input states.

Run the real-checkpoint A/B in an isolated window:

```sh
SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B scripts/cwv_double_shortlist_cost.py \
  --panel FIT_PANEL_FILE --checkpoint ABC_CHECKPOINT \
  --ordinals 12,0 --seconds 300 --inner-worlds 4 --out NEW_COST_ROOT
```

These are the same two fixed fit positions, reordered to complete the earlier
finishable follow first. No outcome/model-score selection, provider calls, or
gameplay-strength claim. Each timeout/error is retained and cannot count as a
parity pass; completed receipts reopen without rerunning a case. An outer
operational deadline bounds the total diagnostic. Do not edit published rows
to make the comparison pass. Wall measurements are descriptive, not a flaky
CI threshold.

## Strength experiment stays the objective

The next screen remains the 26 fresh mirrored-deal plan in
`cwv_double_shortlist_dev_20260906.md`: learned versus flat, uniform versus
flat, and flat versus production. Candidate interval `[91261164,91261190)`
was checked against current canonical windows and Run F's live registered
`[55260904,55268904)` window; recheck and register at launch. This note is not
a claim that registration or gameplay has occurred.

Higher compute is explicitly permitted for learning. There is no cost-matching
gate that can erase a strength result. Retain a two-hour operational stop per
arm, completed pair shards and honest partial readouts. The learned/uniform
arms share the guidance fraction and finalist depth, **not equal runtime**:
uniform does not pay exhaustive neural scoring. Even a strength gain would
not by itself make this expensive simulation policy deployable. No production
deployment or claim that per-world guidance solves imperfect-information
strategy fusion.
