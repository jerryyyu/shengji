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
  const line = { t: Math.round(now()), from, text };
  lines.push(line);
  if (file) toFile(line);
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

const lineText = (l: LogLine): string => `${(l.t / 1000).toFixed(3)} ${l.from} ${l.text}`;

export function nearbyLogText(): string {
  return snapshot.map(lineText).join("\n");
}

// The app's Capacitor bridge (native-bridge.js) returns the listener itself,
// not a promise of it, so the result is wrapped before it is chained.
interface LogSource {
  addListener(event: "debugLog", fn: (ev: { text: string }) => void): unknown;
}

let nativeListening = false;
/** The plugin's own lines (it sends them only in a Debug build made for the
 *  device test) join the log, once per page. */
export function listenNativeLog(p: LogSource): void {
  if (nativeListening) return;
  nativeListening = true;
  try {
    void Promise.resolve(p.addListener("debugLog", (ev) => nearbyLog("native", ev.text))).catch(() => { nativeListening = false; });
  } catch {
    nativeListening = false;
  }
}

/** Tests: listen to the plugin's lines again on the next attach. */
export function forgetNativeLogForTests(): void {
  nativeListening = false;
}

/** Tests: start with an empty log. */
export function clearNearbyLog(): void {
  lines.length = 0;
  snapshot = [];
  listeners.forEach((l) => l());
}

// The device-test log file. The plugin appends, rolls and clears; the page
// batches lines and decides when to roll, so a busy link costs one native
// call every FLUSH_MS, not one per line.

export const LOG_FILE_CAP = 20 * 1024 * 1024;
const FLUSH_MS = 2000;
const FLUSH_LINES = 200;
const MAX_FAILURES = 5;

export interface LogFile {
  debugLogFile(o: {
    op: "append" | "roll" | "clear" | "size" | "read"; text?: string; file?: "current" | "old"; offset?: number; max?: number;
  }): Promise<{ size?: number; text?: string; bytes?: number; exists?: boolean }>;
}

export type LogFileReset = "roll" | "clear";
const resetListeners = new Set<(why: LogFileReset) => void>();

/** Hears each roll and clear of the file, in order with its writes. */
export function onNearbyLogFileReset(fn: (why: LogFileReset) => void): () => void {
  resetListeners.add(fn);
  return () => { resetListeners.delete(fn); };
}

/** Whole lines of the current file (or the older one) from `offset`, at
 *  most `max` bytes, in order with the writes; null without a file. */
export function readNearbyLogFile(which: "current" | "old", offset: number, max: number): Promise<{ text: string; bytes: number; size: number } | null> {
  const f = file;
  if (!f) return Promise.resolve(null);
  return serial(async () => {
    const r = await f.debugLogFile({ op: "read", file: which, offset, max });
    return { text: r?.text ?? "", bytes: r?.bytes ?? 0, size: r?.size ?? 0 };
  });
}

let file: LogFile | null = null;
let cap = LOG_FILE_CAP;
let pending: string[] = [];
let fileSize = 0;
let failures = 0;
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let writing: Promise<unknown> = Promise.resolve();

// A line that looks like an email, a bearer token or a long secret-like run
// never reaches the file (the log is built to hold none; this is the backstop).
const RISKY = /[^\s@]+@[^\s@]+\.[a-z]{2,}|\bbearer\s|\btoken[=:]\s*\S|\beyJ[\w-]{10,}|[A-Za-z0-9_+/=-]{32,}/i;

const utf8 = (s: string): number => new TextEncoder().encode(s).length;

function toFile(l: LogLine): void {
  pending.push(RISKY.test(l.text) ? `${(l.t / 1000).toFixed(3)} ${l.from} [line withheld from the file]` : lineText(l));
  if (pending.length >= FLUSH_LINES) void flushNearbyLogFile();
  else flushTimer ??= setTimeout(() => { flushTimer = null; void flushNearbyLogFile(); }, FLUSH_MS);
}

function serial<T>(work: () => Promise<T>): Promise<T> {
  const run = writing.then(work);
  writing = run.catch(() => {});
  return run;
}

/** Writes the batched lines now (the timer, a full batch, the page hiding). */
export function flushNearbyLogFile(): Promise<void> {
  if (flushTimer !== null) { clearTimeout(flushTimer); flushTimer = null; }
  if (!file || pending.length === 0) return writing.then(() => {});
  const f = file;
  const text = pending.join("\n") + "\n";
  pending = [];
  return serial(async () => {
    const bytes = utf8(text);
    if (fileSize > 0 && fileSize + bytes > cap) {
      await f.debugLogFile({ op: "roll" });
      fileSize = 0;
      resetListeners.forEach((l) => l("roll"));
    }
    const r = await f.debugLogFile({ op: "append", text });
    fileSize = typeof r?.size === "number" ? r.size : fileSize + bytes;
    failures = 0;
  }).catch((e: unknown) => {
    failures += 1;
    if (failures >= MAX_FAILURES && file === f) {
      file = null;
      nearbyLog("log", `log file: ${failures} writes failed (${String(e)}); writing stopped`);
    }
  });
}

let hideListening = false;

/** Starts appending every line to the file, beginning with what the log holds
 *  now; once per page. Its only caller (nearbyDebug.tsx) attaches it where the
 *  plugin reports the device test's `logFile`. */
export function attachNearbyLogFile(f: LogFile, opts: { cap?: number } = {}): Promise<boolean> {
  if (file) return Promise.resolve(false);
  file = f;
  cap = opts.cap ?? LOG_FILE_CAP;
  failures = 0;
  pending.push(`--- log file attached ${new Date().toISOString()} at page time ${(now() / 1000).toFixed(3)} ---`);
  pending.push(...snapshot.map(lineText));
  if (!hideListening && typeof document !== "undefined") {
    hideListening = true;
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") void flushNearbyLogFile(); });
  }
  return serial(async () => {
    const r = await f.debugLogFile({ op: "size" });
    fileSize = typeof r?.size === "number" ? r.size : 0;
  }).then(() => flushNearbyLogFile()).then(() => true, () => true);
}

/** Whether lines are going to the file. */
export function nearbyLogFileOn(): boolean {
  return file !== null;
}

/** Empties the file (and drops the older one), after any write in flight;
 *  resolves whether the plugin did. */
export function clearNearbyLogFile(): Promise<boolean> {
  const f = file;
  if (!f) return Promise.resolve(false);
  pending = [];
  if (flushTimer !== null) { clearTimeout(flushTimer); flushTimer = null; }
  return serial(async () => {
    await f.debugLogFile({ op: "clear" });
    fileSize = 0;
    resetListeners.forEach((l) => l("clear"));
  }).then(() => true, () => false);
}

/** Tests: no file, nothing pending. */
export function detachNearbyLogFile(): void {
  file = null;
  pending = [];
  fileSize = 0;
  failures = 0;
  cap = LOG_FILE_CAP;
  if (flushTimer !== null) { clearTimeout(flushTimer); flushTimer = null; }
  writing = Promise.resolve();
}
