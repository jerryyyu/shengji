// @vitest-environment node
/// <reference types="node" />
// The canonical table_* names on the device: each one, sent where the page
// sends it, gets exactly the frames its old name gets (tables.py's rewrite,
// mirrored by tables.ts); and every message the page can send offline is
// either answered by the offline server or named here as one it never answers.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ClientMsg } from "../../protocol";
import { VirtualClock } from "./clock";
import { LocalServer } from "./server";
import { LOCAL_MESSAGES, LocalSocket } from "./socket";
import { CANONICAL, LOBBY } from "./tables";

type Frame = Record<string, unknown> & { type: string };
type Msg = Record<string, unknown>;
/** A message sent `at` seconds after the socket opens (0 when absent). */
type Step = Msg & { at?: number };

const FRAME_CAP = 40;

/** The environmental fields: a room code and a resume token are random, a
 *  chat line carries the wall clock. */
function normalize(f: Frame, code: string | null, token: string | null): unknown {
  const text = JSON.stringify(f);
  const out = JSON.parse(
    text.split(code ?? "\u0000").join("ROOM").split(token ?? "\u0000").join("TOKEN"),
  ) as Frame;
  if (out.type === "chat") out.t = 0;
  if (out.type === "chat_history") out.messages = (out.messages as Msg[]).map((m) => ({ ...m, t: 0 }));
  return out;
}

/** One fresh server and up to two sockets in turn: the first sends `first`
 *  and closes when `reconnect` holds; the second then sends `second`, with
 *  `$code` (`$lcode` lower-cased) and `$token` replaced by the first
 *  socket's room and resume token.
 *  Frames are those of every socket, normalised, up to FRAME_CAP. */
async function scenario(first: Step[], second: Step[] | null = null) {
  const clock = new VirtualClock();
  const server = new LocalServer({ clock, seed: () => 11 });
  const frames: Frame[] = [];
  let code: string | null = null;
  let token: string | null = null;
  const open = (steps: Step[], after: () => void) => {
    const socket = new LocalSocket(server);
    socket.onopen = () => {
      for (const { at, ...m } of steps) {
        const bound = JSON.parse(JSON.stringify(m).replace(/\$lcode/g, (code ?? "").toLowerCase()).replace(/\$code/g, code ?? "").replace(/\$token/g, token ?? ""));
        clock.setTimeout(() => socket.send(JSON.stringify(bound)), at ?? 0);
      }
      const last = Math.max(0, ...steps.map((s) => s.at ?? 0));
      clock.setTimeout(after, last + 0.01);
    };
    socket.onmessage = (ev) => {
      const f = JSON.parse(ev.data as string) as Frame;
      if (f.type === "resume") token = f.token as string;
      if (f.type === "room" && typeof f.room === "string") code = f.room;
      frames.push(f);
    };
    return socket;
  };
  const a = open(first, () => {
    if (second === null) return;
    a.close();
    open(second, () => {});
  });
  await clock.run(() => frames.length >= FRAME_CAP, 100_000);
  return { server, frames: frames.map((f) => normalize(f, code, token)) };
}

// create_room starts the game at once, so every room step below is in play
const CREATE = { type: "create_room", name: "You" };

/** [label, old-name steps, canonical steps, optional second-socket steps for each]. */
const PAIRS: [string, Step[], Step[], Step[]?, Step[]?][] = [
  ["table_allow_joiners = allow_joiners",
    [CREATE, { type: "allow_joiners", on: false, at: 1 }], [CREATE, { type: "table_allow_joiners", on: false, at: 1 }]],
  ["table_chat = chat", [CREATE, { type: "chat", text: " hi ", at: 1 }], [CREATE, { type: "table_chat", text: " hi ", at: 1 }]],
  ["table_leave = leave_room", [CREATE, { type: "leave_room", at: 1 }], [CREATE, { type: "table_leave", at: 1 }]],
  ["table_leave outside a room = queue_leave", [{ type: "queue_leave" }, CREATE], [{ type: "table_leave" }, CREATE]],
  ["table_start outside a room = its queue meaning", [{ type: "table_unready" }, CREATE], [{ type: "table_start", on: false }, CREATE]],
  ["table_join = join_room (resume by token)",
    [CREATE], [CREATE],
    [{ type: "join_room", room: "$code", name: "You", token: "$token" }],
    [{ type: "table_join", code: " $lcode ", name: "You", token: "$token" }]],
  ["table_join unknown code = join_room unknown room",
    [{ type: "join_room", room: "ZZZZ", name: "You" }], [{ type: "table_join", code: "ZZZZ", name: "You" }]],
  ["table_join without a code = join_room without a room",
    [{ type: "join_room", room: "", name: "You" }], [{ type: "table_join", name: "You" }]],
  ["table_join from a seat = join_room from a seat",
    [CREATE, { type: "join_room", room: "ZZZZ", name: "You" }], [CREATE, { type: "table_join", code: "ZZZZ", name: "You" }]],
  ["table_peek = peek_room", [{ type: "peek_room", room: "ZZZZ" }], [{ type: "table_peek", code: "zzzz" }]],
  ["table_peek from a seat = peek_room from a seat",
    [CREATE, { type: "peek_room", room: "ZZZZ" }], [CREATE, { type: "table_peek", code: "ZZZZ" }]],
];

describe("each canonical table name gets its old name's frames", () => {
  it.each(PAIRS)("%s", async (_label, old, canonical, oldSecond, canonicalSecond) => {
    const a = await scenario(old, oldSecond ?? null);
    const b = await scenario(canonical, canonicalSecond ?? null);
    // a scenario that sent nothing back would compare equal for any name
    expect(a.frames.length).toBeGreaterThan(0);
    expect(b.frames).toEqual(a.frames);
  });

  it("covers every canonical name the offline server takes, the refused ones below", () => {
    const named = new Set(PAIRS.flatMap(([, , c, , c2]) => [...c, ...(c2 ?? [])].map((m) => m.type as string)));
    expect([...CANONICAL].filter((t) => !named.has(t) && !LOBBY.has(t))).toEqual([]);
  });
});

describe("a room's lobby controls, as server.py's", () => {
  it("refuses each one in play with Game already started", async () => {
    const { server } = await scenario([CREATE]);
    const room = [...server.rooms.values()][0];
    expect(room.game).not.toBeNull();
    for (const t of LOBBY) {
      expect(() => server.handleAction(room, 0, { type: t, seat: 1 }), t).toThrow("Game already started.");
    }
  });
});

// Every message type the page can send on its socket. ws.ts's Connection
// takes a ClientMsg, and offline the same Connection runs over LocalSocket,
// so the ClientMsg union is the page's sendable set; `satisfies` below makes
// tsc refuse a union member this table leaves out, or a name it adds that
// Sendable does not list. The rest of Sendable comes from outside the union:
// the telemetry batch (telemetry.ts sends it untyped) and the canonical name
// the page does not send (CANONICAL, checked against tables.py below). "local": the offline server answers it, so it must be in
// LOCAL_MESSAGES; anything else is why the device never answers it, so it
// must not be.
type Sendable = ClientMsg["type"] | "client_event" | "table_join";
const LOCAL = "local";
const QUEUE = "the matchmaking queue, which the device does not have";
const SENDABLE = {
  create_room: LOCAL, join_room: LOCAL, peek_room: LOCAL, leave_room: LOCAL, chat: LOCAL,
  allow_joiners: LOCAL, declare: LOCAL, pass_declare: LOCAL, bury: LOCAL,
  play: LOCAL, next_round: LOCAL,
  table_start: LOCAL, table_start_now: LOCAL, table_start_bots: LOCAL, table_allow_joiners: LOCAL,
  table_start_level: LOCAL, table_chat: LOCAL, table_leave: LOCAL, table_join: LOCAL, table_peek: LOCAL,
  ping: "the heartbeat of a network socket; the device's socket never drops",
  table_move: LOCAL,
  im_back: "the ranked move timer, which offline rooms do not run",
  report_player: "moderation, a service of the game server",
  code_lookup: "codes name the game server's rooms and tables",
  client_event: "telemetry, collected by the game server",
  queue_status: QUEUE, queue_join: QUEUE, queue_leave: QUEUE, table_unready: QUEUE,
  queue_start_bots: QUEUE, table_here: QUEUE, queue_wait_players: QUEUE, queue_allow_bots: QUEUE,
  party_create: QUEUE, party_join: QUEUE, party_leave: QUEUE,
  open_table_join: QUEUE, open_table_wait: QUEUE, open_table_show: QUEUE,
} satisfies Record<Sendable, string>;

describe("every message the page can send offline is answered or named", () => {
  const entries = Object.entries(SENDABLE) as [string, string][];

  it("puts every message the offline server answers in LOCAL_MESSAGES", () => {
    const missing = entries.filter(([t, why]) => why === LOCAL && !LOCAL_MESSAGES.has(t)).map(([t]) => t);
    expect(missing).toEqual([]);
  });

  it("keeps every message it never answers out of LOCAL_MESSAGES", () => {
    const leaked = entries.filter(([t, why]) => why !== LOCAL && LOCAL_MESSAGES.has(t)).map(([t]) => t);
    expect(leaked).toEqual([]);
  });

  it("lets through no message the page cannot send", () => {
    expect([...LOCAL_MESSAGES].filter((t) => !(t in SENDABLE))).toEqual([]);
  });

  it("names every canonical name of tables.py", () => {
    const py = readFileSync(fileURLToPath(new URL("../../../../server/shengji/api/tables.py", import.meta.url)), "utf8");
    const block = /CANONICAL = frozenset\(\{([^}]*)\}\)/.exec(py);
    expect(block).not.toBeNull();
    const names = [...block![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(names.length).toBeGreaterThan(0);
    expect(names.filter((t) => !(t in SENDABLE))).toEqual([]);
    expect(names.filter((t) => !CANONICAL.has(t))).toEqual([]);
    const lobby = /LOBBY = frozenset\(\{([^}]*)\}\)/.exec(py);
    expect(lobby).not.toBeNull();
    expect([...lobby![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort()).toEqual([...LOBBY].sort());
  });

});
