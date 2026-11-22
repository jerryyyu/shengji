// The app's device account: made or signed in at the first online Play, Duo
// or Join, signed in again at launch, its Keychain secret cleared when the
// account is gone, deleted or signed out; nothing of it on the website.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { reconnect, status, listeners } = vi.hoisted(() => ({
  reconnect: vi.fn(),
  status: { current: "open" as string },
  listeners: new Set<(s: string) => void>(),
}));
vi.mock("./ws", () => ({
  conn: {
    reconnect,
    subscribeStatus: (fn: (s: string) => void) => {
      listeners.add(fn);
      fn(status.current);
      return () => { listeners.delete(fn); };
    },
  },
}));

import {
  AccountExists, auth, deviceAccountPending, deviceAccountsApply, deviceSecretOutstanding, identityTurn, keepDeviceSecret,
  reauthFromKeychain, isUnlinkedDevice, loginWithApple, loginWithGoogle, NAME_MESSAGES,
  NameRejected, updateDisplayName,
} from "./auth";
import { beforeOnlineSetup, lastSetupOutcome, resetDeviceAccountForTests } from "./deviceAccount";

type Route = { status: number; body?: unknown };
let routes: Map<string, Route | Route[]>;
let calls: { url: string; method: string; headers: Record<string, string>; body: unknown }[];

function mockFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ url, method, headers: { ...(init?.headers as Record<string, string> | undefined) },
                 body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const got = routes.get(`${method} ${url}`);
    const r = Array.isArray(got) ? got.shift() ?? { status: 404 } : got ?? { status: 404 };
    return {
      status: r.status,
      json: async () => {
        if (r.body === undefined) throw new Error("no body");
        return r.body;
      },
    } as Response;
  }) as typeof fetch;
}

/** The app's shell: iOS (or `platform`), with a Keychain kept in memory. */
function shell(platform = "ios", keychain = true) {
  const store = { value: null as string | null, calls: [] as string[], failGet: 0, failSet: 0, failRemove: 0,
                  holdSet: null as Promise<void> | null };
  const refuse = (n: "failGet" | "failSet" | "failRemove") => {
    if (store[n] <= 0) return;
    store[n] -= 1;
    throw Object.assign(new Error("keychain"), { code: "-25308" });
  };
  const methods: Record<string, (opts?: { value?: string }) => Promise<unknown>> = {
    get: async () => { refuse("failGet"); return { value: store.value }; },
    set: async (opts) => {
      if (store.holdSet) { const hold = store.holdSet; store.holdSet = null; await hold; }
      refuse("failSet");
      store.value = opts?.value ?? null;
    },
    remove: async () => { refuse("failRemove"); store.value = null; },
  };
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => platform,
    isPluginAvailable: (name: string) => keychain && name === "ShengjiKeychain",
    registerPlugin: () => new Proxy({}, {
      get: (_t, m: string) => (opts?: { value?: string }) => {
        store.calls.push(m);
        return methods[m](opts);
      },
    }),
  };
  return store;
}

const DEVICE_USER = { name: "Gentle Tractor", email: "", picture: null, display_name: "Gentle Tractor",
                      name_shown: "Gentle Tractor", rounds_played: 0, linked: false };
const MEI = { name: "Mei Chen", email: "mei@x", picture: null, display_name: "Mei", name_shown: "Mei", rounds_played: 40, linked: true };
const flush = async () => { for (let i = 0; i < 3; i += 1) await new Promise((r) => setTimeout(r, 0)); };
const deviceCalls = () => calls.filter((c) => c.url === "/api/auth/device");
/** The replaced socket opens. */
const opens = () => { status.current = "open"; for (const fn of [...listeners]) fn("open"); };

beforeEach(() => {
  localStorage.clear();
  routes = new Map();
  calls = [];
  reconnect.mockClear();
  status.current = "open";
  listeners.clear();
  auth.reset();
  auth.state = { status: "out", clientId: "cid", user: null };
  resetDeviceAccountForTests();
  mockFetch();
});
afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  vi.useRealTimers();
});

describe("the gate", () => {
  it("on the website Play runs at once and nothing asks for a device account", async () => {
    const action = vi.fn();
    beforeOnlineSetup(action);
    expect(action).toHaveBeenCalledTimes(1);
    await flush();
    expect(deviceAccountsApply()).toBe(false);
    expect(calls).toEqual([]);
  });

  it("in a native shell that is not iOS, nothing changes either", async () => {
    shell("android");
    const action = vi.fn();
    beforeOnlineSetup(action);
    expect(action).toHaveBeenCalledTimes(1);
    await flush();
    expect(calls).toEqual([]);
  });

  it("in an iOS build without the Keychain plugin the player stays a guest", async () => {
    shell("ios", false);
    const action = vi.fn();
    beforeOnlineSetup(action);
    expect(action).toHaveBeenCalledTimes(1);
    await flush();
    expect(calls).toEqual([]);
  });

  it("a signed-in account plays at once, with no device call", async () => {
    shell();
    auth.state = { status: "in", clientId: "cid", user: MEI };
    const action = vi.fn();
    beforeOnlineSetup(action);
    expect(action).toHaveBeenCalledTimes(1);
    await flush();
    expect(calls).toEqual([]);
  });

  it("an account counts as the app's own only in the app and only when the server says it is not linked", () => {
    expect(isUnlinkedDevice(DEVICE_USER)).toBe(false);
    shell();
    expect(isUnlinkedDevice(DEVICE_USER)).toBe(true);
    expect(isUnlinkedDevice(MEI)).toBe(false);
    // an empty email alone is not taken as unlinked
    expect(isUnlinkedDevice({ ...MEI, email: "", linked: undefined })).toBe(false);
    expect(isUnlinkedDevice(null)).toBe(false);
  });
});

describe("the first online Play in the app", () => {
  it("with no secret, makes an account, keeps its token in the Keychain, signs in, then plays", async () => {
    const keychain = shell();
    status.current = "connecting";
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    const [call] = deviceCalls();
    expect(call.headers).toEqual({ "X-Shengji-Client": "ios-app" });
    expect(keychain.value).toBe("tok-new");
    expect(auth.state).toMatchObject({ status: "in", user: { name_shown: "Gentle Tractor" } });
    expect(reconnect).toHaveBeenCalledTimes(1);
    // the table is asked for once the account's socket is open
    expect(action).not.toHaveBeenCalled();
    for (const fn of [...listeners]) fn("open");
    await flush();
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("with a secret, signs in with it and keeps it", async () => {
    const keychain = shell();
    keychain.value = "tok-old";
    routes.set("POST /api/auth/device", { status: 200, body: { user: DEVICE_USER } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(deviceCalls()[0].headers).toEqual({ "X-Shengji-Client": "ios-app", Authorization: "Device tok-old" });
    expect(keychain.calls).not.toContain("set");
    expect(keychain.value).toBe("tok-old");
    expect(auth.state.status).toBe("in");
    // the Play waits for the socket to reopen as the account
    expect(action).not.toHaveBeenCalled();
    opens();
    await flush();
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("a refused secret (401) is cleared and this Play goes ahead as a guest; the next makes a fresh account", async () => {
    const keychain = shell();
    keychain.value = "tok-gone";
    routes.set("POST /api/auth/device", [{ status: 401, body: { detail: "Device sign-in rejected (unknown)." } },
      { status: 200, body: { token: "tok-fresh", user: DEVICE_USER } }]);
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(keychain.value).toBeNull();
    expect(auth.state.status).toBe("out");
    expect(action).toHaveBeenCalledTimes(1);
    expect(reconnect).not.toHaveBeenCalled();
    beforeOnlineSetup(action);
    await flush();
    expect(deviceCalls()[1].headers).toEqual({ "X-Shengji-Client": "ios-app" });
    expect(keychain.value).toBe("tok-fresh");
    opens();
    await flush();
    expect(action).toHaveBeenCalledTimes(2);
  });

  it("device accounts off (404): a guest exactly as today, and the page stops asking", async () => {
    const keychain = shell();
    routes.set("POST /api/auth/device", { status: 404, body: { detail: "Not Found" } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(action).toHaveBeenCalledTimes(1);
    expect(auth.state.status).toBe("out");
    expect(keychain.value).toBeNull();
    expect(reconnect).not.toHaveBeenCalled();
    beforeOnlineSetup(action);
    expect(action).toHaveBeenCalledTimes(2);
    await flush();
    expect(deviceCalls()).toHaveLength(1);
  });

  it("too many attempts (429): a guest this time, and a later Play asks again", async () => {
    const keychain = shell();
    routes.set("POST /api/auth/device", { status: 429, body: { detail: "Too many new accounts; play as a guest for now." } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(action).toHaveBeenCalledTimes(1);
    expect(auth.state.status).toBe("out");
    expect(keychain.value).toBeNull();
    beforeOnlineSetup(action);
    await flush();
    expect(deviceCalls()).toHaveLength(2);
    expect(action).toHaveBeenCalledTimes(2);
  });

  it("no connection: a guest this time", async () => {
    shell();
    globalThis.fetch = vi.fn(async () => { throw new TypeError("Failed to fetch"); }) as typeof fetch;
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(action).toHaveBeenCalledTimes(1);
    expect(auth.state.status).toBe("out");
  });

  it("a second tap while the first signs in, or while the socket reopens, does nothing", async () => {
    shell();
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    const action = vi.fn();
    const second = vi.fn();
    beforeOnlineSetup(action);
    beforeOnlineSetup(second);
    await flush();
    // signed in now, the socket not yet reopened: still the same attempt
    expect(auth.state.status).toBe("in");
    beforeOnlineSetup(second);
    opens();
    await flush();
    expect(deviceCalls()).toHaveLength(1);
    expect(action).toHaveBeenCalledTimes(1);
    expect(second).not.toHaveBeenCalled();
    // once it has settled, a new tap goes at once
    beforeOnlineSetup(second);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("a join made by the held action runs at once: one attempt per tap", async () => {
    shell();
    routes.set("POST /api/auth/device", { status: 429, body: {} });
    const inner = vi.fn();
    beforeOnlineSetup(() => beforeOnlineSetup(inner));
    await flush();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(deviceCalls()).toHaveLength(1);
  });

  it("a held action whose place is gone does not fire", async () => {
    shell();
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    const action = vi.fn();
    let wanted = true;
    beforeOnlineSetup(action, () => wanted);
    await flush();
    wanted = false;
    opens();
    await flush();
    expect(action).not.toHaveBeenCalled();
    const moved = vi.fn();
    auth.state = { status: "out", clientId: "cid", user: null };
    resetDeviceAccountForTests();
    beforeOnlineSetup(moved);
    window.history.replaceState(null, "", "/#/me");
    await flush();
    opens();
    await flush();
    expect(moved).not.toHaveBeenCalled();
    window.history.replaceState(null, "", "/");
  });

  it("the bound covers sign-in too: past 6 s the tap is given up with nothing sent, and a late answer sends nothing", async () => {
    vi.useFakeTimers();
    shell();
    let answer!: (r: Response) => void;
    globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? "GET", headers: {}, body: undefined });
      return new Promise<Response>((r) => { answer = r; });
    }) as typeof fetch;
    const action = vi.fn();
    const gaveUp = vi.fn();
    beforeOnlineSetup(action, () => true, gaveUp);
    await vi.advanceTimersByTimeAsync(5900);
    expect(gaveUp).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(200);
    expect(gaveUp).toHaveBeenCalledTimes(1);
    expect(lastSetupOutcome()).toBe("timed_out");
    // a tap while that sign-in still runs waits for it: no second request
    const next = vi.fn();
    beforeOnlineSetup(next);
    answer({ status: 200, json: async () => ({ token: "tok-new", user: DEVICE_USER }) } as Response);
    await vi.advanceTimersByTimeAsync(10);
    expect(auth.state.status).toBe("in");
    expect(action).not.toHaveBeenCalled();
    expect(next).not.toHaveBeenCalled();
    opens();
    await vi.advanceTimersByTimeAsync(10);
    expect(action).not.toHaveBeenCalled();
    expect(next).toHaveBeenCalledTimes(1);
    expect(calls.filter((c) => c.url === "/api/auth/device")).toHaveLength(1);
  });

  it("a socket that never reopens: the tap is given up at 6 s, and fires never", async () => {
    vi.useFakeTimers();
    shell();
    status.current = "connecting";
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    const action = vi.fn();
    const gaveUp = vi.fn();
    beforeOnlineSetup(action, () => true, gaveUp);
    await vi.advanceTimersByTimeAsync(6100);
    expect(gaveUp).toHaveBeenCalledTimes(1);
    opens();
    await vi.advanceTimersByTimeAsync(10);
    expect(action).not.toHaveBeenCalled();
  });
});

describe("the Keychain failing", () => {
  it("a read error is not an empty Keychain: no account is made, this Play is a guest's", async () => {
    const keychain = shell();
    keychain.value = "tok-kept";
    keychain.failGet = 1;
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(deviceCalls()).toEqual([]);
    expect(keychain.value).toBe("tok-kept");
    expect(action).toHaveBeenCalledTimes(1);
    expect(lastSetupOutcome()).toBe("read_failed");
    // the next Play reads it and signs in with it
    routes.set("POST /api/auth/device", { status: 200, body: { user: DEVICE_USER } });
    beforeOnlineSetup(action);
    await flush();
    expect(deviceCalls()[0].headers.Authorization).toBe("Device tok-kept");
  });

  it("a write refused once is tried again and kept", async () => {
    const keychain = shell();
    keychain.failSet = 1;
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    beforeOnlineSetup(() => {});
    await flush();
    expect(keychain.value).toBe("tok-new");
    expect(auth.state.status).toBe("in");
  });

  it("a write refused twice keeps the account signed in on the cookie, deletes nothing, holds the secret in memory only, and saves it on a later Play", async () => {
    const keychain = shell();
    keychain.failSet = 2;
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    opens();
    await flush();
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["POST /api/auth/device"]);
    expect(keychain.value).toBeNull();
    expect(auth.state.status).toBe("in");
    expect(action).toHaveBeenCalledTimes(1);
    expect(lastSetupOutcome()).toBe("unsaved");
    expect(deviceSecretOutstanding()).toBe(true);
    // never in the page's storage
    expect(Object.values({ ...localStorage }).join()).not.toContain("tok-new");
    // the Keychain recovers: the next Play offers it again
    beforeOnlineSetup(action);
    await flush();
    expect(keychain.value).toBe("tok-new");
    expect(deviceSecretOutstanding()).toBe(false);
  });

  it("while a secret is still owed to the Keychain, no other account is made", async () => {
    const keychain = shell();
    keychain.failSet = 4;
    await keepDeviceSecret("tok-owed");
    expect(deviceSecretOutstanding()).toBe(true);
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-second", user: DEVICE_USER } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    expect(deviceCalls()).toEqual([]);
    expect(lastSetupOutcome()).toBe("read_failed");
    expect(action).toHaveBeenCalledTimes(1);
    expect(keychain.value).toBeNull();
  });

  it("a provider sign-in during a storage failure deletes nothing and waits its turn; its own secret is the one kept", async () => {
    const keychain = shell();
    let release!: () => void;
    keychain.holdSet = new Promise<void>((r) => { release = r; });
    keychain.failSet = 2;
    routes.set("POST /api/auth/device", { status: 200, body: { token: "tok-new", user: DEVICE_USER } });
    routes.set("POST /api/auth/google", { status: 200, body: { ...MEI, device_token: "tok-mei" } });
    const action = vi.fn();
    beforeOnlineSetup(action);
    await flush();
    // while the Keychain holds the write, the player signs in with Google, as GoogleSignIn does
    const signing = identityTurn(async () => { auth.signedIn(await loginWithGoogle("jwt", "n1")); });
    await flush();
    // its request waits for the device's turn
    expect(calls.filter((c) => c.url === "/api/auth/google")).toEqual([]);
    release();
    await signing;
    await flush();
    opens();
    await flush();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    expect(calls.map((c) => c.url)).toEqual(["/api/auth/device", "/api/auth/google"]);
    expect(auth.state.user?.name_shown).toBe("Mei");
    expect(keychain.value).toBe("tok-mei");
    expect(deviceSecretOutstanding()).toBe(false);
  });

  it("sign-in, then an immediate sign-out, with a slow Keychain write: the next launch does not restore the account", async () => {
    const keychain = shell();
    keychain.value = "tok-device";
    let release!: () => void;
    keychain.holdSet = new Promise<void>((r) => { release = r; });
    auth.state = { status: "in", clientId: "cid", user: DEVICE_USER };
    routes.set("POST /api/auth/google", { status: 200, body: { ...MEI, device_token: "tok-mei" } });
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    const signing = identityTurn(async () => { auth.signedIn(await loginWithGoogle("jwt", "n1")); });
    const out = auth.signOut();
    await flush();
    release();
    await signing;
    await out;
    expect(auth.state.status).toBe("out");
    // the sign-out came after the merge's write and sent the secret it left
    expect(calls.find((c) => c.url === "/api/auth/logout")!.headers).toEqual({ Authorization: "Device tok-mei" });
    expect(keychain.value).toBeNull();
    routes.set("POST /api/auth/device", { status: 200, body: { user: MEI } });
    expect(await reauthFromKeychain()).toBeNull();
    expect(deviceCalls()).toEqual([]);
  });

  it("signed in as A with the switch off, removal refused twice: sign-out fails, A stays signed in, and a retry signs out for good", async () => {
    const keychain = shell();
    keychain.value = "tok-a";
    keychain.failRemove = 2;
    auth.state = { status: "in", clientId: "cid", user: MEI };
    // the switch is off: the server would end the session and leave the secret alone
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await expect(auth.signOut()).rejects.toThrow("Sign-out failed. Try again.");
    expect(calls.filter((c) => c.url === "/api/auth/logout")).toEqual([]);
    expect(auth.state.status).toBe("in");
    expect(keychain.value).toBe("tok-a");
    // nothing in the page's storage stands for the sign-out
    expect({ ...localStorage }).toEqual({});
    // tapping again, the Keychain now removes it
    await auth.signOut();
    expect(auth.state.status).toBe("out");
    expect(keychain.value).toBeNull();
    // relaunch with the page's storage gone and the switch on: A is not restored
    localStorage.clear();
    auth.reset();
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid", device_accounts: true } });
    routes.set("POST /api/auth/device", { status: 200, body: { user: MEI } });
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(deviceCalls()).toEqual([]);
    expect(auth.state.status).toBe("out");
  });

  it("page storage that cannot be read changes nothing: sign-out rests on the Keychain alone", async () => {
    const keychain = shell();
    keychain.value = "tok-a";
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
    await auth.signOut();
    getItem.mockRestore();
    expect(auth.state.status).toBe("out");
    expect(keychain.value).toBeNull();
  });

  it("logout 503 after the removal, with the Keychain refusing it back: still signed in, the secret held in memory, and a retry sends it", async () => {
    const keychain = shell();
    keychain.value = "tok-a";
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", [{ status: 503, body: {} }, { status: 200, body: { ok: true } }]);
    keychain.failSet = 2;
    await expect(auth.signOut()).rejects.toThrow("Sign-out failed. Try again.");
    expect(auth.state.status).toBe("in");
    expect(keychain.value).toBeNull();
    expect(deviceSecretOutstanding()).toBe(true);
    await auth.signOut();
    const logouts = calls.filter((c) => c.url === "/api/auth/logout");
    expect(logouts.map((c) => c.headers.Authorization)).toEqual(["Device tok-a", "Device tok-a"]);
    expect(auth.state.status).toBe("out");
    expect(deviceSecretOutstanding()).toBe(false);
  });

  it("logout 503 after the removal, with the Keychain taking it back: still signed in and the Keychain has it again", async () => {
    const keychain = shell();
    keychain.value = "tok-a";
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", { status: 503, body: {} });
    await expect(auth.signOut()).rejects.toThrow("Sign-out failed. Try again.");
    expect(auth.state.status).toBe("in");
    expect(keychain.value).toBe("tok-a");
    expect(deviceSecretOutstanding()).toBe(false);
  });

  it("the newest secret is the one sent: a merge's held in memory over an older one in the Keychain, kept for the retry", async () => {
    const keychain = shell();
    keychain.value = "tok-old";
    keychain.failSet = 2;
    await keepDeviceSecret("tok-mei");
    expect(keychain.value).toBe("tok-old");
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", [{ status: 503, body: {} }, { status: 200, body: { ok: true } }]);
    keychain.failSet = 2;
    await expect(auth.signOut()).rejects.toThrow("Sign-out failed. Try again.");
    expect(deviceSecretOutstanding()).toBe(true);
    await auth.signOut();
    const logouts = calls.filter((c) => c.url === "/api/auth/logout");
    expect(logouts.map((c) => c.headers.Authorization)).toEqual(["Device tok-mei", "Device tok-mei"]);
    expect(auth.state.status).toBe("out");
    expect(keychain.value).toBeNull();
  });

  it("sign-out with an unreadable Keychain is refused, not reported done", async () => {
    const keychain = shell();
    keychain.value = "tok-mei";
    keychain.failGet = 1;
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await expect(auth.signOut()).rejects.toThrow("Sign-out failed. Try again.");
    expect(calls.filter((c) => c.url === "/api/auth/logout")).toEqual([]);
    expect(auth.state.status).toBe("in");
    expect(keychain.value).toBe("tok-mei");
    // the retry works and clears it
    await auth.signOut();
    expect(keychain.value).toBeNull();
    expect(auth.state.status).toBe("out");
  });

  it("a removal refused once is tried again; once it is gone and the server confirms, sign-out is done", async () => {
    const keychain = shell();
    keychain.value = "tok-mei";
    keychain.failRemove = 1;
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await auth.signOut();
    expect(calls.find((c) => c.url === "/api/auth/logout")!.headers).toEqual({ Authorization: "Device tok-mei" });
    expect(auth.state.status).toBe("out");
    expect(keychain.value).toBeNull();
  });
});

describe("launch", () => {
  beforeEach(() => {
    auth.reset();
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid" } });
  });

  it("with a secret, signs in with it before anything else", async () => {
    const keychain = shell();
    keychain.value = "tok-old";
    routes.set("POST /api/auth/device", { status: 200, body: { user: DEVICE_USER } });
    await auth.init();
    expect(auth.state).toMatchObject({ status: "in", clientId: "cid", user: { name_shown: "Gentle Tractor" } });
    expect(deviceCalls()[0].headers.Authorization).toBe("Device tok-old");
    expect(calls.map((c) => c.url)).not.toContain("/api/me");
  });

  it("with a secret the server no longer knows (401), clears it and starts as a guest", async () => {
    const keychain = shell();
    keychain.value = "tok-gone";
    routes.set("POST /api/auth/device", { status: 401, body: {} });
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(keychain.value).toBeNull();
    expect(auth.state.status).toBe("out");
  });

  it("with device accounts off (404), keeps the secret and starts as today", async () => {
    const keychain = shell();
    keychain.value = "tok-old";
    routes.set("POST /api/auth/device", { status: 404, body: {} });
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(keychain.value).toBe("tok-old");
    expect(auth.state.status).toBe("out");
  });

  it("with no secret, makes no account at launch", async () => {
    shell();
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(deviceCalls()).toEqual([]);
    expect(auth.state.status).toBe("out");
  });

  it("with device accounts on, the app knows before its first Play; off, it does not", async () => {
    shell();
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid", device_accounts: true } });
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null, deviceAccounts: true });
    expect(deviceAccountPending(auth.state)).toBe(true);
    auth.reset();
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid", device_accounts: false } });
    await auth.init();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null });
    expect(deviceAccountPending(auth.state)).toBe(false);
  });

  it("an iOS build without the Keychain plugin is not pending, the switch on or not", async () => {
    shell("ios", false);
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid", device_accounts: true } });
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(deviceAccountPending(auth.state)).toBe(false);
  });

  it("on the website the switch changes nothing", async () => {
    routes.set("GET /api/auth/config", { status: 200, body: { google_client_id: "cid", device_accounts: true } });
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null });
  });

  it("a 404 at the first Play (the switch turned off since launch) drops the pending state", async () => {
    shell();
    auth.state = { status: "out", clientId: "cid", user: null, deviceAccounts: true };
    routes.set("POST /api/auth/device", { status: 404, body: {} });
    beforeOnlineSetup(() => {});
    await flush();
    expect(auth.state).toEqual({ status: "out", clientId: "cid", user: null });
  });

  it("on the website, launch is unchanged: config then /api/me", async () => {
    routes.set("GET /api/me", { status: 401, body: {} });
    await auth.init();
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["GET /api/auth/config", "GET /api/me"]);
  });
});

describe("linking", () => {
  it("a 409 account_exists is the conflict, with the holder's name; confirm repeats it", async () => {
    const keychain = shell();
    keychain.value = "tok-device";
    routes.set("POST /api/auth/google", [
      { status: 409, body: { detail: { code: "account_exists", name: "Mei" } } },
      { status: 200, body: { ...MEI, device_token: "tok-mei" } },
    ]);
    const err = await loginWithGoogle("jwt", "n1").catch((e) => e);
    expect(err).toBeInstanceOf(AccountExists);
    expect(err.holder).toBe("Mei");
    expect(keychain.value).toBe("tok-device");
    const user = await loginWithGoogle("jwt", "n1", true);
    expect(calls.map((c) => c.body)).toEqual([{ credential: "jwt", nonce: "n1" },
      { credential: "jwt", nonce: "n1", confirm: true }]);
    expect(user.name_shown).toBe("Mei");
    // the merge's new device credential replaces the deleted account's
    expect(keychain.value).toBe("tok-mei");
  });

  it("Apple's sign-in carries confirm the same way", async () => {
    shell();
    routes.set("POST /api/auth/apple", { status: 409, body: { detail: { code: "account_exists", name: "Mei" } } });
    const login = { identityToken: "a.jwt", nonce: "n", authorizationCode: "c", givenName: null, familyName: null };
    await expect(loginWithApple(login)).rejects.toBeInstanceOf(AccountExists);
    await loginWithApple(login, true).catch(() => {});
    expect(calls[0].body).not.toHaveProperty("confirm");
    expect(calls[1].body).toMatchObject({ confirm: true });
  });

  it("on the website a device_token is never kept", async () => {
    routes.set("POST /api/auth/google", { status: 200, body: { ...MEI, device_token: "tok-mei" } });
    const user = await loginWithGoogle("jwt", "n1");
    expect(user.name_shown).toBe("Mei");
    expect(user).not.toHaveProperty("device_token");
  });
});

describe("delete and sign out", () => {
  it("a deleted account's secret is cleared from the Keychain", async () => {
    const keychain = shell();
    keychain.value = "tok-device";
    auth.state = { status: "in", clientId: "cid", user: DEVICE_USER };
    auth.deleted();
    await flush();
    expect(keychain.value).toBeNull();
    expect(auth.state.status).toBe("out");
  });

  it("signing out of a linked account in the app sends the device secret and clears it", async () => {
    const keychain = shell();
    keychain.value = "tok-mei";
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await auth.signOut();
    expect(calls.find((c) => c.url === "/api/auth/logout")!.headers).toEqual({ Authorization: "Device tok-mei" });
    expect(keychain.value).toBeNull();
  });

  it("on the website sign-out sends no device header", async () => {
    auth.state = { status: "in", clientId: "cid", user: MEI };
    routes.set("POST /api/auth/logout", { status: 200, body: { ok: true } });
    await auth.signOut();
    expect(calls.find((c) => c.url === "/api/auth/logout")!.headers).toEqual({});
  });
});

describe("names", () => {
  it("a name another account shows is refused with 'That name is taken.'", async () => {
    expect(NAME_MESSAGES.taken).toBe("That name is taken.");
    routes.set("PATCH /api/me", { status: 400, body: { detail: "taken" } });
    const err = await updateDisplayName("Mei").catch((e) => e);
    expect(err).toBeInstanceOf(NameRejected);
    expect(err.message).toBe("That name is taken.");
  });
});
