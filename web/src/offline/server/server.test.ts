// @vitest-environment node
/// <reference types="node" />
// Holds the offline server to server/shengji/api/server.py: replays the solo
// games recorded by server/scripts/gen_offline_server_fixtures.py (same seeds,
// same deck shuffle, same human driver) and compares every frame the human's
// socket receives, after normalising the environmental fields the fixture
// header lists. server_sessions.jsonl.gz starts each game with the client's
// create_room, add_bot, start_game chain (the generator's default flow);
// server_sessions_start.jsonl.gz with one create_room {start: true} (its
// "start" flow). Set OFFLINE_SERVER_FIXTURES to a directory to replay another
// fixture set.
import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { VirtualClock } from "./clock";
import { type Flow, HumanDriver } from "./driver";
import { IllegalPlay } from "../engine/legal";
import { DeckRng } from "./rng";
import { LocalServer } from "./server";
import { LocalSocket } from "./socket";

const DIR = process.env.OFFLINE_SERVER_FIXTURES ?? fileURLToPath(new URL("../fixtures", import.meta.url));

interface Header {
  format: number;
  games: number;
  rounds: number;
  human: string;
  firstDeck: string[];
  normalized: Record<string, string>;
  stats: Record<string, number>;
}
interface SessionRecord {
  seed: number;
  rounds: number;
  config: { startLevel: string | null; throws: boolean };
  frames: number;
  digests: string;
}
type Frame = Record<string, unknown> & { type: string };

function normalize(msg: Frame): Frame {
  const out: Frame = { ...msg };
  if ("room" in out) out.room = "ROOM";
  if (out.type === "resume") out.token = "TOKEN";
  if (out.type === "chat") out.t = 0;
  if (out.type === "chat_history") {
    out.messages = (out.messages as Frame[]).map((m) => ({ ...m, room: "ROOM", t: 0 }));
  }
  return out;
}

function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v !== null && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return Object.fromEntries(Object.keys(o).sort().map((k) => [k, sortKeys(o[k])]));
  }
  return v;
}

/** json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True). */
export function canonical(msg: unknown): string {
  return JSON.stringify(sortKeys(msg)).replace(/[\u0080-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}

const digest = (msg: Frame) => createHash("sha256").update(canonical(msg)).digest("hex").slice(0, 8);

async function playSession(rec: SessionRecord, human: string, flow: Flow): Promise<Frame[]> {
  const clock = new VirtualClock();
  const server = new LocalServer({ clock, seed: () => rec.seed });
  const liveRound = () => [...server.rooms.values()][0]?.round ?? null;
  const driver = new HumanDriver(rec.rounds, liveRound, rec.config.throws, flow);
  const socket = new LocalSocket(server);
  const frames: Frame[] = [];
  let done = false;
  let failure: string | null = null;
  socket.onopen = () => {
    const create: Record<string, unknown> = { type: "create_room", name: human };
    if (flow === "start") create.start = true;
    if (rec.config.startLevel !== null) create.start_level = rec.config.startLevel;
    socket.send(JSON.stringify(create));
  };
  socket.onmessage = (ev) => {
    const msg = JSON.parse(ev.data as string) as Frame;
    frames.push(normalize(msg));
    if (msg.type === "error") failure = `server refused the driver: ${JSON.stringify(msg)}`;
    if (msg.type === "left" || msg.type === "error") {
      done = true;
      return;
    }
    for (const action of driver.react(msg)) socket.send(JSON.stringify(action));
  };
  await clock.run(() => done || frames.length > 20_000);
  if (failure) throw new Error(`seed ${rec.seed}: ${failure}`);
  return frames;
}

function readLines(name: string): string[] {
  return gunzipSync(readFileSync(join(DIR, name))).toString("utf8").split("\n").filter((l) => l.length);
}

const FIXTURES: [string, Flow][] = [
  ["server_sessions.jsonl.gz", "chain"],
  ["server_sessions_start.jsonl.gz", "start"],
];

describe.each(FIXTURES)("offline server vs server.py (recorded solo games, %s)", (file, flow) => {
  const [headerLine, ...lines] = readLines(file);
  const header = JSON.parse(headerLine) as Header;

  it("draws mulberry32's outputs, as the Python DeckRng does", () => {
    const r = new DeckRng(1);
    expect([r.nextU32(), r.nextU32(), r.nextU32()]).toEqual([2693262067, 11749833, 2265367787]);
  });

  it("deals the fixtures' decks from their seeds", () => {
    const first = JSON.parse(lines[0]) as SessionRecord;
    expect(new DeckRng(first.seed).deck()).toEqual(header.firstDeck);
  });

  it("sends every recorded frame, identical after normalisation", async () => {
    expect(header.format).toBe(1);
    expect(lines.length).toBe(header.games);
    expect(Object.keys(header.normalized).sort()).toEqual(["room", "t", "token"]);
    const mismatches: string[] = [];
    const counts: Record<string, number> = { games: 0, frames: 0 };
    for (const line of lines) {
      const rec = JSON.parse(line) as SessionRecord;
      const frames = await playSession(rec, header.human, flow);
      counts.games += 1;
      counts.frames += frames.length;
      for (const f of frames) counts[`frames_${f.type}`] = (counts[`frames_${f.type}`] ?? 0) + 1;
      const got = frames.map(digest).join("");
      if (got !== rec.digests || frames.length !== rec.frames) {
        let i = 0;
        while (i < frames.length && got.slice(8 * i, 8 * i + 8) === rec.digests.slice(8 * i, 8 * i + 8)) i++;
        mismatches.push(
          `seed ${rec.seed}: ${frames.length}/${rec.frames} frames, first difference at frame ${i}: ` +
            (i < frames.length ? canonical(frames[i]).slice(0, 600) : "(no frame)"),
        );
        if (mismatches.length >= 3) break;
      }
    }
    console.log(JSON.stringify({ dir: DIR, file, counts }));
    expect(mismatches).toEqual([]);
    expect(counts.games).toBe(header.games);
    expect(counts.frames).toBe(header.stats.frames);
    // the start flow's only room frame is the one create_room sends
    if (flow === "start") expect(counts.frames_room).toBe(header.games);
  }, 600_000);
});

/** One socket on a fresh server: sends `messages` in order, then runs the
 *  clock until `until` holds for the frames so far or nothing is left. */
async function exchange(messages: Record<string, unknown>[], until: (frames: Frame[]) => boolean = () => false) {
  const clock = new VirtualClock();
  const server = new LocalServer({ clock, seed: () => 7 });
  const socket = new LocalSocket(server);
  const frames: Frame[] = [];
  socket.onopen = () => {
    for (const m of messages) socket.send(JSON.stringify(m));
  };
  socket.onmessage = (ev) => frames.push(JSON.parse(ev.data as string) as Frame);
  await clock.run(() => until(frames), 10_000);
  return { server, frames, room: () => [...server.rooms.values()][0] };
}

const seatNames = (room: { seats: { name: string; isBot: boolean }[] }) => room.seats.map((s) => [s.name, s.isBot]);
const ALL_SEATED = [["You", false], ["Bot 1", true], ["Bot 2", true], ["Bot 3", true]];
const hasState = (frames: Frame[]) => frames.some((f) => f.type === "state");

describe("starting a room with empty seats, as server.py does", () => {
  it("start_game seats a bot named for its seat in every empty seat", async () => {
    const { frames, room } = await exchange(
      [{ type: "create_room", name: "You" }, { type: "add_bot" }, { type: "start_game" }],
      hasState,
    );
    expect(frames.filter((f) => f.type === "error")).toEqual([]);
    expect(seatNames(room())).toEqual(ALL_SEATED);
    expect(room().game).not.toBeNull();
  });

  it("create_room with start: true sends one room frame, then the game", async () => {
    const { frames, room } = await exchange(
      [{ type: "create_room", name: "You", start: true, start_level: "5" }],
      hasState,
    );
    expect(frames.map((f) => f.type)).toEqual(["resume", "chat_history", "room", "state"]);
    expect((frames[2].players as unknown[]).length).toBe(1);
    expect(seatNames(room())).toEqual(ALL_SEATED);
    expect(room().game).not.toBeNull();
    expect(room().startLevel).toBe("5");
  });

  it("a start_game after create_room's start is refused", async () => {
    const { frames } = await exchange(
      [{ type: "create_room", name: "You", start: true }, { type: "start_game" }],
      (fs) => fs.some((f) => f.type === "error"),
    );
    expect(frames.find((f) => f.type === "error")).toEqual({ type: "error", message: "Game already started." });
  });

  it.each([false, "true", 1, null])("start: %j leaves the room in its lobby", async (start) => {
    const { frames, room } = await exchange([{ type: "create_room", name: "You", start }]);
    expect(frames.map((f) => f.type)).toEqual(["resume", "chat_history", "room"]);
    expect(seatNames(room())).toEqual([["You", false]]);
    expect(room().game).toBeNull();
  });

  it("a refused start leaves the lobby and sends the creator the error", async () => {
    const clock = new VirtualClock();
    const server = new LocalServer({ clock, seed: () => 7 });
    const handle = server.handleAction.bind(server);
    server.handleAction = (room, seat, msg) => {
      if (msg.type === "start_game") throw new IllegalPlay("Refused for the test.");
      handle(room, seat, msg);
    };
    const socket = new LocalSocket(server);
    const frames: Frame[] = [];
    socket.onopen = () => socket.send(JSON.stringify({ type: "create_room", name: "You", start: true }));
    socket.onmessage = (ev) => frames.push(JSON.parse(ev.data as string) as Frame);
    await clock.run(() => false, 10_000);
    expect(frames.map((f) => f.type)).toEqual(["resume", "chat_history", "room", "error"]);
    expect(frames[3]).toEqual({ type: "error", message: "Refused for the test." });
    const room = [...server.rooms.values()][0];
    expect(seatNames(room)).toEqual([["You", false]]);
    expect(room.game).toBeNull();
  });
});
