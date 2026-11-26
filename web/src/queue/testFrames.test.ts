// The test doubles' table frame (`tableFrameFor`) against the server's own:
// one (queue_state, table) pair per kind of held queue_state over the
// matchmaking goldens, written by server/tests/test_table_frame.py.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { PartyMsg, TableFrameMsg } from "./messages";
import { tableFrameFor } from "./testFrames";

interface Pair { scenario: string; party: PartyMsg | null; queue_state: Record<string, unknown>; table: TableFrameMsg }

const PAIRS = JSON.parse(readFileSync(join(__dirname, "fixtures", "table_frames.json"), "utf8")) as Pair[];

/** The fields the panel reads: your own seat's name never shows (it is
 *  "You"), and alone a seat's `since` and `sit` are unread (no "Just
 *  joined", no opener's move). */
function read(f: TableFrameMsg, alone: boolean) {
  return {
    code: f.code, mode: f.mode, phase: f.phase, you: f.you, opener: f.opener === f.you, settings: f.settings,
    seats: f.seats.map((s) => ({ seat: s.seat, team: s.team, state: s.state, name: s.you ? null : s.name, you: s.you,
                                 reconnecting: s.reconnecting, since: alone ? null : s.since, sit: alone ? null : s.sit,
                                 pair: s.pair })),
    bots: f.timers.bots?.at ?? null, chatLog: f.chat_log,
  };
}

describe("tableFrameFor", () => {
  it("has the server's pairs to check against, alone and at a waiting table", () => {
    expect(PAIRS.some((p) => p.queue_state.table === null)).toBe(true);
    expect(PAIRS.some((p) => p.queue_state.table !== null)).toBe(true);
    expect(PAIRS.some((p) => p.queue_state.table === null && p.party !== null)).toBe(true);
  });

  it.each(PAIRS.map((p, i) => [`${i} ${p.scenario}`, p] as const))("%s: says what the server's frame says", (_, p) => {
    const alone = p.queue_state.table === null;
    expect(read(tableFrameFor(p.queue_state, p.party), alone)).toEqual(read(p.table, alone));
  });
});
