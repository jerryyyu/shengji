import { describe, expect, it } from "vitest";
import { buildReplay, type RoundReplayDoc } from "./reducer";
import finished from "./server-round-finished.fixture.json";
import unfinished from "./server-round-unfinished.fixture.json";

// These fixtures are responses captured from the server's
// GET /api/me/games/{id}/rounds/{n} tests, so the reducer is held to the
// shapes the server actually sends.
describe("server round responses", () => {
  it("replays a finished round to its result with the viewer's hand emptied", () => {
    const replay = buildReplay(finished as unknown as RoundReplayDoc);
    expect(replay.complete).toBe(true);
    expect(replay.trickCount).toBeGreaterThan(0);
    const first = replay.frames[0];
    const last = replay.frames[replay.frames.length - 1];
    expect(first.hand.length).toBeGreaterThan(0);
    expect(last.kind).toBe("end");
    expect(last.result).not.toBeNull();
    expect(last.hand.length).toBe(0);
  });

  it("replays an unfinished round with only the viewer's hand known", () => {
    const doc = unfinished as unknown as RoundReplayDoc;
    const replay = buildReplay(doc);
    expect(replay.complete).toBe(false);
    const first = replay.frames[0];
    expect(first.hand.length).toBeGreaterThan(0);
    first.hands.forEach((h, seat) => {
      if (seat !== doc.seat) expect(h).toBeNull();
    });
    for (const f of replay.frames) expect(f.result).toBeNull();
  });
});
