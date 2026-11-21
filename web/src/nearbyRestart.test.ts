// A restarted joiner's app on the real host, end to end on the fake
// transport: the joiner's store (nearbyJoin.ts) over NearbySockets, the
// host's room on the in-page server. The seat token is kept on the phone by
// the table's code, so a fresh store, as after iOS ended the app, takes the
// same seat and hand back by it through the code box's join; a Leave, or a
// table it never sat at, joins as a newcomer.
import { afterEach, beforeEach, expect, it } from "vitest";
import { NearbyJoinStore, SEATS_KEY, type NearbyJoinDeps } from "./nearbyJoin";
import { nearbyLogLines } from "./nearbyLog";
import { NearbySocket } from "./offline/server/nearby/socket";
import { NearbyTable, type Frame } from "./offline/server/nearby/testkit";
import type { ConnStatus } from "./ws";

type Msg = Record<string, unknown> & { type: string };

/** One phone's app: a fresh store, as at its launch, on the table's clock. */
function phone(t: NearbyTable) {
  const subs = new Set<(m: Msg) => void>();
  const stats = new Set<(s: ConnStatus) => void>();
  const frames: Frame[] = [];
  const sent: Msg[] = [];
  let sock: NearbySocket | null = null;
  const status = (s: ConnStatus) => stats.forEach((f) => f(s));
  const deps: NearbyJoinDeps = {
    conn: {
      send: ((m: Msg) => {
        if (!sock || sock.readyState !== NearbySocket.OPEN) return false;
        sent.push(m);
        sock.send(JSON.stringify(m));
        return true;
      }) as never,
      subscribe: ((fn: (m: Msg) => void) => { subs.add(fn); return () => {}; }) as never,
      subscribeStatus: ((fn: (s: ConnStatus) => void) => { stats.add(fn); return () => {}; }) as never,
      useNearby: (make) => {
        const s = make() as unknown as NearbySocket;
        sock = s;
        s.onopen = () => status("open");
        s.onmessage = (ev) => {
          const m = JSON.parse(ev.data as string) as Msg;
          frames.push(m);
          subs.forEach((f) => f(m));
        };
        s.onclose = () => { if (sock === s) status("closed"); };
      },
      leaveNearby: () => { const s = sock; sock = null; s?.close(); },
      leaveToLobby: () => {
        sock?.send(JSON.stringify({ type: "table_leave" }));
        subs.forEach((f) => f({ type: "left" }));
      },
      reconnect: () => {},
    },
    socketFor: async (code, onState, greet) => () => new NearbySocket(t.fake, code, onState, t.clock, greet) as unknown as WebSocket,
    watchPath: async () => () => {},
    offline: () => true,
    setOffline: () => {},
    setSession: () => {},
    allowed: () => {},
    refused: () => {},
    onVisible: () => {},
  };
  const store = new NearbyJoinStore(deps);
  return {
    store, frames, sent,
    /** The app is ended by the system: its link just stops, nothing is sent. */
    kill: () => { const s = sock; sock = null; s?.close(); },
    state: () => [...frames].reverse().find((f) => f.type === "state"),
  };
}

async function seatedPhone(t: NearbyTable, name = "Mei") {
  const p = phone(t);
  p.store.open(t.code, name);
  await t.settle(() => p.store.view?.step === "panel");
  p.store.join();
  await t.settle(() => p.store.seated && p.state() !== undefined);
  return p;
}

async function started(): Promise<NearbyTable> {
  const t = new NearbyTable(21, 1);
  await t.open();
  await t.join("P1");
  t.send(t.host, { type: "table_start_bots" });
  await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined) && t.room!.round!.phase === "play");
  return t;
}

const handOf = (st: Frame | undefined) => ((st?.hand ?? []) as { code: string }[]).map((c) => c.code).sort();

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

it("a restarted app takes the same seat and hand back by its kept token", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  const seat = before.state()!.you as number;
  const hand = handOf(before.state());
  expect(hand.length).toBeGreaterThan(0);
  before.kill();
  await t.advance(1);
  // the app again, from its launch: the code box's join with the code
  const after = await seatedPhone(t);
  // the seat picker offered only the bots' seats (Mei's is held for her);
  // the join's kept token took hers back instead
  const join = after.sent.find((m) => m.type === "table_join")!;
  expect(typeof join.token).toBe("string");
  expect(join.seat).not.toBe(seat);
  expect(after.state()!.you).toBe(seat);
  expect(handOf(after.state())).toEqual(hand);
  expect(t.room!.seats[seat].name).toBe("Mei");
  expect(t.room!.seats[seat].isBot).toBe(false);
  // the kept value never reaches the log
  const kept = JSON.parse(localStorage.getItem(SEATS_KEY)!) as Record<string, { token: string }>;
  const token = kept[t.code].token;
  expect(nearbyLogLines().some((l) => l.text.includes(token))).toBe(false);
});

it("after a Leave, the app's next join is a newcomer's", async () => {
  const t = await started();
  const before = await seatedPhone(t);
  before.store.leave();
  await t.advance(5);
  expect(localStorage.getItem(SEATS_KEY)).toBeNull();
  const after = await seatedPhone(t);
  const join = after.sent.find((m) => m.type === "table_join")!;
  expect(join.token).toBeUndefined();
  // a newcomer, as the seat picker offered: the seat left by choice is a bot's at once
  expect(after.state()!.you).toBe(join.seat);
});
