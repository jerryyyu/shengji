// Whether this page is watching a table, and in which mode it asked. The
// watch screen owns everything else; App only swaps it in for the Play tab.
import { useSyncExternalStore } from "react";

export interface Watching {
  mode: "ranked" | "casual";
}

let current: Watching | null = null;
const listeners = new Set<() => void>();

function set(next: Watching | null): void {
  current = next;
  for (const l of listeners) l();
}

/** The history entry a watch is: its state carries this mark, at the Play
 *  tab's own address, so back (the browser's, or the iOS app's left-edge
 *  swipe) ends the watch and lands on the Play tab. */
const MARK = "shengji.watch";

function marked(): boolean {
  try {
    return (window.history.state as Record<string, unknown> | null)?.[MARK] === true;
  } catch {
    return false;
  }
}

let listening = false;
function listen(): void {
  if (listening) return;
  listening = true;
  window.addEventListener("popstate", () => { if (current !== null && !marked()) set(null); });
}

export const watch = {
  open(mode: "ranked" | "casual"): void {
    listen();
    try {
      const state = { ...(window.history.state as object | null), [MARK]: true };
      if (marked()) window.history.replaceState(state, "");
      else window.history.pushState(state, "");
    } catch {
      /* a sandboxed location */
    }
    set({ mode });
  },
  /** End the watch now; its history entry is walked back, so a later back
   *  goes where it would have before the watch. */
  close(): void {
    if (current === null) return;
    set(null);
    try {
      if (marked()) window.history.back();
    } catch {
      /* a sandboxed location */
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
