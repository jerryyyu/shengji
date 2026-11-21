// @vitest-environment node
/// <reference types="node" />
// The canonical table_* names on the device: each one, sent where the page
// sends it, is answered (tables.py's rewrite, mirrored by tables.ts), and the
// old name it replaced is refused as retired and changes nothing; and every
// message the page can send offline is either answered by the offline server
// or named here as one it never answers.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ClientMsg } from "../../protocol";
import { VirtualClock } from "./clock";
import { LocalServer } from "./server";
import { LOCAL_MESSAGES, LocalSocket } from "./socket";
import { CANONICAL, LOBBY, RETIRED, RETIRED_MESSAGE } from "./tables";

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
const CREATE = { type: "create_room", name: "You", start: true };
const RETIRED_FRAME = { type: "error", code: "retired", message: RETIRED_MESSAGE };

/** [label, canonical steps, optional second-socket steps, what the frames
 *  must show, the old name it replaced (in the step that carries `old`)]. */
const CASES: [string, Step[], Step[] | null, string, Msg][] = [
  ["table_allow_joiners", [CREATE, { type: "table_allow_joiners", on: false, at: 1 }], null,
    '"allow_joiners":false', { type: "allow_joiners", on: false }],
  ["table_chat", [CREATE, { type: "table_chat", text: " hi ", at: 1 }], null,
    '"text":"hi"', { type: "chat", text: " hi " }],
  ["table_leave", [CREATE, { type: "table_leave", at: 1 }], null, '"type":"left"', { type: "leave_room" }],
  ["table_join (resume by token)", [CREATE],
    [{ type: "table_join", code: " $lcode ", name: "You", token: "$token", expect: "room" }],
    "You reconnected", { type: "join_room", room: "$code", name: "You", token: "$token" }],
  ["table_join unknown code", [{ type: "table_join", code: "ZZZZ", name: "You" }], null,
    '"room_not_found"', { type: "join_room", room: "ZZZZ", name: "You" }],
  ["table_join without a code", [{ type: "table_join", name: "You" }], null,
    '"room_not_found"', { type: "join_room", room: "", name: "You" }],
  ["table_join from a seat", [CREATE, { type: "table_join", code: "ZZZZ", name: "You", at: 1 }], null,
    "Unknown action: join_room", { type: "join_room", room: "ZZZZ", name: "You" }],
  ["table_peek", [{ type: "table_peek", code: "zzzz" }], null, '"room_not_found"', { type: "peek_room", room: "ZZZZ" }],
  ["table_peek from a seat", [CREATE, { type: "table_peek", code: "ZZZZ", at: 1 }], null,
    "Unknown action: peek_room", { type: "peek_room", room: "ZZZZ" }],
];

/** `steps` with the canonical message (the last one) replaced by `by`. */
function swapLast(steps: Step[], by: Msg | null): Step[] {
  const { at } = steps[steps.length - 1];
  const head = steps.slice(0, -1);
  return by === null ? head : [...head, { ...by, ...(at !== undefined ? { at } : {}) }];
}

describe("each canonical table name, and the old name it replaced", () => {
  it.each(CASES)("%s is answered", async (_label, steps, second, sees) => {
    const { frames } = await scenario(steps, second);
    expect(JSON.stringify(frames)).toContain(sees);
  });

  it.each(CASES)("%s: the old name is refused and changes nothing", async (_label, steps, second, _sees, old) => {
    const [first, again] = second === null ? [swapLast(steps, old), null] : [steps, swapLast(second, old)];
    const [base, baseAgain] = second === null ? [swapLast(steps, null), null] : [steps, swapLast(second, null)];
    const a = await scenario(first, again);
    const b = await scenario(base, baseAgain);
    const refused = a.frames.findIndex((f) => JSON.stringify(f) === JSON.stringify(RETIRED_FRAME));
    expect(refused).toBeGreaterThanOrEqual(0);
    // both runs stop at FRAME_CAP, the refused one a frame early
    const rest = a.frames.filter((_, k) => k !== refused);
    expect(rest.length).toBeGreaterThanOrEqual(Math.min(b.frames.length, FRAME_CAP - 1));
    expect(rest).toEqual(b.frames.slice(0, rest.length));
  });

  it("covers every canonical name the offline server takes, the refused ones below", () => {
    const named = new Set(CASES.flatMap(([, c, c2]) => [...c, ...(c2 ?? [])].map((m) => m.type as string)));
    expect([...CANONICAL].filter((t) => !named.has(t) && !LOBBY.has(t))).toEqual([]);
  });

  it("refuses every retired name, outside a room and from a seat", async () => {
    for (const t of RETIRED) {
      const m = { type: t, ...(t === "queue_join" ? { code: "ABCD" } : {}), on: false, text: "x" };
      const outside = await scenario([m]);
      expect(outside.frames, t).toEqual([RETIRED_FRAME]);
      const seated = await scenario([CREATE, { ...m, at: 1 }]);
      expect(seated.frames.filter((f) => (f as Frame).type === "error"), t).toEqual([RETIRED_FRAME]);
    }
    // the search keeps its name: the device has no queue, so it goes nowhere
    expect((await scenario([{ type: "queue_join", mode: "casual" }])).frames).toEqual([]);
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
// the telemetry batch (telemetry.ts sends it untyped). "local": the offline
// server answers it, so it must be in LOCAL_MESSAGES; anything else is why
// the device never answers it, so it must not be.
type Sendable = ClientMsg["type"] | "client_event";
const LOCAL = "local";
const QUEUE = "the matchmaking queue, which the device does not have";
const SENDABLE = {
  create_room: LOCAL, declare: LOCAL, pass_declare: LOCAL, bury: LOCAL,
  play: LOCAL, next_round: LOCAL,
  table_start: LOCAL, table_start_now: LOCAL, table_start_bots: LOCAL, table_allow_joiners: LOCAL,
  table_start_level: LOCAL, table_bot_level: LOCAL, table_chat: LOCAL, table_leave: LOCAL, table_join: LOCAL, table_peek: LOCAL,
  ping: "the heartbeat of a network socket; the device's socket never drops",
  table_move: LOCAL,
  im_back: LOCAL,
  report_player: "moderation, a service of the game server",
  block_player: "moderation, a service of the game server",
  client_event: "telemetry, collected by the game server",
  queue_status: QUEUE, queue_join: QUEUE, table_here: QUEUE, queue_wait_players: QUEUE,
  queue_allow_bots: QUEUE, party_leave: QUEUE,
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
    for (const [name, set] of [["LOBBY", LOBBY], ["RETIRED", RETIRED]] as const) {
      const block = new RegExp(`\\n${name} = frozenset\\(\\{([^}]*)\\}\\)`).exec(py);
      expect(block, name).not.toBeNull();
      expect([...block![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort(), name).toEqual([...set].sort());
    }
    expect(py).toContain(`RETIRED_MESSAGE = "${RETIRED_MESSAGE}"`);
  });

  it("sends no retired name the page could type", () => {
    expect(Object.keys(SENDABLE).filter((t) => RETIRED.has(t) && t !== "queue_join")).toEqual([]);
  });

});
