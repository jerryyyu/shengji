// @vitest-environment node
/// <reference types="node" />
// Holds the offline bots to Python's SmartBot and HeuristicBot: replays every
// round in the fixtures written by server/scripts/gen_offline_bot_fixtures.py
// and asks the TS bot at every declare, bury and play. Set
// OFFLINE_BOT_FIXTURES to a directory to replay another fixture set (the
// 10,000-round bar) and OFFLINE_BOT_TIMING=1 to print per-decision timings.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { type BotRoundRecord, BotReplayer, percentiles } from "./botReplay";

const DIR = process.env.OFFLINE_BOT_FIXTURES ?? fileURLToPath(new URL("../fixtures", import.meta.url));
const TIMING = process.env.OFFLINE_BOT_TIMING === "1";

describe("offline bots vs the Python bots (recorded decisions)", () => {
  it("reproduces every decision", () => {
    const text = gunzipSync(readFileSync(join(DIR, "bot_rounds.jsonl.gz"))).toString("utf8");
    const [headerLine, ...lines] = text.split("\n").filter((l) => l.length);
    const header = JSON.parse(headerLine) as { format: number; rounds: number; mixed: number; stats: Record<string, number> };
    expect(header.format).toBe(1);
    expect(lines.length).toBe(header.rounds + header.mixed);
    const r = new BotReplayer(TIMING);
    for (const line of lines) r.replayRound(JSON.parse(line) as BotRoundRecord);
    const timing = TIMING ? Object.fromEntries(Object.entries(r.times).map(([k, v]) => [k, percentiles(v)])) : undefined;
    const all = TIMING ? percentiles(Object.values(r.times).flat()) : undefined;
    console.log(JSON.stringify({ dir: DIR, rounds: r.rounds, games: r.games, counts: r.counts, mismatches: r.mismatchCounts, timing, all }));
    expect(r.mismatches).toEqual([]);
    expect(r.rounds).toBe(header.rounds + header.mixed);
    // Every decision the generator recorded was asked of the TS bot.
    const s = header.stats;
    for (const kind of ["smart", "heuristic"]) {
      expect(r.counts[`${kind}_declare`] ?? 0).toBe(s[`${kind}_declare_decisions`] ?? 0);
      expect(r.counts[`${kind}_declares_made`] ?? 0).toBe(s[`${kind}_declares`] ?? 0);
      for (const t of ["bury", "lead", "follow"]) expect(r.counts[`${kind}_${t}`] ?? 0).toBe(s[`${kind}_${t}`] ?? 0);
    }
    expect(r.counts.smart_follow).toBeGreaterThan(0);
    expect(r.counts.heuristic_follow).toBeGreaterThan(0);
  }, 3_600_000);
});
