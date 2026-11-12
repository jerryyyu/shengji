/** The live site, for the app's bundled page to load when back online. */
export const ONLINE_URL = "https://shengji.fly.dev/";

/** The on-device game against bots, for a lobby with no connection: the page
 *  reloads in offline mode, which ws.ts reads from `?offline=1`, and offline
 *  mode starts a game at once. `goOnline` is the way back: the app's bundled
 *  page loads the live site, a browser tab drops the offline flag. An object
 *  so a test can watch the calls instead of navigating. */
export const offlineGame = {
  start(): void { window.location.assign("?offline=1"); },
  goOnline(): void {
    window.location.assign(window.location.protocol === "capacitor:" ? ONLINE_URL : "?offline=0");
  },
};
