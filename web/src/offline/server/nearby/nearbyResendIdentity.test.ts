// @vitest-environment node
// A move the host applied, whose answer the joiner never heard, is never
// sent again at a later decision that looks like it: a Next at a later
// round's end, a play whose card id is in hand again in a later round, a
// declare whose option is on offer again in a later deal. The resumed frame
// must show the same decision (this seat's own cards and the table's
// public cards as when it was sent) or the move is dropped. A move the host
// never had still goes again at the same decision.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { legalPlays } from "../../engine/round";
import { clearNearbyLog, nearbyLogText } from "../../../nearbyLog";
import { type LocalRoom, stateFor } from "../server";
import { setNearbyForTests } from "./flag";
import { DECLARE_WITNESS_CARDS, NearbySocket } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

const DELAY = 0.05;

/** The room's handled actions of `type` from `seat`, from now on. */
function counter(t: NearbyTable): (seat: number, type: string) => number {
  const out: { seat: number; type: string }[] = [];
  const handle = t.server.handleAction.bind(t.server);
  t.server.handleAction = (room: LocalRoom, seat: number, msg: Record<string, unknown>) => {
    out.push({ seat, type: String(msg.type) });
    handle(room, seat, msg);
  };
  return (seat, type) => out.filter((a) => a.seat === seat && a.type === type).length;
}

/** The next `type` from `seat` applies, but its link drops as it arrives,
 *  so the host's answer never reaches the joiner. */
function answerLost(t: NearbyTable, seat: number, type: string): { applied: () => boolean } {
  let applied = false;
  const handle = t.server.handleAction.bind(t.server);
  t.server.handleAction = (room: LocalRoom, s: number, msg: Record<string, unknown>) => {
    if (!applied && s === seat && msg.type === type) {
      applied = true;
      for (const peer of t.fake.peersOf(t.code)) t.fake.drop(t.code, peer);
    }
    handle(room, s, msg);
  };
  return { applied: () => applied };
}

const roundNo = (t: NearbyTable) => t.room!.game!.roundNo;

/** The joiner's link is gone and the seat played by its cover until
 *  `until`; then the page resumes the seat by token. */
async function awayUntil(t: NearbyTable, j: Player, until: () => boolean): Promise<NearbySocket> {
  await t.settle(() => (j.sock as NearbySocket).readyState === NearbySocket.CLOSED, 10_000);
  j.driver = null;
  await t.settle(until, 20_000_000);
  const sock = await t.resume(j);
  expect(sock.readyState).toBe(NearbySocket.OPEN);
  return sock;
}

describe("a move the host applied is not sent again at a later decision", () => {
  it("a Next applied at round 1's end is not counted at round 2's end", async () => {
    const t = new NearbyTable(3, 3, DELAY);
    await t.open(true);
    const j = await t.join("Mei", { drive: true });
    const raw = j.sock.send.bind(j.sock);
    j.sock.send = (d: string) => { if ((JSON.parse(d) as Frame).type !== "next_round") raw(d); };
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j)?.phase === "round_end", 4_000_000);
    const seat = j.seat!;
    const first = roundNo(t);
    const lost = answerLost(t, seat, "next_round");
    raw(JSON.stringify({ type: "next_round" }));
    await awayUntil(t, j, () => roundNo(t) === first + 1 && t.room!.round!.phase === "round_end");
    expect(lost.applied()).toBe(true);
    const count = counter(t);
    await t.advance(1);
    expect(count(seat, "next_round")).toBe(0);
    expect(t.room!.ready.has(seat)).toBe(false);
    expect(t.room!.round!.phase).toBe("round_end");
    expect(nearbyLogText()).not.toMatch(/sent again/);
  }, 120_000);

  it("a play whose card id is in hand again on the joiner's turn in a later round", async () => {
    for (let seed = 1; seed <= 30; seed++) {
      const t = new NearbyTable(seed, 3, DELAY);
      await t.open(true);
      const j = await t.join("Mei");
      t.send(t.host, { type: "table_start_bots" });
      const seat = j.seat!;
      const myTurn = () => t.room!.round!.turn === seat && t.lastState(j)?.turn === seat;
      await t.settle(() => (t.room?.round?.phase === "play" || t.room?.round?.phase === "bury") && myTurn(), 4_000_000);
      if (t.room!.round!.phase === "bury") {
        const room = t.room!;
        room.syncKitty();
        t.send(j, { type: "bury", card_ids: room.idsForCodes(seat, room.round!.hands[seat].slice(0, 8)) });
        await t.settle(() => t.room!.round!.phase === "play" && myTurn(), 2_000_000);
      }
      const first = roundNo(t);
      const ids = t.room!.idsForCodes(seat, legalPlays(t.room!.round!, seat)![0]);
      const lost = answerLost(t, seat, "play");
      t.send(j, { type: "play", card_ids: ids });
      const again = () => {
        const rnd = t.room!.round!;
        return rnd.phase === "play" && rnd.turn === seat && ids.every((id) => t.room!.ids[seat].has(id))
          && ids.every((id) => (stateFor(t.room!, seat, t.clock.now()).hand as { id: number }[]).some((c) => c.id === id));
      };
      await t.settle(() => (j.sock as NearbySocket).readyState === NearbySocket.CLOSED, 10_000);
      await t.settle(() => roundNo(t) > first && again() || roundNo(t) > first + 1, 20_000_000);
      if (!again()) continue;
      expect(lost.applied()).toBe(true);
      const count = counter(t);
      await t.resume(j);
      await t.advance(0.3);
      // the resume landed on that turn: the old play could have gone again
      expect(t.lastState(j)!.turn).toBe(seat);
      expect(count(seat, "play")).toBe(0);
      expect(nearbyLogText()).not.toMatch(/sent again/);
      return;
    }
    throw new Error("no later round with the played card id in hand on the joiner's turn");
  }, 600_000);

  it("a declare whose option is on offer again in a later round's deal", async () => {
    for (let seed = 1; seed <= 60; seed++) {
      const t = new NearbyTable(seed, 3, DELAY);
      await t.open(true);
      const j = await t.join("Mei");
      t.send(t.host, { type: "table_start_bots" });
      const seat = j.seat!;
      await t.settle(() => {
        const s = t.lastState(j);
        return s !== undefined && (s.phase !== "deal"
          || ((s.declare_options as unknown[]).length > 0 && (s.hand as unknown[]).length >= DECLARE_WITNESS_CARDS));
      }, 4_000_000);
      const s = t.lastState(j)!;
      if (s.phase !== "deal") continue;
      const first = roundNo(t);
      const ids = (s.declare_options as number[][])[0];
      const lost = answerLost(t, seat, "declare");
      t.send(j, { type: "declare", card_ids: ids });
      const offered = () => {
        const rnd = t.room!.round!;
        if (rnd.phase !== "deal" && rnd.phase !== "declare") return false;
        const opts = stateFor(t.room!, seat, t.clock.now()).declare_options as number[][];
        return opts.some((o) => o.length === ids.length && o.every((id) => ids.includes(id)));
      };
      await t.settle(() => (j.sock as NearbySocket).readyState === NearbySocket.CLOSED, 10_000);
      if (!lost.applied() || t.room!.round!.declaration?.seat !== seat) continue;
      await t.settle(() => roundNo(t) > first && offered() || roundNo(t) > first + 1, 20_000_000);
      if (!offered()) continue;
      const count = counter(t);
      await t.resume(j);
      await t.advance(0.3);
      expect(count(seat, "declare")).toBe(0);
      expect(nearbyLogText()).not.toMatch(/sent again/);
      return;
    }
    throw new Error("no later deal offering the joiner the same declare ids");
  }, 900_000);
});

describe("a move the host never had still goes again at the same decision", () => {
  it("a play on the joiner's turn", async () => {
    const t = new NearbyTable(5, 1, DELAY);
    await t.open(true);
    const j = await t.join("Mei");
    t.send(t.host, { type: "table_start_bots" });
    const seat = j.seat!;
    const myTurn = () => t.room!.round!.turn === seat && t.lastState(j)?.turn === seat;
    await t.settle(() => (t.room?.round?.phase === "play" || t.room?.round?.phase === "bury") && myTurn(), 4_000_000);
    if (t.room!.round!.phase === "bury") {
      const room = t.room!;
      room.syncKitty();
      t.send(j, { type: "bury", card_ids: room.idsForCodes(seat, room.round!.hands[seat].slice(0, 8)) });
      await t.settle(() => t.room!.round!.phase === "play" && myTurn(), 2_000_000);
    }
    const ids = t.room!.idsForCodes(seat, legalPlays(t.room!.round!, seat)![0]);
    const count = counter(t);
    t.fake.lose(t.fake.peersOf(t.code)[0]);
    t.send(j, { type: "play", card_ids: ids });
    const old = j.sock as NearbySocket;
    await t.settle(() => old.readyState === NearbySocket.CLOSED, 100_000);
    expect(t.room!.round!.turn).toBe(seat);
    const sock = await t.resume(j);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    await t.advance(1);
    expect(count(seat, "play")).toBe(1);
    expect(nearbyLogText()).toMatch(/resume: the unanswered play sent again/);
    expect(t.room!.round!.turn).not.toBe(seat);
  }, 120_000);
});
