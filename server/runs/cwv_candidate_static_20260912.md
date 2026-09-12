# History-free candidate encoding — 2026-09-12

`cwv_eval.score_candidates(history=False)` now uses the existing validated
static encoder instead of constructing history that it immediately discards.
`history=True` retains the reference builder. Candidate application, terminal
overrides, array types/shapes/order and model batch sizes are unchanged.

Tests: nine focused tests pass in pure and native modes, covering multi-action
lead/follow/late ballots for v1/v2, exact arrays and scalar fields, reference
history routing, history-constructor avoidance and terminal handling. Related
static/search-facing tests: 42 passed; training tests: 10 passed.

## Isolated component measurement

Perf native engine, one Torch/BLAS thread. Seven retained DEV snapshots, SHA
`fb44e3d946bdc80c6ba0859e70f61c7d75c3507f675bb5186799153acc57984c`,
at most eight legal candidates per
state: counts 8/8/3/8/1/8/4. Ten repeated passes per timing; warmup excluded.
Counterbalanced reference/static/static/reference, identical consumer call.
All 3,200 candidate encodings matched returned array bytes and scalar fields.

| Encoder | Reference wall (two passes) | Static wall (two passes) |
|---|---|---|
| v1 | 0.2463 / 0.2461 s | 0.1783 / 0.1815 s |
| v2 | 0.3040 / 0.3043 s | 0.2309 / 0.2212 s |

CPU tracked wall closely. About 27%/26% lower component time (v1/v2), **not a
whole-training speedup**. Process high-water RSS was 253,636 KiB; both arms
share a process, so this does not establish memory savings. The finite panel
does not prove an all-rank throughput forecast.

Artifacts and reproducible probe: `/root/candidate-cost.SjVwIv/` on Perf;
archived locally under `~/shengji-archive/2026-09-12/candidate-static-qualification/`.
Source and probe hashes are recorded in result.json. Screen/controller/worker
identities were stopped for 3.69s and all 19 resumed; worker health verified.
No live source/output or production deployment changed.

This complements, but does not double-count, Claude's candidate-pass forward
batching work in #342. Integrate both before measuring total reporting time.
