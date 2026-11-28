// Joining a nearby game in progress, and a seat's resume after a drop, end
// to end on the fake transport: a newcomer takes over a bot's seat at once
// (the online by-code join), never a connected person's; Allow joiners off
// refuses it; the taken seat resumes by its token. A resume opens the
// socket only once the host has bound the seat and sent its state, so a
// move sent at the open applies on the first try; a network that comes back
// gets a fresh attempt that lands, and the move goes once.
import { describe, expect, it, vi } from "vitest";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import type { GameState } from "../../../protocol";
import type { ReviewPrompt } from "../../../reviewPrompt";
import { useReviewPrompt } from "../../../useReviewPrompt";
import { legalPlays } from "../../engine/round";
import { nearbyChoices } from "../../../joinSeats";
import type { RoomSeats } from "../../../protocol";
import { NEARBY_COPY } from "./copy";
import { KEEPALIVE_TEXT, LIMITS } from "./protocol";
import { NearbySocket, setNearbyKeepalive, spread } from "./socket";
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

  it("the taken seat's frames name whose seat it was through that round only, so the rating ask counts whole rounds", async () => {
    // drivers that play on past the first round end
    const t = new NearbyTable(24, 6);
    await t.open(true);
    await t.join("P1", { drive: true });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.room?.round?.phase === "play");
    const mei = await t.join("Mei", { drive: true });
    const team = mei.seat! % 2;
    const states = () => mei.frames.filter((f) => f.type === "state") as unknown as GameState[];
    // each round's frames, split at its card
    const rounds = () => {
      const out: GameState[][] = [[]];
      for (const f of states()) {
        const last = out[out.length - 1];
        if (f.phase !== "round_end" && last.some((g) => g.phase === "round_end")) out.push([f]);
        else last.push(f);
      }
      return out;
    };
    const won = (r: GameState[]) => r.some((g) => g.phase === "round_end" && g.round_result?.winner_team === team);
    await t.settle(() => rounds().slice(1).some((r) => won(r) && r.at(-1)!.phase === "round_end"));
    const all = rounds();
    expect(won(all[0])).toBe(true);
    for (const g of all[0].filter((g) => g.phase !== "round_end")) {
      expect(g.took_seat).toEqual({ name: expect.any(String), is_bot: true });
    }
    for (const g of all.slice(1).flat()) expect(g.took_seat).toBeUndefined();
    // the same frames through the table's hook: the joined round's win is not counted, each whole win is
    (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const roundWon = vi.fn(async () => null);
    const prompt = { roundWon, ask: vi.fn(async () => false) } as unknown as ReviewPrompt;
    const Probe = ({ state }: { state: GameState }) => { useReviewPrompt(state, true, prompt); return null; };
    const root = createRoot(document.createElement("div"));
    for (const g of states()) act(() => root.render(createElement(Probe, { state: g })));
    act(() => root.unmount());
    const wholeWins = all.slice(1).filter((r) => won(r) && r.at(-1)!.phase === "round_end").length;
    expect(wholeWins).toBeGreaterThan(0);
    expect(roundWon).toHaveBeenCalledTimes(wholeWins);
  }, 60_000);

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
    // the old token no longer holds that seat: its resume is refused
    const old = await t.join("Old", { token: j.token });
    expect(errors(old).map((f) => f.code)).toEqual(["room_not_found"]);
  });
});

describe("a seat left by choice", () => {
  async function leftSeat(allowJoiners = true): Promise<{ t: NearbyTable; j: Player; seat: number }> {
    const t = new NearbyTable(31, 1);
    await t.open(true);
    const j = await t.join("P1", { device: "phone-a" });
    await t.join("P2", { device: "phone-b" });
    await t.join("P3", { device: "phone-c" });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    if (!allowJoiners) t.send(t.host, { type: "table_allow_joiners", on: false });
    const seat = j.seat!;
    t.send(j, { type: "table_leave" });
    await t.settle(() => j.left, 10_000);
    await t.advance(2);
    expect(t.room!.seats[seat].leftByChoice).toBe(true);
    return { t, j, seat };
  }

  /** A look from `device`, as the joiner's panel sends it. */
  async function peekFrom(t: NearbyTable, device: string): Promise<RoomSeats> {
    const frames: Frame[] = [];
    const link = await t.fake.join(t.code, { message: (x) => frames.push(JSON.parse(x) as Frame), closed: () => {}, state: () => {} }, device);
    await t.advance(0.01);
    link.send(NearbySocket.outbound(JSON.stringify({ type: "table_peek", code: t.code }))!);
    await t.advance(2);
    link.close();
    await t.advance(0.1);
    return frames.find((f) => f.type === "room_seats") as unknown as RoomSeats;
  }

  /** The seat's player makes its next play over its own link. */
  async function playsIt(t: NearbyTable, p: Player, seat: number): Promise<void> {
    const peer = t.fake.peersOf(t.code).at(-1)!;
    await t.settle(() => t.fake.wire.some((w) => w.from === peer && w.text.startsWith('{"type":"play"'))
      || t.room!.round!.phase === "round_end", 2_000_000);
    expect(t.room!.seats[seat].connected).toBe(true);
    expect(t.lastState(p)!.you).toBe(seat);
  }

  it("is offered at once (no hold) to anyone, and another phone takes it and plays it; the old token is spent", async () => {
    const { t, j, seat } = await leftSeat();
    const look = await peekFrom(t, "phone-z");
    expect(look.full).toBe(false);
    expect(nearbyChoices(look)).toEqual([seat]);
    const zed = await t.join("Zed", { drive: true, device: "phone-z" });
    expect(errors(zed)).toEqual([]);
    expect(t.lastState(zed)!.you).toBe(seat);
    expect(zed.token).not.toBe(j.token);
    const old = await t.join("Old", { token: j.token });
    expect(errors(old).map((f) => f.code)).toEqual(["room_not_found"]);
    await playsIt(t, zed, seat);
  });

  it("a phone whose Leave was lost, back by the code with no token, is a newcomer: its old link ends by its silence, not its address", async () => {
    const t = new NearbyTable(31, 1);
    await t.open(true);
    const j = await t.join("P1", { device: "phone-a" });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    const seat = j.seat!;
    const oldPeer = t.fake.peersOf(t.code).at(-1)!;
    // the Leave never reaches the host; the page is back after its wait
    t.fake.lose(oldPeer);
    t.send(j, { type: "table_leave" });
    await t.advance(3);
    expect(t.room!.seats[seat].connected).toBe(true);
    const back = await t.join("P1", { drive: true, device: "phone-a" });
    expect(errors(back)).toEqual([]);
    expect(t.lastState(back)!.you).not.toBe(seat);
    expect(back.token).not.toBe(j.token);
    // the old link is not ended for sharing the address...
    expect(t.fake.peersOf(t.code)).toContain(oldPeer);
    // ...but for going silent, and its seat then waits for its token
    await t.advance(LIMITS.silentSeconds + 1);
    expect(t.fake.peersOf(t.code)).not.toContain(oldPeer);
    expect(t.room!.seats[seat].connected).toBe(false);
    expect(t.room!.seats[seat].token).toBe(j.token);
  });

  it("the leaver, back by the code with no token, is offered the seat as anyone is and takes it under a new token", async () => {
    const { t, j, seat } = await leftSeat();
    expect(nearbyChoices(await peekFrom(t, "phone-a"))).toEqual([seat]);
    const back = await t.join("P1", { drive: true, device: "phone-a" });
    expect(errors(back)).toEqual([]);
    expect(t.lastState(back)!.you).toBe(seat);
    expect(back.token).not.toBe(j.token);
    expect(t.room!.seats[seat].leftByChoice).toBe(false);
    await playsIt(t, back, seat);
  });

  it("with Allow joiners off, nobody gets in by the code, the leaver's phone included; the seat's token still takes it back", async () => {
    const { t, j, seat } = await leftSeat(false);
    for (const device of ["phone-z", "phone-a"]) {
      expect((await peekFrom(t, device)).full).toBe(true);
      const p = await t.join("Again", { device });
      expect(errors(p).map((f) => f.code)).toEqual(["room_full"]);
    }
    const back = await t.join("P1", { drive: true, device: "phone-a", token: j.token });
    expect(errors(back)).toEqual([]);
    expect(t.lastState(back)!.you).toBe(seat);
    await playsIt(t, back, seat);
  });
});

describe("a seat belongs to its token, never to an address", () => {
  // The transport's per-address id is an address label, not a phone's
  // identity: an address is reused (DHCP, a phone that left), so a link
  // from an address a seated person came from is a newcomer like any other.
  const ADDR = "reused-ip";
  const handOf = (f: Frame | undefined) => ((f?.hand ?? []) as { code: string }[]).map((c) => c.code).sort().join(",");

  async function aliceAt(): Promise<{ t: NearbyTable; alice: Player; seat: number; peer: string }> {
    const t = new NearbyTable(41, 1);
    await t.open(true);
    const alice = await t.join("Alice", { device: ADDR });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    await t.settle(() => t.room!.round!.phase !== "deal", 2_000_000);
    return { t, alice, seat: alice.seat!, peer: t.fake.peersOf(t.code).at(-1)! };
  }

  it("a tokenless join from a dropped person's address, inside the seat's hold, gets no seat, token or hand of theirs", async () => {
    const { t, alice, seat, peer } = await aliceAt();
    const token = alice.token!;
    t.fake.drop(t.code, peer);
    await t.advance(1);
    expect(t.room!.seats[seat].connected).toBe(false);
    const hand = [...t.room!.round!.hands[seat]].sort().join(",");
    // the look from that address does not offer the held seat
    const frames: Frame[] = [];
    const look = await t.fake.join(t.code, { message: (x) => frames.push(JSON.parse(x) as Frame), closed: () => {}, state: () => {} }, ADDR);
    await t.advance(0.01);
    look.send(NearbySocket.outbound(JSON.stringify({ type: "table_peek", code: t.code }))!);
    await t.advance(1);
    look.close();
    expect(nearbyChoices(frames.find((f) => f.type === "room_seats") as unknown as RoomSeats)).not.toContain(seat);
    const mal = await t.join("Mal", { device: ADDR });
    expect(mal.frames.some((f) => f.token === token)).toBe(false);
    expect(mal.token).not.toBe(token);
    expect(t.lastState(mal)!.you).not.toBe(seat);
    expect(mal.frames.filter((f) => f.type === "state").every((f) => f.you !== seat && handOf(f) !== hand)).toBe(true);
    // and asking for that seat by number changes nothing
    const mal2 = await t.join("Mal2", { device: ADDR, seat });
    expect(mal2.frames.some((f) => f.token === token)).toBe(false);
    expect(mal2.frames.filter((f) => f.type === "state").every((f) => f.you !== seat)).toBe(true);
    // the seat is still held for its owner, under its own token
    const sd = t.room!.seats[seat];
    expect(sd.isBot).toBe(false);
    expect(sd.token).toBe(token);
    expect(sd.name).toBe("Alice");
    // and its token takes it back, hand and all
    const sock = await t.resume(alice, ADDR);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    expect(t.lastState(alice)!.you).toBe(seat);
    expect(handOf(t.lastState(alice))).toBe([...t.room!.round!.hands[seat]].sort().join(","));
  });

  it("a second link from a seated person's address, in the game or the lobby, never ends their live link", async () => {
    const { t, alice, seat, peer } = await aliceAt();
    const mal = await t.join("Mal", { device: ADDR });
    expect(t.lastState(mal)!.you).not.toBe(seat);
    await t.advance(2);
    expect(t.fake.peersOf(t.code)).toContain(peer);
    expect(alice.sock.readyState).toBe(NearbySocket.OPEN);
    expect(t.room!.seats[seat].connected).toBe(true);
    expect(t.room!.seats[seat].token).toBe(alice.token);

    const l = new NearbyTable(42, 1);
    await l.open(true);
    const a = await l.join("Alice", { device: ADDR });
    const aPeer = l.fake.peersOf(l.code).at(-1)!;
    const m = await l.join("Mal", { device: ADDR });
    // two seats: the second link takes a free one, not Alice's
    expect(m.frames.find((f) => f.type === "room")!.you).not.toBe(a.seat);
    expect(m.token).not.toBe(a.token);
    await l.advance(2);
    expect(l.fake.peersOf(l.code)).toContain(aPeer);
    expect(a.sock.readyState).toBe(NearbySocket.OPEN);
    // two links from one address only looking at the seats: neither ends the other
    const closed = [false, false];
    for (const i of [0, 1]) {
      const link = await l.fake.join(l.code, { message: () => {}, closed: () => { closed[i] = true; }, state: () => {} }, ADDR);
      await l.advance(0.01);
      link.send(NearbySocket.outbound(JSON.stringify({ type: "table_peek", code: l.code }))!);
    }
    await l.advance(1);
    expect(closed).toEqual([false, false]);
  });

  it("a valid token resumes the same seat and hand, from the same address or a new one (a path change)", async () => {
    const { t, alice, seat } = await aliceAt();
    const token = alice.token;
    for (const from of [ADDR, "other-path"]) {
      // one joiner here: the table's only link is Alice's
      expect(t.fake.peersOf(t.code)).toHaveLength(1);
      t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
      await t.advance(1);
      expect(t.room!.seats[seat].connected).toBe(false);
      const sock = await t.resume(alice, from);
      expect(sock.readyState).toBe(NearbySocket.OPEN);
      expect(t.lastState(alice)!.you).toBe(seat);
      expect(alice.token).toBe(token);
      expect(handOf(t.lastState(alice))).toBe([...t.room!.round!.hands[seat]].sort().join(","));
      expect(t.room!.seats[seat].connected).toBe(true);
    }
  });

  it("a forged token is a newcomer: a bot's seat when there is one, the table-full refusal when not, never a held seat", async () => {
    const { t, alice, seat, peer } = await aliceAt();
    t.fake.drop(t.code, peer);
    await t.advance(1);
    // as a resume (no seat picked) it is refused outright
    const resume = await t.join("Mal", { device: ADDR, token: "not-a-seat-token" });
    expect(errors(resume).map((f) => f.code)).toEqual(["room_not_found"]);
    // with a pick, even of the held seat, it is a newcomer elsewhere
    const forged = await t.join("Mal", { device: ADDR, token: "not-a-seat-token", seat });
    expect(errors(forged)).toEqual([]);
    const took = t.lastState(forged)!.you as number;
    expect(took).not.toBe(seat);
    expect(t.room!.seats[took].isBot).toBe(false);
    expect(forged.token).not.toBe("not-a-seat-token");
    expect(forged.token).not.toBe(alice.token);
    // every other seat a person's now: a forged token gets nothing
    await t.join("M2", { device: ADDR });
    const none = await t.join("M3", { device: ADDR, token: "forged-too", seat });
    expect(errors(none).map((f) => f.code)).toEqual(["room_full"]);
    expect(t.room!.seats[seat].token).toBe(alice.token);
    expect(t.room!.seats[seat].name).toBe("Alice");
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

  it("a link that was slow and then answered is still watched: a later silent break is found", async () => {
    const { t, j, peer } = await seatedJoiner(false);
    // a first stuck link, so the next one waits out the spacing
    let sock = j.sock as NearbySocket;
    t.fake.lose(peer());
    t.send(j, { type: "im_back" });
    await t.settle(() => sock.readyState === NearbySocket.CLOSED, 100_000);
    await t.advance(0.5);
    sock = await t.resume(j);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    // slow inside the spacing: a move's probe and the next ping go
    // unanswered, the socket gives the link more time, and it answers
    t.fake.hold(peer());
    t.send(j, { type: "im_back" });
    await t.advance(LIMITS.pingSeconds + 1.5);
    t.fake.release(peer());
    await t.advance(1);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    // later the joiner's frames stop getting through: its own pings find it
    // (well before the host's silence check would end the link)
    await t.advance(LIMITS.stuckSpacingSeconds);
    t.fake.lose(peer());
    await t.advance(2 * LIMITS.pingSeconds + LIMITS.pongSeconds);
    expect(LIMITS.silentSeconds).toBeGreaterThan(2 * LIMITS.pingSeconds + LIMITS.pongSeconds);
    expect(sock.readyState).toBe(NearbySocket.CLOSED);
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

describe("the peer-to-peer keepalive", () => {
  const kas = (t: NearbyTable, from: number, peer: string) => {
    const w = t.fake.wire.slice(from);
    return {
      up: w.filter((x) => x.from === peer && x.text === KEEPALIVE_TEXT).length,
      down: w.filter((x) => x.to === peer && x.text === KEEPALIVE_TEXT).length,
    };
  };

  it("runs both ways every 250 ms during a game on a peer-to-peer link, never in the lobby, and stops when switched off", async () => {
    const t = new NearbyTable(9, 1);
    t.fake.peerToPeer = true;
    await t.open(true);
    const j = await t.join("P1");
    const peer = t.fake.peersOf(t.code).at(-1)!;
    // the lobby: no keepalive
    let mark = t.fake.wire.length;
    await t.advance(3);
    expect(kas(t, mark, peer)).toEqual({ up: 0, down: 0 });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j) !== undefined);
    mark = t.fake.wire.length;
    await t.advance(5);
    const on = kas(t, mark, peer);
    expect(on.up).toBeGreaterThanOrEqual(5 / LIMITS.keepaliveSeconds - 2);
    expect(on.up).toBeLessThanOrEqual(5 / LIMITS.keepaliveSeconds + 1);
    expect(on.down).toBeGreaterThanOrEqual(on.up - 1);
    // the host's rate limit never trips on it
    expect(t.nearbyHost!.refused.rate ?? 0).toBe(0);
    setNearbyKeepalive(false);
    try {
      await t.advance(0.5);
      mark = t.fake.wire.length;
      await t.advance(3);
      expect(kas(t, mark, peer).up).toBe(0);
    } finally {
      setNearbyKeepalive(true);
    }
    // back on: it runs again
    mark = t.fake.wire.length;
    await t.advance(2);
    expect(kas(t, mark, peer).up).toBeGreaterThan(0);
  });

  it("never runs on a Wi-Fi link", async () => {
    const t = new NearbyTable(9, 1);
    await t.open(true);
    const j = await t.join("P1");
    const peer = t.fake.peersOf(t.code).at(-1)!;
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j) !== undefined);
    const mark = t.fake.wire.length;
    await t.advance(5);
    expect(kas(t, mark, peer)).toEqual({ up: 0, down: 0 });
  });
});
