// @vitest-environment node
/// <reference types="node" />
// Holds the offline engine to the Python engine: replays every round in the
// fixtures written by server/scripts/gen_offline_engine_fixtures.py. Set
// OFFLINE_ENGINE_FIXTURES to a directory to replay another fixture set (the
// 10,000-round bar) instead of the committed one.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { FixtureReplayer, type RoundRecord } from "./fixtureReplay";

const DIR = process.env.OFFLINE_ENGINE_FIXTURES ?? fileURLToPath(new URL("../fixtures", import.meta.url));

function readLines(name: string): string[] {
  return gunzipSync(readFileSync(join(DIR, name))).toString("utf8").split("\n").filter((l) => l.length);
}

describe("offline engine vs the Python engine (recorded rounds)", () => {
  it("replays every round with no mismatch", () => {
    const [headerLine, ...lines] = readLines("rounds.jsonl.gz");
    const header = JSON.parse(headerLine) as { format: number; rounds: number; stats: Record<string, number> };
    expect(header.format).toBe(1);
    expect(lines.length).toBe(header.rounds);
    const r = new FixtureReplayer();
    for (const line of lines) r.replayRound(JSON.parse(line) as RoundRecord);
    console.log(JSON.stringify({ dir: DIR, counts: r.counts, mismatchesByArea: r.areaCounts }));
    expect(r.mismatches).toEqual([]);
    expect(r.counts.rounds).toBe(header.rounds);
    // The replay saw everything the generator recorded.
    expect(r.counts.plays).toBe(header.stats.plays);
    expect(r.counts.tricks).toBe(header.stats.tricks);
    expect(r.counts.legalityChecks).toBe(header.stats.legality_checks);
    expect(r.counts.illegalAttempts).toBe(header.stats.illegal_attempts);
    expect(r.counts.failedThrows).toBe(header.stats.failed_throws);
    expect(r.counts.enumeratedDecisions).toBe(header.stats.enumerated_decisions ?? 0);
  }, 3_600_000);
});
