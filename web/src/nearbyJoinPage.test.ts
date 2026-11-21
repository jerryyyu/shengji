// The joiner's page at a nearby table, end to end: the page's Connection
// (ws.ts) and the join's store (nearbyJoin.ts) over NearbySockets on the
// fake transport, real timers faked.
// - A Leave tapped with the link down, or one whose link goes before the
//   host's answer, goes out on the next link as it opens, so the bot covers
//   the seat at once rather than after a dropped seat's 60 s; and the page,
//   back in the lobby, never sees that link's frames of the seat it left.
// - A resume the table refuses (it no longer knows the token) goes to the
//   seat picker, forgets the token and never loops.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NearbyJoinStore, SEATS_KEY } from "./nearbyJoin";
import { realClock } from "./offline/server/clock";
import { setNearbyForTests } from "./offline/server/nearby/flag";
import { NearbyHost } from "./offline/server/nearby/host";
import { NearbySocket } from "./offline/server/nearby/socket";
import { FakeTransport } from "./offline/server/nearby/transport";
import { LocalServer, type LocalRoom } from "./offline/server/server";
import { LocalSocket } from "./offline/server/socket";

type Msg = Record<string, unknown> & { type: string };

beforeEach(() => {
  setNearbyForTests(true);
  localStorage.clear();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"] });
});
afterEach(() => {
  vi.useRealTimers();
  setNearbyForTests(null);
});

async function seatedJoiner() {
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
    socketFor: async (code, onState, greet) => () => {
      links += 1;
      return new NearbySocket(fake, code, onState, realClock, greet) as unknown as WebSocket;
    },
    watchPath: async () => () => {},
    offline: () => true,
    setOffline: () => {},
    setSession: () => {},
    allowed: () => {},
    refused: () => {},
    onVisible: () => {},
  });
  const seen: Msg[] = [];
  let links = 0;
  conn.subscribe((m) => { seen.push(m as unknown as Msg); });
  conn.start();
  store.open(room.code, "Mei");
  await vi.advanceTimersByTimeAsync(1000);
  expect(store.view?.step).toBe("panel");
  store.join();
  await vi.advanceTimersByTimeAsync(1000);
  expect(store.seated).toBe(true);
  host.send(JSON.stringify({ type: "table_start_bots" }));
  await vi.advanceTimersByTimeAsync(2000);
  const seat = room.seats.find((s) => s.name !== "Host" && !s.isBot)!;
  expect(seat.connected).toBe(true);
  return { fake, server, room, store, conn, seen, seat, links: () => links };
}

it("a Leave tapped while the link is down: the next link carries it, and the bot covers within 5 s", async () => {
  const { fake, server, room, store, conn, seen, seat } = await seatedJoiner();
  fake.network(false, room.code);
  await vi.advanceTimersByTimeAsync(3000);
  expect(conn.status).not.toBe("open");
  expect(seat.connected).toBe(false);
  store.leave();
  const after = seen.length;
  // the page is back in the lobby at once
  expect(store.view).toBeNull();
  await vi.advanceTimersByTimeAsync(8000);
  expect(seat.leftByChoice).toBe(false);
  fake.network(true);
  const back = Date.now();
  for (let i = 0; i < 50 && !seat.leftByChoice; i++) await vi.advanceTimersByTimeAsync(100);
  expect(seat.leftByChoice).toBe(true);
  expect(Date.now() - back).toBeLessThan(5000);
  expect(server.drives(room, room.seats.indexOf(seat))).toBe(true);
  await vi.advanceTimersByTimeAsync(5000);
  // the link is ended and the seat stays left; the page saw none of the
  // resumed seat's frames
  expect(seat.connected).toBe(false);
  expect(store.seated).toBe(false);
  expect(seen.slice(after).filter((m) => m.type === "state" || m.type === "room")).toHaveLength(0);
  conn.stop();
});

it("a Leave whose link goes before the host's answer is sent again on the next link", async () => {
  const { fake, server, room, store, conn, seen, seat } = await seatedJoiner();
  // the joiner's frames stop reaching the host: the Leave is lost
  fake.lose(fake.peersOf(room.code)[0]);
  store.leave();
  const after = seen.length;
  const at = Date.now();
  for (let i = 0; i < 200 && !seat.leftByChoice; i++) await vi.advanceTimersByTimeAsync(100);
  expect(seat.leftByChoice).toBe(true);
  // the stuck link's few seconds, then one resume
  expect(Date.now() - at).toBeLessThan(10_000);
  expect(server.drives(room, room.seats.indexOf(seat))).toBe(true);
  await vi.advanceTimersByTimeAsync(5000);
  expect(seat.connected).toBe(false);
  expect(store.seated).toBe(false);
  expect(seen.slice(after).filter((m) => m.type === "state" || m.type === "room")).toHaveLength(0);
  conn.stop();
});

it("a resume the table no longer knows: the seat picker, the token forgotten, no loop and no seat taken", async () => {
  const { fake, room, store, conn, seat, links } = await seatedJoiner();
  expect(localStorage.getItem(SEATS_KEY)).toContain(room.code);
  // the table has given the seat to someone else meanwhile
  seat.token = "someone-else";
  const owners = room.seats.map((s) => `${s.name}:${s.isBot}`);
  fake.drop(room.code, fake.peersOf(room.code)[0]);
  await vi.advanceTimersByTimeAsync(3000);
  expect(store.seated).toBe(false);
  expect(store.view?.step).toBe("panel");
  expect(store.view?.peek?.in_game).toBe(true);
  expect(localStorage.getItem(SEATS_KEY)).toBeNull();
  // no seat changed hands without the player's pick
  expect(room.seats.map((s) => `${s.name}:${s.isBot}`)).toEqual(owners);
  const made = links();
  await vi.advanceTimersByTimeAsync(20_000);
  expect(links()).toBe(made);
  expect(store.view?.step).toBe("panel");
  expect(store.hostLeft).toBe(false);
  conn.stop();
});
