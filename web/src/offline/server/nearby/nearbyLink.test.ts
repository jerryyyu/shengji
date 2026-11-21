// @vitest-environment node
// A joiner's moves on the fake transport, end to end through its socket, the
// host boundary and the room: each one applies as soon as it arrives (never
// at the move clock's end), Start begins the game at once when everyone is
// ready, I'm back hands the seat back at once, a link whose frames stop
// reaching the host is found stuck within seconds and replaced, and a move
// sent again on the new link can never apply twice.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog, nearbyLogText } from "../../../nearbyLog";
import { AWAY_IN_A_ROW, MOVE_TIMER, type LocalRoom } from "../server";
import { setNearbyForTests } from "./flag";
import { LIMITS } from "./protocol";
import { NearbySocket } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

/** Seconds each frame takes on the fake radio. */
const DELAY = 0.05;

/** Every action the room applied, with the clock time and seat. */
function recordActions(t: NearbyTable): { at: number; seat: number; type: string }[] {
  const out: { at: number; seat: number; type: string }[] = [];
  const server = t.server;
  const handle = server.handleAction.bind(server);
  server.handleAction = (room: LocalRoom, seat: number, msg: Record<string, unknown>) => {
    out.push({ at: t.clock.now(), seat, type: String(msg.type) });
    handle(room, seat, msg);
  };
  return out;
}

/** Every game frame a player's socket sent, with the clock time. */
function recordSends(t: NearbyTable, p: Player): { at: number; type: string }[] {
  const out: { at: number; type: string }[] = [];
  const sock = p.sock;
  const send = sock.send.bind(sock);
  sock.send = (data: string) => {
    out.push({ at: t.clock.now(), type: String((JSON.parse(data) as Frame).type) });
    send(data);
  };
  return out;
}

const GAME = new Set(["declare", "pass_declare", "bury", "play", "next_round", "im_back", "table_start"]);

describe("a joiner's moves reach the room at once", () => {
  it("every declare, bury and play applies within a round trip, and the bot never moves for the joiner", async () => {
    // a deal where the joiner is the banker, so its bury is covered
    let buried = false;
    for (let seed = 1; seed <= 40 && !buried; seed++) {
      const t = new NearbyTable(seed, 1, DELAY);
      await t.open(true);
      const j = await t.join("Mei", { drive: true });
      const applied = recordActions(t);
      const sent = recordSends(t, j);
      t.send(t.host, { type: "table_start_bots" });
      await t.settle(() => t.lastState(j)?.phase === "round_end", 2_000_000);
      const seat = j.seat!;
      const moves = sent.filter((s) => GAME.has(s.type));
      expect(moves.length).toBeGreaterThan(5);
      for (const m of moves) {
        const hit = applied.find((a) => a.seat === seat && a.type === m.type && a.at >= m.at);
        expect(hit, `${m.type} at ${m.at}`).toBeDefined();
        // one frame's trip, well inside any timer
        expect(hit!.at - m.at).toBeLessThanOrEqual(DELAY + 1e-9);
      }
      const sd = t.room!.seats[seat];
      expect(sd.timeoutsInRound).toBe(0);
      expect(sd.away).toBe(false);
      buried = moves.some((m) => m.type === "bury");
    }
    expect(buried).toBe(true);
  }, 120_000);

  it("Start: once both are ready the game deals at once, with no ring to wait out", async () => {
    const t = new NearbyTable(7, 1, DELAY);
    await t.open();
    const j = await t.join("Mei");
    t.send(t.host, { type: "table_start" });
    await t.advance(0.5);
    expect(t.room!.game).toBeNull();
    const at = t.clock.now();
    t.send(j, { type: "table_start" });
    await t.settle(() => t.room!.game !== null, 10_000);
    expect(t.clock.now() - at).toBeLessThanOrEqual(DELAY + 1e-9);
    await t.settle(() => t.lastState(j) !== undefined, 10_000);
    expect(t.clock.now() - at).toBeLessThan(1);
  });

  it("a joiner marked away gets the seat back the moment I'm back arrives", async () => {
    const t = new NearbyTable(3, 1, DELAY);
    await t.open(true);
    const j = await t.join("Mei");
    t.send(t.host, { type: "table_start_bots" });
    const seat = () => j.seat!;
    // the joiner does nothing: its clock runs out until the room marks it away
    await t.settle(() => t.room?.game !== null && t.room!.seats[seat()]?.away === true, 5_000_000);
    expect(t.room!.seats[seat()].timeoutsInRow).toBeGreaterThanOrEqual(AWAY_IN_A_ROW);
    await t.settle(() => t.lastState(j)?.players !== undefined
      && (t.lastState(j)!.players as { seat: number; away?: boolean }[]).find((p) => p.seat === seat())?.away === true, 100_000);
    const at = t.clock.now();
    t.send(j, { type: "im_back" });
    await t.settle(() => !t.room!.seats[seat()].away, 10_000);
    expect(t.clock.now() - at).toBeLessThanOrEqual(DELAY + 1e-9);
    expect(t.server.drives(t.room!, seat())).toBe(false);
    // and the joiner's own page hears it in the next state
    await t.settle(() => (t.lastState(j)!.players as { seat: number; away?: boolean }[])
      .find((p) => p.seat === seat())?.away === false, 10_000);
    expect(t.clock.now() - at).toBeLessThan(2 * DELAY + 0.5);
  }, 120_000);
});

describe("a stuck link", () => {
  /** A two-person game at the joiner's bury: the joiner is driven (so it
   *  declares and can be the banker) up to its bury, which the test sends
   *  itself through `send`. */
  async function atJoinersBury(): Promise<{ t: NearbyTable; j: Player; seat: number; send: (m: object) => void }> {
    for (let seed = 1; seed <= 40; seed++) {
      const t = new NearbyTable(seed, 1, DELAY);
      await t.open(true);
      const j = await t.join("Mei", { drive: true });
      const sock = j.sock;
      const raw = sock.send.bind(sock);
      sock.send = (d: string) => { if ((JSON.parse(d) as Frame).type !== "bury") raw(d); };
      t.send(t.host, { type: "table_start_bots" });
      await t.settle(() => {
        const s = t.lastState(j);
        return s !== undefined && (s.phase === "play" || (s.phase === "bury" && s.turn === j.seat));
      }, 2_000_000);
      const s = t.lastState(j);
      if (s && s.phase === "bury") {
        j.driver = null;
        return { t, j, seat: j.seat!, send: (m) => raw(JSON.stringify(m)) };
      }
    }
    throw new Error("no deal with the joiner as banker");
  }

  const peerOf = (t: NearbyTable) => t.fake.peersOf(t.code)[0];
  const hand = (p: Player) => (p.frames.filter((f) => f.type === "state").at(-1)!.hand as { id: number }[]);

  it("frames lost one way: the joiner's socket finds it within seconds, and its bury sent again applies once", async () => {
    const { t, j, seat, send } = await atJoinersBury();
    const bury = { type: "bury", card_ids: hand(j).slice(0, 8).map((c) => c.id) };
    t.fake.lose(peerOf(t));
    const at = t.clock.now();
    send(bury);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 100_000);
    // stuck after the pong's wait, long before the move clock
    expect(t.clock.now() - at).toBeLessThanOrEqual(LIMITS.pongSeconds + 2 * DELAY + 1e-6);
    expect(t.clock.now() - at).toBeLessThan(MOVE_TIMER / 4);
    expect(nearbyLogText()).toMatch(/STUCK: no pong after a move/);
    expect(t.room!.round!.phase).toBe("bury");
    // the page's new link takes the seat back by token and sends the bury again
    await t.join("Mei", { token: j.token, player: j });
    expect(t.lastState(j)!.phase).toBe("bury");
    t.send(j, bury);
    await t.settle(() => t.room!.round!.phase !== "bury", 10_000);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
  }, 120_000);

  it("a bury held on the old link and delivered after the resume never applies a second time", async () => {
    const { t, j, seat, send } = await atJoinersBury();
    const bury = { type: "bury", card_ids: hand(j).slice(0, 8).map((c) => c.id) };
    const old = peerOf(t);
    t.fake.hold(old);
    send(bury);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 100_000);
    await t.join("Mei", { token: j.token, player: j });
    t.send(j, bury);
    await t.settle(() => t.room!.round!.phase !== "bury", 10_000);
    // the old link's frames arrive now: the host has closed that link
    t.fake.release(old);
    await t.advance(2);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
    expect(nearbyLogText()).toMatch(/IGNORED bury from .*: no such link/);
    // the same bury sent twice on one link: the second is refused by the room's state
    t.send(j, bury);
    await t.advance(1);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
    expect(j.frames.filter((f) => f.type === "error").length).toBeGreaterThan(0);
  }, 120_000);

  it("a bury in flight when the link is called stuck goes once more on the resumed link, and only once", async () => {
    const { t, j, seat, send } = await atJoinersBury();
    const bury = { type: "bury", card_ids: hand(j).slice(0, 8).map((c) => c.id) };
    const errorsBefore = j.frames.filter((f) => f.type === "error").length;
    t.fake.lose(peerOf(t));
    send(bury);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 100_000);
    expect(t.room!.round!.phase).toBe("bury");
    // the page's new link resumes by token; the page itself sends nothing
    const sock = await t.resume(j);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    await t.advance(1);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
    expect(nearbyLogText()).toMatch(/resume: the unanswered bury sent again/);
    // the page's own once-more on the new link (Table's resend) is not sent twice
    t.send(j, bury);
    await t.advance(1);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
    expect(j.frames.filter((f) => f.type === "error").length).toBe(errorsBefore);
    // and a later rebuild sends nothing again
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => sock.readyState === NearbySocket.CLOSED, 1000);
    await t.resume(j);
    await t.advance(1);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
    expect(nearbyLogText().match(/the unanswered bury sent again/g)).toHaveLength(1);
  }, 120_000);

  it("a bury the host applied before the link went is not sent again", async () => {
    const { t, j, seat, send } = await atJoinersBury();
    const bury = { type: "bury", card_ids: hand(j).slice(0, 8).map((c) => c.id) };
    const errorsBefore = j.frames.filter((f) => f.type === "error").length;
    send(bury);
    await t.settle(() => t.room!.round!.phase !== "bury", 10_000);
    // the link goes before the joiner hears the answer
    t.fake.drop(t.code, peerOf(t));
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    await t.resume(j);
    await t.advance(1);
    expect(t.room!.actions.filter((a) => a[0] === "bury" && a[1] === seat)).toHaveLength(1);
    expect(nearbyLogText()).not.toMatch(/sent again/);
    expect(j.frames.filter((f) => f.type === "error").length).toBe(errorsBefore);
  }, 120_000);

  it("a link that only answers late is not called stuck", async () => {
    const t = new NearbyTable(5, 1, 1.5);
    await t.open(true);
    const j = await t.join("Mei", { drive: true });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j)?.phase === "round_end", 4_000_000);
    expect(nearbyLogText()).not.toMatch(/STUCK/);
  }, 120_000);
});
