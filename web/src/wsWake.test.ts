import { expect, it, vi } from "vitest";

it("wakes closed reconnect backoff once, preserves identity, and leaves live sockets alone", async () => {
  vi.useFakeTimers();
  const listeners: [EventTarget, string, EventListenerOrEventListenerObject][] = [];
  for (const target of [window, document]) {
    const add = target.addEventListener.bind(target);
    vi.spyOn(target, "addEventListener").mockImplementation((type, fn, options) => {
      if (fn) listeners.push([target, type, fn]);
      add(type, fn, options);
    });
  }
  class Socket {
    static OPEN = 1;
    static all: Socket[] = [];
    readyState = 0;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    constructor() { Socket.all.push(this); }
    close() { this.readyState = 3; this.onclose?.(); }
    send() {}
    open() { this.readyState = 1; this.onopen?.(); }
  }
  vi.stubGlobal("WebSocket", Socket);
  try {
    vi.resetModules();
    const { conn, saveRoom, saveResumeToken, getSavedRoom, getResumeToken } = await import("./ws");
    saveRoom("ABCD"); saveResumeToken("my-seat-token");
    conn.start(); conn.start();
    expect(Socket.all).toHaveLength(1);
    const wake = () => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("pageshow"));
      document.dispatchEvent(new Event("visibilitychange"));
    };
    // Connecting is not a failed connection; a wake must not restart it.
    wake(); vi.advanceTimersByTime(1);
    expect(Socket.all).toHaveLength(1);
    Socket.all.at(-1)!.open();
    wake(); vi.advanceTimersByTime(1);
    expect(Socket.all).toHaveLength(1);
    // Failed handshakes grow the ordinary backoff to eight seconds.
    Socket.all.at(-1)!.close();
    for (const delay of [500, 1000, 2000, 4000]) {
      vi.advanceTimersByTime(delay);
      Socket.all.at(-1)!.close();
    }
    for (const event of ["online", "pageshow", "visibilitychange"]) {
      const count = Socket.all.length;
      if (event === "visibilitychange") {
        vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
        document.dispatchEvent(new Event(event));
        vi.advanceTimersByTime(1);
        expect(Socket.all).toHaveLength(count);
        vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
      }
      const target = event === "visibilitychange" ? document : window;
      target.dispatchEvent(new Event(event));
      target.dispatchEvent(new Event(event));
      vi.advanceTimersByTime(1);
      expect(Socket.all).toHaveLength(count + 1);
      expect(conn.status).toBe("connecting");
      Socket.all.at(-1)!.open();
      expect(getSavedRoom()).toBe("ABCD");
      expect(getResumeToken()).toBe("my-seat-token");
      vi.advanceTimersByTime(8000);
      expect(Socket.all).toHaveLength(count + 1); // the old timer was cancelled
      Socket.all.at(-1)!.close();
    }
  } finally {
    for (const [target, type, fn] of listeners) target.removeEventListener(type, fn);
    vi.clearAllTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

it("keeps browser wake events off the offline transport while it loads", async () => {
  const network = vi.fn();
  const local = vi.fn();
  let resolveModule!: (value: { LocalSocket: new () => object }) => void;
  const module = new Promise<{ LocalSocket: new () => object }>((resolve) => { resolveModule = resolve; });
  vi.doMock("./offline/server", () => module);
  vi.stubGlobal("WebSocket", network);
  sessionStorage.setItem("shengji.offline", "1");
  try {
    vi.resetModules();
    const { conn, OFFLINE } = await import("./ws");
    expect(OFFLINE).toBe(true);
    conn.start(); conn.start();
    const wake = () => {
      window.dispatchEvent(new Event("online"));
      window.dispatchEvent(new Event("pageshow"));
      document.dispatchEvent(new Event("visibilitychange"));
    };
    wake();
    expect(network).not.toHaveBeenCalled();
    class LocalSocket {
      readyState = 0;
      constructor() { local(); }
    }
    resolveModule({ LocalSocket });
    await vi.waitFor(() => expect(local).toHaveBeenCalledTimes(1));
    wake();
    expect(local).toHaveBeenCalledTimes(1);
    expect(network).not.toHaveBeenCalled();
  } finally {
    sessionStorage.removeItem("shengji.offline");
    vi.doUnmock("./offline/server");
    vi.unstubAllGlobals();
    vi.resetModules();
  }
});
