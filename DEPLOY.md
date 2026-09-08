# Deploying Sheng Ji

The server is a **single stateful process**: rooms and games live in memory,
clients hold WebSockets to it. That drives every deployment rule below.

## Ground rules (any host)

- **Exactly one instance.** No replicas, no autoscaling, no serverless. Two
  instances would each hold half the rooms.
- A restart drops in-progress games (players see "That game has ended.").
  Deploy when it's quiet.
- TLS is handled by the platform/proxy; the frontend auto-selects `wss://`
  on https pages (same-origin), no config needed.
- Health check: `GET /healthz`.
- Pick the bot with `SHENGJI_BOT`. The source fallback is `mc` (N=10), while
  Fly explicitly pins W32 `mc-shortlist-fd6bb411-w32-r55d379a3`, using the
  A+C+D+E+F2 v2 model with N=30 selection and R=300 report checking.
  `mc-s0-report-lcb` is the immediate policy rollback; `smart` and `heuristic`
  are cheaper difficulty choices, not strength-equivalent replacements. See
  `W32_FLY_SERVING.md` for the rollout boundary and `AI_POLICIES.md` for evidence.

## Current production and rollback boundary

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
See `W32_FLY_SERVING.md` for measured latency and test status.

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

For the current rollout, **policy rollback is `SHENGJI_BOT=mc-s0-report-lcb`**
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

## Option A: Fly.io (recommended)

```bash
brew install flyctl && fly auth login
fly launch --copy-config --no-deploy   # uses fly.toml; pick an app name
fly volumes create shengji_data --size 1   # ONE volume (see below)
fly deploy --ha=false                      # ONE machine (see below)
```

`fly.toml` already pins an always-on machine (512MB is plenty — the engine
is tiny) with `auto_stop_machines = "off"` so idle games aren't killed.
Custom domain: `fly certs add yourdomain.com` + a CNAME.

Two Fly defaults to override (learned the hard way):
- **`--ha=false` is required**: plain `fly deploy` creates TWO machines for
  "high availability", but rooms live in one machine's memory — the proxy
  would route players randomly between machines and rooms would appear
  missing. If you end up with two, `fly machine destroy <id> --force` one.
- **Ignore the volume redundancy warning** (`-n 2`): one machine means one
  volume. Extra volumes get claimed by phantom machines and wedge deploys
  ("volume already claimed" / "needs an unattached volume") — destroy
  extras with `fly volumes destroy <vol_id>`.

## Option B: any VPS with Docker

```bash
docker build -t shengji .
docker run -d --restart unless-stopped -p 127.0.0.1:8000:8000 shengji
```

Put Caddy in front for TLS (Caddyfile: `yourdomain.com { reverse_proxy
localhost:8000 }`) — Caddy proxies WebSockets automatically.

## Option C: zero-deploy for friends

Tailscale (invite friends to your tailnet, run the server locally) or a
Cloudflare Tunnel. No code or config changes needed.

## Capacity

Policy cost, not the rules engine, sets CPU capacity. On the measured mini,
SmartBot is p50 0.05ms / p95 0.13ms, direct v11pair is 0.25ms / 0.52ms on the
numpy path, base N=10 MC is 77ms / 150ms, and an earlier matched benchmark put
the production report-LCB decision at 0.390s versus 0.127s for `mc-strong`.
Live Fly time is workload-dependent: after release 17, the first ordinary
human room's 195 searched turns measured p50/p95/max
0.896/1.714/1.906s. Off-loop execution hides event-loop blocking and overlaps
the 0.7s pacing floor; it does **not** make search free or let a worker react
before the latest play. Each turn snapshots only after that play, computes,
then revalidates before commit. Load-test the chosen policy and concurrent room
mix before advertising capacity. Memory per room is small; scaling beyond one
process would require external state and room-affinity routing.
