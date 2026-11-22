// @vitest-environment node
// A joiner whose link drops while it owes a play and comes back by token:
// its move clock stood still while it was gone, so the time away never
// runs it out or counts a strike, and one that had nearly run out before
// the drop has RETURN_MIN left on the return.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog } from "../../../nearbyLog";
import { MOVE_TIMER, RETURN_MIN } from "../server";
import { setNearbyForTests } from "./flag";
import { NearbySocket } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

const DELAY = 0.05;

/** A two-person game at the joiner's first play, which it never sends. */
async function atJoinersPlay(): Promise<{ t: NearbyTable; j: Player; seat: number }> {
  const t = new NearbyTable(6, 1, DELAY);
  await t.open(true);
  const j = await t.join("Mei", { drive: true });
  const raw = j.sock.send.bind(j.sock);
  j.sock.send = (d: string) => { if ((JSON.parse(d) as Frame).type !== "play") raw(d); };
  t.send(t.host, { type: "table_start_bots" });
  await t.settle(() => {
    const s = t.lastState(j);
    return s !== undefined && s.phase === "play" && s.turn === j.seat;
  }, 4_000_000);
  j.driver = null;
  return { t, j, seat: j.seat! };
}

const deadline = (s: Frame | undefined, seat: number) =>
  (s!.players as { seat: number; turn_deadline: number | null }[]).find((p) => p.seat === seat)!.turn_deadline;

async function dropAndReturn(t: NearbyTable, j: Player, away: number): Promise<void> {
  t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
  await t.settle(() => (j.sock as NearbySocket).readyState === NearbySocket.CLOSED, 1000);
  await t.advance(away);
  const sock = await t.resume(j);
  expect(sock.readyState).toBe(NearbySocket.OPEN);
  await t.advance(0.5);
}

describe("the move clock across a drop", () => {
  it("back after 55 s: the clock stood still, and no bot move or strike comes of the time away", async () => {
    const { t, j, seat } = await atJoinersPlay();
    const sd = t.room!.seats[seat];
    const turn = t.room!.round!.history.length;
    await dropAndReturn(t, j, 55);
    expect(t.room!.round!.turn).toBe(seat);
    expect(deadline(t.lastState(j), seat)).toBeGreaterThan(MOVE_TIMER - 2);
    // the old clock's end passes with the player at the table
    await t.advance(15);
    expect(t.room!.round!.turn).toBe(seat);
    expect(t.room!.round!.history.length).toBe(turn);
    expect(sd.timeoutsInRound).toBe(0);
  }, 120_000);

  it(`a clock nearly out at the drop has ${RETURN_MIN} s on the return, and then runs out as usual`, async () => {
    const { t, j, seat } = await atJoinersPlay();
    const sd = t.room!.seats[seat];
    await t.advance(MOVE_TIMER - 5);
    await dropAndReturn(t, j, 20);
    expect(t.room!.round!.turn).toBe(seat);
    const left = deadline(t.lastState(j), seat)!;
    expect(left).toBeGreaterThan(RETURN_MIN - 1);
    expect(left).toBeLessThanOrEqual(RETURN_MIN);
    await t.advance(RETURN_MIN - 1);
    expect(t.room!.round!.turn).toBe(seat);
    expect(sd.timeoutsInRound).toBe(0);
    // present for its whole RETURN_MIN: the bot makes the play, a strike
    await t.settle(() => t.room!.round!.turn !== seat, 100_000);
    expect(sd.timeoutsInRound).toBe(1);
  }, 120_000);
});
