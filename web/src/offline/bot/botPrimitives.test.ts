// @vitest-environment node
/// <reference types="node" />
// HeuristicBot's policy leaves (_lowest, _forced_follow, _cheapest_winning) on
// the randomized and named inputs of server/tests/test_fast_parity.py, with
// the pure Python outputs, replayed through the TS port.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { type Card, type EffSuit, type TrumpSuit, Ordering } from "../engine/cards";
import { EngineAssertion, IllegalPlay } from "../engine/legal";
import { HeuristicBot } from "./heuristic";

const DIR = process.env.OFFLINE_BOT_FIXTURES ?? fileURLToPath(new URL("../fixtures", import.meta.url));

type Cfg = [TrumpSuit, string];
type Outcome = Card[] | null | { exc: string; msg?: string };
interface BotPrimitives {
  format: number;
  lowest: [Cfg, boolean, Card[], Card[] | null, [Card, Card, Card]][];
  forced: [Cfg, boolean, Card[], Card[], Card[] | null, [Outcome, Outcome]][];
  cheapest: [Cfg, Card[], Card[], EffSuit, number, Outcome, string?][];
}

const prim = JSON.parse(gunzipSync(readFileSync(join(DIR, "bot_primitives.json.gz"))).toString("utf8")) as BotPrimitives;
const ord = (cfg: Cfg): Ordering => new Ordering(cfg[0], cfg[1]);

function botFor(voidDump: boolean): HeuristicBot {
  const b = new HeuristicBot();
  b.voidDump = voidDump;
  return b;
}

function outcome(fn: () => Card[] | null): Outcome {
  try {
    return fn();
  } catch (e) {
    if (e instanceof IllegalPlay) return { exc: "IllegalPlay", msg: e.message };
    if (e instanceof EngineAssertion) return { exc: "AssertionError" };
    throw e;
  }
}

describe("HeuristicBot policy leaves vs Python", () => {
  it("_lowest", () => {
    const bad: unknown[] = [];
    for (const [cfg, voidDump, hand, avoid, want] of prim.lowest) {
      const o = ord(cfg);
      const bot = botFor(voidDump);
      const av = avoid === null ? undefined : new Set(avoid);
      const got = [
        bot.lowest(hand, o, { avoid: av }),
        bot.lowest(hand, o, { avoidPoints: true, avoid: av }),
        bot.lowest(hand, o, { seekPoints: true, avoid: av }),
      ];
      if (JSON.stringify(got) !== JSON.stringify(want)) bad.push([cfg, voidDump, hand, avoid, got, want]);
    }
    expect(prim.lowest.length).toBeGreaterThanOrEqual(1000);
    expect(bad.slice(0, 5)).toEqual([]);
  });

  it("_forced_follow", () => {
    const bad: unknown[] = [];
    for (const [cfg, voidDump, hand, lead, avoid, want] of prim.forced) {
      const o = ord(cfg);
      const bot = botFor(voidDump);
      const av = avoid === null ? undefined : new Set(avoid);
      const got = [false, true].map((prefer) => outcome(() => bot.forcedFollow(hand, lead, o, prefer, av)));
      if (JSON.stringify(got) !== JSON.stringify(want)) bad.push([cfg, voidDump, hand, lead, avoid, got, want]);
    }
    expect(prim.forced.length).toBeGreaterThanOrEqual(1000);
    expect(bad.slice(0, 5)).toEqual([]);
  });

  it("_cheapest_winning", () => {
    const bot = new HeuristicBot();
    const bad: unknown[] = [];
    let wins = 0;
    for (const [cfg, hand, lead, incSuit, incTop, want, label] of prim.cheapest) {
      const got = outcome(() => bot.cheapestWinning(hand, lead, incSuit, incTop, ord(cfg)));
      if (Array.isArray(got)) wins += 1;
      if (JSON.stringify(got) !== JSON.stringify(want)) bad.push([label, cfg, hand, lead, incSuit, incTop, got, want]);
    }
    expect(prim.cheapest.filter((c) => c[6] !== undefined).length).toBe(9);
    expect(wins).toBeGreaterThan(1000);
    expect(bad.slice(0, 5)).toEqual([]);
  });
});
