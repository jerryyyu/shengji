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
- Pick the bot with `SHENGJI_BOT` (`mc` default/strongest, `smart` faster,
  `heuristic` easiest — see AI_POLICIES.md).

## Option A: Fly.io (recommended)

```bash
brew install flyctl && fly auth login
fly launch --copy-config --no-deploy   # uses fly.toml; pick an app name
fly deploy
```

`fly.toml` already pins one always-on machine (512MB is plenty — the engine
is tiny) with `auto_stop_machines = "off"` so idle games aren't killed.
Custom domain: `fly certs add yourdomain.com` + a CNAME.

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

One shared CPU comfortably runs dozens of concurrent rooms: the engine is
sub-millisecond per action, SmartBot ~1ms/decision, MCBot ~26ms/decision
(hidden inside the 0.7s bot pacing delay). Memory per room is a few KB.
Scaling beyond hundreds of concurrent games would require external state
(Redis) and room-affinity routing — deliberately out of scope for now.
