// @vitest-environment node
/// <reference types="node" />
// Each Chinese table is written in its own script and leaves nothing in
// English: a zh-Hant string holds no Simplified-only character, a zh-Hans
// string no Traditional-only one, and no Chinese message is Latin words alone. The companions' and colours' names, kept beside their
// art, are held to the same script rule.
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { MESSAGES } from "./messages";
import { tIn } from ".";
import type { MessageKey } from ".";
import { SIMPLIFIED_ONLY, TRADITIONAL_ONLY } from "./scriptChars";

const SAMPLE = new Proxy({} as Record<string, number>, {
  has: () => true,
  get: (_, k) => (typeof k === "string" ? 3 : undefined),
});

/** Each language's own name is written in its own script in every language. */
const NAMES_A_LANGUAGE = new Set<string>(["language.en", "language.zh", "language.zhHant"]);

/** Messages that read the same in every language: a card's face, a rank's
 *  letter, a shorthand players type as it is. */
const SAME_IN_EVERY_LANGUAGE = new Set<string>([
  "table.jokerFace", "table.quickGg", "table.rankJ", "table.rankQ", "table.rankK", "table.rankA",
  "howto.throw.vs",
]);

const HAN = /\p{Script=Han}/u;
const LATIN_WORD = /[A-Za-z]{2,}/;

function wrongScript(text: string, banned: ReadonlySet<string>): string {
  return [...text].filter((c) => banned.has(c)).join("");
}

const keys = Object.keys(MESSAGES) as MessageKey[];

describe("the Chinese tables keep to their scripts", () => {
  it("knows a Simplified character from a Traditional one", () => {
    expect(wrongScript("这个设计", SIMPLIFIED_ONLY)).toBe("这个设计");
    expect(wrongScript("這個設計", SIMPLIFIED_ONLY)).toBe("");
    expect(wrongScript("這個設計", TRADITIONAL_ONLY)).toBe("這個設計");
    expect(wrongScript("这个设计", TRADITIONAL_ONLY)).toBe("");
    expect(wrongScript("后台里面", SIMPLIFIED_ONLY)).toBe("");
    expect(wrongScript("后台里面", TRADITIONAL_ONLY)).toBe("");
  });

  it("writes no Simplified-only character in a zh-Hant message", () => {
    const bad = keys.filter((k) => !NAMES_A_LANGUAGE.has(k))
      .map((k) => [k, wrongScript(tIn("zh-Hant", k, SAMPLE), SIMPLIFIED_ONLY)])
      .filter(([, chars]) => chars);
    expect(bad).toEqual([]);
  });

  it("writes no Traditional-only character in a zh-Hans message", () => {
    const bad = keys.filter((k) => !NAMES_A_LANGUAGE.has(k))
      .map((k) => [k, wrongScript(tIn("zh-Hans", k, SAMPLE), TRADITIONAL_ONLY)])
      .filter(([, chars]) => chars);
    expect(bad).toEqual([]);
  });

  it("leaves no message with English words untranslated in either Chinese", () => {
    const bad: string[] = [];
    for (const k of keys) {
      if (NAMES_A_LANGUAGE.has(k) || SAME_IN_EVERY_LANGUAGE.has(k)) continue;
      for (const loc of ["zh-Hans", "zh-Hant"] as const) {
        const text = tIn(loc, k, SAMPLE);
        if (!HAN.test(text) && LATIN_WORD.test(text)) bad.push(`${k} ${loc}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("names every companion and colour in both scripts, each in its own", () => {
    const files = import.meta.glob("../companion/*.ts", { query: "?url", eager: true });
    const NAME = /\{\s*en:\s*"([^"]*)",\s*zh:\s*"([^"]*)",\s*hant:\s*"([^"]*)"\s*\}/g;
    const bad: string[] = [];
    let seen = 0;
    for (const path of Object.keys(files)) {
      if (path.includes(".test.")) continue;
      const text = readFileSync(new URL(path, import.meta.url), "utf8");
      for (const [, en, zh, hant] of text.matchAll(NAME)) {
        seen += 1;
        if (!HAN.test(zh) || wrongScript(zh, TRADITIONAL_ONLY)) bad.push(`${path}: ${en} zh ${zh}`);
        if (!HAN.test(hant) || wrongScript(hant, SIMPLIFIED_ONLY)) bad.push(`${path}: ${en} hant ${hant}`);
      }
    }
    expect(seen).toBeGreaterThan(40);
    expect(bad).toEqual([]);
  });
});
