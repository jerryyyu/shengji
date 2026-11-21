// A nearby joiner's display name, held to the online rules
// (server/shengji/api/accounts.py validate_display_name) on the host, since
// nothing else checks a name that arrives over the local link, with one
// addition: invisible format characters are taken out first.

import { containsBlocked } from "./chatFilter";

export const DISPLAY_NAME_MAX = 20;
const RAW_MAX = 1000;
const RESERVED = new Set(["bot", "system", "admin", "dealer", "moderator", "server"]);
const BOT_NAME_RE = /^bot\s*\d*$/u;
// control (every line break), surrogate, private use, line and paragraph separators
const FORBIDDEN_RE = /[\p{Cc}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/u;
// format characters (zero-width spaces and joiners, direction overrides, the
// byte-order mark): invisible, so they could hide a refused word or a bot's
// name, or make a name of nothing; they are taken out before any check
const FORMAT_RE = /\p{Cf}/gu;

/** The name to seat, or null when the online rules refuse it. `blocked` is
 *  the word filter: the server's chat filter, bundled with the page, which
 *  refuses a name as the server refuses an account's display name. */
export function validNearbyName(raw: unknown, blocked: ((name: string) => boolean) | null = containsBlocked): string | null {
  if (typeof raw !== "string" || raw.length > RAW_MAX) return null;
  if (FORBIDDEN_RE.test(raw)) return null;
  const name = raw.normalize("NFKC").replace(FORMAT_RE, "").split(/\s+/u).filter(Boolean).join(" ");
  if (!name || [...name].length > DISPLAY_NAME_MAX) return null;
  const folded = name.toLowerCase();
  if (RESERVED.has(folded) || BOT_NAME_RE.test(folded)) return null;
  if (blocked?.(name)) return null;
  return name;
}

/** A refused or missing name becomes the seat's plain name. */
export function nearbyName(raw: unknown, seat: number): string {
  return validNearbyName(raw) ?? `Player ${seat + 1}`;
}
