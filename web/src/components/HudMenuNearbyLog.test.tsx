// The ⋯ menu's Clear log file row: only at a nearby table in the device-test
// build (the plugin reporting `debug` and `logFile`); tapping it empties the
// file on the phone.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import HudMenu from "./HudMenu";
import { resetNearbyDebugForTests } from "../nearbyDebug";
import { resetNearbyGateForTests, setNearbyGateForTests } from "../nearbyGate";
import { detachNearbyLogFile } from "../nearbyLog";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {}, subscribe: () => () => {}, subscribeStatus: () => () => {} } }));
vi.mock("./offlineGame", () => ({ offlineGame: { startFromPlay: () => {}, goOnline: () => {} } }));
const plugin = { current: null as unknown };
vi.mock("../native", async (orig) => ({ ...(await orig<typeof import("../native")>()), nearbyPluginProxy: () => plugin.current }));

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});
afterEach(() => {
  detachNearbyLogFile();
  resetNearbyDebugForTests();
  resetNearbyGateForTests();
});

function fakePlugin(caps: Record<string, unknown>) {
  const ops: string[] = [];
  return {
    ops,
    p: {
      capabilities: async () => caps,
      addListener: async () => ({ remove: () => {} }),
      debugLogFile: async (o: { op: string }) => { ops.push(o.op); return { size: 0 }; },
    },
  };
}

async function openMenu(caps: Record<string, unknown>) {
  await setNearbyGateForTests(caps);
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(<HudMenu room="ABCD" offline nearby />));
  for (let i = 0; i < 10; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());
  for (let i = 0; i < 10; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const rows = () => Array.from(host.querySelectorAll<HTMLElement>(".hud-menu-row"));
  return { host, rows, unmount: () => act(() => root.unmount()) };
}

describe("Clear log file", () => {
  it("is a row in the device-test build, and empties the file", async () => {
    const caps = { debug: true, logFile: true };
    const { p, ops } = fakePlugin(caps);
    plugin.current = p;
    const v = await openMenu(caps);
    const row = v.rows().find((r) => r.textContent === "Clear log file");
    expect(row).toBeDefined();
    expect(v.rows().map((r) => r.textContent)).toContain("Copy log");
    await act(async () => { row!.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(ops).toContain("clear");
    expect(v.host.querySelector(".hud-menu")).toBeNull();
    v.unmount();
  });

  for (const [why, caps] of [
    ["the Beta build", { beta: true, debug: false, logFile: false }],
    ["a binary without the file (a spike build)", { debug: true, logFile: false }],
    ["a shipped binary", { debug: false, logFile: false }],
  ] as const) {
    it(`is absent in ${why}, which writes nothing`, async () => {
      const { p, ops } = fakePlugin(caps);
      plugin.current = p;
      const v = await openMenu(caps);
      expect(v.rows().map((r) => r.textContent)).not.toContain("Clear log file");
      expect(ops).toEqual([]);
      v.unmount();
    });
  }
});
