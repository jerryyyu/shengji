// Nearby play is gated at run time by the app binary: in a browser, an App
// Store binary (no plugin) or a binary whose plugin is not enabled, nothing
// nearby renders and the nearby UI module is never imported; the Beta shows
// the nearby UI without the device test's soak rows; the device test's
// `logFile` adds them.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const { native, evaluated, listeners } = vi.hoisted(() => ({
  native: { available: false, plugin: null as unknown },
  evaluated: { n: 0 },
  listeners: { n: 0 },
}));

vi.mock("./ws", () => ({
  conn: { send: () => true, subscribe: () => () => {}, subscribeStatus: () => () => {}, reconnect: () => {},
          generation: 0, status: "open" },
  getSavedName: () => "",
  saveName: () => {},
  getResumeToken: () => null,
  getSavedRoom: () => null,
  clearSavedRoom: () => {},
}));
vi.mock("./components/offlineGame", () => ({
  offlineGame: { startFromPlay: () => {}, goOnline: () => {}, setTable: () => {}, played: false },
  offlineOffered: () => false,
  useOfflineTable: () => false,
  useOfflineBotLevel: () => "standard",
}));
vi.mock("./native", async (orig) => ({
  ...(await orig<typeof import("./native")>()),
  pluginAvailable: (name: string) => name === "ShengjiNearby" && native.available,
  nearbyPluginProxy: () => native.plugin,
}));
// the nearby UI's module: its body runs only if something imports it
vi.mock("./nearbyUi", async (orig) => {
  evaluated.n += 1;
  return await orig<typeof import("./nearbyUi")>();
});

import Lobby from "./components/Lobby";
import HudMenu from "./components/HudMenu";
import { OfflineControls } from "./components/OfflinePlay";
import { nearbyGate, resetNearbyGateForTests, type NearbyUi } from "./nearbyGate";
import { resetNearbyDebugForTests } from "./nearbyDebug";
import { detachNearbyLogFile } from "./nearbyLog";
import { stopNearbyLogUploadForTests } from "./nearbyLogUpload";

/** A plugin that answers `capabilities()` with `caps` and records every call. */
function fakePlugin(caps: Record<string, unknown>) {
  const calls: string[] = [];
  const record = (name: string, value: unknown = undefined) => async () => { calls.push(name); return value; };
  return {
    calls,
    p: {
      capabilities: record("capabilities", caps),
      addListener: async () => { calls.push("addListener"); listeners.n += 1; return { remove: () => {} }; },
      host: record("host"), join: record("join"), send: record("send"), close: record("close"), stop: record("stop"),
      openSettings: record("openSettings"),
      debugLogFile: async (o: { op: string }) => { calls.push(`debugLogFile:${o.op}`); return { size: 0, text: "" }; },
    },
  };
}

let loads = 0;
let loading: Promise<unknown> = Promise.resolve();
const loader = (): Promise<NearbyUi> => {
  loads += 1;
  const m = import("./nearbyUi");
  loading = m;
  return m;
};

async function settle() {
  for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

/** Play's lobby, the offline Play controls and a nearby table's ⋯ menu, the
 *  three places the nearby entry points live, with the menu open. */
async function renderAll() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(
    <>
      <div className="online"><Lobby status="open" /></div>
      <div className="offline"><OfflineControls local status="open" code="K7Q2M" /></div>
      <div className="menu"><HudMenu room="K7Q2M" offline nearby /></div>
    </>,
  ));
  await settle();
  await act(async () => { await loading; });
  await settle();
  act(() => host.querySelector<HTMLButtonElement>(".menu .hud-more-btn")!.click());
  await settle();
  const rows = () => Array.from(host.querySelectorAll<HTMLElement>(".menu .hud-menu-row")).map((r) => r.textContent);
  return { host, rows, unmount: () => { act(() => root.unmount()); host.remove(); } };
}

const SOAK_ROWS = ["Autoplay", "Chaos", "Copy soak summary", "Clear log file", "Upload log now"];

function expectNoNearby(v: Awaited<ReturnType<typeof renderAll>>) {
  expect(v.host.querySelector(".join-row.nearby")).toBeNull();
  for (const input of v.host.querySelectorAll<HTMLInputElement>(".room-input")) expect(input.maxLength).toBe(4);
  expect(v.host.querySelector(".join-line")).toBeNull();
  expect(v.host.querySelector(".nearby-link-dot")).toBeNull();
  expect(v.host.querySelector("[role='switch']")).toBeNull();
  expect(v.host.textContent).not.toMatch(/nearby|Nearby|Local Network/);
  expect(v.rows().filter((r) => r === "Copy log" || SOAK_ROWS.includes(r ?? ""))).toEqual([]);
}

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});
afterEach(() => {
  stopNearbyLogUploadForTests();
  detachNearbyLogFile();
  resetNearbyDebugForTests();
  resetNearbyGateForTests();
  localStorage.clear();
});
afterAll(() => { resetNearbyGateForTests(); });

// The order matters: the module, once imported, stays in the module cache,
// so the two "never imported" cases run first.
describe("nearby play's run-time gate", () => {
  it("in a browser or an App Store binary (no plugin): nothing nearby, no plugin call, no import", async () => {
    native.available = false;
    const { p, calls } = fakePlugin({ reviewed: true, beta: true, debug: true, logFile: true });
    native.plugin = p;
    loads = 0;
    resetNearbyGateForTests(loader);
    const v = await renderAll();
    expectNoNearby(v);
    expect(calls, "no plugin call at all, the capability check included").toEqual([]);
    expect(loads, "the nearby UI's dynamic import never called").toBe(0);
    expect(evaluated.n, "the nearby UI module never ran").toBe(0);
    expect(listeners.n).toBe(0);
    expect(nearbyGate()).toEqual({ on: false, debug: false, logFile: false });
    v.unmount();
  });

  it("a plugin that is present but not enabled: the capability check alone, then nothing", async () => {
    native.available = true;
    const { p, calls } = fakePlugin({ reviewed: false, beta: false, debug: false, logFile: false });
    native.plugin = p;
    loads = 0;
    resetNearbyGateForTests(loader);
    const v = await renderAll();
    expectNoNearby(v);
    expect(calls).toEqual(["capabilities"]);
    expect(loads).toBe(0);
    expect(evaluated.n).toBe(0);
    expect(listeners.n).toBe(0);
    v.unmount();
  });

  it("while the capabilities are still loading: nothing nearby yet", async () => {
    native.available = true;
    let answer: (c: Record<string, unknown>) => void = () => {};
    native.plugin = { capabilities: () => new Promise((r) => { answer = r; }) };
    loads = 0;
    resetNearbyGateForTests(loader);
    const v = await renderAll();
    expectNoNearby(v);
    expect(loads).toBe(0);
    expect(evaluated.n).toBe(0);
    await act(async () => { answer({ beta: false }); });
    v.unmount();
  });

  it("the Beta (beta enabled): the nearby UI, without the soak rows", async () => {
    native.available = true;
    const { p, calls } = fakePlugin({ reviewed: false, beta: true, debug: false, logFile: false });
    native.plugin = p;
    loads = 0;
    resetNearbyGateForTests(loader);
    const v = await renderAll();
    expect(loads).toBe(1);
    expect(nearbyGate()).toEqual({ on: true, debug: false, logFile: false });
    // the code box takes a nearby code, online and offline, with its one line
    const rows = v.host.querySelectorAll<HTMLInputElement>(".join-row.nearby .room-input");
    expect(rows.length).toBe(2);
    for (const input of rows) expect(input.maxLength).toBe(5);
    expect(v.host.querySelector(".offline .join-line")?.textContent).toMatch(/nearby table/);
    expect(v.rows()).not.toContain("Copy log");
    for (const r of SOAK_ROWS) expect(v.rows()).not.toContain(r);
    expect(calls.filter((c) => c.startsWith("debugLogFile"))).toEqual([]);
    v.unmount();
  });

  it("the device test (debug and logFile): the soak rows", async () => {
    native.available = true;
    const { p, calls } = fakePlugin({ debug: true, logFile: true });
    native.plugin = p;
    loads = 0;
    resetNearbyGateForTests(loader);
    const v = await renderAll();
    expect(nearbyGate()).toEqual({ on: true, debug: true, logFile: true });
    // the soak's own module loads once the menu knows it is in the device test
    for (let i = 0; i < 100 && !v.rows().includes("Autoplay"); i++) await settle();
    for (const r of ["Copy log", ...SOAK_ROWS]) expect(v.rows()).toContain(r);
    expect(calls.some((c) => c.startsWith("debugLogFile"))).toBe(true);
    v.unmount();
  });
});
