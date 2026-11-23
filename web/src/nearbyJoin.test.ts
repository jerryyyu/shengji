// The nearby joiner's flow on a fake socket: look, the seat picker, Join,
// a denial that no later not-found replaces, one automatic retry before not
// found, the retry on coming back from Settings, the rejoin by token after a
// drop, the end screen once the host's window has passed, and the seat token
// kept on the phone by the table's code for a restarted app's join.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JOIN_TIMEOUT_MS } from "./codeJoin";
import {
  ATTEMPT_MAX_MS, HOST_WINDOW_MS, keepSeatToken, keptSeatAt, keptSeatToken, LEAVE_LINK_MS, LOOK_LIMIT_MS, NearbyJoinStore, SEAT_KEEP_MAX, SEAT_KEEP_MS,
  SEATS_KEY, type NearbyJoinDeps,
} from "./nearbyJoin";
import { nearbyLogLines } from "./nearbyLog";
import { LIMITS } from "./offline/server/nearby/protocol";
import type { LinkState } from "./offline/server/nearby/transport";
import type { ConnStatus } from "./ws";

type Msg = Record<string, unknown> & { type: string };

function harness() {
  const sent: Msg[] = [];
  let onMsg: (m: Msg) => void = () => {};
  let onStatus: (s: ConnStatus) => void = () => {};
  let onState: (s: LinkState, detail?: string) => void = () => {};
  let visible: () => void = () => {};
  let greet: () => Record<string, unknown> | null = () => null;
  const paths = new Set<(up: boolean) => void>();
  const calls = { useNearby: 0, leaveNearby: 0, leaveToLobby: 0, refused: 0, reconnect: 0, offline: [] as boolean[], session: [] as boolean[] };
  const deps: NearbyJoinDeps = {
    conn: {
      send: ((m: Msg) => { sent.push(m); return true; }) as never,
      subscribe: ((fn: (m: Msg) => void) => { onMsg = fn; return () => {}; }) as never,
      subscribeStatus: ((fn: (s: ConnStatus) => void) => { onStatus = fn; return () => {}; }) as never,
      useNearby: () => { calls.useNearby += 1; },
      leaveNearby: () => { calls.leaveNearby += 1; },
      // as ws.ts: the page's own `left` at once, before the host answers
      leaveToLobby: () => { calls.leaveToLobby += 1; onMsg({ type: "left" }); },
      reconnect: () => { calls.reconnect += 1; },
      nearbyLeaveOwed: () => false,
    },
    socketFor: async (_code, fn, hello) => { onState = fn; greet = hello; return () => ({}) as WebSocket; },
    watchPath: async (fn) => { paths.add(fn); return () => { paths.delete(fn); }; },
    offline: () => true,
    setOffline: (on) => { calls.offline.push(on); },
    setSession: (on) => { calls.session.push(on); },
    allowed: () => {},
    refused: () => { calls.refused += 1; },
    onVisible: (fn) => { visible = fn; },
  };
  const store = new NearbyJoinStore(deps);
  return {
    store, sent, calls,
    msg: (m: Msg) => onMsg(m),
    status: (s: ConnStatus) => onStatus(s),
    state: (s: LinkState, detail?: string) => onState(s, detail),
    visible: () => visible(),
    /** The hello a new link would resume with now. */
    greet: () => greet(),
    path: (up: boolean) => { for (const fn of [...paths]) fn(up); },
    watching: () => paths.size,
  };
}

const flush = () => vi.advanceTimersByTimeAsync(0);
const seats = { type: "room_seats", room: "K7Q2M", in_game: false, full: false,
  seats: [{ seat: 0, name: "Jerry", is_bot: false, connected: true, team: 0, claimable: false, controller: "human", reserved_secs: null }] };

beforeEach(() => { vi.useFakeTimers(); localStorage.clear(); });
afterEach(() => { vi.useRealTimers(); localStorage.clear(); });

async function seated() {
  const h = harness();
  h.store.open("K7Q2M", "Mei");
  await flush();
  h.status("open");
  h.msg(seats);
  h.store.join();
  h.msg({ type: "resume", token: "tok-9", gen: 1 });
  h.msg({ type: "room", room: "K7Q2M" });
  expect(h.store.seated).toBe(true);
  return h;
}

describe("the nearby join", () => {
  it("a denial stays on the code box: neither a late not-found nor the look's limit replaces it", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    expect(h.store.view?.step).toBe("looking");
    h.state("denied");
    expect(h.store.view).toMatchObject({ code: "K7Q2M", step: "denied" });
    h.state("notFound");
    await vi.advanceTimersByTimeAsync(40_000);
    expect(h.store.view?.step).toBe("denied");
    expect(h.calls.leaveNearby).toBe(1);
  });

  it("back from Settings, the join looks again on its own with the kept code", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.state("denied");
    h.visible();
    await flush();
    expect(h.store.view).toMatchObject({ code: "K7Q2M", step: "looking" });
    expect(h.calls.useNearby).toBe(2);
  });

  it("one miss is looked at again before not found; Try again looks once more", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.state("notFound");
    expect(h.store.view?.step).toBe("looking");
    h.state("notFound");
    expect(h.store.view?.step).toBe("notFound");
    h.store.again();
    await flush();
    expect(h.store.view?.step).toBe("looking");
  });

  it("the panel's one line: looking, then connecting once the link is up, then the seats", async () => {
    const { fromNearbyJoin } = await import("./queue/nearbyModel");
    const { NEARBY_COPY } = await import("./offline/server/nearby/copy");
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    expect(fromNearbyJoin(h.store.view!).status?.text).toBe(NEARBY_COPY.browsing);
    h.status("open");
    expect(fromNearbyJoin(h.store.view!).status?.text).toBe(NEARBY_COPY.connecting);
    // the link dropped before the seats came: looking again
    h.status("closed");
    expect(fromNearbyJoin(h.store.view!).status?.text).toBe(NEARBY_COPY.browsing);
    h.status("open");
    h.msg({ ...seats });
    expect(h.store.view?.step).toBe("panel");
    expect(fromNearbyJoin(h.store.view!).status).toBeUndefined();
  });

  it("shows the seats, starts on the host's partner seat, and joins the one picked", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.status("open");
    expect(h.sent).toEqual([{ type: "table_peek", code: "K7Q2M" }]);
    h.msg(seats);
    expect(h.store.view).toMatchObject({ step: "panel", seat: 2 });
    h.store.pick(0);
    expect(h.store.view?.seat).toBe(2);
    h.store.pick(3);
    h.store.join();
    expect(h.sent[1]).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 3 });
    h.msg({ type: "room", room: "K7Q2M" });
    expect(h.store.view).toBeNull();
    expect(h.store.seated).toBe(true);
  });

  it("a dropped seat rejoins by token, and after the host's window the end screen is up", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.status("open");
    h.msg(seats);
    h.store.join();
    h.msg({ type: "resume", token: "tok-1", gen: 1 });
    h.msg({ type: "room", room: "K7Q2M" });
    h.status("closed");
    await vi.advanceTimersByTimeAsync(20_000);
    // the new link's hello is the resume; the socket opens once it is answered
    expect(h.greet()).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", token: "tok-1" });
    h.status("open");
    h.msg({ type: "state", room: "K7Q2M" });
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
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.status("open");
    h.msg(seats);
    h.store.join();
    h.msg({ type: "room", room: "K7Q2M" });
    h.msg({ type: "left", reason: "host_left" });
    expect(h.store.seated).toBe(false);
    expect(h.calls.leaveNearby).toBe(1);
    expect(h.calls.session).toEqual([true, false]);
  });

  it("a Leave keeps the link until the host answers by ending it, so the leave is not lost", async () => {
    const h = await seated();
    h.store.leave();
    expect(h.calls.leaveToLobby).toBe(1);
    // the page is back at once; the link waits for the host
    expect(h.store.view).toBeNull();
    await vi.advanceTimersByTimeAsync(500);
    expect(h.calls.leaveNearby).toBe(0);
    h.status("closed");
    await flush();
    expect(h.calls.leaveNearby).toBe(1);
    expect(h.store.seated).toBe(false);
    // and the reconnect a close would start never rejoins
    expect(h.greet()).toBeNull();
    h.status("open");
    expect(h.sent.filter((m) => m.type === "table_join")).toHaveLength(1);
  });

  it("a Leave the host never answers closes the link after a short wait; the game menu's Leave is the same", async () => {
    const h = await seated();
    h.store.leave();
    await vi.advanceTimersByTimeAsync(LEAVE_LINK_MS - 100);
    expect(h.calls.leaveNearby).toBe(0);
    await vi.advanceTimersByTimeAsync(200);
    expect(h.calls.leaveNearby).toBe(1);
    const g = await seated();
    // the menu's Leave is leaveToLobby, whose own `left` the store sees
    g.msg({ type: "left" });
    expect(g.calls.leaveNearby).toBe(0);
    await vi.advanceTimersByTimeAsync(LEAVE_LINK_MS + 100);
    expect(g.calls.leaveNearby).toBe(1);
  });

  it("the rejoin uses the table's token, and once the host ends the table storage holds nothing of it", async () => {
    const h = await seated();
    h.status("closed");
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.greet()).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", token: "tok-9" });
    h.status("open");
    h.msg({ type: "left", reason: "host_left" });
    const kept = Object.keys(localStorage).map((k) => `${k}=${localStorage.getItem(k)}`).join(";");
    expect(kept).not.toMatch(/K7Q2M|tok-9/);
  });

  it("a slow answer to the Local Network prompt is not read as no table nearby", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.state("waiting", "prompt");
    await vi.advanceTimersByTimeAsync(LOOK_LIMIT_MS * 3);
    expect(h.store.view?.step).toBe("looking");
    h.state("waiting", "active");
    await vi.advanceTimersByTimeAsync(LOOK_LIMIT_MS - 1000);
    expect(h.store.view?.step).toBe("looking");
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.store.view?.step).toBe("notFound");
  });

  it("a Join with no answer looks at the table again instead of spinning", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.status("open");
    h.msg(seats);
    h.store.join();
    expect(h.store.view?.step).toBe("joining");
    await vi.advanceTimersByTimeAsync(JOIN_TIMEOUT_MS + 100);
    expect(h.store.view?.step).toBe("looking");
    expect(h.sent[h.sent.length - 1]).toEqual({ type: "table_peek", code: "K7Q2M" });
    h.msg(seats);
    expect(h.store.view?.step).toBe("panel");
  });

  it("the panel's link dropping looks again once the link is back", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.status("open");
    h.msg(seats);
    h.status("closed");
    expect(h.store.view).toMatchObject({ step: "looking", peek: null });
    h.status("open");
    expect(h.sent.filter((m) => m.type === "table_peek")).toHaveLength(2);
  });

  it("only tables of another version: the code box asks for an update; a denial forgets the earlier grant", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    h.state("version");
    expect(h.store.view?.step).toBe("version");
    const d = harness();
    d.store.open("K7Q2M", "Mei");
    await flush();
    d.state("denied");
    expect(d.calls.refused).toBe(1);
  });
  it("before the seat, a new link has no resume hello: the panel peeks and joins on the open socket", async () => {
    const h = harness();
    h.store.open("K7Q2M", "Mei");
    await flush();
    expect(h.greet()).toBeNull();
  });

  it("the network back while the seat is not connected starts a fresh attempt at once", async () => {
    const h = await seated();
    expect(h.watching()).toBe(1);
    h.status("closed");
    h.path(false);
    expect(h.calls.reconnect).toBe(0);
    h.path(true);
    expect(h.calls.reconnect).toBe(1);
    // connected again: a path change is nothing to do
    h.status("open");
    h.path(true);
    expect(h.calls.reconnect).toBe(1);
  });

  it("the network back during an attempt under 2 s old keeps it; an older one is replaced", async () => {
    const h = await seated();
    h.status("closed");
    h.path(false);
    h.status("connecting");
    await vi.advanceTimersByTimeAsync(5);
    h.path(true);
    expect(h.calls.reconnect).toBe(0);
    await vi.advanceTimersByTimeAsync(2100);
    h.path(true);
    expect(h.calls.reconnect).toBe(1);
  });

  it("a network down past the host's window ends on the host-left screen, not a stuck pill", async () => {
    const h = await seated();
    h.status("closed");
    // attempt after attempt fails while the network is down
    for (let t = 0; t < HOST_WINDOW_MS - 2000; t += 2000) {
      h.status("connecting");
      await vi.advanceTimersByTimeAsync(1000);
      h.status("closed");
      await vi.advanceTimersByTimeAsync(1000);
    }
    expect(h.store.hostLeft).toBe(false);
    await vi.advanceTimersByTimeAsync(3000);
    expect(h.store.hostLeft).toBe(true);
    expect(h.calls.leaveNearby).toBe(1);
    expect(h.watching()).toBe(0);
  });

  it("the host's window running out during an attempt lets that attempt finish", async () => {
    const h = await seated();
    h.status("closed");
    await vi.advanceTimersByTimeAsync(HOST_WINDOW_MS - 500);
    // the attempt that finds the host
    h.status("connecting");
    // the window runs out mid-attempt
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.store.hostLeft).toBe(false);
    expect(h.calls.leaveNearby).toBe(0);
    expect(h.greet()).toMatchObject({ token: "tok-9" });
    h.status("open");
    h.msg({ type: "state", room: "K7Q2M" });
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
    // seated again: the next drop has the whole window
    h.status("closed");
    await vi.advanceTimersByTimeAsync(HOST_WINDOW_MS - 1000);
    expect(h.store.hostLeft).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.store.hostLeft).toBe(true);
  });

  it("that attempt closing ends the table at once; one that never finishes ends it by its own limit", async () => {
    const h = await seated();
    h.status("closed");
    await vi.advanceTimersByTimeAsync(HOST_WINDOW_MS - 500);
    h.status("connecting");
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.store.hostLeft).toBe(false);
    h.status("closed");
    expect(h.store.hostLeft).toBe(true);
    expect(h.calls.leaveNearby).toBe(1);
    expect(keptSeatToken("K7Q2M")).toBeNull();

    const g = await seated();
    g.status("closed");
    await vi.advanceTimersByTimeAsync(HOST_WINDOW_MS - 500);
    g.status("connecting");
    await vi.advanceTimersByTimeAsync(ATTEMPT_MAX_MS - 1000);
    expect(g.store.hostLeft).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(g.store.hostLeft).toBe(true);
    expect(g.calls.leaveNearby).toBe(1);
    // the limit covers the socket's longest resume attempt
    expect(ATTEMPT_MAX_MS).toBeGreaterThanOrEqual((LIMITS.linkSeconds + LIMITS.silentSeconds) * 1000);
  });
});

describe("the seat token kept on the phone", () => {
  /** A fresh store (the app again after iOS ended it) at the panel for `code`. */
  async function atPanel(code = "K7Q2M") {
    const h = harness();
    h.store.open(code, "Mei");
    await flush();
    h.status("open");
    h.msg({ ...seats, room: code });
    expect(h.store.view?.step).toBe("panel");
    return h;
  }
  const joinSent = (h: ReturnType<typeof harness>) => h.sent.find((m) => m.type === "table_join")!;

  it("is kept when it arrives, and a restarted app's join sends it", async () => {
    const h = await seated();
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
    const again = await atPanel();
    again.store.join();
    expect(joinSent(again)).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 2, token: "tok-9" });
    expect(h.store.seated).toBe(true);
  });

  it("a Leave forgets it, so the next join is a newcomer's; the menu's Leave the same", async () => {
    const h = await seated();
    h.store.leave();
    expect(keptSeatToken("K7Q2M")).toBeNull();
    expect(localStorage.getItem(SEATS_KEY)).toBeNull();
    const again = await atPanel();
    again.store.join();
    expect(joinSent(again).token).toBeUndefined();
    const g = await seated();
    g.msg({ type: "left" });
    expect(keptSeatToken("K7Q2M")).toBeNull();
  });

  it("the host's end of the table, the host's window passing, and game over each forget it", async () => {
    const a = await seated();
    a.msg({ type: "left", reason: "host_left" });
    expect(keptSeatToken("K7Q2M")).toBeNull();
    const b = await seated();
    b.status("closed");
    await vi.advanceTimersByTimeAsync(HOST_WINDOW_MS + 1000);
    expect(b.store.hostLeft).toBe(true);
    expect(keptSeatToken("K7Q2M")).toBeNull();
    const c = await seated();
    c.msg({ type: "state", room: "K7Q2M", round_result: { game_over: false } });
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
    c.msg({ type: "state", room: "K7Q2M", round_result: { game_over: true } });
    expect(keptSeatToken("K7Q2M")).toBeNull();
    // a resume after the game is over does not keep it again
    c.msg({ type: "resume", token: "tok-10", gen: 2 });
    expect(keptSeatToken("K7Q2M")).toBeNull();
  });

  it("past its two hours it is not sent", async () => {
    await seated();
    await vi.advanceTimersByTimeAsync(SEAT_KEEP_MS - 60_000);
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
    await vi.advanceTimersByTimeAsync(120_000);
    const again = await atPanel();
    again.store.join();
    expect(joinSent(again).token).toBeUndefined();
  });

  it("a game longer than two hours keeps it: the seat's frames write its time again", async () => {
    const h = await seated();
    for (let t = 0; t < 3 * 60 * 60 * 1000; t += 15 * 60 * 1000) {
      await vi.advanceTimersByTimeAsync(15 * 60 * 1000);
      h.msg({ type: "state", room: "K7Q2M", round_result: null });
    }
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
  });

  it("a token kept for one code is never sent to another", async () => {
    await seated();
    const other = await atPanel("ZZ9QX");
    other.store.join();
    expect(joinSent(other).token).toBeUndefined();
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
  });

  it("a token the table did not know comes back as a new seat's: the new token replaces it, once", async () => {
    keepSeatToken("K7Q2M", "stale");
    const h = await atPanel();
    h.store.join();
    expect(joinSent(h).token).toBe("stale");
    // the host seated the phone as a newcomer, with a token of its own
    h.msg({ type: "resume", token: "fresh", gen: 1 });
    h.msg({ type: "room", room: "K7Q2M" });
    expect(h.store.seated).toBe(true);
    expect(keptSeatToken("K7Q2M")).toBe("fresh");
    expect(h.sent.filter((m) => m.type === "table_join")).toHaveLength(1);
  });

  it("the kept token back in a resume keeps where it sits until a frame says otherwise; a new token does not", async () => {
    keepSeatToken("K7Q2M", "tok-9", { seat: 2, name: "Mei" });
    const h = await atPanel();
    h.store.join();
    h.msg({ type: "resume", token: "tok-9", gen: 1 });
    // the link drops before any room frame
    h.status("closed");
    expect(keptSeatToken("K7Q2M")).toBe("tok-9");
    expect(keptSeatAt("K7Q2M")).toEqual({ seat: 2, name: "Mei" });
    const g = await atPanel();
    g.store.join();
    g.msg({ type: "resume", token: "tok-new", gen: 1 });
    expect(keptSeatAt("K7Q2M")).toBeNull();
    g.msg({ type: "room", room: "K7Q2M", you: 3, players: [{ seat: 3, name: "Mei" }] });
    expect(keptSeatAt("K7Q2M")).toEqual({ seat: 3, name: "Mei" });
  });

  it("one per table, the newest few tables only", async () => {
    for (let i = 0; i < SEAT_KEEP_MAX + 2; i++) {
      keepSeatToken(`CODE${i}`, `t${i}`);
      await vi.advanceTimersByTimeAsync(1000);
    }
    keepSeatToken("CODE5", "t5b");
    const kept = JSON.parse(localStorage.getItem(SEATS_KEY)!) as Record<string, { token: string }>;
    expect(Object.keys(kept).sort()).toEqual(["CODE2", "CODE3", "CODE4", "CODE5"]);
    expect(kept.CODE5.token).toBe("t5b");
  });

  it("storage that throws or holds junk: no token, and the join goes on", async () => {
    localStorage.setItem(SEATS_KEY, "not json");
    expect(keptSeatToken("K7Q2M")).toBeNull();
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
    try {
      const h = await seated();
      expect(h.store.seated).toBe(true);
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });

  it("no log line carries a token's value", async () => {
    const h = await seated();
    h.status("closed");
    await vi.advanceTimersByTimeAsync(1000);
    h.status("open");
    const again = await atPanel();
    again.store.join();
    const lines = nearbyLogLines().map((l) => l.text);
    expect(lines.some((l) => l.includes("with token"))).toBe(true);
    expect(lines.some((l) => l.includes("tok-9"))).toBe(false);
  });
});
