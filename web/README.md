# Web client

React + TypeScript + Vite. `npm run dev` (expects the game server on :8000),
`npm run build` writes `dist/`, which the server serves in production.

This file documents what is NOT obvious from reading the components: the
protocol contract, and the invariants that have each been broken at least
once. Component-level detail stays in the components.

## Layout

| file | role |
|---|---|
| `ws.ts` | the single connection — auto-reconnect with backoff, re-joins the saved room, buffers chat. Everything else talks to the server through `conn`. |
| `App.tsx` | routes server messages to screens; owns `game` state and the lobby/table decision. |
| `components/Lobby.tsx` | name, create/join, invite links, mid-game seat picker. |
| `components/Table.tsx` | the game screen: hand, trick area, opponents, chat, x-ray. |
| `components/Hud.tsx` | room code (tap to copy an invite link), levels, phase. |
| `components/RoundEndModal.tsx` | round result and the ready-to-continue tally. |
| `components/ChatPanel.tsx` | overlay chat; system lines render centred/italic. |
| `protocol.ts` | the wire types — keep in sync with `server/shengji/api/server.py`. |

## Protocol contract

The server sends **two different shapes** depending on room state, and
conflating them has caused bugs:

- **Lobby** (`game is None`) → `{"type": "room", ...}`: seats, host, `ready`.
- **In game** → `{"type": "state", ...}`: the full game view for one seat.

They are not interchangeable. Any field the client needs during a game must be
in `state_for()`, not only in `room_json()`. The round-end ready tally was
added to `room_json` alone, so the client rendered "0/N ready" and the
Next-round button never disabled.

Client → server messages worth knowing:

- **`peek_room`** — who is sitting where, *without* joining; answered with
  `room_seats`. The lobby uses it to decide between joining straight through
  and showing the seat picker.
- **`join_room`** with an optional `seat`. Reclaim by name is normalised
  (trimmed, case-folded), so returning as "Amy " recovers the seat left by
  "amy" instead of being told the room is full.
- **`join_room`** seat semantics — claims that specific bot seat. If
  the seat was taken between the peek and the join, the server replies
  `seat_unavailable` and the client re-peeks rather than accepting a
  different one: **a different seat means a different team.**

## Invariants (each violated at least once)

1. **Chat can arrive before `<Table>` exists.** Scrollback is delivered on
   join, ahead of the first `state`. `ws.ts` buffers it and `Table` seeds from
   `conn.chatHistory()` on mount — subscribing alone loses it. The buffer
   clears when leaving a room, **not** on reconnect, because the server
   replays its own scrollback and the two would double up.
2. **Invite links must not steal the name field.** `?room=CODE` prefills the
   code and focuses the name input; it does not auto-submit, because a
   returning player has a saved name and would be thrown into the room before
   they could change it. Auto-join happens only when the link also carries
   `?name=`. Any lobby action calls `clearInvite()` so the parameter cannot
   steer a later flow.
3. **Only CONNECTED humans count toward the round-end tally.** A player who
   drops during the round-end screen is dropped from the count server-side and
   must be filtered client-side too, or the display contradicts the server's
   own advance condition.
4. **Typing must not fire hotkeys.** The x-ray panel is bound to `x`; the chat
   input calls `stopPropagation()` on keydown and the global handler ignores
   events targeting inputs, textareas, and contenteditable.
5. **The takeover countdown ticks client-side.** `takeover_in` arrives with a
   state, and states are event-driven, not per-second — `useCountdown` restarts
   from the server's number whenever it changes, so the display can never drift
   away from the server's own deadline.
6. **The chat launcher appears only with more than one human** — solo-vs-bots
   should not show a chat button.

## Testing

There is no client test suite yet. The protocol guarantees are covered
server-side in `server/tests/test_server_ws.py`, which drives real WebSockets.
That file exists because `peek_room` shipped **entirely unimplemented** on the
server while the client was already sending it, and the Python suite stayed
green — nothing spoke the wire protocol.

`npm run build` type-checks, and that is all it does. It cannot see a missing
handler, a field absent from a payload, or a tally that is never recomputed;
all three shipped green. Treat a green build as "it compiles", never as "it
works".

Wanted, roughly in priority order: Vitest + React Testing Library covering
invite precedence, the seat-picker request/response cycle, round-ready
rendering, and chat-before-state.
