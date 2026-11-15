// @vitest-environment node
/// <reference types="node" />
// The release-bot bridge (pybot.ts): the requests the local server sends for
// bot decisions, and SmartBot taking over whenever the bot cannot answer.
//
// Request parity: web/ios/pybot/gen_bridge_fixtures.py ran the recorded solo
// games through server.py with SmartBot as the room bot and recorded, for each
// room-bot decision, the request built from the server's own round. Here the
// same games run on the local server with a stand-in for the native bot that
// answers as SmartBot does, so the games unfold as recorded; every request it
// receives must match, digest by digest, and every frame must still match the
// server_sessions fixture.
import { describe, expect, it } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { SmartBot, viewFor } from "../bot";
import type { Card } from "../engine/cards";
import { VirtualClock } from "./clock";
import { HUMAN_SEAT, HumanDriver } from "./driver";
import { DECISION_LIMIT, type DecisionRequest, MAX_FAILURES, type RemoteBot, nativeRemoteBot, parseResponse } from "./pybot";
import { LocalServer } from "./server";
import { LocalSocket } from "./socket";

const DIR = fileURLToPath(new URL("../fixtures", import.meta.url));

type Frame = Record<string, unknown> & { type: string };
interface GameRecord {
  seed: number;
  rounds: number;
  config: { startLevel: string | null; throws: boolean };
  requests: number;
  digests: string;
}
interface SessionRecord {
  seed: number;
  frames: number;
  digests: string;
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
function canonical(msg: unknown): string {
  return JSON.stringify(sortKeys(msg)).replace(/[\u0080-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}

const digest = (msg: unknown) => createHash("sha256").update(canonical(msg)).digest("hex").slice(0, 8);

/** A request as the round describes it: without its token and the verdicts it carries. */
function roundPart(req: DecisionRequest): DecisionRequest {
  const { token: _token, settle: _settle, ...rest } = req;
  return rest;
}

/** Every verdict the gate reached, in order: those sent on requests and those still queued. */
function verdictsOf(requests: DecisionRequest[], server: LocalServer): Map<string, boolean[]> {
  const out = new Map<string, boolean[]>();
  const all = [...requests.flatMap((r) => r.settle ?? []), ...server.remote!.unsent()];
  for (const [token, committed] of all) out.set(token, [...(out.get(token) ?? []), committed]);
  return out;
}

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

function readLines(name: string): string[] {
  return gunzipSync(readFileSync(join(DIR, name))).toString("utf8").split("\n").filter((l) => l.length);
}

/** A stand-in for the native bot: `answer` decides, from the live round. */
function standIn(answer: (req: DecisionRequest) => Promise<Card[] | null>): RemoteBot & { requests: DecisionRequest[] } {
  const requests: DecisionRequest[] = [];
  return {
    requests,
    ready: () => true,
    decide: (req) => {
      requests.push(structuredClone(req));
      return answer(req);
    },
  };
}

interface Session {
  frames: Frame[];
  server: LocalServer;
  ended: boolean;
}

async function playSession(
  seed: number,
  rounds: number,
  config: { startLevel: string | null; throws: boolean },
  makeRemote: (server: () => LocalServer, clock: VirtualClock) => RemoteBot | null,
): Promise<Session> {
  const clock = new VirtualClock();
  let server: LocalServer | null = null;
  server = new LocalServer({ clock, seed: () => seed, remote: makeRemote(() => server!, clock) });
  const liveRound = () => [...server!.rooms.values()][0]?.round ?? null;
  const driver = new HumanDriver(rounds, liveRound, config.throws);
  const socket = new LocalSocket(server);
  const frames: Frame[] = [];
  let done = false;
  socket.onopen = () => {
    const create: Record<string, unknown> = { type: "create_room", name: "You" };
    if (config.startLevel !== null) create.start_level = config.startLevel;
    socket.send(JSON.stringify(create));
  };
  socket.onmessage = (ev) => {
    const msg = JSON.parse(ev.data as string) as Frame;
    frames.push(normalize(msg));
    if (msg.type === "left" || msg.type === "error") {
      done = true;
      return;
    }
    for (const action of driver.react(msg)) socket.send(JSON.stringify(action));
  };
  await clock.run(() => done || frames.length > 20_000);
  return { frames, server, ended: done };
}

/** SmartBot's answer on the live round, as the room's own SmartBot would give it. */
function smartAnswer(server: () => LocalServer) {
  const bot = new SmartBot();
  return (req: DecisionRequest): Card[] | null => {
    const rnd = [...server().rooms.values()][0].round!;
    const view = viewFor(rnd, req.seat);
    if (req.kind === "declare") return bot.declare(view, req.final ?? false);
    return req.kind === "bury" ? bot.bury(view) : bot.play(view);
  };
}

describe("release-bot requests vs server.py's rounds", () => {
  const [headerLine, ...lines] = readLines("bridge_requests.jsonl.gz");
  const header = JSON.parse(headerLine) as { format: number; games: number; stats: Record<string, number> };
  const sessions = new Map<number, SessionRecord>();
  for (const l of readLines("server_sessions.jsonl.gz").slice(1)) {
    const rec = JSON.parse(l) as SessionRecord;
    sessions.set(rec.seed, rec);
  }

  it("sends the request the server's round describes, for every bot decision", async () => {
    expect(header.format).toBe(1);
    expect(lines.length).toBe(header.games);
    const mismatches: string[] = [];
    const counts: Record<string, number> = { games: 0, requests: 0 };
    for (const line of lines) {
      const rec = JSON.parse(line) as GameRecord;
      let remote: ReturnType<typeof standIn> | null = null;
      const { frames, server } = await playSession(rec.seed, rec.rounds, rec.config, (server) => {
        const answer = smartAnswer(server);
        remote = standIn((req) => Promise.resolve(answer(req)));
        return remote;
      });
      const requests = remote!.requests;
      counts.games += 1;
      counts.requests += requests.length;
      for (const r of requests) {
        counts[r.kind] = (counts[r.kind] ?? 0) + 1;
        expect(r.seat).not.toBe(HUMAN_SEAT);
      }
      const got = requests.map((r) => digest(roundPart(r))).join("");
      // every answer was played, so every decision is committed, exactly once
      const verdicts = verdictsOf(requests, server);
      expect(requests.every((r) => verdicts.get(r.token!)?.join() === "true")).toBe(true);
      expect(server.remote!.open.size).toBe(0);
      if (got !== rec.digests) {
        let i = 0;
        while (i < requests.length && got.slice(8 * i, 8 * i + 8) === rec.digests.slice(8 * i, 8 * i + 8)) i++;
        mismatches.push(`seed ${rec.seed}: ${requests.length}/${rec.requests} requests, first difference at ${i}: ` +
          (i < requests.length ? canonical(roundPart(requests[i])).slice(0, 400) : "(none)"));
      }
      // the bridge leaves the game itself exactly as server.py plays it
      const session = sessions.get(rec.seed)!;
      expect(frames.map(digest).join("")).toBe(session.digests);
      if (mismatches.length >= 3) break;
    }
    console.log(JSON.stringify({ bridge: counts }));
    expect(mismatches).toEqual([]);
    expect(counts.declare).toBe(header.stats.declare);
    expect(counts.bury).toBe(header.stats.bury);
    expect(counts.play).toBe(header.stats.play);
  }, 600_000);
});

describe("SmartBot takes over when the release bot cannot answer", () => {
  const config = { startLevel: null, throws: false };
  const seed = 20261112;

  async function baseline(): Promise<Frame[]> {
    return (await playSession(seed, 1, config, () => null)).frames;
  }

  it("plays the whole game with SmartBot when the bot never answers, one limit per stall", async () => {
    let remote: ReturnType<typeof standIn> | null = null;
    const { frames, server, ended } = await playSession(seed, 1, config, () => {
      remote = standIn(() => new Promise<Card[] | null>(() => {}));
      return remote;
    });
    expect(ended).toBe(true);
    // the first call stalls past its limit; after that the bot is busy, never asked again
    expect(remote!.requests.length).toBe(1);
    expect(server.remote!.stats.timeout).toBe(1);
    expect(server.remote!.stats.busy).toBe(0);
    // the stalled decision is dropped; its verdict waits for the next request
    expect(server.remote!.unsent()).toEqual([[remote!.requests[0].token, false]]);
    expect(frames.some((f) => f.type === "state" && f.phase === "round_end")).toBe(true);
  }, 60_000);

  it("falls back on errors and stops asking after repeated failures", async () => {
    const want = await baseline();
    let remote: ReturnType<typeof standIn> | null = null;
    const { frames, server } = await playSession(seed, 1, config, () => {
      remote = standIn(() => Promise.reject(new Error("interpreter crashed")));
      return remote;
    });
    expect(remote!.requests.length).toBe(MAX_FAILURES);
    expect(server.remote!.stats.error).toBe(MAX_FAILURES);
    const verdicts = verdictsOf(remote!.requests, server);
    expect(remote!.requests.map((r) => verdicts.get(r.token!)?.join())).toEqual(["false,false,false", "false,false", "false"]);
    expect(frames.map(digest)).toEqual(want.map(digest));
  }, 60_000);

  it("refuses an illegal answer and plays SmartBot's move instead", async () => {
    const want = await baseline();
    let remote: ReturnType<typeof standIn> | null = null;
    const { frames, server } = await playSession(seed, 1, config, (srv) => {
      const answer = smartAnswer(srv);
      remote = standIn((req) => Promise.resolve(req.kind === "play" ? ["BJ", "BJ", "BJ"] : answer(req)));
      return remote;
    });
    const plays = remote!.requests.filter((r) => r.kind === "play").length;
    expect(plays).toBe(MAX_FAILURES);
    expect(server.remote!.stats.invalid).toBe(MAX_FAILURES);
    // declarations were played and committed; the illegal plays were dropped
    const verdicts = verdictsOf(remote!.requests, server);
    for (const r of remote!.requests) expect(verdicts.get(r.token!)).toEqual([r.kind !== "play"]);
    expect(frames.map(digest)).toEqual(want.map(digest));
  }, 60_000);

  it("uses the bot's answers when they come in time, and drops a late one", async () => {
    let remote: ReturnType<typeof standIn> | null = null;
    let lateOnce = true;
    const { frames, server, ended } = await playSession(seed, 1, config, (srv, clock) => {
      const answer = smartAnswer(srv);
      remote = standIn((req) => {
        const cards = answer(req);
        if (req.kind === "play" && lateOnce) {
          lateOnce = false;
          // answers after the play limit: SmartBot has already played that turn
          return new Promise((resolve) => clock.setTimeout(() => resolve(cards), DECISION_LIMIT.play + 1));
        }
        return Promise.resolve(cards);
      });
      return remote;
    });
    expect(ended).toBe(true);
    const stats = server.remote!.stats;
    expect(stats.timeout).toBe(1);
    expect(stats.answered).toBeGreaterThan(50);
    expect(stats.answered + stats.timeout + stats.busy).toBe(stats.asked);
    // the late play is dropped, every other answer committed, each exactly once
    const late = remote!.requests.find((r) => r.kind === "play")!;
    const verdicts = verdictsOf(remote!.requests, server);
    for (const r of remote!.requests) expect(verdicts.get(r.token!)).toEqual([r !== late]);
    expect(server.remote!.open.size).toBe(0);
    expect(frames.some((f) => f.type === "state" && f.phase === "round_end")).toBe(true);
  }, 60_000);

  it("under autoplay plays a whole round with nobody at the table, asking only for bot seats", async () => {
    const clock = new VirtualClock();
    let server: LocalServer | null = null;
    const answer = smartAnswer(() => server!);
    const remote = standIn((req) => Promise.resolve(answer(req)));
    server = new LocalServer({ clock, seed: () => seed, remote, autoplay: true });
    const socket = new LocalSocket(server);
    let roundEnd = false;
    socket.onopen = () => socket.send(JSON.stringify({ type: "create_room", name: "You" }));
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as Frame;
      if (msg.type === "room") {
        const players = msg.players as unknown[];
        socket.send(JSON.stringify(players.length < 4 ? { type: "add_bot" } : { type: "start_game" }));
      }
      if (msg.type === "state" && msg.phase === "round_end") roundEnd = true;
    };
    await clock.run(() => roundEnd);
    expect(roundEnd).toBe(true);
    expect(remote.requests.filter((r) => r.kind === "play").length).toBeGreaterThan(20);
    expect(remote.requests.every((r) => r.seat !== HUMAN_SEAT)).toBe(true);
  }, 60_000);

  it("finds no plugin in a browser or in node", () => {
    expect(nativeRemoteBot()).toBeNull();
  });

  it("reads a response's cards and refuses a malformed one", () => {
    expect(parseResponse('{"cards":["S2","S2"],"seconds":0.1}')).toEqual(["S2", "S2"]);
    expect(parseResponse('{"cards":null}')).toBeNull();
    expect(() => parseResponse('{"seconds":1}')).toThrow();
    expect(() => parseResponse(42)).toThrow();
  });
});
