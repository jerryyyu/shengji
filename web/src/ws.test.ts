/**
 * Client-side regression tests (Codex ship gate P0-8).
 *
 * The 21 server wire tests cannot see any of this: chat buffered before
 * <Table> mounts, room-keyed history, resume-token persistence, and which
 * room a reconnect decides to rejoin all live in the browser. Each test here
 * fails against the behaviour it replaced.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// A fake WebSocket the tests drive by hand. `conn` grabs whatever is on
// globalThis at connect time, so this must be installed before importing ws.ts.
class FakeWS {
  static OPEN = 1;
  static last: FakeWS | null = null;
  static count = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: any[] = [];
  readyState = 1;
  url: string;
  constructor(url: string) {   // no parameter properties: erasableSyntaxOnly
    this.url = url;
    FakeWS.last = this;
    FakeWS.count += 1;
  }
  send(raw: string) {
    this.sent.push(JSON.parse(raw));
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  /** Server -> client. */
  deliver(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

(globalThis as any).WebSocket = FakeWS;

const load = async () => {
  vi.resetModules();
  return await import("./ws");
};

beforeEach(() => {
  localStorage.clear();
  FakeWS.last = null;
});

describe("chat: snapshot + identified live events", () => {
  const hist = (room: string, msgs: any[]) => ({
    type: "chat_history", room, through_id: msgs.at(-1)?.id ?? 0, messages: msgs,
  });
  const line = (room: string, id: number, text: string) => ({
    type: "chat", room, id, seat: 0, name: "a", text, t: id,
  });

  it("keeps history that arrives before any component subscribes", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    // The snapshot is delivered on attach, ahead of the first state — i.e.
    // before <Table> exists. Subscribing alone would lose it.
    FakeWS.last!.deliver(hist("AAAA", [line("AAAA", 1, "a joined"), line("AAAA", 2, "hi")]));
    expect(conn.chatHistory().map((m: any) => m.text)).toEqual(["a joined", "hi"]);
  });

  it("does not double messages when the same room reconnects", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver(hist("AAAA", [line("AAAA", 1, "one"), line("AAAA", 2, "two")]));
    // Reconnect: the server replays its snapshot, which now also contains a
    // line we already saw live. Neither may appear twice.
    FakeWS.last!.deliver(line("AAAA", 3, "three"));
    FakeWS.last!.deliver(hist("AAAA", [
      line("AAAA", 1, "one"), line("AAAA", 2, "two"), line("AAAA", 3, "three"),
    ]));
    expect(conn.chatHistory().map((m: any) => m.text)).toEqual(["one", "two", "three"]);
  });

  it("keeps a live message that straddles the snapshot boundary", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver(hist("AAAA", [line("AAAA", 1, "one")]));
    FakeWS.last!.deliver(line("AAAA", 2, "live"));       // after through_id
    expect(conn.chatHistory().map((m: any) => m.text)).toEqual(["one", "live"]);
    expect(conn.chatHistory()).toHaveLength(2);          // not lost, not doubled
  });

  it("handles server scrollback rollover beyond fifty messages", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    const sixty = Array.from({ length: 60 }, (_, i) =>
      line("AAAA", i + 1, `line-${i + 1}`));
    FakeWS.last!.deliver(hist("AAAA", sixty));
    expect(conn.chatHistory()).toHaveLength(60);

    // Reattach snapshot: the server retains its most recent 50. Replacing the
    // local snapshot must neither keep stale prefix lines nor duplicate the
    // live message immediately after the snapshot boundary.
    FakeWS.last!.deliver(hist("AAAA", sixty.slice(-50)));
    FakeWS.last!.deliver(line("AAAA", 61, "line-61"));
    FakeWS.last!.deliver(line("AAAA", 61, "line-61"));
    expect(conn.chatHistory().map((m: any) => m.id)).toEqual(
      Array.from({ length: 51 }, (_, i) => i + 11),
    );
  });

  it("leaks nothing from room A after joining room B", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver(hist("AAAA", [line("AAAA", 1, "secret")]));
    FakeWS.last!.deliver({ type: "room", room: "BBBB", you: 1 });
    expect(conn.chatHistory()).toHaveLength(0);
    // Ids restart per room; an id already seen in A must not suppress B's.
    FakeWS.last!.deliver(line("BBBB", 1, "in B"));
    expect(conn.chatHistory().map((m: any) => m.text)).toEqual(["in B"]);
  });
});

describe("resume identity", () => {
  it("stores the server's token and never invents one", async () => {
    const { conn, getResumeToken } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    expect(getResumeToken()).toBeNull();
    FakeWS.last!.deliver({ type: "resume", token: "tok-123", gen: 1 });
    expect(getResumeToken()).toBe("tok-123");
  });

  it("forgets the token when the room is cleared, so it cannot be replayed", async () => {
    const { conn, clearSavedRoom, getResumeToken } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver({ type: "resume", token: "tok-123", gen: 1 });
    clearSavedRoom();
    expect(getResumeToken()).toBeNull();
  });
});

describe("a table on a device or a nearby phone is never written down", () => {
  it("a nearby link's resume token is not saved, nor the table's code, while a nearby session or offline play is on", async () => {
    const { conn, saveRoom, saveResumeToken, getSavedRoom, getResumeToken } = await load();
    const mode = await import("./offlineMode");
    conn.start();
    FakeWS.last!.onopen?.();
    // the nearby link, even before the session flags are up
    conn.useNearby(() => new FakeWS("nearby") as unknown as WebSocket);
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver({ type: "resume", token: "near-tok", gen: 1 });
    expect(getResumeToken()).toBeNull();
    mode.setOffline(true);
    mode.setNearbySession(true);
    FakeWS.last!.deliver({ type: "resume", token: "near-tok-2", gen: 2 });
    // App's room frame handler and its first-state save
    saveRoom("K7Q2M");
    saveResumeToken("near-tok-3");
    mode.setNearbySession(false);
    // offline play on this device: its room is not the game server's either
    saveRoom("QWER");
    expect(getSavedRoom()).toBeNull();
    expect(getResumeToken()).toBeNull();
    const kept = Object.keys(localStorage).map((k) => `${k}=${localStorage.getItem(k)}`).join(";");
    expect(kept).not.toMatch(/K7Q2M|QWER|near-tok/);
    mode.setOffline(false);
    saveRoom("ZZZZ");
    expect(getSavedRoom()).toBe("ZZZZ");
  });
});

describe("connection intent", () => {
  it("does not rejoin on its own — App decides", async () => {
    const { conn, saveRoom, saveName } = await load();
    saveRoom("ZZZZ");
    saveName("jerry");
    conn.start();
    FakeWS.last!.onopen?.();
    // ws.ts used to read localStorage here and send join_room itself, which
    // raced the invite flow. It must now report "open" and nothing else.
    expect(FakeWS.last!.sent.filter((m) => m.type === "table_join")).toHaveLength(0);
  });
});

describe("leaveToLobby (Back to lobby without a page reload)", () => {
  const state = { type: "state", room: "AAAA", you: 0, phase: "game_over" };
  const record = (conn: { subscribe: (fn: (m: any) => void) => () => void }) => {
    const got: string[] = [];
    const off = conn.subscribe((m) => got.push(m.type));
    return { got, off };
  };

  it("tells the server, resets listeners now, and keeps the one socket", async () => {
    const { conn, saveRoom, saveResumeToken, getSavedRoom, getResumeToken } = await load();
    conn.start();
    const ws = FakeWS.last!;
    ws.onopen?.();
    saveRoom("AAAA");
    saveResumeToken("tok");
    const { got } = record(conn);
    const before = FakeWS.count;

    conn.leaveToLobby();

    expect(ws.sent).toEqual([{ type: "table_leave" }]);
    expect(got).toEqual(["left"]);                 // UI resets without waiting
    expect(getSavedRoom()).toBeNull();             // a reconnect cannot resume it
    expect(getResumeToken()).toBeNull();
    expect(ws.readyState).toBe(1);                 // socket kept open...
    expect(FakeWS.count).toBe(before);             // ...and no second one opened
  });

  it("drops the left room's in-flight messages until the server confirms", async () => {
    const { conn } = await load();
    conn.start();
    const ws = FakeWS.last!;
    ws.onopen?.();
    const { got } = record(conn);
    conn.leaveToLobby();
    ws.deliver(state);                             // sent before leave_room was processed
    ws.deliver({ type: "chat", room: "AAAA", id: 9, seat: 1, name: "b", text: "gg", t: 1 });
    ws.deliver({ type: "left" });                  // the server's confirmation
    expect(got).toEqual(["left"]);
    expect(conn.chatHistory()).toHaveLength(0);
    ws.deliver({ type: "room", room: "BBBB", you: 0 });   // next create/join
    expect(got).toEqual(["left", "room"]);
  });

  // Codex HOLD on #845: errors carry no request id, so a late error from an
  // old action must not lift the barrier for the old state queued behind it.
  it("a late error from the old room does not let a late state through", async () => {
    vi.useFakeTimers();
    try {
      const { conn } = await load();
      conn.start();
      const ws = FakeWS.last!;
      ws.onopen?.();
      const { got } = record(conn);
      conn.leaveToLobby();
      ws.deliver({ type: "error", message: "Invalid request." });   // reply to an old play
      ws.deliver(state);                                            // old room, still in flight
      expect(got).toEqual(["left"]);
      // The ambiguous error retired that socket; the next one is clean.
      expect(ws.readyState).toBe(3);
      vi.advanceTimersByTime(500);
      const next = FakeWS.last!;
      expect(next).not.toBe(ws);
      next.onopen?.();
      expect(next.sent).toEqual([]);                                // nothing resumed
      next.deliver({ type: "room", room: "BBBB", you: 0 });
      expect(got).toEqual(["left", "room"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a socket close during the leave resets cleanly", async () => {
    vi.useFakeTimers();
    try {
      const { conn } = await load();
      conn.start();
      const ws = FakeWS.last!;
      ws.onopen?.();
      const { got } = record(conn);
      conn.leaveToLobby();
      ws.close();
      ws.deliver(state);                       // a dead socket's leftovers stay dropped
      vi.advanceTimersByTime(500);
      const next = FakeWS.last!;
      expect(next).not.toBe(ws);
      next.onopen?.();
      expect(next.sent).toEqual([]);
      next.deliver({ type: "room", room: "BBBB", you: 0 });
      expect(got).toEqual(["left", "room"]);
      vi.advanceTimersByTime(10_000);          // the leave watchdog was cancelled
      expect(next.readyState).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("with no confirmation at all, the socket is retired after the watchdog", async () => {
    vi.useFakeTimers();
    try {
      const { conn } = await load();
      conn.start();
      const ws = FakeWS.last!;
      ws.onopen?.();
      const { got } = record(conn);
      conn.leaveToLobby();
      vi.advanceTimersByTime(4999);
      expect(ws.readyState).toBe(1);
      vi.advanceTimersByTime(1);
      expect(ws.readyState).toBe(3);
      ws.deliver(state);
      expect(got).toEqual(["left"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("after the server's left, the watchdog does not retire the socket", async () => {
    vi.useFakeTimers();
    try {
      const { conn } = await load();
      conn.start();
      const ws = FakeWS.last!;
      ws.onopen?.();
      conn.leaveToLobby();
      ws.deliver({ type: "left" });
      vi.advanceTimersByTime(10_000);
      expect(ws.readyState).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("with no open socket it only resets locally", async () => {
    const { conn, saveRoom, getSavedRoom } = await load();
    conn.start();
    const ws = FakeWS.last!;
    ws.readyState = 0;                             // still connecting
    saveRoom("AAAA");
    const { got } = record(conn);
    conn.leaveToLobby();
    expect(ws.sent).toEqual([]);
    expect(got).toEqual(["left"]);
    expect(getSavedRoom()).toBeNull();
    ws.readyState = 1;
    ws.onopen?.();
    ws.deliver({ type: "room", room: "BBBB", you: 0 });   // nothing suppressed
    expect(got).toEqual(["left", "room"]);
  });
});

describe("a Leave while the socket is down is delivered by the next one", () => {
  const record = (conn: { subscribe: (fn: (m: any) => void) => () => void }) => {
    const got: string[] = [];
    conn.subscribe((m) => got.push(m.type));
    return got;
  };
  const seated = async () => {
    const mod = await load();
    mod.conn.start();
    const ws = FakeWS.last!;
    ws.onopen?.();
    mod.saveName("jerry");
    mod.saveRoom("AAAA");
    mod.saveResumeToken("tok");
    return { ...mod, ws };
  };
  const resumeThenLeave = [
    { type: "table_join", code: "AAAA", name: "jerry", expect: "room", token: "tok" },
    { type: "table_leave" },
  ];

  it("goes to the lobby now, then resumes the seat and leaves it on the next socket", async () => {
    vi.useFakeTimers();
    try {
      const { conn, ws, getSavedRoom } = await seated();
      ws.close();                                       // the link is down
      const got = record(conn);
      expect(conn.send({ type: "table_leave" })).toBe(true);
      expect(got).toEqual(["left"]);                    // the page leaves at once
      expect(getSavedRoom()).toBeNull();                // App resumes nothing itself
      vi.advanceTimersByTime(500);
      const next = FakeWS.last!;
      expect(next).not.toBe(ws);
      next.onopen?.();
      expect(next.sent).toEqual(resumeThenLeave);
      next.deliver({ type: "state", room: "AAAA", you: 1, phase: "play" });   // the resumed seat's frames
      next.deliver({ type: "left" });
      expect(got).toEqual(["left"]);
      next.deliver({ type: "room", room: "BBBB", you: 0 });   // the socket is the lobby's again
      expect(got).toEqual(["left", "room"]);
      next.close();
      vi.advanceTimersByTime(500);
      FakeWS.last!.onopen?.();
      expect(FakeWS.last!.sent).toEqual([]);            // delivered once
    } finally {
      vi.useRealTimers();
    }
  });

  it("a Leave whose socket closed before the server's left goes again on the next one", async () => {
    vi.useFakeTimers();
    try {
      const { conn, ws, getSavedRoom } = await seated();
      const got = record(conn);
      expect(conn.send({ type: "table_leave" })).toBe(true);
      expect(ws.sent).toEqual([{ type: "table_leave" }]);
      ws.close();                                       // no "left" came back
      expect(got).toEqual(["left"]);
      expect(getSavedRoom()).toBeNull();
      vi.advanceTimersByTime(500);
      FakeWS.last!.onopen?.();
      expect(FakeWS.last!.sent).toEqual(resumeThenLeave);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a refused resume ends the owed Leave: the next socket sends nothing", async () => {
    vi.useFakeTimers();
    try {
      const { conn, ws } = await seated();
      ws.close();
      record(conn);
      conn.send({ type: "table_leave" });
      vi.advanceTimersByTime(500);
      const next = FakeWS.last!;
      next.onopen?.();
      next.deliver({ type: "error", code: "room_not_found", message: "Room not found." });
      expect(next.readyState).toBe(3);                  // retired, as any leave's error is
      vi.advanceTimersByTime(500);
      FakeWS.last!.onopen?.();
      expect(FakeWS.last!.sent).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("with no seat saved, a Leave that cannot go is refused as before", async () => {
    const { conn, FakeWSref } = { ...(await load()), FakeWSref: FakeWS };
    conn.start();
    const ws = FakeWSref.last!;
    ws.onopen?.();
    ws.close();
    const got = record(conn);
    expect(conn.send({ type: "table_leave" })).toBe(false);
    expect(got).toEqual([]);
  });

  it("the left answered on the same socket clears it: nothing goes again", async () => {
    vi.useFakeTimers();
    try {
      const { conn, ws } = await seated();
      conn.send({ type: "table_leave" });
      ws.deliver({ type: "left" });
      ws.close();
      vi.advanceTimersByTime(500);
      FakeWS.last!.onopen?.();
      expect(FakeWS.last!.sent).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("reconnect(): the identity lives on the handshake", () => {
  it("closes the live socket and opens a new one at once, without the failure backoff", async () => {
    vi.useFakeTimers();
    const { conn } = await load();
    conn.start();
    const first = FakeWS.last!;
    first.onopen?.();
    expect(conn.status).toBe("open");
    const before = FakeWS.count;
    conn.reconnect();
    expect(first.readyState).toBe(3);
    expect(conn.status).toBe("closed");
    vi.advanceTimersByTime(0);
    expect(FakeWS.count).toBe(before + 1);        // immediately, not after 500 ms
    const second = FakeWS.last!;
    expect(second).not.toBe(first);
    second.onopen?.();
    expect(conn.status).toBe("open");
    expect(second.sent).toEqual([]);              // the lobby has nothing to resend
    // a later unplanned drop still backs off
    const b2 = FakeWS.count;
    second.close();
    vi.advanceTimersByTime(0);
    expect(FakeWS.count).toBe(b2);
    vi.advanceTimersByTime(1000);
    expect(FakeWS.count).toBe(b2 + 1);
    vi.useRealTimers();
  });
  it("is a no-op before start()", async () => {
    const { conn } = await load();
    const before = FakeWS.count;
    conn.reconnect();
    expect(FakeWS.count).toBe(before);
  });
});

describe("negotiated connection heartbeat", () => {
  const start = async () => {
    vi.useFakeTimers();
    const { conn } = await load();
    conn.start();
    const ws = FakeWS.last!;
    ws.onopen?.();
    return { conn, ws };
  };

  it("does not probe a server that has not advertised support", async () => {
    try {
      const { conn, ws } = await start();
      vi.advanceTimersByTime(60_000);
      expect(ws.sent).toEqual([]);
      expect(conn.status).toBe("open");
      ws.close();
    } finally { vi.useRealTimers(); }
  });

  it("keeps a quiet healthy socket and consumes pong without emitting game events", async () => {
    try {
      const { conn, ws } = await start();
      const seen: unknown[] = [];
      conn.subscribe((m) => seen.push(m));
      expect(ws.url).toContain("heartbeat=1");
      ws.deliver({ type: "heartbeat_ready" });
      for (let nonce = 1; nonce <= 3; nonce++) {
        vi.advanceTimersByTime(15_000);
        expect(ws.sent.at(-1)).toEqual({ type: "ping", nonce });
        ws.deliver({ type: "pong", nonce });
      }
      expect(seen).toEqual([]);
      expect(conn.status).toBe("open");
      ws.close();
    } finally { vi.useRealTimers(); }
  });

  it("replaces a dead-but-open socket even if close never calls back, retaining resume identity", async () => {
    try {
      const { conn, ws } = await start();
      localStorage.setItem("shengji.room", "ABCD");
      localStorage.setItem("shengji.token", "saved-token");
      ws.close = () => { ws.readyState = 3; };
      ws.deliver({ type: "heartbeat_ready" });
      vi.advanceTimersByTime(15_000);
      ws.deliver({ type: "pong", nonce: 0 }); // a stale reply is not this probe's answer
      vi.advanceTimersByTime(15_000);
      expect(conn.status).toBe("closed");
      vi.advanceTimersByTime(1);
      expect(FakeWS.last).not.toBe(ws);
      const fresh = FakeWS.last!;
      fresh.onopen?.();
      expect(conn.generation).toBe(2);
      expect(localStorage.getItem("shengji.room")).toBe("ABCD");
      expect(localStorage.getItem("shengji.token")).toBe("saved-token");
      ws.deliver({ type: "heartbeat_ready" });
      vi.advanceTimersByTime(60_000);
      expect(fresh.sent).toEqual([]);
      expect(conn.status).toBe("open");
      fresh.deliver({ type: "heartbeat_ready" });
      vi.advanceTimersByTime(15_000);
      expect(fresh.sent).toEqual([{ type: "ping", nonce: 1 }]);
      fresh.deliver({ type: "pong", nonce: 1 });
      expect(conn.status).toBe("open");
      fresh.close();
    } finally { vi.useRealTimers(); }
  });

  it("cancels the old heartbeat when a socket closes normally", async () => {
    try {
      const { conn, ws } = await start();
      ws.deliver({ type: "heartbeat_ready" });
      vi.advanceTimersByTime(15_000);
      ws.close();
      vi.advanceTimersByTime(500);
      const fresh = FakeWS.last!;
      fresh.onopen?.();
      vi.advanceTimersByTime(60_000);
      expect(conn.status).toBe("open");
      expect(fresh.sent).toEqual([]);
      fresh.close();
    } finally { vi.useRealTimers(); }
  });
});

describe("a dead socket is found fast at a table", () => {
  const table = { type: "state", room: "ABCD", you: 0, phase: "play" };
  const pings = (ws: FakeWS) => ws.sent.filter((m) => m.type === "ping");
  // A half-open socket: close() starts a closing handshake that never ends,
  // so onclose never calls back, and nothing it sends gets an answer.
  const halfOpen = (ws: FakeWS) => { ws.close = () => { ws.readyState = 2; }; };
  const seated = async () => {
    vi.useFakeTimers();
    const { conn, ANSWER_MS, ACTION_PONG_MS, TABLE_PING_MS, TABLE_PONG_MS, HEARTBEAT_MS } = await load();
    conn.start();
    const ws = FakeWS.last!;
    ws.onopen?.();
    ws.deliver({ type: "heartbeat_ready" });
    ws.deliver(table);
    return { conn, ws, ANSWER_MS, ACTION_PONG_MS, TABLE_PING_MS, TABLE_PONG_MS, HEARTBEAT_MS };
  };

  it("after an action, silence then a lost pong reconnects within 6 s", async () => {
    try {
      const { conn, ws, ANSWER_MS, ACTION_PONG_MS } = await seated();
      expect(ANSWER_MS + ACTION_PONG_MS).toBeLessThanOrEqual(6000);
      const statuses: string[] = [];
      conn.subscribeStatus((s: string) => statuses.push(s));
      halfOpen(ws);
      expect(conn.send({ type: "play", card_ids: [7] })).toBe(true);
      vi.advanceTimersByTime(ANSWER_MS - 1);
      expect(pings(ws)).toEqual([]);
      vi.advanceTimersByTime(1);
      expect(pings(ws)).toEqual([{ type: "ping", nonce: 1 }]);
      vi.advanceTimersByTime(ACTION_PONG_MS - 1);
      expect(conn.status).toBe("open");
      vi.advanceTimersByTime(1);
      // the connection pill and the Play button read this status at once
      expect(conn.status).toBe("closed");
      expect(statuses.at(-1)).toBe("closed");
      vi.advanceTimersByTime(1);   // the reconnect opens at once
      const fresh = FakeWS.last!;
      expect(fresh).not.toBe(ws);
      fresh.onopen?.();
      expect(conn.status).toBe("open");
      fresh.close();
    } finally { vi.useRealTimers(); }
  });

  it("an idle table on a dead socket reconnects within 14 s of the last pong", async () => {
    try {
      const { conn, ws, TABLE_PING_MS, TABLE_PONG_MS } = await seated();
      expect(TABLE_PING_MS + TABLE_PONG_MS).toBeLessThanOrEqual(14_000);
      vi.advanceTimersByTime(TABLE_PING_MS);
      expect(pings(ws)).toEqual([{ type: "ping", nonce: 1 }]);
      ws.deliver({ type: "pong", nonce: 1 });
      halfOpen(ws);                                  // dies right after a pong: the worst case
      vi.advanceTimersByTime(TABLE_PING_MS);
      expect(pings(ws)).toHaveLength(2);
      vi.advanceTimersByTime(TABLE_PONG_MS - 1);
      expect(conn.status).toBe("open");
      vi.advanceTimersByTime(1);
      expect(conn.status).toBe("closed");
      vi.advanceTimersByTime(1);   // the reconnect opens at once
      expect(FakeWS.last).not.toBe(ws);
      FakeWS.last!.close();
    } finally { vi.useRealTimers(); }
  });

  it("a slow but live server (every pong 2 s late) never reconnects", async () => {
    try {
      const { conn, ws } = await seated();
      const count = FakeWS.count;
      let answered = 0;
      for (let t = 0; t < 120_000; t += 100) {
        // an action every 3 s that the server never answers with a state
        if (t % 3000 === 0) conn.send({ type: "play", card_ids: [t] });
        vi.advanceTimersByTime(100);
        for (const m of pings(ws).slice(answered)) {
          window.setTimeout(() => ws.deliver({ type: "pong", nonce: m.nonce }), 2000);
          answered += 1;
        }
      }
      expect(answered).toBeGreaterThan(10);
      expect(conn.status).toBe("open");
      expect(FakeWS.count).toBe(count);
      // one ping in flight at a time, however many actions wait on it
      const nonces = pings(ws).map((m) => m.nonce);
      expect(nonces).toEqual(nonces.map((_, i) => i + 1));
      ws.close();
    } finally { vi.useRealTimers(); }
  });

  it("an answer to the action, or any message, sends no probe", async () => {
    try {
      const { conn, ws, ANSWER_MS, TABLE_PING_MS } = await seated();
      conn.send({ type: "pass_declare" });
      vi.advanceTimersByTime(ANSWER_MS - 100);
      ws.deliver(table);
      vi.advanceTimersByTime(TABLE_PING_MS - ANSWER_MS);
      expect(pings(ws)).toEqual([]);
      // telemetry and other unanswered messages wait on nothing
      conn.send({ type: "client_event", events: [] } as any);
      vi.advanceTimersByTime(TABLE_PING_MS - 1);
      expect(pings(ws)).toHaveLength(1);         // the table heartbeat, not a probe
      ws.close();
    } finally { vi.useRealTimers(); }
  });

  it("an action on a dead socket is not replayed: the resumed state decides", async () => {
    try {
      const { conn, ws, ANSWER_MS, ACTION_PONG_MS } = await seated();
      halfOpen(ws);
      conn.send({ type: "play", card_ids: [7] });
      vi.advanceTimersByTime(ANSWER_MS + ACTION_PONG_MS);
      expect(conn.status).toBe("closed");
      // nothing goes out while no socket is open
      expect(conn.send({ type: "play", card_ids: [7] })).toBe(false);
      vi.advanceTimersByTime(1);   // the reconnect opens at once
      const fresh = FakeWS.last!;
      fresh.onopen?.();
      fresh.deliver({ type: "heartbeat_ready" });
      vi.advanceTimersByTime(60_000);
      expect(fresh.sent.filter((m) => m.type !== "ping")).toEqual([]);
      expect(ws.sent.filter((m) => m.type === "play")).toHaveLength(1);
      fresh.close();
    } finally { vi.useRealTimers(); }
  });

  it("the lobby keeps 15 s pings with a 15 s deadline, and leaving a table returns to it", async () => {
    try {
      const { conn, ws, HEARTBEAT_MS, TABLE_PING_MS } = await seated();
      expect(HEARTBEAT_MS).toBe(15_000);
      vi.advanceTimersByTime(TABLE_PING_MS);
      ws.deliver({ type: "pong", nonce: 1 });
      conn.leaveToLobby();
      ws.deliver({ type: "left" });
      // queue messages are answered by the queue's own panels, not a probe
      conn.send({ type: "queue_status" } as any);
      vi.advanceTimersByTime(HEARTBEAT_MS - 1);
      expect(pings(ws)).toHaveLength(1);
      vi.advanceTimersByTime(1);
      expect(pings(ws)).toHaveLength(2);
      halfOpen(ws);
      vi.advanceTimersByTime(HEARTBEAT_MS - 1);
      expect(conn.status).toBe("open");
      vi.advanceTimersByTime(1);
      expect(conn.status).toBe("closed");
    } finally { vi.useRealTimers(); }
  });
});

describe("reconnecting fast once a drop is known", () => {
  const table = { type: "state", room: "ABCD", you: 0, phase: "play" };
  const boot = async () => {
    vi.useFakeTimers();
    const mod = await load();
    const link = await import("./link");
    mod.conn.start();
    return { ...mod, link };
  };
  it("abandons a connect that has not opened in 5 s, and a late open changes nothing", async () => {
    try {
      const { conn, CONNECT_MS } = await boot();
      const first = FakeWS.last!;
      first.readyState = 0;
      vi.advanceTimersByTime(CONNECT_MS - 1);
      expect(conn.status).toBe("connecting");
      vi.advanceTimersByTime(1);
      expect(conn.status).toBe("closed");
      expect(first.readyState).toBe(3);
      expect(first.onopen).toBeNull();
      vi.advanceTimersByTime(500);
      const second = FakeWS.last!;
      expect(second).not.toBe(first);
      second.onopen?.();
      expect(conn.status).toBe("open");
      vi.advanceTimersByTime(60_000);            // its connect timer was cleared by the open
      expect(conn.status).toBe("open");
      second.close();
    } finally { vi.useRealTimers(); }
  });

  it("retries at once after losing a socket that had worked for over 10 s, and after 500 ms otherwise", async () => {
    try {
      const { LONG_LIVED_MS } = await boot();
      const a = FakeWS.last!;
      a.onopen?.();
      vi.advanceTimersByTime(LONG_LIVED_MS + 1);
      a.close();
      vi.advanceTimersByTime(1);
      const b = FakeWS.last!;
      expect(b).not.toBe(a);
      b.onopen?.();
      vi.advanceTimersByTime(1000);              // a short-lived socket
      b.close();
      vi.advanceTimersByTime(499);
      expect(FakeWS.last).toBe(b);
      vi.advanceTimersByTime(1);
      expect(FakeWS.last).not.toBe(b);
    } finally { vi.useRealTimers(); }
  });

  it("at a table the retry delay stops growing at 3 s; in the lobby it grows to 8 s", async () => {
    try {
      const { conn, TABLE_RETRY_MAX_MS } = await boot();
      const delays = (n: number) => {
        const out: number[] = [];
        for (let i = 0; i < n; i++) {
          const ws = FakeWS.last!;
          const t0 = Date.now();
          ws.close();                            // a handshake that failed
          while (FakeWS.last === ws) vi.advanceTimersByTime(100);
          out.push(Date.now() - t0);
        }
        return out;
      };
      expect(delays(6)).toEqual([500, 1000, 2000, 4000, 8000, 8000]);
      FakeWS.last!.onopen?.();
      FakeWS.last!.deliver(table);
      expect(conn.status).toBe("open");
      expect(delays(6)).toEqual([500, 1000, 2000, TABLE_RETRY_MAX_MS, 3000, 3000]);
    } finally { vi.useRealTimers(); }
  });

  it("back online while the socket reads open: it must answer a ping within 2 s", async () => {
    try {
      const { conn, PROBE_MS } = await boot();
      expect(PROBE_MS).toBe(2000);
      const ws = FakeWS.last!;
      ws.onopen?.();
      ws.deliver({ type: "heartbeat_ready" });
      ws.close = () => { ws.readyState = 2; };
      window.dispatchEvent(new Event("online"));
      expect(ws.sent).toEqual([{ type: "ping", nonce: 1 }]);
      vi.advanceTimersByTime(PROBE_MS - 1);
      expect(conn.status).toBe("open");
      vi.advanceTimersByTime(1);
      expect(conn.status).toBe("closed");
    } finally { vi.useRealTimers(); }
  });

  it("a wake restarts a connect older than 2 s, and leaves a younger one alone", async () => {
    try {
      const { conn, STALE_CONNECT_MS } = await boot();
      const first = FakeWS.last!;
      first.readyState = 0;
      vi.advanceTimersByTime(STALE_CONNECT_MS);
      window.dispatchEvent(new Event("online"));
      expect(FakeWS.last).toBe(first);
      vi.advanceTimersByTime(1);
      window.dispatchEvent(new Event("pageshow"));
      vi.advanceTimersByTime(1);
      const second = FakeWS.last!;
      expect(second).not.toBe(first);
      expect(conn.status).toBe("connecting");
      second.onopen?.();
      expect(conn.status).toBe("open");
      second.close();
    } finally { vi.useRealTimers(); }
  });

  it("an unanswered action shows as stalled at 1.5 s, and any message clears it", async () => {
    try {
      const { conn, link, ANSWER_MS } = await boot();
      expect(ANSWER_MS).toBe(1500);
      const ws = FakeWS.last!;
      ws.onopen?.();
      ws.deliver({ type: "heartbeat_ready" });
      ws.deliver(table);
      const seen: boolean[] = [];
      link.subscribeStalled((on) => seen.push(on));
      conn.send({ type: "play", card_ids: [1] });
      vi.advanceTimersByTime(ANSWER_MS - 1);
      expect(link.isStalled()).toBe(false);
      vi.advanceTimersByTime(1);
      expect(link.isStalled()).toBe(true);
      ws.deliver({ type: "pong", nonce: 1 });
      expect(link.isStalled()).toBe(false);
      expect(seen).toEqual([true, false]);
      ws.close();
    } finally { vi.useRealTimers(); }
  });

  it("reports each lost open socket with its cause, and the time down once a new one opens", async () => {
    try {
      const { conn, link, ANSWER_MS, ACTION_PONG_MS } = await boot();
      const events: unknown[] = [];
      link.subscribeLink((ev) => events.push(ev));
      const a = FakeWS.last!;
      a.readyState = 0;
      a.close();                                 // a failed first connect is no drop
      vi.advanceTimersByTime(500);
      const b = FakeWS.last!;
      b.onopen?.();
      b.deliver({ type: "heartbeat_ready" });
      b.deliver(table);
      b.close = () => { b.readyState = 2; };
      conn.send({ type: "play", card_ids: [1] });
      vi.advanceTimersByTime(ANSWER_MS + ACTION_PONG_MS);
      expect(events).toEqual([{ kind: "down", cause: "no_pong" }]);
      vi.advanceTimersByTime(1);
      vi.advanceTimersByTime(700);
      FakeWS.last!.onopen?.();
      expect(events).toEqual([{ kind: "down", cause: "no_pong" }, { kind: "up", ms: 701 }]);
      FakeWS.last!.close();
      expect(events.at(-1)).toEqual({ kind: "down", cause: "closed" });
      vi.advanceTimersByTime(500);
      FakeWS.last!.onopen?.();
      conn.reconnect();
      expect(events.at(-1)).toEqual({ kind: "down", cause: "replaced" });
    } finally { vi.useRealTimers(); }
  });
});

describe("the device key", () => {
  it("is made once, 22 url-safe characters, kept in storage and sent on every socket", async () => {
    vi.useFakeTimers();
    try {
      const { conn, deviceKey } = await load();
      const key = deviceKey();
      expect(key).toMatch(/^[A-Za-z0-9_-]{22}$/);
      expect(deviceKey()).toBe(key);
      expect(localStorage.getItem("shengji.device")).toBe(key);
      conn.start();
      const first = FakeWS.last!;
      expect(new URL(first.url).searchParams.get("device")).toBe(key);
      expect(new URL(first.url).searchParams.get("heartbeat")).toBe("1");
      first.onopen?.();
      first.close();
      vi.advanceTimersByTime(30_000);
      const second = FakeWS.last!;
      expect(second).not.toBe(first);
      expect(new URL(second.url).searchParams.get("device")).toBe(key);
    } finally { vi.useRealTimers(); }
  });

  it("survives a reload, and two devices get different keys", async () => {
    const a = (await load()).deviceKey();
    expect((await load()).deviceKey()).toBe(a);
    localStorage.clear();
    expect((await load()).deviceKey()).not.toBe(a);
  });

  it("falls back to one in-memory key when storage refuses", async () => {
    const { deviceKey } = await load();
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    try {
      const key = deviceKey();
      expect(key).toMatch(/^[A-Za-z0-9_-]{22}$/);
      expect(deviceKey()).toBe(key);
    } finally { get.mockRestore(); }
  });
});

describe("transport swap: the game server's socket and the on-device one share nothing", () => {
  it("cuts the old socket, forgets its room, chat and pending leave, and opens the other in place", async () => {
    const { conn, saveRoom, saveResumeToken, getSavedRoom, getResumeToken } = await load();
    const seen: any[] = [];
    const statuses: string[] = [];
    conn.subscribe((m: any) => seen.push(m));
    conn.subscribeStatus((s: string) => statuses.push(s));
    conn.start();
    const network = FakeWS.last!;
    network.onopen?.();
    network.deliver({ type: "chat_history", room: "ABCD", through_id: 1,
                      messages: [{ type: "chat", room: "ABCD", id: 1, seat: 0, name: "a", text: "hi", t: 1 }] });
    saveRoom("ABCD");
    saveResumeToken("tok");
    conn.leaveToLobby();            // a leave still waiting for the server's "left"
    seen.length = 0;

    await conn.useLocalServer();
    expect(network.readyState).toBe(3);
    expect(network.onmessage).toBeNull();
    expect(network.onclose).toBeNull();
    expect(conn.chatHistory()).toEqual([]);
    expect(getSavedRoom()).toBeNull();
    expect(getResumeToken()).toBeNull();
    expect(seen).toEqual([{ type: "left" }]);
    expect(statuses.at(-1)).toBe("connecting");
    // the on-device socket opens; the old one's late traffic reaches no one
    await vi.waitFor(() => expect(conn.status).toBe("open"));
    const count = FakeWS.count;
    network.deliver({ type: "room", room: "ABCD", players: [], you: 0, host: 0 });
    expect(seen).toEqual([{ type: "left" }]);
    // the game server's own messages go nowhere offline: no error comes back
    expect(conn.send({ type: "queue_status" } as any)).toBe(true);
    expect(conn.send({ type: "create_room", name: "Me" })).toBe(true);
    await vi.waitFor(() => expect(seen.some((m) => m.type === "room")).toBe(true));
    expect(seen.filter((m) => m.type === "error")).toEqual([]);
    expect(FakeWS.count).toBe(count);

    // and back: a fresh game-server socket, the offline room forgotten
    seen.length = 0;
    conn.useGameServer();
    expect(seen).toEqual([{ type: "left" }]);
    expect(FakeWS.count).toBe(count + 1);
    expect(FakeWS.last).not.toBe(network);
    expect(getSavedRoom()).toBeNull();
    FakeWS.last!.onopen?.();
    expect(conn.status).toBe("open");
    expect(FakeWS.last!.sent).toEqual([]);
  });
});

it("does not send an offline turn's telemetry after returning online", async () => {
  const { conn } = await load();
  const { telemetry } = await import("./telemetry");
  const { offlineGame } = await import("./components/offlineGame");
  conn.start();
  FakeWS.last!.onopen?.();
  offlineGame.startFromPlay();
  await vi.waitFor(() => expect(conn.status).toBe("open"));
  telemetry.turnDone({ phase: "play", need: 1, ms_total: 123, sel_changes: 1,
    disabled_play_taps: 0, refused: 0, coach: false, nth_turn: 1, by: "you" });
  offlineGame.goOnline();
  FakeWS.last!.onopen?.();
  telemetry.flush();
  expect(FakeWS.last!.sent.filter((m) => m.type === "client_event")
    .flatMap((m) => m.events).filter((e: any) => e.e === "turn_done")).toEqual([]);
});

it("sends the online page's buffered telemetry before going offline, collects nothing offline, and resumes online", async () => {
  const { conn } = await load();
  const { telemetry } = await import("./telemetry");
  const { offlineGame } = await import("./components/offlineGame");
  conn.start();
  const network = FakeWS.last!;
  network.onopen?.();
  telemetry.tap("play");
  offlineGame.startFromPlay();
  const taps = (ws: FakeWS) => ws.sent.filter((m) => m.type === "client_event")
    .flatMap((m) => m.events).filter((e: any) => e.e === "tap").map((e: any) => e.id);
  expect(taps(network)).toEqual(["play"]);
  await vi.waitFor(() => expect(conn.status).toBe("open"));
  telemetry.tap("next_round");
  expect(telemetry.pending()).toEqual([]);
  offlineGame.goOnline();
  const back = FakeWS.last!;
  back.onopen?.();
  telemetry.tap("duo");
  telemetry.flush();
  expect(taps(back)).toEqual(["duo"]);
});

describe("a nearby link's reconnect attempts", () => {
  it("retry at 0, 0.25, 0.5 and then every 1 s, from the start again once one opens; the game server's keep their backoff", async () => {
    vi.useFakeTimers();
    try {
      const { conn } = await load();
      conn.start();
      FakeWS.last!.onopen?.();
      const made: number[] = [];
      conn.useNearby(() => {
        made.push(Date.now());
        return new FakeWS("nearby") as unknown as WebSocket;
      });
      FakeWS.last!.onopen?.();
      const closed: number[] = [];
      for (let i = 0; i < 6; i++) {
        closed.push(Date.now());
        FakeWS.last!.close();
        await vi.advanceTimersByTimeAsync(1000);
      }
      // each attempt's wait after the close before it
      expect(closed.map((t, i) => made[i + 1] - t)).toEqual([0, 250, 500, 1000, 1000, 1000]);
      FakeWS.last!.onopen?.();
      made.length = 0;
      made.push(Date.now());
      FakeWS.last!.close();
      await vi.advanceTimersByTimeAsync(0);
      expect(made).toHaveLength(2);
      expect(made[1] - made[0]).toBe(0);
      // back to the game server: its own backoff, unchanged
      conn.leaveNearby();
      await vi.advanceTimersByTimeAsync(0);
      const remote: number[] = [];
      let at = Date.now();
      FakeWS.last!.onopen?.();
      for (let i = 0; i < 3; i++) {
        const ws = FakeWS.last!;
        at = Date.now();
        ws.close();
        while (FakeWS.last === ws) await vi.advanceTimersByTimeAsync(50);
        remote.push(Date.now() - at);
      }
      expect(remote).toEqual([500, 1000, 2000]);
      conn.stop();
    } finally {
      vi.useRealTimers();
    }
  });
});
