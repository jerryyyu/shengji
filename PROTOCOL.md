# Sheng Ji WebSocket Protocol (v1)

Single WebSocket endpoint: `ws://localhost:8000/ws`. All messages are JSON objects with a `type` field. The server is authoritative: after any change it broadcasts a full personalized `state` to every player. The client renders state; it never computes rules.

## Card codes

A card is a string code:

- Suited: suit letter + rank symbol. Suits `S H D C`. Ranks `2 3 4 5 6 7 8 9 10 J Q K A`. Examples: `"S2"`, `"H10"`, `"DA"`, `"CJ"` (club jack).
- Jokers: `"LJ"` = little/black joker, `"BJ"` = big/red joker.

Two decks are used, so each code appears twice. Every physical card instance has a numeric `id` (0–107) unique within the round. Hands are lists of `{id, code}`. When the client acts on cards it sends **ids**; when the server describes other players' plays it sends **codes** only.

## Client → Server

| type | fields | when |
|------|--------|------|
| `create_room` | `name` (player display name) | anytime before joining |
| `join_room` | `room` (4-letter code), `name` | lobby |
| `add_bot` | — | host, in lobby or between rounds |
| `remove_bot` | — | host, lobby (removes last bot) |
| `start_game` | — | host, lobby, exactly 4 players |
| `declare` | `card_ids: number[]` (1 or 2 ids of a valid declaration) | anytime during `deal` or `declare` phase |
| `pass_declare` | — | `declare` phase (marks you done with the declare window) |
| `bury` | `card_ids: number[]` (exactly 8) | you are banker, phase `bury` |
| `play` | `card_ids: number[]` | your play turn |
| `next_round` | — | phase `round_end`, any player (host advances) |

Invalid actions get an `error` message; state is unchanged.

## Server → Client

### `{type: "error", message: string, code?: string}`
`code` is set for machine-readable cases: `"room_not_found"` (the room no
longer exists — the client should clear its saved room and return to the
lobby instead of retrying).

### `{type: "room", room: string, you: number, host: number, players: RoomPlayer[]}`
Sent in lobby. `RoomPlayer = {seat: number, name: string, is_bot: boolean, connected: boolean}`. Seats 0–3. Teams: seats 0+2 vs 1+3.

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
  }[];
  hand: { id: number; code: string }[];   // your cards, sorted server-side
  levels: [string, string];       // rank symbol per team, e.g. ["2","5"]
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
  kitty_count: number;            // 8 during play, shown face-down
  // --- round_end / game_over ---
  round_result: {
    attacker_points: number;
    kitty_points: number;         // added (already multiplied) if attackers won last trick, else 0
    kitty_cards: string[];        // revealed at round end
    winner_team: 0 | 1;
    level_change: number;         // levels gained by winner
    next_banker: number;
    new_levels: [string, string];
    game_over: boolean;
  } | null;
  message: string | null;         // transient info line ("Alice declared Hearts", "Throw failed, forced to S3", ...)
}
```


## Flow

1. `create_room` → `room` message with code; others `join_room`; host `add_bot` to fill; `start_game` requires 4 seats.
2. **deal**: cards are dealt one at a time (~10s for the full deal); each new state shows your hand growing and every player's `cards_left`. At ANY point during dealing, a player holding a valid declaration (`declare_options` non-empty) may send `declare`: single trump-rank card sets that suit; a pair of trump-rank cards beats a single; a joker pair beats both and declares NT. `turn` is null throughout — declaration is a race, not a rotation.
3. **declare**: a short grace window (~5s) after the last card so anyone can still (over-)declare. `pass_declare` marks you done (you appear in `passed`); the window closes when every connected human has passed or the timer runs out — a new declaration resets both. If nobody declared at all, the server flips the kitty to fix trump. First round: first declarer's seat becomes banker; later rounds the banker is fixed by rotation and declaring only sets the suit.
4. **bury**: banker's hand shows 33 cards (25 + 8 kitty); banker sends `bury` with 8 ids.
5. **play**: `turn` rotates; send `play` with card ids. Server validates follow rules, resolves tricks (`last_trick` updates, `trick` resets to winner leading).
6. **round_end**: `round_result` populated; any human sends `next_round` to start the next round (banker/levels advance per result).
7. **game_over** when a team wins the round while on level A.

## Reconnect & lifecycle

Rejoining with `join_room` using the same name reclaims the seat if it's disconnected, and the current `state` is resent. Bots act automatically after a short delay.

A room survives with **no humans connected for 5 minutes** before being deleted, so refreshes and network blips can resume the game. If the current turn's human stays disconnected for **30 seconds**, the server's bot plays that turn (and keeps doing so until they reconnect).
