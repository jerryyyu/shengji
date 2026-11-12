// Saved games are the Me tab's Games section, a hash route over the live
// app: opening it leaves the socket alone, and Play returns to the lobby.
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
    const body = url === "/api/auth/config" ? { google_client_id: "cid" }
      : url === "/api/me" ? { name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" }
      : url.startsWith("/api/me/games?") ? { games: [], next_before: null } : null;
    return { status: body ? 200 : 404, json: async () => body ?? {} } as Response;
  }) as typeof fetch;
  vi.resetModules();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});

it("Me's Games opens the saved games and the Play tab returns, leaving the socket alone", async () => {
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const tab = (label: string) =>
    [...host.querySelectorAll<HTMLButtonElement>(".tabbar-item")].find((b) => b.textContent === label)!;
  await act(async () => { tab("Me").click(); await new Promise((r) => setTimeout(r, 0)); });
  const games = [...host.querySelectorAll<HTMLButtonElement>(".segmented-btn")].find((b) => b.textContent === "Games")!;
  await act(async () => { games.click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(window.location.hash).toBe("#/me/games");
  expect(host.querySelector(".games-status")?.textContent).toContain("No saved games yet");
  expect(host.querySelector(".lobby-panel")).toBeNull();
  expect(FakeWS.all).toHaveLength(1);       // the socket was not touched
  await act(async () => { tab("Play").click(); await new Promise((r) => setTimeout(r, 0)); });
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  expect(window.location.hash).toBe("");
});

it("opens the usual screens when the hash holds a malformed escape", async () => {
  window.history.replaceState(null, "", "/#/games/%");
  const { default: App } = await import("./App");
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root.render(<App />); });
  expect(host.querySelector(".lobby-panel")).not.toBeNull();
  expect(host.querySelector(".games-title")).toBeNull();
});
