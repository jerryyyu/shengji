# Opt-in W32 serving

Implementation and engineering measurements for [#300](https://github.com/jerryyyu/shengji/issues/300).
**Not deployed.** Production remains `mc-s0-report-lcb`; `fly.toml`, its VM
size and the Docker entry point are unchanged. Serving this backend does not
inherit a new strength claim from the Torch checkpoint.

## What runs

Export a reviewed MLP checkpoint once, with Torch available:

```sh
PYTHONPATH=server python server/scripts/export_cwv_numpy.py SOURCE.pt MODEL.npz
```

The export refuses overwrites and publishes atomically. It stores float32
weights, encoder/config metadata and the original checkpoint SHA. A potentially
large training-population manifest is retained in the original checkpoint,
referenced by SHA in the export instead of copied into every room.

Serving uses NumPy, not Torch. The real registry dispatches `.npz` checkpoints
to the existing W32 consumer: W32/K4/N30/R300, static MLP encoding and successor
reuse. Each bot owns its RNG and counters; immutable weights are shared across
bots and deep-copied turn snapshots. A package has its own policy identity;
do not reuse the original Torch checkpoint's policy name.

The public-history helper was extracted from the training module. New encoder
identities cover the new file. A narrow compatibility rule admits old **full**
encoder identities only when the history computation/constants/dependencies
still match and reversing that one import recreates the original closure.
Other source drift is refused; source-move acceptance is not a general bypass.

## Configuration and rollback

For an isolated server first, set these **before Python starts**:

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export SHENGJI_FAST=1
export SHENGJI_CWV_SHORTLIST_CKPT=/data/models/MODEL.npz
export SHENGJI_CWV_SHORTLIST_WORLDS=32
export SHENGJI_MODEL_SEARCH_CONCURRENCY=1
```

Obtain the exact registered name, rather than constructing a guessed hash:

```sh
python -c 'import os; from shengji.ai.registry import register_cwv_shortlist_policies; print(register_cwv_shortlist_policies(os.environ["SHENGJI_CWV_SHORTLIST_CKPT"], [32]))'
```

Set `SHENGJI_BOT` to that name only in the explicitly approved deployment.
Mount the immutable package at the configured path; keep the source checkpoint
and previous package. No Torch installation or model retraining is needed in
the runtime image. The compiled engine must be built for that image's Python.

Across rooms, NumPy searches queue behind a shared per-event-loop admission
limit (default 1, configurable 1–8). A queued cancellation does not start work;
running cancellation drains the isolated worker before releasing its slot.
The limit is validated and bound when the server imports, before rooms are
accepted; changing it requires a restart. Cancellation takes precedence over
a secondary worker failure so enclosing timeouts retain their semantics.
`model_search` log events expose queued/running/completed/error/cancelled and
10-second heartbeats, with no hidden cards or exception messages. Errors leave
the live game/RNG untouched and display a generic room error; they never
silently switch to another policy. Existing stale-turn ownership checks remain.

Rollback means selecting `SHENGJI_BOT=mc-s0-report-lcb` and removing the
`SHENGJI_CWV_SHORTLIST_*` opt-in variables for the next server start. Keep the
package for diagnosis. Game rooms are in-memory: drain active rooms and notify
players before any restart. Neither this document nor its PR authorizes a
production restart, deployment or VM resize.

## Measurements — September 8, 2026

One retained ABC MLP, SHA `3f00500c5bf207e51d50ccd59a7b78c4f917b0a8adf3f39b31e660f81baa84ec`.
Compact export SHA `171893bd2bb5cb21add67ffec985c0d4fd53686fa6348d9e2ad8e7141429975b`.
Saved states SHA `fb44e3d946bdc80c6ba0859e70f61c7d75c3507f675bb5186799153acc57984c`,
indices 0/2/6, seeds `89260904 + index`. Batch size 128; compiled engine.

| Saved decision | Mini / NumPy | Mini / Torch | Linux / NumPy, 1 CPU quota |
|---|---:|---:|---:|
| Wide lead, 6,958 legal actions | 11.59 s | 2.52 s | 30.20 s |
| Follow, 3 legal actions | 0.168 s | 0.157 s | 0.331 s |
| Follow, 4 legal actions | 0.063 s | 0.065 s | 0.107 s |

All three plays, report-fold fields and final RNG hashes matched across these
measurements; all input snapshots remained unchanged. NumPy probabilities are
computed with float64 math and exact-erf GELU, rather than Torch float32:
**this is not a proof of bit-identical rankings/actions on every state**.
Near ties can differ. The Torch path was faster on the wide fixture.

Removing the unused population metadata reduced Mini peak RSS across these
three decisions from 397.8 MB to 115.4 MB. Linux peak process RSS was 104.5 MB
(systemd cgroup peak 82.3 MiB, zero swap). The Linux process succeeded inside
`MemoryMax=512M`, `CPUQuota=100%`, `TasksMax=32`; Python 3.12.12, production
locked dependencies, native engine, Torch import actively blocked. Perf was
otherwise compute-idle, but Claude's Run G rsync was active: label these Linux
timings **I/O-overlapped**, not an uncontended latency baseline. This measures
one search process importing the API,
not a full WebSocket load test or Fly shared-host latency guarantee.

Private measurement inputs/package: `/opt/w32-serving-measure.OtpaS5` on Perf;
Mini export directory `/private/tmp/w32-numpy-serving-measure.FiRNhL`.
Reproducer: `server/scripts/benchmark_cwv_serving.py`; the 180-second limit is
only for the diagnostic process, not a timeout that abandons server workers.

### Concurrent rooms and real WebSockets

A separate, uncontended Perf probe used the repaired serving source
`fa58c36638940c76b355fd88a034acf966b1bc8f`, the same package/states and locked
Python 3.12 runtime. It bound Uvicorn only to an ephemeral `127.0.0.1` port;
real WebSocket clients queried rooms while the actual W32 worker searched.
Two rooms shared immutable weights, private RNG and turn snapshots. Both
normal turns committed through the real engine. A changed seat owner refused
the stale prepared turn; an injected worker failure produced the generic
room error and left the live RNG unchanged.

| Measurement | Result |
|---|---:|
| Wide turn / ordinary turn after admission | 30.87 s / 0.38 s |
| Real WebSocket room queries during searches | 579 |
| Mean / maximum WebSocket response | 1.80 ms / 62.88 ms |
| Peak process RSS | 119.0 MB |
| Unit CPU / wall | 33.04 s / 33.27 s |
| Maximum simultaneously running searches | 1 |

The process exited successfully under the same 512 MB / one-CPU bounds;
Torch was absent. Queued and running heartbeats appeared at 10, 20 and 30
seconds. **One search slot means head-of-line waiting:** the ordinary room
waited about 31 seconds for the wide room. Responsive sockets do not imply
short move latency. The cap bounds active CPU work, not an unlimited number
of room snapshots; larger room counts and higher concurrency need their own
memory/load check before configuration changes.

Reproducer: `server/scripts/benchmark_cwv_rooms.py MODEL.npz STATES.json`.
Private Linux root `/opt/w32-room-measure.6gYdNn`; systemd unit
`w32-room-measure-20260908.service`. Retained journal on Mini:
`~/shengji-archive/2026-09-08/w32-fly-serving/room-probe-journal.txt`.
This is a production-dependency Linux process, **not the built Docker image**
or a public Fly deployment. It exercises actual room search/commit and socket
queries, not a full human lobby-to-round session. No Docker runtime was
available on the measured host; the intended-image check remains below.

Before deployment: review the complete source, test concurrent/stale/error
rooms in the intended image, approve acceptable wide-action latency, and obtain
Jerry's explicit deployment approval. No further teacher/provider run is
required for this engineering change.
