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

const KNOWN: ReadonlySet<string> = new Set(QUICK_PHRASE_IDS);

export function isQuickPhrase(value: unknown): value is QuickPhraseId {
  return typeof value === "string" && KNOWN.has(value);
}
