import type { MessageKey } from "./i18n";

/** The chat sheet's quick phrases, in the sheet's order. A tap sends the id
 *  with the sender's wording as `text`; every client words a line that
 *  carries a known id in its own language, and a client that does not know
 *  the id shows `text`. The servers accept only these ids
 *  (matchmaking.QUICK_PHRASES, offline/server/server.ts); a test keeps the
 *  three lists equal. */
export const QUICK_PHRASE_IDS = ["hi", "gg", "nice", "more", "brb", "thanks", "sorry", "luck"] as const;

export type QuickPhraseId = (typeof QUICK_PHRASE_IDS)[number];

export const QUICK_PHRASE_KEY: Record<QuickPhraseId, MessageKey> = {
  hi: "table.quickHi",
  gg: "table.quickGg",
  nice: "table.quickNice",
  more: "table.quickMore",
  brb: "table.quickBrb",
  thanks: "table.quickThanks",
  sorry: "table.quickSorry",
  luck: "table.quickLuck",
};

/** Each phrase in Traditional Chinese, for the zh-Hant column of its
 *  message once that locale exists. */
export const QUICK_PHRASE_HANT: Record<QuickPhraseId, string> = {
  hi: "大家好！",
  gg: "GG",
  nice: "好牌！",
  more: "再來一局？",
  brb: "馬上回來",
  thanks: "謝謝！",
  sorry: "抱歉！",
  luck: "加油！",
};

const KNOWN: ReadonlySet<string> = new Set(QUICK_PHRASE_IDS);

export function isQuickPhrase(value: unknown): value is QuickPhraseId {
  return typeof value === "string" && KNOWN.has(value);
}
