// @vitest-environment node
// The nearby table's guards against a person or a phone holding it up: the
// move clock for a present player who does nothing, lobby seats freed after
// a drop and bound to one phone, one look at the seats per link, resume
// tokens matched whole, names cleaned on the host, the liveness ping, and a
// fuzz of a seated joiner's frames paced under the rate limit.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { LOBBY_SEAT_HOLD, MOVE_TIMER } from "../server";
import { setNearbyForTests } from "./flag";
import { PEEK_SECONDS } from "./host";
import { validNearbyName } from "./names";
import { LIMITS, NEARBY_V, PING_TEXT, cleanJoinerMessage } from "./protocol";
import { NearbySocket } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";
import type { JoinLink } from "./transport";

beforeEach(() => setNearbyForTests(true));
afterEach(() => setNearbyForTests(null));

type Json = Record<string, unknown>;
type PlayerJson = { seat: number; name: string; connected: boolean; controller?: string; turn_deadline?: number | null; away?: boolean };
const rooms = (p: Player) => p.frames.filter((f) => f.type === "room");
const lastRoom = (p: Player) => rooms(p)[rooms(p).length - 1];
const errors = (p: Player) => p.frames.filter((f) => f.type === "error");

async function lobby(humans: number, drive = false, seed = 11): Promise<NearbyTable> {
  const t = new NearbyTable(seed, 1);
  await t.open(drive);
  for (let i = 1; i < humans; i++) await t.join(`P${i}`, { drive });
  return t;
}

async function started(humans: number, drive = false): Promise<NearbyTable> {
  const t = await lobby(humans, drive);
  t.send(t.host, { type: "table_start_bots" });
  await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
  return t;
}

/** A link with no client filter, as a modified joiner would open one. */
interface Raw { link: JoinLink; frames: Frame[]; closed: boolean }
async function raw(t: NearbyTable, device?: string): Promise<Raw> {
  const r: Raw = { link: null as unknown as JoinLink, frames: [], closed: false };
  r.link = await t.fake.join(t.code, { message: (x) => r.frames.push(JSON.parse(x) as Frame), closed: () => { r.closed = true; },
                                       state: () => {} }, device);
  await t.advance(0.01);
  return r;
}
const hello = (over: Json = {}) => JSON.stringify({ type: "nearby_hello", nearby_v: NEARBY_V, name: "Mal", token: null, ...over });

describe("the move clock at a nearby table", () => {
  it("a connected joiner who does nothing cannot hold the table: the bot plays after the move timer, and the round end goes on", async () => {
    const t = new NearbyTable(21, 2);
    await t.open(true);
    await t.join("Active", { drive: true });
    // connected the whole time (a phone kept awake on the table), never acting
    const idle = await t.join("Idle");
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(idle) !== undefined);
    await t.settle(() => t.host.left, 3_000_000);
    expect(t.host.left).toBe(true);
    // two rounds, both ended, in well under the hours an idle seat once held
    const phases = t.host.frames.filter((f) => f.type === "state").map((f) => f.phase);
    expect(phases.filter((ph, i) => ph === "round_end" && phases[i - 1] !== "round_end")).toHaveLength(2);
    expect(t.clock.now()).toBeLessThan(3600);
    const seat = idle.seat!;
    const views = t.host.frames.filter((f) => f.type === "state").map((f) => (f.players as PlayerJson[])[seat]);
    // the idle seat stayed a connected person; its clock showed a full move
    // timer, and after two run out the bot plays every decision for it
    expect(views.every((p) => p.connected)).toBe(true);
    expect(Math.max(...views.map((p) => p.turn_deadline ?? 0))).toBe(MOVE_TIMER);
    expect(views.some((p) => p.away)).toBe(true);
    expect(errors(idle)).toEqual([]);
  }, 60_000);

  it("waits the whole move timer before the first decision it makes for a present player", async () => {
    const t = await started(2);
    const room = t.room!;
    const humanTurn = () => {
      const rnd = room.round!;
      return (rnd.phase === "bury" || rnd.phase === "play") && rnd.turn !== null && !room.seats[rnd.turn].isBot;
    };
    await t.settle(humanTurn, 500_000);
    const rnd = room.round!;
    const seat = rnd.turn!;
    const key = `${rnd.phase}:${rnd.history.length}:${rnd.trick?.plays.length ?? 0}`;
    const at = t.clock.now();
    await t.settle(() => `${rnd.phase}:${rnd.history.length}:${rnd.trick?.plays.length ?? 0}` !== key, 500_000);
    expect(t.clock.now() - at).toBeGreaterThanOrEqual(MOVE_TIMER);
    expect(t.clock.now() - at).toBeLessThan(MOVE_TIMER + 2);
    // one timeout is not away yet
    expect(room.seats[seat].away).toBe(false);
    expect(room.seats[seat].connected).toBe(true);
  }, 60_000);

  it("I'm back clears away and gives the owed decision a fresh clock", async () => {
    const t = new NearbyTable(21, 5);
    await t.open(true);
    const idle = await t.join("Idle");
    t.send(t.host, { type: "table_start_bots" });
    const seat = () => idle.seat!;
    await t.settle(() => t.lastState(idle) !== undefined);
    await t.settle(() => t.room!.seats[seat()].away, 3_000_000);
    t.send(idle, { type: "im_back" });
    await t.settle(() => !t.room!.seats[seat()].away, 1000);
    expect(t.room!.seats[seat()].away).toBe(false);
  }, 60_000);

  it("a person alone with the bots has no clock", async () => {
    const t = await started(1);
    await t.advance(5);
    const players = t.lastState(t.host)!.players as PlayerJson[];
    expect(players.every((p) => p.turn_deadline === null)).toBe(true);
  });
});

describe("lobby seats", () => {
  it("a seat whose link dropped is freed after the hold, so ghosts never fill the table", async () => {
    const t = await lobby(1);
    for (let i = 0; i < 3; i++) {
      const r = await raw(t);
      r.link.send(hello({ name: `Ghost${i}` }));
      await t.advance(0.5);
      r.link.close();
      await t.advance(0.5);
    }
    expect((lastRoom(t.host).players as PlayerJson[]).length).toBe(4);
    await t.advance(LOBBY_SEAT_HOLD + 1);
    expect((lastRoom(t.host).players as PlayerJson[]).map((p) => p.name)).toEqual(["Host"]);
    const friend = await t.join("Friend");
    expect(errors(friend)).toEqual([]);
    expect(lastRoom(friend).you).toBe(1);
  });

  it("a joiner back by token within the hold keeps the seat", async () => {
    const t = await lobby(2);
    const j = t.joiners[0];
    const token = j.token;
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(LOBBY_SEAT_HOLD / 2);
    await t.join("P1", { token, player: j });
    await t.advance(LOBBY_SEAT_HOLD);
    expect(lastRoom(j).you).toBe(1);
    expect((lastRoom(t.host).players as PlayerJson[]).map((p) => [p.seat, p.connected])).toEqual([[0, true], [1, true]]);
  });

  it("everyone else ready, a not-ready joiner's drop starts the game at once", async () => {
    const t = await lobby(3);
    t.send(t.host, { type: "table_start" });
    t.send(t.joiners[0], { type: "table_start" });
    await t.advance(1);
    const t0 = t.clock.now();
    t.fake.drop(t.code, t.fake.peersOf(t.code)[1]);
    await t.settle(() => t.lastState(t.host) !== undefined, 2_000_000);
    expect(t.clock.now() - t0).toBeLessThan(2);
  });

  it("one phone holds one lobby seat: its later links resume the same seat by its token", async () => {
    const t = await lobby(1);
    const got: number[] = [];
    const first = await t.join("M0", { device: "phone-a" });
    got.push(lastRoom(first).you as number);
    for (let i = 1; i < 3; i++) {
      const p = await t.join(`M${i}`, { device: "phone-a", token: first.token });
      got.push(lastRoom(p).you as number);
      await t.advance(0.3);
    }
    expect(got).toEqual([1, 1, 1]);
    expect((lastRoom(t.host).players as PlayerJson[]).map((p) => p.seat)).toEqual([0, 1]);
    // the superseded links are closed, so frames reach that phone once
    await t.advance(2);
    expect(t.joiners.slice(0, 2).every((p) => p.sock.readyState === NearbySocket.CLOSED)).toBe(true);
    // another phone still gets a seat of its own
    const other = await t.join("Other", { device: "phone-b" });
    expect(lastRoom(other).you).toBe(2);
  });

});

describe("links that are not seated", () => {
  it("one look at the seats per link: looking again does not extend it", async () => {
    const t = await lobby(1);
    const r = await raw(t);
    const opened = t.clock.now();
    // a link that keeps pinging and looking, every 5 s
    while (!r.closed && t.clock.now() - opened < 3 * PEEK_SECONDS) {
      r.link.send(PING_TEXT);
      r.link.send(hello({ peek: true }));
      await t.advance(5);
    }
    expect(r.closed).toBe(true);
    expect(t.clock.now() - opened).toBeLessThanOrEqual(PEEK_SECONDS + 6);
    expect(t.nearbyHost!.refused.hello_timeout).toBe(1);
  });

  it("after the start with every seat a person's, a look is answered full and the link ends", async () => {
    const t = await started(4);
    const r = await raw(t);
    r.link.send(hello({ peek: true }));
    await t.advance(3);
    expect(r.frames.find((f) => f.type === "room_seats")).toMatchObject({ full: true, in_game: true });
    expect(r.closed).toBe(true);
  });

  it("after the start with bot seats, a look lists the people and keeps the link for a pick", async () => {
    const t = await started(2);
    const r = await raw(t);
    r.link.send(hello({ peek: true }));
    await t.advance(3);
    const seats = r.frames.find((f) => f.type === "room_seats") as Frame & { seats: { seat: number; is_bot: boolean }[] };
    expect(seats).toMatchObject({ full: false, in_game: true });
    // the seats a newcomer may take (the bots') are the ones not listed
    expect(seats.seats.map((s) => s.seat).sort()).toEqual([0, 1]);
    expect(seats.seats.every((s) => !s.is_bot)).toBe(true);
    expect(r.closed).toBe(false);
  });

  it("two links from one address only looking at the seats: the newer never ends the older", async () => {
    const t = await lobby(1);
    const a = await raw(t, "phone-x");
    a.link.send(hello({ peek: true }));
    await t.advance(0.5);
    const b = await raw(t, "phone-x");
    b.link.send(hello({ peek: true }));
    await t.advance(0.5);
    expect(a.closed).toBe(false);
    expect(b.closed).toBe(false);
  });


  it("looking links cannot crowd out a dropped seat's resume", async () => {
    const t = await started(2);
    const hogs: Raw[] = [];
    for (let i = 0; i < LIMITS.peers; i++) {
      const r = await raw(t);
      r.link.send(hello({ peek: true }));
      hogs.push(r);
    }
    const j = t.joiners[0];
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(1);
    await t.join("P1", { token: j.token, player: j });
    expect(t.lastState(j)!.you).toBe(j.seat);
    expect((t.lastState(t.host)!.players as PlayerJson[])[j.seat!].controller).toBe("human");
  });
});

describe("resume tokens", () => {
  // every seat a person's, so a newcomer has no bot seat to take and the
  // dropped seat is held for its owner
  async function dropped(humans = 3): Promise<{ t: NearbyTable; j: Player }> {
    const t = await started(humans);
    const j = t.joiners[0];
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    await t.advance(1);
    expect(t.room!.seats[j.seat!].connected).toBe(false);
    return { t, j };
  }

  it("with a seat dropped, a wrong token gets no seat, and the seat stays its owner's", async () => {
    const { t, j } = await dropped(4);
    // a resume with a token the table does not know: refused, no seat
    const stranger = await t.join("X", { token: "nope" });
    expect(errors(stranger)).toEqual([{ type: "error", code: "room_not_found", message: "Seat no longer exists." }]);
    expect(t.room!.seats[j.seat!].connected).toBe(false);
    await t.join("P1", { token: j.token, player: j });
    expect(t.lastState(j)!.you).toBe(j.seat);
  });

  it("a token one character off, at either end, gets no seat", async () => {
    const { t, j } = await dropped(4);
    const tok = j.token!;
    const flip = (c: string) => (c === "A" ? "B" : "A");
    for (const bad of [tok.slice(0, -1) + flip(tok.slice(-1)), flip(tok[0]) + tok.slice(1)]) {
      const x = await t.join("X", { token: bad });
      expect(errors(x).map((f) => f.code)).toEqual(["room_not_found"]);
    }
    expect(t.room!.seats[j.seat!].connected).toBe(false);
  });

  it("a replaced connection's actions are refused as stale", async () => {
    const t = await started(2);
    const j = t.joiners[0];
    const seen: Frame[][] = [[], []];
    const conns = [0, 1].map((i) => t.server.connect((text) => seen[i].push(JSON.parse(text) as Frame)));
    for (const c of conns) {
      c.receive(JSON.stringify({ type: "table_join", code: t.code, name: "P1", token: j.token }));
      await t.advance(0.1);
    }
    const before = t.room!.round!.passed.length;
    conns[0].receive(JSON.stringify({ type: "pass_declare" }));
    await t.advance(0.1);
    expect(seen[0].some((f) => f.type === "error" && f.code === "stale_connection")).toBe(true);
    expect(t.room!.round!.passed.length).toBeLessThanOrEqual(before);
    expect(conns[0].currentRoom).toBeNull();
  });
});

describe("names and the joiner allow-list on the host", () => {
  it("a name the rules refuse, sent raw past the joiner's socket, is seated as Player N", async () => {
    const t = await lobby(1);
    const names = ["Bot 3", "System", "a\u0007b", "​​", "Bo​t 1"];
    for (const [i, name] of names.entries()) {
      const r = await raw(t);
      r.link.send(hello({ name }));
      await t.advance(0.5);
      const room = r.frames.find((f) => f.type === "room");
      const me = (room!.players as PlayerJson[]).find((p) => p.seat === room!.you)!;
      expect([name, me.name]).toEqual([name, `Player ${me.seat + 1}`]);
      r.link.send(JSON.stringify({ type: "table_leave" }));
      await t.advance(2);
      void i;
    }
  });

  it("invisible format characters are taken out before the name rules", () => {
    expect(validNearbyName("​")).toBeNull();
    expect(validNearbyName("‍‍")).toBeNull();
    expect(validNearbyName("Bo​t 1")).toBeNull();
    expect(validNearbyName("‮evil")).toBe("evil");
    expect(validNearbyName("﻿Ann")).toBe("Ann");
    expect(validNearbyName("A​nn")).toBe("Ann");
  });

  it("a joiner's seat move never carries another seat", () => {
    expect(cleanJoinerMessage({ type: "table_move", seat: 3, from: 0 })).toEqual({ type: "table_move", seat: 3 });
    expect(cleanJoinerMessage({ type: "im_back", seat: 2 })).toEqual({ type: "im_back" });
  });
});

describe("the liveness ping", () => {
  it("the host ends a link that goes silent; a joiner's socket keeps its link up while it waits", async () => {
    const t = await lobby(2);
    const r = await raw(t);
    r.link.send(hello({ name: "Quiet" }));
    await t.advance(LIMITS.silentSeconds + 1);
    expect(r.closed).toBe(true);
    expect(t.nearbyHost!.refused.silent).toBe(1);
    // the joiner sends nothing of its own for five minutes: its pings hold the link
    await t.advance(300);
    expect(t.joiners[0].sock.readyState).toBe(NearbySocket.OPEN);
    expect(t.fake.wire.some((w) => w.from !== "host" && w.text === PING_TEXT)).toBe(true);
    // the pong is the socket's own: the page never sees it
    expect(t.joiners[0].frames.some((f) => f.type === "nearby_pong")).toBe(false);
  });

  it("the host ends a silent link even on a clock whose timers fire a hair early", async () => {
    const t = await lobby(2);
    // float time: a timer due at heard + 20 s that lands a nanosecond short
    // must not re-arm for that nanosecond forever
    const early = t.clock.setTimeout.bind(t.clock);
    t.clock.setTimeout = (fn, seconds) => early(fn, Math.max(0, seconds - 1e-9));
    const r = await raw(t);
    r.link.send(hello({ name: "Quiet" }));
    await t.advance(LIMITS.silentSeconds + 1);
    expect(r.closed).toBe(true);
    expect(t.nearbyHost!.refused.silent).toBe(1);
  });

  it("a joiner's socket closes when the host goes silent", async () => {
    const t = await lobby(1);
    // a host that takes the link and then answers nothing
    const silent = new NearbyTable(3, 1);
    const link = await silent.fake.host("ZZZZZZ", { peer: () => {}, message: () => {}, state: () => {} });
    void link;
    const sock = new NearbySocket(silent.fake, "ZZZZZZ", null, silent.clock);
    await silent.advance(LIMITS.silentSeconds + LIMITS.pingSeconds + 1);
    expect(sock.readyState).toBe(NearbySocket.CLOSED);
    void t;
  });
});

describe("a seated joiner's random frames, paced under the rate limit", () => {
  it("reach the room, change nobody's cards, and never end the link", async () => {
    const t = await started(3);
    const peer = t.fake.peersOf(t.code)[0];
    const rnd = t.room!.round!;
    let seed = 7;
    const rand = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32);
    const values = [null, true, -1, 0, 3, 1e300, "x", "", [], {}, [1, 2], [1, 1], Array(40).fill(1), "AS", { type: "play" }];
    const types = ["play", "bury", "declare", "pass_declare", "next_round", "table_move", "table_start", "create_room",
      "table_join", "nearby_hello", "__proto__", "constructor", "table_allow_joiners", "table_start_level", "x"];
    let delivered = 0;
    for (let i = 0; i < 400; i++) {
      const msg: Record<string, unknown> = { type: types[Math.floor(rand() * types.length)] };
      for (const k of ["card_ids", "seat", "from", "on", "name", "token", "code", "text", "nearby_v"]) {
        if (rand() < 0.4) msg[k] = values[Math.floor(rand() * values.length)];
      }
      if (t.fake.peersOf(t.code).includes(peer)) delivered += 1;
      t.fake.inject(t.code, peer, JSON.stringify(msg));
      // ten a second: half the limit
      await t.advance(0.1);
    }
    await t.advance(1);
    expect(delivered).toBe(400);
    expect(t.fake.peersOf(t.code)).toContain(peer);
    const refused = t.nearbyHost!.refused;
    expect(refused.rate).toBeUndefined();
    expect(refused.exception).toBeUndefined();
    // the off-list types were dropped at the boundary; the rest reached the room
    expect(refused.message).toBeGreaterThan(50);
    expect(refused.message).toBeLessThan(400);
    expect(t.server.rooms.has(t.code)).toBe(true);
    expect(t.room!.round).toBe(rnd);
    for (let s = 0; s < 4; s++) if (s !== t.joiners[0].seat) expect(rnd.hands[s].length).toBeGreaterThan(0);
  });
});
