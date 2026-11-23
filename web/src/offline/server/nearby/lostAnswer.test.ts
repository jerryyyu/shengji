// @vitest-environment node
// A newcomer's seat whose answer never reached its phone (the frames to it
// lost on the way): the host is not told, so the seat is given up
// CONFIRM_SECONDS after the hello, as by a Leave, and no ghost holds it for
// a phone that never had its token. A phone that did get its seat shows
// the host within a ping interval and keeps it through a drop, as before.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog, nearbyLogText } from "../../../nearbyLog";
import { TAKEOVER_AFTER, nearbyClaimable } from "../server";
import { setNearbyForTests } from "./flag";
import { CONFIRM_SECONDS } from "./host";
import { LIMITS } from "./protocol";
import { NearbySocket } from "./socket";
import { NearbyTable } from "./testkit";
import type { NearbyTransport } from "./transport";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

/** A table whose host loses every frame to a link made after `lossy()`. */
async function lossyTable(seed: number): Promise<{ t: NearbyTable; lossy: () => void }> {
  const t = new NearbyTable(seed, 1, 0.05);
  let known: Set<string> | null = null;
  const host = t.fake.host.bind(t.fake);
  (t.fake as unknown as NearbyTransport).host = async (code, h) => {
    const link = await host(code, h);
    return { ...link, send: (peer, text) => { if (known === null || known.has(peer)) link.send(peer, text); } };
  };
  await t.open(true);
  return { t, lossy: () => { known = new Set(t.fake.peersOf(t.code)); } };
}

/** A newcomer's join of `seat`, from a phone that never hears back. */
function joinUnheard(t: NearbyTable, seat: number): NearbySocket {
  const sock = t.socket();
  sock.onopen = () => sock.send(JSON.stringify({ type: "table_join", code: t.code, name: "Zed", seat }));
  return sock;
}

describe("a newcomer whose answer was lost", () => {
  it("mid-game: the seat it took is the bot's and anyone's again within CONFIRM_SECONDS, not a dropped seat's 60 s", async () => {
    const { t, lossy } = await lossyTable(9);
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(t.host) !== undefined, 100_000);
    lossy();
    const before = nearbyClaimable(t.room!, t.clock.now());
    const seat = before[0];
    const at = t.clock.now();
    const sock = joinUnheard(t, seat);
    await t.settle(() => !t.room!.seats[seat].isBot, 10_000);
    // the room seated it; the phone never heard, and gives its link up
    expect(nearbyClaimable(t.room!, t.clock.now())).not.toContain(seat);
    await t.settle(() => sock.readyState === NearbySocket.CLOSED, 100_000);
    await t.advance(CONFIRM_SECONDS - (t.clock.now() - at) + 0.5);
    expect(t.clock.now() - at).toBeLessThan(TAKEOVER_AFTER / 2);
    expect(nearbyClaimable(t.room!, t.clock.now())).toContain(seat);
    expect(t.server.drives(t.room!, seat)).toBe(true);
    expect(nearbyLogText()).toMatch(/its new seat was never confirmed; given up/);
  }, 60_000);

  it("in the lobby: the seat is free again, and never holds the start, after CONFIRM_SECONDS", async () => {
    const { t, lossy } = await lossyTable(9);
    lossy();
    const sock = joinUnheard(t, 2);
    await t.settle(() => t.room!.lobby![2] !== null, 10_000);
    await t.settle(() => sock.readyState === NearbySocket.CLOSED, 100_000);
    t.send(t.host, { type: "table_start" });
    await t.advance(1);
    // held for a phone that may be back by its token
    expect(t.room!.game).toBeNull();
    await t.advance(CONFIRM_SECONDS);
    expect(t.room!.lobby?.[2] ?? null).toBeNull();
  }, 60_000);
});

describe("a newcomer that has its seat", () => {
  it("shows the host within a ping interval, and keeps its seat through a drop", async () => {
    const t = new NearbyTable(9, 1, 0.05);
    await t.open(true);
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(t.host) !== undefined, 100_000);
    const zed = await t.join("Zed", { seat: nearbyClaimable(t.room!, t.clock.now())[0] });
    const seat = zed.seat!;
    await t.advance(LIMITS.pingSeconds + 1);
    expect(nearbyLogText()).toMatch(/its new seat is confirmed/);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(CONFIRM_SECONDS + 5);
    // a dropped seat's hold: still its owner's
    expect(nearbyClaimable(t.room!, t.clock.now())).not.toContain(seat);
    expect(t.room!.seats[seat].leftByChoice).toBe(false);
    await t.join("Zed", { token: zed.token, player: zed });
    expect(zed.seat).toBe(seat);
  }, 60_000);

  it("a phone back by its token before it confirmed keeps the seat", async () => {
    const t = new NearbyTable(9, 1, 0.05);
    await t.open(true);
    const zed = await t.join("Zed");
    const seat = zed.seat!;
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.advance(2);
    await t.join("Zed", { token: zed.token, player: zed });
    await t.advance(CONFIRM_SECONDS + 5);
    expect(t.room!.lobby![seat]?.name).toBe("Zed");
    expect(nearbyLogText()).not.toMatch(/given up/);
  }, 60_000);

  // the page is seated only by a room or state frame, so a link that goes
  // between the seat's answer and its state leaves the page on the seat
  // picker; its Join carries the token the answer gave (nearbyJoin.ts
  // join()), and the host's older, half-open link of that seat ends
  for (const game of [false, true]) {
    it(`${game ? "mid-game" : "in the lobby"}: back on a new link before its state, with the answer's token, it holds one seat`, async () => {
      const t = new NearbyTable(9, 1, 0.05);
      await t.open(true);
      if (game) {
        t.send(t.host, { type: "table_start_bots" });
        await t.settle(() => t.lastState(t.host) !== undefined, 100_000);
      }
      const [first, second] = game ? nearbyClaimable(t.room!, t.clock.now()) : [2, 3];
      const zed = await t.join("Zed", { device: "zed-phone", seat: first });
      const token = zed.token;
      expect(token).not.toBeNull();
      const oldPeer = t.fake.peersOf(t.code).at(-1)!;
      t.fake.lose(oldPeer);
      await t.join("Zed", { device: "zed-phone", seat: second, token, player: zed });
      expect(zed.token).toBe(token);
      expect(t.fake.peersOf(t.code)).not.toContain(oldPeer);
      const seats = t.room!.lobby ?? t.room!.seats;
      const held = seats.flatMap((s, i) => (s && !s.isBot && s.connected && s.token === token ? [i] : []));
      expect(held).toEqual([first]);
    }, 60_000);
  }
});
