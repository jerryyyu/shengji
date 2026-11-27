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
export function fetchWatch(mode: string, skip: string | null, watcher: string | null): Promise<WatchFetch> {
  const q = new URLSearchParams({ mode });
  if (skip) q.set("skip", skip);
  if (watcher) q.set("w", watcher);
  return getDoc(`/api/watch?${q.toString()}`);
}

/** The table being watched: its round after `after` once that round is finished. */
export function followWatch(table: string, after: number, watcher: string): Promise<WatchFetch> {
  const q = new URLSearchParams({ after: String(after), w: watcher });
  return getDoc(`/api/watch/${encodeURIComponent(table)}?${q.toString()}`);
}
