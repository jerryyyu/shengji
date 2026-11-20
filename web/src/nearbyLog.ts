// The nearby device-test log: the last LOG_KEEP lines of what the link did
// (the plugin's own lines, the frames each end sent and received, and every
// frame the host refused), with times in milliseconds, for the debug pane a
// Debug build made for the device test shows. It is kept in memory only and
// never leaves the phone; a refused frame is always written here, so a frame
// dropped at the boundary is never silent while the pane is up.

export const LOG_KEEP = 500;

export interface LogLine {
  /** Milliseconds since the page loaded. */
  t: number;
  /** Which part wrote it: native, host, join, socket. */
  from: string;
  text: string;
}

const lines: LogLine[] = [];
const listeners = new Set<() => void>();
let snapshot: readonly LogLine[] = [];

const now = (): number => (typeof performance !== "undefined" ? performance.now() : Date.now());

export function nearbyLog(from: string, text: string): void {
  lines.push({ t: Math.round(now()), from, text });
  if (lines.length > LOG_KEEP) lines.splice(0, lines.length - LOG_KEEP);
  snapshot = lines.slice();
  listeners.forEach((l) => l());
}

/** A frame's type, for a log line: never its cards or names. */
export function frameType(text: string): string {
  const m = /^\{"type":"([a-z_]{1,40})"/.exec(text);
  return m ? m[1] : "?";
}

export function nearbyLogLines(): readonly LogLine[] {
  return snapshot;
}

export function subscribeNearbyLog(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

export function nearbyLogText(): string {
  return snapshot.map((l) => `${(l.t / 1000).toFixed(3)} ${l.from} ${l.text}`).join("\n");
}

interface LogSource {
  addListener(event: "debugLog", fn: (ev: { text: string }) => void): Promise<unknown>;
}

let nativeListening = false;
/** The plugin's own lines (it sends them only in a Debug build made for the
 *  device test) join the log, once per page. */
export function listenNativeLog(p: LogSource): void {
  if (nativeListening) return;
  nativeListening = true;
  void p.addListener("debugLog", (ev) => nearbyLog("native", ev.text)).catch(() => { nativeListening = false; });
}

/** Tests: start with an empty log. */
export function clearNearbyLog(): void {
  lines.length = 0;
  snapshot = [];
  listeners.forEach((l) => l());
}
