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
  static last: FakeWS | null = null;
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

describe("chat buffering", () => {
  it("keeps messages that arrive before any component subscribes", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    // Scrollback is delivered on join, ahead of the first state — i.e. before
    // <Table> exists. Subscribing alone would lose it.
    FakeWS.last!.deliver({ type: "room", room: "AAAA", you: 0 });
    FakeWS.last!.deliver({ type: "chat", seat: -1, name: "", text: "a joined", t: 1 });
    FakeWS.last!.deliver({ type: "chat", seat: 0, name: "a", text: "hi", t: 2 });
    expect(conn.chatHistory().map((m: any) => m.text)).toEqual(["a joined", "hi"]);
  });

  it("drops the previous room's log when the room changes", async () => {
    const { conn } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver({ type: "room", room: "AAAA", you: 0 });
    FakeWS.last!.deliver({ type: "chat", seat: 0, name: "a", text: "in A", t: 1 });
    FakeWS.last!.deliver({ type: "room", room: "BBBB", you: 1 });
    expect(conn.chatHistory()).toHaveLength(0);
    FakeWS.last!.deliver({ type: "chat", seat: 1, name: "b", text: "in B", t: 2 });
    expect(conn.chatHistory().map((m: any) => m.text)).toEqual(["in B"]);
  });

  it("does not leak room A's chat after leaving it", async () => {
    const { conn, clearSavedRoom } = await load();
    conn.start();
    FakeWS.last!.onopen?.();
    FakeWS.last!.deliver({ type: "room", room: "AAAA", you: 0 });
    FakeWS.last!.deliver({ type: "chat", seat: 0, name: "a", text: "secret", t: 1 });
    conn.clearChat();
    clearSavedRoom();
    expect(conn.chatHistory()).toHaveLength(0);
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

describe("connection intent", () => {
  it("does not rejoin on its own — App decides", async () => {
    const { conn, saveRoom, saveName } = await load();
    saveRoom("ZZZZ");
    saveName("jerry");
    conn.start();
    FakeWS.last!.onopen?.();
    // ws.ts used to read localStorage here and send join_room itself, which
    // raced the invite flow. It must now report "open" and nothing else.
    expect(FakeWS.last!.sent.filter((m) => m.type === "join_room")).toHaveLength(0);
  });
});
