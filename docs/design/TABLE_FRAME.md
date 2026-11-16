# One table frame

A table is open (a matchmaker `Table`: alone or waiting) or playing (a
`Room`). One frame, `table`, says the same thing from either source. The
client reads the open phase from it alone ("Migration" 3); the playing
phase still from `room`, `state` and `room_seats`, translated into one
`TableModel`.

## The frame

`{type: "table", code, phase, mode, you, opener, seats[4], settings, timers, your_ready, waiting_for, chat_log}`

- `phase`: `"open"` | `"playing"`. `mode`: `"ranked"` | `"casual"`.
- `seats`: four, in seat order, each `{seat, team, state, name, you, ready, reconnecting, since, sit, pair, leader, left}`;
  `state` is `taken` | `open` | `held` (kept for a Duo opener's friend) | `bot` (a bot plays it in a game).
- `settings`: `{allow_joiners, start_level}`. `timers`: `{bots: {at, name, you} | null, start_now_at}`.
- `chat_log`: the key the table's chat frames carry (`table_chat.table`, or the room code for `chat`).

**Not in it.** The search (`since`, `count`, `front`, `party_id`, `leader`,
`wait_players`, `bots_paused`, `offer`, `open_tables`, `panel_seq`,
`still_here_until`, `duo`, `duo_ready`) stays in `queue_state`: it is the
entry, not the table. The game (`state`, its `players[].cards_left`, takeover
countdowns, move timer, `ready` for the next round, `joining`) stays in
`state`. `resume`, `chat`/`table_chat`, `table_moved`, offers and
`room_seats` (a peek of someone else's table) are unchanged.

**Privacy.** Display names only, as the frames it replaces. No account id,
rating, device key or resume token; `sit` is the sitting token every person
at a waiting table already gets in `queue_state.table`, null at your own
table and in a room. Newly visible: while you wait alone, your own table's
seats (you, a pair partner and whether they are connected, the held seat),
all of which you already know from `queue_state` and `party`.

**Send points.** Open: right after every `queue_state` that holds the entry
(`queued` and not `elsewhere`), on the same socket, so its timing is that
frame's. Playing: in every broadcast, right after the seat's `state`, only
when it differs from the last one that socket got (nothing in it ticks); a
fresh socket always gets it. `queue_state {queued: false}`, `queue_removed`,
`match_started` (the room's frame follows) and `left` end a table, as today.

## Field mapping

The open column names the `queue_state` fields each frame field took over;
`queue_state` no longer sends them ("Migration" 3).

| table frame | open: `queue_state` | playing: `room` / `state` |
|---|---|---|
| `code` | `code` (= `table.code`) | `room` |
| `phase` | `"open"` | `"playing"` |
| `mode` | `mode` | `"ranked"` iff rated (`matched` and ordinary), else `"casual"` |
| `you` | `table.you`; alone: your seat (0, or 2 for a pair's partner) | `you` |
| `opener` | `table.opener`; `opener: true` iff it equals `you` | `opener` (= `host`) |
| `seats[i].state` | `table.seats[i]` non-null: `taken`; null: `held` if in `held_seats`, else `open` | `players[i].is_bot` or `left`: `bot`; else `taken` |
| `seats[i].name, you` | `table.seats[i].name, you` | `players[i].name`; `you` = `i == you` |
| `seats[i].ready` | `table.seats[i].ready` | null (round-end `ready` stays in `state`) |
| `seats[i].reconnecting` | `table.seats[i].reconnecting` | a person's seat with `connected: false` |
| `seats[i].since, sit, pair, leader` | `table.seats[i]` same names | null / false |
| `seats[i].left` | false | `players[i].left` |
| `settings.allow_joiners` | `allow_joiners` | `allow_joiners`, null where absent (a test room) |
| `settings.start_level` | `start_level` | `start_level` |
| `timers.bots` | `table.timer`; alone: `{at: bots_at, ...}` or null | null |
| `timers.start_now_at` | `table.start_now_at`; alone null | null |
| `your_ready` | `you_ready` (= `table.you_ready`) | null |
| `waiting_for` | `table.waiting_for`; alone: your Duo partner if not ready | null |
| `chat_log` | `table.id`, alone null | `room` |

Derivable, so dropped: `table.ready`/`of` (count `ready`/`taken` seats),
`table.held_seat`/`held_seats` and `queue_state.held_seat` (the `held` seat),
`duo_ready` (ready seats of your pair). Lost: nothing the panel reads.
Not carried: `table.id` beyond `chat_log`, `experimental_policy` and
`matched` (stay in `room`/`state`).

## Migration

1. **Server, additive** (this PR): both servers' old frames unchanged; the
   matchmaker goldens and the offline-server fixtures filter out `table`, and
   `tests/test_table_frame.py` holds the frame to the old frames for every
   golden scenario and the room paths. The offline TS server does not send it
   yet.
2. **Client switch, the queue's table** (done): the queue store commits a
   held `queue_state` together with the `table` frame that follows it, and
   `fromQueue` draws seats, settings, timers and the panel's kind from the
   frame alone, with one seat builder for a table alone or shared.
   `queue_state` still carries the search (`since`, `count`, `front`,
   `party_id`, `leader`, `wait_players`, `bots_paused`, `offer`,
   `open_tables`, `panel_seq`, `still_here_until`, `duo`, `duo_ready`,
   `mode`, `cooldown_until`, `elsewhere`); its table fields are still sent
   and no longer read. The client's test sockets build the frame from each
   held `queue_state` (`web/src/queue/testFrames.ts`, held to the server's
   pairs in `web/src/queue/fixtures/table_frames.json`). Not yet: a room's
   seats from the `playing` frame, and the offline server's `table`.
3. **Retire, the queue's table** (done): `queue_state` carries the search
   alone; `table`, `code`, `allow_joiners`, `start_level`, `opener`,
   `held_seat`, `you_ready` and `bots_at` are gone (`bots_at` is
   `timers.bots`). The matchmaker goldens record the `table` frame, and the
   client's test sockets send each queue_state without those names. Not
   yet: `room`'s seat list, once a room's client reads the `playing` frame.
   The matcher keeps `Entry.code` (the code registry) and `Table.waiting`
   (a lone table and a waiting one start, time out and take joiners
   differently).
