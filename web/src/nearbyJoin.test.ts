// The nearby joiner's flow on a fake socket: look, the seat picker, Join,
// a denial that no later not-found replaces, one automatic retry before not
// found, the retry on coming back from Settings, the rejoin by token after a
// drop, and the end screen once the host's window has passed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HOST_WINDOW_MS, NearbyJoinStore, type NearbyJoinDeps } from "./codeJoin";
import type { LinkState } from "./offline/server/nearby/transport";
import type { ConnStatus } from "./ws";

type Msg = Record<string, unknown> & { type: string };

function harness() {
  const sent: Msg[] = [];
  let onMsg: (m: Msg) => void = () => {};
  let onStatus: (s: ConnStatus) => void = () => {};
  let onState: (s: LinkState) => void = () => {};
  let visible: () => void = () => {};
  const calls = { useNearby: 0, leaveNearby: 0, leaveToLobby: 0, offline: [] as boolean[], session: [] as boolean[] };
  const deps: NearbyJoinDeps = {
    conn: {
      send: ((m: Msg) => { sent.push(m); return true; }) as never,
      subscribe: ((fn: (m: Msg) => void) => { onMsg = fn; return () => {}; }) as never,
      subscribeStatus: ((fn: (s: ConnStatus) => void) => { onStatus = fn; return () => {}; }) as never,
      useNearby: () => { calls.useNearby += 1; },
      leaveNearby: () => { calls.leaveNearby += 1; },
      leaveToLobby: () => { calls.leaveToLobby += 1; },
    },
    socketFor: async (_code, fn) => { onState = fn; return () => ({}) as WebSocket; },
    offline: () => true,
    setOffline: (on) => { calls.offline.push(on); },
    setSession: (on) => { calls.session.push(on); },
    allowed: () => {},
    token: () => "tok-1",
    onVisible: (fn) => { visible = fn; },
  };
  const store = new NearbyJoinStore(deps);
  return {
    store, sent, calls,
    msg: (m: Msg) => onMsg(m),
    status: (s: ConnStatus) => onStatus(s),
    state: (s: LinkState) => onState(s),
    visible: () => visible(),
  };
}

const flush = () => vi.advanceTimersByTimeAsync(0);
const seats = { type: "room_seats", room: "K7Q2MX", in_game: false, full: false,
  seats: [{ seat: 0, name: "Jerry", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null }] };

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("the nearby join", () => {
  it("a denial stays on the code box: neither a late not-found nor the look's limit replaces it", async () => {
    const h = harness();
    h.store.open("K7Q2MX", "Mei");
    await flush();
    expect(h.store.view?.step).toBe("looking");
    h.state("denied");
    expect(h.store.view).toMatchObject({ code: "K7Q2MX", step: "denied" });
    h.state("notFound");
    await vi.advanceTimersByTimeAsync(40_000);
    expect(h.store.view?.step).toBe("denied");
    expect(h.calls.leaveNearby).toBe(1);
  });

  it("back from Settings, the join looks again on its own with the kept code", async () => {
    const h = harness();
    h.store.open("K7Q2MX", "Mei");
    await flush();
    h.state("denied");
    h.visible();
    await flush();
    expect(h.store.view).toMatchObject({ code: "K7Q2MX", step: "looking" });
    expect(h.calls.useNearby).toBe(2);
  });

  it("one miss is looked at again before not found; Try again looks once more", async () => {
    const h = harness();
    h.store.open("K7Q2MX", "Mei");
    await flush();
    h.state("notFound");
    expect(h.store.view?.step).toBe("looking");
    h.state("notFound");
    expect(h.store.view?.step).toBe("notFound");
    h.store.again();
    await flush();
    expect(h.store.view?.step).toBe("looking");
  });

  it("shows the seats, starts on the host's partner seat, and joins the one picked", async () => {
    const h = harness();
    h.store.open("K7Q2MX", "Mei");
    await flush();
    h.status("open");
    expect(h.sent).toEqual([{ type: "table_peek", code: "K7Q2MX" }]);
    h.msg(seats);
    expect(h.store.view).toMatchObject({ step: "panel", seat: 2 });
    h.store.pick(0);
    expect(h.store.view?.seat).toBe(2);
    h.store.pick(3);
    h.store.join();
    expect(h.sent[1]).toEqual({ type: "table_join", code: "K7Q2MX", name: "Mei", seat: 3 });
    h.msg({ type: "room", room: "K7Q2MX" });
    expect(h.store.view).toBeNull();
    expect(h.store.seated).toBe(true);
  });

  it("a dropped seat rejoins by token, and after the host's window the end screen is up", async () => {
    const h = harness();
    h.store.open("K7Q2MX", "Mei");
    await flush();
    h.status("open");
    h.msg(seats);
    h.store.join();
    h.msg({ type: "room", room: "K7Q2MX" });
    h.status("closed");
    await vi.advanceTimersByTimeAsync(20_000);
    h.status("open");
    expect(h.sent[h.sent.length - 1]).toEqual({ type: "table_join", code: "K7Q2MX", name: "Mei", token: "tok-1" });
    h.msg({ type: "state", room: "K7Q2MX" });
    // back in time: the window starts over at the next drop
    h.status("closed");
    await vi.advanceTimersByTimeAsync(HOST_WINDOW_MS - 1000);
    expect(h.store.hostLeft).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.store.hostLeft).toBe(true);
    expect(h.calls.leaveNearby).toBe(1);
    expect(h.calls.offline[h.calls.offline.length - 1]).toBe(true);
    h.store.cancel();
    expect(h.store.hostLeft).toBe(false);
  });

  it("the host's own end of the table ends the join", async () => {
    const h = harness();
    h.store.open("K7Q2MX", "Mei");
    await flush();
    h.status("open");
    h.msg(seats);
    h.store.join();
    h.msg({ type: "room", room: "K7Q2MX" });
    h.msg({ type: "left", reason: "host_left" });
    expect(h.store.seated).toBe(false);
    expect(h.calls.leaveNearby).toBe(1);
    expect(h.calls.session).toEqual([true, false]);
  });
});
