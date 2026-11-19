// A nearby joiner's display name, held to the online rules
// (server/shengji/api/accounts.py validate_display_name) on the host, since
// nothing else checks a name that arrives over the local link.

export const DISPLAY_NAME_MAX = 20;
const RAW_MAX = 1000;
const RESERVED = new Set(["bot", "system", "admin", "dealer", "moderator", "server"]);
const BOT_NAME_RE = /^bot\s*\d*$/u;
// control (every line break), surrogate, private use, line and paragraph separators
const FORBIDDEN_RE = /[\p{Cc}\p{Cs}\p{Co}\p{Zl}\p{Zp}]/u;

/** The name to seat, or null when the online rules refuse it. `blocked` is
 *  the word filter; none is bundled with the page yet. */
export function validNearbyName(raw: unknown, blocked: ((name: string) => boolean) | null = null): string | null {
  if (typeof raw !== "string" || raw.length > RAW_MAX) return null;
  if (FORBIDDEN_RE.test(raw)) return null;
  const name = raw.normalize("NFKC").split(/\s+/u).filter(Boolean).join(" ");
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
