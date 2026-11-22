// The host page's Nearby switch on the real in-page server and the fake
// transport: its Leave (the switch off, or the game menu's Leave) tells every
// joiner the table is over before the links stop, and a switch turned off
// while the listener is still on its way leaves no listener behind.
import { afterAll, beforeAll, expect, it } from "vitest";
import * as offline from "./offline/server";
import { realClock } from "./offline/server/clock";
import { NEARBY_COPY } from "./offline/server/nearby/copy";
import { NEARBY_V } from "./offline/server/nearby/protocol";
import { FakeTransport, NearbyError, type NearbyTransport } from "./offline/server/nearby/transport";
import { NearbyHostSession } from "./nearbySession";
import { conn } from "./ws";

// the game server's socket never opens here: the page plays on the device
class NoSocket {
  static OPEN = 1;
  readyState = 0;
  onopen = null; onmessage = null; onclose = null; onerror = null;
  send(): void {}
  close(): void {}
}
(globalThis as unknown as { WebSocket: unknown }).WebSocket = NoSocket;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function until(ok: () => boolean, ms = 4000): Promise<void> {
  const end = Date.now() + ms;
  while (!ok()) {
    if (Date.now() > end) throw new Error("timed out");
    await sleep(10);
  }
}

let fake: FakeTransport;
beforeAll(async () => {
  fake = new FakeTransport(realClock);
  offline.setNearbyTransportForTests(fake);
  conn.start();
  await conn.useLocalServer();
  await until(() => conn.status === "open");
});
afterAll(() => {
  conn.stop();
  offline.setNearbyTransportForTests(null);
});

const nearbyCode = () => [...offline.localServer().rooms.values()].filter((r) => r.nearby && !r.closed).pop()!.code;

async function seatedJoiner(code: string, via: NearbyTransport = fake) {
  const j = { frames: [] as Record<string, unknown>[], closed: false };
  const link = await via.join(code, {
    message: (x) => j.frames.push(JSON.parse(x) as Record<string, unknown>), closed: () => { j.closed = true; }, state: () => {},
  });
  await sleep(20);
  link.send(JSON.stringify({ type: "nearby_hello", nearby_v: NEARBY_V, name: "Mei", token: null }));
  await until(() => j.frames.some((f) => f.type === "room"));
  return j;
}

async function hostOn(session: NearbyHostSession): Promise<string> {
  session.turnOn("Host");
  await until(() => session.view.phase === "on");
  return nearbyCode();
}

it("the switch off tells every joiner the host left before their links stop", async () => {
  const session = new NearbyHostSession(async () => offline);
  const code = await hostOn(session);
  const joiners = [await seatedJoiner(code), await seatedJoiner(code)];
  session.turnOff();
  await until(() => joiners.every((j) => j.closed));
  for (const j of joiners) {
    expect(j.frames.filter((f) => f.type === "left")).toEqual([{ type: "left", reason: "host_left", message: NEARBY_COPY.hostLeft }]);
  }
  await expect(fake.join(code, { message: () => {}, closed: () => {}, state: () => {} })).rejects.toBeInstanceOf(NearbyError);
});

it("the game menu's Leave does the same", async () => {
  const session = new NearbyHostSession(async () => offline);
  const code = await hostOn(session);
  const j = await seatedJoiner(code);
  conn.leaveToLobby();
  await until(() => j.closed);
  expect(j.frames.filter((f) => f.type === "left")).toEqual([{ type: "left", reason: "host_left", message: NEARBY_COPY.hostLeft }]);
  expect(session.view.phase).toBe("off");
});

it("the switch off while the listener is on its way leaves no listener up", async () => {
  let release: () => void = () => {};
  const slow: NearbyTransport = {
    host: async (code, handlers) => {
      await new Promise<void>((r) => { release = r; });
      return fake.host(code, handlers);
    },
    join: (code, handlers) => fake.join(code, handlers),
  };
  offline.setNearbyTransportForTests(slow);
  try {
    const session = new NearbyHostSession(async () => offline);
    session.turnOn("Host");
    await until(() => session.view.phase === "starting" && offline.localServer().rooms.size > 0);
    await sleep(50);
    const code = nearbyCode();
    session.turnOff();
    await sleep(50);
    release();
    await sleep(100);
    await expect(fake.join(code, { message: () => {}, closed: () => {}, state: () => {} })).rejects.toBeInstanceOf(NearbyError);
    expect(session.view.phase).toBe("off");
  } finally {
    offline.setNearbyTransportForTests(fake);
  }
});

it("the switch on makes the nearby table at the offline table's Bots", async () => {
  const session = new NearbyHostSession(async () => offline);
  session.turnOn("Host", "advanced");
  await until(() => session.view.phase === "on");
  const room = [...offline.localServer().rooms.values()].filter((r) => r.nearby && !r.closed).pop()!;
  expect(room.botLevel).toBe("advanced");
  session.turnOff();
});
