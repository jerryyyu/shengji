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
| `set_start_level` | `start_level` (same values) | host, lobby only; refused once the game has started |
| `join_room` | `room` (4-letter code), `name`, optional `seat`, optional `token` (from `resume`) | lobby, OR mid-game to claim a bot's or a dropped human's seat |
| `peek_room` | `room` | anytime, WITHOUT joining — answered with `room_seats` |
| `code_lookup` | `code` | anytime, guests too, WITHOUT joining — answered with `code_kind` (see "Codes") |
| `chat` | `text` (<=300 chars) | after joining |
| `add_bot` | — | host, in lobby or between rounds |
| `remove_bot` | — | host, lobby (removes last bot) |
| `start_game` | — | host, lobby, exactly 4 players |
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

### `{type: "room", room: string, you: number, host: number, start_level: string, ready: number[], players: RoomPlayer[]}`
Sent in lobby. `RoomPlayer = {seat: number, name: string, is_bot: boolean, connected: boolean}`. Seats 0–3. Teams: seats 0+2 vs 1+3.

`start_level` is the rank BOTH teams begin at: set at `create_room`, changeable
by the host with `set_start_level` until the game starts, and echoed to everyone
so a joiner knows what game they are taking a seat in. A team wins a game by
successfully DEFENDING at `A`, so a higher start level is simply a shorter game.
The room then plays on (see `games_won` below).

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

Room codes and pair codes are one space: 4 characters from
`ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no `I`, `O`, `0` or `1`). A new room's
code is never the code of a live pair, and a new pair's code is never the code
of a live room, so a code names at most one thing. Codes are compared after
trimming and uppercasing.

A client that does not know which kind a code is sends
`{type: "code_lookup", code}` and gets `{type: "code_kind", code, kind}`, with
`code` normalised and `kind` one of:

- `"room"`: a live room. Continue with `peek_room` / `join_room`.
- `"party"`: a live pair. Continue with `party_join`, which needs sign-in (a
  guest gets `signed_in_only`).
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
(`since`, `deadline`, `cooldown_until`, `expires_at`, `bots_at`) are Unix
seconds from the server clock; `deadline_in` is relative seconds. Refusals are
`error` frames with a `code`.

### Client → Server

| type | fields | effect |
|------|--------|--------|
| `queue_join` | optional `party_id` | queue alone, or (party leader only) as the pair; a member of a full party always queues as the pair |
| `queue_leave` | — | leave the queue (leader only for a pair); during a ready check this is a decline |
| `match_accept` | `match_id` (required) | accept the ready check named by `match_id`; it must be your current one and its deadline not passed |
| `match_decline` | `match_id` (required), optional `keep_waiting` | decline the ready check named by `match_id` (same rule as `match_accept`); with `keep_waiting: true` on a bot-fill match the entry stays queued, its wait restarted, with no cooldown |
| `queue_start_bots` | — | leave the queue and start a rated game at once: solo = you + 3 bots; pair (leader only) = the pair (seats 0+2) vs 2 bots |
| `party_create` | — | create a pair party (or resend yours); answered with `party` |
| `party_invite` | — | the same as `party_create`: the party's `code` is the invite |
| `party_join` | `code` | join a friend's party by its code (pair codes share the room code space; see "Codes") |
| `party_leave` | — | leave the party; it dissolves and the other member is told. A queued pair leaves the queue; during a ready check it is a decline |

Error codes: `signed_in_only` (guest), `in_room`, `rate_limited`
(`queue_join` 10 and `party_*` 20 per account per minute), `cooldown` (with
`cooldown_until`, `cooldown_secs`), `not_leader`, `bad_party`,
`party_incomplete`, `party_changed`, `partner_unavailable` (the partner has no
lobby socket), `not_queued`, `match_pending` (a match already formed for you:
answer the ready check), `no_match` (no ready check is open for you),
`stale_match` (a `match_accept` or `match_decline` whose `match_id` is
missing, is not your current ready check, or arrived after its deadline; a
late answer is the timeout: you get `queue_removed {reason: "missed"}` first),
`start_failed`,
`party_not_found`, `party_full`, `party_busy` (the leader is queued),
`in_queue`, `in_party`, `not_in_party`.

### Server → Client

- `queue_state {queued, count, since?, front?, party_id?, leader?, bots_at?, replaced?}`:
  your entry, after every change to it and on reconnect. `front` marks an entry
  requeued at the front after someone else missed a ready check that every
  member of this entry had accepted. `replaced:
  true` tells an older socket that a newer one of the same account now holds
  the entry (one entry per account).
- `queue_count {count}`: to every lobby socket, signed in or not; players
  queued, including those in a ready check. At most one per second; a newly
  connected lobby socket gets the current count if it is above zero.
- `match {match_id, deadline, deadline_in, size, bots, party_id}`: a ready
  check. `size` is the number of humans who must accept, `bots` the bot seats.
- `match_ready {match_id, accepted, of, names?}`: after each accept, counts
  only; `names` (the humans, seat order) only once everyone has accepted.
- `match_started {match_id, room, rated}`: the room was created and started
  for you; `match_id` is null for `queue_start_bots`. It arrives with the usual
  `resume`, `chat_history`, `room` and `state` frames: the socket now holds its
  seat exactly as after `join_room`. `room` and `state` of such a room carry
  `matched: true`.
- `match_cancelled {match_id, reason}`: the ready check ended without you being
  at fault (`player_missed`, `keep_waiting`, `server_error`); a `queue_state`
  follows. After `server_error` the room was never left behind: you are back
  in the lobby and queued at the front, even if its `resume` or
  `match_started` frames already reached you.
- `queue_removed {reason, cooldown_until, match_id?, by?}`: you are out of the
  queue. `declined` and `missed` carry a 30 s cooldown; `away` (your socket was
  gone over 10 s, or at the start of an accepted match) and `in_room` carry
  none (`cooldown_until: null`). For a pair, `by` names the member who missed or
  left, and both members get it.
- `party {party_id, code, you_lead, members: [{name, leader, you}], expires_at}`.
- `party_closed {party_id, reason, by?, you?}`: `left` (`by` who left) or
  `expired` (5 minutes without queueing).

### Matching

The server runs a pass every 2 s (`server/shengji/api/matchmaking.py`; the
numbers are named constants there):

1. Waiting entries are ordered front-of-line first, then longest wait. A pair
   is one entry at the mean of its two ratings; bots count as
   `ratings.BOT_RATING`.
2. The anchor is the first entry. The entries whose rating lies within the
   anchor's window are added closest first until four players are found: ±100
   for the first 20 s of the anchor's wait, ±250 until 40 s, then any. A pair
   anchor takes another pair if one fits, else two solos. If the anchor cannot
   be matched, nobody behind it is matched on that pass.
3. From 60 s the anchor's match is completed with bots: the 1–3 humans who
   fit, the rest bots.
4. Teams (seats 0+2 vs 1+3): of the three pairings, those that keep each pair
   together; with bots, those that give each team a human where any does; then
   the smallest gap in team-average rating. A lone pair gets both bots on the
   other team; a pair and a solo get one bot as the solo's partner.
5. Every human gets a 10 s ready check. When all accept, the server creates an
   ordinary room, seats everyone, adds the bots and starts it; ratings are the
   ordinary room ratings (the round-start snapshot of signed-in seats). A
   decline or timeout removes that entry (the whole pair, for a pair) with a
   30 s cooldown. The others keep their original wait; an entry whose every
   member had accepted goes to the front, one with a member who had not
   answered yet (a pair with one acceptance included) keeps its place with no
   front priority and no cooldown. The deadline is checked when an answer
   arrives, so a late accept never starts a room.

A queued socket that closes keeps its place for 10 s; a new socket of the same
account within that time takes the entry back (and gets `queue_state`). After
10 s the entry is dropped with `queue_removed {reason: "away"}` and no
cooldown. A disconnected entry is not matched while it may still come back.
`create_room` or `join_room` that seats the socket ends its queue entry (a
ready check in progress counts as a decline); a failed join leaves it queued.

## Reconnect & lifecycle

Rejoining with `join_room` and the stored `token` (or, for a disconnected seat, the same name, trimmed and case-folded) reclaims the seat, and the current `state` is resent. Bots act automatically after a short delay.

A room survives with **no humans connected for 5 minutes** before being deleted, so refreshes and network blips can resume the game. If the current turn's human stays disconnected for **30 seconds**, the server's bot plays that turn (and keeps doing so until they reconnect).

`leave_room` is the explicit exit: in the lobby the seat is freed (host passes to the first remaining human; a room with only bots left is deleted). Mid-game the seat is kept reclaimable (bots cover it, same as a disconnect) but the leaver's client should clear its saved room. The server confirms with `{type: "left"}`, after which the same connection may `create_room`/`join_room` again.
