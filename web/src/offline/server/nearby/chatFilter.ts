// The server's chat filter (server/shengji/api/chat_filter.py) for a nearby
// host, which has no server to ask. The word list is a generated copy of
// chat_filter_words.txt; chatFilter.test.ts checks this matcher against the
// answers the Python filter gives on a fixed case list.

import { CHAT_FILTER_WORDS } from "./chatFilterWords.gen";

// One character for one, so a match's span in the folded text is its span in
// the original. 4 and 5 stay digits ("45s" is a time, not a word).
const LEET: Record<string, string> = { "0": "o", "1": "i", "3": "e", "@": "a", $: "s" };
const TOKEN_RE = /[A-Za-z0-9@$]+/gu;
const ENDINGS = ["s", "es", "er", "ers", "ing", "in", "ings", "ed", "y", "ty", "face", "faces",
  "head", "heads", "hole", "holes", "wit", "wits", "tard", "tards", "bag", "bags"];
const CJK = "㐀-䶿一-鿿豈-﫿";
const IS_LATIN = /^[a-z]+\*?$/u;

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\/]/gu, "\\$&");
}

function escapeClass(s: string): string {
  return s.replace(/[\]\\^-]/gu, "\\$&");
}

/** A word as a pattern in which every letter may repeat: "ass" is a+s{2,}. */
function letters(word: string): string {
  return word.replace(/(.)\1*/gu, (run, ch: string) => `${escapeRe(ch)}{${run.length},}`);
}

interface Patterns { latin: RegExp | null; cjk: RegExp | null }

export function parseChatFilter(lines: string[]): Patterns {
  const latin: string[] = [];
  const cjk: [number, string][] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const entry = line.toLowerCase();
    if (IS_LATIN.test(entry)) {
      let pat = letters(entry.replace(/\*+$/u, ""));
      if (entry.endsWith("*")) pat += `(?:${ENDINGS.join("|")})?`;
      latin.push(pat);
    } else if (entry.startsWith("=")) {
      const phrase = entry.slice(1);
      cjk.push([[...phrase].length, `(?<![${CJK}])${escapeRe(phrase)}(?![${CJK}])`]);
    } else if (entry.includes("!")) {
      const at = entry.indexOf("!");
      const phrase = entry.slice(0, at);
      cjk.push([[...phrase].length, `${escapeRe(phrase)}(?![${escapeClass(entry.slice(at + 1))}])`]);
    } else {
      cjk.push([[...entry].length, escapeRe(entry)]);
    }
  }
  // longest phrases first, so 操你 masks both characters rather than 操 alone
  // (a stable sort, as Python's is)
  cjk.sort((a, b) => b[0] - a[0]);
  return {
    latin: latin.length ? new RegExp(`^(?:${latin.join("|")})$`, "u") : null,
    cjk: cjk.length ? new RegExp(cjk.map((e) => e[1]).join("|"), "gu") : null,
  };
}

let cached: Patterns | null = null;
function patterns(): Patterns {
  cached ??= parseChatFilter(CHAT_FILTER_WORDS.split(/\r?\n/u));
  return cached;
}

function spans(text: string): [number, number][] {
  const { latin, cjk } = patterns();
  const out: [number, number][] = [];
  if (latin) {
    for (const m of text.matchAll(TOKEN_RE)) {
      const folded = [...m[0].toLowerCase()].map((c) => LEET[c] ?? c).join("");
      if (latin.test(folded)) out.push([m.index, m.index + m[0].length]);
    }
  }
  if (cjk) {
    // lower case for the Latin letters a phrase may hold (傻B), one character
    // for one so a span stays the original's
    const folded = [...text].map((c) => {
      const l = c.toLowerCase();
      return l.length === c.length && [...l].length === 1 ? l : c;
    }).join("");
    cjk.lastIndex = 0;
    for (const m of folded.matchAll(cjk)) out.push([m.index, m.index + m[0].length]);
  }
  return out;
}

/** The text with every listed word or phrase replaced by asterisks, one per
 *  character (a UTF-16 unit outside the BMP becomes two). */
export function maskChat(text: string): string {
  const found = spans(text);
  if (!found.length) return text;
  const chars = text.split("");
  for (const [start, end] of found) {
    for (let i = start; i < end; i++) if (!/\s/u.test(chars[i])) chars[i] = "*";
  }
  return chars.join("");
}

/** Whether maskChat would change the text: the name check. */
export function containsBlocked(text: string): boolean {
  return spans(text).length > 0;
}
