// The device account end to end through the real auth store, socket manager,
// queue store and code join: which identity each socket carries (the session
// cookie at its handshake, as the server reads it) and what each one sends.
// A Play, Duo or Join must reach the server once, on a socket that carries
// the account, or as a guest on today's path; never twice, never on the
// socket of the identity before.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** The session cookie as the server would read it at a handshake. */
let cookie: string | null = null;

class FakeWS {
  static OPEN = 1;
  static all: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  /** Who this socket is, read from the cookie when it was made. */
  who: string | null = cookie;
  constructor() {
    FakeWS.all.push(this);
    setTimeout(() => {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      this.onopen?.();
    }, 0);
  }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  deliver(msg: unknown) { this.onmessage?.({ data: JSON.stringify(msg) }); }
}

const JOINS = new Set(["queue_join", "table_join"]);
/** Every join any socket sent, with who that socket was. */
const joins = () => FakeWS.all.flatMap((w) => w.sent.filter((m) => JOINS.has(String(m.type))).map((m) => ({ who: w.who, msg: m })));
const live = () => FakeWS.all.filter((w) => w.readyState === 1);

const DEVICE_USER = { name: "Gentle Tractor", email: "", picture: null, display_name: "Gentle Tractor",
                      name_shown: "Gentle Tractor", rounds_played: 3, linked: false };

type Answer = { status: number; body?: unknown; cookie?: string | null };
let deviceAnswers: (Answer | Promise<Answer>)[];
let googleAnswers: (Answer | Promise<Answer>)[];
let deviceCalls: Record<string, string>[];
let googleCalls = 0;
let keychain: { value: string | null; failGet: number; failSet: number };

function mockFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    let a: Answer = { status: 404 };
    if (url === "/api/auth/config") a = { status: 200, body: { google_client_id: "cid", device_accounts: true } };
    else if (url === "/api/me" && method === "GET") a = cookie ? { status: 200, body: DEVICE_USER } : { status: 401, body: {} };
    else if (url === "/api/me/stats") a = { status: 404, body: {} };
    else if (url === "/api/auth/device") {
      deviceCalls.push({ ...(init?.headers as Record<string, string>) });
      a = await (deviceAnswers.shift() ?? { status: 429, body: {} });
    } else if (url === "/api/auth/google") {
      googleCalls += 1;
      a = await (googleAnswers.shift() ?? { status: 500, body: {} });
    } else if (url === "/api/me" && method === "DELETE") a = { status: 204, cookie: null };
    if (a.cookie !== undefined) cookie = a.cookie;
    return { status: a.status, json: async () => { if (a.body === undefined) throw new Error("no body"); return a.body; } } as Response;
  }) as typeof fetch;
}

function iosShell() {
  const refuse = (n: "failGet" | "failSet") => {
    if (keychain[n] <= 0) return;
    keychain[n] -= 1;
    throw new Error("keychain");
  };
  const methods: Record<string, (o?: { value?: string }) => Promise<unknown>> = {
    get: async () => { refuse("failGet"); return { value: keychain.value }; },
    set: async (o) => { refuse("failSet"); keychain.value = o?.value ?? null; },
    remove: async () => { keychain.value = null; },
  };
  (window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    getPlatform: () => "ios",
    isPluginAvailable: (n: string) => n === "ShengjiKeychain",
    registerPlugin: (n: string) => (n === "ShengjiKeychain" ? methods : {}),
  };
}

const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 6; i += 1) await tick(); };

async function load() {
  const { conn } = await import("./ws");
  const authModule = await import("./auth");
  const { auth } = authModule;
  const { queue } = await import("./queue/store");
  const { codes } = await import("./codeJoin");
  const device = await import("./deviceAccount");
  return { conn, auth, authModule, queue, codes, device };
}

let mods: Awaited<ReturnType<typeof load>>;

beforeEach(async () => {
  FakeWS.all = [];
  cookie = null;
  deviceAnswers = [];
  googleAnswers = [];
  deviceCalls = [];
  googleCalls = 0;
  keychain = { value: null, failGet: 0, failSet: 0 };
  localStorage.clear();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWS;
  iosShell();
  mockFetch();
  vi.resetModules();
  mods = await load();
});
afterEach(() => {
  mods.queue.reset();
  mods.conn.stop();
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  window.history.replaceState(null, "", "/");
});

describe("restore after a reinstall", () => {
  it("a Play tapped while the launch restores waits, then queues once on the account's socket", async () => {
    keychain.value = "tok-kept";
    let answer!: (a: Answer) => void;
    deviceAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    mods.conn.start();
    const init = mods.auth.init();
    await settle();
    // the first socket opened before the restore: a guest's handshake
    expect(live().map((w) => w.who)).toEqual([null]);
    expect(mods.auth.state.status).toBe("loading");
    mods.queue.join();
    await settle();
    expect(joins()).toEqual([]);
    answer({ status: 200, body: { user: DEVICE_USER }, cookie: "account:7" });
    await init;
    await settle();
    expect(mods.auth.state.status).toBe("in");
    expect(deviceCalls).toEqual([{ "X-Shengji-Client": "ios-app", Authorization: "Device tok-kept" }]);
    expect(joins()).toEqual([{ who: "account:7", msg: { type: "queue_join", mode: "ranked" } }]);
    expect(live().map((w) => w.who)).toEqual(["account:7"]);
  });

  it("a restore with no tap replaces the guest socket, so the first Play is the account's", async () => {
    keychain.value = "tok-kept";
    deviceAnswers.push({ status: 200, body: { user: DEVICE_USER }, cookie: "account:7" });
    mods.conn.start();
    await settle();
    await mods.auth.init();
    await settle();
    mods.queue.join();
    await settle();
    expect(joins()).toEqual([{ who: "account:7", msg: { type: "queue_join", mode: "ranked" } }]);
  });
});

describe("a device sign-in and a provider sign-in, either answering late", () => {
  const MEI = { name: "Mei Chen", email: "mei@x", picture: null, display_name: "Mei", name_shown: "Mei",
                rounds_played: 40, linked: true };
  const signInWithGoogle = () => mods.authModule.identityTurn(async () => {
    mods.auth.signedIn(await mods.authModule.loginWithGoogle("jwt", "n1"));
  });

  beforeEach(async () => {
    mods.conn.start();
    await mods.auth.init();
    await settle();
  });

  it("Play, then Google while the device answer is out: Google goes after it, and Mei is the cookie, the page and the socket", async () => {
    let device!: (a: Answer) => void;
    deviceAnswers.push(new Promise<Answer>((r) => { device = r; }));
    googleAnswers.push({ status: 200, body: MEI, cookie: "account:mei" });
    mods.queue.join();
    await settle();
    const google = signInWithGoogle();
    await settle();
    // the provider request waits for the device's turn
    expect(googleCalls).toBe(0);
    device({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    await google;
    await settle();
    expect(googleCalls).toBe(1);
    expect(cookie).toBe("account:mei");
    expect(mods.auth.state.user?.name_shown).toBe("Mei");
    expect(live().map((w) => w.who)).toEqual(["account:mei"]);
    // the held Play goes once, on the identity asked for last
    expect(joins()).toEqual([{ who: "account:mei", msg: { type: "queue_join", mode: "ranked" } }]);
  });

  it("Google, then Play while the Google answer is out: no device account is made, and the Play goes as Mei", async () => {
    let answer!: (a: Answer) => void;
    googleAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    deviceAnswers.push({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    const google = signInWithGoogle();
    await settle();
    mods.queue.join();
    await settle();
    expect(deviceCalls).toEqual([]);
    answer({ status: 200, body: MEI, cookie: "account:mei" });
    await google;
    await settle();
    expect(deviceCalls).toEqual([]);
    expect(cookie).toBe("account:mei");
    expect(mods.auth.state.user?.name_shown).toBe("Mei");
    expect(joins()).toEqual([{ who: "account:mei", msg: { type: "queue_join", mode: "ranked" } }]);
    expect(live().map((w) => w.who)).toEqual(["account:mei"]);
  });
});

describe("switching accounts", () => {
  const MEI = { name: "Mei Chen", email: "mei@x", picture: null, display_name: "Mei", name_shown: "Mei",
                rounds_played: 40, linked: true };

  it("signed in as A, a Play during a delayed switch to B waits for it and goes once, as B", async () => {
    cookie = "account:a";
    mods.conn.start();
    await mods.auth.init();
    await settle();
    expect(mods.auth.state.status).toBe("in");
    expect(live().map((w) => w.who)).toEqual(["account:a"]);
    let answer!: (a: Answer) => void;
    googleAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    const switching = mods.authModule.identityTurn(async () => {
      mods.auth.signedIn(await mods.authModule.loginWithGoogle("jwt", "n1"));
    });
    await settle();
    mods.queue.join();
    await settle();
    // nothing goes on A's socket while the switch is out
    expect(joins()).toEqual([]);
    answer({ status: 200, body: MEI, cookie: "account:mei" });
    await switching;
    await settle();
    expect(joins()).toEqual([{ who: "account:mei", msg: { type: "queue_join", mode: "ranked" } }]);
    expect(live().map((w) => w.who)).toEqual(["account:mei"]);
  });

  it("a switch that fails leaves the Play to go once, as A", async () => {
    cookie = "account:a";
    mods.conn.start();
    await mods.auth.init();
    await settle();
    let answer!: (a: Answer) => void;
    googleAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    const switching = mods.authModule.identityTurn(async () => {
      mods.auth.signedIn(await mods.authModule.loginWithGoogle("jwt", "n1"));
    }).catch(() => undefined);
    await settle();
    mods.queue.join();
    await settle();
    expect(joins()).toEqual([]);
    answer({ status: 401, body: { detail: "Sign-in rejected (nonce)." } });
    await switching;
    await settle();
    expect(joins()).toEqual([{ who: "account:a", msg: { type: "queue_join", mode: "ranked" } }]);
  });
});

describe("past the 6 s bound", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("a sign-in answered after the deadline sends nothing for that tap; a new tap queues once on the account's socket", async () => {
    vi.useFakeTimers();
    mods.conn.start();
    await vi.advanceTimersByTimeAsync(10);
    await mods.auth.init();
    await vi.advanceTimersByTimeAsync(10);
    let answer!: (a: Answer) => void;
    deviceAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    mods.queue.join();
    await vi.advanceTimersByTimeAsync(6100);
    expect(joins()).toEqual([]);
    expect(mods.queue.getSnapshot().note?.title).toBe("Couldn't open a table.");
    answer({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    await vi.advanceTimersByTimeAsync(50);
    expect(mods.auth.state.status).toBe("in");
    expect(joins()).toEqual([]);
    mods.queue.join();
    await vi.advanceTimersByTimeAsync(50);
    expect(joins()).toEqual([{ who: "account:9", msg: { type: "queue_join", mode: "ranked" } }]);
    expect(deviceCalls).toHaveLength(1);
  });

  it("a restore answered after the deadline sends nothing for the tap made during it", async () => {
    vi.useFakeTimers();
    keychain.value = "tok-kept";
    let answer!: (a: Answer) => void;
    deviceAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    mods.conn.start();
    const init = mods.auth.init();
    await vi.advanceTimersByTimeAsync(10);
    mods.queue.join();
    await vi.advanceTimersByTimeAsync(6100);
    answer({ status: 200, body: { user: DEVICE_USER }, cookie: "account:7" });
    await init;
    await vi.advanceTimersByTimeAsync(50);
    expect(mods.auth.state.status).toBe("in");
    expect(joins()).toEqual([]);
    expect(live().map((w) => w.who)).toEqual(["account:7"]);
  });
});

describe("the first online Play", () => {
  beforeEach(async () => {
    mods.conn.start();
    await mods.auth.init();
    await settle();
    expect(mods.auth.state.deviceAccounts).toBe(true);
  });

  it("makes the account, keeps its secret, and queues once on its socket; a tap during the reconnect adds nothing", async () => {
    deviceAnswers.push({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    mods.queue.join();
    mods.queue.join();
    await tick();
    mods.queue.joinDuo();
    await settle();
    expect(keychain.value).toBe("tok-new");
    expect(deviceCalls).toHaveLength(1);
    expect(joins()).toEqual([{ who: "account:9", msg: { type: "queue_join", mode: "ranked" } }]);
  });

  it("an unreadable Keychain makes no account: the Play goes once, as today's guest", async () => {
    keychain.value = "tok-kept";
    keychain.failGet = 1;
    mods.queue.join();
    await settle();
    expect(deviceCalls).toEqual([]);
    expect(keychain.value).toBe("tok-kept");
    expect(joins()).toHaveLength(1);
    expect(joins()[0].who).toBeNull();
    expect(joins()[0].msg).toMatchObject({ type: "queue_join", mode: "ranked" });
    expect(mods.auth.state.status).toBe("out");
  });

  it("a secret the Keychain will not keep: the account stays signed in on the cookie, nothing is deleted or stored in the page, and the next Play saves it", async () => {
    keychain.failSet = 2;
    deviceAnswers.push({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    mods.queue.join();
    await settle();
    expect(cookie).toBe("account:9");
    expect(mods.auth.state.status).toBe("in");
    expect(joins()).toEqual([{ who: "account:9", msg: { type: "queue_join", mode: "ranked" } }]);
    expect(keychain.value).toBeNull();
    expect(Object.values({ ...localStorage }).join()).not.toContain("tok-new");
    mods.queue.reset();
    mods.queue.join();
    await settle();
    // a signed-in Play goes at once, and offers the secret to the Keychain again
    expect(joins()).toHaveLength(2);
    expect(keychain.value).toBe("tok-new");
  });

  it("a mode switched while the account is made drops the held Play", async () => {
    let answer!: (a: Answer) => void;
    deviceAnswers.push(new Promise<Answer>((r) => { answer = r; }));
    mods.queue.join();
    await settle();
    mods.queue.setPlayMode("casual");
    answer({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    await settle();
    expect(joins()).toEqual([]);
    expect(mods.auth.state.status).toBe("in");
  });

  it("a code's Join: one sign-in attempt for one tap, then table_join on the account's socket", async () => {
    deviceAnswers.push({ status: 200, body: { token: "tok-new", user: DEVICE_USER }, cookie: "account:9" });
    mods.codes.setPlace({ ready: true, seatedAt: null });
    expect(mods.codes.open("FG3K")).toBe(true);
    for (const w of live()) {
      w.deliver({ type: "room_seats", room: "FG3K", table: true, mode: "casual", in_game: false, allow_joiners: true,
                  full: false, closed: false,
                  seats: [{ seat: 0, team: 0, state: "taken", name: "Ann", ready: false },
                          { seat: 1, team: 1, state: "open", name: null, ready: false },
                          { seat: 2, team: 0, state: "open", name: null, ready: false },
                          { seat: 3, team: 1, state: "open", name: null, ready: false }] });
    }
    expect(mods.codes.view?.step).toBe("panel");
    mods.codes.join("Gentle Tractor");
    mods.codes.join("Gentle Tractor");
    await settle();
    expect(deviceCalls).toHaveLength(1);
    expect(joins()).toHaveLength(1);
    expect(joins()[0].who).toBe("account:9");
    expect(joins()[0].msg).toMatchObject({ type: "table_join", code: "FG3K" });
  });

  it("a code's Join refused a sign-in (429) asks once and joins once, as a guest", async () => {
    deviceAnswers.push({ status: 429, body: {} });
    mods.codes.setPlace({ ready: true, seatedAt: null });
    mods.codes.open("FG3K");
    for (const w of live()) {
      w.deliver({ type: "room_seats", room: "FG3K", table: true, mode: "casual", in_game: false, allow_joiners: true,
                  full: false, closed: false,
                  seats: [{ seat: 0, team: 0, state: "taken", name: "Ann", ready: false },
                          { seat: 1, team: 1, state: "open", name: null, ready: false },
                          { seat: 2, team: 0, state: "open", name: null, ready: false },
                          { seat: 3, team: 1, state: "open", name: null, ready: false }] });
    }
    mods.codes.join("Gentle Tractor");
    await settle();
    expect(deviceCalls).toHaveLength(1);
    expect(joins()).toHaveLength(1);
    expect(joins()[0].who).toBeNull();
  });
});
