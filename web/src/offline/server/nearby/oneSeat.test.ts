// @vitest-environment node
// A phone holds one seat: its hello with its seat's token, while an older
// link of that seat still counts as connected (the host has not heard it go),
// supersedes that link at once, and the older link can no longer act.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setNearbyForTests } from "./flag";
import { NearbyTable, type Player } from "./testkit";
import type { NearbySocket } from "./socket";

beforeEach(() => setNearbyForTests(true));
afterEach(() => setNearbyForTests(null));

async function seatedAt3() {
  const t = new NearbyTable(11, 1);
  await t.open();
  const mei = await t.join("Mei", { seat: 3 });
  expect(mei.seat).toBe(3);
  expect(t.room!.lobby![3]?.connected).toBe(true);
  return { t, mei, old: mei.sock as NearbySocket };
}

const seatsOf = (t: NearbyTable, p: Player) =>
  t.room!.lobby!.flatMap((s, i) => (s && s.connected && s.token === p.token ? [i] : []));

describe("a hello with a seat's token while its old link is still up", () => {
  it("supersedes the old link: one seat, and the old link's frames are dropped", async () => {
    const { t, mei, old } = await seatedAt3();
    await t.join("Mei", { token: mei.token, player: mei, seat: 3 });
    expect(mei.seat).toBe(3);
    expect(seatsOf(t, mei)).toEqual([3]);
    expect(t.fake.peersOf(t.code)).toHaveLength(1);
    // the old link acts after the supersede: nothing of it reaches the room
    old.send(JSON.stringify({ type: "table_leave" }));
    await t.advance(3);
    expect(t.room!.lobby![3]?.connected, "the seat is still the new link's").toBe(true);
    expect(seatsOf(t, mei)).toEqual([3]);
  });

  it("with a free seat chosen, moves there and frees the old seat", async () => {
    const { t, mei, old } = await seatedAt3();
    await t.join("Mei", { token: mei.token, player: mei, seat: 2, chosen: true });
    expect(mei.seat).toBe(2);
    expect(t.room!.lobby![3], "the old seat is free").toBeNull();
    expect(seatsOf(t, mei)).toEqual([2]);
    old.send(JSON.stringify({ type: "table_leave" }));
    await t.advance(3);
    expect(seatsOf(t, mei)).toEqual([2]);
  });

  it("a different phone with no token gets a seat of its own", async () => {
    const { t, mei } = await seatedAt3();
    const zed = await t.join("Zed", { seat: 2 });
    expect(zed.seat).toBe(2);
    expect(zed.token).not.toBe(mei.token);
    expect(t.room!.lobby![3]?.connected).toBe(true);
    expect(t.fake.peersOf(t.code)).toHaveLength(2);
  });
});
