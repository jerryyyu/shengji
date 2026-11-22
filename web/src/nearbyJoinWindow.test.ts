// The joiner's page at a nearby table when the host's window runs out
// during a retry, end to end: the page's Connection (ws.ts) and the join's
// store (nearbyJoin.ts) over NearbySockets on the fake transport, with the
// game server's sockets counted. That retry closing ends the table, and the
// page goes back to exactly one game-server socket: the close that ended
// the table schedules no second one on the restored transport.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { HOST_WINDOW_MS, NearbyJoinStore } from "./nearbyJoin";
import { nearbyLogLines } from "./nearbyLog";
import { realClock } from "./offline/server/clock";
import { setNearbyForTests } from "./offline/server/nearby/flag";
import { NearbyHost } from "./offline/server/nearby/host";
import { NearbySocket } from "./offline/server/nearby/socket";
import { FakeTransport } from "./offline/server/nearby/transport";
import { LocalServer, type LocalRoom } from "./offline/server/server";
import { LocalSocket } from "./offline/server/socket";

// a game-server socket that opens only when the test answers it, so no
// server on this machine reaches the page
class GameSocket {
  static OPEN = 1;
  /** Every game-server socket the page has made. */
  static made: GameSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage = null;
  onclose: (() => void) | null = null;
  onerror = null;
  constructor() { GameSocket.made.push(this); }
  send(): void {}
  close(): void { this.readyState = 3; }
  /** The game server answers: the socket opens. */
  answer(): void {
    this.readyState = 1;
    this.onopen?.();
  }
}
(globalThis as unknown as { WebSocket: unknown }).WebSocket = GameSocket;

beforeEach(() => {
  setNearbyForTests(true);
  localStorage.clear();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"] });
});
afterEach(() => {
  vi.useRealTimers();
  setNearbyForTests(null);
});

it("a retry under way when the host's window runs out, closing, ends the table on exactly one restored game-server socket", async () => {
  const fake = new FakeTransport(realClock, 0.05);
  const server = new LocalServer({ clock: realClock, seed: () => 5 });
  const host = new LocalSocket(server);
  host.onopen = () => host.send(JSON.stringify({ type: "create_room", nearby: true, name: "Host" }));
  await vi.advanceTimersByTimeAsync(100);
  const room: LocalRoom = [...server.rooms.values()][0];
  await new NearbyHost(server, room).start(fake);
  const { conn } = await import("./ws");
  const store = new NearbyJoinStore({
    conn,
    socketFor: async (code, onState, greet) => () => new NearbySocket(fake, code, onState, realClock, greet) as unknown as WebSocket,
    watchPath: async () => () => {},
    offline: () => true,
    setOffline: () => {},
    setSession: () => {},
    allowed: () => {},
    refused: () => {},
    onVisible: () => {},
  });
  conn.start();
  store.open(room.code, "Mei");
  await vi.advanceTimersByTimeAsync(1000);
  store.join();
  await vi.advanceTimersByTimeAsync(1000);
  expect(store.seated).toBe(true);
  host.send(JSON.stringify({ type: "table_start_bots" }));
  await vi.advanceTimersByTimeAsync(2000);
  const before = GameSocket.made.length;

  // the host's phone is out of reach: each resume attempt hangs to its own limit
  fake.network(false, room.code, "stall");
  for (let i = 0; i < (HOST_WINDOW_MS + 40_000) / 100 && !store.hostLeft; i++) await vi.advanceTimersByTimeAsync(100);
  expect(store.hostLeft).toBe(true);
  const lines = nearbyLogLines().map((l) => l.text);
  expect(lines).toContain("the host's window is over during an attempt: that attempt decides");
  expect(lines).toContain("the attempt past the host's window closed: the table is over");

  const remote = () => GameSocket.made.slice(before);
  expect(remote()).toHaveLength(1);
  remote()[0].answer();
  expect(conn.status).toBe("open");
  // through the game server's whole backoff: no second socket replaces it
  await vi.advanceTimersByTimeAsync(10_000);
  expect(remote()).toHaveLength(1);
  expect(remote()[0].readyState).toBe(1);
  expect(conn.status).toBe("open");
  conn.stop();
});
