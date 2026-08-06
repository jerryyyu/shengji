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
