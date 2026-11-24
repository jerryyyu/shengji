// The message table: every key has both languages, no key is defined in two
// areas, and a zh sentence uses exactly the placeholders its English does.
import { afterEach, describe, expect, it } from "vitest";
import { AREAS, MESSAGES } from "./messages";
import { localeFor, reloadLanguage, setLanguageChoice, t, tIn, locale } from ".";
import type { MessageKey } from ".";

/** Fills any placeholder a message names, with a number (a plural's count
 *  must be one). */
const SAMPLE = new Proxy({} as Record<string, number>, {
  has: () => true,
  get: (_, k) => (typeof k === "string" ? 3 : undefined),
});

function placeholders(msg: unknown): string[] {
  if (typeof msg !== "string") return [];
  return [...msg.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
}

describe("the message table", () => {
  const keys = Object.keys(MESSAGES) as MessageKey[];

  it("has entries", () => {
    expect(keys.length).toBeGreaterThan(10);
  });

  it("gives every key a non-empty English and Simplified Chinese message", () => {
    for (const key of keys) {
      const en = tIn("en", key, SAMPLE);
      const zh = tIn("zh-Hans", key, SAMPLE);
      expect(en.trim(), `${key} en`).not.toBe("");
      expect(zh.trim(), `${key} zh`).not.toBe("");
    }
  });

  it("defines each key in one area only, under that area's prefix", () => {
    const seen = new Map<string, string>();
    for (const [area, table] of Object.entries(AREAS)) {
      for (const key of Object.keys(table)) {
        expect(seen.get(key), `${key} is in ${seen.get(key)} and ${area}`).toBeUndefined();
        seen.set(key, area);
      }
    }
  });

  it("uses the same placeholders in both languages", () => {
    for (const key of keys) {
      const entry = MESSAGES[key];
      if (typeof entry.en !== "string" || typeof entry.zh !== "string") continue;
      expect(placeholders(entry.zh), key).toEqual(placeholders(entry.en));
    }
  });

  it("leaves no placeholder unfilled when its params are given", () => {
    for (const key of keys) {
      expect(tIn("en", key, SAMPLE), key).not.toMatch(/\{\w+\}/);
      expect(tIn("zh-Hans", key, SAMPLE), key).not.toMatch(/\{\w+\}/);
    }
  });

  it("keeps the decided terms out of the zh table's rejected spellings", () => {
    // the decided terms: bots are 机器人, the code is 房间码, the bury is 埋底
    for (const key of keys) {
      const zh = tIn("zh-Hans", key, SAMPLE);
      expect(zh, key).not.toMatch(/电脑|房间号|扣底|守方|攻方/);
    }
  });
});

describe("locale selection", () => {
  afterEach(() => { localStorage.clear(); reloadLanguage(); });

  it("reads Simplified Chinese for any zh tag but Traditional", () => {
    expect(localeFor(["zh-CN"])).toBe("zh-Hans");
    expect(localeFor(["zh-Hans-CN"])).toBe("zh-Hans");
    expect(localeFor(["zh"])).toBe("zh-Hans");
    expect(localeFor(["zh-SG"])).toBe("zh-Hans");
    expect(localeFor(["zh-Hant"])).toBe("en");
    expect(localeFor(["zh-TW"])).toBe("en");
    expect(localeFor(["zh-HK"])).toBe("en");
    expect(localeFor(["zh-Hant-TW"])).toBe("en");
    expect(localeFor(["en-US", "zh-CN"])).toBe("en");
    expect(localeFor([])).toBe("en");
  });

  it("keeps the website English until its Language row picks 中文", () => {
    // jsdom is not the app: Follow system resolves to English
    expect(locale()).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    setLanguageChoice("zh-Hans");
    expect(locale()).toBe("zh-Hans");
    expect(document.documentElement.lang).toBe("zh-Hans");
    expect(localStorage.getItem("shengji.language")).toBe("zh-Hans");
    expect(t("language.row")).toBe("语言");
    setLanguageChoice("system");
    expect(locale()).toBe("en");
    expect(localStorage.getItem("shengji.language")).toBeNull();
  });

  it("follows the device inside the app", async () => {
    const cap = { isNativePlatform: () => true };
    (window as unknown as { Capacitor?: unknown }).Capacitor = cap;
    const langs = Object.getOwnPropertyDescriptor(Navigator.prototype, "languages");
    Object.defineProperty(navigator, "languages", { configurable: true, get: () => ["zh-Hans-CN"] });
    try {
      reloadLanguage();
      expect(locale()).toBe("zh-Hans");
      setLanguageChoice("en");
      expect(locale()).toBe("en");
    } finally {
      delete (window as unknown as { Capacitor?: unknown }).Capacitor;
      delete (navigator as unknown as { languages?: unknown }).languages;
      if (langs) Object.defineProperty(Navigator.prototype, "languages", langs);
    }
  });
});
