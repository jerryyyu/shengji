// The page's Connection on a nearby link, end to end on the fake transport
// and real timers (faked): ws.ts's connect deadline is the game server's, so
// a seat's resume whose hello is slow to be answered on a link that is up
// keeps that one link, and the seat is back as soon as the answer lands.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { realClock } from "./offline/server/clock";
import { setNearbyForTests } from "./offline/server/nearby/flag";
import { NearbyHost } from "./offline/server/nearby/host";
import { NearbySocket } from "./offline/server/nearby/socket";
import { FakeTransport } from "./offline/server/nearby/transport";
import { LocalServer } from "./offline/server/server";
import { LocalSocket } from "./offline/server/socket";

type Msg = Record<string, unknown> & { type: string };

beforeEach(() => {
  setNearbyForTests(true);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"] });
});
afterEach(() => {
  vi.useRealTimers();
  setNearbyForTests(null);
});

/** A host page's nearby table on `fake`, with a game on. */
async function table(fake: FakeTransport): Promise<{ server: LocalServer; code: string; host: LocalSocket }> {
  const server = new LocalServer({ clock: realClock, seed: () => 11 });
  const host = new LocalSocket(server);
  host.onopen = () => host.send(JSON.stringify({ type: "create_room", nearby: true, name: "Host" }));
  await vi.advanceTimersByTimeAsync(100);
  const room = [...server.rooms.values()][0];
  await new NearbyHost(server, room).start(fake);
  return { server, code: room.code, host };
}

it("a resume whose hello is answered at 5.5 s keeps its one link and is back by 5.7 s", async () => {
  const fake = new FakeTransport(realClock, 0.05);
  const { code, host } = await table(fake);
  const { conn } = await import("./ws");
  let token: string | null = null;
  let seated = false;
  const made: number[] = [];
  conn.subscribe((m) => {
    const msg = m as unknown as Msg;
    if (msg.type === "resume") token = msg.token as string;
    if (msg.type === "room" || msg.type === "state") seated = true;
  });
  const statuses: { at: number; s: string }[] = [];
  conn.subscribeStatus((s) => statuses.push({ at: Date.now(), s }));
  const greet = () => (seated && token ? { type: "table_join", code, name: "Mei", token } : null);
  conn.start();
  conn.useNearby(() => {
    made.push(Date.now());
    return new NearbySocket(fake, code, null, realClock, greet) as unknown as WebSocket;
  });
  await vi.advanceTimersByTimeAsync(10);
  conn.send({ type: "table_join", code, name: "Mei", token: null } as never);
  await vi.advanceTimersByTimeAsync(1000);
  expect(seated).toBe(true);
  host.send(JSON.stringify({ type: "table_start_bots" }));
  await vi.advanceTimersByTimeAsync(2000);
  expect(conn.status).toBe("open");
  // the link drops; the next one is slow: each frame takes 2.75 s, so the
  // host's answer to its hello lands 5.5 s after it was made
  fake.drop(code, fake.peersOf(code)[0]);
  await vi.advanceTimersByTimeAsync(100);
  expect(conn.status).not.toBe("open");
  fake.delay = 2.75;
  const before = made.length;
  await vi.advanceTimersByTimeAsync(1000);
  expect(made.length).toBe(before + 1);
  const at = made[before];
  await vi.advanceTimersByTimeAsync(5700 - (Date.now() - at));
  expect(made.length, "one link").toBe(before + 1);
  const back = statuses.filter((x) => x.s === "open" && x.at >= at);
  expect(back.length).toBeGreaterThan(0);
  expect(back[0].at - at).toBeLessThan(5700);
  conn.stop();
});
