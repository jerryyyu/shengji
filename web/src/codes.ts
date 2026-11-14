// Room and table codes are one space (PROTOCOL.md "Codes"): the same four
// characters, the same link. codeJoin.ts looks a code up and runs the room
// or the table flow.

export const NO_CODE = "No table has that code.";
export const CODE_LEN = 4;

/** Uppercase letters and digits only, at most four: what the server compares. */
export function normalizeCode(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, CODE_LEN);
}

/** A `?party=CODE` link from before a Duo was a table reads as
 *  `?code=CODE`, so it opens that code as any invite does. */
export function aliasPartyLink(): void {
  const params = new URLSearchParams(window.location.search);
  const party = params.get("party");
  if (party === null) return;
  params.delete("party");
  if (!params.has("code")) params.set("code", party);
  window.history.replaceState(window.history.state, "",
    `${window.location.pathname}?${params.toString()}${window.location.hash}`);
}

/** The invite link for a room or a table: one parameter for either kind. */
export function codeLink(code: string): string {
  return `${window.location.origin}/?code=${code}`;
}
