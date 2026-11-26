// Friendly random lobby names, an adjective and a card or game word
// ("Lucky Spades", "Quiet Tractor"), for a guest who has not picked a name;
// in a Chinese interface a mood and a game word ("淡定的庄家").
// Every combination fits the display-name rules (see randomName.test.ts).
import { locale } from "./i18n/locale";

export const NAME_ADJECTIVES = [
  "Lucky", "Bold", "Sly", "Quiet", "Steady", "Clever", "Brave", "Swift", "Calm", "Merry",
  "Witty", "Jolly", "Daring", "Nimble", "Plucky", "Sunny", "Gentle", "Keen", "Patient", "Cheerful",
  "Crafty", "Mighty", "Noble", "Curious", "Dapper", "Breezy", "Humble", "Shrewd", "Spry", "Wise",
] as const;

export const NAME_NOUNS = [
  "Spades", "Hearts", "Diamonds", "Clubs", "Joker", "Tractor", "Ace", "King", "Queen", "Jack",
  "Deuce", "Kitty", "Banker", "Trick", "Pair", "Deck", "Shuffle", "Level", "Throw", "Ten",
] as const;

/** A Chinese interface's names: a mood and a game word joined by 的
 *  ("淡定的庄家"), at most six characters. Traditional uses Taiwan's words
 *  (紅心 for hearts). The server's device-account draw has the same lists
 *  (server/shengji/api/device_names.py). */
export const ZH_NAMES: Readonly<Record<string, { moods: readonly string[]; words: readonly string[] }>> = {
  "zh-Hans": {
    moods: ["淡定", "机智", "稳健", "快乐", "勇敢", "沉着", "幸运", "聪明", "开心", "冷静",
            "豪爽", "灵巧", "从容", "果断", "爽快", "机灵", "大胆", "温和", "认真", "潇洒"],
    words: ["庄家", "闲家", "大王", "小王", "拖拉机", "红桃", "黑桃", "方块", "梅花", "对子",
            "主牌", "底牌", "王牌", "牌友", "搭档", "高手", "老K", "牌神", "上家", "下家"],
  },
  "zh-Hant": {
    moods: ["淡定", "機智", "穩健", "快樂", "勇敢", "沉著", "幸運", "聰明", "開心", "冷靜",
            "豪爽", "靈巧", "從容", "果斷", "爽快", "機靈", "大膽", "溫和", "認真", "瀟灑"],
    words: ["莊家", "閒家", "大王", "小王", "拖拉機", "紅心", "黑桃", "方塊", "梅花", "對子",
            "主牌", "底牌", "王牌", "牌友", "搭檔", "高手", "老K", "牌神", "上家", "下家"],
  },
};

/** The two lists and the join for `loc`: Chinese where the interface is,
 *  else English. */
function namePool(loc: string): { firsts: readonly string[]; seconds: readonly string[]; join: string } {
  const zh = ZH_NAMES[loc];
  return zh ? { firsts: zh.moods, seconds: zh.words, join: "的" }
    : { firsts: NAME_ADJECTIVES, seconds: NAME_NOUNS, join: " " };
}

/** Every name the random fill could give in any language. */
export function isRandomName(name: string): boolean {
  return [" ", "的"].some((join) => {
    const parts = name.split(join);
    if (parts.length !== 2) return false;
    const [a, b] = parts;
    const pools = join === " " ? [namePool("en")] : Object.keys(ZH_NAMES).map(namePool);
    return pools.some((p) => p.firsts.includes(a) && p.seconds.includes(b));
  });
}

/** A random name in the interface's language (`loc`, the current locale by
 *  default): "Adjective Noun", or a Chinese one for a Chinese interface.
 *  `avoid` (the name shown now) is never returned, so a reroll always
 *  changes the name. A name already given keeps its language: only a new
 *  draw reads the locale. */
export function randomName(avoid = "", rng: () => number = Math.random, loc: string = locale()): string {
  const { firsts, seconds, join } = namePool(loc);
  const pick = <T,>(list: readonly T[]) => list[Math.min(list.length - 1, Math.floor(rng() * list.length))];
  for (let tries = 0; tries < 8; tries++) {
    const name = `${pick(firsts)}${join}${pick(seconds)}`;
    if (name !== avoid.trim()) return name;
  }
  // A stuck random source: fall back to a fixed name other than `avoid`.
  const first = `${firsts[0]}${join}${seconds[0]}`;
  return first === avoid.trim() ? `${firsts[0]}${join}${seconds[1]}` : first;
}
