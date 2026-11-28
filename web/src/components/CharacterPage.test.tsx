// The stage's one status line: a look's colour, then how it was got or what unlocks it, in every language.
import { afterEach, describe, expect, it } from "vitest";
import type { AuthUser } from "../auth";
import type { LookEntry } from "../companion/look";
import { setLanguageChoice, t } from "../i18n";
import { statusParts } from "./CharacterPage";

const LAMB = "com.jerryyu.shengji.companion.lamb";
const TODAY = new Date(2026, 10, 28);
const user = (over: Partial<AuthUser> = {}): AuthUser => ({
  name: "J", email: "j@x", picture: null, display_name: null, name_shown: "J", rounds_played: 0, ranked_wins: 30, ranked_games: 0,
  ...over,
} as AuthUser);
const line = (entry: LookEntry, u: AuthUser | null, inUse = "tractor/red") => {
  const { name, how } = statusParts(t, entry, inUse, u, TODAY);
  return how ? t("home.statusLine", { name, how }) : name;
};
const lamb: LookEntry = { id: "lamb/ink", unlocked: true, needs: null, product: LAMB };
const won = (of: number, count: "ranked_wins" | "rounds" = "ranked_wins"): LookEntry =>
  ({ id: "tractor/orange", unlocked: true, needs: { count, of } });
const locked: LookEntry = { id: "tractor/jade", unlocked: false, needs: { count: "ranked_wins", of: 50 } };
const free: LookEntry = { id: "tractor/blue", unlocked: true, needs: null };

afterEach(() => setLanguageChoice("system"));

describe("the stage's one status line", () => {
  it.each([
    ["en", "Ink wash · Purchased Nov 27", "Ink wash · Purchased Nov 27, 2025", "Ink wash · Gift", "Lantern orange · 25 ranked rounds won",
      "Lantern orange · A ranked round won", "Lantern orange · 1,000 rounds played", "Jade · Win 50 ranked rounds to unlock · 30 of 50", "Tractor · Enamel blue"],
    ["zh-Hans", "水墨 · 11月27日购买", "水墨 · 2025年11月27日购买", "水墨 · 赠送", "灯笼橙 · 赢 25 局排位",
      "灯笼橙 · 赢一局排位", "灯笼橙 · 打满 1,000 局", "翡翠 · 赢 50 局排位解锁 · 30/50", "拖拉机 · 搪瓷蓝"],
    ["zh-Hant", "水墨 · 11月27日購買", "水墨 · 2025年11月27日購買", "水墨 · 贈送", "燈籠橙 · 贏 25 局排位",
      "燈籠橙 · 贏一局排位", "燈籠橙 · 打滿 1,000 局", "翡翠 · 贏 50 局排位解鎖 · 30/50", "拖拉機 · 搪瓷藍"],
  ] as const)("in %s: the colour's name, then how it was got or what unlocks it", (lang, paid, paidLastYear, gift, ranked, rankedWin, rounds, lock, plain) => {
    setLanguageChoice(lang);
    expect(line(lamb, user({ purchased_on: { [LAMB]: "2026-11-27" } }))).toBe(paid);
    expect(line(lamb, user({ purchased_on: { [LAMB]: "2025-11-27" } }))).toBe(paidLastYear);
    expect(line(lamb, user({ gifts: [LAMB] }))).toBe(gift);
    expect(line(won(25), user())).toBe(ranked);
    expect(line(won(1), user())).toBe(rankedWin);
    expect(line(won(1000, "rounds"), user({ rounds_played: 1200 }))).toBe(rounds);
    expect(line(locked, user())).toBe(lock);
    expect(line(free, user())).toBe(plain);
  });

  it("a look free from the start, one worn from before its count, and one shown to a guest name the look alone", () => {
    expect(statusParts(t, free, "tractor/red", user(), TODAY)).toEqual({ name: "Tractor · Enamel blue", how: "" });
    expect(statusParts(t, won(25), "tractor/orange", user({ ranked_wins: 3 }), TODAY).how).toBe("");
    expect(statusParts(t, locked, "tractor/red", null, TODAY).how).toBe("");
  });
});
