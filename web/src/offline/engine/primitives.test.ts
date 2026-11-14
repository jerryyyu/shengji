// @vitest-environment node
/// <reference types="node" />
// The randomized and edge-case inputs of server/tests/test_fast_parity.py,
// with the pure Python engine's outputs, replayed through the TS port.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { type Card, type EffSuit, type TrumpSuit, Ordering } from "./cards";
import { type Decomposition, type Shape, decompose, decomposeMatching, findTractorRuns, pairCount } from "./combos";
import { EngineAssertion, IllegalPlay, beats, checkInHand, uniformSuit, validateFollow, validateLead } from "./legal";

const DIR = process.env.OFFLINE_ENGINE_FIXTURES ?? fileURLToPath(new URL("../fixtures", import.meta.url));

type Cfg = [TrumpSuit, string];
type Comp = [string, Card[], number, number];
interface Primitives {
  format: number;
  decompose: [Cfg, Card[], Comp[], Card[][][]][];
  beats: [Cfg, Card[], Card[], EffSuit, number, boolean, number][];
  matching: [Cfg, Card[], Shape, Comp[] | null][];
  follow: [Cfg, Card[], Card[], Card[], string | null, string | null, EffSuit | null, number][];
  lead: [Cfg, Card[], Card[], Card[][], { err?: string; forced?: Card[]; msg?: string }][];
}

const prim = JSON.parse(gunzipSync(readFileSync(join(DIR, "primitives.json.gz"))).toString("utf8")) as Primitives;
const ord = (cfg: Cfg): Ordering => new Ordering(cfg[0], cfg[1]);
const dec = (d: Decomposition | null): Comp[] | null =>
  d === null ? null : d.components.map((c) => [c.kind, c.cards, c.top, c.pairLen]);

function errorOf(fn: () => void): string | null {
  try {
    fn();
    return null;
  } catch (e) {
    if (e instanceof IllegalPlay) return e.message;
    if (e instanceof EngineAssertion) return "AssertionError";
    throw e;
  }
}

function diffs<T>(rows: T[], check: (row: T) => unknown | null): unknown[] {
  const out: unknown[] = [];
  for (const row of rows) {
    const d = check(row);
    if (d !== null && out.length < 10) out.push(d);
  }
  return out;
}

describe("offline engine primitives vs the Python engine", () => {
  it("decompose and tractor runs", () => {
    expect(prim.decompose.length).toBeGreaterThan(5000);
    const bad = diffs(prim.decompose, ([cfg, cards, want, runs]) => {
      const o = ord(cfg);
      const got = dec(decompose(cards, o));
      const gotRuns = [1, 2, 3, 4, 5, 6].map((k) => findTractorRuns(cards, o, k));
      return JSON.stringify([got, gotRuns]) === JSON.stringify([want, runs]) ? null : { cfg, cards, got, want };
    });
    expect(bad).toEqual([]);
  });

  it("beats", () => {
    expect(prim.beats.length).toBeGreaterThan(10000);
    const bad = diffs(prim.beats, ([cfg, ch, lead, suit, top, won, wtop]) => {
      const got = beats(ch, lead, suit, top, ord(cfg));
      return got[0] === won && got[1] === wtop ? null : { cfg, ch, lead, suit, top, got, want: [won, wtop] };
    });
    expect(bad).toEqual([]);
  });

  it("decompose_matching", () => {
    expect(prim.matching.length).toBeGreaterThan(10000);
    const bad = diffs(prim.matching, ([cfg, cards, shape, want]) => {
      const got = dec(decomposeMatching(cards, ord(cfg), shape));
      return JSON.stringify(got) === JSON.stringify(want) ? null : { cfg, cards, shape, got, want };
    });
    expect(bad).toEqual([]);
  });

  it("validate_follow, check_in_hand, uniform_suit, pair_count", () => {
    expect(prim.follow.length).toBeGreaterThan(10000);
    const bad = diffs(prim.follow, ([cfg, play, hand, lead, vf, cih, us, pc]) => {
      const o = ord(cfg);
      const got = [
        errorOf(() => validateFollow(play, hand, lead, o)),
        errorOf(() => checkInHand(hand, play)),
        play.length ? uniformSuit(play, o) : null,
        pairCount(play),
      ];
      const want = [vf, cih, us, pc];
      return JSON.stringify(got) === JSON.stringify(want) ? null : { cfg, play, hand, lead, got, want };
    });
    expect(bad).toEqual([]);
  });

  it("validate_lead and the throw penalty", () => {
    expect(prim.lead.length).toBeGreaterThan(500);
    let fired = 0;
    const bad = diffs(prim.lead, ([cfg, play, hand, others, want]) => {
      let got: { err?: string; forced?: Card[]; msg?: string };
      try {
        const v = validateLead(play, hand, others, ord(cfg));
        got = v.message === null ? {} : { forced: v.actual, msg: v.message };
      } catch (e) {
        if (!(e instanceof IllegalPlay)) throw e;
        got = { err: e.message };
      }
      if (want.forced) fired += 1;
      return JSON.stringify(got) === JSON.stringify(want) ? null : { cfg, play, hand, others, got, want };
    });
    expect(bad).toEqual([]);
    expect(fired).toBeGreaterThan(100);
  });
});
