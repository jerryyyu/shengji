// A sign-in or sign-out while the page is open: the server reads who we are
// only on the websocket handshake, so the socket is replaced, and a player
// mid-game rejoins their own seat with the saved resume token.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: { type: string; token?: string; room?: string }[] = [];
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send(raw: string) { this.sent.push(JSON.parse(raw)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const realLocation = window.location;
beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  Object.defineProperty(window, "location", { configurable: true, value: { ...realLocation, search: "" } });
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/auth/logout" ? { ok: true } : null;
    return { status: body ? 200 : 401, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.useFakeTimers();
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
});

async function mount() {
  const { default: App } = await import("./App");
  const { auth } = await import("./auth");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  return { auth };
}

it("sign-in from the lobby replaces the socket; nothing is resent", async () => {
  const { auth } = await mount();
  const first = FakeWS.all[0];
  act(() => first.onopen?.());
  expect(first.sent).toEqual([]);
  act(() => auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }));
  expect(first.readyState).toBe(3);
  act(() => { vi.advanceTimersByTime(0); });
  expect(FakeWS.all).toHaveLength(2);
  const second = FakeWS.all[1];
  act(() => second.onopen?.());
  expect(second.sent).toEqual([]);
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
});

it("sign-in and sign-out mid-game rejoin the same seat with the resume token", async () => {
  const { auth } = await mount();
  const { saveName, saveRoom, saveResumeToken } = await import("./ws");
  saveName("Me"); saveRoom("ABCD"); saveResumeToken("tok-1");
  const first = FakeWS.all[0];
  act(() => first.onopen?.());
  expect(first.sent).toEqual([{ type: "join_room", room: "ABCD", name: "Me", token: "tok-1" }]);

  act(() => auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }));
  act(() => { vi.advanceTimersByTime(0); });
  const second = FakeWS.all[1];
  expect(second).toBeTruthy();
  act(() => second.onopen?.());
  expect(second.sent).toEqual([{ type: "join_room", room: "ABCD", name: "Me", token: "tok-1" }]);
  expect(host.querySelector(".reconnect-banner")).toBeNull();   // back to "open"

  await act(async () => { await auth.signOut(); });
  act(() => { vi.advanceTimersByTime(0); });
  expect(FakeWS.all).toHaveLength(3);
  const third = FakeWS.all[2];
  act(() => third.onopen?.());
  expect(third.sent).toEqual([{ type: "join_room", room: "ABCD", name: "Me", token: "tok-1" }]);
  expect(auth.state.status).toBe("out");
});
