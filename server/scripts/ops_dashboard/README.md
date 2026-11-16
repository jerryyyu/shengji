# Ops dashboard

A private, read-only usage page for production, run on the Mac mini. `serve.py`
binds by default localhost plus the address in `$OPS_BIND_EXTRA` (the Mini's
Tailscale address, set in the LaunchAgent, never in this repo); `--bind` accepts any comma-separated list of addresses and refuses only a wildcard
(`0.0.0.0`, `::`), so another address is reachable from wherever it routes.

| file | runs where | does |
|---|---|---|
| `query.py` | inside the Fly container (`python3 -`) | opens `/data/accounts.sqlite3` with `mode=ro` and runs every database query in one read transaction (one consistent snapshot, including rows committed to the server's WAL; it shares the `-wal`/`-shm` files the server already keeps), reads room logs changed in the last 30 days and the support/report files, prints one `OPS_JSON {...}` line of counts |
| `collector.py` | Mini, launchd every 300 s | fetches `/healthz`, runs `query.py` over `flyctl ssh console`, refuses any output outside its fixed key schema, writes `latest.json`, `history.jsonl` and `snapshots/<date>/<time>.json` under `~/shengji-ops/` |
| `serve.py` | Mini, launchd, kept alive | serves `index.html`, `/api/latest`, `/api/history`, `/api/botspeed`; binds only the `--bind` addresses (refuses a wildcard); every request needs `?t=<token>` from `~/shengji-ops/token`, else 403. Its one write, `POST /api/reports/handled`, edits the local list `~/shengji-ops/state/reports_handled.json` and is accepted only on the loopback listener from a loopback client |
| `index.html` | the browser | one inline page (no external requests), refreshes every 60 s |
| `backfill_botspeed.py` | Mini, by hand, once | fills `botspeed.json` from a local copy of the room logs (read only), with the same code `query.py` runs on Fly |

Privacy: the page shows counts, except the player-report rows: an opaque id,
time, room code, round, reason and the two seats' table names
(`QUERY_SCHEMA["reports"]` allows exactly those strings). `query.py` prints no email, account id, IP or
message text. Before anything is stored,
`collector.check_schema` requires the output to use only the key paths in
`collector.QUERY_SCHEMA`, each holding a number (a bool or null where listed);
any other key or a string fails the run. Failures are stored as fixed codes
(`query_failed`, `query_timeout`, `query_bad_json`, `schema_violation`,
`healthz_failed`), never as key names, values or command output. This check
limits what is stored on the Mini; it cannot prove what the container
computes, and a number under an allowed key could still be anything the query
chose to put there. Nothing is sent to a third party.

Production cost per run: one `flyctl ssh` session and about 0.1 s of CPU in the
container (measured 0.055-0.08 s on 2026-11-12 with 46 log files, 29 MB).

## What the data supports

| metric | source |
|---|---|
| open rooms | `/healthz` `rooms` |
| tables playing now, by non-bot roster seats at the latest round start | room logs: a `round_start` in the last 20 min (latest per room) |
| accounts, Google/Apple, new 24 h/7 d, sign-ups per day | `users` |
| rated rounds, 2+ humans, abandoned, per player | `rating_events` (rows for every round with a signed-in seat; ranked and casual are not told apart) |
| signed-in players, saved games, games per player | `game_players` + `games`, plus `rating_events` |
| rounds played, rounds by non-bot roster seats | room logs `round_start.players[].is_bot`. False means the seat was not a bot seat on the roster at round start, which includes a disconnected owner's seat while a bot covers it (`server._controller` = `bot_cover`); these counts are not evidence of human play |
| signed-in / unknown / guest roster seat-rounds (estimate) | each logged round's non-bot roster seats, by that round's timestamp. Signed in: a saved-game link (`games.log_offset` locates the game in the log, `game_players` seat and round range; an open link has no upper round) covers the seat in that round. Unknown: not covered, and the database may lag the log (the round is past the game's stored `last_round`, or it started within 120 s of the database snapshot). Guest estimate: the rest. A signed-in seat whose game has no `log_offset` (its first log write failed) counts as a guest |
| return after 1 / 7 days | `users.created_at` vs later rated rounds or saved games |
| support messages, player reports (7 d) | `support_messages.jsonl`, `player_reports.jsonl` (`ts` only) |
| latest player reports and their state | `player_reports.jsonl`: the 20 newest rows, plus id and time of every report from the last 7 days. Each id is an opaque hash of the whole stored record (and its count among identical records), made in the container. The server keeps no handled mark, so **Mark handled** (on `127.0.0.1` only) adds the id to `~/shengji-ops/state/reports_handled.json` on the Mini; amber/red count every unhandled report of the last 7 days over 12 h / 24 h old, not only the displayed ones, and unhandled ones older than the newest 20 are listed first so they can be marked |
| bot decision time | room logs' decision timings, folded into `~/shengji-ops/botspeed.json` by day and hour |

Not available without a server change: players right now split into
signed-in / guests / bots, and the ranked queue. Those live only in the server
process; the dashboard shows "needs server endpoint". Guests are never
countable as people: a guest has no persistent id.

## Install (Mac mini)

```sh
mkdir -p ~/shengji-ops/app ~/shengji-ops/logs && chmod 700 ~/shengji-ops
cp server/scripts/ops_dashboard/{query.py,collector.py,serve.py,index.html,backfill_botspeed.py} ~/shengji-ops/app/
python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > ~/shengji-ops/token
chmod 600 ~/shengji-ops/token
```

The installed copy runs from `~/shengji-ops/app`, so it does not depend on a
checkout. Two LaunchAgents (`/opt/homebrew/bin/python3`, 3.11+ for `zoneinfo`):

`~/Library/LaunchAgents/org.shengji-ops.collector.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.shengji-ops.collector</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/python3</string>
    <string>/Users/USER/shengji-ops/app/collector.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>/Users/USER/shengji-ops/logs/collector.log</string>
  <key>StandardErrorPath</key><string>/Users/USER/shengji-ops/logs/collector.err</string>
</dict>
</plist>
```

`~/Library/LaunchAgents/org.shengji-ops.server.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.shengji-ops.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/python3</string>
    <string>/Users/USER/shengji-ops/app/serve.py</string>
    <string>--port</string><string>8787</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>OPS_BIND_EXTRA</key><string>TAILSCALE_IP</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/USER/shengji-ops/logs/server.log</string>
  <key>StandardErrorPath</key><string>/Users/USER/shengji-ops/logs/server.err</string>
</dict>
</plist>
```

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.shengji-ops.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.shengji-ops.collector.plist
launchctl list | grep shengji-ops
```

Replace `TAILSCALE_IP` with the Mini's address (`tailscale ip -4`). Open
`http://TAILSCALE_IP:8787/?t=<token>` from a device on the tailnet; marking a
report handled works from `http://127.0.0.1:8787/?t=<token>` on the Mini.

Stop: `launchctl bootout gui/$(id -u)/org.shengji-ops.collector` and
`launchctl bootout gui/$(id -u)/org.shengji-ops.server`. Run one collection
now: `launchctl kickstart gui/$(id -u)/org.shengji-ops.collector`.

Update: copy the five files again; `launchctl kickstart -k
gui/$(id -u)/org.shengji-ops.server` reloads the server.

Snapshots are about 2 KB each (about 600 KB a day); nothing prunes them.
