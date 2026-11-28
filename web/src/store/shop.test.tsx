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
import { setLanguageChoice, tIn } from "../i18n";
import type { Locale } from "../i18n";
import { refusalMessage } from "./shop";

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

const HELD = "Your Apple ID already bought this for another account. Sign in to that account to use it.";

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
    expect(host.querySelector(".coll-status")?.textContent).toBe(HELD);
    // a retry would be refused the same way: Buy gives way to the status line
    expect(host.querySelector(".coll-use")).toBeNull();
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
    expect(host.querySelector(".coll-grid-status")?.textContent).toBe("Couldn't restore purchases.");
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

  it("a refund while the Lamb is selected moves it to Coming soon, where the store cannot sell", async () => {
    authState.current = { status: "in", clientId: "cid", user: owner };
    await draw();
    await openTile(".coll-yours", 4);
    expect(title()).toBe("Spring Lamb");
    // a refresh brings the account back without the Lamb
    authState.current = { status: "in", clientId: "cid", user: { ...owner, products: [], looks: tractorLooks } };
    await draw();
    expect(title()).toBe("Coming soon");
    expect(host.querySelector(".char-stage svg.cmp-lamb")).not.toBeNull();
    expect(names(".coll-yours")).toEqual(FREE_TILES);
    expect(host.querySelector(".coll-soon .coll-tile.selected")?.textContent).toBe("Spring Lamb");
  });

  it("an account switch while the Lamb is selected shows it as Coming soon, never as the new account's own", async () => {
    authState.current = { status: "in", clientId: "cid", user: owner };
    await draw();
    await openTile(".coll-yours", 4);
    authState.current = { status: "in", clientId: "cid", user: { ...user, email: "mei@x", features: { collection: true },
      products: [], looks: tractorLooks } };
    await draw();
    // the Lamb is not hers: never her Use, only Coming soon
    expect(title()).toBe("Coming soon");
    expect(host.querySelector(".char-page .coll-use, .char-swatches")).toBeNull();
    authState.current = { status: "out", clientId: "cid", user: null };
    await draw();
    expect(title()).toBe("Coming soon");
    expect(host.querySelector(".char-page .coll-use, .char-swatches")).toBeNull();
  });

  it("the store turning off while a store character is selected shows it as Coming soon, with no price", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 1);
    expect(title()).toBe("Baby Panda");
    expect(host.querySelector(".coll-use.gold")?.textContent).toBe("Buy $3.99");
    authState.current = { status: "in", clientId: "cid", user: { ...user, features: { collection: true } } };
    await draw();
    expect(title()).toBe("Coming soon");
    expect(host.querySelector(".char-stage svg.cmp-panda")).not.toBeNull();
    expect(host.querySelector(".coll-more, .coll-use, .store-price")).toBeNull();
    // and a Soon page turns Coming soon with the store too
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 2);
    expect(title()).toBe("Jade Rabbit");
    authState.current = { status: "in", clientId: "cid", user: { ...user, features: { collection: true } } };
    await draw();
    expect(title()).toBe("Coming soon");
    expect(host.querySelector(".char-stage svg.cmp-rabbit")).not.toBeNull();
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

  it("selects it as Coming soon once the store's check says no", async () => {
    nativeShell();
    plugin.storefront.mockImplementation(later("CHN"));
    window.history.replaceState(null, "", "/#/collection/rabbit");
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(window.location.hash).toBe("#/collection/rabbit");
    expect(title()).toBe("Tractor");
    await wait(220);
    expect(title()).toBe("Coming soon");
    expect(host.querySelector(".char-stage svg.cmp-rabbit")).not.toBeNull();
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

describe("an address the viewer cannot follow", () => {
  it("with Bun selected, a link to no character gives the stage back to the one in use", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-yours", 1);
    expect(onStage()).toBe("Bun");
    await act(async () => {
      window.history.replaceState(null, "", "/#/collection/unicorn");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await settle();
    expect(window.location.hash).toBe("#/collection");
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Tractor · Icon red");
    expect(host.querySelector(".coll-yours .coll-tile.selected")?.textContent).toBe("Tractor");
  });
});

describe("each store answer on its own line", () => {
  const announcements = () => [...host.querySelectorAll("[role=status]")].map((s) => s.textContent).filter(Boolean);
  const refused = () => {
    globalThis.fetch = vi.fn(async () => ({ status: 409, json: async () => ({ detail: "held_by_other" }) }) as Response) as unknown as typeof fetch;
  };
  const FAILED = HELD;

  it("a refused purchase is said once, on the stage, and not under Restore purchases", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 0);
    refused();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    await settle();
    expect(announcements().filter((s) => s === FAILED)).toHaveLength(1);
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe(FAILED);
    expect(host.querySelector(".coll-grid-status")?.textContent).toBe("");
  });

  it("a purchase answered after the selection moved is not said on the new stage", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 0);
    let answer: (v: unknown) => void = () => {};
    plugin.purchase.mockImplementationOnce(() => new Promise((r) => { answer = r; }) as never);
    refused();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
    await openTile(".coll-yours", 1);
    await act(async () => { answer({ status: "purchased", jws: "header.payload.sig", productId: LAMB }); });
    await settle();
    expect(announcements()).not.toContain(FAILED);
    expect(onStage()).toBe("Bun");
  });

  it("a failed restore is said once, under Restore purchases, and not on the stage", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 0);
    plugin.restore.mockImplementationOnce(async () => { throw new Error("offline"); });
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-restore")!.click(); });
    await settle();
    const said = announcements().filter((s) => s !== "Spring Lamb · New Year");
    expect(said).toHaveLength(1);
    expect(host.querySelector(".coll-grid-status")?.textContent).toBe(said[0]);
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Spring Lamb · New Year");
  });
});

describe("Coming soon, where the store cannot sell", () => {
  const STORE_SEVEN = ["Spring Lamb", "Baby Panda", "Jade Rabbit", "Lucky Cat", "Fortune Fox", "Dancing Lion", "Little Dragon"];
  const noStore: AuthUser = { ...user, features: { collection: true } };
  const sections = () => [...host.querySelectorAll(".coll-section")].map((h) => h.textContent);
  const stageKind = () => [...(host.querySelector(".char-stage svg.cmp")?.classList ?? [])]
    .find((c) => /^cmp-(tractor|bun|chick|sparrow|lamb|panda|rabbit|cat|fox|lion|dragon)$/.test(c));
  /** No price, no buy, no store wording anywhere on the page. */
  const sellsNothing = () => {
    const text = host.textContent ?? "";
    expect(text).not.toMatch(/\$|¥|Buy|Shop|Restore|购买|商店/);
    expect(host.querySelector(".coll-use.gold, .store-price, .coll-restore, .coll-more")).toBeNull();
  };

  it("an account the store is off for sees the seven store characters under Yours, muted, with no price and no buy", async () => {
    authState.current = { status: "in", clientId: "cid", user: noStore };
    await draw();
    expect(sections()).toEqual(["Yours", "Coming soon"]);
    expect(names(".coll-yours")).toEqual(FREE_TILES);
    expect(names(".coll-soon")).toEqual(STORE_SEVEN);
    expect([...host.querySelectorAll(".coll-soon .coll-tile")].every((b) => b.classList.contains("dim"))).toBe(true);
    sellsNothing();
  });

  it("so do a website guest (with Get the app), a guest in the app, and the China mainland storefront", async () => {
    await draw();
    expect(names(".coll-soon")).toEqual(STORE_SEVEN);
    expect(host.querySelector(".coll-get-app")).not.toBeNull();
    nativeShell();
    await draw();
    expect(names(".coll-soon")).toEqual(STORE_SEVEN);
    plugin.storefront.mockImplementation(async () => ({ countryCode: "CHN" }));
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(names(".coll-soon")).toEqual(STORE_SEVEN);
    sellsNothing();
  });

  it("an account the store sells to keeps More companions and has no Coming soon; the store off, Coming soon takes its place", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(sections()).toEqual(["Yours", "More companions"]);
    expect(host.querySelector(".coll-soon")).toBeNull();
    authState.current = { status: "in", clientId: "cid", user: noStore };
    await draw();
    expect(sections()).toEqual(["Yours", "Coming soon"]);
  });

  it("a character owned stays in Yours, not in Coming soon", async () => {
    authState.current = { status: "in", clientId: "cid", user: { ...noStore, products: [LAMB],
      looks: [...tractorLooks, ...lambLooks(true)] } };
    await draw();
    expect(names(".coll-yours")).toEqual([...FREE_TILES, "Spring Lamb"]);
    expect(names(".coll-soon")).toEqual(STORE_SEVEN.slice(1));
  });

  it("a Coming soon tile puts the character live on the stage with the one status line Coming soon and no button", async () => {
    authState.current = { status: "in", clientId: "cid", user: noStore };
    await draw();
    await openTile(".coll-soon", 0);
    expect(stageKind()).toBe("cmp-lamb");
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Coming soon");
    expect(host.querySelectorAll(".char-page [role=status]")).toHaveLength(1);
    expect(host.querySelector(".char-page .coll-use, .char-move, .char-swatches")).toBeNull();
    expect(host.querySelectorAll(".coll-soon .coll-tile")[0].classList.contains("selected")).toBe(true);
    await openTile(".coll-soon", 4);
    expect(stageKind()).toBe("cmp-fox");
    // a tap on the figure plays its special
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-figure")!.click(); });
    expect(host.querySelector(".char-stage svg.cmp-react")).not.toBeNull();
    sellsNothing();
    expect(plugin.purchase).not.toHaveBeenCalled();
  });

  it("a link to a store character opens it on the stage as Coming soon", async () => {
    window.history.replaceState(null, "", "/#/collection/panda");
    authState.current = { status: "in", clientId: "cid", user: noStore };
    await draw();
    expect(stageKind()).toBe("cmp-panda");
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Coming soon");
    expect(window.location.hash).toBe("#/collection");
  });

  it("reads in Chinese", async () => {
    setLanguageChoice("zh-Hans");
    try {
      await draw();
      expect(sections()).toEqual(["我的", "即将推出"]);
      expect(names(".coll-soon")).toEqual(["小羊", "熊猫宝宝", "玉兔", "招财猫", "福狐", "醒狮", "小龙"]);
      await openTile(".coll-soon", 3);
      expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("即将推出");
      setLanguageChoice("zh-Hant");
      await draw();
      expect(sections()).toEqual(["我的", "即將推出"]);
      expect(names(".coll-soon")).toEqual(["小羊", "熊貓寶寶", "玉兔", "招財貓", "福狐", "醒獅", "小龍"]);
    } finally {
      setLanguageChoice("system");
    }
  });
});

describe("a refusal in plain words", () => {
  const LOCALES: Locale[] = ["en", "zh-Hans", "zh-Hant"];
  const refusal = (reason: string | undefined, status = 409) => Object.assign(new Error("verify"), { status, ...(reason ? { reason } : {}) });
  const copy = (loc: Locale, err: unknown, during: "buy" | "restore") => {
    const key = refusalMessage(err, during);
    return key === null ? null : tIn(loc, key);
  };

  it("says each server refusal in every language", () => {
    const want: Record<string, [string, string, string]> = {
      held_by_other: [HELD, "此 Apple ID 已为另一个账号购买，请登录该账号使用。", "此 Apple ID 已為另一個帳號購買，請登入該帳號使用。"],
      revoked: ["This purchase was refunded.", "这笔购买已退款。", "這筆購買已退款。"],
      wrong_app: ["Couldn't complete the purchase.", "购买未能完成。", "購買未能完成。"],
    };
    for (const [code, lines] of Object.entries(want)) {
      LOCALES.forEach((loc, i) => expect(copy(loc, refusal(code), "buy")).toBe(lines[i]));
    }
    // anything else, a network failure or a 5xx among them, is the generic line
    for (const err of [refusal("unknown_token"), refusal("storefront", 403), refusal(undefined, 503), refusal(undefined, 0), new Error("offline"),
      refusal("Too many requests; try again in a minute.", 429)]) {
      LOCALES.forEach((loc, i) => expect(copy(loc, err, "buy")).toBe(want.wrong_app[i]));
      LOCALES.forEach((loc, i) => expect(copy(loc, err, "restore")).toBe(["Couldn't restore purchases.", "未能恢复购买。", "未能恢復購買。"][i]));
    }
    // no session to buy with: the sign-in flow, not a line
    expect(refusalMessage(refusal("sign_in_required"), "buy")).toBeNull();
    expect(refusalMessage(refusal("Not signed in.", 401), "restore")).toBeNull();
  });

  it("a purchase the server needs a sign-in for opens sign-in and says no line", async () => {
    const { guestName } = await import("../guestName");
    const open = vi.spyOn(guestName, "open").mockImplementation(() => {});
    try {
      nativeShell();
      authState.current = { status: "in", clientId: "cid", user };
      globalThis.fetch = vi.fn(async (url: string) => (url === "/api/store/verify"
        ? { status: 409, json: async () => ({ detail: "sign_in_required" }) }
        : { status: 200, json: async () => authState.current.user }) as Response) as unknown as typeof fetch;
      await draw();
      await openTile(".coll-more", 0);
      await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")!.click(); });
      await settle();
      expect(open).toHaveBeenCalledWith("shop");
      expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Spring Lamb · New Year");
    } finally {
      open.mockRestore();
    }
  });

  it("a restore whose purchases another account holds says where they are, under Restore purchases", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    globalThis.fetch = vi.fn(async (url: string) => (url === "/api/store/verify"
      ? { status: 409, json: async () => ({ detail: "held_by_other" }) }
      : { status: 200, json: async () => authState.current.user }) as Response) as unknown as typeof fetch;
    plugin.restore.mockImplementationOnce(async () => ({ transactions: [{ jws: "taken.jws.sig", productId: LAMB, transactionId: "71" }] }));
    await draw();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-restore")!.click(); });
    await settle();
    await settle();
    expect(host.querySelector(".coll-grid-status")?.textContent).toBe(HELD);
    // settled: acknowledged, never handed over again
    expect(plugin.finish).toHaveBeenCalledWith({ transactionId: "71" });
  });

  it("a double tap on Buy opens Apple's sheet once", async () => {
    nativeShell();
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    await openTile(".coll-more", 0);
    let pay!: (v: unknown) => void;
    plugin.purchase.mockImplementationOnce(() => new Promise((r) => { pay = r; }) as never);
    const button = host.querySelector<HTMLButtonElement>(".coll-use.gold")!;
    await act(async () => { button.click(); button.click(); });
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")?.click(); });
    expect(plugin.purchase).toHaveBeenCalledTimes(1);
    await act(async () => { pay({ status: "cancelled" }); });
    await settle();
  });

  it("never shows a raw code on the store's status lines", async () => {
    const codes: [string | undefined, number][] = [["held_by_other", 409], ["revoked", 409], ["wrong_app", 409], ["unknown_token", 409],
      ["storefront", 403], ["bad_signature", 400], [undefined, 503], ["Too many requests; try again in a minute.", 429]];
    const lines = () => [...host.querySelectorAll(".coll-status")].map((s) => s.textContent ?? "");
    try {
      for (const loc of LOCALES) {
        setLanguageChoice(loc);
        for (const [reason, status] of codes) {
          nativeShell();
          authState.current = { status: "in", clientId: "cid", user };
          globalThis.fetch = vi.fn(async (url: string) => (url === "/api/store/verify"
            ? { status, json: async () => (reason ? { detail: reason } : {}) }
            : { status: 200, json: async () => authState.current.user }) as Response) as unknown as typeof fetch;
          plugin.restore.mockImplementationOnce(async () => ({ transactions: [{ jws: "r.j.s", productId: LAMB }] }));
          await draw();
          await act(async () => { host.querySelector<HTMLButtonElement>(".coll-restore")!.click(); });
          await settle();
          await openTile(".coll-more", 0);
          await act(async () => { host.querySelector<HTMLButtonElement>(".coll-use.gold")?.click(); });
          await settle();
          await settle();
          const said = lines();
          expect(said.join("|")).not.toMatch(/\([a-z_0-9]+\)|（[a-z_0-9]+）/i);
          for (const s of said) {
            expect(s).not.toMatch(/held_by_other|revoked|wrong_app|unknown_token|storefront|bad_signature|503|Too many/);
          }
          act(() => root.unmount());
          root = createRoot(host);
        }
      }
    } finally {
      setLanguageChoice("system");
    }
  });
});
