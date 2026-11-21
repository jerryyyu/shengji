// @vitest-environment node
// A lobby seat whose link drops: the table never starts without a person
// who has not tapped Start while their seat is held for them, a Start
// tapped before the drop still counts, and the seat is held for longer
// than a stuck link takes to come back.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog } from "../../../nearbyLog";
import { LOBBY_SEAT_HOLD } from "../server";
import { setNearbyForTests } from "./flag";
import { NearbySocket } from "./socket";
import { NearbyTable, type Player } from "./testkit";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

async function lobby(): Promise<{ t: NearbyTable; a: Player; b: Player }> {
  const t = new NearbyTable(8, 1, 0.05);
  await t.open();
  const a = await t.join("Ann");
  const b = await t.join("Bo");
  return { t, a, b };
}

async function dropLink(t: NearbyTable, p: Player): Promise<void> {
  const i = t.joiners.indexOf(p);
  t.fake.drop(t.code, t.fake.peersOf(t.code)[i]);
  await t.settle(() => (p.sock as NearbySocket).readyState === NearbySocket.CLOSED, 1000);
  await t.advance(0.5);
}

describe("a lobby seat whose link drops", () => {
  it("a blip from one who has not tapped Start never starts the game, and the seat outlasts a stuck link's recovery", async () => {
    const { t, a, b } = await lobby();
    t.send(t.host, { type: "table_start" });
    t.send(a, { type: "table_start" });
    await t.advance(1);
    expect(t.room!.game).toBeNull();
    const seat = b.seat!;
    await dropLink(t, b);
    expect(t.room!.lobby![seat]!.connected).toBe(false);
    await t.advance(1);
    expect(t.room!.game).toBeNull();
    // back after 25 s, a stuck link's whole recovery: the same seat
    expect(LOBBY_SEAT_HOLD).toBeGreaterThanOrEqual(25);
    await t.advance(23.5);
    expect(t.room!.lobby![seat]?.name).toBe("Bo");
    await t.join("Bo", { token: b.token, player: b });
    expect(b.seat).toBe(seat);
    expect(t.room!.game).toBeNull();
    t.send(b, { type: "table_start" });
    await t.settle(() => t.room!.game !== null, 10_000);
  }, 60_000);

  it("a Start tapped before the drop still counts", async () => {
    const { t, a, b } = await lobby();
    t.send(t.host, { type: "table_start" });
    t.send(b, { type: "table_start" });
    await t.advance(1);
    await dropLink(t, b);
    expect(t.room!.lobbyReady.has(b.seat!)).toBe(true);
    t.send(a, { type: "table_start" });
    await t.settle(() => t.room!.game !== null, 10_000);
  }, 60_000);

  it("after the hold the seat is free and the others start without it", async () => {
    const { t, a, b } = await lobby();
    t.send(t.host, { type: "table_start" });
    t.send(a, { type: "table_start" });
    await t.advance(1);
    const seat = b.seat!;
    await dropLink(t, b);
    await t.advance(LOBBY_SEAT_HOLD + 1);
    expect(t.room!.game).not.toBeNull();
    expect(t.room!.seats[seat].isBot).toBe(true);
  }, 60_000);
});
