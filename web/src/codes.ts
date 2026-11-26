// Room and table codes are one space (PROTOCOL.md "Codes"): the same four
// characters, the same link. codeJoin.ts peeks a code and opens its Join
// panel.

import { t } from "./i18n";

export const CODE_LEN = 4;

/** Uppercase letters and digits only, at most four: what the server compares. */
export function normalizeCode(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, CODE_LEN);
}

/** The code in pasted text that is an invite link (`?code=`, or an older
 *  `?room=` or `?party=`), from any host, so a link pasted into the code box
 *  reads as its code; null for anything else, which pastes as typed. */
export function codeFromLink(text: string): string | null {
  const raw = text.trim();
  if (!/^(https?:\/\/|[\w.-]+\.[a-z]{2,}\/)/i.test(raw)) return null;
  let url: URL;
  try { url = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`); } catch { return null; }
  const param = url.searchParams.get("code") ?? url.searchParams.get("room") ?? url.searchParams.get("party");
  const code = normalizeCode(param ?? "");
  return code.length === CODE_LEN ? code : null;
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

/** The link token's query parameter, beside `code`. */
export const HOST_PARAM = "h";
export const HOST_KEY = "shengji.invite.host";
const HOST_TOKEN = /^[0-9a-f]{12}$/;

/** Whether `raw` is a link token as this device mints them. */
export function isHostToken(raw: unknown): raw is string {
  return typeof raw === "string" && HOST_TOKEN.test(raw);
}

/** This device's link token: twelve random hex, minted once and kept in the
 *  origin's storage. It names no account and no table, and telemetry keeps
 *  only the server's hash of it, so the opens and seats a sender's links
 *  lead to group by sender. Null where storage or randomness is missing:
 *  the link then goes without it. */
export function hostToken(): string | null {
  try {
    const kept = localStorage.getItem(HOST_KEY);
    if (isHostToken(kept)) return kept;
    const bytes = new Uint8Array(6);
    crypto.getRandomValues(bytes);
    const token = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem(HOST_KEY, token);
    return token;
  } catch {
    return null;
  }
}

/** The invite link for a room or a table: one parameter for either kind,
 *  and the sender's link token after it. */
export function codeLink(code: string): string {
  const token = hostToken();
  return `${window.location.origin}/?code=${code}${token ? `&${HOST_PARAM}=${token}` : ""}`;
}

/** A step of an invite's funnel: the link sent, a page loaded from it, that
 *  page's visitor seated by its Join. */
export type InviteStep = "created" | "opened" | "seated";
export type InviteVia = "share" | "copy";
type InviteReporter = (step: InviteStep, via: InviteVia | undefined, host: string | null) => void;
let inviteReporter: InviteReporter | null = null;

/** Where invite steps go (telemetry.ts sets it); none goes nowhere. */
export function setInviteReporter(fn: InviteReporter | null): void {
  inviteReporter = fn;
}

export function reportInvite(step: InviteStep, via: InviteVia | undefined, host: string | null): void {
  try {
    inviteReporter?.(step, via, host);
  } catch {
    /* telemetry never breaks an invite */
  }
}

/** How long an Invite button reads "Link copied" after a copy. */
export const COPIED_MS = 1200;

/** What an invite asks for: one, two or three more people, or the partner
 *  for the sender's own held seat. The server's link preview uses the same
 *  words (server/shengji/api/invite_preview.py). "three" is also the plain
 *  ask, for a table whose open seats the sender cannot know. */
export type InviteAsk = "one" | "two" | "three" | "partner";

/** The ask for your own table's seats, from what a join by the code you
 *  share takes. Every seat is sent the table's one code, its opener's,
 *  whose join takes a held partner seat before any open one: so with a seat
 *  held, its holder (the opener, seated opposite it) asks for a partner and
 *  anyone else sends the plain ask; without one, the open seats count. A
 *  bot and a person are not offered, so the message never promises more
 *  than Join finds. */
export function inviteAskOf(seats: readonly { at: number; look: string }[], you: number): InviteAsk {
  const held = seats.find((s) => s.look === "held");
  if (held) return held.at === (you + 2) % 4 ? "partner" : "three";
  const open = seats.filter((s) => s.look === "open").length;
  if (open === 1) return "one";
  if (open === 2) return "two";
  return "three";
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
  const host = hostToken();
  if (typeof navigator.share === "function") {
    return navigator.share({ title: t("home.shareTitle"), text: inviteText(code, ask), url })
      .then(() => { reportInvite("created", "share", host); return false; },
            () => false);   // a dismissed share sheet is not an error, and sent nothing
  }
  if (!navigator.clipboard) return Promise.resolve(false);
  return navigator.clipboard.writeText(url).then(() => {
    reportInvite("created", "copy", host);
    return true;
  }, () => false);
}
