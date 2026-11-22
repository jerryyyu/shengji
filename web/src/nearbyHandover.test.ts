// The page's side of a move off peer-to-peer, on a stand-in plugin that
// does what NearbyPlugin.swift's handover does: it drops the peer-to-peer
// link only once its Wi-Fi link to the host is ready, and the page's resume
// join takes that link at once ("connected" within the join call). The page
// makes one new join, at once, and its hello (the token resume) is the first
// frame on the new link, so the seat is back in one round trip.
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type Ev = Record<string, unknown>;
const plugin = vi.hoisted(() => {
  const listeners = new Map<string, Set<(ev: Record<string, unknown>) => void>>();
  const p = {
    listeners,
    joins: [] as { code: string; resume: boolean; at: number }[],
    sent: [] as { text: string; at: number; link: number }[],
    stops: 0,
    link: 0,
    /** The next join's link comes up at once, over Wi-Fi (the handover). */
    handover: false,
    emit(event: string, ev: Record<string, unknown>) { for (const fn of [...(listeners.get(event) ?? [])]) fn(ev); },
    capabilities: async () => ({ reviewed: false, debug: true }),
    openSettings: async () => {},
    host: async () => {},
    async join(o: { code: string; resume?: boolean }) {
      p.joins.push({ code: o.code, resume: o.resume === true, at: Date.now() });
      p.link += 1;
      const via = p.handover ? "wifi" : "p2p";
      p.handover = false;
      p.emit("peer", { peer: "host", state: "connected", via });
    },
    async send(o: { peer: string; text: string }) { p.sent.push({ text: o.text, at: Date.now(), link: p.link }); },
    close: async () => {},
    async stop() { p.stops += 1; },
    async addListener(event: string, fn: (ev: Record<string, unknown>) => void) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(fn);
      return { remove: () => { listeners.get(event)!.delete(fn); } };
    },
  };
  return p;
});
vi.mock("./native", () => ({ nearbyPluginProxy: () => plugin }));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"] });
});
afterEach(() => vi.useRealTimers());

const host = (msg: Ev) => plugin.emit("message", { peer: "host", text: JSON.stringify(msg) });

it("a move off peer-to-peer: one resume join at once, taking the ready Wi-Fi link, and the seat back in one round trip", async () => {
  const { nativeTransport } = await import("./offline/server/nearby/native");
  const { NearbySocket } = await import("./offline/server/nearby/socket");
  const { realClock } = await import("./offline/server/clock");
  const { conn } = await import("./ws");
  const t = nativeTransport()!;
  let token: string | null = null;
  const statuses: { s: string; at: number }[] = [];
  conn.subscribe((m) => { if ((m as unknown as Ev).type === "resume") token = (m as unknown as Ev).token as string; });
  conn.subscribeStatus((s) => statuses.push({ s, at: Date.now() }));
  const greet = () => (token ? { type: "table_join", code: "K7Q2M", name: "Mei", token } : null);
  conn.start();
  conn.useNearby(() => new NearbySocket(t, "K7Q2M", null, realClock, greet) as unknown as WebSocket);
  await vi.advanceTimersByTimeAsync(10);
  expect(conn.status).toBe("open");
  // seated on the peer-to-peer link
  conn.send({ type: "table_join", code: "K7Q2M", name: "Mei", token: null } as never);
  host({ type: "resume", token: "tok-1", gen: 1 });
  host({ type: "state", room: "K7Q2M", you: 1, phase: "play", turn: 0, hand: [] });
  await vi.advanceTimersByTimeAsync(10);
  const joinsBefore = plugin.joins.length;
  // the plugin's Wi-Fi link is ready: it drops the peer-to-peer one
  plugin.handover = true;
  const movedAt = Date.now();
  plugin.emit("peer", { peer: "host", state: "disconnected" });
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(0);
  // one resume join, at once
  expect(plugin.joins.slice(joinsBefore)).toEqual([{ code: "K7Q2M", resume: true, at: movedAt }]);
  // the first frame on the new link is the token resume
  const onNew = plugin.sent.filter((s) => s.link === plugin.link);
  expect(onNew.length).toBeGreaterThan(0);
  expect(JSON.parse(onNew[0].text)).toMatchObject({ type: "nearby_hello", token: "tok-1" });
  expect(onNew[0].at).toBe(movedAt);
  // the host answers over Wi-Fi a round trip later: the seat is back
  await vi.advanceTimersByTimeAsync(30);
  host({ type: "resume", token: "tok-1", gen: 2 });
  host({ type: "state", room: "K7Q2M", you: 1, phase: "play", turn: 0, hand: [] });
  const back = statuses.filter((x) => x.s === "open" && x.at >= movedAt);
  expect(back).toHaveLength(1);
  expect(back[0].at - movedAt).toBeLessThanOrEqual(30);
  expect(plugin.joins.length).toBe(joinsBefore + 1);
  conn.stop();
});
