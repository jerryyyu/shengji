import { OFFLINE } from "../offlineMode";

/** The live site, for the app's bundled page to load when back online. */
export const ONLINE_URL = "https://shengji.fly.dev/";

/** The query that brings a page into offline mode (ws.ts reads `offline`)
 *  with its offline table already open on the Play tab. */
export const OFFLINE_TABLE_QUERY = "?offline=1&table=1";

function arrivedForTable(): boolean {
  if (!OFFLINE || typeof location === "undefined") return false;
  return new URLSearchParams(location.search).get("table") === "1";
}

const listeners = new Set<() => void>();

/** The on-device game against bots, entered from the Play tab. Offline is a
 *  state of the Play tab: its Play opens your table with three bots, and the
 *  game it starts stays on this device until you leave it. `startFromPlay`
 *  is the one way in, from the Play tab or from the connection screen; a
 *  page that still talks to the game server reloads in offline mode for it.
 *  `goOnline` is the way back once the offline table is left. An object so
 *  a test can watch the calls instead of navigating. */
export const offlineGame = {
  /** Set once the page is on its way home, so a second caller adds no second navigation. */
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
  /** Opens the offline table with three bots: in place on an offline page,
   *  else by reloading in offline mode with the table open. */
  startFromPlay(): void {
    if (OFFLINE) {
      this.setTable(true);
      return;
    }
    window.location.assign(OFFLINE_TABLE_QUERY);
  },
  goOnline(): void {
    if (this.going) return;
    this.going = true;
    window.location.assign(window.location.protocol === "capacitor:" ? ONLINE_URL : "?offline=0");
  },
};
