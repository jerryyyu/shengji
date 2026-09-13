# Static-v2 widening cost: targeted gain, ordinary-screen result unresolved

This is a decision-preserving encoding experiment, not a strength screen.
The change converts the validated unseen-card plane to Python floats once,
instead of repeated NumPy scalar indexing, comparison and multiplication.
All counts are exact half-copies. It does not change the training encoder,
model, world sampler, validation rules, cache, search, or batch boundaries.

## Measurements

Perf Cloud, isolated, one worker/thread, same native binaries and Torch
checkpoint; control source `1dd66a0285c2530118d793991e945f9c2adae9d4`.
Treatment changes only `ai/cwv_static_encoding.py`. All times below are
unprofiled. Runs alternate A (control), B (treatment), B, A.

| Consumer | A0 | B1 | B2 | A3 | Mean comparison |
|---|---:|---:|---:|---:|---|
| Wide-follow original 1,024-row prefix | 0.186516 s | 0.163972 s | 0.160721 s | 0.180146 s | 0.183331 → 0.162347 s; **11.45% lower** |
| Three ordinary mirrored clusters | 83.1331 s | 85.2865 s | 84.5493 s | 84.0753 s | 83.6042 → 84.9179 s; **1.57% higher**, no demonstrated full-screen gain |

The prefix is the original first eight 128-row model batches of world 0 at
seed 13561373, rank 10, mirror 1, seat 3. Its complete legal universe has
379,753 actions. It is not a complete decision: do not project the prefix
improvement to full-screen wall time. Ordinary cached positions have a very
different cost distribution. These four measurements are not a population CI
or proof of an ordinary-screen regression.

The attribution profile, separately instrumented, measured 0.270 s in encoding
versus 0.018 s in network forward for that prefix. Cumulative times overlap.
Native activation was verified (`Round.play is fast._fast.round_play`); Python
fallback frames are expected for states outside the trusted-rollout guard.

## Correctness

- All four prefix runs have identical worlds, score/mean hashes and eight
  128-row batches; root and bot RNG remain unchanged.
- Every non-timing field in all three full-consumer shards matches across
  all four arms: decisions, reports, scores, counts, seeds and outcomes.
  The comparison excludes only the named shortlist and decision wall/CPU
  fields and the three per-mirror timing fields; it does not drop whole records.
- 58 focused static/fused/evaluator tests pass. A new direct witness checks
  every unseen count against `Memory(own_kitty=False)` for all four seats,
  including banker, covers counts 0/1/2, and checks public tensor bytes.

## Evidence and disposition

Mini archive under `~/shengji-archive/2026-09-13/`:

- `wide-follow-prefix-input/codex-wide-follow-widen-{a0,b1,b2,a3}.json`
- `codex-static-widen-abba-20260913/{A0,B1,B2,A3}/`: full shards,
  timing receipts, original configuration and executing-source identities.

Remote copies remain on Perf under `/root/` with the same run directory name;
the prefix receipts are `/root/codex-wide-follow-widen-*.json`.
General profiling is tracked in issue #208. No deployment or live-job changes.

This small candidate is qualified for tensor/decision parity and has a
repeatable gain on the retained wide-follow prefix. It is **not** evidence
that the remaining screen-performance goal is solved. Review the narrow
change with the negative ordinary-screen result visible before adoption.
