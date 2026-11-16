// The test doubles' frames (`framer`, `tableFrameFor`) against the server's
// own: one (queue_state, table) pair per kind of held queue_state over the
// matchmaking goldens, written by server/tests/test_table_frame.py. Each
// server pair is turned into a test's description (`describe`, as
// server/tests/table_view.py reads a pair) and framed again.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { PartyMsg, TableFrameMsg } from "./messages";
import { TABLE_NAMES, framer, tableFrameFor } from "./testFrames";

interface Pair { scenario: string; party: PartyMsg | null; queue_state: Record<string, unknown>; table: TableFrameMsg }

const PAIRS = JSON.parse(readFileSync(join(__dirname, "fixtures", "table_frames.json"), "utf8")) as Pair[];

/** The fields the panel reads: your own seat's name never shows (it is
 *  "You"), and alone a seat's `since` and `sit` are unread (no "Just
 *  joined", no opener's move). */
function read(f: TableFrameMsg, alone: boolean) {
  return {
    code: f.code, mode: f.mode, phase: f.phase, you: f.you, opener: f.opener === f.you, settings: f.settings,
    seats: f.seats.map((s) => ({ seat: s.seat, team: s.team, state: s.state, name: s.you ? null : s.name, you: s.you,
                                 ready: s.ready, reconnecting: s.reconnecting, since: alone ? null : s.since, sit: alone ? null : s.sit,
                                 pair: s.pair })),
    bots: f.timers.bots?.at ?? null, startNowAt: f.timers.start_now_at, yourReady: f.your_ready,
    waitingFor: f.waiting_for, chatLog: f.chat_log,
  };
}

/** A test's description of the queue the pair shows: the queue_state with
 *  the table's names read off the frame. */
function describeQueue(p: Pair): Record<string, unknown> {
  const f = p.table;
  const held = f.seats.filter((s) => s.state === "held").map((s) => s.seat);
  const you = f.seats[f.you];
  const partner = you.pair ? (f.you + 2) % 4 : null;
  const others = f.seats.filter((s) => s.state === "taken" && !s.you && !(s.seat === partner && s.pair));
  const table = others.length === 0 ? null : {
    id: f.chat_log, code: f.code, opener: f.opener, you: f.you, held_seat: held[0] ?? null, held_seats: held,
    start_now_at: f.timers.start_now_at, timer: f.timers.bots, you_ready: f.your_ready, waiting_for: f.waiting_for,
    seats: f.seats.map((s) => (s.state !== "taken" ? null : {
      name: s.name, you: s.you, ready: s.ready, reconnecting: s.reconnecting, since: s.since, sit: s.sit,
      pair: s.pair, leader: s.leader })),
  };
  return { ...p.queue_state, table, code: f.code, allow_joiners: f.settings.allow_joiners,
           start_level: f.settings.start_level, opener: f.opener === f.you, held_seat: held[0] ?? null,
           you_ready: f.your_ready, bots_at: table === null ? f.timers.bots?.at ?? null : undefined };
}

describe("tableFrameFor", () => {
  it("has the server's pairs to check against, alone and at a waiting table", () => {
    const kinds = PAIRS.map((p) => [describeQueue(p).table === null, p.party !== null]);
    expect(kinds.some(([alone]) => alone)).toBe(true);
    expect(kinds.some(([alone]) => !alone)).toBe(true);
    expect(kinds.some(([alone, party]) => alone && party)).toBe(true);
  });

  it.each(PAIRS.map((p, i) => [`${i} ${p.scenario}`, p] as const))("%s: says what the server's frame says", (_, p) => {
    const spec = describeQueue(p);
    const alone = spec.table === null;
    expect(read(tableFrameFor(spec, p.party), alone)).toEqual(read(p.table, alone));
  });

  it.each(PAIRS.map((p, i) => [`${i} ${p.scenario}`, p] as const))("%s: a test socket sends the server's queue_state", (_, p) => {
    for (const k of TABLE_NAMES) expect(p.queue_state).not.toHaveProperty(k);
    const [qs] = framer()(describeQueue(p)) as Record<string, unknown>[];
    expect(qs).toEqual(p.queue_state);
  });
});
