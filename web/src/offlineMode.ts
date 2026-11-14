import { useSyncExternalStore } from "react";

/**
 * Offline mode: the page plays against the in-page server (src/offline/server)
 * with SmartBot seats instead of the game server. It is a state of the page,
 * not a page of its own: Play offline turns it on in place, and leaving the
 * offline table turns it off again, with no reload either way. The app's
 * bundled page (served from its own capacitor:// origin, which the shell
 * shows when the live site cannot load) starts in it, as does a page opened
 * with `?offline=1`.
 */
function detectOffline(): boolean {
  if (typeof location === "undefined") return false;
  if (location.protocol === "capacitor:") return true;
  return new URLSearchParams(location.search).get("offline") === "1";
}

/** Whether the page plays on this device now. A live binding: modules that
 *  import it read the current value each time. */
export let OFFLINE = detectOffline();

const listeners = new Set<() => void>();

/** Turn offline mode on or off. Only offlineGame calls this, together with
 *  the socket's transport swap. */
export function setOffline(on: boolean): void {
  if (OFFLINE === on) return;
  OFFLINE = on;
  for (const l of [...listeners]) l();
}

export function subscribeOffline(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** Offline mode, re-rendering when it changes. */
export function useOffline(): boolean {
  return useSyncExternalStore(subscribeOffline, () => OFFLINE, () => OFFLINE);
}
