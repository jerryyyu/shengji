// Room and table codes are one space (PROTOCOL.md "Codes"): the same four
// characters, the same link. codeJoin.ts peeks a code and opens its Join
// panel.

export const CODE_LEN = 4;

/** Uppercase letters and digits only, at most four: what the server compares. */
export function normalizeCode(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, CODE_LEN);
}

/** One link kind: an older `?room=CODE` or `?party=CODE` link reads as
 *  `?code=CODE`, and a `?name=` beside it is dropped (a guest joins under the
 *  name their chip shows). Old links, and the app's universal links, still open. */
export function aliasInviteLink(): void {
  const params = new URLSearchParams(window.location.search);
  const alias = params.get("room") ?? params.get("party");
  if (alias === null && !params.has("name")) return;
  params.delete("room");
  params.delete("party");
  params.delete("name");
  if (alias !== null && !params.has("code")) params.set("code", alias);
  const rest = params.toString();
  window.history.replaceState(window.history.state, "",
    `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
}

/** The invite link for a room or a table: one parameter for either kind. */
export function codeLink(code: string): string {
  return `${window.location.origin}/?code=${code}`;
}
