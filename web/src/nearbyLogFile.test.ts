// @vitest-environment node
// The device-test log file: every log line is appended in batches, the file
// rolls to one older file at its cap, a line that looks like personal data is
// withheld, and outside the device test and the Beta nothing is ever written.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  attachNearbyLogFile, clearNearbyLog, clearNearbyLogFile, detachNearbyLogFile, flushNearbyLogFile, nearbyLog,
  nearbyLogFileOn, type LogFile,
} from "./nearbyLog";

/** The plugin's two files, in memory. */
function fakeFile() {
  const files = { main: "", old: null as string | null };
  const calls: { op: string; text?: string }[] = [];
  const f: LogFile = {
    debugLogFile: vi.fn(async (o: { op: string; text?: string }) => {
      calls.push(o);
      if (o.op === "append") files.main += o.text ?? "";
      if (o.op === "roll") { files.old = files.main; files.main = ""; }
      if (o.op === "clear") { files.old = null; files.main = ""; }
      return { size: new TextEncoder().encode(files.main).length };
    }),
  };
  return { f, files, calls };
}

beforeEach(() => {
  detachNearbyLogFile();
  clearNearbyLog();
});
afterEach(() => {
  detachNearbyLogFile();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("the nearby log file, in the device test and the Beta", () => {
  it("starts with what the log holds, then appends each line in one batched write", async () => {
    nearbyLog("host", "link p1 up");
    const { f, files, calls } = fakeFile();
    expect(await attachNearbyLogFile(f)).toBe(true);
    expect(nearbyLogFileOn()).toBe(true);
    expect(files.main).toMatch(/^--- log file attached \d{4}-\d\d-\d\dT[^\n]* ---\n[\d.]+ host link p1 up\n$/);
    vi.useFakeTimers();
    nearbyLog("socket", "STUCK: no state; making a new link");
    nearbyLog("soak", "SOAK 10 min: games 1, rounds 3");
    const before = calls.length;
    // batched: nothing until the timer
    expect(calls.length).toBe(before);
    await vi.advanceTimersByTimeAsync(2500);
    expect(calls.slice(before).map((c) => c.op)).toEqual(["append"]);
    expect(files.main.split("\n").slice(-3)).toEqual([
      expect.stringMatching(/^[\d.]+ socket STUCK: no state; making a new link$/),
      expect.stringMatching(/^[\d.]+ soak SOAK 10 min: games 1, rounds 3$/),
      "",
    ]);
  });

  it("a full batch writes at once, without waiting for the timer", async () => {
    const { f, calls } = fakeFile();
    await attachNearbyLogFile(f);
    vi.useFakeTimers();
    const before = calls.length;
    for (let i = 0; i < 200; i++) nearbyLog("host", `in state from p${i}`);
    await vi.advanceTimersByTimeAsync(0);
    expect(calls.slice(before).map((c) => c.op)).toEqual(["append"]);
    expect(calls.at(-1)!.text!.split("\n")).toHaveLength(201);
  });

  it("rolls to the one older file before a write would pass the cap", async () => {
    const { f, files, calls } = fakeFile();
    await attachNearbyLogFile(f, { cap: 200 });
    const first = files.main;
    nearbyLog("host", "x ".repeat(10));
    await flushNearbyLogFile();
    expect(calls.map((c) => c.op)).toEqual(["size", "append", "append"]);
    const full = files.main;
    expect(full.startsWith(first)).toBe(true);
    nearbyLog("host", "y ".repeat(90));
    await flushNearbyLogFile();
    expect(calls.map((c) => c.op).slice(-2)).toEqual(["roll", "append"]);
    expect(files.old).toBe(full);
    expect(files.main).toMatch(/^[\d.]+ host (y ){89}y \n$/);
    // a second roll keeps only one older file
    nearbyLog("host", "z ".repeat(90));
    await flushNearbyLogFile();
    expect(files.old).toMatch(/(y ){89}/);
    expect(files.main).toMatch(/(z ){89}/);
  });

  it("a file already on the phone counts toward the cap", async () => {
    const { f, files, calls } = fakeFile();
    files.main = "a".repeat(150);
    await attachNearbyLogFile(f, { cap: 200 });
    expect(calls.map((c) => c.op)).toEqual(["size", "roll", "append"]);
    expect(files.old).toBe("a".repeat(150));
  });

  it("withholds a line that looks like an email or a token", async () => {
    const { f, files } = fakeFile();
    await attachNearbyLogFile(f);
    nearbyLog("join", "signed in as someone@example.com");
    nearbyLog("join", "auth token=abc123");
    nearbyLog("join", "jwt eyJhbGciOiJIUzI1NiJ9.payload");
    nearbyLog("join", "resume: link up in 40 ms; hello sent (with token)");
    nearbyLog("host", "link p3 up from Q7XK2M9PLA4B");
    await flushNearbyLogFile();
    expect(files.main).not.toMatch(/example\.com|abc123|eyJ/);
    expect(files.main.match(/\[line withheld from the file\]/g)).toHaveLength(3);
    expect(files.main).toContain("hello sent (with token)");
    expect(files.main).toContain("link p3 up from Q7XK2M9PLA4B");
  });

  it("Clear empties both files and drops lines not yet written", async () => {
    const { f, files, calls } = fakeFile();
    await attachNearbyLogFile(f, { cap: 120 });
    nearbyLog("host", "y ".repeat(50));
    await flushNearbyLogFile();
    nearbyLog("host", "unwritten");
    expect(await clearNearbyLogFile()).toBe(true);
    expect(calls.at(-1)!.op).toBe("clear");
    expect(files).toEqual({ main: "", old: null });
    await flushNearbyLogFile();
    expect(files.main).toBe("");
    nearbyLog("host", "after the clear");
    await flushNearbyLogFile();
    expect(files.main).toMatch(/^[\d.]+ host after the clear\n$/);
  });

  it("stops writing after repeated failures, and says so in the log", async () => {
    const f: LogFile = { debugLogFile: vi.fn(async (o: { op: string }) => { if (o.op === "size") return { size: 0 }; throw new Error("disk"); }) };
    await attachNearbyLogFile(f);
    for (let i = 0; i < 5; i++) { nearbyLog("host", `line ${i}`); await flushNearbyLogFile(); }
    expect(nearbyLogFileOn()).toBe(false);
  });
});

describe("the nearby log file, in any other build", () => {
  it("is attached only where the plugin reports logFile, and unattached writes nothing", async () => {
    const debug = readFileSync(fileURLToPath(new URL("./nearbyDebug.tsx", import.meta.url)), "utf8");
    expect(debug.match(/attachNearbyLogFile\(/g)).toHaveLength(1);
    expect(debug).toMatch(/if \(c\.logFile === true && typeof \(p as Partial<LogFile>\)\.debugLogFile === "function"\) \{\n      listenNativeLog\(p as DebugPlugin\);\n      if \(await attachNearbyLogFile\(/);
    const { calls } = fakeFile();
    nearbyLog("host", "link p1 up");
    await flushNearbyLogFile();
    expect(await clearNearbyLogFile()).toBe(false);
    expect(calls).toEqual([]);
    expect(nearbyLogFileOn()).toBe(false);
  });

  it("the plugin compiles the file method only in the device test and the Beta", () => {
    const swift = readFileSync(fileURLToPath(new URL("../ios/App/App/NearbyPlugin.swift", import.meta.url)), "utf8");
    expect(swift.match(/func debugLogFile/g)).toHaveLength(1);
    expect(swift).toMatch(/#if \(DEBUG && SHENGJI_NEARBY_DEV\) \|\| SHENGJI_NEARBY_BETA\n(?:\/\/\/[^\n]*\n)*extension ShengjiNearbyPlugin \{\n    static let logFileMethods: \[CAPPluginMethod\] = \[\n        CAPPluginMethod\(name: "debugLogFile"[\s\S]*?func debugLogFile[\s\S]*?\n#else\nextension ShengjiNearbyPlugin \{\n    static let logFileMethods: \[CAPPluginMethod\] = \[\]\n    static let logFileBuild = false\n\}\n#endif/);
    expect(swift).toContain('"logFile": Self.logFileBuild');
  });
});
