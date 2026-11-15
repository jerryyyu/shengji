// @vitest-environment node
/// <reference types="node" />
// Holds the offline server to server/shengji/api/server.py: replays the solo
// games recorded by server/scripts/gen_offline_server_fixtures.py (same seeds,
// same deck shuffle, same human driver) and compares every frame the human's
// socket receives, after normalising the environmental fields the fixture
// header lists. Frames and keys only the online server sends are dropped from
// the recorded side; ../fixtures/online_only.json lists them, the generator
// reads the same file, and the offline server must send none of them.
// server_sessions_start.jsonl.gz starts each game with one
// create_room {start: true}, as the client's Play bots does. Set
// OFFLINE_SERVER_FIXTURES to a directory to replay another fixture set.
import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { VirtualClock } from "./clock";
import { HumanDriver } from "./driver";
import { IllegalPlay } from "../engine/legal";
import { DeckRng } from "./rng";
import { LocalServer } from "./server";
import { LOCAL_MESSAGES, LocalSocket } from "./socket";
import { RETIRED } from "./tables";

const DIR = process.env.OFFLINE_SERVER_FIXTURES ?? fileURLToPath(new URL("../fixtures", import.meta.url));
type OnlineOnly = Record<string, Record<string, string>>;
const ONLINE_ONLY = JSON.parse(
  readFileSync(fileURLToPath(new URL("../fixtures/online_only.json", import.meta.url)), "utf8"),
) as OnlineOnly;

interface Header {
  format: number;
  games: number;
  rounds: number;
  human: string;
  firstDeck: string[];
  normalized: Record<string, string>;
  onlineOnly: OnlineOnly;
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

/** The online-only frame type or keys `msg` carries, as "type" or "type.key". */
function onlineOnlyIn(msg: Frame): string[] {
  if (msg.type in ONLINE_ONLY.frames) return [msg.type];
  const found = Object.keys(ONLINE_ONLY[msg.type] ?? {})
    .filter((k) => k in msg)
    .map((k) => `${msg.type}.${k}`);
  const playerKeys = Object.keys(ONLINE_ONLY[`${msg.type}.players`] ?? {});
  for (const p of (msg.players as Record<string, unknown>[] | undefined) ?? []) {
    for (const k of playerKeys) if (k in p) found.push(`${msg.type}.players.${k}`);
  }
  return [...new Set(found)];
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

async function playSession(rec: SessionRecord, human: string): Promise<Frame[]> {
  const clock = new VirtualClock();
  const server = new LocalServer({ clock, seed: () => rec.seed });
  const liveRound = () => [...server.rooms.values()][0]?.round ?? null;
  const driver = new HumanDriver(rec.rounds, liveRound, rec.config.throws);
  const socket = new LocalSocket(server);
  const frames: Frame[] = [];
  let done = false;
  let failure: string | null = null;
  socket.onopen = () => {
    const create: Record<string, unknown> = { type: "create_room", name: human, start: true };
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

const FIXTURE = "server_sessions_start.jsonl.gz";

describe("offline server vs server.py (recorded solo games)", () => {
  const file = FIXTURE;
  const [headerLine, ...lines] = readLines(file);
  const header = JSON.parse(headerLine) as Header;

  it("draws mulberry32's outputs, as the Python DeckRng does", () => {
    const r = new DeckRng(1);
    expect([r.nextU32(), r.nextU32(), r.nextU32()]).toEqual([2693262067, 11749833, 2265367787]);
  });

  it("finds an online-only frame type and online-only keys", () => {
    expect(onlineOnlyIn({ type: "table" })).toEqual(["table"]);
    const state: Frame = { type: "state", matched: false, players: [{ seat: 0, left: false }, { seat: 1 }] };
    expect(onlineOnlyIn(state)).toEqual(["state.matched", "state.players.left"]);
    expect(onlineOnlyIn({ type: "state", players: [{ seat: 0 }] })).toEqual([]);
  });

  it("deals the fixtures' decks from their seeds", () => {
    const first = JSON.parse(lines[0]) as SessionRecord;
    expect(new DeckRng(first.seed).deck()).toEqual(header.firstDeck);
  });

  it("sends every recorded frame, identical after normalisation", async () => {
    expect(header.format).toBe(1);
    expect(lines.length).toBe(header.games);
    expect(Object.keys(header.normalized).sort()).toEqual(["room", "t", "token"]);
    // recorded against the list this checkout holds
    expect(header.onlineOnly).toEqual(ONLINE_ONLY);
    const mismatches: string[] = [];
    const leaks = new Set<string>();
    const counts: Record<string, number> = { games: 0, frames: 0 };
    for (const line of lines) {
      const rec = JSON.parse(line) as SessionRecord;
      const frames = await playSession(rec, header.human);
      counts.games += 1;
      counts.frames += frames.length;
      for (const f of frames) {
        counts[`frames_${f.type}`] = (counts[`frames_${f.type}`] ?? 0) + 1;
        for (const k of onlineOnlyIn(f)) leaks.add(k);
      }
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
    // a key the offline server starts sending leaves online_only.json
    expect([...leaks]).toEqual([]);
    expect(counts.games).toBe(header.games);
    expect(counts.frames).toBe(header.stats.frames);
    // a game's only room frame is the one create_room sends
    expect(counts.frames_room).toBe(header.games);
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
  it("create_room without start seats a bot named for its seat in every empty seat", async () => {
    const { frames, room } = await exchange([{ type: "create_room", name: "You" }], hasState);
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

  it("a Start now after create_room's start is refused", async () => {
    const { frames } = await exchange(
      [{ type: "create_room", name: "You", start: true }, { type: "table_start_now" }],
      (fs) => fs.some((f) => f.type === "error"),
    );
    expect(frames.find((f) => f.type === "error")).toEqual({ type: "error", message: "Game already started." });
  });

  it.each([false, "true", 1, null])("start: %j starts the game all the same", async (start) => {
    const { frames, room } = await exchange([{ type: "create_room", name: "You", start }], hasState);
    expect(frames.map((f) => f.type)).toEqual(["resume", "chat_history", "room", "state"]);
    expect(seatNames(room())).toEqual(ALL_SEATED);
    expect(room().game).not.toBeNull();
  });

  it("add_bot and the other retired names are refused, never answered as local messages", () => {
    for (const t of ["add_bot", "remove_bot", "remove_player", "set_ranked"]) {
      expect(LOCAL_MESSAGES.has(t)).toBe(false);
      expect(RETIRED.has(t)).toBe(true);
    }
  });

  it("a refused start discards the room: the creator gets the error, then left", async () => {
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
    expect(frames.map((f) => f.type)).toEqual(["resume", "chat_history", "room", "error", "left"]);
    expect(frames[3]).toEqual({ type: "error", message: "Refused for the test." });
    expect(server.rooms.size).toBe(0);
  });
});
