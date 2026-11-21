// The joiner page's reconnect timing in ws.ts's Connection, copied here
// because ws.ts makes its live connection when it loads; a test in src pins
// each copy to ws.ts. The simulator's page runs on these with --page ws: a
// socket still connecting at CONNECT_S is cut and retried after the backoff,
// and losing one that had been open LONG_LIVED_S retries at once. The page
// model is a switch so the simulator can follow the app when its reconnect
// changes.
export type PageModel = "sim" | "ws";

/** ws.ts CONNECT_MS: an attempt still connecting this long is cut. */
export const CONNECT_S = 5;
/** ws.ts LONG_LIVED_MS: losing a socket open this long retries at once. */
export const LONG_LIVED_S = 10;
/** ws.ts's first retry delay (its backoff starts at 500 ms). */
export const BACKOFF_FIRST_S = 0.5;
/** ws.ts NEARBY_BACKOFF_MAX_MS: the retry delay doubles up to this at a nearby table. */
export const BACKOFF_MAX_S = 2;
