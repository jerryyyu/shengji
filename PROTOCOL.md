# Sheng Ji WebSocket Protocol (v1)

Single WebSocket endpoint: `ws://localhost:8000/ws`. All messages are JSON objects with a `type` field. The handshake may carry the optional `sj_session` cookie (docs/accounts.md): the server then remembers the account on the seat and, when `name` is empty, uses the account's first name; the wire protocol itself is unchanged. The server is authoritative: after any change it broadcasts a full personalized `state` to every player. The client renders state; it never computes rules.

## Card codes

A card is a string code:

- Suited: suit letter + rank symbol. Suits `S H D C`. Ranks `2 3 4 5 6 7 8 9 10 J Q K A`. Examples: `"S2"`, `"H10"`, `"DA"`, `"CJ"` (club jack).
- Jokers: `"LJ"` = little/black joker, `"BJ"` = big/red joker.

Two decks are used, so each code appears twice. Every physical card instance has a numeric `id` (0–107) unique within the round. Hands are lists of `{id, code}`. When the client acts on cards it sends **ids**; when the server describes other players' plays it sends **codes** only.

## Client → Server

| type | fields | when |
|------|--------|------|
| `create_room` | `name` (player display name), optional `start_level` (rank both teams start at: `"2"`..`"10"`, `"J"`, `"Q"`, `"K"`, `"A"`; omit for `"2"`) | anytime before joining |
| `set_start_level` | `start_level` (same values) | host (the opener), lobby only; refused once the game has started, and in a ranked room ("A ranked table starts at level 2."): every rated game starts at `"2"`. A real change clears every Start tap (`lobby_ready`) |
| `set_ranked` | `on: boolean` | host (the opener), lobby only, created rooms only: whether the room is ranked (see "Ranked rooms"); refused once the game has started. On sets `start_level` back to `"2"`. A real change clears every Start tap |
| `swap_seats` | `a`, `b` (seat positions), optional `expect` | lobby: the host exchanges any two positions; anyone else moves themselves (one of `a`, `b` is their own seat, the other empty) until they tap Start |
| `remove_player` | `seat`, optional `expect` | host, lobby: that occupant leaves the room |
| `allow_joiners` | `on: boolean` | anyone seated at an ordinary room, ranked or casual (lobby or in play): whether the queue may offer its bot seats to newcomers (see "Open tables"). On at creation; refused in a test room |
| `join_room` | `room` (4-letter code), `name`, optional `seat`, optional `token` (from `resume`) | lobby, OR mid-game to claim a bot's or a dropped human's seat |
| `peek_room` | `room` | anytime, WITHOUT joining — answered with `room_seats` |
| `code_lookup` | `code` | anytime, guests too, WITHOUT joining — answered with `code_kind` (see "Codes") |
| `chat` | `text` (<=300 chars) | after joining |
| `add_bot` | — | host, in lobby or between rounds |
| `remove_bot` | — | host, lobby (removes last bot) |
| `start_game` | — | host (the opener), lobby: the game starts at once, bots in every empty seat ("Start now" once others sit; see "Room lobby") |
| `lobby_ready` | optional `on: boolean` (default `true`) | anyone seated in a created room's lobby: their Start tap; the game starts when every connected person has tapped it. `on: false` takes it back |
| `declare` | `card_ids: number[]` (1 or 2 ids of a valid declaration) | anytime during `deal` or `declare` phase |
| `pass_declare` | — | `declare` phase (marks you done with the declare window) |
| `bury` | `card_ids: number[]` (exactly 8) | you are banker, phase `bury` |
| `play` | `card_ids: number[]` | your play turn |
| `next_round` | — | phase `round_end`; EVERY connected human must send it before the round advances |
| `leave_room` | — | anytime after joining; server replies `{type:"left"}` |

Invalid actions get an `error` message; state is unchanged.

## Server → Client

### `{type: "error", message: string, code?: string}`

Codes: `room_not_found`, `room_full` (every seat held by a CONNECTED human),
`choose_seat` (seats exist but each belongs to a dropped player — the client
should re-peek and offer the picker rather than auto-taking one),
`seat_unavailable` (the seat was claimed
between a peek and the join — the client should re-peek rather than accept a
different seat, since a different seat means a different TEAM).
`code` is set for machine-readable cases: `"room_not_found"` (the room no
longer exists — the client should clear its saved room and return to the
lobby instead of retrying), and `"bad_start_level"` (`create_room` carried a
`start_level` that is not a known rank). An unknown `start_level` is REFUSED,
never coerced to `"2"`: silently downgrading it would hand the player a game
their own lobby misdescribes. No room is created, and the socket stays usable.
`"test_room_unavailable"` refuses a `create_room` that asks for a guarded test
room (`test_policy`) when the server has them off (production does); such rooms
add an `experimental_policy` field to `room` and `state`.

### `{type: "room", room: string, you: number, host: number, opener: number, start_level: string, ready: number[], players: RoomPlayer[], allow_joiners?: boolean, start_now_in?: number, ranked?: true, rankable?: true}`
Sent in lobby. `RoomPlayer = {seat: number, name: string, is_bot: boolean, connected: boolean}`. Seats 0–3. Teams: seats 0+2 vs 1+3.

### Room lobby

`opener` is the same seat as `host`: the creator, and when the opener leaves
the lobby, the next person round the table from the opener's seat (the room
stays open). Only the opener sets the starting level and Ranked. `ready` is the
seats that tapped Start (`lobby_ready`); the game starts when every connected
person at the table has. A person who tapped Start keeps their seat until they
take the tap back. `start_now_in` is sent only while someone besides the opener
is seated: the seconds until the client offers the opener "Start now", 30 s
after the latest person sat down (ticked down locally). The server does not
hold `start_game` back: an older client's host Start still starts at once.
`allow_joiners` (every ordinary room; on at creation) says whether the queue
may offer the room's bot seats once its game is in play.

`start_level` is the rank BOTH teams begin at: set at `create_room`, changeable
by the host with `set_start_level` until the game starts, and echoed to everyone
so a joiner knows what game they are taking a seat in. A team wins a game by
successfully DEFENDING at `A`, so a higher start level is simply a shorter game.
The room then plays on (see `games_won` below).

### Ranked rooms

Only a ranked room's rounds are rated. A room from the ranked queue
(`matched: true`) always is; a room from the casual queue never is (it is an
ordinary unranked room, with no move timer). A room made with `create_room` (Play bots and a continued saved
game included) starts unranked; its host may send `set_ranked {on}` until the
game starts, and `room` and `state` then carry `ranked: true` (absent when
off) to every seat. Once the game starts the mode is fixed for it. `set_ranked`
is refused for anyone but the host, after the game has started, and in a
queue or test room. A ranked room starts at level `"2"`, fixed, so every
rated game is the same game: `set_ranked {on: true}` sets `start_level` back
to `"2"`, `set_start_level` is refused while the room is ranked, and the
game starts at `"2"` whatever the room held. A casual room keeps its host's
level.

A created ranked room keeps the open join of any created room: guests may sit
and join by code or invite link, and the queue-only refusals
(`ranked_sign_in`, `ranked_queue_only`) and open-table invite path belong to
queue rooms only. Its signed-in seats are rated from the round-start snapshot;
a guest seat counts at the bot anchor rating, and a guest seated does not void
the round (a queue room's round that starts with a guest is not rated). A
person who claims a seat mid-round is rated from the next round. An unranked
room is never rated: its `round_result` carries no `rating`, and the client
shows no rating line.

### Trick plays carry a `shape`

Each play in `trick` / `last_trick` includes `shape`: `"single" | "pair" |
`"tractor" | "throw"`, decided by the ENGINE. Clients must not infer it —
whether pairs form a tractor depends on consecutiveness under the trump
ordering, where trump-rank cards and jokers sit outside their printed ranks.
The voice announcer inferred it and called a two-pair 甩牌 a 拖拉机.

### `{type: "room_seats", room, in_game: bool, seats: [{seat, name, is_bot, connected, team, claimable, reserved_secs, controller}]}`

Reply to `peek_room`. Read-only: it does not seat the asker and reveals no
private information. The lobby uses it to show a seat picker when a game is in
progress and more than one bot seat is open — which bot you replace decides
who your partner is.

### `{type: "code_kind", code, kind}`

Reply to `code_lookup`; see "Codes".

### `{type: "chat_history", room, through_id, messages[]}`

One authoritative snapshot per attach, sent **before** the first state. The
client REPLACES that room's log with it — never merges — so a reconnect cannot
double the log.

### `{type: "chat", room, id, seat, name, text, t}`

`seat: -1` marks a SYSTEM line (joins, leaves, seat claims, bot takeover and
handback). `id` is monotonic **per room**, so a client drops any id already in
its snapshot. Ids restart per room; always key the log by `room`.

### `{type: "resume", token, gen}`

Sent on every attach. `token` is the seat's opaque identity — names are NOT
identity, and the token is what lets a player resume their own seat even while
a stale socket of theirs is still open. Store it and send it back in
`join_room`. `gen` is the connection generation that now owns the seat.

### `{type: "state", ...GameState}`
Full personalized game state:

```ts
interface GameState {
  type: "state";
  room: string;
  you: number;                    // your seat
  phase: "deal" | "declare" | "bury" | "play" | "round_end" | "game_over";
  players: {
    seat: number; name: string; is_bot: boolean; connected: boolean;
    team: 0 | 1;                  // seat % 2
    cards_left: number;
    is_banker: boolean;
    controller: "human" | "bot" | "bot_cover";  // bot_cover = a bot covering a dropped human
    takeover_in: number | null;   // seconds before the bot covers a dropped human
    reserved_for: string | null;  // the dropped owner's name while a bot covers the seat
    reserved_secs: number | null; // seconds the seat stays reserved for its owner
    left?: true;                  // the owner pressed Leave: the bot plays the seat at once
                                  // (takeover_in is null); absent otherwise
  }[];
  hand: { id: number; code: string }[];   // your cards, sorted server-side
  levels: [string, string];       // rank symbol per team, e.g. ["2","5"]
  games_won: [number, number];    // games each team has won by defending at A
  banker: number | null;          // banker seat (null before first declaration of game)
  trump: { suit: string | null; rank: string; declarer: number | null } | null;
    // suit: "S"|"H"|"D"|"C"|"NT" (jokers declared = no-trump). rank e.g. "2".
  turn: number | null;            // whose action is awaited (bury/play); null during deal/declare
  // --- deal & declare phases ---
  declare_options: number[][];    // arrays of your card ids forming valid declarations, [] if you can't beat the current one
  current_declaration: { seat: number; cards: string[] } | null;
  passed: number[];               // seats done with the declare window (cleared when someone declares)
  declare_deadline: number | null; // seconds left in the post-deal declare window, to a tenth; null outside it
  // --- play phase ---
  trick: { leader: number; plays: { seat: number; cards: string[] }[] } | null;
  last_trick: { leader: number; plays: { seat: number; cards: string[] }[]; winner: number; points: number } | null;
  attacker_points: number;        // points captured by non-banker team this round
  ready: number[];              // seats that confirmed the round end;
                                // the round advances only when every
                                // CONNECTED human appears here
  kitty_count: number;            // 8 during play, shown face-down
  // --- round_end / game_over ---
  round_result: {
    attacker_points: number;      // FINAL TOTAL, kitty bonus already included
    kitty_points: number;         // the (multiplied) kitty portion OF that total, else 0
                                  // trick points alone = attacker_points - kitty_points
    kitty_cards: string[];        // revealed at round end
    winner_team: 0 | 1;
    level_change: number;         // levels gained by winner
    next_banker: number;
    new_levels: [string, string];
    game_over: boolean;           // false in rooms: a table plays on
    games_won: [number, number];
    point_scored: boolean;        // this round won a game (a defence at A); levels restart
  } | null;
  message: string | null;         // transient info line ("Alice declared Hearts", "Throw failed \u2014 forced to play S3+S3", ...)
  notice: {                       // outlives `message`; null when there is none
    id: number;                   // bumps per notice, so a client dismissal binds to one notice
    kind: "failed_throw";
    seat: number;
    attempted: string[];          // what the player tried to throw
    forced: string[];             // what the engine made them play instead
  } | null;
}
```

`message` is cleared by the very next play at the table, which with bots is about
0.7 s. A `notice` survives eight further plays, the rest of the current trick plus
the next one, so a refused throw can still be read after the fact. It carries the
ATTEMPTED cards, which `message` never did, and never the opposing card that beat
the throw: that is hidden information the thrower has not earned by throwing. A
client may dismiss a notice early; dismissal is per-viewer and is never sent to the
server, so one player dismissing does not blank it for anyone else.


## Codes

Room codes, pair codes and table codes are one space: 4 characters from
`ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no `I`, `O`, `0` or `1`). A new code is
never the code of a live room, pair or queued table, so a code names at most
one thing. A queued table's code becomes its room's code when the table
starts (see "Table codes"). Codes are compared after
trimming and uppercasing.

A client that does not know which kind a code is sends
`{type: "code_lookup", code}` and gets `{type: "code_kind", code, kind}`, with
`code` normalised and `kind` one of:

- `"room"`: a live room. Continue with `peek_room` / `join_room`.
- `"party"`: a live pair. Continue with `party_join`, which needs sign-in (a
  guest gets `signed_in_only`).
- `"table"`: a queued table that has not started (see "Table codes").
  Continue with `queue_join {code}`. An older client reads it as no code.
- `"none"`: nothing live has that code (or it is not 4 letters and digits).

The lookup changes nothing on the server, works from a seat or the lobby,
signed in or not, and is limited to 30 per account (a guest: per socket) per
minute (`error` with code `rate_limited`). A room wins a code that a room and
a pair both hold, which only codes issued before the shared space can do.
`peek_room`, `join_room` and `party_join` are unchanged, so a client that
never sends `code_lookup` keeps working. Invite links are `/?code=CODE`;
`/?room=CODE` and `/?party=CODE` still open a room and a pair.

## Flow

1. `create_room` → `room` message with code; others `join_room`; host `add_bot` to fill; `start_game` requires 4 seats.
2. **deal**: cards are dealt one at a time (~10s for the full deal); each new state shows your hand growing and every player's `cards_left`. At ANY point during dealing, a player holding a valid declaration (`declare_options` non-empty) may send `declare`: single trump-rank card sets that suit; a pair of trump-rank cards beats a single; a joker pair beats both and declares NT. `turn` is null throughout — declaration is a race, not a rotation.
3. **declare**: a short grace window (~5s) after the last card so anyone can still (over-)declare. `pass_declare` marks you done (you appear in `passed`); the window closes when every connected human has passed or the timer runs out — a new declaration resets both. If nobody declared at all, the server flips the kitty to fix trump. First round: first declarer's seat becomes banker; later rounds the banker is fixed by rotation and declaring only sets the suit.
4. **bury**: banker's hand shows 33 cards (25 + 8 kitty); banker sends `bury` with 8 ids.
5. **play**: `turn` rotates; send `play` with card ids. Server validates follow rules, resolves tricks (`last_trick` updates, `trick` resets to winner leading).
6. **round_end**: `round_result` populated; every connected human sends `next_round` before the next round starts (banker/levels advance per result).
7. A successful defence at level A scores a game: `point_scored` is set, `games_won` increments and both teams restart at the room's start level. Rooms never reach `game_over` (they are created with no game limit); the phase exists for engine games with a limit.

## Matchmaking queue

Signed-in players can queue for a rated game instead of sharing a room code.
Invite rooms (`create_room` / `join_room`) are unchanged. Every queue message is
sent from the lobby (a socket that holds no seat); a seated socket may send only
`party_leave`, and anything else is refused with code `in_room`. Times
(`since`, `expires_at`, `bots_at`, a table's `timer.at` and seat `since`) are
Unix seconds from the server clock. Refusals are `error` frames with a `code`.

### Client → Server

| type | fields | effect |
|------|--------|--------|
| `queue_join` | optional `party_id`, optional `mode` (`"ranked"`, the default, or `"casual"`), optional `code`, optional `allow_joiners` (default `true`), optional `start_level` (default `"2"`), optional `duo` (default `false`) | queue alone, or (party leader only) as the pair; a member of a full party always queues as the pair. An entry is seated with, offered and starts only tables of its own `mode`: a casual one never meets a ranked one, and its table or bot game is an unrated room. Guests may queue in either mode. Any other `mode` is refused with `bad_mode`; while queued, `queue_join` keeps the entry's mode. `allow_joiners` and `start_level` are your own table's settings (see "Table codes"); a ranked table refuses any level but `"2"` with `ranked_level_fixed`. With `code`, sit at that queued table instead, in its mode and with its settings (the other four fields are ignored). `duo: true` opens your own table with your partner seat held for a friend (see "Duo tables"); a non-boolean is `bad_setting`, and a member of a full party queues as the pair, holding nothing |
| `table_allow_joiners` | `on: boolean` | your table's Allow joiners, alone or at a waiting table; only the table's opener (its leader, for a pair) may switch it, anyone else is refused with `not_opener`, and the whole table takes it. 20 per account per minute (with `table_move`) |
| `table_start_level` | `start_level` | your casual table's starting level: the opener only (`not_opener`), never at a ranked table (`ranked_level_fixed`), `bad_start_level` for an unknown level. A real change clears every Start at the table |
| `queue_leave` | — | leave the queue (leader only for a pair); at a waiting table this frees your seat |
| `table_start` | optional `panel_seq` | tap Start at your waiting table (leader only for a pair, for both): your entry is ready for good; the table starts when every entry at it is ready. With `panel_seq` (see `queue_state`) a tap sent against a panel you no longer see is refused with `panel_changed` |
| `table_move` | `seat` | move yourself to an empty seat at your waiting table: singles only (`pair_seats_fixed`), before your Start (`already_ready`); `seat_taken` for a seat someone holds, `bad_seat` for anything but 0-3. 20 per account per minute |
| `table_here` | — | answer the "still here?" prompt (`queue_state.still_here_until`); any other queue message from the table answers it too |
| `table_chat` | `text` | a chat line to everyone at your table (`not_seated` when you are not queued): your waiting table, or while you wait alone your own table, which only you (and a Duo partner) hear. Validated as room `chat` is: trimmed, at most 300 chars, an empty line ignored; 30 per person per minute (`rate_limited`). Kept in memory only (the last 50), never in a log. Lines sent alone merge into the waiting table you sit at, in time order, and either log is the room's opening scrollback (`chat_history`) when the game starts |
| `queue_start_bots` | optional `panel_seq` | alone in the queue: leave it and start a rated game at once: solo = you + 3 bots; pair (leader only) = the pair (seats 0+2) vs 2 bots. At a waiting table it is `table_start` (what an older client's bar button sends) |
| `queue_wait_players` | — | "Only tables with people" on (leader only for a pair): the entry keeps its wait, place in line and seat, but its own timer never starts a bot game (`bots_at: null`, `wait_players: true`); it still sits at a table and rides a switch-off player's timer there. Leaving and queueing again turns it off |
| `queue_allow_bots` | — | undo `queue_wait_players` (leader only): the entry's timer is due 60 s from now (a new `bots_at`); the wait itself is kept |
| `party_create` | — | create a pair party (or resend yours); answered with `party` |
| `party_invite` | — | the same as `party_create`: the party's `code` is the invite |
| `party_join` | `code` | join a friend's party by its code (pair codes share the room code space; see "Codes") |
| `party_leave` | — | leave the party; it dissolves and the other member is told. A queued pair leaves the queue (and its seats); a Duo made at a table splits instead, as `queue_leave` does (see "Duo tables") |
| `match_accept`, `match_decline` | — | retired with the ready check: always refused with `no_match` |
| `open_table_join` | `room`, `seat`, optional `panel_seq` | take that seat at the open table offered to you (see "Open tables"); the first confirm wins |
| `open_table_wait` | — | keep looking instead; the offered table is not offered again by itself in this search (a fresh `queue_join` forgets it) |
| `open_table_show` | optional `room` | show again the offer of an open table you waited on (the bar's chip), with a fresh 20 s |

Error codes: `signed_in_only` (guest), `in_room`, `rate_limited`
(`queue_join` 10 and `party_*` 20 per account per minute), `not_leader`,
`bad_party`, `party_incomplete`, `party_changed`, `partner_unavailable` (the
partner has no lobby socket), `not_queued`, `not_seated` (`table_start` while
not at a waiting table), `no_match`, `start_failed`, `party_not_found`,
`party_full`, `party_busy` (the leader is queued), `in_queue`, `in_party`,
`not_in_party`, `cooldown` (with `cooldown_until`: you left a table you
joined, see "Open tables"), `no_offer`, `bad_seat`, `seat_taken` (another
newcomer confirmed that seat first; the offer is re-sent without it, or the
seat of a `table_move` is held), `table_closed`, `pair_seats_fixed`,
`already_ready`, `panel_changed` (a fresh `queue_state` follows),
`table_not_found` (no queued table has that `code`), `own_table`,
`table_full`, `same_device` (a device of yours already sits at that table),
`not_opener`, `ranked_level_fixed`, `bad_start_level`, `bad_setting`. A signed-in
account with a connected seat in a ranked game in play is refused
`queue_join`, `queue_start_bots`, `party_create`, `party_join` and `open_table_join` from any
other socket with `account_in_game`.

### Server → Client

- `queue_state {queued, count, mode?, since?, front?, party_id?, leader?, bots_at?, wait_players?, bots_paused?, table?, offer?, open_tables?, replaced?, panel_seq?, still_here_until?, code?, allow_joiners?, start_level?, opener?, duo?, held_seat?}`:
  your entry, after every change to it or to its table, and on reconnect.
  `mode` is the search's mode (`"ranked"` or `"casual"`). `code`,
  `allow_joiners` and `start_level` are your table's, alone or at a waiting
  table (see "Table codes"); `opener` is true when you opened it (always,
  alone), so you set its level and Allow joiners. `duo` is true for a Duo
  table's opener and for both members of a Duo made there; `held_seat` is
  the seat your entry holds for your friend (2 while alone), else the
  table's `held_seat`, or null.
  `bots_at` is when this entry's own timer starts a bot game (60 s after
  joining, or after `queue_allow_bots`); it is null and `wait_players` is true
  while the switch is on. `front` marks an entry put back at the front after
  its room failed to start. `table` is null while you are alone in the queue,
  else your waiting table:
  `{id, code, opener, held_seat, held_seats, seats, you, timer, ready, of, you_ready, waiting_for}`
  (`code` the table's code, `opener` the opener's seat, `held_seats` the
  empty seats held for a Duo opener's friend and `held_seat` the first of
  them, else null). `seats` has
  four items in seat order (team 0 at seats 0+2), `null` for an empty seat (a
  bot plays it), else `{name, you, ready, reconnecting, since, pair, leader}`;
  `you` is your seat; `timer` is `{at, name, you}` (the earliest `bots_at`
  among the table's switch-off entries, named by that entry's leader) or null
  when every switch is on; `ready`/`of` count people; `waiting_for` names the
  other entries (by leader) yet to tap Start. `replaced: true` tells an older
  socket that a newer one of the same account now holds the entry (one entry
  per account). Older clients ignore `table`. `offer` is an open table
  offered to you now, `{room, seats, pick, expires_at, round_end}`: `seats`
  in seat order, each `{name, bot, open}` (`open`: you may take it), `pick`
  the seat picked for you; null when none is. `open_tables` counts the open
  tables you waited on that can still be joined; `bots_paused` is true while
  an offer is up or such a table exists, and `bots_at` is then null (the
  wait stands still and runs on from where it stopped). `panel_seq` is a
  number, increasing across the server process, that changes whenever what
  your panel shows changes kind or target (alone, an offer of one room, a
  waiting table) and stays put across re-renders of the same panel; send it
  back with a Start or Join so a tap aimed at one panel never acts on the
  next. `still_here_until` is set while you are asked "still here?" at a
  waiting table with no timer: answer before then or you leave (`idle`).
- `presence {tables, playing, waiting, ranked, casual}`: to every lobby socket
  when the counts change, at most once per second, and at once to a new lobby
  socket when any is above zero. `waiting`: people queued; `tables`: games in
  play that a newcomer could join (a seat open, Allow joiners on, someone
  connected), ranked or casual; `ranked` and `casual` split `tables` by mode;
  `playing`: connected people seated at those tables. Counts only, no names
  or codes.
- `table_chat {table, id, seat, name, text, t}`: a line of your table's
  chat, to everyone there, the sender included; `table` is the waiting
  table's id, or null while you wait alone; `id` counts up per table, `seat`
  is the sender's seat (alone: the seat you take against bots), `t` Unix
  seconds.
- `table_chat_history {table, messages}`: the table's chat so far (each
  `{id, seat, name, text, t}`), replacing what you hold: when you sit down at
  a table that has some, when a newcomer's lines from alone merge in (to
  everyone there; every line then takes a new id), or when you come back.
- `table_moved {name, seat, your_team}`: to everyone else at your waiting
  table when `name` moved to `seat`; `your_team` says whether that seat is on
  your team. It comes right after the `queue_state` that shows the new seats.
- `first_joiner {name, seat, move_secs, round_end}`: once per game started
  alone (`queue_start_bots` or the entry's own timer), to its people, when the
  first newcomer's Join lands. `move_secs` is the move clock that runs from
  now on (null without one); `round_end` says the newcomer plays from the
  next round.
- `queue_count {count}`: to every lobby socket, signed in or not; players
  queued, including those at waiting tables. At most one per second; a newly
  connected lobby socket gets the current count if it is above zero.
- `match_started {match_id, room, rated}`: the room was created and started
  for you; `match_id` is the waiting table's id, or null for a game started
  alone (`queue_start_bots` or the entry's own timer). It arrives with the
  usual `resume`, `chat_history`, `room` and `state` frames: the socket now
  holds its seat exactly as after `join_room`. `room` and `state` of such a
  room carry `matched: true`. There is no ready check before it. After
  `open_table_join` it is `match_started {match_id: null, room, rated,
  joining: true, seat}`: the seat is yours from the handover (see "Open
  tables").
- `match_cancelled {match_id, reason: "server_error"}`: the room could not be
  built; a `queue_state` follows. You were never left in a room: you are back
  in the lobby and queued at the front, unseated, even if its `resume` or
  `match_started` frames already reached you.
- `queue_removed {reason, cooldown_until: null, by?}`: you are out of the
  queue, with no cooldown: `away` (your socket was gone over 10 s alone, 60 s
  alone with "Wait for people" on, or 60 s at a waiting table, or was gone
  when the table's timer started it), `idle` (2 minutes at a waiting table
  without tapping Start or sending anything; at a table with no timer, 30 s
  after the "still here?" prompt) or `in_room`. For a pair, `by` names the member who left, and both
  members get it.
- `party {party_id, code, table, you_lead, members: [{name, leader, you}], expires_at}`.
  `table` is true for a Duo made at a table: it has no code of its own, and
  `code` is its table's while it is queued, else empty.
- `party_closed {party_id, reason, by?, you?}`: `left` (`by` who left) or
  `expired` (5 minutes without queueing).

### Matching

`server/shengji/api/matchmaking.py`; the numbers are named constants there.
Seating runs on every join and every 2 s:

1. Waiting entries (not at a table) are ordered front first, then longest
   wait. A pair is one entry at the mean of its two ratings.
2. Each takes a free place at an existing waiting table first, else opens a
   new table with the next waiting entry. Below 5 people queued (at tables or
   not) anyone sits with anyone; from 5, only within the entry's rating
   window: ±100 for its first 20 s, ±250 until 40 s, then any. Tables never
   merge.
3. Seats fill in arrival order, partner first: seat 0, then 2 (the first
   one's partner), then 1 and 3 (the other team). A pair takes seats 0+2 or
   1+3, whichever team is free (so a pair sits across from two singles);
   with neither free it waits for another table. Nobody is re-seated while
   waiting except by their own `table_move`; a leaver's seat is simply free,
   and a table left with one entry dissolves (that entry is alone again, its
   tick gone, its own timer kept).

A waiting table starts, with bots in its empty seats, when it has four
people, when every entry at it has tapped Start, or at its timer. The first
two wait while a member is reconnecting; the timer does not, and an entry
whose socket is still gone at that moment leaves (`away`). An entry alone in
the queue starts with bots at its own `bots_at`. The room is an ordinary
rated room (ratings are the round-start snapshot of signed-in seats); the
server records on it the table it came from and how many people sat there.

A queued socket that closes keeps its place for 10 s alone (60 s alone with
"Wait for people" on), 60 s at a waiting table (its seat shows `reconnecting`, its Start is kept); a new socket
of the same account within that time takes the entry back. After that the
entry is dropped with `queue_removed {reason: "away"}`. A seated entry that
has not tapped Start and sent nothing for 2 minutes is dropped with
`queue_removed {reason: "idle"}`; at a table with no timer it is first asked
"still here?" (`still_here_until`) and dropped 30 s later unless it answers. A disconnected entry that is not seated is
not seated while it may still come back. `create_room` or `join_room` that
seats the socket ends its queue entry (and frees its seat); a failed join
leaves it queued.

### Table codes

Every queued entry has a table code, from the moment it joins: alone, the
code of its own table (`queue_state.code`, with `table` still null, so an
older client sees no change); at a waiting table, the table's code is its
opener's (the first arrival still there), and every seated entry's own code
still leads to that table. When the table (or the lone entry's bot game)
starts, the room takes the table's code, so an invite link `/?code=CODE`
made before the game still opens the room after it. A code is released when
its entry leaves the queue.

`queue_join {code}` (the link, or a typed code that `code_lookup` calls
`"table"`) seats you at that table: opening it with its host when the host is
alone, in the table's mode and with its settings, outside the rating window
and whatever Allow joiners says. Every other queue rule holds: the cooldown,
the account-in-game refusals, one device per table (`same_device`), a full
table (`table_full`); a guest joins a ranked table at the guest rating, as
from Play. Already queued elsewhere: `in_queue`.

A table's settings are the room's when it starts. Allow joiners (default
on): off, Play seats no stranger with the table and offers it no open
table, and the room starts with Allow joiners off; its code still works.
Starting level: a ranked table starts at `"2"`, fixed; a casual table's
opener picks it (`queue_join start_level`, `table_start_level`). Allow
joiners is the opener's switch too. The settings belong to the whole table,
so they stay when its opener leaves.

### Duo tables

`queue_join {mode, duo: true}` opens your own table, as Play does, with the
seat opposite you held for a friend (`held_seat`). There is no Duo code: the
table's code and its invite link are the Duo invite. The held seat is never
a stranger's: Play seats strangers in the other two seats only (under Allow
joiners, as at any table), a Duo opener is offered no open table while it
holds the seat, a seated stranger cannot `table_move` into it
(`seat_taken`), and a Duo opener opens its own table and never sits at
another's (two Duo openers never share one). A table that starts first
plays a bot in it.

The first single who joins by the table's code (`queue_join {code}`) takes
the held seat, and the two become one paired entry (`queue_state.duo`, a
`party` with `table: true`). From then on it is a pair: seated together,
matched and moved as a unit, its leader (the opener) taps Start for it, and
a ranked Duo is rated as a pair. Later code joiners, and a pair joining by
the code, take the open seats as at any table.

Before the game, one Leave (`queue_leave` or `party_leave`, from either
member) ends the Duo for the leaver only; the other is told with
`party_closed {by}` and keeps the table, its seat and its code. When the
partner leaves (or signs in from a guest, takes a seat elsewhere or stays
away), its seat is held again for the opener, at whichever table the pair
sits; when the opener leaves, the partner keeps the opener's code and, at
its own table, becomes the opener, and nothing is held. After the game the
pair stays paired, as a party pair does.

The `party_*` messages are unchanged for older clients: a party pair keeps
its own code and its leader alone cancels it.

### Open tables

A room in play, ranked or casual, is an open table while it has a bot seat, a
person connected and "Allow joiners" on (`allow_joiners`, any seated person
may send `{type: "allow_joiners", on}`; default on, created rooms included).
A test or evaluation room never is. Each open table has a mode: ranked
(queue-matched, or a created room switched to Ranked) or casual (any other
created room, or a casual queue room), and the queue offers it only to
entries of that mode. A newcomer who taps Play goes, in
order, to a waiting table if anyone is queued, else is offered the open table
with the most people (`queue_state.offer`, 20 s), else waits alone. A
signed-in entry not at a waiting table is offered one, at its join and
whenever a table opens; guests never are. A single may take any open seat. A
queued pair is offered a table only when two partner seats (opposite each
other) are open there, and gets those two together: each member's `offer`
has `pick` (its own seat) and `partner: {seat, name}` (null for a single);
neither picks, and either member's `open_table_join` takes both seats. The
pair is seated at one handover, when both seats can change hands, and both
are unranked for that round. Either member's `open_table_wait` is Wait for
both, at no cost. If either member leaves or drops before the handover, both
Joins end (the other gets `left {reason: "partner_left", message}`); only
the member who confirmed pays the join-then-leave cost for a leave. A table you waited on (or let
lapse) is not offered again by itself in this search (a fresh `queue_join`
forgets it; a table you joined and left stays barred); while it can still be joined your bot
wait is paused and `open_tables` puts a chip on the bar.

`open_table_join {room, seat}` takes any open seat (the lone player's
partner is picked by default). The bot keeps playing it until the handover:
at once if the seat owes nothing (dealing, declaring, someone else's bury, a
trick it already played to, a round end), else at the end of the current
trick, never in the middle of its bury. Until then the newcomer's socket gets
the seat's `state` frames with `joining_you: true` and may send only
`leave_room`; the table's frames carry `joining: [{seat, name, when}]`
(`when: "trick"`, then `"round"` for someone seated at a round end, who plays
from the next round). At the handover the socket holds the seat as after
`join_room` (`resume`, `chat_history`, `state`).

A newcomer seated mid-round at a ranked table is not rated for that round
(its `round_result` carries `unranked: "joined"`) and is rated from the next.
Leaving it before the handover, or leaving (or being away or taken over at
the end of) the round they joined mid-way: the seat is a bot's again and that
table is never offered to them again; at a ranked table `queue_join` is also
refused with `cooldown` for 1 minute, and after a seated leave their next
rated round anywhere is capped as a leave (kept in server memory). Leaving a
casual table costs nothing more, and neither does leaving at a round end, so
a casual table's frames never set `joined_round`.

A ranked table's invite link (its room code; "Copy invite link" stays in
the game menu) is the table's consent: `peek_room` answers `room_seats` with
`ranked: true`, `full` and `claimable` on the seats a newcomer may take, and
a signed-in account that holds no seat there joins with `join_room {room,
seat?}` exactly as from an offer (pending until the handover, first round
unranked), even with Allow joiners off. The cooldown, never-again and
carried-cap rules apply as to any newcomer. Refusals: `ranked_sign_in` for a
guest ("Sign in to join a ranked table."), `table_full` when no seat is
open, `seat_unavailable` when the chosen seat went, `cooldown`, and
`table_left` (they left this table after joining it).

From a round boundary, a seat whose player has been away (move timer) for
the whole previous round is offered too (`open: true` with the player's
name). Its player keeps it by tapping I'm back until the newcomer is seated
(the newcomer then gets `left {reason: "reclaimed", message}` and is back at
the front of the queue); once seated, the away player gets `left {reason:
"seat_given", message}`. A game that ends before the handover sends `left
{reason: "table_closed"}`.

## Reconnect & lifecycle

Rejoining with `join_room` and the stored `token` (or, for a disconnected seat, the same name, trimmed and case-folded) reclaims the seat, and the current `state` is resent. Bots act automatically after a short delay.

A room survives with **no humans connected for 5 minutes** before being deleted, so refreshes and network blips can resume the game. If the current turn's human stays disconnected for **30 seconds**, the server's bot plays that turn (and keeps doing so until they reconnect).

`leave_room` is the explicit exit: in the lobby the seat is freed (host passes to the first remaining human; a room with only bots left is deleted). Mid-game the seat is kept reclaimable (bots cover it, same as a disconnect) but the leaver's client should clear its saved room. The server confirms with `{type: "left"}`, after which the same connection may `create_room`/`join_room` again.
