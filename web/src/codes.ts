// Room and table codes are one space (PROTOCOL.md "Codes"): the same four
// characters, the same link. codeJoin.ts peeks a code and opens its Join
// panel.

import { t } from "./i18n";

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

/** How long an Invite button reads "Link copied" after a copy. */
export const COPIED_MS = 1200;

/** What an invite asks for: one, two or three more people, or the partner
 *  for a Duo opener's held seat. The server's link preview uses the same
 *  words (server/shengji/api/invite_preview.py). */
export type InviteAsk = "one" | "two" | "three" | "partner";

/** The ask for a table with `people` seated (bots are not people) and
 *  whether a seat is held for a partner. A full table asks as one alone. */
export function inviteAsk(people: number, held = false): InviteAsk {
  if (held) return "partner";
  if (people === 3) return "one";
  if (people === 2) return "two";
  return "three";
}

/** The ask for a table's seats, by each seat's look in the panel. */
export function inviteAskOf(looks: readonly string[]): InviteAsk {
  const people = looks.filter((l) => l === "you" || l === "friend" || l === "person").length;
  return inviteAsk(people, looks.includes("held"));
}

/** The invite's message in the app's language, the code in it so someone
 *  without the link can type it. */
export function inviteText(code: string, ask: InviteAsk): string {
  return t(`home.invite.${ask}`, { code });
}

/** A table's invite: the system share sheet where there is one, its text the
 *  message and the link after it, else the link on the clipboard. Resolves
 *  true when the link was copied. */
export function shareInvite(code: string, ask: InviteAsk): Promise<boolean> {
  const url = codeLink(code);
  if (typeof navigator.share === "function") {
    return navigator.share({ title: t("home.shareTitle"), text: inviteText(code, ask), url })
      .then(() => false, () => false);   // a dismissed share sheet is not an error
  }
  if (!navigator.clipboard) return Promise.resolve(false);
  return navigator.clipboard.writeText(url).then(() => true, () => false);
}
