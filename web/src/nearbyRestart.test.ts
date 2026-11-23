// A restarted joiner's app on the real host, end to end on the fake
// transport: the joiner's store (nearbyJoin.ts) over NearbySockets, the
// host's room on the in-page server. The seat token is kept on the phone by
// the table's code, so a fresh store, as after iOS ended the app, takes the
// same seat and hand back by it through the code box's join; a Leave, or a
// table it never sat at, joins as a newcomer.
import { afterEach, beforeEach, expect, it } from "vitest";
import { keptSeatToken, NearbyJoinStore, SEAT_KEEP_MS, SEATS_KEY, type NearbyJoinDeps } from "./nearbyJoin";
import { nearbyLogLines } from "./nearbyLog";
import { NearbySocket } from "./offline/server/nearby/socket";
import { LOBBY_SEAT_HOLD } from "./offline/server/server";
import { NearbyTable, type Frame } from "./offline/server/nearby/testkit";
import type { ConnStatus } from "./ws";

type Msg = Record<string, unknown> & { type: string };

/** One phone's app: a fresh store, as at its launch, on the table's clock.
 *  `oldHost`: the host's peek answers come without held_seat, as an older
 *  host's do. */
function phone(t: NearbyTable, { oldHost = false } = {}) {
  const subs = new Set<(m: Msg) => void>();
  const stats = new Set<(s: ConnStatus) => void>();
  const frames: Frame[] = [];
  const sent: Msg[] = [];
  let sock: NearbySocket | null = null;
  const status = (s: ConnStatus) => stats.forEach((f) => f(s));
  const deps: NearbyJoinDeps = {
    conn: {
      send: ((m: Msg) => {
        if (!sock || sock.readyState !== NearbySocket.OPEN) return false;
        sent.push(m);
        sock.send(JSON.stringify(m));
        return true;
      }) as never,
      subscribe: ((fn: (m: Msg) => void) => { subs.add(fn); return () => {}; }) as never,
      subscribeStatus: ((fn: (s: ConnStatus) => void) => { stats.add(fn); return () => {}; }) as never,
      useNearby: (make) => {
        // the page's socket retires the link it had before the new one
        const old = sock;
        const s = make() as unknown as NearbySocket;
        sock = s;
        old?.close();
        s.onopen = () => status("open");
        s.onmessage = (ev) => {
          const m = JSON.parse(ev.data as string) as Msg;
          if (oldHost && m.type === "room_seats") delete m.held_seat;
          frames.push(m);
          subs.forEach((f) => f(m));
        };
        s.onclose = () => { if (sock === s) status("closed"); };
      },
      leaveNearby: () => { const s = sock; sock = null; s?.close(); },
      leaveToLobby: () => {
        sock?.send(JSON.stringify({ type: "table_leave" }));
        subs.forEach((f) => f({ type: "left" }));
      },
      reconnect: () => {},
      nearbyLeaveOwed: () => false,
    },
    socketFor: async (code, onState, greet) => () => new NearbySocket(t.fake, code, onState, t.clock, greet) as unknown as WebSocket,
    watchPath: async () => () => {},
    offline: () => true,
    setOffline: () => {},
    setSession: () => {},
    allowed: () => {},
    refused: () => {},
    onVisible: () => {},
  };
  const store = new NearbyJoinStore(deps);
  return {
    store, frames, sent,
    /** The app is ended by the system: its link just stops, nothing is sent. */
    kill: () => { const s = sock; sock = null; s?.close(); },
    state: () => [...frames].reverse().find((f) => f.type === "state"),
  };
}

async function seatedPhone(t: NearbyTable, name = "Mei") {
  const p = phone(t);
  p.store.open(t.code, name);
  await t.settle(() => p.store.view?.step === "panel");
  p.store.join();
  await t.settle(() => p.store.seated && p.state() !== undefined);
  return p;
}

async function started(): Promise<NearbyTable> {
  const t = new NearbyTable(21, 1);
  await t.open();
  await t.join("P1");
  t.send(t.host, { type: "table_start_bots" });
  await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined) && t.room!.round!.phase === "play");
  return t;
}

const handOf = (st: Frame | undefined) => ((st?.hand ?? []) as { code: string }[]).map((c) => c.code).sort();

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

it("a restarted app takes the same seat and hand back by its kept token", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  const seat = before.state()!.you as number;
  const hand = handOf(before.state());
  expect(hand.length).toBeGreaterThan(0);
  before.kill();
  await t.advance(1);
  // the app again, from its launch: the code box's join with the code
  const after = await seatedPhone(t);
  // the seat picker started on Mei's held seat, the one the kept token
  // takes back, so the seat that glowed is the seat Join gave
  const join = after.sent.find((m) => m.type === "table_join")!;
  expect(typeof join.token).toBe("string");
  expect(join.seat).toBe(seat);
  expect(nearbyLogLines().map((l) => l.text)).toContain(`seat picker open: glow seat ${seat} (held)`);
  expect(after.state()!.you).toBe(seat);
  expect(handOf(after.state())).toEqual(hand);
  expect(t.room!.seats[seat].name).toBe("Mei");
  expect(t.room!.seats[seat].isBot).toBe(false);
  // the kept value never reaches the log
  const kept = JSON.parse(localStorage.getItem(SEATS_KEY)!) as Record<string, { token: string }>;
  const token = kept[t.code].token;
  expect(nearbyLogLines().some((l) => l.text.includes(token))).toBe(false);
});

it("a restarted app whose old link still looks connected glows its own seat, and Join lands there", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  const seat = before.state()!.you as number;
  // the old link is never closed: the peek lists the seat as connected
  const after = phone(t);
  after.store.open(t.code, "Mei");
  await t.settle(() => after.store.view?.step === "panel");
  expect(after.store.view?.seat).toBe(seat);
  after.store.join();
  await t.settle(() => after.store.seated && after.state() !== undefined);
  expect(after.sent.find((m) => m.type === "table_join")!.seat).toBe(seat);
  expect(after.state()!.you).toBe(seat);
  expect(t.room!.seats[seat].name).toBe("Mei");
});

it("a kept seat another phone took over, now away, is not glowed as held: Join lands where it glows", async () => {
  const t = new NearbyTable(21, 1);
  await t.open();
  const before = phone(t);
  before.store.open(t.code, "Mei");
  await t.settle(() => before.store.view?.step === "panel");
  before.store.join();
  await t.settle(() => before.store.seated);
  const seat = t.room!.lobby!.findIndex((s) => s?.name === "Mei");
  expect(seat).toBeGreaterThan(0);
  before.kill();
  await t.advance(LOBBY_SEAT_HOLD + 5);
  expect(t.room!.lobby![seat], "the hold is over and the seat open").toBeNull();
  const zed = await t.join("Zed", { seat });
  expect(zed.seat).toBe(seat);
  t.fake.drop(t.code, t.fake.peersOf(t.code).at(-1)!);
  await t.advance(5);
  expect(t.room!.lobby![seat]?.connected, "Zed's seat is held for Zed").toBe(false);
  // Mei's app again, its token kept for the seat Zed now holds
  const after = phone(t);
  after.store.open(t.code, "Mei");
  await t.settle(() => after.store.view?.step === "panel");
  const glow = after.store.view!.seat!;
  expect(glow).not.toBe(seat);
  after.store.join();
  await t.settle(() => after.store.seated);
  expect(t.room!.lobby![glow]?.name).toBe("Mei");
  expect(t.room!.lobby![seat]?.name).toBe("Zed");
});

/** A fresh app at the picker for `t`, then its untapped Join, seated. */
async function joinUntapped(t: NearbyTable, opts: { oldHost?: boolean } = {}) {
  const p = phone(t, opts);
  p.store.open(t.code, "Mei");
  await t.settle(() => p.store.view?.step === "panel");
  const glow = p.store.view!.seat!;
  p.store.join();
  await t.settle(() => p.store.seated);
  await t.advance(1);
  return { p, glow };
}

const lastPeek = (p: { frames: Frame[] }) => [...p.frames].reverse().find((f) => f.type === "room_seats")!;

/** The kept token's entry with no seat of its own, as an older build wrote it. */
function forgetKeptSeat(code: string): void {
  const kept = JSON.parse(localStorage.getItem(SEATS_KEY)!) as Record<string, { token: string; at: number }>;
  localStorage.setItem(SEATS_KEY, JSON.stringify({ [code]: { token: kept[code].token, at: kept[code].at } }));
}

it("another phone of the same name in the old seat, away: the host says the token holds nothing, and Join lands where it glows", async () => {
  const t = new NearbyTable(21, 1);
  await t.open();
  const before = phone(t);
  before.store.open(t.code, "Mei");
  await t.settle(() => before.store.view?.step === "panel");
  before.store.join();
  await t.settle(() => before.store.seated);
  const seat = t.room!.lobby!.findIndex((s) => s?.name === "Mei");
  before.kill();
  await t.advance(LOBBY_SEAT_HOLD + 5);
  // a second Mei takes the seat and drops: it is held for her, under the same name
  const other = await t.join("Mei", { seat });
  expect(other.seat).toBe(seat);
  t.fake.drop(t.code, t.fake.peersOf(t.code).at(-1)!);
  await t.advance(5);
  expect(t.room!.lobby![seat]).toMatchObject({ name: "Mei", connected: false });
  const { p, glow } = await joinUntapped(t);
  expect(lastPeek(p).held_seat).toBeNull();
  expect(glow).not.toBe(seat);
  expect(t.room!.lobby![glow]?.token).toBe(keptSeatToken(t.code));
  expect(t.room!.lobby![seat]?.token).toBe(other.token);
});

it("a token kept with no seat (an older build's), its old link still up: the host names its seat, which glows and resumes", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  const seat = before.state()!.you as number;
  forgetKeptSeat(t.code);
  const { p, glow } = await joinUntapped(t);
  expect(lastPeek(p).held_seat).toBe(seat);
  expect(glow).toBe(seat);
  expect(nearbyLogLines().map((l) => l.text)).toContain(`seat picker open: glow seat ${seat} (held)`);
  // the host's word: an untapped Join resumes, with no choice sent
  expect(p.sent.find((m) => m.type === "table_join")!.chosen).toBeUndefined();
  expect(p.state()!.you).toBe(seat);
});

it("an older host, its seat away under a second phone of the same name: the glow is an open seat, and room.you is the glow", async () => {
  const t = new NearbyTable(21, 1);
  await t.open();
  const before = phone(t);
  before.store.open(t.code, "Mei");
  await t.settle(() => before.store.view?.step === "panel");
  before.store.join();
  await t.settle(() => before.store.seated);
  const seat = t.room!.lobby!.findIndex((s) => s?.name === "Mei");
  before.kill();
  await t.advance(LOBBY_SEAT_HOLD + 5);
  const other = await t.join("Mei", { seat });
  t.fake.drop(t.code, t.fake.peersOf(t.code).at(-1)!);
  await t.advance(5);
  expect(t.room!.lobby![seat]).toMatchObject({ name: "Mei", connected: false });
  const { p, glow } = await joinUntapped(t, { oldHost: true });
  expect(lastPeek(p).held_seat).toBeUndefined();
  expect((lastPeek(p).seats as { seat: number }[]).some((s) => s.seat === glow), "the glow is an open seat").toBe(false);
  expect(p.sent.find((m) => m.type === "table_join")!.chosen).toBe(true);
  const room = [...p.frames].reverse().find((f) => f.type === "room")!;
  expect(room.you).toBe(glow);
  expect(t.room!.lobby![seat]?.token).toBe(other.token);
});

it("an older host, a valid kept token: the glow is an open seat, and the Join sent as the choice lands there", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  const seat = before.state()!.you as number;
  before.kill();
  await t.advance(1);
  const { p, glow } = await joinUntapped(t, { oldHost: true });
  expect(glow).not.toBe(seat);
  expect(p.sent.find((m) => m.type === "table_join")!.chosen).toBe(true);
  expect([...p.frames].reverse().find((f) => f.type === "room" || f.type === "state")!.you).toBe(glow);
  expect(p.state()!.you).toBe(glow);
});

it("an older host and a token with no seat kept: Join sent as the choice lands on the glow, not the old seat", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  const seat = before.state()!.you as number;
  before.kill();
  await t.advance(1);
  forgetKeptSeat(t.code);
  const { p, glow } = await joinUntapped(t, { oldHost: true });
  expect(glow).not.toBe(seat);
  expect(p.state()!.you).toBe(glow);
  expect(t.room!.seats[glow].name).toBe("Mei");
});

it("after a Leave, the app's next join is a newcomer's", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  before.store.leave();
  await t.advance(5);
  expect(localStorage.getItem(SEATS_KEY)).toBeNull();
  const after = await seatedPhone(t);
  const join = after.sent.find((m) => m.type === "table_join")!;
  expect(join.token).toBeUndefined();
  // a newcomer, as the seat picker offered: the seat left by choice is a bot's at once
  expect(after.state()!.you).toBe(join.seat);
});

/** A started table of four people: the host, P1, P2 and the phone. */
async function fullTable() {
  const t = await started();
  await t.join("P2");
  const phoneBefore = await seatedPhone(t);
  expect(t.room!.seats.every((s) => !s.isBot)).toBe(true);
  return { t, phoneBefore };
}

/** The joiner hellos that crossed to the host since `from`, by kind. */
function hellos(t: NearbyTable, from: number) {
  const out = t.fake.wire.slice(from).filter((w) => w.to === "host").map((w) => JSON.parse(w.text) as Msg)
    .filter((m) => m.type === "nearby_hello");
  return { token: out.filter((m) => m.token && !m.peek), join: out.filter((m) => !m.peek) };
}

async function reopened(t: NearbyTable) {
  const p = phone(t);
  p.store.open(t.code, "Mei");
  await t.settle(() => (p.store.seated && p.state() !== undefined) || p.store.view?.step === "full");
  await t.advance(2);
  return p;
}

it("at a table of four people, a restarted app takes its held seat and hand back by its kept token", async () => {
  const { t, phoneBefore } = await fullTable();
  const seat = phoneBefore.state()!.you as number;
  const hand = handOf(phoneBefore.state());
  expect(hand.length).toBeGreaterThan(0);
  phoneBefore.kill();
  await t.advance(1);
  const mark = t.fake.wire.length;
  const after = await reopened(t);
  expect(after.store.seated).toBe(true);
  expect(after.state()!.you).toBe(seat);
  expect(handOf(after.state())).toEqual(hand);
  expect(t.room!.seats[seat].name).toBe("Mei");
  expect(hellos(t, mark).token).toHaveLength(1);
  expect(hellos(t, mark).token[0].seat).toBeNull();
  const kept = JSON.parse(localStorage.getItem(SEATS_KEY)!) as Record<string, { token: string }>;
  expect(nearbyLogLines().some((l) => l.text.includes(kept[t.code].token))).toBe(false);
});

it("at a table of four people, a token the table does not know is the full outcome, tried once and forgotten", async () => {
  const { t, phoneBefore } = await fullTable();
  phoneBefore.kill();
  await t.advance(1);
  const names = t.room!.seats.map((s) => s.name);
  const tokens = t.room!.seats.map((s) => s.token);
  localStorage.setItem(SEATS_KEY, JSON.stringify({ [t.code]: { token: "not-this-tables-token", at: Date.now() } }));
  const mark = t.fake.wire.length;
  const after = await reopened(t);
  expect(after.store.seated).toBe(false);
  expect(after.store.view?.step).toBe("full");
  expect(hellos(t, mark).token).toHaveLength(1);
  expect(localStorage.getItem(SEATS_KEY)).toBeNull();
  expect(t.room!.seats.map((s) => s.name)).toEqual(names);
  expect(t.room!.seats.map((s) => s.token)).toEqual(tokens);
  await t.advance(30);
  expect(hellos(t, mark).token).toHaveLength(1);
});

it("at a table of four people, an expired kept token or none is the full outcome with no join sent", async () => {
  const { t, phoneBefore } = await fullTable();
  phoneBefore.kill();
  await t.advance(1);
  for (const store of [{ [t.code]: { token: "expired", at: Date.now() - SEAT_KEEP_MS - 1 } }, null]) {
    if (store) localStorage.setItem(SEATS_KEY, JSON.stringify(store));
    else localStorage.clear();
    const mark = t.fake.wire.length;
    const after = await reopened(t);
    expect(after.store.view?.step).toBe("full");
    expect(after.sent.filter((m) => m.type === "table_join")).toHaveLength(0);
    expect(hellos(t, mark).join).toHaveLength(0);
  }
});
