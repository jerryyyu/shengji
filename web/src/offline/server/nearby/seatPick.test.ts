// @vitest-environment node
// The host seats a newcomer in the open seat its picker asked for, before
// the start and in a game in progress, over the real link and hello.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { nearbyClaimable } from "../server";
import { setNearbyForTests } from "./flag";
import { NearbyTable } from "./testkit";

beforeEach(() => setNearbyForTests(true));
afterEach(() => setNearbyForTests(null));

describe("a join for an open seat", () => {
  for (const want of [1, 2, 3]) {
    it(`sits the joiner at seat ${want} in the lobby`, async () => {
      const t = new NearbyTable(11, 1);
      await t.open();
      const mei = await t.join("Mei", { seat: want });
      expect(mei.seat).toBe(want);
      expect(t.room!.lobby![want]?.name).toBe("Mei");
    });
  }

  it("sits each of three joiners at the seat each picked", async () => {
    const t = new NearbyTable(11, 1);
    await t.open();
    for (const [name, want] of [["A", 3], ["B", 1], ["C", 2]] as const) {
      const p = await t.join(name, { seat: want });
      expect(p.seat, name).toBe(want);
    }
  });

  for (const want of [1, 2, 3]) {
    it(`takes over bot seat ${want} in a game in progress`, async () => {
      const t = new NearbyTable(9, 1, 0.05);
      await t.open(true);
      t.send(t.host, { type: "table_start_bots" });
      await t.settle(() => t.lastState(t.host) !== undefined, 100_000);
      expect(nearbyClaimable(t.room!, t.clock.now())).toContain(want);
      const zed = await t.join("Zed", { seat: want });
      expect(zed.seat).toBe(want);
      expect(t.room!.seats[want].isBot).toBe(false);
    }, 60_000);
  }
});
