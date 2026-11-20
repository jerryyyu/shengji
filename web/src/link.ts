// What the socket manager (ws.ts) knows about the link beyond its status:
// whether an action is going unanswered, and when a socket was lost or a new
// one opened. A module of its own, with no imports, so the connection pill
// and telemetry read it where a test stands in for ws.ts.

/** Why the page lost an open socket. */
export type DropCause = "closed" | "no_pong" | "replaced";

export type LinkEvent =
  | { kind: "down"; cause: DropCause }
  | { kind: "up"; ms: number };

let stalled = false;
const stallListeners = new Set<(stalled: boolean) => void>();
const eventListeners = new Set<(ev: LinkEvent) => void>();

/** An action has gone unanswered past its wait while the socket still
 *  reads open: the pill shows now, before the socket is replaced. */
export function isStalled(): boolean {
  return stalled;
}

export function setStalled(on: boolean): void {
  if (on === stalled) return;
  stalled = on;
  for (const fn of stallListeners) fn(on);
}

export function subscribeStalled(fn: (stalled: boolean) => void): () => void {
  stallListeners.add(fn);
  return () => { stallListeners.delete(fn); };
}

export function noteLink(ev: LinkEvent): void {
  for (const fn of eventListeners) {
    try { fn(ev); } catch { /* a listener never breaks the socket */ }
  }
}

export function subscribeLink(fn: (ev: LinkEvent) => void): () => void {
  eventListeners.add(fn);
  return () => { eventListeners.delete(fn); };
}
