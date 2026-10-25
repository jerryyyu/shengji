import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  auth, fetchAuthConfig, fetchMe, firstName, loadGis, loginWithGoogle, newNonce,
} from "./auth";

type Route = { status: number; body?: unknown };
const routes = new Map<string, Route>();
const calls: { url: string; init?: RequestInit }[] = [];

function mockFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const r = routes.get(`${init?.method ?? "GET"} ${url}`) ?? { status: 404 };
    return {
      status: r.status,
      json: async () => {
        if (r.body === undefined) throw new Error("no body");
        return r.body;
      },
    } as Response;
  }) as typeof fetch;
}

beforeEach(() => {
  routes.clear();
  calls.length = 0;
  auth.reset();
  mockFetch();
  delete window.google;
  document.head.querySelectorAll("script").forEach((s) => s.remove());
});
afterEach(() => { vi.restoreAllMocks(); });

describe("firstName / nonce", () => {
  it("takes the first word, capped at 20 characters", () => {
    expect(firstName("Jerry Yu")).toBe("Jerry");
    expect(firstName("  Yu ")).toBe("Yu");
    expect(firstName("")).toBe("");
    expect(firstName(null)).toBe("");
    expect(firstName("x".repeat(40))).toHaveLength(20);
  });
  it("nonces are 32 hex chars and differ", () => {
    const a = newNonce(), b = newNonce();
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(a).not.toBe(b);
  });
});

describe("the API wrappers", () => {
  it("config: null on 200-null, on 404 and on a bodyless answer", async () => {
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid" } });
    expect(await fetchAuthConfig()).toEqual({ google_client_id: "cid" });
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: null } });
    expect(await fetchAuthConfig()).toEqual({ google_client_id: null });
    routes.delete("GET /api/auth/config");
    expect(await fetchAuthConfig()).toEqual({ google_client_id: null });
  });
  it("me: the user on 200, null on 401; the cookie rides same-origin", async () => {
    routes.set("GET /api/me", { status: 401, body: { detail: "Not signed in." } });
    expect(await fetchMe()).toBeNull();
    routes.set("GET /api/me", { status: 200, body: { name: "Jerry Yu", email: "j@x", picture: null } });
    expect(await fetchMe()).toEqual({ name: "Jerry Yu", email: "j@x", picture: null });
    expect(calls.every((c) => c.init?.credentials === "same-origin")).toBe(true);
  });
  it("login posts JSON with the credential and nonce; a refusal throws its detail", async () => {
    routes.set("POST /api/auth/google", { status: 200, body: { name: "J", email: "j@x", picture: "p" } });
    expect(await loginWithGoogle("tok", "n1")).toEqual({ name: "J", email: "j@x", picture: "p" });
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(JSON.parse(post.init!.body as string)).toEqual({ credential: "tok", nonce: "n1" });
    expect((post.init!.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    routes.set("POST /api/auth/google", { status: 401, body: { detail: "Sign-in rejected (bad_audience)." } });
    await expect(loginWithGoogle("tok", "n1")).rejects.toThrow("bad_audience");
    routes.set("POST /api/auth/google", { status: 404 });
    await expect(loginWithGoogle("tok", "n1")).rejects.toThrow("404");
  });
});

describe("the auth store", () => {
  it("feature off: status 'off', no /api/me call, no GIS script", async () => {
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: null } });
    await auth.init();
    expect(auth.state).toEqual({ status: "off", clientId: null, user: null });
    expect(calls.map((c) => c.url)).toEqual(["/api/auth/config"]);
    expect(document.head.querySelector("script[src*='gsi/client']")).toBeNull();
  });
  it("a server without the endpoint (older deploy) reads as off", async () => {
    await auth.init();
    expect(auth.state.status).toBe("off");
  });
  it("feature on, signed out, then a sign-in and a sign-out", async () => {
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid" } });
    routes.set("GET /api/me", { status: 401 });
    const seen: string[] = [];
    const unsub = auth.subscribe((s) => seen.push(s.status));
    await auth.init();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null });
    auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null });
    expect(auth.state.status).toBe("in");
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await auth.signOut();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null });
    expect(seen).toEqual(["loading", "out", "in", "out"]);
    unsub();
    await auth.init();                       // idempotent
    expect(calls.filter((c) => c.url === "/api/auth/config")).toHaveLength(1);
  });
  it("feature on with a live cookie: signed in from the first paint", async () => {
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid" } });
    routes.set("GET /api/me", { status: 200, body: { name: "Jerry Yu", email: "j@x", picture: "p" } });
    await auth.init();
    expect(auth.state.status).toBe("in");
    expect(auth.state.user?.name).toBe("Jerry Yu");
  });
});

describe("loadGis", () => {
  it("injects the script once and resolves with window.google.accounts.id", async () => {
    const p1 = loadGis();
    const p2 = loadGis();
    const scripts = document.head.querySelectorAll("script[src='https://accounts.google.com/gsi/client']");
    expect(scripts).toHaveLength(1);
    const fake = { initialize: vi.fn(), renderButton: vi.fn(), disableAutoSelect: vi.fn() };
    window.google = { accounts: { id: fake } };
    (scripts[0] as HTMLScriptElement).onload!(new Event("load"));
    expect(await p1).toBe(fake);
    expect(await p2).toBe(fake);
    expect(await loadGis()).toBe(fake);      // already present: no second script
    expect(document.head.querySelectorAll("script")).toHaveLength(1);
  });
  it("a failed load rejects and can be retried", async () => {
    const p = loadGis();
    const script = document.head.querySelector("script")!;
    script.onerror!(new Event("error"));
    await expect(p).rejects.toThrow("Could not load");
    expect(document.head.querySelectorAll("script")).toHaveLength(0);
    void loadGis();
    expect(document.head.querySelectorAll("script")).toHaveLength(1);
  });
});
