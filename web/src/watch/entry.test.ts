// The presence line's way in to watching: "N playing" leads to a live table
// only when one can be watched; with none, a replay is offered by name, so
// "Nobody is playing right now" never opens a game.
import { afterEach, describe, expect, it } from "vitest";
import { setLanguageChoice } from "../i18n";
import { presenceParts } from "../queue/tableText";

const base = { tables: 0, playing: 0, waiting: 0, ranked: 0, casual: 0 };
const text = (parts: ReturnType<typeof presenceParts>) => parts.map((p) => p.text).join("");
const links = (parts: ReturnType<typeof presenceParts>) => parts.filter((p) => p.watch).map((p) => p.text);

afterEach(() => setLanguageChoice("system"));

describe("the way in", () => {
  it("links N playing when a live table can be watched", () => {
    const parts = presenceParts({ ...base, tables: 1, playing: 3, ranked: 1, watch: 1, rerun: true });
    expect(links(parts)).toEqual([" · 3 playing"]);
  });

  it("with nobody playing, offers a replay and leaves the nobody line plain", () => {
    const parts = presenceParts({ ...base, watch: 0, rerun: true });
    expect(text(parts)).toBe("Nobody is playing right now · Watch a replay");
    expect(links(parts)).toEqual([" · Watch a replay"]);
  });

  it("people at tables none of which can be watched: their count is plain, the replay is the link", () => {
    const parts = presenceParts({ ...base, tables: 1, playing: 2, ranked: 1, watch: 0, rerun: true });
    expect(links(parts)).toEqual([" · Watch a replay"]);
    expect(parts.find((p) => p.text.includes("2 playing"))?.watch).toBe(false);
  });

  it("nothing to watch, or a server without the feed: no link at all", () => {
    expect(links(presenceParts({ ...base, watch: 0, rerun: false }))).toEqual([]);
    expect(links(presenceParts({ ...base, tables: 1, playing: 2, ranked: 1 }))).toEqual([]);
  });

  it("says it in Chinese, both scripts", () => {
    setLanguageChoice("zh-Hans");
    expect(text(presenceParts({ ...base, watch: 0, rerun: true }))).toBe("现在没人在玩 · 看回放");
    setLanguageChoice("zh-Hant");
    expect(text(presenceParts({ ...base, watch: 0, rerun: true }))).toBe("現在沒人在玩 · 看回放");
  });

  it("a full table of people (no seat for a newcomer) still leads to a live table", () => {
    const parts = presenceParts({ ...base, watch: 1, rerun: false });
    expect(text(parts)).toBe("Watch a table");
    expect(links(parts)).toEqual(["Watch a table"]);
    setLanguageChoice("zh-Hans");
    expect(text(presenceParts({ ...base, watch: 1, rerun: true }))).toBe("看一桌");
    setLanguageChoice("zh-Hant");
    expect(text(presenceParts({ ...base, watch: 1, rerun: true }))).toBe("看一桌");
  });
});
