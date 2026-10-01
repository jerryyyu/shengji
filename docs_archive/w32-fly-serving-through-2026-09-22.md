> **ARCHIVED 2026-09-22** (Jerry: "lets archive ... lets keep a high bar for these top level file quality and updates"). Moved from `W32_FLY_SERVING.md` unchanged below this line. The serving record now lives in `DEPLOY.md` (releases, gates, rollbacks, `/healthz`) and in `server/shengji/train/pv_search_policy.py` / `cwv_shortlist_policy.py` docstrings for the served modes; release 28 is the deployed package, release 29 (pv-search) is prepared.

# W32 serving

Implementation and engineering measurements for the NumPy serving path.
**Production since September 8, explicitly authorized by Jerry at each step.**
Check live `/healthz` for the deployed policy; it now also reports the prior's
SHA, threshold and top. Release records with images, digests and rollback
environments are in `DEPLOY.md`.

## Release 28 (September 16): the JS-M1 joint model as one package

`SHENGJI_BOT = mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff`, with
`SHENGJI_CWV_SHORTLIST_CKPT` and `SHENGJI_CWV_PRIOR_CKPT` both naming
`/data/models/js-m1-0d17fd03.npz` (SHA `0d17fd03…`), `SHENGJI_CWV_PRIOR_SHA256`
pinned, threshold 1,000, top 256, hybrid bury with the 2 s budget. The package
is a v2 NumPy export (`server/scripts/export_cwv_numpy.py`) that carries the
residual trunk, the outcome head and the policy head; `cwv_numpy.CWVNumpyMLP`
serves `probabilities` for the value net and `policy_log_odds` for the prior
over the same trunk, and `cwv_prior_admission.load_prior_checked` binds such a
package as prior kind `joint-numpy` (refusing a headless package or one whose
trunk does not read the v2 833-column root rows). Registration is from the
environment at import (`registry._register_cwv_shortlist_from_env` /
`_register_cwv_bury_from_env`); the policy name binds the package SHA, the
W32/N30/R300 recipe and the prior fields (`cwv_shortlist.PRIOR_RECIPE_FIELDS`).

Qualification before the deploy: `scripts/cwv_serving_gate.py --serving
--threshold 1000` on the exact package as value and prior vs the Torch
checkpoint (2,208 decisions: 2,207 identical, 1 near-tie with the same play and
RNG, prior fired 141×); `scripts/cwv_serving_smoke.py` from a clean checkout of
main with the committed fly.toml (40 server turns through the server's bot-turn
path); SHA verified on the volume; a live takeover-driven room played a full
round (bury 0.7 s after the trump call; 69 searches p50 0.6 s / p90 1.6 s /
max 2.7 s).

## Releases 25–27 (September 15): M1 + policy prior v2, two packages

Release 25 shipped M1 (`12ce4415`, the first residual-trunk NumPy export; schema
v2 added the residual trunk to the runtime) plus a separate policy-prior package
(`b9ff76c9`, `cwv_prior_numpy`). It passed the identity gate and stalled every
live bot turn: the server's turn snapshot deep-copies the bot and the prior's
read-only weight mapping could not be pickled. It was rolled back to the
release 24 image within the hour (release 26), fixed
(`CWVNumpyPrior.__deepcopy__`), and redeployed as release 27 at threshold 1,000
with the new server-path smoke as a precondition. Release 27 is the rollback for
release 28.

## Hybrid bury release (September 9)

Deployed as Fly **release22**, image `b5dc327f…1030c82d`, with the exact
selected policy below. Live health, literal model SHA/path, qualified encoder
hashes and native/no-Torch execution verified. One isolated functional bury
completed legally in 0.803s without fallback or play-RNG advance. No synthetic
ordinary room or human-training log was created. The original machine,
volume and engineering-room gate were preserved. See DEPLOY.md for the full
image digest and environment overrides.

PR #323 is merged. Jerry authorized shipping the reviewed baseline after the
1,976-deal all-rank result: hybrid versus heuristic banker utility
`+0.03644 [0.01164, 0.06024]`, win-rate `+1.62pp [0.56, 2.68]`.
Hybrid versus MC-only remains unresolved; more worlds/candidates did not show
a supported gain. Kitty-loss risk increased versus heuristic. These are
counterfactual single-round results, not human-weighted multi-round matches.

The selected serving name is
`mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`:

- Same compact fd6bb411 model and W32 play settings.
- Up to32 structured buries,32 model worlds, heuristic incumbent plus four
  alternatives,32 independent MC worlds. Only the bury decision changes.
- `SHENGJI_CWV_BURY_ARM=hybrid` registers the policy;
  `SHENGJI_BOT` must select the exact name.
- `SHENGJI_CWV_BURY_SERVING_BUDGET_SECONDS=2` enables cooperative expiry and
  legal heuristic fallback. This is search time, not total queued request time.
- One off-loop search worker; live room/turn/controller checked before commit.
- Data-generation recipes omit the serving budget and fail on errors. They
  record only actual MC-finalist labels with counts and provenance; serving
  fallbacks are not silently treated as training targets.

The prior Linux1CPU/512MiB actual-consumer probe passed11/11: serial367–508ms,
four-request burst tail1.75s,cgroup peak104.9MiB,noOOM. That probe used a30s
diagnostic deadline; the shipping2s configuration passed its own focused
11-request Mini smoke, not a duplicate strength run. Measurements are not productionp99 or a
bound on mixed play/bury queueing.

Bury-only rollback restores `mc-shortlist-fd6bb411-w32-r55d379a3` **and removes
bury registration/budget settings together**. Preserve the model and volume.
Pre-bury image is release21 at digest
`4a68a54058d028dd2444270d1f83b51dcc8623c627043e68ea8058594d41f54b`.
Full W32 play rollback to MC-LCB is a different intervention. See [DEPLOY.md](../DEPLOY.md)
for occupancy, monitoring and rollback rules; see the [bury report](value-guided-bury-dev-2026-09-08.md)
for source reviews, complete evidence and statistical limitations.

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

For the current global default, set these **before Python starts** (the exact
values are in `fly.toml`; the name is derived by the registry from them):

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export SHENGJI_FAST=1
export SHENGJI_BOT=mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff
export SHENGJI_CWV_SHORTLIST_CKPT=/data/models/js-m1-0d17fd03.npz
export SHENGJI_CWV_PRIOR_CKPT=/data/models/js-m1-0d17fd03.npz
export SHENGJI_CWV_PRIOR_SHA256=0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747
export SHENGJI_CWV_PRIOR_THRESHOLD=1000 SHENGJI_CWV_PRIOR_TOP=256
export SHENGJI_CWV_BURY_ARM=hybrid SHENGJI_CWV_BURY_SERVING_BUDGET_SECONDS=2
export SHENGJI_MODEL_SEARCH_CONCURRENCY=1
```

Prior-only rollback: drop the four `SHENGJI_CWV_PRIOR_*` settings and set
`SHENGJI_BOT` to the prior-less name the registry prints; `/healthz` must show
`"prior": null`. Release rollbacks (27, 24) are in `DEPLOY.md`.

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

## Moved from DEPLOY.md on 2026-10-01

The sections below are verbatim from `DEPLOY.md` (main `ceea12e9`): the release-28 plan as approved, releases 27, 26 and 25 with the release-25 plan, and the release-22 "current production and rollback boundary" with the September-8 W32 rollout and the release-19/18 boundaries. Release numbers, images and rollback statements are those of their day; production since 2026-09-30 is described at the top of `DEPLOY.md`.

## Release 28 plan as approved (kept for the record)

Play policy `mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff`: JS-M1 (`a5248cc5`, M1's recipe from scratch with a policy head trained on all
20.3M root rows) served as a single NumPy package `/data/models/js-m1-0d17fd03.npz`
(SHA256 `0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747`, schema v2 with the policy head, PR #455). The package is the value net
AND, above 1,000 legal actions with top 256 per sampled world, its own policy head is the
admission prior (`SHENGJI_CWV_PRIOR_CKPT` names the same file; prior kind `joint-numpy`).
Hybrid bury and the 2-second bury budget unchanged (JS-M1 scores bury candidates).
Evidence: offline, val_ce 0.5957 (M1 0.5975) and a policy head non-inferior to prior v3 on
four of five strata (widest unresolved); in play (cloud lane v22, five capped windows),
+0.0239 [+0.0005, +0.0472] vs the release 24 recipe (nominal, shared-control seeds) and
paired +0.0057 [−0.0163, +0.0277] vs the release 27 recipe at the same decision wall with
0 decisions over 60 s in 182,096 — no ten-window or fresh-seed read yet. Preconditions
before `fly deploy --ha=false`: #455 merged; decision-identity gate PASS at threshold
1,000 on this exact package as value and prior (`scripts/cwv_serving_gate.py --serving
--threshold 1000`); `scripts/cwv_serving_smoke.py` PASS from a clean checkout of main with
this fly.toml; the package SHA256-verified on the volume; a live room's log showing a bot
bury and bot plays completing. Prior-only rollback: remove the four `SHENGJI_CWV_PRIOR_*`
settings and set `SHENGJI_BOT` to the prior-less JS-M1 name the registry prints. Full
rollback: release 27 (M1 + prior v2, its fly.toml) or release 24.

## Release 27 — M1 + policy prior v2 (#435), redeployed 2026-09-15 22:0x ET

Release **27**, image `registry.fly.io/shengji:deployment-01M2M1B48P44H5HJXEP6ETYQXE` (digest
`sha256:ff1b78f900f141315582d770ef2232da8d1999d65e6e7a63e22e8d52c0a62993`), deployed with
`fly deploy --ha=false` from main `383c8dc8` (the release 25 recipe plus the
`CWVNumpyPrior.__deepcopy__` fix from #451/#452) on machine `48e7e35a9597e8`, 0 rooms at
deploy time. Live health after the deploy:

```
{"ok":true,"rooms":0,"bot":"mc-shortlist-12ce4415-w32-r45b303c2-prior-b9ff76c9-bury-hybrid-3ba49886a78f","fast":true,"prior":{"sha256":"b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c","threshold":1000,"top":256}}
```

Preconditions met, in order: fix merged; `scripts/cwv_serving_smoke.py` PASS from a clean
checkout of that main on the exact packages with this fly.toml (40 server turns through
`_paced_bot_step` / `_commit_bot_turn`); decision-identity gate PASS at threshold 1,000
(2,222/2,222 identical, prior fired 139×); packages SHA256-verified on the volume.
`/healthz` cannot see a bot-turn failure (release 25 reported ok while every bot turn
raised), so the first live room's log is the completion check: a bot `bury` event and
`model_search` `completed` events must appear.

**Rollback** is unchanged: release 24 image
`registry.fly.io/shengji:deployment-01M2BGBXE7JXWYBEVWNMG2YM5A` with release 24's
`fly.toml` (as done for release 26 at 20:55 ET); prior-only rollback as described below.

## Release 26 = the release 24 image (rollback), 2026-09-15 20:55 ET → superseded by release 27

Release 25 (below) stalled every bot turn in its first live room (KXXD): the server
deep-copies the bot into a turn snapshot before any search, and the NumPy prior's
read-only weight mapping could not be pickled, so the snapshot raised before the bury
budget began. The in-process decision-identity gate could not catch it (it never takes
the server's snapshot path). Rolled back with
`fly deploy --image registry.fly.io/shengji:deployment-01M2BGBXE7JXWYBEVWNMG2YM5A --ha=false`
and release 24's `fly.toml` → release **26**, `/healthz`
`{"ok":true,"rooms":0,"bot":"mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a","fast":true}`.
The two new packages stay on the volume. Redeploy of the release 25 recipe requires:
PR #451 (`CWVNumpyPrior.__deepcopy__`) merged, `scripts/cwv_serving_smoke.py` PASS on the
real packages from the fixed tree (it builds the bot from `fly.toml` and plays a bury and
play turns through the server's own bot-turn path), and Jerry's word.

## Release 25 — M1 + policy prior v2 (#435), deployed 2026-09-15 19:54 ET, rolled back 20:55 ET

Release **25**, image `registry.fly.io/shengji:deployment-01M2KQVJVPC6WD85RQD59SYG38`
(digest `sha256:4ed088a25eef1244818bbce6dc3e9742ade8f913679a70ebf2a62def1b3af189`), deployed
with `fly deploy --ha=false` from main `55f0029c` on machine `48e7e35a9597e8`
(1/1 health passing, 0 rooms at deploy time). Live health after the deploy:

```
{"ok":true,"rooms":0,"bot":"mc-shortlist-12ce4415-w32-r45b303c2-prior-b9ff76c9-bury-hybrid-3ba49886a78f","fast":true,"prior":{"sha256":"b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c","threshold":1000,"top":256}}
```

Preconditions that were met, in order: serving gate merged (#445), config merged (#448),
the serving-scope gate on the exact packages at threshold 1,000 PASS (2,222/2,222 decisions
identical, prior fired 139×; receipt archived under `~/shengji-archive/2026-09-15/release25/`
with the 10k run, the deploy log and this health response), both packages SHA256-verified on
the volume. Jerry's go: 18:2x ET (M1 + prior v2), 19:2x ET (threshold 1,000).

**Rollback.** Full: release **24**, image
`registry.fly.io/shengji:deployment-01M2BGBXE7JXWYBEVWNMG2YM5A` (fd6bb411 + hybrid bury,
`SHENGJI_BOT=mc-shortlist-fd6bb411-w32-r55d379a3-bury-hybrid-c93a9877ae6a`,
`SHENGJI_CWV_SHORTLIST_CKPT=/data/models/w32-fd6bb411.npz`, no `SHENGJI_CWV_PRIOR_*`); the
release 24 package stays on the volume. Prior-only: remove the four `SHENGJI_CWV_PRIOR_*`
settings and set `SHENGJI_BOT` to the registry's prior-less M1 name; `/healthz` must then
show `"prior": null`. Machine and volume `vol_rkgj0xeg8ejy1kw4` are unchanged; logs and
model packages must be preserved.

## Release 25 plan as approved (kept for the record)

Play policy `mc-shortlist-12ce4415-w32-r45b303c2-prior-b9ff76c9-bury-hybrid-3ba49886a78f`:
M1 (`3cb9cd62`) served as NumPy package `/data/models/m1-12ce4415.npz`
(SHA256 `12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f`),
policy prior v2 (`b6d928c5`) as `/data/models/prior-v2-b9ff76c9.npz`
(SHA256 `b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c`, pinned by
`SHENGJI_CWV_PRIOR_SHA256`), applied above 1,000 legal actions with top 256 per
sampled world (Jerry accepted 1,000 over the originally approved 10,000 on
2026-09-15 19:2x ET: on five paired capped windows threshold 1,000 is outcome-identical
to 10,000, −0.0006 [−0.0026, +0.0014], at 0.72× its decision wall and 0.60× the
previous recipe's, longest decision 9.9 s vs 57.6 s); hybrid bury and the 2-second
bury budget unchanged. Evidence: twenty
fresh windows of the M1 family +0.0140 [+0.0026, +0.0254] vs the previous recipe;
the prior arm is outcome-identical to M1 (paired −0.0003 [−0.0017, +0.0012]) at
0.79× the previous decision wall with 0 decisions over 60 s and 0 cap hits in
365,414 (previous recipe: 161 and 7). Preconditions before `fly deploy --ha=false`:
both packages on the volume with matching SHA256, the in-repo serving gate
(`scripts/cwv_serving_gate.py --serving --threshold 1000`) PASS with
`qualifies_serving` on these exact files at this threshold, `/healthz` after deploy showing the policy name and `"prior"` with the
prior SHA. Prior-only rollback: remove the four `SHENGJI_CWV_PRIOR_*` settings and set
`SHENGJI_BOT` to the prior-less M1 name the registry prints; full rollback: release
24 (below) with its environment. The release number, image and health response are
recorded above.

## Current production and rollback boundary

Previous production (superseded by release 25 above): release **22** deployed September 9 at approximately 20:51 ET, image
`registry.fly.io/shengji@sha256:b5dc327f79d8804d2a9f79bcddbb6bea1740b71547937ce1be1c08661030c82d`.
Live health reports the exact hybrid policy and native engine. An isolated
functional probe verified the literal model path and SHA, encoder bytes,
legal eight-card bury, unchanged play RNG and no Torch import; it completed
in 0.803s without fallback. This is one smoke observation, not a latency SLA.
The existing engineering-room gate and checkpoint were preserved using deploy
overrides `SHENGJI_W32_TEST_ROOMS=1` and
`SHENGJI_W32_TEST_CKPT=/data/models/w32-fd6bb411.npz`; retain those overrides
on a later deploy if the engineering gate is to remain available. Ordinary
rooms use the default policy without an access code.

Jerry authorized shipping hybrid bury on September 9 after PR #323's fixed
1,976-deal all-rank confirmation and consumer review. The shipping config uses
32 candidates / 32 model worlds / 32 MC worlds, incumbent plus four alternatives,
and a **2-second cooperative search budget**. Expiry or search error returns
the legal heuristic incumbent without advancing the play RNG. Queue wait,
model loading and an in-flight operation are not bounded by that deadline.
The existing W32 play recipe, compact model, one search worker and 512MiB VM
remain unchanged. Consult `/healthz` for the live policy; configuration in Git
is not itself proof of deployment.

Pre-bury rollback release: **21**, image
`registry.fly.io/shengji@sha256:4a68a54058d028dd2444270d1f83b51dcc8623c627043e68ea8058594d41f54b`.
Machine `48e7e35a9597e8`, volume `vol_rkgj0xeg8ejy1kw4`, existing model package
and logs must be preserved. Bury-only policy rollback on the new image restores
the base W32 name and removes bury registration/budget together; do not select
an unregistered bury name. Reverting the image also requires restoring its
compatible environment. Do not interrupt occupied rooms without scoped consent.

Monitor queue/search/request latency separately, fallback reasons, stale-turn
discards, OOM/crash, legality and kitty-loss incidents. Roll back immediately on
illegal action, RNG/isolation violation or crash/OOM. Investigate repeated
2-second expiries or new queue stalls; do not silently raise the budget. Live
traffic is not a powered strength trial. Large kitty losses are a known tradeoff:
the confirmation saw four 80+ bonuses versus zero for heuristic, despite better
average results. See the [bury report](docs_archive/value-guided-bury-dev-2026-09-08.md).
For tail monitoring, count `round_end.kitty_points >= 80` among completed
bot-banker rounds using this policy, with the completed-round denominator;
separate successful hybrid decisions from logged heuristic fallbacks. This
field is the awarded kitty bonus, not raw buried-card points. Preserve failed
and unfinished rounds separately rather than silently excluding operational
failures. These observational counts are not a causal comparison with old traffic.

### Historical W32 rollout (September 8)

On September 8, Fly release **20** deployed the reviewed opt-in W32 room gate
from PR #310, image
`registry.fly.io/shengji@sha256:b8f48f41149d8a27225e7a44260b72b03475dbdf99ba7398c56167682afd19e5`.
The single 512 MB / shared-CPU-1x machine `48e7e35a9597e8` and its volume are
unchanged. At **19:53 UTC September 8**, after Jerry explicitly authorized
all-user rollout and health showed zero rooms, an environment-only update on
this same image made W32 the ordinary-room default. No access code is needed.
The loaded NumPy package was verified as `fd6bb411` (source `3cd27716`, encoder
v2), with no Torch import; public health passed with the exact W32 policy.
Explicit engineering rooms still require a creator access code and remain
excluded from ordinary training logs.
See `docs_archive/w32-fly-serving-through-2026-09-22.md` (archived 2026-09-22) for the measured latency and test status through release 28.

The pre-deploy **release 19** rollback image is
`registry.fly.io/shengji:deployment-01M0P8VNX2C49XMVHFWFNNAPC2`, manifest
`sha256:38c40bb675b2a330e845168ed3f63089279cff764bdcb7fea4908578721045dc`.
This is the rollback image for the gated-W32 deployment; retain its
machine configuration and volume. Health must report
`{"bot":"mc-s0-report-lcb","fast":true}`. The earlier release-18 boundary
below is historical, not the current release number.

The decision runtime moves an isolated bot/round snapshot into
a worker, overlaps the existing 0.7-second pacing floor, and commits the action
only if the live room, round, phase, turn and controller still match. Claims,
reconnects and X-ray therefore remain responsive; a stale search is discarded
with its cloned RNG/counters.

For the original W32 rollout, **policy rollback was `SHENGJI_BOT=mc-s0-report-lcb`**
on the same image; retain both model packages and the volume. The global model
registration can remain present when MC-LCB is selected. A normal-room
constructor and health were checked, not a many-room concurrency benchmark;
one model-search worker bounds CPU use but concurrent players can queue.

Historical release-18 rollback decisions (not the current W32 rollback):

1. **Release/runtime rollback:** Fly release 17 / image
   `latency-cd6789e`. Use this for a release-18 availability or kitty-X-ray
   regression while keeping the report-LCB policy and release-17 scheduler
   decision separate. It does not undo a defect shared with release 17. The
   release-17 manifest SHA-256 is
   `047bcfe4d4573961734a5536ad549605fd0df5e1477d7480cdf322282955b300`.
2. **Policy rollback:** `SHENGJI_BOT=mc-strong`. Use this for a report-LCB
   decision-semantics/correctness problem; it gives up the confirmed strength
   gain and is not the response to a generic server/runtime issue.

The project owner (Jerry) is the production deploy and rollback decider.
Before a planned deploy or policy change, inspect room occupancy and obtain
scoped authorization before interrupting games. Record the old release, exact
image/manifest, health response, reason and rollback target. Do not treat an
empty room as permission to change the production policy.
