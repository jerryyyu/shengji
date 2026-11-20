// Joining a nearby game in progress, and a seat's resume after a drop, end
// to end on the fake transport: a newcomer takes over a bot's seat at once
// (the online by-code join), never a connected person's; Allow joiners off
// refuses it; the taken seat resumes by its token. A resume opens the
// socket only once the host has bound the seat and sent its state, so a
// move sent at the open applies on the first try; a network that comes back
// gets a fresh attempt that lands, and the move goes once.
import { describe, expect, it } from "vitest";
import { legalPlays } from "../../engine/round";
import { nearbyChoices } from "../../../joinSeats";
import type { RoomSeats } from "../../../protocol";
import { NEARBY_COPY } from "./copy";
import { LIMITS } from "./protocol";
import { NearbySocket, spread } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";

type PlayerJson = { seat: number; is_bot: boolean; controller: string; name: string };

async function started(humans: number, drive = false, seed = 21): Promise<NearbyTable> {
  const t = new NearbyTable(seed, 1);
  await t.open(drive);
  for (let i = 1; i < humans; i++) await t.join(`P${i}`, { drive });
  t.send(t.host, { type: "table_start_bots" });
  await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
  return t;
}

const errors = (p: Player) => p.frames.filter((f) => f.type === "error");
const players = (t: NearbyTable, p: Player) => t.lastState(p)!.players as PlayerJson[];

/** A raw look at the seats, as the joiner's panel sends it. */
async function peek(t: NearbyTable): Promise<{ seats: RoomSeats; closed: () => boolean }> {
  const frames: Frame[] = [];
  let closed = false;
  const link = await t.fake.join(t.code, { message: (x) => frames.push(JSON.parse(x) as Frame), closed: () => { closed = true; },
                                           state: () => {} });
  await t.advance(0.01);
  link.send(NearbySocket.outbound(JSON.stringify({ type: "table_peek", code: t.code }))!);
  await t.advance(2);
  return { seats: frames.find((f) => f.type === "room_seats") as unknown as RoomSeats, closed: () => closed };
}

/** The joiner's seat's first legal play now, as card ids. */
function aPlay(t: NearbyTable, seat: number): number[] {
  const room = t.room!;
  const plays = legalPlays(room.round!, seat)!;
  return room.idsForCodes(seat, plays[0]);
}

describe("joining a nearby game in progress", () => {
  it("after the deal, a newcomer takes a bot's seat at once, and its own moves play it", async () => {
    const t = await started(2, true);
    await t.settle(() => t.room!.round!.phase !== "deal" && t.room!.round!.phase !== "declare");
    const look = await peek(t);
    expect(look.seats).toMatchObject({ in_game: true, full: false });
    // the seat picker offers exactly the bot seats
    expect(nearbyChoices(look.seats)).toEqual([2, 3]);
    const mei = await t.join("Mei", { drive: true });
    expect(errors(mei)).toEqual([]);
    const seat = mei.seat!;
    expect([2, 3]).toContain(seat);
    expect(t.room!.seats[seat].isBot).toBe(false);
    expect(players(t, t.host)[seat]).toMatchObject({ name: "Mei", is_bot: false, controller: "human" });
    const history = () => t.room!.round!.history.flatMap((tr) => tr.plays).filter((p) => p.seat === seat).length
      + (t.room!.round!.trick?.plays.filter((p) => p.seat === seat).length ?? 0);
    const before = history();
    await t.settle(() => history() >= before + 2 || t.room!.round!.phase === "round_end");
    expect(history()).toBeGreaterThanOrEqual(before + 1);
    // the plays came over Mei's link, not from the bot
    const meiPeer = t.fake.wire.find((w) => w.to !== "host" && w.text.includes(`"you":${seat}`))!.to;
    expect(t.fake.wire.some((w) => w.from === meiPeer && w.text.startsWith('{"type":"play"'))).toBe(true);
  });

  it("the newcomer's frames carry its own hand only", async () => {
    const t = await started(2, true);
    await t.settle(() => t.room!.round!.phase === "play");
    const mei = await t.join("Mei");
    const seat = mei.seat!;
    const st = t.lastState(mei)!;
    const hand = (st.hand as { code: string }[]).map((c) => c.code).sort();
    expect(hand).toEqual([...t.room!.round!.hands[seat]].sort());
    for (const other of [0, 1, 2, 3].filter((s) => s !== seat)) {
      const theirs = new Set(t.room!.round!.hands[other]);
      // a card the other seat holds that Mei does not (two decks: codes repeat)
      const only = [...theirs].filter((c) => !hand.includes(c));
      for (const f of mei.frames) {
        const text = JSON.stringify({ ...f, trick: null, last_trick: null, current_declaration: null });
        for (const c of only) expect(text.includes(`"${c}"`)).toBe(false);
      }
    }
  });

  it("with every seat a person's there is no seat: a look is full and a join is refused", async () => {
    const t = await started(4);
    const look = await peek(t);
    expect(look.seats).toMatchObject({ in_game: true, full: true });
    const x = await t.join("X");
    expect(errors(x)).toEqual([{ type: "error", code: "room_full", message: NEARBY_COPY.full }]);
  });

  it("a newcomer never takes a connected person's seat, even by asking for it", async () => {
    const t = await started(2);
    const sock = t.socket();
    const x: Player = { name: "X", sock, frames: [], token: null, driver: null, seat: null, left: false };
    sock.onmessage = (ev) => x.frames.push(JSON.parse(ev.data as string) as Frame);
    sock.onopen = () => sock.send(JSON.stringify({ type: "table_join", code: t.code, name: "X", seat: 1 }));
    await t.settle(() => x.frames.some((f) => f.type === "state"));
    const you = x.frames.find((f) => f.type === "state")!.you as number;
    expect([2, 3]).toContain(you);
    expect(t.room!.seats[1].name).toBe("P1");
  });

  it("Allow joiners off: the look is full and a join is refused with the table-full line; on again, it seats", async () => {
    const t = await started(2);
    t.send(t.host, { type: "table_allow_joiners", on: false });
    await t.advance(1);
    expect(t.room!.allowJoiners).toBe(false);
    const look = await peek(t);
    expect(look.seats.full).toBe(true);
    expect(look.closed()).toBe(true);
    const x = await t.join("X");
    expect(errors(x)).toEqual([{ type: "error", code: "room_full", message: NEARBY_COPY.full }]);
    // a seated joiner's resume is not a newcomer: it still gets back in
    const j = t.joiners[0];
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(1);
    await t.join("P1", { token: j.token, player: j });
    expect(t.lastState(j)!.you).toBe(1);
    t.send(t.host, { type: "table_allow_joiners", on: true });
    await t.advance(1);
    const y = await t.join("Y");
    expect(errors(y)).toEqual([]);
    expect(t.lastState(y)!.you).toBe(2);
  });

  it("a reconnect after the mid-game join keeps the taken seat, by its token", async () => {
    const t = await started(2);
    const mei = await t.join("Mei");
    const seat = mei.seat!;
    const token = mei.token!;
    t.fake.drop(t.code, t.fake.peersOf(t.code).at(-1)!);
    await t.settle(() => mei.sock.readyState === NearbySocket.CLOSED, 1000);
    await t.advance(5);
    expect(t.room!.seats[seat].connected).toBe(false);
    const sock = await t.resume(mei);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    expect(mei.token).toBe(token);
    expect(t.lastState(mei)!.you).toBe(seat);
    expect(players(t, t.host)[seat]).toMatchObject({ name: "Mei", controller: "human" });
  });

  it("a joiner whose window passed comes back by the code: its old seat, now the bot's, is offered and taken", async () => {
    const t = await started(4);
    const j = t.joiners[1];
    const seat = j.seat!;
    t.fake.drop(t.code, t.fake.peersOf(t.code)[1]);
    await t.advance(70);
    const look = await peek(t);
    expect(look.seats.full).toBe(false);
    expect(nearbyChoices(look.seats)).toEqual([seat]);
    // the page forgot its token with the end screen: a plain join by code
    const back = await t.join("P2");
    expect(errors(back)).toEqual([]);
    expect(t.lastState(back)!.you).toBe(seat);
    // the old token no longer holds that seat
    const old = await t.join("Old", { token: j.token });
    expect(errors(old).map((f) => f.code)).toEqual(["room_full"]);
  });
});

describe("a seat's resume after a drop", () => {
  /** Two people, the joiner undriven, the play phase on the joiner's turn. */
  async function onJoinersTurn(): Promise<{ t: NearbyTable; j: Player }> {
    const t = new NearbyTable(5, 1);
    await t.open(true);
    const j = await t.join("P1");
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.room?.round?.phase === "play" && t.room.round.turn === j.seat
      || (t.room?.round?.phase === "bury" && t.room.round.turn === j.seat), 2_000_000);
    // a bury by the joiner, if it is the banker, gets it to the play
    if (t.room!.round!.phase === "bury") {
      const room = t.room!;
      room.syncKitty();
      const ids = room.idsForCodes(j.seat!, room.round!.hands[j.seat!].slice(0, 8));
      t.send(j, { type: "bury", card_ids: ids });
      await t.settle(() => t.room!.round!.phase === "play" && t.room!.round!.turn === j.seat, 2_000_000);
    }
    return { t, j };
  }

  const hellos = (t: NearbyTable, from: number) =>
    t.fake.wire.slice(from).filter((w) => w.to === "host" && w.text.startsWith('{"type":"nearby_hello"')).length;
  const playsBy = (t: NearbyTable, seat: number) =>
    t.room!.round!.history.flatMap((tr) => tr.plays).filter((p) => p.seat === seat).length
    + (t.room!.round!.trick?.plays.filter((p) => p.seat === seat).length ?? 0);

  it("opens only once the host has the seat and its state is in; a move sent at the open applies first time", async () => {
    const { t, j } = await onJoinersTurn();
    const seat = j.seat!;
    const play = aPlay(t, seat);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(1);
    const mark = t.fake.wire.length;
    const before = playsBy(t, seat);
    let opened: number | null = null;
    let stateAtOpen = false;
    const framesBefore = j.frames.length;
    const sock = t.socket(undefined, () => ({ type: "table_join", code: t.code, name: "P1", token: j.token }));
    sock.onmessage = (ev) => j.frames.push(JSON.parse(ev.data as string) as Frame);
    sock.onopen = () => {
      opened = t.clock.now();
      stateAtOpen = t.room!.seats[seat].connected && t.room!.seats[seat].writer !== null;
      // the page's move, the moment the socket says it is open
      sock.send(JSON.stringify({ type: "play", card_ids: play }));
    };
    await t.settle(() => playsBy(t, seat) > before, 50_000);
    expect(opened).not.toBeNull();
    expect(stateAtOpen).toBe(true);
    // the state came with the open, ahead of anything the page did
    expect(j.frames.slice(framesBefore).some((f) => f.type === "state")).toBe(true);
    expect(playsBy(t, seat)).toBe(before + 1);
    // one hello, one link: no second reconnect
    expect(hellos(t, mark)).toBe(1);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
  });

  it("a resume whose link never comes up (a stale path) gives up within the link limit, for a fresh attempt", async () => {
    const { t, j } = await onJoinersTurn();
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(1);
    t.fake.network(false, t.code, "stall");
    const start = t.clock.now();
    const sock = await t.resume(j);
    expect(sock.readyState).toBe(NearbySocket.CLOSED);
    expect(t.clock.now() - start).toBeLessThanOrEqual(LIMITS.linkSeconds + 0.1);
  });

  it("drop, a move while down, the network back: a fresh attempt within 2 s lands, and the move applies once", async () => {
    const { t, j } = await onJoinersTurn();
    const seat = j.seat!;
    const play = aPlay(t, seat);
    t.fake.network(false, t.code);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    // the move while down: the socket is closed, so the page holds it
    // (Table's pending send) instead of sending it
    j.sock.send(JSON.stringify({ type: "play", card_ids: play }));
    const before = playsBy(t, seat);
    // attempts while down fail at once
    for (let i = 0; i < 3; i++) {
      const s = await t.resume(j);
      expect(s.readyState).toBe(NearbySocket.CLOSED);
      await t.advance(2);
    }
    // the page reconnects at once on the path event (NearbyJoinStore)
    let regained: number | null = null;
    let attempt: Promise<NearbySocket> | null = null;
    const off = t.fake.path((up) => {
      if (!up) return;
      regained = t.clock.now();
      attempt = t.resume(j);
    });
    t.fake.network(true);
    off();
    const sock = await attempt!;
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    expect(t.clock.now() - regained!).toBeLessThanOrEqual(2);
    // the held move goes once on the new link (Table resends once)
    t.send(j, { type: "play", card_ids: play });
    await t.settle(() => playsBy(t, seat) > before, 50_000);
    await t.advance(2);
    expect(playsBy(t, seat)).toBe(before + 1);
  });

  it("an attempt stuck on an endpoint of the outage is replaced when the network is back, and the new one lands", async () => {
    const { t, j } = await onJoinersTurn();
    const seat = j.seat!;
    t.fake.network(false, t.code, "stall");
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    // an attempt made while down hangs on the old path
    const stale = t.socket(undefined, () => ({ type: "table_join", code: t.code, name: "P1", token: j.token }));
    await t.advance(1);
    expect(stale.readyState).toBe(NearbySocket.CONNECTING);
    // back: the page drops the hanging attempt (ws.ts reconnect) and makes a fresh one
    let fresh: Promise<NearbySocket> | null = null;
    const off = t.fake.path((up) => {
      if (!up) return;
      stale.close();
      fresh = t.resume(j);
    });
    const at = t.clock.now();
    t.fake.network(true);
    off();
    const sock = await fresh!;
    expect(stale.readyState).toBe(NearbySocket.CLOSED);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    expect(t.clock.now() - at).toBeLessThanOrEqual(2);
    expect(t.lastState(j)!.you).toBe(seat);
  });
  it("after a drop and resume, five moves in a row each apply on the same link, as fast as before, with no stuck probe", async () => {
    const t = new NearbyTable(5, 1, 0.05);
    await t.open(true);
    const j = await t.join("P1");
    t.send(t.host, { type: "table_start_bots" });
    const seat = j.seat!;
    const myTurn = () => t.room?.round?.phase === "play" && t.room.round.turn === seat;
    const latencies = async (n: number): Promise<number[]> => {
      const out: number[] = [];
      for (let i = 0; i < n; i++) {
        await t.settle(() => myTurn() || t.room!.round!.phase === "round_end", 2_000_000);
        if (!myTurn()) break;
        const before = playsBy(t, seat);
        const sent = t.clock.now();
        const frames = j.frames.length;
        t.send(j, { type: "play", card_ids: aPlay(t, seat) });
        await t.settle(() => j.frames.slice(frames).some((f) => f.type === "state" && playsBy(t, seat) > before), 50_000);
        out.push(Math.round((t.clock.now() - sent) * 1000));
        // a probe's pong window passes before the next move
        await t.advance(LIMITS.pongSeconds + 0.5);
        expect(j.sock.readyState).toBe(NearbySocket.OPEN);
      }
      return out;
    };
    await t.settle(() => myTurn(), 2_000_000);
    const first = await latencies(2);
    const sockBefore = j.sock;
    const oldPeer = t.fake.peersOf(t.code)[0];
    t.fake.drop(t.code, oldPeer);
    await t.settle(() => sockBefore.readyState === NearbySocket.CLOSED, 1000);
    await t.advance(1);
    const sock = await t.resume(j);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    const mark = t.fake.wire.length;
    const after = await latencies(5);
    expect(after.length).toBe(5);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    expect(j.sock).toBe(sock);
    // one link the whole time: no second hello, and nothing more from the old socket
    expect(hellos(t, mark)).toBe(0);
    expect(t.fake.wire.slice(mark).some((w) => w.from === oldPeer)).toBe(false);
    // one probe at most per move, as on the first link: no extra pings
    const pings = t.fake.wire.slice(mark).filter((w) => w.to === "host" && w.text.includes('"nearby_ping"')).length;
    expect(pings).toBeLessThanOrEqual(after.length * 2);
    expect(Math.max(...after)).toBeLessThanOrEqual(Math.max(...first) + 10);
  });
});

describe("the link's latency summary in the device log", () => {
  it("gives the count, median, 95th percentile and worst", () => {
    expect(spread([])).toBe("none");
    expect(spread([40, 10, 500, 20, 30])).toBe("n=5 p50 30 p95 500 max 500 ms");
  });
});

describe("a slow link is not torn down in a loop", () => {
  async function seatedJoiner(peerToPeer: boolean): Promise<{ t: NearbyTable; j: Player; peer: () => string }> {
    const t = new NearbyTable(9, 1);
    t.fake.peerToPeer = peerToPeer;
    await t.open(true);
    const j = await t.join("P1");
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j) !== undefined);
    return { t, j, peer: () => t.fake.peersOf(t.code).at(-1)! };
  }

  it("over peer-to-peer Wi-Fi a ping may take up to 8 s; over Wi-Fi 4 s", async () => {
    for (const [p2p, kept] of [[true, true], [false, false]] as const) {
      const { t, j, peer } = await seatedJoiner(p2p);
      const sock = j.sock as NearbySocket;
      // the joiner's frames are held for 6 s, then arrive
      t.fake.hold(peer());
      t.send(j, { type: "im_back" });
      await t.advance(6);
      t.fake.release(peer());
      await t.advance(1);
      expect(sock.readyState === NearbySocket.OPEN).toBe(kept);
    }
  });

  it("links that keep sticking are replaced at most once every 10 s", async () => {
    const { t, j, peer } = await seatedJoiner(false);
    const closes: number[] = [];
    for (let i = 0; i < 3; i++) {
      const sock = j.sock as NearbySocket;
      t.fake.lose(peer());
      t.send(j, { type: "im_back" });
      await t.settle(() => sock.readyState === NearbySocket.CLOSED, 100_000);
      closes.push(t.clock.now());
      await t.advance(0.5);
      const next = await t.resume(j);
      expect(next.readyState).toBe(NearbySocket.OPEN);
    }
    expect(closes[1] - closes[0]).toBeGreaterThanOrEqual(LIMITS.stuckSpacingSeconds - 1e-9);
    expect(closes[2] - closes[1]).toBeGreaterThanOrEqual(LIMITS.stuckSpacingSeconds - 1e-9);
  });
});
