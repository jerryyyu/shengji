import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState, AuthUser } from "../auth";

const { authState, updated } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
  updated: vi.fn(),
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return {
    ...real, useAuth: () => authState.current,
    auth: {
      updated: (u: AuthUser) => { updated(u); authState.current = { ...authState.current, user: u } as AuthState; },
      get state() { return authState.current; },
    },
  };
});

import CollectionPage from "../components/CollectionPage";
import { forgetHomeSession } from "../home/session";
import { lookCatalogue } from "../companion/look";

const LAMB = "com.jerryyu.shengji.companion.lamb";
const PANDA = "com.jerryyu.shengji.companion.panda";
const lambLooks = (unlocked: boolean) => ["newyear", "jade", "ink", "lacquer"].map((c) => (
  { id: `lamb/${c}`, unlocked, needs: null, product: LAMB }));
const pandaLooks = ["classic", "russet", "ink", "gilded"].map((c) => (
  { id: `panda/${c}`, unlocked: false, needs: null, product: PANDA }));
const tractorLooks = lookCatalogue({ rounds: 0, ranked_wins: 0 }, "tractor/red");

const user: AuthUser = {
  name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
  rounds_played: 0, ranked_wins: 0, look: "tractor/red", companions: "team", products: [],
  store_token: "11111111-1111-4111-8111-111111111111",
  looks: [...tractorLooks, ...lambLooks(false), ...pandaLooks],
  features: { collection: true, store: true },
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const fetches: { url: string; init?: RequestInit }[] = [];
const plugin = {
  products: vi.fn(async () => ({ products: [
    { id: LAMB, displayName: "Goat", displayPrice: "$3.99" },
    { id: PANDA, displayName: "Panda", displayPrice: "$3.99" }] })),
  purchase: vi.fn(async () => ({ status: "purchased", jws: "header.payload.sig", productId: LAMB })),
  restore: vi.fn(async () => ({ transactions: [{ jws: "restored.jws.sig", productId: LAMB }] })),
  entitlements: vi.fn(async () => ({ transactions: [] })),
  storefront: vi.fn(async () => ({ countryCode: "USA" })),
  addListener: vi.fn(async () => ({ remove: () => {} })),
  pending: vi.fn(async () => ({ transactions: [] as unknown[] })),
  finish: vi.fn(async () => ({ finished: true })),
};

function nativeShell(withPlugin = true) {
  (window as unknown as { Capacitor?: unknown }).Capacitor = {
    isNativePlatform: () => true,
    isPluginAvailable: (name: string) => withPlugin && name === "ShengjiStore",
    registerPlugin: (name: string) => (name === "ShengjiStore" && withPlugin ? plugin : {}),
  };
}

const ownedUser: AuthUser = { ...user, products: [LAMB], looks: [...tractorLooks, ...lambLooks(true), ...pandaLooks] };
// what the server holds: a verify grants the Goat, and /api/me then says so
const server = { granted: false };

beforeEach(() => {
  // a character page opened by an earlier test is its own address: start on the grid
  window.history.replaceState(null, "", "/");
  server.granted = false;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  updated.mockClear();
  Object.values(plugin).forEach((f) => f.mockClear());
  plugin.storefront.mockImplementation(async () => ({ countryCode: "USA" }));
  plugin.pending.mockImplementation(async () => ({ transactions: [] }));
  forgetHomeSession();
  fetches.length = 0;
  globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    fetches.push({ url, init });
    if (url.includes("/api/leaderboard")) return { status: 404, json: async () => ({}) } as Response;
    if (url === "/api/store/verify") {
      server.granted = true;
      return { status: 200, json: async () => ownedUser } as Response;
    }
    return { status: 200, json: async () => (server.granted ? ownedUser : authState.current.user) } as Response;
  }) as unknown as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  authState.current = { status: "out", clientId: "cid", user: null };
  delete (window as unknown as { Capacitor?: unknown }).Capacitor;
});

const settle = async () => { await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); };
const draw = async () => {
  await act(async () => { root.render(<CollectionPage />); });
  await settle();
  await settle();
};

const names = (sel: string) => [...host.querySelectorAll(`${sel} .coll-tile`)].map((b) => b.textContent);
const FREE_TILES = ["Tractor", "Bun", "Chick", "Sparrow"];
const SOON_TILES = ["Jade RabbitSoon", "Lucky CatSoon", "Fortune FoxSoon", "Dancing LionSoon", "Little DragonSoon"];
const openTile = async (sel: string, i = 0) => {
  await act(async () => { host.querySelectorAll<HTMLButtonElement>(`${sel} .coll-tile`)[i].click(); });
  await settle();
};
/** The character on the stage, by the status line under it ("Kind · Colour", or a Soon one's name). */
const onStage = () => (host.querySelector(".char-page .coll-status")?.textContent ?? "").split(" · ")[0];

describe("the grid's sections", () => {
  it("More companions lists the store's characters with StoreKit's price, then Soon, and Restore purchases last", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect([...host.querySelectorAll(".coll-section")].map((h) => h.textContent)).toEqual(["Yours", "More companions"]);
    expect(names(".coll-yours")).toEqual(FREE_TILES);
    expect(names(".coll-more")).toEqual(["Spring Lamb$3.99", "Baby Panda$3.99", ...SOON_TILES]);
    // only the sold ones are asked of StoreKit; free and Soon characters never
    expect(plugin.products).toHaveBeenCalledWith({ ids: [LAMB, PANDA] });
    expect(host.querySelector(".coll-restore")?.textContent).toBe("Restore purchases");
    // no Shop segment, button or page
    expect(host.querySelector(".coll-shop, .shop-row")).toBeNull();
  });

  it("every store tile draws its own character, and a Soon page shows its art with no Buy", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const kinds = [...host.querySelectorAll(".coll-more .coll-tile svg.cmp")]
      .map((svg) => [...svg.classList].find((c) => /^cmp-(lamb|panda|rabbit|cat|fox|lion|dragon|tractor)$/.test(c)));
    expect(kinds).toEqual(["cmp-lamb", "cmp-panda", "cmp-rabbit", "cmp-cat", "cmp-fox", "cmp-lion", "cmp-dragon"]);
    await openTile(".coll-more", 2);
    expect(host.querySelector(".char-stage svg.cmp")?.classList.contains("cmp-rabbit")).toBe(true);
    expect(host.querySelector(".coll-use")?.textContent).toBe("Soon");
    expect(host.querySelectorAll(".coll-use")).toHaveLength(1);
    expect(host.querySelector(".store-price, .char-swatches")).toBeNull();
  });

  it("is hidden on the China storefront: Yours alone, no Restore purchases", async () => {
    nativeShell();
    plugin.storefront.mockImplementation(async () => ({ countryCode: "CHN" }));
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(names(".coll-yours")).toEqual(FREE_TILES);
    expect(host.querySelector(".coll-more")).toBeNull();
    expect(host.querySelector(".coll-restore")).toBeNull();
    expect(host.querySelector(".coll-get-app")).toBeNull();
    expect(plugin.products).not.toHaveBeenCalled();
  });

  it("is hidden without the plugin; a web guest gets one Get the app row instead", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(host.querySelector(".coll-more")).toBeNull();
    expect(host.querySelector(".coll-get-app")).toBeNull();        // signed in on the web: nothing
    authState.current = { status: "out", clientId: "cid", user: null };
    await draw();
    expect(names(".coll-yours")).toEqual(FREE_TILES);
    expect(host.querySelector(".coll-more")).toBeNull();
    const row = host.querySelector<HTMLAnchorElement>(".coll-get-app")!;
    expect(row.textContent).toBe("Get the app");
    expect(row.getAttribute("href")).toMatch(/^https:\/\/apps\.apple\.com\/.*ct=collection-web$/);
  });

  it("is hidden for a guest in the app and an account without the store", async () => {
    nativeShell();
    await draw();
    expect(host.querySelector(".coll-more")).toBeNull();
    expect(host.querySelector(".coll-get-app")).toBeNull();
    authState.current = { status: "in", clientId: "cid", user: { ...user, features: { collection: true } } };
    await draw();
    expect(host.querySelector(".coll-more")).toBeNull();
  });

  it("an owned character sits in Yours, not in More companions", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user: {
      ...user, products: [LAMB], looks: [...tractorLooks, ...lambLooks(true), ...pandaLooks] } };
    await draw();
    expect(names(".coll-yours")).toEqual([...FREE_TILES, "Spring Lamb"]);
    expect(names(".coll-more")).toEqual(["Baby Panda$3.99", ...SOON_TILES]);
    await openTile(".coll-yours", 4);
    expect(host.querySelector(".coll-use")?.textContent).toBe("Use");
  });

  it("a Soon tile selects a stage that says Soon and sells nothing", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 2);
    expect(onStage()).toBe("Jade Rabbit");
    const foot = host.querySelector<HTMLButtonElement>(".coll-use")!;
    expect(foot.textContent).toBe("Soon");
    expect(foot.disabled).toBe(true);
    expect(plugin.purchase).not.toHaveBeenCalled();
  });

  it("buys the store character selected on the stage: Apple's sheet, the server's verification, Use and the cheer, its tile up into Yours", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 0);
    expect(onStage()).toBe("Spring Lamb");
    // selected in place: still the Collection, its tile ringed in More companions
    expect(host.querySelector(".large-title")?.textContent).toBe("Collection");
    expect(host.querySelectorAll(".coll-more .coll-tile")[0].classList.contains("selected")).toBe(true);
    // try a colour on the felt: a preview, nothing sent
    const swatches = [...host.querySelectorAll<HTMLButtonElement>(".coll-swatch")];
    expect(swatches.map((s) => s.getAttribute("aria-label"))).toEqual(["New Year", "Jade", "Ink wash", "Lacquer red"]);
    await act(async () => { swatches[1].click(); });
    expect(fetches.some((f) => f.url === "/api/store/verify")).toBe(false);
    const price = host.querySelector<HTMLButtonElement>(".coll-use.gold")!;
    expect(price.textContent).toBe("Buy $3.99");
    await act(async () => { price.click(); });
    await settle();
    expect(plugin.purchase).toHaveBeenCalledWith({ id: LAMB, appAccountToken: "11111111-1111-4111-8111-111111111111" });
    const sent = fetches.find((f) => f.url === "/api/store/verify")!;
    expect(JSON.parse(String(sent.init?.body))).toEqual({ jws: "header.payload.sig", storefront: "USA" });
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ products: [LAMB] }));
    await draw();       // the mocked useAuth does not subscribe: draw again to read the account
    expect(host.querySelector(".coll-use")?.textContent).toBe("Use");
    expect(host.querySelector(".char-stage svg.cmp.cmp-cheer")).not.toBeNull();
    // on the same page, the Lamb's tile has risen into Yours and stays selected
    expect(names(".coll-yours")).toEqual([...FREE_TILES, "Spring Lamb"]);
    expect(host.querySelectorAll(".coll-yours .coll-tile")[4].classList.contains("arrive")).toBe(true);
    expect(host.querySelectorAll(".coll-yours .coll-tile")[4].classList.contains("selected")).toBe(true);
  });

  it("a cancelled purchase changes nothing; a refused one says so on the one status line", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 0);
    plugin.purchase.mockImplementationOnce(async () => ({ status: "cancelled" }) as never);
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    await settle();
    expect(fetches.some((f) => f.url === "/api/store/verify")).toBe(false);
    expect(host.querySelector(".coll-status")?.textContent).toBe("Spring Lamb · New Year");
    globalThis.fetch = vi.fn(async () => ({ status: 409, json: async () => ({ detail: "held_by_other" }) }) as Response) as unknown as typeof fetch;
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    await settle();
    expect(host.querySelector(".coll-status")?.textContent).toBe("Purchase not completed (held_by_other)");
    expect(host.querySelector(".coll-use")?.textContent).toBe("Buy $3.99");
  });

  it("restore hands every owned transaction to the server", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-restore")!.click(); });
    await settle();
    await settle();
    expect(plugin.restore).toHaveBeenCalled();
    const sent = fetches.find((f) => f.url === "/api/store/verify")!;
    expect(JSON.parse(String(sent.init?.body)).jws).toBe("restored.jws.sig");
    await draw();
    expect(names(".coll-yours")).toEqual([...FREE_TILES, "Spring Lamb"]);
  });
});

describe("delivery until the server has it", () => {
  it("finishes a purchase only after the server granted it", async () => {
    nativeShell();
    plugin.purchase.mockImplementationOnce(async () => (
      { status: "purchased", jws: "header.payload.sig", productId: LAMB, transactionId: "2000000111" }) as never);
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-more .coll-tile")[0].click(); });
    await settle();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    await settle();
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "2000000111" });
  });

  it("an interrupted grant stays unfinished and is recovered at the next open", async () => {
    nativeShell();
    plugin.purchase.mockImplementationOnce(async () => (
      { status: "purchased", jws: "header.payload.sig", productId: LAMB, transactionId: "2000000111" }) as never);
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-more .coll-tile")[0].click(); });
    await settle();
    const ok = globalThis.fetch;
    globalThis.fetch = vi.fn(async (url: string) => {
      if (url === "/api/store/verify") throw new TypeError("network");
      return ok(url);
    }) as unknown as typeof fetch;
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    await settle();
    expect(plugin.finish).not.toHaveBeenCalled();
    expect(host.querySelector(".shop-owned")).toBeNull();

    // relaunch: the App Store still holds it unfinished, and no listener ever saw it
    globalThis.fetch = ok;
    plugin.pending.mockImplementation(async () => ({ transactions: [
      { jws: "header.payload.sig", productId: LAMB, transactionId: "2000000111" }] }));
    act(() => root.unmount());
    root = createRoot(host);
    await draw();
    await settle();
    expect(fetches.filter((f) => f.url === "/api/store/verify").length).toBeGreaterThan(0);
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "2000000111" });
  });

  it("a definitive refusal finishes it; a server it cannot reach does not", async () => {
    nativeShell();
    plugin.pending.mockImplementation(async () => ({ transactions: [
      { jws: "x.y.z", productId: LAMB, transactionId: "9" }] }));
    globalThis.fetch = vi.fn(async (url: string) => (url === "/api/store/verify"
      ? { status: 409, json: async () => ({ detail: "held_by_other" }) }
      : { status: 200, json: async () => authState.current.user }) as Response) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await settle();
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "9" });
    act(() => root.unmount());
    root = createRoot(host);
    plugin.finish.mockClear();
    globalThis.fetch = vi.fn(async (url: string) => (url === "/api/store/verify"
      ? { status: 503, json: async () => ({}) }
      : { status: 200, json: async () => authState.current.user }) as Response) as unknown as typeof fetch;
    await draw();
    await settle();
    expect(plugin.finish).not.toHaveBeenCalled();
  });
});

describe("the payer, the order and the reasons", () => {
  const openGoat = async () => {
    await draw();
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-more .coll-tile")[0].click(); });
    await settle();
  };
  const other: AuthUser = { ...user, email: "other@x", name_shown: "Mei", store_token: "22222222-2222-4222-8222-222222222222" };

  it("binds the purchase to the payer's token and shows no success to an account switched in meanwhile", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user: { ...user, store_token: "11111111-1111-4111-8111-111111111111" } };
    let pay!: (v: unknown) => void;
    plugin.purchase.mockImplementationOnce(() => new Promise((r) => { pay = r; }) as never);
    await openGoat();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    expect(plugin.purchase).toHaveBeenCalledWith({ id: LAMB, appAccountToken: "11111111-1111-4111-8111-111111111111" });
    // the sheet is up; the player switches account
    authState.current = { status: "in", clientId: "cid", user: other };
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      if (url === "/api/store/verify") return { status: 409, json: async () => ({ detail: "held_by_other" }) } as Response;
      return { status: 200, json: async () => authState.current.user } as Response;
    }) as unknown as typeof fetch;
    await act(async () => { pay({ status: "purchased", jws: "a.b.c", productId: LAMB, transactionId: "7" }); });
    await settle();
    expect(host.querySelector(".coll-felt svg.cmp.cmp-cheer")).toBeNull();
    expect(host.querySelector(".coll-status")?.textContent).not.toMatch(/Purchase/);
    // the server gave it to the payer; this transaction is settled
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "7" });
  });

  it("a return signed out shows no success and keeps the transaction", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    let pay!: (v: unknown) => void;
    plugin.purchase.mockImplementationOnce(() => new Promise((r) => { pay = r; }) as never);
    await openGoat();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    authState.current = { status: "out", clientId: "cid", user: null };
    await act(async () => { pay({ status: "purchased", jws: "a.b.c", productId: LAMB, transactionId: "8" }); });
    await settle();
    expect(host.querySelector(".coll-felt svg.cmp.cmp-cheer")).toBeNull();
    expect(fetches.some((f) => f.url === "/api/store/verify")).toBe(false);
    expect(plugin.finish).not.toHaveBeenCalled();
  });

  it("answers that come back out of order never replace a newer account", async () => {
    nativeShell();
    plugin.pending.mockImplementation(async () => ({ transactions: [
      { jws: "slow.jws.sig", productId: LAMB, transactionId: "1" }] }));
    let listen: ((d: unknown) => void) | null = null;
    plugin.addListener.mockImplementationOnce((async (_e: string, cb: (d: unknown) => void) => {
      listen = cb;
      return { remove: () => {} };
    }) as never);
    const both = { ...user, products: [LAMB, PANDA] };
    const starts: string[] = [];
    const done: string[] = [];
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      if (url === "/api/store/verify") {
        const jws = JSON.parse(String(init?.body)).jws as string;
        starts.push(jws);
        // the first answer is slow and carries only the Goat
        if (jws === "slow.jws.sig") await new Promise((r) => setTimeout(r, 30));
        done.push(jws);
        return { status: 200, json: async () => (jws === "slow.jws.sig" ? { ...user, products: [LAMB] } : both) } as Response;
      }
      return { status: 200, json: async () => (done.length === 2 ? both : authState.current.user) } as Response;
    }) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    // an update arrives while the slow pending one is still with the server
    await act(async () => { listen!({ jws: "fast.jws.sig", productId: PANDA, transactionId: "2" }); });
    await act(async () => { await new Promise((r) => setTimeout(r, 80)); });
    await settle();
    expect(starts).toEqual(["slow.jws.sig", "fast.jws.sig"]);        // one at a time, in order
    const last = updated.mock.calls.at(-1)?.[0] as AuthUser;
    expect(last.products).toEqual([LAMB, PANDA]);
  });

  it("restore keeps a transient failure pending, says so, and acknowledges only a permanent refusal", async () => {
    nativeShell();
    plugin.restore.mockImplementation(async () => ({ transactions: [
      { jws: "busy.jws.sig", productId: LAMB, transactionId: "31" },
      { jws: "china.jws.sig", productId: PANDA, transactionId: "32" },
      { jws: "taken.jws.sig", productId: PANDA, transactionId: "33" }] }));
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      if (url === "/api/store/verify") {
        const jws = JSON.parse(String(init?.body)).jws as string;
        if (jws === "busy.jws.sig") return { status: 503, json: async () => ({}) } as Response;
        if (jws === "china.jws.sig") return { status: 403, json: async () => ({ detail: "storefront" }) } as Response;
        return { status: 409, json: async () => ({ detail: "held_by_other" }) } as Response;
      }
      return { status: 200, json: async () => authState.current.user } as Response;
    }) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-restore")!.click(); });
    await settle();
    await settle();
    expect(host.querySelector(".coll-grid-status")?.textContent).toBe("Purchase not completed (503)");
    expect(plugin.finish.mock.calls).toEqual([[{ transactionId: "33" }]]);
  });
});


describe("no payer token, no purchase", () => {
  it("keeps the price unavailable and never opens Apple's sheet until the account has a token", async () => {
    nativeShell();
    const tokenless = { ...user, store_token: undefined };
    authState.current = { status: "in", clientId: "cid", user: tokenless };
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      return { status: 200, json: async () => tokenless } as Response;
    }) as unknown as typeof fetch;
    await draw();
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-more .coll-tile")[0].click(); });
    await settle();
    const meReads = fetches.filter((f) => f.url === "/api/me").length;
    const price = host.querySelector<HTMLButtonElement>(".coll-use.gold");
    expect(price === null || price.disabled).toBe(true);
    if (price) await act(async () => { price.click(); });
    await settle();
    expect(plugin.purchase).not.toHaveBeenCalled();
    // the page asked the server again for the token, once
    await settle();
    expect(fetches.filter((f) => f.url === "/api/me").length).toBe(meReads);
    expect(meReads).toBeGreaterThanOrEqual(2);
    // buy() itself refuses without a token
    const { buy } = await import("./shop");
    await expect(buy(LAMB)).resolves.toBe("none");
    expect(plugin.purchase).not.toHaveBeenCalled();
  });

  it("unknown_token keeps the transaction pending", async () => {
    nativeShell();
    plugin.pending.mockImplementation(async () => ({ transactions: [{ jws: "x.y.z", productId: LAMB, transactionId: "5" }] }));
    globalThis.fetch = vi.fn(async (url: string) => (url === "/api/store/verify"
      ? { status: 409, json: async () => ({ detail: "unknown_token" }) }
      : { status: 200, json: async () => authState.current.user }) as Response) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await settle();
    expect(plugin.finish).not.toHaveBeenCalled();
  });
});

describe("buying needs an Apple or Google sign-in", () => {
  const device: AuthUser = { ...user, linked: false, store_token: undefined, name_shown: "Gentle Draw" };
  const openGoat = async () => {
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-more .coll-tile")[0].click(); });
    await settle();
  };

  it("a device account sees Sign in to buy with the price, opens sign-in, and never reaches Apple's sheet", async () => {
    const { guestName } = await import("../guestName");
    const open = vi.spyOn(guestName, "open").mockImplementation(() => {});
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user: device };
    await draw();
    await openGoat();
    const button = host.querySelector<HTMLButtonElement>(".coll-use.gold")!;
    expect(button.textContent).toBe("Sign in to buy");
    expect(button.disabled).toBe(false);
    expect(host.querySelector(".store-price")?.textContent).toBe("$3.99");
    // the price stands above the button, not beside it in the button's row
    const priceEl = host.querySelector(".store-price")!;
    expect(priceEl.closest(".coll-use-row")).toBeNull();
    expect(priceEl.nextElementSibling?.classList.contains("coll-use-row")).toBe(true);
    await act(async () => { button.click(); });
    expect(open).toHaveBeenCalledWith("shop");
    expect(plugin.purchase).not.toHaveBeenCalled();
    // restore asks for sign-in too, and never restores onto the device account
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-restore")!.click(); });
    expect(open).toHaveBeenCalledTimes(2);
    expect(plugin.restore).not.toHaveBeenCalled();
    // the page refreshes nothing in a loop for a token a device account never gets
    expect(fetches.filter((f) => f.url === "/api/me").length).toBeLessThanOrEqual(1);
    open.mockRestore();
  });

  it("after signing in, the same page buys", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user: device };
    await draw();
    await openGoat();
    // the sign-in links the device account; the account comes back with its token
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(onStage()).toBe("Spring Lamb");
    const price = host.querySelector<HTMLButtonElement>(".coll-use.gold")!;
    expect(price.textContent).toBe("Buy $3.99");
    await act(async () => { price.click(); });
    await settle();
    expect(plugin.purchase).toHaveBeenCalledWith({ id: LAMB, appAccountToken: user.store_token });
  });

  it("sign_in_required keeps the transaction pending, and it is delivered once the account has signed in", async () => {
    nativeShell();
    plugin.pending.mockImplementation(async () => ({ transactions: [{ jws: "p.q.r", productId: LAMB, transactionId: "44" }] }));
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      if (url === "/api/store/verify") {
        const ok = authState.current.status === "in" && authState.current.user?.linked !== false;
        return (ok ? { status: 200, json: async () => ownedUser }
          : { status: 409, json: async () => ({ detail: "sign_in_required" }) }) as Response;
      }
      return { status: 200, json: async () => authState.current.user } as Response;
    }) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user: device };
    await draw();
    await settle();
    expect(fetches.some((f) => f.url === "/api/store/verify")).toBe(true);
    expect(plugin.finish).not.toHaveBeenCalled();
    // signed in (the device account merged): the next open delivers it
    act(() => root.unmount());
    root = createRoot(host);
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await settle();
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "44" });
  });
});

describe("signing in on the item page", () => {
  it("delivers the pending purchase when the account becomes eligible, without leaving the page", async () => {
    nativeShell();
    const device: AuthUser = { ...user, linked: false, store_token: undefined, email: "", name_shown: "Gentle Draw" };
    plugin.pending.mockImplementation(async () => ({ transactions: [{ jws: "ask.to.buy", productId: LAMB, transactionId: "61" }] }));
    let granted = false;
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      fetches.push({ url, init });
      if (url === "/api/store/verify") {
        const ok = authState.current.status === "in" && authState.current.user?.linked !== false;
        if (ok) granted = true;
        return (ok ? { status: 200, json: async () => ownedUser }
          : { status: 409, json: async () => ({ detail: "sign_in_required" }) }) as Response;
      }
      return { status: 200, json: async () => (granted ? ownedUser : authState.current.user) } as Response;
    }) as unknown as typeof fetch;
    authState.current = { status: "in", clientId: "cid", user: device };
    await draw();
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-more .coll-tile")[0].click(); });
    await settle();
    const verifies = () => fetches.filter((f) => f.url === "/api/store/verify").length;
    expect(verifies()).toBe(1);
    expect(plugin.finish).not.toHaveBeenCalled();
    // the identity sheet links the account and closes; the page is never remounted
    authState.current = { status: "in", clientId: "cid", user };
    await act(async () => { root.render(<CollectionPage />); });
    await settle();
    await settle();
    expect(onStage()).toBe("Spring Lamb");
    expect(verifies()).toBe(2);
    expect(JSON.parse(String(fetches.filter((f) => f.url === "/api/store/verify")[1].init?.body)).jws).toBe("ask.to.buy");
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "61" });
    expect(updated).toHaveBeenCalledWith(expect.objectContaining({ products: [LAMB] }));
    // the page now reads the grant: Use in the price spot
    await act(async () => { root.render(<CollectionPage />); });
    expect(host.querySelector(".coll-use")?.textContent).toBe("Use");
  });
});

describe("a selected character that goes away", () => {
  const owner: AuthUser = { ...user, features: { collection: true }, products: [LAMB],
    looks: [...tractorLooks, ...lambLooks(true)] };
  // the stage: a selection that goes away gives it back to the one in use (the Tractor)
  const title = () => onStage();

  it("a refund while the Lamb is selected gives the stage back to the one in use", async () => {
    authState.current = { status: "in", clientId: "cid", user: owner };
    await draw();
    await openTile(".coll-yours", 4);
    expect(title()).toBe("Spring Lamb");
    // a refresh brings the account back without the Lamb
    authState.current = { status: "in", clientId: "cid", user: { ...owner, products: [], looks: tractorLooks } };
    await draw();
    expect(title()).toBe("Tractor");
    expect(names(".coll-yours")).toEqual(FREE_TILES);
  });

  it("an account switch while the Lamb is selected gives the stage back to the one in use", async () => {
    authState.current = { status: "in", clientId: "cid", user: owner };
    await draw();
    await openTile(".coll-yours", 4);
    authState.current = { status: "in", clientId: "cid", user: { ...user, email: "mei@x", features: { collection: true },
      products: [], looks: tractorLooks } };
    await draw();
    expect(title()).toBe("Tractor");
    authState.current = { status: "out", clientId: "cid", user: null };
    await draw();
    expect(title()).toBe("Tractor");
  });

  it("the store turning off while a store character is selected gives the stage back to the one in use", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 1);
    expect(title()).toBe("Baby Panda");
    expect(host.querySelector(".coll-use.gold")?.textContent).toBe("Buy $3.99");
    authState.current = { status: "in", clientId: "cid", user: { ...user, features: { collection: true } } };
    await draw();
    expect(title()).toBe("Tractor");
    expect(host.querySelector(".coll-more")).toBeNull();
    // and a Soon page closes with the store too
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 2);
    expect(title()).toBe("Jade Rabbit");
    authState.current = { status: "in", clientId: "cid", user: { ...user, features: { collection: true } } };
    await draw();
    expect(title()).toBe("Tractor");
  });
});

describe("a store character by its address", () => {
  const later = (code: string) => async () => {
    await new Promise((r) => setTimeout(r, 180));
    return { countryCode: code };
  };
  const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });
  // the stage: a selection that goes away gives it back to the one in use (the Tractor)
  const title = () => onStage();

  it("stays asked for while the store's check is out, then selects it when the store is allowed", async () => {
    nativeShell();
    plugin.storefront.mockImplementation(later("USA"));
    window.history.replaceState(null, "", "/#/collection/rabbit");
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(window.location.hash).toBe("#/collection/rabbit");
    expect(title()).toBe("Tractor");
    await wait(220);
    expect(title()).toBe("Jade Rabbit");
    expect(window.location.hash).toBe("#/collection");          // selected, and the plain address in its place
  });

  it("leaves the stage on the one in use once the store's check says no", async () => {
    nativeShell();
    plugin.storefront.mockImplementation(later("CHN"));
    window.history.replaceState(null, "", "/#/collection/rabbit");
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(window.location.hash).toBe("#/collection/rabbit");
    await wait(220);
    expect(title()).toBe("Tractor");
    expect(window.location.hash).toBe("#/collection");
  });

  it("waits for the account to load too", async () => {
    nativeShell();
    window.history.replaceState(null, "", "/#/collection/lamb");
    authState.current = { status: "loading", clientId: "cid", user: null } as AuthState;
    await draw();
    expect(window.location.hash).toBe("#/collection/lamb");
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await wait(20);
    expect(title()).toBe("Spring Lamb");
  });
});
