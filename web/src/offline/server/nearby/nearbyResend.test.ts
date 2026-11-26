// @vitest-environment node
// Every move a joiner sends on a link that is then rebuilt reaches the room
// exactly once: the declare, the pass, the round end's Next and the lobby's
// Start go again on the new link, as a play and a bury do, when the resumed
// frame shows the host never had them, and never when it did.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog, nearbyLogText } from "../../../nearbyLog";
import type { LocalRoom } from "../server";
import { setNearbyForTests } from "./flag";
import { DECLARE_WITNESS_CARDS, NearbySocket } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

const DELAY = 0.05;

/** The room's handled actions of `type` from `seat`. */
function counter(t: NearbyTable): (seat: number, type: string) => number {
  const out: { seat: number; type: string }[] = [];
  const handle = t.server.handleAction.bind(t.server);
  t.server.handleAction = (room: LocalRoom, seat: number, msg: Record<string, unknown>) => {
    out.push({ seat, type: String(msg.type) });
    handle(room, seat, msg);
  };
  return (seat, type) => out.filter((a) => a.seat === seat && a.type === type).length;
}

/** `msg` goes out on a link whose frames to the host are lost; the socket
 *  calls it stuck, and the page's new link resumes the seat by token. */
async function sendOnALostLink(t: NearbyTable, j: Player, msg: Record<string, unknown>, raw?: (d: string) => void): Promise<NearbySocket> {
  t.fake.lose(t.fake.peersOf(t.code)[0]);
  (raw ?? ((d: string) => j.sock.send(d)))(JSON.stringify(msg));
  const old = j.sock as NearbySocket;
  await t.settle(() => old.readyState === NearbySocket.CLOSED, 100_000);
  const sock = await t.resume(j);
  expect(sock.readyState).toBe(NearbySocket.OPEN);
  await t.advance(1);
  return sock;
}

describe("a move sent on a link that is rebuilt applies exactly once", () => {
  it("a guest's older lobby Start is not sent again: it changes nothing", async () => {
    const t = new NearbyTable(4, 1, DELAY);
    await t.open();
    const j = await t.join("Mei");
    const count = counter(t);
    await sendOnALostLink(t, j, { type: "table_start" });
    expect(count(j.seat!, "table_start")).toBe(0);
    expect(nearbyLogText()).not.toMatch(/table_start sent again/);
    await sendOnALostLink(t, j, { type: "table_start", on: false });
    expect(count(j.seat!, "table_start")).toBe(0);
    expect(t.room!.game).toBeNull();
  }, 60_000);

  it("a declare during the deal", async () => {
    for (let seed = 1; seed <= 40; seed++) {
      const t = new NearbyTable(seed, 1, DELAY);
      await t.open();
      const j = await t.join("Mei");
      t.send(t.host, { type: "table_start_bots" });
      await t.settle(() => {
        const s = t.lastState(j);
        return s !== undefined && (s.phase !== "deal"
          || ((s.declare_options as unknown[]).length > 0 && (s.hand as unknown[]).length >= DECLARE_WITNESS_CARDS));
      }, 2_000_000);
      const s = t.lastState(j)!;
      // a declare needs the deal to run for the rebuild's few seconds more
      if (s.phase !== "deal" || (s.hand as unknown[]).length > 18) continue;
      const count = counter(t);
      const ids = (s.declare_options as number[][])[0];
      await sendOnALostLink(t, j, { type: "declare", card_ids: ids });
      expect(count(j.seat!, "declare")).toBe(1);
      expect(t.room!.round!.declaration?.seat).toBe(j.seat);
      expect(t.room!.actions.filter((a) => a[0] === "declare" && a[1] === j.seat)).toHaveLength(1);
      return;
    }
    throw new Error("no deal with an early declare for the joiner");
  }, 120_000);

  it("a pass in the declare window", async () => {
    const t = new NearbyTable(2, 1, DELAY);
    await t.open();
    const j = await t.join("Mei");
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j)?.phase === "declare", 2_000_000);
    const count = counter(t);
    await sendOnALostLink(t, j, { type: "pass_declare" });
    expect(count(j.seat!, "pass_declare")).toBe(1);
    expect(t.room!.actions.filter((a) => a[0] === "pass" && a[1] === j.seat)).toHaveLength(1);
  }, 60_000);

  it("Next at the round end", async () => {
    const t = new NearbyTable(3, 2, DELAY);
    await t.open(true);
    const j = await t.join("Mei", { drive: true });
    // neither page sends its own Next: the test sends the joiner's
    const hostRaw = t.host.sock.send.bind(t.host.sock);
    t.host.sock.send = (d: string) => { if ((JSON.parse(d) as Frame).type !== "next_round") hostRaw(d); };
    const raw = j.sock.send.bind(j.sock);
    j.sock.send = (d: string) => { if ((JSON.parse(d) as Frame).type !== "next_round") raw(d); };
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j)?.phase === "round_end", 4_000_000);
    j.driver = null;
    const count = counter(t);
    await sendOnALostLink(t, j, { type: "next_round" }, raw);
    expect(count(j.seat!, "next_round")).toBe(1);
    expect(t.room!.ready.has(j.seat!)).toBe(true);
    expect(t.room!.round!.phase).toBe("round_end");
  }, 120_000);
});

describe("a move the host had is never sent again", () => {
  it("a Start applied before the link went", async () => {
    const t = new NearbyTable(4, 1, DELAY);
    await t.open();
    const j = await t.join("Mei");
    const count = counter(t);
    t.send(j, { type: "table_start" });
    await t.settle(() => count(j.seat!, "table_start") === 1, 10_000);
    // the link goes before the joiner hears the answer
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => (j.sock as NearbySocket).readyState === NearbySocket.CLOSED, 1000);
    await t.resume(j);
    await t.advance(1);
    expect(count(j.seat!, "table_start")).toBe(1);
    expect(t.room!.game).toBeNull();
    expect(nearbyLogText()).not.toMatch(/sent again/);
  }, 60_000);

  it("an older Start's take-back on a lost link is not sent again", async () => {
    const t = new NearbyTable(4, 1, DELAY);
    await t.open();
    const j = await t.join("Mei");
    const count = counter(t);
    t.send(j, { type: "table_start" });
    await t.settle(() => count(j.seat!, "table_start") === 1, 10_000);
    await sendOnALostLink(t, j, { type: "table_start", on: false });
    expect(count(j.seat!, "table_start")).toBe(1);
    expect(t.room!.game).toBeNull();
  }, 60_000);
});
