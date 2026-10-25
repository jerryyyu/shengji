import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  auth, checkDisplayName, effectiveName, fetchAuthConfig, fetchMe, firstName, loadGis, loginWithGoogle,
  logout, NameRejected, newNonce, updateDisplayName,
} from "./auth";

const { reconnect } = vi.hoisted(() => ({ reconnect: vi.fn() }));
vi.mock("./ws", () => ({ conn: { reconnect } }));

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
  reconnect.mockClear();
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
    // an older server (no display-name fields) still yields a complete user
    expect(await fetchMe()).toEqual({
      name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
    });
    routes.set("GET /api/me", { status: 200, body: {
      name: "Jerry Yu", email: "j@x", picture: null, display_name: "Cap", name_shown: "Cap" } });
    expect(await fetchMe()).toMatchObject({ display_name: "Cap", name_shown: "Cap" });
    expect(calls.every((c) => c.init?.credentials === "same-origin")).toBe(true);
  });
  it("login posts JSON with the credential and nonce; a refusal throws its detail", async () => {
    routes.set("POST /api/auth/google", { status: 200, body: {
      name: "J", email: "j@x", picture: "p", display_name: null, name_shown: "J" } });
    expect(await loginWithGoogle("tok", "n1")).toEqual({
      name: "J", email: "j@x", picture: "p", display_name: null, name_shown: "J" });
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(JSON.parse(post.init!.body as string)).toEqual({ credential: "tok", nonce: "n1" });
    expect((post.init!.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    routes.set("POST /api/auth/google", { status: 401, body: { detail: "Sign-in rejected (bad_audience)." } });
    await expect(loginWithGoogle("tok", "n1")).rejects.toThrow("bad_audience");
    routes.set("POST /api/auth/google", { status: 404 });
    await expect(loginWithGoogle("tok", "n1")).rejects.toThrow("404");
  });
});

describe("display names", () => {
  it("checkDisplayName mirrors the server's rules", () => {
    expect(checkDisplayName("  Jerry   Yu ")).toEqual({ ok: true, value: "Jerry Yu" });
    expect(checkDisplayName("小明")).toEqual({ ok: true, value: "小明" });
    expect(checkDisplayName("Robot")).toEqual({ ok: true, value: "Robot" });
    const reason = (s: string) => { const c = checkDisplayName(s); return c.ok ? "ok" : c.reason; };
    expect(reason("")).toBe("empty");
    expect(reason("   ")).toBe("empty");
    expect(reason("x".repeat(21))).toBe("too_long");
    expect(reason("a\nb")).toBe("control_chars");
    expect(reason("a\tb")).toBe("control_chars");
    expect(reason("Bot 1")).toBe("reserved");
    expect(reason("BOT")).toBe("reserved");
    expect(reason("System")).toBe("reserved");
    expect(reason("admin")).toBe("reserved");
    expect(reason("dealer")).toBe("reserved");
    const c = checkDisplayName("Bot 1");
    expect(!c.ok && c.message).toContain("reserved");
  });
  it("effectiveName prefers name_shown, then the first name", () => {
    expect(effectiveName(null)).toBe("");
    expect(effectiveName({ name: "Jerry Yu", email: "", picture: null, display_name: "Cap", name_shown: "Cap" })).toBe("Cap");
    expect(effectiveName({ name: "Jerry Yu", email: "", picture: null, display_name: null, name_shown: "" })).toBe("Jerry");
  });
  it("updateDisplayName PATCHes JSON; a 400 rejects with the reason's message; updated() notifies", async () => {
    const user = { name: "Jerry Yu", email: "j@x", picture: null, display_name: "Cap", name_shown: "Cap" };
    routes.set("PATCH /api/me", { status: 200, body: user });
    expect(await updateDisplayName("Cap")).toEqual(user);
    const patch = calls.find((c) => c.init?.method === "PATCH")!;
    expect(JSON.parse(patch.init!.body as string)).toEqual({ display_name: "Cap" });
    expect(patch.init?.credentials).toBe("same-origin");
    routes.set("PATCH /api/me", { status: 400, body: { detail: "reserved" } });
    const err = await updateDisplayName("Bot 1").catch((e: Error) => e);
    expect(err).toBeInstanceOf(NameRejected);
    expect((err as NameRejected).reason).toBe("reserved");
    expect((err as Error).message).toContain("reserved for bots");
    routes.set("PATCH /api/me", { status: 401 });
    await expect(updateDisplayName("X")).rejects.toThrow("401");
    // clearing sends null
    routes.set("PATCH /api/me", { status: 200, body: { ...user, display_name: null, name_shown: "Jerry" } });
    await updateDisplayName(null);
    const last = calls.filter((c) => c.init?.method === "PATCH").at(-1)!;
    expect(JSON.parse(last.init!.body as string)).toEqual({ display_name: null });

    const seen: (string | null)[] = [];
    auth.signedIn({ ...user, display_name: null, name_shown: "Jerry" });
    const unsub = auth.subscribe((s) => seen.push(s.user?.name_shown ?? null));
    auth.updated(user);
    expect(seen).toEqual(["Jerry", "Cap"]);
    unsub();
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
    auth.signedIn({ name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry" });
    expect(auth.state.status).toBe("in");
    // the open socket carried the guest handshake: it is replaced
    expect(reconnect).toHaveBeenCalledTimes(1);
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await auth.signOut();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null });
    expect(reconnect).toHaveBeenCalledTimes(2);   // and again, so the seat drops the account
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

describe("sign-out honesty (Codex review1155 P2)", () => {
  it("does not report signed out when revocation failed with a 500", async () => {
    auth.signedIn({ name: "Jerry", email: "j@example.test", picture: null, display_name: null, name_shown: "Jerry" });
    reconnect.mockClear();
    routes.set("POST /api/auth/logout", { status: 500, body: { detail: "database unavailable" } });
    await expect(auth.signOut()).rejects.toThrow("Sign-out failed (500)");
    expect(auth.state.status).toBe("in");
    expect(auth.state.user?.name).toBe("Jerry");
    expect(reconnect).not.toHaveBeenCalled();
    // a retry that succeeds completes the sign-out
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await auth.signOut();
    expect(auth.state.status).toBe("out");
    expect(reconnect).toHaveBeenCalledTimes(1);
  });
  it("a network failure keeps the signed-in state and names the retry", async () => {
    auth.signedIn({ name: "Jerry", email: "j@example.test", picture: null, display_name: null, name_shown: "Jerry" });
    reconnect.mockClear();
    globalThis.fetch = vi.fn(async () => { throw new TypeError("Failed to fetch"); }) as typeof fetch;
    await expect(auth.signOut()).rejects.toThrow("no connection");
    await expect(logout()).rejects.toThrow("Try again");
    expect(auth.state.status).toBe("in");
    expect(reconnect).not.toHaveBeenCalled();
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
