// @vitest-environment node
// A phone's own pause (its page's JS frozen, or in the background) is not
// someone else's silence or slowness. A host page stopped 30 s ends no link
// on its first timer back, strikes no one, and its move clock and declare
// window go on from where they stood; a joiner page stopped past its pong
// wait keeps its link. The pause's timers run before its queued link events
// here, the order that once ended every link.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DeviceClock, type Rng } from "../../../../scripts/nearby-chaos/radio";
import { MOVE_TIMER } from "../server";
import { setNearbyForTests } from "./flag";
import { LIMITS, NEARBY_V, PING_TEXT } from "./protocol";
import { NearbySocket } from "./socket";
import { NearbyTable, type Frame } from "./testkit";
import type { JoinHandlers, JoinLink } from "./transport";

beforeEach(() => setNearbyForTests(true));
afterEach(() => setNearbyForTests(null));

/** Back from the pause: every held timer first, then the held events. */
const timersFirst = { chance: () => true } as unknown as Rng;

/** A seated joiner on a raw link that pings every LIMITS.pingSeconds and
 *  never moves (a phone left on the table). */
async function idleJoiner(t: NearbyTable) {
  const r = { link: null as unknown as JoinLink, frames: [] as Frame[], closed: false };
  r.link = await t.fake.join(t.code, { message: (x) => r.frames.push(JSON.parse(x) as Frame), closed: () => { r.closed = true; },
                                       state: () => {} });
  r.link.send(JSON.stringify({ type: "nearby_hello", nearby_v: NEARBY_V, name: "Idle", token: null }));
  const beat = () => {
    if (r.closed) return;
    r.link.send(PING_TEXT);
    t.clock.setTimeout(beat, LIMITS.pingSeconds);
  };
  beat();
  await t.advance(0.5);
  return r;
}

async function frozenHostTable(seed: number) {
  let dc!: DeviceClock;
  const t = new NearbyTable(seed, 1, 0, null, (vc) => (dc = new DeviceClock(vc)));
  await t.open(true);
  const idle = await idleJoiner(t);
  const seat = t.room!.lobby!.findIndex((s) => s?.name === "Idle");
  expect(seat).toBeGreaterThan(0);
  t.send(t.host, { type: "table_start_bots" });
  return { t, dc: () => dc, idle, seat };
}

async function freeze(t: NearbyTable, dc: DeviceClock, seconds: number): Promise<void> {
  dc.suspend();
  await t.advance(seconds);
  dc.resume(timersFirst);
  await t.advance(0.5);
}

describe("a host page frozen 30 s", () => {
  it("ends no link, strikes no one, and the move clock goes on where it stood", async () => {
    const { t, dc, idle, seat } = await frozenHostTable(21);
    await t.settle(() => {
      const rnd = t.room!.round;
      return !!rnd && (rnd.phase === "play" || rnd.phase === "bury") && rnd.turn === seat;
    }, 3_000_000);
    const sd = t.room!.seats[seat];
    const point = `${t.room!.round!.phase}|${t.room!.round!.hands[seat].length}`;
    // 40 s of the idle player's 60 s gone; then the host stops for 30 s
    await t.advance(40);
    expect(sd.timeoutsInRound).toBe(0);
    await freeze(t, dc(), 30);
    expect(t.nearbyHost!.refused.silent).toBeUndefined();
    expect(idle.closed).toBe(false);
    expect(sd.connected).toBe(true);
    expect(sd.timeoutsInRound).toBe(0);
    expect(t.room!.round!.turn).toBe(seat);
    expect(`${t.room!.round!.phase}|${t.room!.round!.hands[seat].length}`).toBe(point);
    // the clock stood at about 40 s: the player still has about 20 s
    const used = t.clock.now() - sd.turnStarted!;
    expect(used).toBeGreaterThan(38);
    expect(used).toBeLessThan(MOVE_TIMER - 15);
    await t.advance(MOVE_TIMER - used + 1);
    expect(sd.timeoutsInRound).toBe(1);
  }, 60_000);

  it("the declare window keeps what it had left", async () => {
    const { t, dc } = await frozenHostTable(22);
    await t.settle(() => t.room!.round?.phase === "declare" && t.room!.declareUntil !== null, 3_000_000);
    await t.advance(1);
    const left = t.room!.declareUntil! - t.clock.now();
    expect(left).toBeGreaterThan(1);
    await freeze(t, dc(), 30);
    expect(t.room!.round!.phase).toBe("declare");
    expect(t.room!.declareUntil! - t.clock.now()).toBeGreaterThan(left - 1.6);
  }, 60_000);
});

describe("a joiner page frozen past its pong wait", () => {
  it("keeps its link: the pong it missed is still on its way in", async () => {
    const t = new NearbyTable(23);
    await t.open(true);
    const jc = new DeviceClock(t.clock);
    // the joiner's link events run in its page's JS
    const transport = {
      host: t.fake.host.bind(t.fake),
      join: (code: string, h: JoinHandlers) => t.fake.join(code, {
        ...h,
        message: (x: string) => jc.post(() => h.message(x)),
        closed: () => jc.post(() => h.closed()),
      }),
    };
    const sock = new NearbySocket(transport, t.code, null, jc);
    let closed = false;
    sock.onclose = () => { closed = true; };
    sock.onopen = () => sock.send(JSON.stringify({ type: "table_join", code: t.code, name: "Mei", token: null }));
    await t.settle(() => sock.readyState === NearbySocket.OPEN && t.room!.lobby!.some((s) => s?.name === "Mei"));
    await t.advance(LIMITS.pingSeconds + 0.5);
    // a move's probe ping goes out, and the page stops before its pong is
    // in: 12 s, past the pong's wait, well inside the host's silence
    sock.send(JSON.stringify({ type: "table_start" }));
    jc.suspend();
    await t.advance(12);
    jc.resume(timersFirst);
    await t.advance(LIMITS.pongSeconds + 1);
    expect(closed).toBe(false);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    expect(t.nearbyHost!.refused.silent).toBeUndefined();
  }, 60_000);
});
