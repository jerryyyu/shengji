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

export const watch = {
  open(mode: "ranked" | "casual"): void { set({ mode }); },
  close(): void { set(null); },
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
 *  `watch` only with its feed on, and `rerun` when a finished ranked round
 *  can be replayed with nobody playing. */
export function canWatch(p: { watch?: number; rerun?: boolean } | null): boolean {
  return p !== null && typeof p.watch === "number" && (p.watch > 0 || p.rerun === true);
}
