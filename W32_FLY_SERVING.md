# W32 serving

Implementation and engineering measurements for [#300](https://github.com/jerryyyu/shengji/issues/300).
**Production default since September 8, 19:53 UTC, explicitly authorized by Jerry.**
Ordinary rooms use `mc-shortlist-fd6bb411-w32-r55d379a3` without an access code.
This was an environment-only update on the existing release-20 image; VM size,
volume and Docker entry point are unchanged. Serving this backend does not
inherit a new strength claim from the Torch checkpoint.

## What runs

Export a reviewed MLP checkpoint once, with Torch available:

```sh
PYTHONPATH=server python server/scripts/export_cwv_numpy.py SOURCE.pt MODEL.npz
```

The export refuses overwrites and publishes atomically. It stores float32
weights, encoder/config metadata and the original checkpoint SHA. A potentially
large training-population or exposure manifest is retained in the original
checkpoint, referenced by SHA and canonical byte count in the export instead
of copied into every room.

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

## Selected v2 package — deployed

Jerry selected **A+C+D+E+F2 v2 `3cd27716`** for the production default.
It is the gameplay-supported all-rank teacher, not a new CE winner. Its
520-deal all-rank result and ABC's older 256-deal rank-2 result are different
populations: they do **not** establish a head-to-head improvement over the
previously served ABC model.

The source is Mini's
`~/.claude/jobs/68f9c8bd/tmp/train-out/cwv/runACDEF-v2/best.pt`:

| Binding | SHA-256 |
|---|---|
| Original checkpoint file | `3cd277160322b30e9a61d5d83cb7fb6bceac6887ab1e899b98a42f15b259d600` |
| Logical model state | `79ea14f2c0d1ff6807e615038552669f8627a1e23bd199cc01966545a3d749fb` |
| Compact NumPy package | `fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9` |

All six learned arrays are unchanged by export. Model shape is
833 → 512 → 256 → 204 (public input 561, encoder v2). Removing the unused
exposure ledger reduced the exported package from **6,497,395 to 2,284,341
bytes**; the source checkpoint and full ledger remain intact. This changes
package identity, not the learned parameters or search recipe.

Qualification used the **existing release-20 image** below, offline on Perf
with no network, one CPU and 512 MB. Three fixed saved states (indices 0/2/6,
6,958/3/4 legal actions) completed without Torch. The compact package matched
the source Torch checkpoint's final moves, report folds and final RNG on all
three. Compact decision walls were **29.697 / 0.403 / 0.151 seconds**, maximum
process RSS **98,168,832 bytes**, and snapshot-copy wall **0.00086–0.00617 s**.
The ledger-carrying package reached 127,963,136 bytes RSS in a separate process.
These are small engineering observations, **not** universal numeric parity,
a gameplay screen, a controlled throughput A/B, or new public Fly latency.
Torch used Mini/native Python 3.14; NumPy used Linux/native Python 3.12, so the
comparison supports these outputs, not a backend speed ranking.

### Explicit v2 dependency check (#307 remains open)

The legacy checkpoint identity omits the two v2 implementation files. Do not
silently widen that loader's acceptance or claim this qualification fixes it.
For this specific rollout, the compensating binding is the **immutable image
digest plus the exact package SHA**, with these image source hashes checked:

| Image source | SHA-256 |
|---|---|
| `rl/encode_versions.py` | `214806d52794f737826bda7d310dcdcdf497dca7a1d3c08c470e754e516a18f3` |
| `rl/value_afterstate_v2.py` | `566432ee53860d925667e9ab93fab1a3fd32cab6ff71af2f5da18186fe2d52dd` |

The training commit is `fda20f64feb1a2b16faddf83c8778f2933cd52ca`.
Its v2 arithmetic versus serving's extraction/import moves produced identical
public/history/world/perspective tensors on **52 already-opened FIT roots ×
4 seats**, after one legal action. This check shares the already-admitted v1
builder; it is not proof of an arbitrary historical runtime's equivalence.
A different serving image needs a new dependency qualification: the legacy
identity alone is insufficient. No archived checkpoint or training run changed.

Reproducible scripts and raw engineering receipts are private at
`~/shengji-archive/2026-09-08/w32-selected-serving.zXBQED/` (weights, encoder
qualification, Mini Torch and Linux NumPy logs). Two attempted host-side Linux
Torch probes stopped during setup (ABI mismatch, then Torch absent); neither
reached a decision, and neither is counted as a successful measurement.

**Switch completed:** PR #313 passed review and CI and merged at `049b1e7e`.
The exact image, package and v2 source hashes were checked on Fly, and health
showed zero rooms before the environment-only update. Both the global and
test-room checkpoint paths now select `/data/models/w32-fd6bb411.npz`; the old
ABC package remains available. Post-update health passed and a normal `Room`
constructor loaded the exact package, encoder v2 and NumPy backend without
Torch. Machine resources, image, volume and live Run I were unchanged.
Before/after machine receipts are in the private qualification directory above.
Rollback is the same image with `SHENGJI_BOT=mc-s0-report-lcb`.

## Historical ABC public Fly check — release 20

PR #310 passed source review at `a1080700` and all five CI checks before the
September 8 deployment. The tested registry image is
`sha256:b8f48f41149d8a27225e7a44260b72b03475dbdf99ba7398c56167682afd19e5`.
Fresh health showed zero rooms before the restart. The same single
`48e7e35a9597e8` machine, 512 MB/shared CPU, and existing volume were retained.
The release-19 rollback digest in `DEPLOY.md` remains available.

The served package `171893bd` was exported from checkpoint `3f00500c`
(A+B+C MLP, encoder v1), not the later selected teacher `3cd27716`
(A+C+D+E+F2, encoder v2). Full source/export SHAs appear below. These latency
measurements belong to the ABC package; neither newer-checkpoint latency nor
its all-rank strength result transfers automatically to this engineering test.

The public socket smoke completed one designated W32 round (`OPMA`) in
**604.808 seconds**, including normal deal/pacing and 22 human-seat actions.
It covered lobby, deal, declaration, burial, play, round end and explicit leave.
Invalid access-code refusal, the two-test-room cap, and ordinary-versus-W32
room markers passed. The concurrent ordinary lobby was queried but did not
play a public test game, avoiding ordinary training-log contamination.

| Live Fly measurement | Result |
|---|---:|
| Bot play turns | 63 |
| Compute median / nearest-rank p95 / maximum | 5.358 / 27.763 / 122.273 s |
| Sum of logged bot play-computation wall / round wall | 570.259 / 604.808 s (94.3%) |
| Ordinary-lobby socket queries during W32 play | 20, all successful |
| Query mean / maximum, including network | 91.3 / 155.8 ms |
| Server process high-water RSS | 99,592 KiB |
| Model worker errors / stale discards | 0 / 0 |

**This is usable as a restricted engineering test, not a polished public mode.**
The UI's approximately-30-second wide-move warning is not a cap: a live move
took over two minutes, and 33 of 63 bot turns took more than five seconds.
The service stayed responsive, but typical search cost consumes most of a round,
and searches in different test rooms queue behind one another. Keep access codes
restricted and improve typical as well as worst-case latency before wider
availability. No strength or broad reliability claim follows from one round.
No resize or additional replicas were introduced.

All 401 retained records carry `training_excluded: true` and policy
`mc-shortlist-171893bd-w32-r55d379a3`. The 709,314-byte log remains on Fly at
`/data/shortlist-tests/OPMA.jsonl`, with a private copy at
`~/shengji-archive/2026-09-08/w32-fly-serving/fly20-OPMA.jsonl`, SHA-256
`8012f7090746fbeef16313d50e23e0d3357444855b32c084cb8ab8fefcc1f017`.
No private cards or access code are committed. Explicit leave closes the clients;
the disconnected game room uses the existing five-minute reclaim grace before
automatic removal, not an operator restart.

## Configuration and rollback

For the current global default, set these **before Python starts**:

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export SHENGJI_FAST=1
export SHENGJI_BOT=mc-shortlist-fd6bb411-w32-r55d379a3
export SHENGJI_CWV_SHORTLIST_CKPT=/data/models/w32-fd6bb411.npz
export SHENGJI_MODEL_SEARCH_CONCURRENCY=1
```

Optional excluded engineering rooms additionally use `SHENGJI_W32_TEST_ROOMS=1`
and `SHENGJI_W32_TEST_CKPT=/data/models/w32-fd6bb411.npz`.
Supply `SHENGJI_W32_TEST_ACCESS_KEY` separately through the deployment secret
store: a randomly generated 32–128 character code, never committed or placed
in a URL. `fly.toml` defaults this separate test-room availability to `0`;
it does not restrict ordinary rooms' W32 default.

Visit `/?test_shortlist=1` to reveal the test controls, check the initially
unchecked W32 option, and enter the access code. The URL reveals controls,
not authority. Only the create-room request can select W32; joining or claiming
an existing room cannot change its policy. Invalid codes, missing packages,
disabled availability, and the two-test-room limit refuse creation with a
generic error; none silently creates a fallback room. Ordinary creation
remains unchanged. Test lobbies and games display an experimental badge.

Test logs go to `/data/shortlist-tests`, outside `/data/logs`, with
`experimental_policy`, the actual recipe identity and `training_excluded`
markers. Keep these engineering trajectories out of ordinary human training
data. The access code is not persisted by the UI or written to room logs.

Mount the immutable compact package at the configured path; keep the source
checkpoint and previous package. No Torch installation or model retraining is
needed in the runtime image. The compiled engine must be built for that image's Python.

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

To disable further test-room creation on the next start, set
`SHENGJI_W32_TEST_ROOMS=0`; keep `SHENGJI_BOT=mc-s0-report-lcb`. For a runtime
regression, restore the recorded pre-deploy image and configuration, not just
the flag. Keep the package for diagnosis. Rooms are in-memory: inspect fresh
`/healthz` occupancy and wait for a quiet window before any planned restart.
Jerry's scoped goal authorizes this gated deployment/test, not interruption of
active games, a global policy switch or a VM resize. Coordinate timing with Claude.

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

Before deployment: review the complete source and test concurrent/stale/error
rooms in the intended image. Record that exact image, the pre-deploy image and
configuration, and the fresh zero-room check. Then test lobby → game → completed
round through real sockets in a designated test room, alongside an ordinary
room. Keep observed usability/cost separate from strength claims. No further
teacher/provider run is required for this engineering change.

### Intended image and complete socket rounds

PR #310's image was built from this Dockerfile on otherwise-idle Perf:
image ID `95d8a8ff8336f0fa56320a4b3a30f12475405de4680a1334b6da9f9b2ccf5a71`,
295,324,332 bytes uncompressed. The runtime imports no Torch and activates the
image-built native extension. Its unchanged default `uv run --no-dev
shengji-server` entry point starts successfully with the gate disabled and
health reports MC-LCB, native enabled, zero rooms.

Under a one-CPU quota, 512 MB memory limit and no swap, the same saved-state
room diagnostic passed inside this image: wide search 28.109 s, ordinary
follow 0.442 s after admission, 109,445,120-byte peak process RSS. All 522
socket queries succeeded (mean 2.35 ms, maximum 42.70 ms). Stale-turn refusal,
isolated worker-error handling and one-slot admission passed. The ordinary
follow's queue-inclusive completion was 28.551 s: queue time is not inference time.

`server/scripts/check_cwv_test_rooms.py --ordinary-round` then drove two fresh
rooms through real create/add-bot/deal/declare/bury/play/round-end/leave
messages. It checked invalid-key refusal, the two-test-room cap, and ordinary
versus W32 markers. The human-seat driver uses only its own hand/public trick;
no debug endpoint or hidden hand. Concurrent ordinary and W32 rounds completed
in 68.014 s and 82.360 s, including normal deal and move pacing; the container
cgroup memory peak was 103,243,776 bytes. These are two different random deals,
**not a paired speed or strength comparison**. No OOM or server defect appeared.

Two diagnostic setup failures preceded that check: the client initially
treated a nullable status message as a string, then a launch raced server
startup. The client was repaired and startup health checked; the server/image
was unchanged. Failed attempts and final journals remain available rather
than being described as a first-attempt pass.

Private Perf root `/opt/w32-fly-image.IvOawR`; units
`w32-fly-image-rooms-20260908` and `w32-fly-image-e2e-ready-20260908`.
Release 20 uses the registry digest of this tested image, without a rebuild.
For a public designated-room check, the script requires
`--allow-remote --url wss://shengji.fly.dev/ws`; omit `--ordinary-round` to
avoid putting synthetic gameplay into ordinary human logs. Supply the access
code via the environment, never an argument or committed file.
