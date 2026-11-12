/** The live site, for the app's bundled page to load when back online. */
export const ONLINE_URL = "https://shengji.fly.dev/";

/** The on-device game against bots, for a lobby with no connection: the page
 *  reloads in offline mode, which ws.ts reads from `?offline=1`, and offline
 *  mode starts a game at once. `goOnline` is the way back to the home Play
 *  tab: the app's bundled page loads the live site, a browser tab drops the
 *  offline flag. With no connection the Play tab says so, and its Play bots
 *  comes back here. An object so a test can watch the calls instead of
 *  navigating. */
export const offlineGame = {
  /** Set once the page is on its way home, so a second caller adds no second navigation. */
  going: false,
  start(): void { window.location.assign("?offline=1"); },
  goOnline(): void {
    if (this.going) return;
    this.going = true;
    window.location.assign(window.location.protocol === "capacitor:" ? ONLINE_URL : "?offline=0");
  },
};
