// The joiner page's reconnect timing in ws.ts's Connection, copied here
// because ws.ts makes its live connection when it loads; a test in src pins
// each copy to ws.ts. The simulator's page runs on these with --page ws: a
// nearby attempt has no connect timer (the socket's own link and resume
// timers decide when it gives up), each retry waits NEARBY_RETRY_S[tries
// since the last open], the last value repeating, and losing a socket that
// had been open LONG_LIVED_S retries at once. The page model is a switch so
// the simulator can follow the app when its reconnect changes.
export type PageModel = "sim" | "ws";

/** ws.ts LONG_LIVED_MS: losing a socket open this long retries at once. */
export const LONG_LIVED_S = 10;
/** ws.ts NEARBY_RETRY_MS: a nearby retry's wait by tries since the last open. */
export const NEARBY_RETRY_S: readonly number[] = [0, 0.25, 0.5, 1];
/** nearbyJoin.ts HOST_WINDOW_MS: a seated page with no link this long of
 *  its own awake time shows the host left. */
export const HOST_WINDOW_S = 65;
