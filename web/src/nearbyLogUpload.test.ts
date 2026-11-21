// @vitest-environment jsdom
// The device-test log upload: whole lines in chunks, the offset moves only on
// 204, a missing or failing endpoint is retried next tick, 413 halves the
// chunk, 400 skips to the file's end, a roll or a clear starts the new file at
// 0, and outside the device-test page build nothing is started or bundled.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  attachNearbyLogFile, clearNearbyLog, clearNearbyLogFile, detachNearbyLogFile, flushNearbyLogFile, nearbyLog,
  nearbyLogLines, type LogFile,
} from "./nearbyLog";
import {
  loadUploadState, startNearbyLogUpload, stopNearbyLogUploadForTests, TICK_MS, UPLOAD_URL, uploadChunkForTests,
  uploadDeviceId, uploadNearbyLogNow,
} from "./nearbyLogUpload";

const enc = new TextEncoder();
const dec = new TextDecoder();
const size = (s: string) => enc.encode(s).length;

/** The plugin's two files, in memory, with the native read's whole-line rule. */
function fakeFile() {
  const files = { main: "", old: null as string | null };
  const f: LogFile = {
    debugLogFile: vi.fn(async (o) => {
      if (o.op === "append") files.main += o.text ?? "";
      if (o.op === "roll") { files.old = files.main; files.main = ""; }
      if (o.op === "clear") { files.old = null; files.main = ""; }
      if (o.op === "read") {
        const src = o.file === "old" ? files.old : files.main;
        if (src === null) return { text: "", bytes: 0, size: 0, exists: false };
        const b = enc.encode(src);
        let d = b.slice(o.offset ?? 0, (o.offset ?? 0) + (o.max ?? 0));
        const nl = d.lastIndexOf(10);
        d = nl >= 0 ? d.slice(0, nl + 1) : d.length < (o.max ?? 0) ? d.slice(0, 0) : d;
        return { text: dec.decode(d), bytes: d.length, size: b.length, exists: true };
      }
      return { size: size(files.main) };
    }),
  };
  return { f, files };
}

type Reply = number | "network";
function mockFetch(replies: Reply[], fallback: Reply = 204) {
  const calls: { body: string; headers: Record<string, string> }[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe(UPLOAD_URL);
    expect(init.method).toBe("POST");
    calls.push({ body: String(init.body), headers: init.headers as Record<string, string> });
    const r = replies.length ? replies.shift()! : fallback;
    if (r === "network") throw new TypeError("Failed to fetch");
    return new Response(r === 204 ? null : "secret server text", { status: r });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

const uploadLines = () => nearbyLogLines().filter((l) => /^upload/.test(l.text)).map((l) => l.text);

async function withFile(lines: string[]) {
  const ff = fakeFile();
  expect(await attachNearbyLogFile(ff.f)).toBe(true);
  for (const l of lines) nearbyLog("host", l);
  await flushNearbyLogFile();
  return ff;
}

beforeEach(() => {
  localStorage.clear();
  detachNearbyLogFile();
  clearNearbyLog();
  stopNearbyLogUploadForTests();
  vi.stubEnv("VITE_SHENGJI_NEARBY", "1");
});
afterEach(() => {
  stopNearbyLogUploadForTests();
  detachNearbyLogFile();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("the log upload", () => {
  it("sends the unsent bytes as whole lines with the contract's headers, and nothing twice", async () => {
    const { files } = await withFile(["link p1 up", "link p2 up"]);
    startNearbyLogUpload();
    const { calls } = mockFetch([]);
    await uploadNearbyLogNow();
    expect(calls).toHaveLength(1);
    expect(calls[0].body).toBe(files.main.slice(0, calls[0].body.length));
    expect(calls[0].body.endsWith("\n")).toBe(true);
    expect(calls[0].headers).toEqual({
      "Content-Type": "text/plain; charset=utf-8",
      "X-Nearby-Device": expect.stringMatching(/^[A-Z0-9]{12}$/),
      "X-Nearby-Offset": "0",
      "X-Nearby-Build": "beta-soak",
    });
    expect(uploadDeviceId()).toBe(calls[0].headers["X-Nearby-Device"]);
    const first = size(calls[0].body);
    expect(loadUploadState()).toMatchObject({ cur: first, stream: first });
    expect(uploadLines()).toEqual([`upload ${first} B ok`]);
    await flushNearbyLogFile();
    await uploadNearbyLogNow();
    // the second tick sends only the new line (the first tick's own)
    expect(calls).toHaveLength(2);
    expect(calls[1].headers["X-Nearby-Offset"]).toBe(String(first));
    expect(calls[1].body).toMatch(/^[\d.]+ log upload \d+ B ok\n$/);
  });

  it("chunks at 1 MB and stops at 5 MB a tick", async () => {
    const line = "x ".repeat(50);
    const lines = Array.from({ length: 70_000 }, (_, i) => `${line} ${i}`);   // ~7.7 MB
    await withFile(lines);
    const { calls } = mockFetch([]);
    await uploadNearbyLogNow();
    expect(calls.length).toBeGreaterThanOrEqual(5);
    for (const c of calls) {
      expect(size(c.body)).toBeLessThanOrEqual(1_000_000);
      expect(c.body.endsWith("\n")).toBe(true);
    }
    const total = calls.reduce((n, c) => n + size(c.body), 0);
    expect(total).toBeLessThanOrEqual(5_000_000);
    expect(total).toBeGreaterThan(4_800_000);
    let at = 0;
    for (const c of calls) { expect(c.headers["X-Nearby-Offset"]).toBe(String(at)); at += size(c.body); }
  });

  it.each([404, 405, 429, 500, 503, "network" as const])("keeps the offset on %s and retries next tick, one pending line", async (r) => {
    await withFile(["link p1 up"]);
    const { calls } = mockFetch([r]);
    await uploadNearbyLogNow();
    expect(loadUploadState()).toMatchObject({ cur: 0, stream: 0 });
    expect(uploadLines()).toEqual([`upload pending (${r})`]);
    expect(calls).toHaveLength(1);
    await uploadNearbyLogNow();
    expect(calls).toHaveLength(2);
    expect(calls[1].headers["X-Nearby-Offset"]).toBe("0");
    expect(calls[1].body.startsWith(calls[0].body)).toBe(true);
    expect(loadUploadState().cur).toBeGreaterThan(0);
    // the response body never reaches the log
    expect(nearbyLogLines().some((l) => l.text.includes("secret"))).toBe(false);
  });

  it("writes one pending line per tick while the server is down", async () => {
    await withFile(["link p1 up"]);
    mockFetch([], 404);
    for (let i = 0; i < 5; i++) await uploadNearbyLogNow();
    expect(uploadLines()).toEqual(Array(5).fill("upload pending (404)"));
  });

  it("halves the chunk on 413 and sends the same bytes smaller", async () => {
    await withFile(Array.from({ length: 20_000 }, (_, i) => `line ${i} ${"y ".repeat(30)}`));
    const { calls } = mockFetch([413, 413]);
    await uploadNearbyLogNow();
    expect(uploadChunkForTests()).toBe(250_000);
    expect(size(calls[0].body)).toBeGreaterThan(size(calls[1].body));
    expect(size(calls[2].body)).toBeLessThanOrEqual(250_000);
    expect(calls[2].headers["X-Nearby-Offset"]).toBe("0");
    expect(loadUploadState().cur).toBeGreaterThan(0);
  });

  it("on 400 logs one refusal, skips to the end of the file and does not retry that chunk", async () => {
    const { files } = await withFile(["link p1 up", "link p2 up"]);
    const { calls } = mockFetch([400]);
    await uploadNearbyLogNow();
    const end = size(files.main);
    expect(uploadLines()).toEqual(["upload refused (400)", "upload 0 B ok"]);
    expect(calls).toHaveLength(1);
    expect(loadUploadState().cur).toBe(end);
    await flushNearbyLogFile();
    await uploadNearbyLogNow();
    expect(calls[1].headers["X-Nearby-Offset"]).toBe(String(end));
    expect(calls[1].body).not.toContain("link p1 up");
  });

  it("a roll sends the rest of the older file, then the new one from 0; the stream offset keeps counting", async () => {
    const ff = fakeFile();
    expect(await attachNearbyLogFile(ff.f, { cap: 400 })).toBe(true);
    startNearbyLogUpload();
    const { calls } = mockFetch([]);
    nearbyLog("host", "a ".repeat(25));
    await flushNearbyLogFile();
    await uploadNearbyLogNow();
    const sent1 = loadUploadState().cur;
    nearbyLog("host", "b ".repeat(60));
    await flushNearbyLogFile();
    nearbyLog("host", "c ".repeat(150));   // over the cap: the file rolls before this
    await flushNearbyLogFile();
    expect(ff.files.old).toContain("b b b");
    expect(loadUploadState()).toMatchObject({ gen: 1, cur: 0, old: sent1 });
    await uploadNearbyLogNow();
    const bodies = calls.slice(1).map((c) => c.body);
    expect(bodies[0]).toContain("b b b");
    expect(bodies[0]).not.toContain("a a a");
    expect(bodies[1]).toContain("c c c");
    expect(calls[2].headers["X-Nearby-Offset"]).toBe(String(sent1 + size(bodies[0])));
    expect(loadUploadState().old).toBeNull();
  });

  it("a clear starts the file at 0 and drops what the older file held", async () => {
    const ff = await withFile(["link p1 up"]);
    startNearbyLogUpload();
    mockFetch([]);
    await uploadNearbyLogNow();
    const st = loadUploadState();
    expect(st.cur).toBeGreaterThan(0);
    expect(await clearNearbyLogFile()).toBe(true);
    expect(loadUploadState()).toEqual({ gen: 1, cur: 0, old: null, stream: st.stream });
    expect(ff.files.main).toBe("");
  });

  it("ticks every 10 minutes and when the page hides", async () => {
    await withFile(["link p1 up"]);
    vi.useFakeTimers();
    const { calls } = mockFetch([]);
    expect(startNearbyLogUpload()).toBe(true);
    await vi.advanceTimersByTimeAsync(TICK_MS - 1000);
    expect(calls).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2000);
    expect(calls).toHaveLength(1);
    nearbyLog("host", "more");
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(10);
    expect(calls).toHaveLength(2);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });
});

describe("the log upload outside the device-test build", () => {
  it("never starts", async () => {
    vi.stubEnv("VITE_SHENGJI_NEARBY", "");
    const { fn } = mockFetch([]);
    expect(startNearbyLogUpload()).toBe(false);
    await Promise.resolve();
    expect(fn).not.toHaveBeenCalled();
  });

  it("is loaded only from the device-test branch, behind the logFile capability, so other builds bundle none of it", () => {
    const src = readFileSync(join(process.cwd(), "src/nearbyDebug.tsx"), "utf8");
    expect(src).not.toMatch(/from "\.\/nearbyLogUpload"/);   // no static import: only the gated dynamic one
    expect(src.match(/= import\("\.\/nearbyLogUpload"\)/g)).toHaveLength(1);
    expect(src).toMatch(/if \(import\.meta\.env\.VITE_SHENGJI_NEARBY !== "1"\) return;\n  upload = import\("\.\/nearbyLogUpload"\)/);
    expect(src).toMatch(/c\.logFile === true[^\n]*\n      if \(await attachNearbyLogFile\(p as unknown as LogFile\)\) startUpload\(\);/);
    // nothing else imports it
    const menu = readFileSync(join(process.cwd(), "src/components/HudMenu.tsx"), "utf8");
    expect(menu).not.toContain("nearbyLogUpload");
  });
});
