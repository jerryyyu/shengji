# Lead cache lookup before cloning — implementation checkpoint

Implementation in `codex/cwv-cache-hit-before-clone`; not yet reviewed or adopted.
Prepared lead validation resolves the submitted action before cloning when
the cache has entries. Hits return the same cached leaf, preserving ordered
accepted-card keys, LRU behavior and every original model row. Misses use the
unchanged afterstate path; follows and unprepared caches are unchanged.

Every submission still validates, including invalid throws which would
otherwise resemble a cached component. Exact Round roots only use the shortcut.
The fixed root/world lifetime remains the existing cache contract.

Validation: 39 focused tests pass in pure and native modes. New tests prove
that a hit does not construct an afterstate, an invalid submission still
refuses, and the complete natural lead ballot matches the old unprepared path
on finished state, score, message and model-input bytes. Existing integration,
double-shortlist and prepared-context tests pass. One implementation-detail
test now expects the avoided afterstate call, retaining its validation-count
assertion.

Exploratory timing on a contended Mini, native explicitly activated:
`tests.test_world_shortlist.play_state`, 629 legal actions, 596 hits and 33
completed leaves per decision, 20 repetitions per arm. Reference is the class
from base HEAD 338b1402, with its existing prepared validation enabled.
Counterbalanced reference/candidate/candidate/reference wall seconds:
0.081651 / 0.041459 / 0.041411 / 0.078290. CPU closely tracks wall.
This is only a high-reuse cache-component signal, not an isolated or end-to-end
screening speedup. No memory claim. No live jobs paused or changed.

## Isolated W32 consumer qualification

Completed on Perf in `/root/preclone-cost.vTzp3e`, using the existing diagnostic
with `--optimization preclone-hits --repetitions 2`. Seven retained snapshots
SHA `fb44e3d946bdc80c6ba0859e70f61c7d75c3507f675bb5186799153acc57984c`;
W32/N30/K4/R300, static Torch, batch 128, native engine, one numerical thread.
Both arms keep prepared validation, every model row and identical batching.
The explicit `preclone_hits=False` control preserves the old clone-first path.

| Checkpoint | Reference wall / CPU | Candidate wall / CPU | Wall reduction |
|---|---:|---:|---:|
| h256 `fc73c0f4` | 13.9696 / 13.9672 s | 11.2224 / 11.2215 s | 19.7% |
| h1024 `34e6fa0f` | 26.8625 / 26.8577 s | 24.1658 / 24.1635 s | 10.0% |

All 28 pairs exactly match score-byte hashes, model batches, chosen actions,
shortlists, report evidence, work/reuse counters and RNG; roots remain unchanged.
Shared-process peak RSS is 412656 / 425632 KiB respectively, equal between arms;
no memory saving claim. Timing includes the full decision consumer on these
saved states, not full-game scheduling or an all-rank throughput forecast.
The wide lead dominates the panel; low-reuse states need not benefit.

The exact current screen queue/controller and children were stopped for 82.76s;
all 19 process identities resumed in finally, with parent 817226 verified running.
No live source, completed results or deployment changed. Result/config/individual
rows are retained remotely and copied to
`~/shengji-archive/2026-09-12/preclone-qualification/`.

Next: one source+qualification review, integrate approved optimizations, then
verify full-window consumer adoption without duplicating compatible reference
results. This gain is incremental to existing static encoding and prepared
lead validation; do not count those previous savings again.
