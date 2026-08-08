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
  Fly explicitly pins the confirmed production champion
  `mc-s0-report-lcb` (N=30 selection plus an R=300 disjoint report check).
  `mc-strong` is the policy rollback; `smart` and `heuristic` are cheaper
  difficulty choices, not strength-equivalent replacements. No learned policy
  is currently authorized for production. See `AI_POLICIES.md`.

## Current production and rollback boundary

Fly release 17 runs
`registry.fly.io/shengji:latency-cd6789e`, manifest SHA-256
`047bcfe4d4573961734a5536ad549605fd0df5e1477d7480cdf322282955b300`.
Health must report `{"bot":"mc-s0-report-lcb","fast":true}`. The release
moves an isolated bot/round snapshot into a worker, overlaps the existing
0.7-second pacing floor, and commits the action only if the live room, round,
phase, turn and controller still match. Claims, reconnects and X-ray therefore
remain responsive; a stale search is discarded with its cloned RNG/counters.

There are two independent rollback decisions:

1. **Runtime/scheduler rollback:** Fly release 16. Use this for availability,
   responsiveness, stale-commit or scheduler correctness regressions while
   keeping the report-LCB policy decision separate.
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
