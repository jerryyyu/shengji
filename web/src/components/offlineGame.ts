import { useSyncExternalStore } from "react";
import { OFFLINE, setOffline } from "../offlineMode";
import { conn } from "../ws";
import { queue } from "../queue/store";
import { clearToast } from "../toast";

/** The live site, for the app's bundled page to load when back online. */
export const ONLINE_URL = "https://shengji.fly.dev/";

/** True for the app's bundled page, which has no game server of its own: it
 *  goes online only by loading the live site. */
function bundledPage(): boolean {
  return typeof location !== "undefined" && location.protocol === "capacitor:";
}

function arrivedForTable(): boolean {
  if (!OFFLINE || typeof location === "undefined") return false;
  return new URLSearchParams(location.search).get("table") === "1";
}

/** What one server's socket left behind goes with it: the queue's entry,
 *  pair and presence, and a toast about them. */
function resetServerState(): void {
  queue.reset();
  clearToast();
}

const listeners = new Set<() => void>();
let prefetched = false;

/** The on-device game against bots, entered from the Play tab. Offline is a
 *  state of the Play tab: its Play opens your table with three bots, and the
 *  game it starts stays on this device until you leave it. `startFromPlay`
 *  is the one way in, from the Play tab, its Play offline link and the
 *  connection screen; it swaps the socket to the on-device server in place.
 *  `goOnline` is the way back once the offline table is left. An object so
 *  a test can watch the calls. */
export const offlineGame = {
  /** Set once the app's bundled page is on its way to the live site. */
  going: false,
  /** The offline table is up on the Play tab, from Play until its Leave or the end of its game. */
  tableOpen: arrivedForTable(),
  /** A game started at this page's offline table, until the player is back on the Play tab. */
  played: false,

  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  },
  setTable(open: boolean): void {
    if (this.tableOpen === open) return;
    this.tableOpen = open;
    listeners.forEach((l) => l());
  },
  /** Opens the offline table with three bots, in place: a page still on the
   *  game server swaps its socket to the on-device one first. */
  startFromPlay(): void {
    if (!OFFLINE) {
      setOffline(true);
      resetServerState();
      void conn.useLocalServer().catch(() => {
        // the on-device server could not load: the Play tab stays as it was
        this.setTable(false);
        setOffline(false);
      });
    }
    this.setTable(true);
  },
  /** Back to the online Play tab, once the offline table is left. In place
   *  for a page with a game server; the app's bundled page loads the live site. */
  goOnline(): void {
    this.played = false;
    this.setTable(false);
    if (bundledPage()) {
      if (this.going) return;
      this.going = true;
      window.location.assign(ONLINE_URL);
      return;
    }
    if (!OFFLINE) return;
    setOffline(false);
    resetServerState();
    conn.useGameServer();
  },
  /** Loads the on-device server ahead of need, once the page is idle, so
   *  Play offline works after the network has gone. */
  prefetch(): void {
    if (prefetched || OFFLINE) return;
    prefetched = true;
    const load = () => { void import("../offline/server").catch(() => { prefetched = false; }); };
    const idle = (globalThis as { requestIdleCallback?: (cb: () => void) => void }).requestIdleCallback;
    if (idle) idle(load);
    else window.setTimeout(load, 2000);
  },
};

/** Whether the offline table is up on this page's Play tab. */
export function useOfflineTable(local: boolean): boolean {
  const table = useSyncExternalStore((l) => offlineGame.subscribe(l),
                                     () => offlineGame.tableOpen, () => offlineGame.tableOpen);
  return local && table;
}
