// @vitest-environment node
// A lobby seat whose link drops: the table never starts without a person
// who has not tapped Start while their seat is held for them, a Start
// tapped before the drop still counts, and the seat is held for longer
// than a stuck link takes to come back.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog } from "../../../nearbyLog";
import { LOBBY_SEAT_HOLD } from "../server";
import { setNearbyForTests } from "./flag";
import { LIMITS } from "./protocol";
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
  // seated a moment: each phone's socket has shown the host it has its seat
  await t.advance(LIMITS.pingSeconds + 1);
  return { t, a, b };
}

async function dropLink(t: NearbyTable, p: Player): Promise<void> {
  const i = t.joiners.indexOf(p);
  t.fake.drop(t.code, t.fake.peersOf(t.code)[i]);
  await t.settle(() => (p.sock as NearbySocket).readyState === NearbySocket.CLOSED, 1000);
  await t.advance(0.5);
}

describe("a lobby seat whose link drops", () => {
  it("a guest's older Start and a blip never start the game, and the seat outlasts a stuck link's recovery", async () => {
    const { t, a, b } = await lobby();
    t.send(a, { type: "table_start" });
    t.send(b, { type: "table_start" });
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
    t.send(t.host, { type: "table_start_now" });
    await t.settle(() => t.room!.game !== null, 10_000);
    expect(t.room!.seats[seat].name).toBe("Bo");
  }, 60_000);

  it("the host's Start does not wait for a guest whose link is down", async () => {
    const { t, b } = await lobby();
    const seat = b.seat!;
    await dropLink(t, b);
    t.send(t.host, { type: "table_start_now" });
    await t.settle(() => t.room!.game !== null, 10_000);
    expect(t.room!.seats[seat].isBot).toBe(false);
    expect(t.room!.seats[seat].connected).toBe(false);   // covered by a bot after its window
  }, 60_000);

  it("after the hold the seat is free, nothing starts by itself, and the host's Start fills it with a bot", async () => {
    const { t, b } = await lobby();
    const seat = b.seat!;
    await dropLink(t, b);
    await t.advance(LOBBY_SEAT_HOLD + 1);
    expect(t.room!.game).toBeNull();
    expect(t.room!.lobby![seat]).toBeNull();
    t.send(t.host, { type: "table_start_now" });
    await t.settle(() => t.room!.game !== null, 10_000);
    expect(t.room!.seats[seat].isBot).toBe(true);
  }, 60_000);
});
