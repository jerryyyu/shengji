// @vitest-environment node
// The page's side of the native plugin, on a stand-in plugin: a join link the
// host closed ends the plugin's session (its screen wake lock goes with it),
// and a host link passes the plugin's opaque device id through.
import { expect, it, vi } from "vitest";

type Fn = (ev: Record<string, unknown>) => void;
const plugin = vi.hoisted(() => {
  const listeners = new Map<string, Set<(ev: Record<string, unknown>) => void>>();
  return {
    listeners,
    stops: 0,
    emit(event: string, ev: Record<string, unknown>) { for (const fn of [...(listeners.get(event) ?? [])]) fn(ev); },
    capabilities: async () => ({ reviewed: false, debug: true }),
    openSettings: async () => {},
    host: async () => {},
    join: async () => {},
    send: async () => {},
    close: async () => {},
    async stop() { this.stops += 1; },
    async addListener(event: string, fn: (ev: Record<string, unknown>) => void) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(fn);
      return { remove: () => { listeners.get(event)!.delete(fn); } };
    },
  };
});
vi.mock("../../../native", () => ({ nearbyPluginProxy: () => plugin }));

const { nativeTransport } = await import("./native");
const tick = () => new Promise((r) => setTimeout(r, 0));

it("a join link the host closed stops the plugin's session", async () => {
  const t = nativeTransport()!;
  let closed = 0;
  const linking = t.join("K7Q2MX", { message: () => {}, closed: () => { closed += 1; }, state: () => {} });
  await tick();
  plugin.emit("peer", { peer: "host", state: "connected" });
  await linking;
  const before = plugin.stops;
  plugin.emit("peer", { peer: "host", state: "disconnected" });
  expect(closed).toBe(1);
  expect(plugin.stops).toBe(before + 1);
});

it("a host link passes the plugin's device id to the room", async () => {
  const t = nativeTransport()!;
  const peers: unknown[][] = [];
  await t.host("K7Q2MX", { peer: (...a) => peers.push(a), message: () => {}, state: () => {} });
  plugin.emit("peer", { peer: "p1", state: "connected", device: "DEV1" } as Parameters<Fn>[0]);
  plugin.emit("peer", { peer: "p1", state: "disconnected" });
  expect(peers).toEqual([["p1", true, "DEV1"], ["p1", false, undefined]]);
});
