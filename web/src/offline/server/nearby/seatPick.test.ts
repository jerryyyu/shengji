// @vitest-environment node
// The host seats a newcomer in the open seat its picker asked for, before
// the start and in a game in progress, over the real link and hello; a
// phone back by its kept token with another seat picked moves there and
// gives its held seat up, while one that picked nothing resumes in place.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { nearbyClaimable } from "../server";
import { setNearbyForTests } from "./flag";
import { CONFIRM_SECONDS } from "./host";
import { LIMITS } from "./protocol";
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

describe("a kept token's join with a seat picked", () => {
  async function heldInLobby() {
    const t = new NearbyTable(11, 1);
    await t.open();
    const mei = await t.join("Mei", { seat: 2 });
    expect(mei.seat).toBe(2);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(5);
    expect(t.room!.lobby![2]?.connected, "the lobby seat is held for its token").toBe(false);
    return { t, mei };
  }

  it("before the start, moves the held seat to the one picked", async () => {
    const { t, mei } = await heldInLobby();
    await t.join("Mei", { token: mei.token, player: mei, seat: 1, chosen: true });
    expect(mei.seat).toBe(1);
    expect(t.room!.lobby![1]?.token).toBe(mei.token);
    expect(t.room!.lobby![2], "no second seat for the same phone").toBeNull();
  });

  it("before the start, with no seat picked, resumes the held seat", async () => {
    const { t, mei } = await heldInLobby();
    await t.join("Mei", { token: mei.token, player: mei, seat: 1 });
    expect(mei.seat).toBe(2);
    expect(t.room!.lobby![1]).toBeNull();
  });

  async function heldInGame() {
    const t = new NearbyTable(9, 1, 0.05);
    await t.open(true);
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(t.host) !== undefined, 100_000);
    const zed = await t.join("Zed", { seat: 2 });
    expect(zed.seat).toBe(2);
    // its new seat confirmed, so a drop holds it
    await t.advance(LIMITS.pingSeconds + 1);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(CONFIRM_SECONDS + 5);
    // the seat is held for its token: not one a newcomer may take
    expect(nearbyClaimable(t.room!, t.clock.now())).not.toContain(2);
    return { t, zed };
  }

  it("in a game, takes over the seat picked and gives the held one to its bot", async () => {
    const { t, zed } = await heldInGame();
    const old = zed.token;
    await t.join("Zed", { token: old, player: zed, seat: 1, chosen: true });
    expect(zed.seat).toBe(1);
    expect(t.room!.seats[1].isBot).toBe(false);
    expect(t.room!.seats[1].connected).toBe(true);
    expect(zed.token, "the new seat's own token").not.toBe(old);
    // the seat given up: its bot plays it, a newcomer may take it, the old token holds nothing
    expect(t.room!.seats[2].connected).toBe(false);
    expect(t.room!.seats[2].leftByChoice).toBe(true);
    expect(t.room!.seats[2].token).not.toBe(old);
    expect(nearbyClaimable(t.room!, t.clock.now())).toContain(2);
    // the phone plays one seat: the connected people are the host and Zed at seat 1
    expect(t.room!.seats.flatMap((s, i) => (s.connected && !s.isBot ? [i] : []))).toEqual([0, 1]);
  }, 60_000);

  it("in a game, with no seat picked, resumes the held seat", async () => {
    const { t, zed } = await heldInGame();
    await t.join("Zed", { token: zed.token, player: zed, seat: 1 });
    expect(zed.seat).toBe(2);
    expect(t.room!.seats[1].isBot).toBe(true);
  }, 60_000);
});
