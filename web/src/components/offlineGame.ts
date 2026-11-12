/** The on-device game against bots, for a lobby with no connection: the page
 *  reloads in offline mode, which ws.ts reads from `?offline=1`. An object so
 *  a test can watch the call instead of navigating. */
export const offlineGame = {
  start(): void { window.location.assign("?offline=1"); },
};
