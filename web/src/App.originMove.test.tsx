// The app's first launch on its own domain: the shell hands the page the old
// origin's storage and whether it was signed in (originMove.ts). A session
// that did not carry over opens the one identity sheet at Sign in, once.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

class FakeWS {
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor() { FakeWS.all.push(this); }
  send() {}
  close() { this.readyState = 3; this.onclose?.(); }
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
let me: unknown = null;
const win = window as unknown as { __shengjiOriginMove?: unknown };
beforeEach(() => {
  FakeWS.all = [];
  me = null;
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url === "/api/auth/config" ? { google_client_id: "cid" } : url === "/api/me" ? me : null;
    return { status: body ? 200 : 401, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  delete win.__shengjiOriginMove;
});

async function mount() {
  const { default: App } = await import("./App");
  const { auth } = await import("./auth");
  const { guestName } = await import("./guestName");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await act(async () => { await auth.settled(); await Promise.resolve(); });
  return { auth, view: guestName.getSnapshot() };
}

it("opens the identity sheet at Sign in when the old origin's session did not carry over", async () => {
  win.__shengjiOriginMove = { origin: window.location.origin, entries: { "shengji.name": "Mei" }, session: true };
  const { auth, view } = await mount();
  expect(auth.state.status).toBe("out");
  expect(view).toMatchObject({ editing: true, toSignIn: true, name: "Mei" });
});

it("stays closed when the session carried over", async () => {
  me = { name: "Mei Li", email: "m@x", picture: null, display_name: null, name_shown: "Mei" };
  win.__shengjiOriginMove = { origin: window.location.origin, entries: {}, session: true };
  const { auth, view } = await mount();
  expect(auth.state.status).toBe("in");
  expect(view.editing).toBe(false);
});

it("stays closed for a guest's move and on the website", async () => {
  win.__shengjiOriginMove = { origin: window.location.origin, entries: { "shengji.name": "Mei" }, session: false };
  expect((await mount()).view.editing).toBe(false);
  act(() => root.unmount());
  host.remove();
  delete win.__shengjiOriginMove;
  vi.resetModules();
  localStorage.clear();
  expect((await mount()).view.editing).toBe(false);
});
