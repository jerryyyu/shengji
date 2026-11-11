// The leaderboard and My stats are hash routes shown only to a signed-in
// account: a guest landing on the hash gets the lobby.
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

let signedIn = true;
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  FakeWS.all = [];
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  (window as unknown as { AudioContext: unknown }).AudioContext = class {
    state = "running";
    resume() { return Promise.resolve(); }
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/me" && !signedIn) return { status: 401, json: async () => ({}) } as Response;
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : url.startsWith("/api/leaderboard") ? { period: "week", players: [], me: null, anchor: { name: "Sheng Ji bot", rating: 1500 } }
      : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

async function renderApp() {
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

it("a signed-in player on #/leaderboard sees the leaderboard", async () => {
  signedIn = true;
  window.history.replaceState(null, "", "/#/leaderboard");
  await renderApp();
  expect(host.querySelector(".games-title")?.textContent).toBe("Leaderboard");
  expect(host.querySelector(".lb-row.anchor")?.textContent).toContain("Sheng Ji bot");
});

it("a guest on #/leaderboard or #/stats gets the lobby", async () => {
  signedIn = false;
  window.history.replaceState(null, "", "/#/stats");
  await renderApp();
  expect(host.querySelector(".games-title")).toBeNull();
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  expect(host.querySelector(".account-leaderboard")).toBeNull();
  expect(host.querySelector(".signin-upsell")?.textContent).toBe(
    "Sign in to save your games and join the leaderboard.");
});
