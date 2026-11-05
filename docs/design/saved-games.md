# Saved games for signed-in accounts (proposal)

Status: proposal for Jerry's pick. Nothing here is implemented. Line numbers are
at `main` ca02123a.

## What exists today

- **Accounts.** Optional Google sign-in (`docs/accounts.md`). `accounts.sqlite3`
  lives in `SHENGJI_DATA_DIR` (`/data` on Fly, `server/shengji/api/accounts.py:137-151`)
  and holds only `users` (Google `sub`, email, name, picture, display name) and
  hashed `sessions` (schema v2, `accounts.py:170-196`). Access is plain sqlite3
  off the event loop (`Store.run`, `accounts.py:344`). No consent or privacy
  text exists in the web app beyond the Google button.
- **Seat ↔ account.** The `/ws` handshake reads the cookie once
  (`server.py:1679-1680`); the seat keeps `Seat.user_id` (`server.py:236-240`,
  set again on reclaim and bot-seat claim at `server.py:1808,1890`). By design it
  enters no state frame and **no log record** (`docs/accounts.md` flow step 7).
- **Games.** Rooms live only in memory; a restart drops them and there is no
  restore path (`DEPLOY.md:802-807`). An empty room is deleted after `ROOM_TTL`
  = 300 s (`server.py:119,1318-1324`). A dropped player can already rejoin
  their own seat with the resume token while the room lives.
- **Room logs.** `Room.log_event` appends best-effort JSONL to
  `/data/logs/<CODE>.jsonl` (`server.py:121-127,324-363`); a write failure
  bumps `ACTIVITY.record_write_failures` and play continues (`server.py:145-190`).
  `round_start` carries the full deck, banker, levels and
  `players[{seat,name,is_bot}]` (`server.py:895-918`); `play` carries the bot's
  `decision` record (`server.py:805-827`); `round_end` carries the result and
  `new_levels` (`server.py:921-930`); `model_search`, `bot_timing`,
  `declare_decision` and `chat` (with text) are logged too. In the local cache
  (108 files, 296 rounds, 55 MB, about 185 KB per round) `play` is 82 % of the
  bytes, mostly decision records; `model_search` 9 %, `bot_timing` 5 %.
- **Room codes are reused.** `new_code` only avoids codes of *live* rooms
  (`server.py:1520-1524`), and the log opens in append mode, so a later room
  with the same code appends a second game to the same file, restarting at
  round 1. `rl/replay_log.group_rounds` keys by round number only
  (`server/shengji/rl/replay_log.py:30-36`) and would merge such games. A saved
  game therefore needs its own id, not just the file name.
- **Replay tools** are offline only: `server/scripts/replay.py` (transcript)
  and `server/scripts/xray.py`. The web app has no replay page; the live
  `XrayPanel` is token-gated debug (`server/shengji/api/debug.py`).
- **Fetch.** `server/scripts/fetch_fly_logs.sh:18-36` copies only
  `/data/logs/*.jsonl`; the accounts database is never copied off the machine.
  The fetched logs are the human training corpus.

## 1. Scope (recommended phasing)

| phase | what the player gets | cost |
|---|---|---|
| **1 (recommend)** | **History**: "My games" lists each game the account played: date, partners and opponents by name, rounds played, final levels, games won. **Replay** of any finished round from the player's seat. | one table, one hook, two read endpoints, one page |
| 2 | Rejoin by account: a signed-in player whose tab died can retake their seat in a *live* room from any device (the seat's `user_id` matches) instead of needing the localStorage resume token. | small; uses the existing reclaim path |
| 3 (later, maybe never) | Resume after a server restart. Needs a durable snapshot of `Game`/`Round` at each trick, room re-creation on boot, bot state (seed, belief) restored, and a rewrite of the "deploy at 0 rooms" rule. | large; touches the serving path |

Phase 1 is a pure read of data the server already writes, adds nothing to the
bot path, and covers what "saved games" most likely means. Phase 3 changes
the single-process recovery model and should wait for a demand signal.

## 2. Data model

The room log stays the source of truth. The account database stores only the
link and a small summary, so a log reader or the training corpus never sees an
account id (the `Seat.user_id` invariant holds).

New migration v3 in `accounts.SCHEMA`:

```
games(id TEXT PK,                 -- random 16-byte id minted at start_game
      room_code TEXT, log_file TEXT,   -- "<CODE>.jsonl", relative to LOG_DIR
      log_offset INTEGER,         -- byte offset of this game's first round_start
      started_at INTEGER, last_round INTEGER, ended_at INTEGER NULL,
      final_levels TEXT NULL, games_won TEXT NULL)   -- JSON, from round_end
game_players(game_id -> games.id ON DELETE CASCADE, user_id -> users.id
      ON DELETE CASCADE, seat INTEGER, from_round INTEGER, to_round INTEGER NULL,
      hidden INTEGER DEFAULT 0, PRIMARY KEY(game_id, user_id, seat, from_round))
INDEX game_players_user ON game_players(user_id, game_id)
```

- **Write points** (all through `STORE.run`, best-effort, never raising into a
  game): `start_game` (`server.py:1596-1610`) inserts `games` and one
  `game_players` row per signed-in seat; `log_event` returns the file offset
  it wrote at so the first `round_start` offset is exact. A seat whose
  `user_id` changes mid-game (reclaim, bot-seat claim, sign-in, sign-out)
  closes the old row and opens a new one at the current round. `_log_round_end`
  (`server.py:921`) updates `last_round`, `final_levels`, `games_won`, `ended_at`.
- **Failure handling:** a failed account write increments a new
  `ACTIVITY.account_link_failures` shown on `/healthz` next to
  `record_write_failures`. A failed log write means a round has no replay; the
  history row shows "incomplete".
- **Size.** About 300 B per game in SQLite: 10,000 games is about 3 MB. The
  logs, about 185 KB per round, are what fill the 1 GB volume (974 MB,
  about 88 MB used). Saved games do not add log bytes, but they make deleting
  logs visible to players. Proposed policy: keep linked games for 12 months; when
  the volume passes 70 % used, write a stripped replay file per linked game
  (only `round_start`, `declare`, `trump`, `bury`, `play` without `decision`,
  `trick`, `round_end`; about 5 % of the raw size), and only then may raw logs that
  `fetch_fly_logs.sh` has already copied be removed. Cap the history list at the
  latest 200 games per account (older ones stay until the 12 months are up).
- **Backups.** The volume snapshot covers both files today; check the Fly
  snapshot schedule and retention before launch. The Litestream plan in
  `docs/accounts.md` "Backup" becomes worth doing once history exists.
- **Existing logs** stay unlinked: they carry names, not accounts, and names are
  not identity (`server.py:229-233`). There is no backfill.

## 3. Privacy

- A game is visible only to an account in its `game_players`; every other
  request gets 404, not 403, so ids cannot be probed.
- The replay is built from the viewer's seat: their own hand from the deal;
  other hands and the kitty only once that round's `round_end` exists; an
  unfinished round shows only the cards played.
- Never served: `decision`, `model_search`, `bot_timing`, `declare_decision`,
  `bot_seed`. Chat is left out in phase 1 (it is other people's text).
- Other players appear under the names they had in that room, as at the table.
- Deletion: `DELETE /api/me/games/{id}` hides the game from that account;
  `DELETE /api/me` removes the user, sessions and links (cascade). The
  anonymous room log is unchanged; it never held the account. One line under
  the sign-in button says so: "Signed in, your games appear in My games. Game
  records without your account are kept to improve the bots."

## 4. API and UI sketch

- `GET /api/me/games?before=<started_at>&limit=50`: list rows, newest first,
  with names from `round_start.players`, the viewer's seat and team, rounds, and
  final levels (all from the database plus one `round_start` read, cached).
- `GET /api/me/games/{id}`: the summary plus per-round results.
- `GET /api/me/games/{id}/rounds/{n}`: the filtered event list for one round,
  sliced from `log_offset` until the next game's round 1. It reuses
  `rl/replay_log.rebuild_round` after splitting by game.
- Auth: the same `sj_session` cookie as `GET /api/me` (401 without), the same
  per-IP limiter, and the reads run in an executor with a byte cap per request
  so a long game cannot stall the loop.
- Web: a "My games" entry in `AccountChip.tsx` and the phone `…` menu; a
  `GamesList` page; a `ReplayView` that steps trick by trick through the existing
  `Table`/`TrickArea` components fed by a local reducer, read-only, with no
  socket.

## 5. Risks and non-goals

- No change to bot decisions, served packages or latency: the hooks run at game
  start and round end, off the loop. The pinned production-package and timing
  tests must stay green.
- The log schema is unchanged for corpus readers; the one `log_event` change
  is that it returns the offset.
- Training excluded rooms (`experimental_policy`, human-evaluation roots,
  `server.py:296-310`) are not linked in phase 1.
- Non-goals: public sharing links, spectating, stats or leaderboards, guest
  history.

## 6. Implementation plan (each PR has its own tests)

1. **Schema v3 and store methods.** Migration, insert, close and list; v2→v3
   upgrade test (pattern of `test_a_v1_database_upgrades_to_v2_once…`,
   `server/tests/test_accounts.py:563`).
2. **Link on the game path.** Offset from `log_event`; hooks at `start_game`,
   seat changes and round end; failure counter on `/healthz`. Tests: signed-in
   and guest seats, a reused room code giving two games with distinct offsets,
   a DB failure that leaves play unaffected, no account id in any log record.
3. **Read API with the privacy filter.** Tests: an owner sees the game, another
   account gets 404; hidden hands before `round_end`; decision fields absent.
4. **Web "My games" and replay** (vitest coverage like `App.auth.test.tsx`).
5. **Deletion and consent line.**
6. *(phase 2)* Rejoin by account. *(later)* Stripped replay compaction once
   the volume reaches the threshold.

## Decisions for Jerry

1. Scope: phase 1 (history + replay) now, phase 2 next, phase 3 deferred?
2. Retention: 12 months and a 200-game list cap, or other numbers?
3. Guests: when a guest signs in during a game, the seat links from that round
   on (proposed). Should they also claim the earlier rounds of that game? Games
   finished as a guest are never claimed (proposed: no).
4. Chat in replays: out (proposed) or in?
5. Consent wording under the sign-in button, and whether to show the bots'
   reasoning to the owner later as an opt-in "analysis" view (proposed: no for now).
