// The Collection as one page: a tile selects its character into the stage at
// the top, in place, with no page and no history entry of its own; the
// colours and the one button under the stage follow the selection; a link to
// `#/collection/<kind>` selects that character and leaves the plain address.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState, AuthUser } from "../auth";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import CollectionPage from "./CollectionPage";
import { forgetHomeSession } from "../home/session";
import { guestLookFor, lookCatalogue } from "../companion/look";
import { setLanguageChoice } from "../i18n";

/** The name line of a look in English, as the stage writes it. */
const lookNameEn = (id: string) => {
  const [kind, colour] = id.split("/");
  return `${kind[0].toUpperCase()}${kind.slice(1)} · ${colour[0].toUpperCase()}${colour.slice(1)}`;
};

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const puts: unknown[] = [];
const user: AuthUser = {
  name: "Jerry Yu", email: "j@x", picture: null, display_name: null, name_shown: "Jerry",
  rounds_played: 3, ranked_wins: 0, look: "tractor/red", companions: "individual", features: { collection: true },
};
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  forgetHomeSession();
  window.history.replaceState(null, "", "/#/collection");
  puts.length = 0;
  globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}"));
    if (url === "/api/me/look") puts.push(body);
    return { status: 200, json: async () => ({ ...user, ...body }) } as Response;
  }) as unknown as typeof fetch;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  authState.current = { status: "out", clientId: "cid", user: null };
  window.history.replaceState(null, "", "/");
});
const draw = async () => {
  await act(async () => { root.render(<CollectionPage />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
};
const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-tile")]
  .find((b) => b.querySelector(".coll-tile-name")!.textContent === name)!;
const stageKind = () => [...(host.querySelector(".char-stage svg.cmp")?.classList ?? [])]
  .find((c) => /^cmp-(tractor|bun|chick|sparrow|lamb|panda|rabbit|cat|fox|lion|dragon)$/.test(c));
const swatchNames = () => [...host.querySelectorAll(".char-swatches .coll-swatch")].map((s) => s.getAttribute("aria-label"));

describe("one page", () => {
  it("the stage shows the one in use; a tile selects its character into it, in place", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(stageKind()).toBe("cmp-tractor");
    expect(tile("Tractor").classList.contains("selected")).toBe(true);
    const entries = window.history.length;
    await act(async () => { tile("Bun").click(); });
    expect(stageKind()).toBe("cmp-bun");
    expect(host.querySelector(".large-title")?.textContent).toBe("Collection");      // no page of its own
    expect(window.location.hash).toBe("#/collection");
    expect(window.history.length).toBe(entries);                                      // and no history entry
    expect(tile("Bun").classList.contains("selected")).toBe(true);
    expect(tile("Tractor").classList.contains("selected")).toBe(false);
    expect(tile("Tractor").querySelector(".coll-tick")).not.toBeNull();             // the one in use keeps its tick
    expect(host.querySelector(".coll-back, .edge-swipe")).toBeNull();
    // the grid stays under the stage
    expect(host.querySelector(".coll-yours")).not.toBeNull();
  });

  it("the colours, the status line and the one button follow the selection; Use puts the selected look in use", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(swatchNames()[0]).toBe("Icon red");
    await act(async () => { tile("Chick").click(); });
    expect(swatchNames()).toHaveLength(4);
    expect(swatchNames()[0]).toMatch(/^Chick yellow/);
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Chick · Chick yellow");
    const use = host.querySelector<HTMLButtonElement>(".coll-use")!;
    expect(use.textContent).toBe("Use");
    await act(async () => { use.click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(puts).toEqual([{ look: "chick/yellow" }]);
  });

  it("a link to a character selects it and leaves the plain address, with no history entry", async () => {
    window.history.replaceState(null, "", "/#/collection/sparrow");
    const entries = window.history.length;
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(stageKind()).toBe("cmp-sparrow");
    expect(window.location.hash).toBe("#/collection");
    expect(window.history.length).toBe(entries);
  });

  it("the tiles stand still and only the stage moves; a tapped tile hops once and rests again", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const figures = [...host.querySelectorAll(".coll-tile svg.cmp")];
    expect(figures.length).toBeGreaterThan(1);
    for (const f of figures) expect(f.classList.contains("cmp-rest")).toBe(true);
    expect(host.querySelector(".char-stage svg.cmp")!.classList.contains("cmp-rest")).toBe(false);
    await act(async () => { tile("Bun").click(); });
    const hopping = tile("Bun").querySelector("svg.cmp")!;
    expect(hopping.getAttribute("data-pose")).toBe("hop");
    expect(hopping.classList.contains("cmp-rest")).toBe(false);
    const ended = "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd";
    await act(async () => { hopping.querySelector(".cmp-body")!.dispatchEvent(new Event(ended, { bubbles: true })); });
    const after = tile("Bun").querySelector("svg.cmp")!;
    expect(after.getAttribute("data-pose")).toBe("idle");
    expect(after.classList.contains("cmp-rest")).toBe(true);
  });

  it("on a phone a selection scrolls the page back up to the stage", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const page = host.querySelector<HTMLElement>(".coll-page")!;
    const to = vi.fn();
    page.scrollTo = to as never;
    Object.defineProperty(page, "scrollTop", { value: 420, configurable: true });
    await act(async () => { tile("Sparrow").click(); });
    expect(to).toHaveBeenCalledWith({ top: 0, behavior: "smooth" });
  });
});

describe("the stage's line and button", () => {
  it("a locked colour says what unlocks it on the status line; the button stays Use, inert, at its size", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    const swatch = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".char-swatches .coll-swatch")]
      .find((s) => s.getAttribute("aria-label")!.startsWith(name))!;
    await act(async () => { swatch("Imperial yellow").click(); });
    expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("Win 10 ranked rounds to unlock · 0 of 10");
    const use = host.querySelector<HTMLButtonElement>(".coll-use")!;
    expect(use.textContent).toBe("Use");
    expect(use.disabled).toBe(true);
  });

  it("a colour named as its companion is named once (麻雀, not 麻雀 · 麻雀)", async () => {
    const { setLanguageChoice } = await import("../i18n/locale");
    setLanguageChoice("zh-Hans");
    try {
      authState.current = { status: "in", clientId: "cid", user: { ...user, look: "sparrow/tree" } };
      await draw();
      expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("麻雀");
      const swatch = [...host.querySelectorAll<HTMLButtonElement>(".char-swatches .coll-swatch")][1];
      await act(async () => { swatch.click(); });
      expect(host.querySelector(".char-page .coll-status")?.textContent).toBe("麻雀 · 文鸟灰");
    } finally {
      setLanguageChoice("system");
    }
  });
});

const names = () => [...host.querySelectorAll(".coll-yours .coll-tile-name")].map((n) => n.textContent);

describe("Yours", () => {
  it("is ordered by last use: the one in use first, then the latest used, then the rest in Collection order", async () => {
    authState.current = { status: "in", clientId: "cid",
      user: { ...user, look: "chick/ink", recent_looks: ["sparrow/java", "chick/ink", "bun/taro", "sparrow/tree"] } };
    await draw();
    expect(names()).toEqual(["Chick", "Sparrow", "Bun", "Tractor"]);
    expect(tile("Chick").querySelector(".coll-tick")).not.toBeNull();
  });

  it("keeps Collection order for an account that has used nothing, the one in use first", async () => {
    authState.current = { status: "in", clientId: "cid", user: { ...user, look: "sparrow/snow" } };
    await draw();
    expect(names()).toEqual(["Sparrow", "Tractor", "Bun", "Chick"]);
  });
});

describe("a guest", () => {
  it("wears the free look its device key draws, the same on every visit", async () => {
    window.localStorage.setItem("shengji.device", "AAAAAAAAAAAAAAAAAAAAAA");    // draws bun/plain
    await draw();
    expect(stageKind()).toBe("cmp-bun");
    expect(tile("Bun").querySelector(".coll-tick")).not.toBeNull();
    act(() => root.unmount());
    root = createRoot(host);
    await draw();
    expect(stageKind()).toBe("cmp-bun");
    expect(window.localStorage.getItem("shengji.device")).toBe("AAAAAAAAAAAAAAAAAAAAAA");
  });

  it("is given a device key, and so a look, on a first visit", async () => {
    window.localStorage.removeItem("shengji.device");
    await draw();
    const key = window.localStorage.getItem("shengji.device")!;
    expect(key).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(stageKind()).toBe(`cmp-${guestLookFor(key).split("/")[0]}`);
    expect(host.querySelectorAll(".coll-yours .coll-tick")).toHaveLength(1);
  });
});

describe("the stage's one line says how an owned look was got", () => {
  const LAMB = "com.jerryyu.shengji.companion.lamb";
  const tractor = lookCatalogue({ ranked_wins: 30 }, "tractor/red");
  const lambOwned = ["newyear", "jade", "ink", "lacquer"].map((c) => ({ id: `lamb/${c}`, unlocked: true, needs: null, product: LAMB }));
  const signIn = (over: Partial<AuthUser>) => {
    authState.current = { status: "in", clientId: "cid", user: { ...user, ranked_wins: 30, looks: [...tractor, ...lambOwned], ...over } };
  };
  const line = () => {
    const lines = host.querySelectorAll(".char-page .coll-status");
    expect(lines).toHaveLength(1);                   // the copy rule: one status line, never a second
    return lines[0].textContent;
  };
  const button = () => host.querySelector(".char-page .coll-use")?.textContent;
  afterEach(() => setLanguageChoice("system"));

  it("a Tractor colour won: the count that unlocked it, worn or only shown; the button is unchanged", async () => {
    signIn({ look: "tractor/orange" });
    await draw();
    expect(line()).toBe("Unlocked with 25 ranked rounds won");
    expect(button()).toBe("In use");
    signIn({ look: "tractor/red" });
    await draw();
    await act(async () => { host.querySelector<HTMLButtonElement>('.char-swatches [aria-label^="Lantern orange"]')!.click(); });
    expect(line()).toBe("Unlocked with 25 ranked rounds won");
    expect(button()).toBe("Use");
  });

  it("a colour still locked keeps what unlocks it", async () => {
    signIn({ look: "tractor/red" });
    await draw();
    await act(async () => { host.querySelector<HTMLButtonElement>('.char-swatches [aria-label^="Jade"]')!.click(); });
    expect(line()).toBe("Win 50 ranked rounds to unlock · 30 of 50");
  });

  it("a purchase: the date it was bought, in the viewer's own date format", async () => {
    signIn({ look: "lamb/ink", products: [LAMB], purchased_on: { [LAMB]: "2026-11-27" } });
    await draw();
    const date = new Date(2026, 10, 27).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    expect(line()).toBe(`Purchased ${date}`);
    expect(line()).toMatch(/27/);
    expect(button()).toBe("In use");
  });

  it("a look free from the start, and one kept from before its count, name the look: no Free", async () => {
    signIn({ look: "bun/plain" });
    await draw();
    expect(line()).toBe(lookNameEn("bun/plain"));
    expect(line()).not.toMatch(/Free|Unlocked|Purchased/);
    signIn({ look: "tractor/jade", ranked_wins: 3, looks: lookCatalogue({ ranked_wins: 3 }, "tractor/jade") });
    await draw();
    expect(line()).not.toMatch(/Unlocked/);
  });

  it("reads in Simplified and Traditional Chinese", async () => {
    for (const [lang, won, bought] of [
      ["zh-Hans", "赢 25 局排位解锁", "2026年11月27日购买"],
      ["zh-Hant", "贏 25 局排位解鎖", "2026年11月27日購買"],
    ] as const) {
      setLanguageChoice(lang);
      signIn({ look: "tractor/orange" });
      await draw();
      expect(line()).toBe(won);
      signIn({ look: "lamb/ink", products: [LAMB], purchased_on: { [LAMB]: "2026-11-27" } });
      await draw();
      expect(line()).toBe(bought);
    }
  });
});

describe("the stage's move chips", () => {
  const row = () => [...host.querySelectorAll(".char-page .char-poses > *")].map((c) => c.textContent);

  it("are one row of four: labels only, and still one status line", async () => {
    authState.current = { status: "in", clientId: "cid", user };
    await draw();
    expect(row()).toEqual(["Hop", "Cheer", "Big play", "Wheelie"]);
    expect([...host.querySelectorAll(".char-page .char-poses > *")].every((c) => c.tagName === "BUTTON")).toBe(true);
    expect(host.querySelectorAll(".char-page .coll-status")).toHaveLength(1);
    expect(host.querySelectorAll(".char-page p")).toHaveLength(1);          // no sentence under the chips
    await act(async () => { tile("Chick").click(); });
    expect(row()).toEqual(["Hop", "Cheer", "Big play", "Flutter"]);
    await act(async () => { tile("Sparrow").click(); });
    expect(row()[3]).toBe("Loop");
    expect(host.querySelector(".char-chip")).toBeNull();               // Try on your table is gone
  });

  it("read in Simplified and Traditional Chinese", async () => {
    for (const [lang, names] of [
      ["zh-Hans", ["跳一跳", "欢呼", "大牌", "出笼"]],
      ["zh-Hant", ["跳一跳", "歡呼", "大牌", "出籠"]],
    ] as const) {
      setLanguageChoice(lang);
      authState.current = { status: "in", clientId: "cid", user: { ...user, look: "bun/plain" } };
      await draw();
      expect(row()).toEqual(names);
    }
    setLanguageChoice("system");
  });
});
