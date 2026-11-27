// Whether this page is watching a table, and in which mode it asked. The
// watch screen owns everything else; App only swaps it in for the Play tab.
import { useSyncExternalStore } from "react";
import type { WatchBy, WatchFrom } from "../telemetry";
import { watchUsage } from "./usage";

export interface Watching {
  mode: "ranked" | "casual";
}

let current: Watching | null = null;
const listeners = new Set<() => void>();

function set(next: Watching | null): void {
  current = next;
  for (const l of listeners) l();
}

/** The history entry a watch is: its state carries this mark (the mode and
 *  the session it was pushed for), at the Play tab's own address, so back
 *  (the browser's, or the iOS app's left-edge swipe) ends the watch and lands
 *  on the Play tab, and forward onto that entry opens it again. */
const MARK = "shengji.watch";
type Mark = { mode: Watching["mode"]; session: number };

function markOf(): Mark | null {
  try {
    const m = (window.history.state as Record<string, unknown> | null)?.[MARK] as Partial<Mark> | undefined;
    return m && (m.mode === "ranked" || m.mode === "casual") && typeof m.session === "number" ? m as Mark : null;
  } catch {
    return null;
  }
}

/** The session on screen (0 for none) and the last one handed out. */
let session = 0;
let sessions = 0;
/** The session whose close is walking its entry back, until that back lands:
 *  the popstate it brings is the close's own, never a Back of a later session. */
let closing: number | null = null;

function pushEntry(mode: Watching["mode"], id: number): void {
  try {
    const state = { ...(window.history.state as object | null), [MARK]: { mode, session: id } };
    if (markOf()) window.history.replaceState(state, "");
    else window.history.pushState(state, "");
  } catch {
    /* a sandboxed location */
  }
}

function onPop(): void {
  if (closing !== null) {
    // the close's own back has landed; a watch opened meanwhile gets its entry now
    closing = null;
    if (current !== null) pushEntry(current.mode, session);
    return;
  }
  const m = markOf();
  if (m && current === null) {
    // forward onto a watch's entry opens that watch again
    session = m.session;
    watchUsage.begin("history");
    set({ mode: m.mode });
  } else if (!m && current !== null) {
    session = 0;
    watchUsage.left("back");
    set(null);
  }
}

if (typeof window !== "undefined") window.addEventListener("popstate", onPop);

export const watch = {
  open(mode: "ranked" | "casual", from: WatchFrom = "presence"): void {
    session = ++sessions;
    watchUsage.begin(from);
    // while a close's back is on its way, the entry waits for it to land
    if (closing === null) pushEntry(mode, session);
    set({ mode });
  },
  /** End the watch now; its history entry is walked back, so a later back
   *  goes where it would have before the watch. `by` says why, for its telemetry. */
  close(by: WatchBy = "close"): void {
    if (current === null) return;
    const id = session;
    session = 0;
    watchUsage.left(by);
    set(null);
    if (closing !== null || markOf()?.session !== id) return;
    closing = id;
    try {
      window.history.back();
    } catch {
      closing = null;
    }
  },
  get(): Watching | null { return current; },
};

export function useWatching(): Watching | null {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => { listeners.delete(l); }; },
    () => current,
    () => null,
  );
}

/** Whether the presence line may lead to the watch screen: the server sends
 *  `watch` only to a socket that may watch (its feed on for everyone, or this
 *  account on its allowlist), and `rerun` when a finished ranked round can be
 *  replayed with nobody playing. The page checks no account itself. */
export function canWatch(p: { watch?: number; rerun?: boolean } | null): boolean {
  return p !== null && typeof p.watch === "number" && (p.watch > 0 || p.rerun === true);
}
