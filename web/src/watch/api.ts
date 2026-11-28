// The watch feed (PROTOCOL.md "Watching a table"): a finished round of a
// table the server picks, read over HTTP. A watcher never opens the table's
// socket; `watcher` is the token the server counts it by.
import type { RoundEvent } from "../replay/reducer";

export interface WatchDoc {
  table: string;
  watcher: string;
  mode: "ranked" | "casual";
  /** The table's round in play; null for a rerun. */
  live_round: number | null;
  /** A casual table seating joiners now: its code, for Take a seat. */
  code: string | null;
  rerun: boolean;
  waiting: boolean;
  /** How many watch this table now, this watcher among them; absent for a rerun. */
  watchers?: number;
  round?: number;
  seat?: number;
  players?: string[];
  finished?: boolean;
  events?: RoundEvent[];
}

export type WatchFetch =
  | { ok: true; doc: WatchDoc }
  | { ok: false; reason: "none" | "limited" | "error" };

/** The token this tab (or app session) watches by, made here before the
 *  first read and kept for the session, so every read of the session, a
 *  watch opened again included, is the same watcher to the server. */
const TOKEN_KEY = "shengji.watcher";
const tokenOk = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9]{16,64}$/.test(v);
let token: string | null = null;

function mint(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function watcherToken(): string {
  if (token) return token;
  try {
    const v = window.sessionStorage.getItem(TOKEN_KEY);
    if (tokenOk(v)) return (token = v);
  } catch {
    /* storage off: this page's own token */
  }
  token = mint();
  try {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage off: the token lasts as long as the page */
  }
  return token;
}

/** Forget the page's copy (tests: a fresh tab reads storage again). */
export function forgetWatcherToken(): void {
  token = null;
  epoch = 0;
}

/** The Watch session: a count, kept for the tab or app session, that goes
 *  up each time the watch screen opens. Every read and leave carries it, and
 *  the server lets a leave end only the session it names or an older one, so
 *  a late leave from a closed screen never ends a watch opened since. */
const EPOCH_KEY = "shengji.watch.epoch";
let epoch = 0;

export function nextWatchSession(): number {
  let stored = 0;
  try {
    stored = Number(window.sessionStorage.getItem(EPOCH_KEY)) || 0;
  } catch {
    /* storage off: this page's own count */
  }
  epoch = Math.max(epoch, stored) + 1;
  try {
    window.sessionStorage.setItem(EPOCH_KEY, String(epoch));
  } catch {
    /* storage off */
  }
  return epoch;
}

async function getDoc(path: string): Promise<WatchFetch> {
  let resp: Response;
  try {
    resp = await fetch(path, { credentials: "same-origin" });
  } catch {
    return { ok: false, reason: "error" };
  }
  if (resp.status === 404) return { ok: false, reason: "none" };
  if (resp.status === 429) return { ok: false, reason: "limited" };
  if (resp.status !== 200) return { ok: false, reason: "error" };
  try {
    return { ok: true, doc: (await resp.json()) as WatchDoc };
  } catch {
    return { ok: false, reason: "error" };
  }
}

/** A table to watch: `mode` first; never `skip` (Next table). */
export function fetchWatch(mode: string, skip: string | null, session: number): Promise<WatchFetch> {
  const q = new URLSearchParams({ mode, w: watcherToken(), e: String(session) });
  if (skip) q.set("skip", skip);
  return getDoc(`/api/watch?${q.toString()}`);
}

/** The table being watched: its round after `after` once that round is finished. */
export function followWatch(table: string, after: number, session: number): Promise<WatchFetch> {
  const q = new URLSearchParams({ after: String(after), w: watcherToken(), e: String(session) });
  return getDoc(`/api/watch/${encodeURIComponent(table)}?${q.toString()}`);
}

/** Watch session `session` left (its screen closed, or the page went
 *  away): this watcher stops counting wherever the server counts it, unless
 *  a newer session holds it. Sent as a beacon, so it survives the page
 *  closing; the server's lease is the fallback when even that is lost. */
export function leaveWatch(session: number): void {
  const q = new URLSearchParams({ w: watcherToken(), e: String(session) });
  const url = `/api/watch/leave?${q.toString()}`;
  try {
    if (typeof navigator.sendBeacon === "function" && navigator.sendBeacon(url)) return;
  } catch {
    /* no beacon here: the request below */
  }
  try {
    void fetch(url, { method: "POST", credentials: "same-origin", keepalive: true }).catch(() => {});
  } catch {
    /* the lease ends the count */
  }
}
