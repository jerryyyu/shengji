// The device-test log file's upload: in the device-test build only (the
// plugin's debug and logFile capabilities, the same gating as the file), the
// bytes of the file not yet sent go to the
// server every TICK_MS, when the app goes to the background, and on the ⋯
// menu's Upload log now. Whole lines only, at most CHUNK_MAX per request and
// TICK_MAX per tick; the uploaded offset is kept per file in localStorage, so
// a byte is never sent twice, and a roll or a Clear starts the new file at 0.
// An endpoint that is missing or down keeps the offset for the next tick and
// writes at most one "pending" line per tick. Nothing here runs inside a game
// handler: every tick is a timer, a visibility event or a menu tap.
import { flushNearbyLogFile, nearbyLog, onNearbyLogFileReset, readNearbyLogFile, type LogFileReset } from "./nearbyLog";

export const UPLOAD_URL = "https://shengji.fly.dev/api/nearby-log";
export const CHUNK_MAX = 1_000_000;
export const TICK_MAX = 5_000_000;
export const TICK_MS = 10 * 60 * 1000;
export const TIMEOUT_MS = 20_000;
const CHUNK_MIN = 4096;
const STATE_KEY = "shengji.nearbyLogUpload.v1";
const DEVICE_KEY = "shengji.nearbyLogDevice.v1";

/** What has been sent: `cur` bytes of nearby-log.txt, `old` bytes of
 *  nearby-log.1.txt (null once it is sent or gone), `stream` bytes in all;
 *  `gen` counts the rolls and clears. */
export interface UploadState { gen: number; cur: number; old: number | null; stream: number }

const fresh = (): UploadState => ({ gen: 0, cur: 0, old: null, stream: 0 });

function store(): Storage | null {
  try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; }
}

export function loadUploadState(): UploadState {
  try {
    const v = JSON.parse(store()?.getItem(STATE_KEY) ?? "null") as Partial<UploadState> | null;
    if (v && typeof v.gen === "number" && typeof v.cur === "number" && typeof v.stream === "number") {
      return { gen: v.gen, cur: v.cur, old: typeof v.old === "number" ? v.old : null, stream: v.stream };
    }
  } catch { /* a fresh state */ }
  return fresh();
}

function saveUploadState(s: UploadState): void {
  try { store()?.setItem(STATE_KEY, JSON.stringify(s)); } catch { /* kept in memory only this tick */ }
}

const ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

/** A random id for this install, made once: not the account, not the device name. */
export function uploadDeviceId(): string {
  try {
    const have = store()?.getItem(DEVICE_KEY);
    if (have && /^[A-Z0-9]{12}$/.test(have)) return have;
  } catch { /* make one */ }
  const bytes = new Uint8Array(12);
  globalThis.crypto.getRandomValues(bytes);
  const id = Array.from(bytes, (b) => ID_CHARS[b % ID_CHARS.length]).join("");
  try { store()?.setItem(DEVICE_KEY, id); } catch { /* this page only */ }
  return id;
}

function onReset(why: LogFileReset): void {
  const s = loadUploadState();
  saveUploadState({ gen: s.gen + 1, cur: 0, old: why === "roll" ? s.cur : null, stream: s.stream });
}

let chunk = CHUNK_MAX;
let running: Promise<void> | null = null;

const buildLabel = (): string => {
  const v = import.meta.env.VITE_NEARBY_BUILD as string | undefined;
  return (v && v.trim() ? v.trim() : "beta-soak").slice(0, 60);
};

type Sent = { status: number } | { error: string };

async function post(body: string, offset: number): Promise<Sent> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(UPLOAD_URL, {
      method: "POST",
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "X-Nearby-Device": uploadDeviceId(),
        "X-Nearby-Offset": String(offset),
        "X-Nearby-Build": buildLabel(),
      },
      body,
      signal: ctl.signal,
      credentials: "omit",
      cache: "no-store",
    });
    // the body is never read or logged
    return { status: r.status };
  } catch (e) {
    return { error: ctl.signal.aborted ? "timeout" : "network" };
  } finally {
    clearTimeout(timer);
  }
}

/** One tick: sends what is not yet sent, up to TICK_MAX; resolves when done.
 *  A tick asked for while one runs joins it. */
export function uploadNearbyLogNow(): Promise<void> {
  running ??= tick().finally(() => { running = null; });
  return running;
}

async function tick(): Promise<void> {
  let sent = 0;
  let pending: string | null = null;
  try {
    await flushNearbyLogFile();
    while (sent < TICK_MAX) {
      const s = loadUploadState();
      const which = s.old !== null ? "old" : "current";
      const off = which === "old" ? (s.old as number) : s.cur;
      const max = Math.min(chunk, TICK_MAX - sent);
      const r = await readNearbyLogFile(which, off, max);
      if (!r) { pending = "no log file"; break; }
      // the tick's budget ran out inside a line: that line goes next tick, whole
      if (r.bytes > 0 && !r.text.endsWith("\n") && max < chunk) break;
      if (r.bytes === 0) {
        if (which === "old") { saveUploadState({ ...loadUploadState(), old: null }); continue; }
        break;
      }
      const res = await post(r.text, s.stream);
      if ("error" in res) { pending = res.error; break; }
      if (res.status === 204) {
        advance(s.gen, which, r.bytes, r.bytes);
        sent += r.bytes;
        continue;
      }
      if (res.status === 413 && chunk > CHUNK_MIN) {
        chunk = Math.max(CHUNK_MIN, Math.floor(chunk / 2));
        continue;
      }
      if (res.status === 400) {
        nearbyLog("log", "upload refused (400)");
        const skip = Math.max(r.bytes, r.size - off);
        advance(s.gen, which, skip, skip);
        break;
      }
      pending = String(res.status);
      break;
    }
  } catch (e) {
    pending = "read failed";
  }
  if (pending !== null) nearbyLog("log", sent > 0 ? `upload ${sent} B ok, then pending (${pending})` : `upload pending (${pending})`);
  else nearbyLog("log", `upload ${sent} B ok`);
}

/** Moves the offset of the file read at `gen`: if it rolled since, those bytes
 *  are now the older file's; after a clear they are gone. */
function advance(gen: number, which: "current" | "old", fileBytes: number, streamBytes: number): void {
  const s = loadUploadState();
  s.stream += streamBytes;
  if (s.gen === gen) {
    if (which === "old" && s.old !== null) s.old += fileBytes;
    else if (which === "current") s.cur += fileBytes;
  } else if (s.gen === gen + 1 && which === "current" && s.old !== null) {
    s.old += fileBytes;
  }
  saveUploadState(s);
}

let started = false;
let interval: ReturnType<typeof setInterval> | null = null;
let offReset: () => void = () => {};
let onHide: (() => void) | null = null;

/** Starts the ticks, once per page, only after the log file is attached
 *  (the caller checks the capability). */
export function startNearbyLogUpload(): boolean {
  if (started) return false;
  started = true;
  offReset = onNearbyLogFileReset(onReset);
  interval = setInterval(() => { void uploadNearbyLogNow(); }, TICK_MS);
  if (typeof document !== "undefined") {
    onHide = () => { if (document.visibilityState === "hidden") void uploadNearbyLogNow(); };
    document.addEventListener("visibilitychange", onHide);
  }
  return true;
}

export function nearbyLogUploadOn(): boolean {
  return started;
}

/** Tests: stopped, at a full chunk. */
export function stopNearbyLogUploadForTests(): void {
  started = false;
  chunk = CHUNK_MAX;
  running = null;
  offReset();
  offReset = () => {};
  if (interval !== null) { clearInterval(interval); interval = null; }
  if (onHide && typeof document !== "undefined") document.removeEventListener("visibilitychange", onHide);
  onHide = null;
}

export function uploadChunkForTests(): number {
  return chunk;
}
